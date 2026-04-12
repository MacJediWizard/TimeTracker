"""Tests for shared invoice PDF Factur-X / PDF/A post-processing."""

import io
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import ANY, MagicMock, patch

import pytest

from app import db
from app.models import Client, Invoice, InvoiceItem, Project, User
from app.utils.invoice_pdf_postprocess import postprocess_invoice_pdf_bytes


@pytest.mark.unit
def test_postprocess_noop_when_zugferd_disabled(app):
    with app.app_context():
        settings = __import__("app.models", fromlist=["Settings"]).Settings.get_settings()
        settings.invoices_zugferd_pdf = False
        settings.invoices_pdfa3_compliant = False
        db.session.commit()
        raw = b"%PDF-1.4 minimal"
        out, e1, e2 = postprocess_invoice_pdf_bytes(raw, None, settings)
        assert out == raw and e1 is None and e2 is None


@pytest.mark.unit
def test_postprocess_embeds_when_zugferd_enabled(app):
    try:
        import pikepdf
    except ImportError:
        pytest.skip("pikepdf not installed")

    with app.app_context():
        user = User(username="ppuser", role="user", email="pp@example.com")
        user.is_active = True
        user.set_password("x")
        db.session.add(user)
        client = Client(name="C1", email="c@example.com", address="Street 1")
        client.set_custom_field("peppol_country", "DE")
        db.session.add(client)
        db.session.commit()
        project = Project(name="P1", client_id=client.id, billable=True, hourly_rate=Decimal("50"))
        project.status = "active"
        db.session.add(project)
        db.session.commit()
        inv = Invoice(
            invoice_number="INV-PP-1",
            project_id=project.id,
            client_id=client.id,
            client_name=client.name,
            issue_date=date.today(),
            due_date=date.today() + timedelta(days=14),
            created_by=user.id,
            currency_code="EUR",
            tax_rate=Decimal("19"),
        )
        db.session.add(inv)
        db.session.commit()
        db.session.add(
            InvoiceItem(
                invoice_id=inv.id,
                description="Work",
                quantity=Decimal("1"),
                unit_price=Decimal("100.00"),
            )
        )
        db.session.commit()
        inv.calculate_totals()
        db.session.commit()

        settings = __import__("app.models", fromlist=["Settings"]).Settings.get_settings()
        settings.company_name = "Seller Co"
        settings.company_tax_id = "DE123456789"
        settings.peppol_sender_country = "DE"
        settings.peppol_sender_endpoint_id = "0088:123"
        settings.peppol_sender_scheme_id = "0088"
        settings.invoices_zugferd_pdf = True
        settings.invoices_pdfa3_compliant = False
        db.session.commit()

        pdf = pikepdf.Pdf.new()
        pdf.add_blank_page(page_size=(595, 842))
        buf = io.BytesIO()
        pdf.save(buf)
        pdf.close()
        raw = buf.getvalue()

        out, e1, e2 = postprocess_invoice_pdf_bytes(raw, inv, settings)
        assert e1 is None and e2 is None
        assert len(out) > len(raw)
        r = pikepdf.open(io.BytesIO(out))
        from app.utils.zugferd import FACTURX_EMBEDDED_FILENAME

        assert FACTURX_EMBEDDED_FILENAME in r.attachments
        r.close()


@pytest.mark.unit
def test_postprocess_returns_embed_error_on_invalid_pdf(app):
    with app.app_context():
        settings = __import__("app.models", fromlist=["Settings"]).Settings.get_settings()
        settings.invoices_zugferd_pdf = True
        settings.invoices_pdfa3_compliant = False
        db.session.commit()
        from types import SimpleNamespace

        inv = SimpleNamespace(
            id=1,
            invoice_number="X",
            issue_date=date.today(),
            due_date=None,
            currency_code="EUR",
            subtotal=Decimal("0"),
            tax_rate=Decimal("0"),
            tax_amount=Decimal("0"),
            total_amount=Decimal("0"),
            notes=None,
            buyer_reference=None,
            project=None,
            client=None,
            client_name="B",
            client_email=None,
            client_address=None,
            items=[],
            expenses=[],
            extra_goods=[],
        )
        out, e1, e2 = postprocess_invoice_pdf_bytes(b"not pdf", inv, settings)
        assert e1 is not None
        assert out == b"not pdf"
        assert e2 is None


@pytest.mark.unit
@patch("app.utils.email.render_template", return_value="<html/>")
@patch("app.utils.pdf_generator.InvoicePDFGenerator")
@patch("app.utils.invoice_pdf_postprocess.postprocess_invoice_pdf_bytes")
def test_build_invoice_email_payload_calls_postprocess(mock_pp, mock_igen, mock_render, app):
    """Email PDF path applies the same Factur-X / PDF/A post-processing as export."""
    from app.utils.email import _build_invoice_email_payload

    mock_igen.return_value.generate_pdf.return_value = b"raw_pdf"
    mock_pp.return_value = (b"processed_pdf", None, None)
    inv = MagicMock()
    inv.invoice_number = "INV-E-1"
    inv.issue_date = date(2025, 1, 10)
    inv.due_date = date(2025, 2, 10)
    inv.currency_code = "EUR"
    inv.total_amount = Decimal("100.00")
    with app.app_context():
        pdf, *_ = _build_invoice_email_payload(inv)
    mock_pp.assert_called_once_with(b"raw_pdf", inv, ANY)
    assert pdf == b"processed_pdf"
