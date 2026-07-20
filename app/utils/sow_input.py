"""Shared SOW input extraction.

Both the cookie-session route (``app/routes/api.py``) and the API-token route
(``app/routes/api_v1_ai.py``) accept the same SOW payloads -- a pasted text
body or an uploaded PDF/DOCX/TXT file -- so the extraction lives here once.

PDFs are handed to Claude natively (returned as bytes); DOCX and plain text are
decoded to text server-side. Returns ``(sow_text, pdf_bytes)`` where exactly one
side is populated.
"""

from __future__ import annotations

import io
from typing import Optional, Tuple

from app.services.llm_service import AIServiceError


def extract_docx_text(data: bytes) -> str:
    try:
        import docx  # python-docx
    except ImportError as exc:
        raise AIServiceError("DOCX support is unavailable on the server.", "docx_unavailable", 500) from exc
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise AIServiceError("Could not read the DOCX file.", "validation_error", 400) from exc
    return "\n".join(p.text for p in document.paragraphs if p.text)


def extract_sow_input(req) -> Tuple[Optional[str], Optional[bytes]]:
    """Pull SOW input from a request: multipart file (PDF/DOCX/TXT) or JSON sow_text.

    Returns ``(sow_text, pdf_bytes)``. PDFs are sent to Claude natively; DOCX/TXT
    are extracted to text server-side.
    """
    upload = req.files.get("file") if req.files else None
    if upload and upload.filename:
        filename = (upload.filename or "").lower()
        data = upload.read()
        content_type = (upload.mimetype or "").lower()
        if filename.endswith(".pdf") or content_type == "application/pdf":
            return None, data
        if filename.endswith(".docx") or "officedocument.wordprocessingml" in content_type:
            return extract_docx_text(data), None
        # Plain text / markdown / unknown — best-effort decode.
        try:
            return data.decode("utf-8", errors="replace"), None
        except Exception as exc:  # pragma: no cover - decode guard
            raise AIServiceError("Could not read the uploaded file.", "validation_error", 400) from exc

    payload = req.get_json(silent=True) or {}
    return (payload.get("sow_text") or payload.get("text") or ""), None
