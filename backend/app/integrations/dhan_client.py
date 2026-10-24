"""Read-only DhanHQ v2 REST client.

PAPER TRADING ONLY. This client can reach exactly the endpoints listed in
``ALLOWED_ENDPOINTS`` (profile check, historical/intraday candles and market-feed
snapshots). Every request is checked against that whitelist before it is sent; any
other path - including every order, super-order, forever-order, position-conversion,
kill-switch or eDIS endpoint - raises ``ForbiddenEndpointError``. The official
``dhanhq`` SDK is deliberately NOT used because it bundles order-placement methods.

Endpoint shapes were verified against the official ``dhanhq`` 2.3.0 SDK source
(``_historical_data.py``, ``_market_feed.py``, ``auth.py``, ``_security.py``).
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx

log = logging.getLogger(__name__)

API_BASE_URL = "https://api.dhan.co/v2"
SCRIP_MASTER_COMPACT_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
SCRIP_MASTER_DETAILED_URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"

# (method, path) pairs this application may call. Nothing else.
ALLOWED_ENDPOINTS: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/profile"),
        ("POST", "/charts/historical"),
        ("POST", "/charts/intraday"),
        ("POST", "/marketfeed/ltp"),
        ("POST", "/marketfeed/ohlc"),
        ("POST", "/marketfeed/quote"),
    }
)

INTRADAY_INTERVALS = (1, 5, 15, 25, 60)  # minutes supported by /charts/intraday
QUOTE_BATCH_LIMIT = 1000  # instruments per marketfeed request


class ForbiddenEndpointError(RuntimeError):
    """Raised when code attempts to call a non-whitelisted (e.g. order) endpoint."""


class DhanStatus:
    NOT_CONFIGURED = "NOT_CONFIGURED"
    CONNECTED = "CONNECTED"
    AUTH_FAILED = "AUTH_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RATE_LIMITED = "RATE_LIMITED"
    NETWORK_ERROR = "NETWORK_ERROR"
    MARKET_DATA_UNAVAILABLE = "MARKET_DATA_UNAVAILABLE"
    INVALID_REQUEST = "INVALID_REQUEST"
    ERROR = "ERROR"


class DhanError(Exception):
    def __init__(self, status: str, message: str, http_status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.http_status = http_status
        self.code = code

    def to_dict(self) -> dict:
        return {"status": self.status, "message": self.message, "http_status": self.http_status, "code": self.code}


def classify_error(http_status: int | None, body: Any) -> DhanError:
    code = None
    msg = ""
    if isinstance(body, dict):
        code = body.get("errorCode") or body.get("error_code")
        msg = str(body.get("errorMessage") or body.get("message") or body.get("remarks") or "")
    msg = msg or (str(body)[:300] if body else f"HTTP {http_status}")
    # Dhan error codes are more specific than HTTP status, so they are checked first.
    by_code = {
        "DH-901": (DhanStatus.AUTH_FAILED, "Invalid or expired access token"),
        "DH-902": (DhanStatus.PERMISSION_DENIED, "Not subscribed to Data APIs / no access"),
        "DH-904": (DhanStatus.RATE_LIMITED, "Rate limit exceeded"),
        "DH-905": (DhanStatus.INVALID_REQUEST, "Invalid request"),
        "DH-907": (DhanStatus.MARKET_DATA_UNAVAILABLE, "No data available"),
    }
    if code in by_code:
        st, default = by_code[code]
        return DhanError(st, msg or default, http_status, code)
    if http_status == 401:
        return DhanError(DhanStatus.AUTH_FAILED, msg, http_status, code)
    if http_status == 403:
        return DhanError(DhanStatus.PERMISSION_DENIED, msg, http_status, code)
    if http_status == 429:
        return DhanError(DhanStatus.RATE_LIMITED, msg, http_status, code)
    if http_status == 400:
        return DhanError(DhanStatus.INVALID_REQUEST, msg, http_status, code)
    return DhanError(DhanStatus.ERROR, msg, http_status, code)


class RateLimiter:
    """Simple thread-safe minimum-interval limiter."""

    def __init__(self, per_second: float):
        self.interval = 1.0 / per_second
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            time.sleep(delay)


@dataclass
class DhanCredentials:
    client_id: str
    access_token: str


class DhanClient:
    # Dhan documents ~5 req/s for Data APIs and 1 req/s for Market Quote APIs.
    # We stay slightly below to leave headroom.
    data_limiter = RateLimiter(4.0)
    quote_limiter = RateLimiter(1.0)

    def __init__(
        self,
        creds: DhanCredentials,
        *,
        timeout: float = 20.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not creds.client_id or not creds.access_token:
            raise DhanError(DhanStatus.NOT_CONFIGURED, "Dhan Client ID and Access Token are required")
        self.creds = creds
        self.max_retries = max_retries
        self._sleep = sleep
        self._http = httpx.Client(base_url=API_BASE_URL, timeout=timeout, transport=transport)

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------ core
    def _headers(self) -> dict[str, str]:
        return {
            "access-token": self.creds.access_token,
            "client-id": self.creds.client_id,
            "dhanClientId": self.creds.client_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @staticmethod
    def assert_allowed(method: str, path: str) -> None:
        if (method.upper(), path) not in ALLOWED_ENDPOINTS:
            raise ForbiddenEndpointError(
                f"{method} {path} is not a whitelisted read-only market-data endpoint. "
                "This application is PAPER TRADING ONLY and never calls broker order endpoints."
            )

    def _request(self, method: str, path: str, payload: dict | None = None, limiter: RateLimiter | None = None) -> Any:
        self.assert_allowed(method, path)
        limiter = limiter or self.data_limiter
        last_err: DhanError | None = None
        for attempt in range(self.max_retries + 1):
            limiter.wait()
            try:
                resp = self._http.request(method, path, json=payload, headers=self._headers())
            except (httpx.TimeoutException, httpx.NetworkError, httpx.ProxyError) as exc:
                last_err = DhanError(DhanStatus.NETWORK_ERROR, f"{type(exc).__name__}: {exc}")
            else:
                try:
                    body = resp.json()
                except ValueError:
                    body = resp.text[:300]
                if 200 <= resp.status_code < 300:
                    if isinstance(body, dict) and body.get("status") == "failure":
                        raise classify_error(resp.status_code, body.get("remarks") or body)
                    return body
                last_err = classify_error(resp.status_code, body)
                if last_err.status not in (DhanStatus.RATE_LIMITED,) and resp.status_code < 500:
                    raise last_err
            if attempt < self.max_retries:
                backoff = 0.5 * (2**attempt)
                log.warning("Dhan %s %s failed (%s); retry %d in %.1fs", method, path, last_err.status, attempt + 1, backoff)
                self._sleep(backoff)
        assert last_err is not None
        raise last_err

    # ------------------------------------------------------------------ API
    def profile(self) -> dict:
        return self._request("GET", "/profile")

    def historical_daily(self, security_id: str, from_date: str, to_date: str, segment: str = "NSE_EQ", instrument: str = "EQUITY") -> dict:
        """Daily candles. ``to_date`` is exclusive per Dhan docs. Dates: YYYY-MM-DD."""
        return self._request(
            "POST",
            "/charts/historical",
            {
                "securityId": str(security_id),
                "exchangeSegment": segment,
                "instrument": instrument,
                "expiryCode": 0,
                "oi": False,
                "fromDate": from_date,
                "toDate": to_date,
            },
        )

    def intraday(self, security_id: str, interval: int, from_dt: str, to_dt: str, segment: str = "NSE_EQ", instrument: str = "EQUITY") -> dict:
        """Intraday candles (1/5/15/25/60 min). Dhan limits a single request to 90 days."""
        if interval not in INTRADAY_INTERVALS:
            raise ValueError(f"Unsupported Dhan intraday interval {interval}; supported: {INTRADAY_INTERVALS}")
        return self._request(
            "POST",
            "/charts/intraday",
            {
                "securityId": str(security_id),
                "exchangeSegment": segment,
                "instrument": instrument,
                "interval": str(interval),
                "oi": False,
                "fromDate": from_dt,
                "toDate": to_dt,
            },
        )

    def ohlc(self, security_ids: list[str], segment: str = "NSE_EQ") -> dict[str, dict]:
        """Market-feed OHLC snapshot, batched. Returns {security_id: {last_price, ohlc{...}}}."""
        out: dict[str, dict] = {}
        for i in range(0, len(security_ids), QUOTE_BATCH_LIMIT):
            batch = [int(s) for s in security_ids[i : i + QUOTE_BATCH_LIMIT]]
            body = self._request("POST", "/marketfeed/ohlc", {segment: batch}, limiter=self.quote_limiter)
            data = (body or {}).get("data", {}) if isinstance(body, dict) else {}
            for sid, row in (data.get(segment) or {}).items():
                out[str(sid)] = row
        return out

    def ltp(self, security_ids: list[str], segment: str = "NSE_EQ") -> dict[str, dict]:
        body = self._request("POST", "/marketfeed/ltp", {segment: [int(s) for s in security_ids[:QUOTE_BATCH_LIMIT]]}, limiter=self.quote_limiter)
        data = (body or {}).get("data", {}) if isinstance(body, dict) else {}
        return {str(k): v for k, v in (data.get(segment) or {}).items()}


def download_scrip_master(url: str = SCRIP_MASTER_COMPACT_URL, timeout: float = 60.0, transport: httpx.BaseTransport | None = None) -> str:
    """Download Dhan's public instrument master CSV (no credentials required)."""
    try:
        with httpx.Client(timeout=timeout, transport=transport, follow_redirects=True) as c:
            r = c.get(url)
            r.raise_for_status()
            return r.text
    except httpx.HTTPError as exc:
        raise DhanError(DhanStatus.NETWORK_ERROR, f"Could not download Dhan scrip master: {exc}") from exc
