"""DocuSeal connector — concrete implementation of
``BaseESignatureConnector`` against the user's self-hosted DocuSeal
instance.

API surface and webhook spec are source-verified against
``lib/webhook_urls/signatures.rb`` in docusealco/docuseal: header
``X-Docuseal-Signature``, format ``{ts}.{hex_digest}`` over
``{ts}.{body}``, 5-minute timestamp tolerance, secret prefix
``whsec_``, constant-time HMAC compare."""

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone

import requests
from flask import current_app

from app.integrations.esignature.base import (
    BaseESignatureConnector,
    ESignatureError,
    ESignatureSendResult,
    ESignatureWebhookEvent,
)
from app.models.esignature_request import ESignatureStatus

_DOCUSEAL_TO_INTERNAL_STATUS = {
    "pending": ESignatureStatus.SENT,
    "completed": ESignatureStatus.SIGNED,
    "declined": ESignatureStatus.DECLINED,
    "expired": ESignatureStatus.EXPIRED,
}

_FORM_EVENT_TO_STATUS = {
    "form.viewed": ESignatureStatus.VIEWED,
    "form.completed": ESignatureStatus.SIGNED,
    "form.declined": ESignatureStatus.DECLINED,
}

_SUBMISSION_EVENT_TO_STATUS = {
    "submission.completed": ESignatureStatus.SIGNED,
    "submission.expired": ESignatureStatus.EXPIRED,
}

# DocuSeal webhook HMAC tolerance — matches the source-verified
# TOLERANCE = 5 * 60 constant in lib/webhook_urls/signatures.rb.
_WEBHOOK_TOLERANCE_SECONDS = 300


class DocuSealConnector(BaseESignatureConnector):
    """Concrete connector for DocuSeal. Reads base URL, API key, and
    webhook secret from ``credentials.extra_data``."""

    def __init__(self, integration, credentials):
        super().__init__(integration, credentials)
        config = (credentials.extra_data or {}) if credentials else {}
        self.base_url = (config.get("DOCUSEAL_BASE_URL") or "").rstrip("/")
        self.api_key = config.get("DOCUSEAL_API_KEY") or ""
        self.webhook_secret = config.get("DOCUSEAL_WEBHOOK_SECRET")
        self._session = requests.Session()
        if self.api_key:
            self._session.headers.update(
                {
                    "X-Auth-Token": self.api_key,
                    "Content-Type": "application/json",
                }
            )

    @property
    def provider_name(self) -> str:
        return "docuseal"

    @property
    def display_name(self) -> str:
        return "DocuSeal"

    def test_connection(self) -> bool:
        if not self.base_url or not self.api_key:
            return False
        try:
            resp = self._session.get(
                f"{self.base_url}/templates",
                params={"limit": 1},
                timeout=10,
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False

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
        if not self.base_url or not self.api_key:
            raise ESignatureError("DocuSeal credentials not configured")

        encoded = base64.b64encode(document_pdf).decode("ascii")
        expire_at = (datetime.now(timezone.utc) + timedelta(days=expire_in_days)).isoformat()

        fields = []
        for f in signature_fields:
            fields.append(
                {
                    "name": f["name"],
                    "role": f.get("role", "Client"),
                    "type": f.get("type", "signature"),
                    "areas": [
                        {
                            "x": f["x"],
                            "y": f["y"],
                            "w": f["w"],
                            "h": f["h"],
                            "page": f.get("page", 0),
                        }
                    ],
                }
            )

        body = {
            "name": subject,
            "send_email": True,
            "external_id": external_id,
            "expire_at": expire_at,
            "documents": [
                {
                    "name": f"{subject}.pdf",
                    "file": encoded,
                    "fields": fields,
                }
            ],
            "submitters": [
                {
                    "role": signature_fields[0].get("role", "Client") if signature_fields else "Client",
                    "email": recipient_email,
                    "name": recipient_name,
                    "external_id": external_id,
                }
            ],
        }

        resp = self._session.post(f"{self.base_url}/submissions/pdf", json=body, timeout=30)
        if resp.status_code >= 400:
            raise ESignatureError(f"DocuSeal send failed: {resp.status_code} {resp.text[:500]}")

        submitters = resp.json()
        if not submitters:
            raise ESignatureError("DocuSeal returned no submitters for created submission")

        submitter = submitters[0]
        submission_id = str(submitter.get("submission_id") or submitter.get("id"))
        signer_url = f"{self.base_url}/s/{submitter['slug']}" if submitter.get("slug") else None

        return ESignatureSendResult(
            external_id=submission_id,
            signer_url=signer_url,
            sent_at=datetime.now(timezone.utc),
        )

    def get_status(self, external_id: str) -> ESignatureStatus:
        resp = self._session.get(f"{self.base_url}/submissions/{external_id}", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return _DOCUSEAL_TO_INTERNAL_STATUS.get(data.get("status"), ESignatureStatus.SENT)

    def download_signed_document(self, external_id: str) -> bytes:
        resp = self._session.get(
            f"{self.base_url}/submissions/{external_id}/documents",
            params={"merge": "true"},
            timeout=30,
        )
        resp.raise_for_status()
        documents = resp.json().get("documents", [])
        if not documents:
            raise ESignatureError(f"No signed documents available for submission {external_id}")
        pdf_url = documents[0]["url"]
        pdf_resp = requests.get(pdf_url, timeout=60)
        pdf_resp.raise_for_status()
        return pdf_resp.content

    def download_audit_certificate(self, external_id: str) -> bytes | None:
        resp = self._session.get(f"{self.base_url}/submissions/{external_id}", timeout=10)
        resp.raise_for_status()
        audit_url = resp.json().get("audit_log_url")
        if not audit_url:
            return None
        pdf_resp = requests.get(audit_url, timeout=30)
        pdf_resp.raise_for_status()
        return pdf_resp.content

    def cancel(self, external_id: str) -> bool:
        resp = self._session.delete(f"{self.base_url}/submissions/{external_id}", timeout=10)
        return resp.status_code in (200, 204)

    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        if not self.webhook_secret:
            current_app.logger.warning("DocuSeal webhook secret not configured; rejecting webhook")
            return False

        sig_header = headers.get("X-Docuseal-Signature") or headers.get("x-docuseal-signature")
        if not sig_header:
            return False

        try:
            ts_str, sig = sig_header.split(".", 1)
            ts = int(ts_str)
        except (ValueError, AttributeError):
            return False

        now = int(time.time())
        if ts < now - _WEBHOOK_TOLERANCE_SECONDS or ts > now + _WEBHOOK_TOLERANCE_SECONDS:
            return False

        signed_payload = f"{ts}.".encode() + raw_body
        expected = hmac.new(self.webhook_secret.encode(), signed_payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)

    def parse_webhook(self, raw_body: bytes) -> ESignatureWebhookEvent:
        payload = json.loads(raw_body)
        event_type = payload.get("event_type", "")
        data = payload.get("data") or {}
        occurred_at = _parse_iso8601(payload.get("timestamp"))

        if event_type.startswith("form."):
            submission = data.get("submission") or {}
            external_id = str(submission.get("id") or data.get("id") or "")
            status = _FORM_EVENT_TO_STATUS.get(event_type, ESignatureStatus.SENT)
            return ESignatureWebhookEvent(
                external_id=external_id,
                status=status,
                occurred_at=occurred_at,
                decline_reason=data.get("decline_reason"),
                signer_email=data.get("email"),
                raw_payload=payload,
            )

        if event_type.startswith("submission."):
            external_id = str(data.get("id") or "")
            status = _SUBMISSION_EVENT_TO_STATUS.get(event_type, ESignatureStatus.SENT)
            return ESignatureWebhookEvent(
                external_id=external_id,
                status=status,
                occurred_at=occurred_at,
                raw_payload=payload,
            )

        raise ESignatureError(f"Unknown DocuSeal event type: {event_type!r}")


def _parse_iso8601(value) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value
    cleaned = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return datetime.now(timezone.utc)
