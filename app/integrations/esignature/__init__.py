"""E-signature integration connectors. Sibling to the OAuth-shaped
``BaseConnector`` at ``app/integrations/base.py``; e-signature providers
typically use static API keys, not OAuth, so they get their own ABC."""

from app.integrations.esignature.base import (
    BaseESignatureConnector,
    ESignatureError,
    ESignatureSendResult,
    ESignatureWebhookEvent,
)

__all__ = [
    "BaseESignatureConnector",
    "ESignatureError",
    "ESignatureSendResult",
    "ESignatureWebhookEvent",
]
