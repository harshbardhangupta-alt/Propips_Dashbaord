"""Credential storage, masking and genuine connection tests for Dhan and OpenAI."""
from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import mask_secret
from app.core.timeutils import iso
from app.database.models import Instrument, UniverseMember, utcnow
from app.database.repository import audit, get_setting, set_setting, setting_updated_at
from app.integrations.dhan_client import DhanClient, DhanCredentials, DhanError, DhanStatus

K_DHAN_CLIENT = "dhan_client_id"
K_DHAN_TOKEN = "dhan_access_token"
K_DHAN_STATUS = "dhan_status"
K_OPENAI_KEY = "openai_api_key"
K_OPENAI_MODEL = "openai_model"
K_OPENAI_ENABLED = "openai_enabled"
K_OPENAI_STATUS = "openai_status"
K_SCAN_AUTO = "scanner_auto_enabled"
K_SCAN_AFTER = "scanner_after_market_enabled"

TOKEN_REMINDER_HOURS = 24


def _json(db: Session, key: str) -> dict:
    raw = get_setting(db, key)
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def dhan_credentials(db: Session) -> DhanCredentials | None:
    cid = get_setting(db, K_DHAN_CLIENT)
    tok = get_setting(db, K_DHAN_TOKEN)
    if not cid or not tok:
        return None
    return DhanCredentials(cid, tok)


def get_dhan_client(db: Session) -> DhanClient:
    creds = dhan_credentials(db)
    if creds is None:
        raise DhanError(DhanStatus.NOT_CONFIGURED, "Dhan credentials are not configured (Settings & API Credentials)")
    return DhanClient(creds)


def dhan_view(db: Session) -> dict:
    cid = get_setting(db, K_DHAN_CLIENT)
    tok = get_setting(db, K_DHAN_TOKEN)
    tok_at = setting_updated_at(db, K_DHAN_TOKEN) if tok else None
    status = _json(db, K_DHAN_STATUS)
    reminder_due = bool(tok_at and utcnow() - tok_at > timedelta(hours=TOKEN_REMINDER_HOURS))
    return {
        "client_id": cid,
        "client_id_set": bool(cid),
        "access_token_masked": mask_secret(tok),
        "access_token_set": bool(tok),
        "access_token_updated_at": iso(tok_at),
        "token_reminder_due": reminder_due,
        "token_reminder_note": "Dhan access tokens generated from the web portal are typically valid for up to 24 hours. "
        "This is a reminder interval only; the real expiry is reported by Dhan's /profile (tokenValidity) when you test the connection.",
        "status": status.get("status", DhanStatus.NOT_CONFIGURED if not (cid and tok) else "UNTESTED"),
        "status_detail": status,
    }


def save_dhan(db: Session, client_id: str | None, access_token: str | None) -> None:
    if client_id is not None:
        set_setting(db, K_DHAN_CLIENT, client_id.strip())
    if access_token is not None:
        set_setting(db, K_DHAN_TOKEN, access_token.strip(), secret=True)
    # Saving credentials never implies they work: status resets to UNTESTED.
    set_setting(db, K_DHAN_STATUS, json.dumps({"status": "UNTESTED", "tested_at": None}))
    audit(db, "INFO", "settings", "Dhan credentials updated (values not logged)")


def delete_dhan(db: Session) -> None:
    for k in (K_DHAN_CLIENT, K_DHAN_TOKEN, K_DHAN_STATUS):
        set_setting(db, k, None)
    audit(db, "WARN", "settings", "Dhan credentials deleted")


def record_dhan_status(db: Session, status: str, message: str = "", extra: dict | None = None) -> dict:
    payload = {"status": status, "message": message, "tested_at": iso(utcnow()), **(extra or {})}
    set_setting(db, K_DHAN_STATUS, json.dumps(payload))
    return payload


def test_dhan(db: Session, client: DhanClient | None = None) -> dict:
    """Call Dhan /profile, then a market-data request, and record the real outcome."""
    try:
        client = client or get_dhan_client(db)
    except DhanError as e:
        return record_dhan_status(db, e.status, e.message)
    try:
        profile = client.profile()
    except DhanError as e:
        return record_dhan_status(db, e.status, e.message, {"step": "profile"})
    extra = {
        "profile": {k: profile.get(k) for k in ("dhanClientId", "tokenValidity", "activeSegment", "dataPlan", "dataValidity") if isinstance(profile, dict)},
    }
    inst = db.scalar(select(Instrument).join(UniverseMember, UniverseMember.instrument_id == Instrument.id)
                     .where(Instrument.security_id.isnot(None)).limit(1))
    if inst is None:
        return record_dhan_status(db, DhanStatus.CONNECTED, "Profile OK. Market data not tested: no instrument mapped yet (sync the scrip master and universes).", extra)
    try:
        data = client.ltp([inst.security_id])
        if not data:
            return record_dhan_status(db, DhanStatus.MARKET_DATA_UNAVAILABLE, f"Profile OK but no LTP returned for {inst.symbol}", extra)
        extra["market_data_probe"] = {"symbol": inst.symbol, "ltp": (data.get(inst.security_id) or {}).get("last_price")}
    except DhanError as e:
        status = e.status if e.status != DhanStatus.ERROR else DhanStatus.MARKET_DATA_UNAVAILABLE
        return record_dhan_status(db, status, f"Profile OK; market data failed: {e.message}", extra)
    return record_dhan_status(db, DhanStatus.CONNECTED, "Profile and market-data requests succeeded", extra)


# ------------------------------------------------------------------ OpenAI
FALLBACK_MODELS = ["gpt-5-mini", "gpt-5", "gpt-5-nano", "gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini"]
DEFAULT_MODEL = "gpt-5-mini"


def openai_view(db: Session) -> dict:
    key = get_setting(db, K_OPENAI_KEY)
    status = _json(db, K_OPENAI_STATUS)
    return {
        "api_key_masked": mask_secret(key),
        "api_key_set": bool(key),
        "api_key_updated_at": iso(setting_updated_at(db, K_OPENAI_KEY)) if key else None,
        "model": get_setting(db, K_OPENAI_MODEL, DEFAULT_MODEL),
        "enabled": get_setting(db, K_OPENAI_ENABLED, "false") == "true",
        "status": status.get("status", "NOT_CONFIGURED" if not key else "UNTESTED"),
        "status_detail": status,
        "available_models": status.get("models") or FALLBACK_MODELS,
        "models_source": "OpenAI /v1/models (last successful test)" if status.get("models") else "Built-in fallback list (test the connection to load the live list)",
    }


def save_openai(db: Session, api_key: str | None, model: str | None, enabled: bool | None) -> None:
    if api_key is not None:
        set_setting(db, K_OPENAI_KEY, api_key.strip(), secret=True)
        set_setting(db, K_OPENAI_STATUS, json.dumps({"status": "UNTESTED"}))
    if model is not None:
        set_setting(db, K_OPENAI_MODEL, model.strip())
    if enabled is not None:
        set_setting(db, K_OPENAI_ENABLED, "true" if enabled else "false")
    audit(db, "INFO", "settings", "OpenAI settings updated (key not logged)")


def delete_openai(db: Session) -> None:
    for k in (K_OPENAI_KEY, K_OPENAI_STATUS):
        set_setting(db, k, None)
    set_setting(db, K_OPENAI_ENABLED, "false")


def bool_setting(db: Session, key: str, default: bool) -> bool:
    v = get_setting(db, key)
    return default if v is None else v == "true"
