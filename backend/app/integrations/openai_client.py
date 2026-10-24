"""Thin wrapper over the official OpenAI Python SDK (Responses API).

The AI is used only to EXPLAIN results already computed by the deterministic engines.
It has no tools, cannot place or simulate orders, and its output never feeds back into
strategy or execution logic.
"""
from __future__ import annotations

from dataclasses import dataclass

import openai


@dataclass
class AIStatus:
    status: str
    message: str


def classify(exc: Exception) -> AIStatus:
    if isinstance(exc, openai.AuthenticationError):
        return AIStatus("AUTH_FAILED", "Invalid OpenAI API key")
    if isinstance(exc, openai.PermissionDeniedError):
        return AIStatus("PERMISSION_DENIED", "Key lacks permission for this model/project")
    if isinstance(exc, openai.RateLimitError):
        msg = str(exc)
        return AIStatus("QUOTA_EXCEEDED" if "quota" in msg.lower() else "RATE_LIMITED", msg[:300])
    if isinstance(exc, openai.NotFoundError):
        return AIStatus("MODEL_NOT_FOUND", str(exc)[:300])
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        return AIStatus("NETWORK_ERROR", str(exc)[:300])
    if isinstance(exc, openai.APIError):
        return AIStatus("ERROR", str(exc)[:300])
    return AIStatus("ERROR", f"{type(exc).__name__}: {exc}"[:300])


class OpenAIClient:
    def __init__(self, api_key: str, timeout: float = 45.0, client: openai.OpenAI | None = None):
        self._c = client or openai.OpenAI(api_key=api_key, timeout=timeout, max_retries=2)

    def list_models(self) -> list[str]:
        ids = [m.id for m in self._c.models.list()]
        chat_like = [i for i in ids if i.startswith(("gpt-", "o")) and not any(x in i for x in ("audio", "realtime", "tts", "transcribe", "image", "search", "embedding"))]
        return sorted(chat_like) or sorted(ids)

    def explain(self, model: str, instructions: str, prompt: str, max_output_tokens: int = 900) -> str:
        r = self._c.responses.create(model=model, instructions=instructions, input=prompt, max_output_tokens=max_output_tokens)
        return (r.output_text or "").strip()
