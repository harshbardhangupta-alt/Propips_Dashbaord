import logging

from app.core.logging_config import RedactingFilter
from app.core.security import decrypt_secret, encrypt_secret, mask_secret, redact
from app.database.models import Setting
from app.database.repository import get_setting, set_setting


def test_mask_secret():
    assert mask_secret(None) is None
    assert mask_secret("short") == "•" * 8
    m = mask_secret("sk-abcdefghijklmnop1234")
    assert m.endswith("1234") and "abcdef" not in m


def test_encrypt_roundtrip_and_not_plaintext(db):
    set_setting(db, "dhan_access_token", "eyJtokenvalue1234567890", secret=True)
    db.flush()
    raw = db.get(Setting, "dhan_access_token").value
    assert "tokenvalue" not in raw
    assert get_setting(db, "dhan_access_token") == "eyJtokenvalue1234567890"
    assert decrypt_secret("not-a-token") is None
    assert decrypt_secret(encrypt_secret("x")) == "x"


def test_redaction_patterns():
    s = redact("headers={'access-token': 'eyJabcdefghijklmnopqrstuv', 'client-id': '1'} api_key=sk-proj-abcdefghijklmnop")
    assert "abcdefghijklmnopqrstuv" not in s and "sk-proj-abcdefghijklmnop" not in s and "[REDACTED]" in s


def test_log_filter_redacts(caplog):
    logger = logging.getLogger("redact-test")
    logger.addFilter(RedactingFilter())
    with caplog.at_level(logging.INFO, logger="redact-test"):
        logger.info("calling with access-token=%s", "eyJsecretsecretsecretsecret")
    assert "eyJsecretsecretsecretsecret" not in caplog.text
