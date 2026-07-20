"""Claude API provider for SOW auto-provisioning.

Talks to the official Anthropic SDK with provider keys kept server-side. Used by
the SOW -> project/kanban auto-provisioning feature: an SOW (pasted text or an
uploaded PDF) is parsed into a structured ``SowPlan`` via structured outputs, so
the result is always valid, parseable JSON rather than free-form text.

Separate from ``LLMService`` (the Ollama / OpenAI-compatible chat helper) so the
SOW feature can run Opus without changing the chat helper's provider.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.models import Settings
from app.services.llm_service import AIServiceError

logger = logging.getLogger(__name__)

# --- Supported models / effort -------------------------------------------------

DEFAULT_CLAUDE_MODEL = "claude-opus-4-8"
DEFAULT_CLAUDE_EFFORT = "high"

# Selectable models (newest Opus first). Opus-tier supports every effort level;
# Sonnet 4.6 supports low/medium/high; Haiku 4.5 does not support effort at all.
SUPPORTED_CLAUDE_MODELS = (
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
)

EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
# xhigh / max are Opus-tier only; the rest are shared by Opus + Sonnet 4.6.
OPUS_ONLY_EFFORT = ("xhigh", "max")

# USD per 1M tokens (input, output). Used only for cost *estimation* in the usage
# log; the authoritative bill is Anthropic's. Unknown models fall back to Opus.
MODEL_PRICING = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

# How many times the Anthropic SDK retries transient failures (429 / 408 / 5xx /
# connection errors) with exponential backoff before giving up.
DEFAULT_CLAUDE_MAX_RETRIES = 2


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Best-effort USD cost for a call from token counts. Never raises."""
    in_price, out_price = MODEL_PRICING.get(normalize_model(model), MODEL_PRICING[DEFAULT_CLAUDE_MODEL])
    try:
        return round((int(input_tokens) / 1_000_000) * in_price + (int(output_tokens) / 1_000_000) * out_price, 6)
    except (TypeError, ValueError):
        return 0.0


def is_opus(model: str) -> bool:
    return (model or "").startswith("claude-opus")


def supports_effort(model: str) -> bool:
    """Haiku 4.5 rejects the effort parameter outright; everything else accepts it."""
    return is_opus(model) or model == "claude-sonnet-4-6"


def supports_adaptive_thinking(model: str) -> bool:
    return is_opus(model) or model == "claude-sonnet-4-6"


def normalize_model(model: Optional[str]) -> str:
    model = (model or "").strip().lower()
    return model if model in SUPPORTED_CLAUDE_MODELS else DEFAULT_CLAUDE_MODEL


def normalize_effort(effort: Optional[str], *, model: str) -> str:
    """Clamp the requested effort to what the model supports.

    Returns "" when the model does not support effort at all (Haiku), so callers
    can omit the parameter rather than send something the API would 400 on.
    """
    model = normalize_model(model)
    if not supports_effort(model):
        return ""
    effort = (effort or "").strip().lower()
    if effort not in EFFORT_LEVELS:
        effort = DEFAULT_CLAUDE_EFFORT
    if effort in OPUS_ONLY_EFFORT and not is_opus(model):
        effort = "high"
    return effort


def allowed_efforts_for(model: str) -> tuple:
    """Effort options the UI should offer for a given model (server-side source of truth)."""
    model = normalize_model(model)
    if not supports_effort(model):
        return ()
    if is_opus(model):
        return EFFORT_LEVELS
    return ("low", "medium", "high")


# --- SOW structured-output schema ---------------------------------------------

# JSON Schema for structured outputs. Keep it within the supported subset:
# types/enums/required/additionalProperties only (no min/max/length constraints).
SOW_PLAN_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["client", "project", "tasks"],
    "properties": {
        "client": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "contact_person": {"type": ["string", "null"]},
                "email": {"type": ["string", "null"]},
                "default_hourly_rate": {"type": ["number", "null"]},
            },
        },
        "project": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "billable"],
            "properties": {
                "name": {"type": "string"},
                "code": {"type": ["string", "null"]},
                "description": {"type": ["string", "null"]},
                "billable": {"type": "boolean"},
                "hourly_rate": {"type": ["number", "null"]},
                "budget_amount": {"type": ["number", "null"]},
                "start_date": {"type": ["string", "null"]},
                "end_date": {"type": ["string", "null"]},
            },
        },
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "status", "priority"],
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": ["string", "null"]},
                    "status": {
                        "type": "string",
                        "enum": ["todo", "in_progress", "review", "done"],
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "urgent"],
                    },
                    "estimated_hours": {"type": ["number", "null"]},
                    "due_date": {"type": ["string", "null"]},
                    "tags": {"type": ["string", "null"]},
                },
            },
        },
    },
}

SOW_SYSTEM_PROMPT = (
    "You convert a customer Statement of Work (SOW) into a structured project plan for a "
    "time-tracking app. Extract the client, the project (name, optional code, description, "
    "billable flag, hourly rate, budget, and start/end dates if present), and a list of work "
    "items as tasks. Each task gets a short name, optional description, a kanban status "
    "(default 'todo'), and a priority (default 'medium'). Use ISO 8601 (YYYY-MM-DD) for any "
    "dates. Infer reasonable estimated hours only when the SOW states or strongly implies them; "
    "otherwise leave them null. Do not invent clients, budgets, or rates that are not in the SOW. "
    "Break deliverables and milestones into actionable tasks a technician can pick up."
)


@dataclass
class ClaudeConfig:
    enabled: bool
    model: str
    effort: str
    api_key: str
    api_key_set: bool
    timeout_seconds: int
    max_retries: int = DEFAULT_CLAUDE_MAX_RETRIES

    @classmethod
    def from_settings(cls) -> "ClaudeConfig":
        config = Settings.get_settings().get_claude_config(include_secrets=True)
        return cls(**config)

    def public_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "model": self.model,
            "effort": self.effort,
            "api_key_set": self.api_key_set,
            "timeout_seconds": self.timeout_seconds,
            "allowed_efforts": list(allowed_efforts_for(self.model)),
            "supported_models": list(SUPPORTED_CLAUDE_MODELS),
        }


class ClaudeService:
    """Claude-backed SOW parser. Returns structured plans; never writes to the DB."""

    def __init__(self, config: Optional[ClaudeConfig] = None):
        self.config = config or ClaudeConfig.from_settings()

    def is_enabled(self) -> bool:
        return bool(self.config.enabled)

    def ensure_enabled(self) -> None:
        if not self.config.enabled:
            raise AIServiceError("Claude integration is disabled.", "claude_disabled", 503)
        if not self.config.api_key:
            raise AIServiceError("Claude integration requires an API key.", "claude_missing_api_key", 400)

    # -- client -----------------------------------------------------------------

    def _client(self):
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise AIServiceError("The anthropic package is not installed.", "claude_sdk_missing", 500) from exc
        return anthropic.Anthropic(
            api_key=self.config.api_key,
            timeout=self.config.timeout_seconds,
            # SDK does exponential backoff with jitter on 408/409/429/5xx.
            max_retries=getattr(self.config, "max_retries", DEFAULT_CLAUDE_MAX_RETRIES),
        )

    def _request_kwargs(self, *, max_tokens: int, output_format: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        model = normalize_model(self.config.model)
        kwargs: Dict[str, Any] = {"model": model, "max_tokens": max_tokens}
        if supports_adaptive_thinking(model):
            kwargs["thinking"] = {"type": "adaptive"}
        output_config: Dict[str, Any] = {}
        effort = normalize_effort(self.config.effort, model=model)
        if effort:
            output_config["effort"] = effort
        if output_format is not None:
            output_config["format"] = output_format
        if output_config:
            kwargs["output_config"] = output_config
        return kwargs

    def _call(self, *, system, messages, max_tokens, output_format=None, operation=None, user_id=None) -> str:
        import anthropic

        client = self._client()
        try:
            response = client.messages.create(
                system=system,
                messages=messages,
                **self._request_kwargs(max_tokens=max_tokens, output_format=output_format),
            )
        except anthropic.AuthenticationError as exc:
            raise AIServiceError("Claude rejected the API key.", "claude_auth_error", 401) from exc
        except anthropic.RateLimitError as exc:
            raise AIServiceError("Claude is rate limited. Try again shortly.", "claude_rate_limited", 429) from exc
        except anthropic.APITimeoutError as exc:
            raise AIServiceError("Claude timed out.", "claude_timeout", 504) from exc
        except anthropic.APIConnectionError as exc:
            raise AIServiceError("Claude is not reachable.", "claude_unreachable", 502) from exc
        except anthropic.APIStatusError as exc:
            status = getattr(exc, "status_code", 502) or 502
            raise AIServiceError("Claude rejected the request.", "claude_provider_error", status) from exc

        if operation:
            self._log_usage(operation=operation, user_id=user_id, response=response)

        if getattr(response, "stop_reason", None) == "refusal":
            raise AIServiceError("Claude declined to process this document.", "claude_refusal", 422)
        return next(
            (block.text for block in response.content if getattr(block, "type", None) == "text"),
            "",
        )

    def _log_usage(self, *, operation: str, user_id: Optional[int], response: Any) -> None:
        """Record a per-user usage/cost row. Never lets a logging failure break the call."""
        try:
            from app import db
            from app.models import ClaudeUsageLog

            usage = getattr(response, "usage", None)
            input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
            output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
            model = normalize_model(self.config.model)
            db.session.add(
                ClaudeUsageLog(
                    user_id=user_id,
                    operation=operation[:30],
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=estimate_cost_usd(model, input_tokens, output_tokens),
                )
            )
            db.session.commit()
        except Exception:  # pragma: no cover - metering must never break the request
            logger.warning("Failed to record Claude usage log", exc_info=True)
            try:
                from app import db

                db.session.rollback()
            except Exception:
                pass

    # -- public API -------------------------------------------------------------

    def test_connection(self, *, user_id: Optional[int] = None) -> Dict[str, Any]:
        self.ensure_enabled()
        reply = self._call(
            system="Reply with a short confirmation only.",
            messages=[
                {
                    "role": "user",
                    "content": "Say the TimeTracker Claude integration is connected.",
                }
            ],
            max_tokens=40,
            operation="test_connection",
            user_id=user_id,
        )
        return {
            "ok": True,
            "reply": (reply or "").strip(),
            "provider": self.config.public_dict(),
        }

    def parse_sow(
        self,
        *,
        sow_text: Optional[str] = None,
        pdf_bytes: Optional[bytes] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Parse an SOW into a structured plan. Accepts pasted text and/or a PDF.

        Returns the validated plan dict (client/project/tasks). Does NOT write to
        the database — provisioning is a separate, confirmed step.
        """
        self.ensure_enabled()
        content = self._build_user_content(sow_text, pdf_bytes)

        # Prompt caching: freeze the instruction prefix; the SOW is the volatile suffix.
        system = [
            {
                "type": "text",
                "text": SOW_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        raw = self._call(
            system=system,
            messages=[{"role": "user", "content": content}],
            max_tokens=16000,
            output_format={"type": "json_schema", "schema": SOW_PLAN_SCHEMA},
            operation="parse_sow",
            user_id=user_id,
        )
        try:
            plan = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise AIServiceError("Claude returned an unparseable plan.", "claude_invalid_plan", 502) from exc
        if not isinstance(plan, dict) or "project" not in plan or "client" not in plan:
            raise AIServiceError("Claude returned an incomplete plan.", "claude_invalid_plan", 502)
        plan.setdefault("tasks", [])
        return {"plan": plan, "provider": self.config.public_dict()}

    def _build_user_content(self, sow_text: Optional[str], pdf_bytes: Optional[bytes]):
        text = (sow_text or "").strip()
        if not text and not pdf_bytes:
            raise AIServiceError("Provide SOW text or a document to parse.", "validation_error", 400)

        content = []
        if pdf_bytes:
            content.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": base64.standard_b64encode(pdf_bytes).decode("ascii"),
                    },
                }
            )
        instruction = "Parse this Statement of Work into the structured project plan."
        if text:
            instruction = f"{instruction}\n\nSOW:\n{text}"
        content.append({"type": "text", "text": instruction})
        return content
