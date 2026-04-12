"""
Shared Factur-X (ZUGFeRD) embed + PDF/A-3 post-processing for invoice PDFs.

Used by HTTP PDF export and email attachment generation so behavior matches.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple


def postprocess_invoice_pdf_bytes(
    pdf_bytes: bytes,
    invoice: Any,
    settings: Any,
) -> Tuple[bytes, Optional[str], Optional[str]]:
    """
    Apply Factur-X CII embedding and optional PDF/A-3 normalization per settings.

    Order: embed Factur-X XML first, then PDF/A-3 (metadata, ICC, optional Ghostscript).

    Returns:
        (pdf_bytes, embed_error, pdfa_error)
        - If Factur-X is disabled: returns (pdf_bytes, None, None).
        - On embed failure: returns (original pdf_bytes, error_message, None).
        - On PDF/A failure after successful embed: returns (pdf after embed, None, error_message).
    """
    if not getattr(settings, "invoices_zugferd_pdf", False):
        return pdf_bytes, None, None

    from app.utils.zugferd import embed_zugferd_xml_in_pdf

    out_pdf, embed_err = embed_zugferd_xml_in_pdf(pdf_bytes, invoice, settings)
    if embed_err:
        return out_pdf, embed_err, None

    if not getattr(settings, "invoices_pdfa3_compliant", False):
        return out_pdf, None, None

    from app.utils.pdfa3 import convert_to_pdfa3

    out_pdf, pdfa_err = convert_to_pdfa3(out_pdf)
    return out_pdf, None, pdfa_err
