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
    kwargs = svc._request_kwargs(
        max_tokens=16000, output_format={"type": "json_schema", "schema": {}}
    )
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
