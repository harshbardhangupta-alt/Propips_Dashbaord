from app.database.repository import set_setting
from app.services import explanation_service as es


class FakeAI:
    def __init__(self, text="", exc=None):
        self.text, self.exc = text, exc

    def explain(self, model, instructions, prompt, max_output_tokens=900):
        if self.exc:
            raise self.exc
        assert "PAPER-TRADING" in instructions and "Do not invent prices" in instructions
        return self.text

    def list_models(self):
        if self.exc:
            raise self.exc
        return ["gpt-5-mini", "gpt-5"]


def test_validate_ai_output_flags_invented_numbers():
    ctx = {"entry": 144.95, "stop_loss": 139.5}
    assert es.validate_ai_output("Entry 144.95 and stop 139.5 with 3 red candles", ctx) == []
    w = es.validate_ai_output("Price will reach 250.75", ctx)
    assert w and "250.75" in w[0]


def test_disabled_and_unconfigured(db):
    assert es.explain(db, "X", {})["status"] == "DISABLED"
    set_setting(db, "openai_enabled", "true")
    assert es.explain(db, "X", {})["status"] == "NOT_CONFIGURED"


def test_explain_ok_and_errors(db):
    import httpx
    import openai

    set_setting(db, "openai_enabled", "true")
    out = es.explain(db, "D2_SIGNAL", {"entry": 10.5}, client=FakeAI("Entry 10.5 then 99.99"))
    assert out["available"] and out["warnings"] and "does not change" in out["disclaimer"]
    req = httpx.Request("POST", "https://api.openai.com/v1/responses")
    err = openai.AuthenticationError("bad key", response=httpx.Response(401, request=req), body=None)
    out = es.explain(db, "D2_SIGNAL", {}, client=FakeAI(exc=err))
    assert not out["available"] and out["status"] == "AUTH_FAILED"
    rl = openai.RateLimitError("You exceeded your current quota", response=httpx.Response(429, request=req), body=None)
    assert es.test_openai(db, client=FakeAI(exc=rl))["status"] == "QUOTA_EXCEEDED"
    ok = es.test_openai(db, client=FakeAI())
    assert ok["status"] == "CONNECTED" and ok["selected_model_available"]
