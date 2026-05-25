"""Provider-agnostic ABC for e-signature connectors.

Every concrete connector (DocuSeal, future DocuSign, future HelloSign,
etc.) implements this contract. The ABC deliberately mirrors only the
operations the feature layer needs — sending for signature, polling
status, downloading the signed document + audit certificate, parsing
webhooks. OAuth-style auth methods live on the sibling ``BaseConnector``
and are not relevant here."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from app.models.esignature_request import ESignatureStatus


class ESignatureError(Exception):
    """Raised by connectors when a provider call fails in a non-recoverable
    way. The service layer translates these into user-facing flash
    messages and persists the request as status=failed."""


@dataclass
class ESignatureSendResult:
    """Returned by ``send_for_signature``. ``external_id`` is the
    provider-side submission identifier — used for status polling and
    signed-document retrieval."""

    external_id: str
    signer_url: str | None
    sent_at: datetime


@dataclass
class ESignatureWebhookEvent:
    """Normalised webhook payload. Each connector translates its
    provider-specific event types into one of these."""

    external_id: str
    status: ESignatureStatus
    occurred_at: datetime
    decline_reason: str | None = None
    signer_email: str | None = None
    raw_payload: dict | None = None


class BaseESignatureConnector(ABC):
    """Contract every e-signature connector must implement. Constructed
    with the ``Integration`` row + its ``IntegrationCredential`` row;
    provider-specific config (base URL, API key, webhook secret) lives
    on ``credentials.extra_data``."""

    def __init__(self, integration, credentials):
        self.integration = integration
        self.credentials = credentials

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Stable short identifier, e.g. ``'docuseal'``, ``'docusign'``."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name, e.g. ``'DocuSeal'``."""

    @abstractmethod
    def test_connection(self) -> bool:
        """Verify the configured credentials can reach the provider.
        Returns True on 2xx from a low-cost authenticated endpoint."""

    @abstractmethod
    def send_for_signature(
        self,
        *,
        document_pdf: bytes,
        recipient_email: str,
        recipient_name: str,
        subject: str,
        external_id: str,
        signature_fields: list[dict],
        expire_in_days: int = 30,
    ) -> ESignatureSendResult:
        """Create a submission and dispatch the signing email.

        ``signature_fields`` is a list of normalised field descriptors:
        ``[{"name": "Signature", "type": "signature", "page": 2,
            "x": 36, "y": 280, "w": 480, "h": 70, "role": "Client"}]``
        Each connector translates these to its provider format.

        ``external_id`` is OUR side identifier (e.g. the
        ``ESignatureRequest`` UUID) — providers that accept it echo
        it back on webhooks for free correlation."""

    @abstractmethod
    def get_status(self, external_id: str) -> ESignatureStatus:
        """Re-fetch authoritative status from the provider. Used by the
        reconciliation cron and webhook verify-by-refetch."""

    @abstractmethod
    def download_signed_document(self, external_id: str) -> bytes:
        """Fetch the final signed PDF. Raise ``ESignatureError`` if the
        submission isn't yet complete."""

    @abstractmethod
    def download_audit_certificate(self, external_id: str) -> bytes | None:
        """Fetch the provider's Certificate of Completion PDF. Returns
        ``None`` if the certificate isn't yet available (e.g. multi-signer
        submission where one signer is pending)."""

    @abstractmethod
    def cancel(self, external_id: str) -> bool:
        """Cancel / archive an in-flight submission. Idempotent."""

    @abstractmethod
    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        """Verify webhook authenticity (HMAC, signature timestamp, etc.)
        Must be constant-time. Fail-closed when the secret is missing.
        Returns True on valid, False otherwise."""

    @abstractmethod
    def parse_webhook(self, raw_body: bytes) -> ESignatureWebhookEvent:
        """Decode the provider's webhook payload into a normalised event.
        Must be called only after ``verify_webhook`` returns True."""
