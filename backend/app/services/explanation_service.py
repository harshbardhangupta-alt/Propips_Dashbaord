"""Optional AI explanations of deterministic results, with output validation."""
from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from app.core.timeutils import iso
from app.database.models import utcnow
from app.database.repository import get_setting, set_setting
from app.integrations.openai_client import OpenAIClient, classify
from app.services.settings_service import DEFAULT_MODEL, K_OPENAI_ENABLED, K_OPENAI_KEY, K_OPENAI_MODEL, K_OPENAI_STATUS

INSTRUCTIONS = (
    "You explain the output of a deterministic stock-screening engine for a PAPER-TRADING (simulated) application. "
    "Use ONLY the facts and numbers in the provided JSON. Do not invent prices, candles, levels or probabilities. "
    "Do not recommend changing risk limits or allocation, do not upgrade a rejected setup, and do not suggest placing real orders. "
    "Explain: why it qualified or was rejected, how each rule was evaluated, what would invalidate it, how entry/stop/target were derived, "
    "and any data limitations. Be concise (under 250 words), use short headed sections, and end with: "
    "'Educational explanation of simulated results — not investment advice.'"
)

_NUM = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{2,3})*(?:\.\d+)?|\d+(?:\.\d+)?")


def _numbers(text: str) -> set[float]:
    out = set()
    for m in _NUM.findall(text):
        try:
            out.add(round(float(m.replace(",", "")), 2))
        except ValueError:
            pass
    return out


def validate_ai_output(text: str, context: dict) -> list[str]:
    """Flag any number in the AI text (other than small integers) that does not appear in the source data."""
    ctx_nums = _numbers(json.dumps(context, default=str))
    warnings = []
    for n in sorted(_numbers(text)):
        if n <= 10 and float(n).is_integer():
            continue  # list numbering, "3 red candles", "1:3"
        if not any(abs(n - c) <= max(0.011, abs(c) * 0.001) for c in ctx_nums):
            warnings.append(f"Number {n} in the AI text is not present in the engine data — treat as unverified")
    return warnings


def ai_client(db: Session) -> OpenAIClient | None:
    key = get_setting(db, K_OPENAI_KEY)
    return OpenAIClient(key) if key else None


def test_openai(db: Session, client: OpenAIClient | None = None) -> dict:
    client = client or ai_client(db)
    if client is None:
        payload = {"status": "NOT_CONFIGURED", "message": "No OpenAI API key saved", "tested_at": iso(utcnow())}
    else:
        try:
            models = client.list_models()
            model = get_setting(db, K_OPENAI_MODEL, DEFAULT_MODEL)
            available = model in models
            payload = {"status": "CONNECTED", "message": f"Key valid; {len(models)} models listed" + ("" if available else f"; selected model '{model}' is NOT in the list"),
                       "models": models[:200], "selected_model_available": available, "tested_at": iso(utcnow()), "last_success_at": iso(utcnow())}
        except Exception as e:  # noqa: BLE001
            s = classify(e)
            prev = json.loads(get_setting(db, K_OPENAI_STATUS) or "{}")
            payload = {"status": s.status, "message": s.message, "tested_at": iso(utcnow()), "last_success_at": prev.get("last_success_at"), "models": prev.get("models")}
    set_setting(db, K_OPENAI_STATUS, json.dumps(payload))
    db.commit()
    return payload


def explain(db: Session, kind: str, context: dict, client: OpenAIClient | None = None) -> dict:
    if get_setting(db, K_OPENAI_ENABLED, "false") != "true":
        return {"available": False, "status": "DISABLED", "message": "AI explanations are disabled in Settings"}
    client = client or ai_client(db)
    if client is None:
        return {"available": False, "status": "NOT_CONFIGURED", "message": "No OpenAI API key saved"}
    model = get_setting(db, K_OPENAI_MODEL, DEFAULT_MODEL)
    prompt = f"Result type: {kind}\nEngine output JSON:\n" + json.dumps(context, default=str)[:12000]
    try:
        text = client.explain(model, INSTRUCTIONS, prompt)
    except Exception as e:  # noqa: BLE001
        s = classify(e)
        return {"available": False, "status": s.status, "message": s.message, "model": model}
    if not text:
        return {"available": False, "status": "EMPTY", "message": "Model returned no text", "model": model}
    return {"available": True, "status": "OK", "model": model, "text": text, "warnings": validate_ai_output(text, context),
            "disclaimer": "AI-generated explanation of deterministic results. It does not change any calculation, signal or paper trade."}
