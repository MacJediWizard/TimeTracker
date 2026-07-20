"""Tests for the Claude provider service (SOW brains)."""

import json

import pytest

from app.services.claude_service import (
    DEFAULT_CLAUDE_EFFORT,
    DEFAULT_CLAUDE_MODEL,
    ClaudeConfig,
    ClaudeService,
    allowed_efforts_for,
    normalize_effort,
    normalize_model,
    supports_effort,
)
from app.services.llm_service import AIServiceError


def _config(**overrides):
    base = dict(
        enabled=True,
        model="claude-opus-4-8",
        effort="high",
        api_key="sk-test",
        api_key_set=True,
        timeout_seconds=120,
    )
    base.update(overrides)
    return ClaudeConfig(**base)


# --- model / effort normalization (pure) --------------------------------------


def test_normalize_model_defaults_unknown_to_opus():
    assert normalize_model("not-a-model") == DEFAULT_CLAUDE_MODEL
    assert normalize_model("") == DEFAULT_CLAUDE_MODEL
    assert normalize_model("CLAUDE-OPUS-4-8") == "claude-opus-4-8"


def test_normalize_model_accepts_supported():
    for model in ("claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"):
        assert normalize_model(model) == model


def test_effort_xhigh_max_gated_to_opus():
    assert normalize_effort("xhigh", model="claude-opus-4-8") == "xhigh"
    assert normalize_effort("max", model="claude-opus-4-7") == "max"
    # Sonnet cannot use xhigh/max -> clamps to high
    assert normalize_effort("xhigh", model="claude-sonnet-4-6") == "high"
    assert normalize_effort("max", model="claude-sonnet-4-6") == "high"


def test_haiku_has_no_effort():
    assert supports_effort("claude-haiku-4-5") is False
    assert normalize_effort("high", model="claude-haiku-4-5") == ""
    assert allowed_efforts_for("claude-haiku-4-5") == ()


def test_invalid_effort_falls_back_to_default():
    assert normalize_effort("turbo", model="claude-opus-4-8") == DEFAULT_CLAUDE_EFFORT


def test_allowed_efforts_per_tier():
    assert allowed_efforts_for("claude-opus-4-8") == (
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    )
    assert allowed_efforts_for("claude-sonnet-4-6") == ("low", "medium", "high")


# --- request kwargs ------------------------------------------------------------


def test_request_kwargs_opus_includes_effort_and_thinking():
    svc = ClaudeService(config=_config(model="claude-opus-4-8", effort="xhigh"))
    kwargs = svc._request_kwargs(max_tokens=16000, output_format={"type": "json_schema", "schema": {}})
    assert kwargs["model"] == "claude-opus-4-8"
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"]["effort"] == "xhigh"
    assert "format" in kwargs["output_config"]


def test_request_kwargs_haiku_omits_effort_and_thinking():
    svc = ClaudeService(config=_config(model="claude-haiku-4-5", effort="high"))
    kwargs = svc._request_kwargs(max_tokens=16000)
    assert "thinking" not in kwargs
    assert "output_config" not in kwargs  # no effort, no format


# --- enable guards -------------------------------------------------------------


def test_ensure_enabled_when_disabled():
    svc = ClaudeService(config=_config(enabled=False))
    with pytest.raises(AIServiceError) as exc:
        svc.ensure_enabled()
    assert exc.value.code == "claude_disabled"


def test_ensure_enabled_without_key():
    svc = ClaudeService(config=_config(api_key="", api_key_set=False))
    with pytest.raises(AIServiceError) as exc:
        svc.ensure_enabled()
    assert exc.value.code == "claude_missing_api_key"


# --- parse_sow (mocked Claude call) -------------------------------------------


SAMPLE_PLAN = {
    "client": {
        "name": "Acme Corp",
        "email": "ops@acme.test",
        "default_hourly_rate": 150,
    },
    "project": {
        "name": "Network Refresh",
        "billable": True,
        "hourly_rate": 175,
        "start_date": "2026-07-01",
    },
    "tasks": [
        {
            "name": "Site survey",
            "status": "todo",
            "priority": "high",
            "estimated_hours": 8,
        },
        {"name": "Install switches", "status": "todo", "priority": "medium"},
    ],
}


def test_parse_sow_returns_structured_plan(monkeypatch):
    svc = ClaudeService(config=_config())
    monkeypatch.setattr(svc, "_call", lambda **kwargs: json.dumps(SAMPLE_PLAN))
    result = svc.parse_sow(sow_text="Acme wants a network refresh...")
    assert result["plan"]["client"]["name"] == "Acme Corp"
    assert len(result["plan"]["tasks"]) == 2
    assert result["provider"]["model"] == "claude-opus-4-8"


def test_parse_sow_rejects_empty_input():
    svc = ClaudeService(config=_config())
    with pytest.raises(AIServiceError) as exc:
        svc.parse_sow(sow_text="   ")
    assert exc.value.code == "validation_error"


def test_parse_sow_raises_on_unparseable(monkeypatch):
    svc = ClaudeService(config=_config())
    monkeypatch.setattr(svc, "_call", lambda **kwargs: "not json")
    with pytest.raises(AIServiceError) as exc:
        svc.parse_sow(sow_text="something")
    assert exc.value.code == "claude_invalid_plan"


# --- Env/app-config fallback for get_claude_config -----------------------------
# Regression guard: get_claude_config's docstring promises an env/app-config
# fallback, but that only works if the Config class actually defines the CLAUDE_*
# keys (Flask does not auto-import arbitrary env vars). If these are missing,
# setting CLAUDE_API_KEY / CLAUDE_ENABLED / etc. in the environment silently
# does nothing and only the DB/UI path works.


def test_config_class_defines_claude_env_keys():
    """The five CLAUDE_* keys must exist on Config or the env fallback is dead."""
    from app.config import Config

    for key in ("CLAUDE_ENABLED", "CLAUDE_MODEL", "CLAUDE_EFFORT", "CLAUDE_API_KEY", "CLAUDE_TIMEOUT_SECONDS"):
        assert hasattr(Config, key), f"Config is missing {key} -> env override for it is silently ignored"


def test_get_claude_config_falls_back_to_app_config(app):
    """With no DB overrides, get_claude_config must read CLAUDE_* from app config."""
    from app.models.settings import Settings

    with app.app_context():
        app.config["CLAUDE_ENABLED"] = True
        app.config["CLAUDE_MODEL"] = "claude-sonnet-4-6"
        app.config["CLAUDE_EFFORT"] = "medium"
        app.config["CLAUDE_TIMEOUT_SECONDS"] = 222

        s = Settings()
        s.claude_enabled = None
        s.claude_model = None
        s.claude_effort = None
        s.claude_timeout_seconds = None
        s.claude_api_key = None

        cfg = s.get_claude_config()
        assert cfg["enabled"] is True
        assert cfg["model"] == "claude-sonnet-4-6"
        assert cfg["effort"] == "medium"
        assert cfg["timeout_seconds"] == 222


# --- cost estimation (pure) ----------------------------------------------------


def test_estimate_cost_usd_per_tier():
    from app.services.claude_service import estimate_cost_usd

    # Opus: $5/1M in + $25/1M out
    assert estimate_cost_usd("claude-opus-4-8", 1_000_000, 1_000_000) == 30.0
    assert estimate_cost_usd("claude-sonnet-4-6", 1_000_000, 0) == 3.0
    assert estimate_cost_usd("claude-haiku-4-5", 0, 1_000_000) == 5.0


def test_estimate_cost_usd_unknown_model_falls_back_to_opus():
    from app.services.claude_service import estimate_cost_usd

    assert estimate_cost_usd("mystery-model", 1_000_000, 0) == 5.0


def test_estimate_cost_usd_bad_tokens_returns_zero():
    from app.services.claude_service import estimate_cost_usd

    assert estimate_cost_usd("claude-opus-4-8", None, None) == 0.0


# --- retry / max_retries config -----------------------------------------------


def test_claude_config_defaults_max_retries():
    from app.services.claude_service import DEFAULT_CLAUDE_MAX_RETRIES

    # _config() does not pass max_retries -> dataclass default applies.
    assert _config().max_retries == DEFAULT_CLAUDE_MAX_RETRIES


def test_get_claude_config_reads_and_clamps_max_retries(app):
    from app.models.settings import Settings

    with app.app_context():
        s = Settings()
        s.claude_enabled = None
        s.claude_model = None
        s.claude_effort = None
        s.claude_timeout_seconds = None
        s.claude_api_key = None

        app.config["CLAUDE_MAX_RETRIES"] = 5
        assert s.get_claude_config()["max_retries"] == 5
        # clamp to [0, 10]
        app.config["CLAUDE_MAX_RETRIES"] = 99
        assert s.get_claude_config()["max_retries"] == 10
        app.config["CLAUDE_MAX_RETRIES"] = -3
        assert s.get_claude_config()["max_retries"] == 0
        # non-numeric -> default 2
        app.config["CLAUDE_MAX_RETRIES"] = "nope"
        assert s.get_claude_config()["max_retries"] == 2


def test_client_passes_max_retries_and_timeout(monkeypatch):
    import anthropic

    captured = {}

    def fake_anthropic(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(anthropic, "Anthropic", fake_anthropic)
    svc = ClaudeService(config=_config(max_retries=7, timeout_seconds=99))
    svc._client()
    assert captured["max_retries"] == 7
    assert captured["timeout"] == 99
    assert captured["api_key"] == "sk-test"


# --- usage logging -------------------------------------------------------------


class _FakeUsage:
    def __init__(self, i, o):
        self.input_tokens = i
        self.output_tokens = o


class _FakeResponse:
    def __init__(self, i, o, *, stop_reason="end_turn", text="hi"):
        self.usage = _FakeUsage(i, o)
        self.stop_reason = stop_reason
        self.content = [type("B", (), {"type": "text", "text": text})()]


def test_log_usage_writes_row(app):
    from app.models import ClaudeUsageLog
    from app.services.claude_service import estimate_cost_usd

    with app.app_context():
        svc = ClaudeService(config=_config(model="claude-opus-4-8"))
        before = ClaudeUsageLog.query.count()
        svc._log_usage(operation="parse_sow", user_id=None, response=_FakeResponse(100, 50))
        rows = ClaudeUsageLog.query.order_by(ClaudeUsageLog.id.desc()).all()
        assert len(rows) == before + 1
        row = rows[0]
        assert row.operation == "parse_sow"
        assert row.model == "claude-opus-4-8"
        assert row.input_tokens == 100
        assert row.output_tokens == 50
        assert float(row.cost_usd) == estimate_cost_usd("claude-opus-4-8", 100, 50)


def test_log_usage_never_raises_on_bad_response(app):
    with app.app_context():
        svc = ClaudeService(config=_config())
        # response=None has no .usage -> counts default to 0, must not raise.
        svc._log_usage(operation="parse_sow", user_id=None, response=None)


def test_call_logs_usage_and_returns_text(app, monkeypatch):
    from app.models import ClaudeUsageLog

    class _FakeMessages:
        def create(self, **kwargs):
            return _FakeResponse(12, 3, text="pong")

    class _FakeClient:
        messages = _FakeMessages()

    with app.app_context():
        svc = ClaudeService(config=_config())
        monkeypatch.setattr(svc, "_client", lambda: _FakeClient())
        before = ClaudeUsageLog.query.count()
        out = svc._call(system="x", messages=[], max_tokens=10, operation="test_connection", user_id=None)
        assert out == "pong"
        assert ClaudeUsageLog.query.count() == before + 1
        assert ClaudeUsageLog.query.order_by(ClaudeUsageLog.id.desc()).first().operation == "test_connection"
