"""Secret storage and masking.

Secrets (Dhan access token, OpenAI API key) are encrypted at rest in the SQLite
database with Fernet (AES-128-CBC + HMAC-SHA256). The Fernet key lives in
``data/.secret.key`` (created with 0600 permissions). This protects against casual
disclosure of the DB file alone; anyone who can read BOTH the key file and the DB
can decrypt the secrets. It is not an OS keychain / HSM.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

_fernet: Fernet | None = None


def _key_path() -> Path:
    return get_settings().data_dir / ".secret.key"


def get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        path = _key_path()
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            key = Fernet.generate_key()
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(key)
        _fernet = Fernet(path.read_bytes().strip())
    return _fernet


def reset_fernet_cache() -> None:
    global _fernet
    _fernet = None


def encrypt_secret(value: str) -> str:
    return get_fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str | None:
    try:
        return get_fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def mask_secret(value: str | None) -> str | None:
    """Show at most the last 4 characters of a secret."""
    if not value:
        return None
    if len(value) <= 8:
        return "•" * 8
    return "•" * 12 + value[-4:]


_REDACT_PATTERNS = [
    re.compile(r"(access[-_]?token['\"]?\s*[:=]\s*['\"]?)([^'\"\s,}]+)", re.I),
    re.compile(r"(authorization['\"]?\s*[:=]\s*['\"]?(?:bearer\s+)?)([^'\"\s,}]+)", re.I),
    re.compile(r"(api[-_]?key['\"]?\s*[:=]\s*['\"]?)([^'\"\s,}]+)", re.I),
    re.compile(r"(token=)([^&\s]+)", re.I),
    re.compile(r"(sk-[A-Za-z0-9_\-]{4})[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(eyJ[A-Za-z0-9_\-]{4})[A-Za-z0-9_\-\.]{10,}"),  # JWT-like (Dhan tokens are JWTs)
]


def redact(text: str) -> str:
    for pat in _REDACT_PATTERNS:
        text = pat.sub(lambda m: m.group(1) + "[REDACTED]", text)
    return text
