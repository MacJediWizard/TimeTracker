"""Smoke test for the signoff PDF generator. Confirms the renderer
produces a non-empty PDF and deterministic SignatureAreas with sample
data — protects against regressions in palette/font/logo defaults."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace

from app.utils.timesheet_signoff_pdf import (
    SignatureAreas,
    SignoffData,
    SignoffTemplate,
    build_signoff_pdf,
    default_preview_template,
)


def _sample_data() -> SignoffData:
    monday = date(2026, 5, 4)
    friday = monday + timedelta(days=4)

    def entry(day_offset, h_start, h_end, project, task, notes):
        start = datetime.combine(
            monday + timedelta(days=day_offset), datetime.min.time()
        )
        return SimpleNamespace(
            start_time=start.replace(hour=h_start),
            end_time=start.replace(hour=h_end),
            duration_seconds=(h_end - h_start) * 3600,
            project=SimpleNamespace(name=project),
            task=SimpleNamespace(name=task),
            notes=notes,
            billable=True,
        )

    return SignoffData(
        my_company_name="Test Company",
        client_name="Acme Test",
        engineer_name="Alice Test",
        engagement_name="Test Engagement",
        period_start=monday,
        period_end=friday,
        entries=[
            entry(0, 9, 12, "Project A", "Task 1", "Notes 1"),
            entry(0, 13, 17, "Project A", "Task 2", "Notes 2"),
            entry(1, 9, 17, "Project B", "Task 3", "Notes 3"),
        ],
    )


def test_renders_non_empty_pdf():
    data = _sample_data()
    template = default_preview_template()
    pdf_bytes, _sig = build_signoff_pdf(data, template)
    assert isinstance(pdf_bytes, (bytes, bytearray))
    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF-")


def test_returns_valid_signature_areas():
    data = _sample_data()
    template = default_preview_template()
    _pdf, sig = build_signoff_pdf(data, template)
    assert isinstance(sig, SignatureAreas)
    assert sig.page_index >= 0
    for area in (sig.signature, sig.name, sig.title, sig.date):
        assert len(area) == 4
        x, y, w, h = area
        assert all(isinstance(v, (int, float)) for v in (x, y, w, h))
        assert w > 0 and h > 0


def test_custom_palette_applied():
    """Template colors flow through — pdf bytes differ when primary
    color changes."""
    data = _sample_data()
    template_a = SignoffTemplate(
        primary_color_hex="#c41e3a",
        accent_color_hex="#1a1a1a",
        columns_to_show=["time", "duration", "project", "task", "notes"],
    )
    template_b = SignoffTemplate(
        primary_color_hex="#0066cc",
        accent_color_hex="#1a1a1a",
        columns_to_show=["time", "duration", "project", "task", "notes"],
    )
    pdf_a, _ = build_signoff_pdf(data, template_a)
    pdf_b, _ = build_signoff_pdf(data, template_b)
    assert pdf_a != pdf_b


def test_empty_entries_renders_pdf():
    """No time entries (edge case: empty week) still renders without crash."""
    data = SignoffData(
        my_company_name="Test",
        client_name="Acme",
        engineer_name="Alice",
        engagement_name="",
        period_start=date(2026, 5, 4),
        period_end=date(2026, 5, 8),
        entries=[],
    )
    pdf_bytes, sig = build_signoff_pdf(data, default_preview_template())
    assert pdf_bytes.startswith(b"%PDF-")
    assert sig.page_index >= 0
