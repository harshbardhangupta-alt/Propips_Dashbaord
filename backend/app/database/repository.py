"""Small persistence helpers shared by services."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decrypt_secret, encrypt_secret
from app.database.models import AuditEvent, JobStatus, PaperAccount, Setting, utcnow


def get_setting(db: Session, key: str, default: str | None = None) -> str | None:
    row = db.get(Setting, key)
    if row is None or row.value is None:
        return default
    if row.is_secret:
        return decrypt_secret(row.value)
    return row.value


def set_setting(db: Session, key: str, value: str | None, secret: bool = False) -> None:
    row = db.get(Setting, key)
    stored = encrypt_secret(value) if (secret and value is not None) else value
    if row is None:
        db.add(Setting(key=key, value=stored, is_secret=secret))
    else:
        row.value = stored
        row.is_secret = secret
        row.updated_at = utcnow()


def setting_updated_at(db: Session, key: str):
    row = db.get(Setting, key)
    return row.updated_at if row else None


def audit(db: Session, level: str, source: str, message: str, data: dict[str, Any] | None = None) -> None:
    db.add(AuditEvent(level=level, source=source, message=message[:4000], data=data or {}))


def job_status(db: Session, job_id: str) -> JobStatus:
    row = db.get(JobStatus, job_id)
    if row is None:
        row = JobStatus(job_id=job_id, enabled=True)
        db.add(row)
        db.flush()
    return row


def get_account(db: Session, code: str) -> PaperAccount:
    acc = db.scalar(select(PaperAccount).where(PaperAccount.code == code))
    if acc is None:
        raise LookupError(f"Paper account {code} not found")
    return acc
