"""Dhan client with a mocked transport (no network, no real credentials)."""
import json

import httpx
import pytest

from app.integrations.dhan_client import (
    ALLOWED_ENDPOINTS,
    DhanClient,
    DhanCredentials,
    DhanError,
    DhanStatus,
    ForbiddenEndpointError,
    RateLimiter,
)
from app.market_data.candles import parse_dhan_candles

CREDS = DhanCredentials("1000000001", "eyJhbGciOiJIUzUxMiJ9.test-token-value")


def client(handler, retries=2):
    DhanClient.data_limiter = RateLimiter(1000)
    DhanClient.quote_limiter = RateLimiter(1000)
    return DhanClient(CREDS, transport=httpx.MockTransport(handler), max_retries=retries, sleep=lambda s: None)


def test_requires_credentials():
    with pytest.raises(DhanError) as e:
        DhanClient(DhanCredentials("", ""))
    assert e.value.status == DhanStatus.NOT_CONFIGURED


@pytest.mark.parametrize("path", ["/orders", "/super/orders", "/forever/orders", "/positions/convert", "/killswitch", "/edis/form", "/margincalculator", "/fundlimit"])
def test_order_and_account_endpoints_forbidden(path):
    c = client(lambda r: httpx.Response(200, json={}))
    for method in ("GET", "POST", "PUT", "DELETE"):
        with pytest.raises(ForbiddenEndpointError):
            c._request(method, path, {})


def test_whitelist_contains_only_read_only_market_data():
    paths = {p for _, p in ALLOWED_ENDPOINTS}
    assert paths == {"/profile", "/charts/historical", "/charts/intraday", "/marketfeed/ltp", "/marketfeed/ohlc", "/marketfeed/quote"}
    assert not any("order" in p for p in paths)


def test_headers_and_payload_for_intraday():
    seen = {}

    def h(req: httpx.Request):
        seen["path"] = req.url.path
        seen["headers"] = dict(req.headers)
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"open": [1], "high": [2], "low": [0.5], "close": [1.5], "volume": [10], "timestamp": [1700000000]})

    body = client(h).intraday("1333", 5, "2026-10-20 09:15:00", "2026-10-23 15:30:00")
    assert seen["path"] == "/v2/charts/intraday"
    assert seen["headers"]["access-token"] == CREDS.access_token and seen["headers"]["client-id"] == CREDS.client_id
    assert seen["body"]["interval"] == "5" and seen["body"]["exchangeSegment"] == "NSE_EQ"
    assert parse_dhan_candles(body)[0].close == 1.5


def test_unsupported_interval():
    with pytest.raises(ValueError):
        client(lambda r: httpx.Response(200, json={})).intraday("1", 240, "a", "b")


@pytest.mark.parametrize("status,body,expected", [
    (401, {"errorCode": "DH-901", "errorMessage": "Invalid token"}, DhanStatus.AUTH_FAILED),
    (403, {"errorCode": "DH-902", "errorMessage": "No data subscription"}, DhanStatus.PERMISSION_DENIED),
    (400, {"errorCode": "DH-905", "errorMessage": "bad"}, DhanStatus.INVALID_REQUEST),
    (400, {"errorCode": "DH-907", "errorMessage": "no data"}, DhanStatus.MARKET_DATA_UNAVAILABLE),
])
def test_error_classification(status, body, expected):
    with pytest.raises(DhanError) as e:
        client(lambda r: httpx.Response(status, json=body)).profile()
    assert e.value.status == expected


def test_rate_limit_retries_with_backoff_then_succeeds():
    calls = {"n": 0}
    sleeps = []

    def h(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, json={"errorCode": "DH-904", "errorMessage": "Too many requests"})
        return httpx.Response(200, json={"dhanClientId": "1000000001"})

    c = client(h, retries=3)
    c._sleep = sleeps.append
    assert c.profile()["dhanClientId"] == "1000000001"
    assert calls["n"] == 3 and sleeps == [0.5, 1.0]


def test_rate_limit_exhausted():
    with pytest.raises(DhanError) as e:
        client(lambda r: httpx.Response(429, json={"errorCode": "DH-904"}), retries=1).profile()
    assert e.value.status == DhanStatus.RATE_LIMITED


def test_network_error():
    def h(req):
        raise httpx.ConnectError("boom")

    with pytest.raises(DhanError) as e:
        client(h, retries=1).profile()
    assert e.value.status == DhanStatus.NETWORK_ERROR


def test_ohlc_batches_of_1000():
    batches = []

    def h(req):
        body = json.loads(req.content)
        ids = body["NSE_EQ"]
        batches.append(len(ids))
        return httpx.Response(200, json={"data": {"NSE_EQ": {str(i): {"last_price": 10.0, "ohlc": {"close": 9.5}} for i in ids}}, "status": "success"})

    out = client(h).ohlc([str(i) for i in range(1, 1501)])
    assert batches == [1000, 500] and len(out) == 1500


def test_malformed_candles_are_dropped():
    from app.market_data.candles import validate_candles

    cs = parse_dhan_candles({"open": [1, 1, 5], "high": [2, 0.5, 6], "low": [0.5, 0.4, 4], "close": [1.5, 0.45, 5.5], "timestamp": [1, 2, 2]})
    clean, warnings = validate_candles(cs)
    assert [c.ts for c in clean] == [1.0, 2.0] and clean[1].open == 5 and any("malformed" in w for w in warnings)
