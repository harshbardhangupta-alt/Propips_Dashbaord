"""Logging setup with a redaction filter so tokens/keys never reach log output."""
from __future__ import annotations

import logging

from app.core.security import redact


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover - malformed record
            return True
        record.msg = redact(msg)
        record.args = ()
        return True


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if any(isinstance(f, RedactingFilter) for h in root.handlers for f in h.filters):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    root.handlers = [handler]
    root.setLevel(level)
    # httpx logs full URLs at INFO; keep it quiet.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
