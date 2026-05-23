"""
Client-facing timesheet signoff PDF.

Renders a single-engineer, single-client, single-period timesheet for
e-signature by the client's approver. Palette, fonts, and logo are all
template-driven so each client can have their own branding applied at
render time without forking this module. The signature block is forced
onto its own last page via a ``PageBreak()`` so DocuSeal field
coordinates are deterministic regardless of how many entries flowed.

Run this module directly via ``/tmp/render_signoff_mock.py`` to produce
a sample PDF at ``/tmp/timesheet_signoff_mock.pdf`` for visual review.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

FONT_SIZE = 9
HEADER_FONT_SIZE = 10
DATE_GROUP_FONT_SIZE = 9
CELL_PAD_H = 6
CELL_PAD_V = 5
HEADER_PAD_V = 7

PAGE_SIZE = landscape(A4)
MARGIN = 1.0 * cm
BOTTOM_MARGIN = 1.2 * cm
USABLE_WIDTH_CM = 27.7

DEFAULT_COL_WIDTHS_CM = {
    "time": 3.6,
    "duration": 2.0,
    "project": 5.5,
    "task": 5.0,
    "notes": 11.6,
}
DEFAULT_COLUMN_LABELS = {
    "time": "Time",
    "duration": "Duration",
    "project": "Project",
    "task": "Task",
    "notes": "Notes",
    "billable": "Billable",
}


@dataclass
class SignatureAreas:
    """Coordinates DocuSeal needs to overlay signature fields. PDF points
    from the bottom-left of the page. ``page_index`` is zero-indexed and
    set post-build because total page count depends on entry flow."""

    signature: tuple[float, float, float, float]
    name: tuple[float, float, float, float]
    title: tuple[float, float, float, float]
    date: tuple[float, float, float, float]
    page_index: int = -1


@dataclass
class SignoffTemplate:
    """Per-client / global PDF customization. In production loaded from
    ``timesheet_signoff_templates`` rows; here a plain dataclass."""

    # Content knobs
    intro_markdown: str = ""
    terms_markdown: str = ""
    columns_to_show: list[str] = field(default_factory=lambda: ["time", "duration", "project", "task", "notes"])
    show_billable: bool = False
    show_daily_totals: bool = True
    signature_block_label: str = "Approved by Project Manager"

    # Colors
    primary_color_hex: str = "#c41e3a"
    accent_color_hex: str = "#1a1a1a"

    # Logo (uploaded via admin UI; stored at uploads/branding/)
    logo_path: str | None = None
    logo_position: str = "left"
    logo_max_height_pt: float = 32.0
    logo_opacity: float = 1.0  # 0.0 = invisible, 1.0 = full; admin slider

    # Body font — Roboto for the user. Falls back to Helvetica when no TTF.
    body_font_name: str | None = None
    body_font_regular_path: str | None = None
    body_font_bold_path: str | None = None
    body_font_italic_path: str | None = None
    body_font_bold_italic_path: str | None = None

    # Display font — Orbitron for the user. For titles + headings only.
    display_font_name: str | None = None
    display_font_regular_path: str | None = None
    display_font_bold_path: str | None = None


@dataclass
class SignoffData:
    """Inputs to the renderer. In production assembled from
    ``TimesheetSignoffRequest`` + related rows."""

    my_company_name: str
    client_name: str
    engineer_name: str
    engagement_name: str
    period_start: date
    period_end: date
    entries: list


@dataclass
class _Theme:
    """Render-time palette + font names. Derived from a SignoffTemplate."""

    brand: colors.Color
    accent: colors.Color
    header_bg: colors.Color
    header_fg: colors.Color
    row_alt_bg: colors.Color
    row_normal_bg: colors.Color
    grid_light: colors.Color
    grid_dark: colors.Color
    totals_bg: colors.Color
    totals_fg: colors.Color
    muted_text: colors.Color
    callout_bg: colors.Color
    sig_line: colors.Color
    placeholder_text: colors.Color

    body_regular: str
    body_bold: str
    body_italic: str
    body_bold_italic: str
    display_regular: str
    display_bold: str


# ---------------------------------------------------------------------------
# Font + theme resolution
# ---------------------------------------------------------------------------


def _register_fonts(template: SignoffTemplate) -> None:
    """Register any TTFs the template references with ReportLab. Silent
    no-op for paths that don't exist on disk — the theme resolver will
    fall back to Helvetica for the variant in that case."""

    def _safe_register(name: str, path: str | None) -> bool:
        if not name or not path:
            return False
        if not Path(path).is_file():
            return False
        try:
            pdfmetrics.registerFont(TTFont(name, path))
            return True
        except Exception:
            return False

    if template.body_font_name:
        base = template.body_font_name
        _safe_register(base, template.body_font_regular_path)
        _safe_register(f"{base}-Bold", template.body_font_bold_path)
        _safe_register(f"{base}-Italic", template.body_font_italic_path)
        _safe_register(f"{base}-BoldItalic", template.body_font_bold_italic_path)
        pdfmetrics.registerFontFamily(
            base,
            normal=base if _font_registered(base) else "Helvetica",
            bold=(
                f"{base}-Bold"
                if _font_registered(f"{base}-Bold")
                else (base if _font_registered(base) else "Helvetica-Bold")
            ),
            italic=(
                f"{base}-Italic"
                if _font_registered(f"{base}-Italic")
                else (base if _font_registered(base) else "Helvetica-Oblique")
            ),
            boldItalic=(
                f"{base}-BoldItalic"
                if _font_registered(f"{base}-BoldItalic")
                else (base if _font_registered(base) else "Helvetica-BoldOblique")
            ),
        )

    if template.display_font_name:
        base = template.display_font_name
        _safe_register(base, template.display_font_regular_path)
        _safe_register(f"{base}-Bold", template.display_font_bold_path)


def _font_registered(name: str) -> bool:
    return name in pdfmetrics.getRegisteredFontNames()


def _build_theme(template: SignoffTemplate) -> _Theme:
    brand = colors.HexColor(template.primary_color_hex)
    accent = colors.HexColor(template.accent_color_hex)

    body_name = template.body_font_name
    if body_name and _font_registered(body_name):
        body_regular = body_name
        body_bold = f"{body_name}-Bold" if _font_registered(f"{body_name}-Bold") else body_name
        body_italic = f"{body_name}-Italic" if _font_registered(f"{body_name}-Italic") else body_name
        body_bold_italic = f"{body_name}-BoldItalic" if _font_registered(f"{body_name}-BoldItalic") else body_bold
    else:
        body_regular = "Helvetica"
        body_bold = "Helvetica-Bold"
        body_italic = "Helvetica-Oblique"
        body_bold_italic = "Helvetica-BoldOblique"

    display_name = template.display_font_name
    if display_name and _font_registered(display_name):
        display_regular = display_name
        display_bold = f"{display_name}-Bold" if _font_registered(f"{display_name}-Bold") else display_name
    else:
        display_regular = body_bold
        display_bold = body_bold

    return _Theme(
        brand=brand,
        accent=accent,
        header_bg=accent,
        header_fg=colors.white,
        row_alt_bg=colors.HexColor("#f5f5f5"),
        row_normal_bg=colors.white,
        grid_light=colors.HexColor("#e5e5e5"),
        grid_dark=colors.HexColor("#262626"),
        totals_bg=brand,
        totals_fg=colors.white,
        muted_text=colors.HexColor("#525252"),
        callout_bg=colors.HexColor("#fafafa"),
        sig_line=colors.HexColor("#a3a3a3"),
        placeholder_text=colors.HexColor("#cbd5e1"),
        body_regular=body_regular,
        body_bold=body_bold,
        body_italic=body_italic,
        body_bold_italic=body_bold_italic,
        display_regular=display_regular,
        display_bold=display_bold,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_time(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.strftime("%H:%M")


def _fmt_date_group(d: date) -> str:
    return d.strftime("%A, %Y-%m-%d")


def _fmt_date(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _duration_hhmm(seconds: int) -> str:
    if not seconds or seconds < 0:
        return "00:00"
    minutes = int(seconds) // 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _safe(value, fallback: str = "") -> str:
    if value is None:
        return fallback
    s = str(value).strip()
    return s if s else fallback


def _wrap_cell(text, theme: _Theme):
    s = _safe(text)
    if not s:
        return ""
    escaped = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    style = ParagraphStyle(
        "NotesCell",
        fontName=theme.body_regular,
        fontSize=FONT_SIZE,
        leading=FONT_SIZE + 2,
        alignment=TA_LEFT,
        wordWrap="CJK",
        splitLongWords=True,
    )
    return Paragraph(escaped, style)


def _group_by_date(entries) -> "OrderedDict[date, list]":
    grouped: OrderedDict = OrderedDict()
    for e in entries:
        d = e.start_time.date() if e.start_time else None
        grouped.setdefault(d, []).append(e)
    return grouped


def _prepare_logo_path(template: SignoffTemplate) -> str | None:
    """Return path to a renderable logo. If logo_opacity < 1.0, writes a
    faded copy to /tmp and returns that path instead. Keeps the original
    upload untouched."""
    src = template.logo_path
    if not src or not Path(src).is_file():
        return None
    if template.logo_opacity >= 0.999:
        return src
    try:
        from PIL import Image as PILImage
    except ImportError:
        return src
    try:
        img = PILImage.open(src).convert("RGBA")
        alpha = img.split()[-1].point(lambda p: int(p * template.logo_opacity))
        img.putalpha(alpha)
        out = Path("/tmp") / f"_signoff_logo_{int(template.logo_opacity * 100)}_{Path(src).name}"
        img.save(out)
        return str(out)
    except Exception:
        return src


def _logo_flowable(template: SignoffTemplate):
    path = _prepare_logo_path(template)
    if not path:
        return None
    try:
        img = Image(path)
        h = template.logo_max_height_pt
        ratio = img.imageWidth / img.imageHeight
        img.drawHeight = h
        img.drawWidth = h * ratio
        return img
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _build_top_bar(data: SignoffData, template: SignoffTemplate, theme: _Theme) -> list:
    company_style = ParagraphStyle(
        "TopBarCompany",
        fontName=theme.display_bold,
        fontSize=12,
        leading=15,
        textColor=theme.accent,
    )
    title_style = ParagraphStyle(
        "TopBarTitle",
        fontName=theme.display_bold,
        fontSize=16,
        leading=20,
        textColor=theme.brand,
        alignment=TA_CENTER,
    )
    period_style = ParagraphStyle(
        "TopBarPeriod",
        fontName=theme.body_regular,
        fontSize=9,
        leading=12,
        textColor=theme.muted_text,
        alignment=TA_RIGHT,
    )

    period_label = (
        f'Period<br/><font name="{theme.body_bold}" color="{template.accent_color_hex}">'
        f"{_fmt_date(data.period_start)} → {_fmt_date(data.period_end)}</font>"
    )

    logo = _logo_flowable(template)
    wordmark = Paragraph(data.my_company_name, company_style)
    if logo is not None:
        left_cell = Table(
            [[logo, wordmark]],
            colWidths=[logo.drawWidth + 8, None],
        )
        left_cell.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
    else:
        left_cell = wordmark

    cells = [
        [
            left_cell,
            Paragraph("TIMESHEET FOR APPROVAL", title_style),
            Paragraph(period_label, period_style),
        ]
    ]
    third = USABLE_WIDTH_CM * cm / 3.0
    table = Table(cells, colWidths=[third, third, third])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    accent_line = Table([[""]], colWidths=[USABLE_WIDTH_CM * cm], rowHeights=[2.5])
    accent_line.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), theme.brand),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    return [table, Spacer(1, 4), accent_line, Spacer(1, 12)]


def _build_engagement_card(data: SignoffData, theme: _Theme) -> list:
    label_style = ParagraphStyle(
        "CardLabel",
        fontName=theme.body_bold,
        fontSize=7.5,
        leading=10,
        textColor=theme.muted_text,
    )
    value_style = ParagraphStyle(
        "CardValue",
        fontName=theme.body_bold,
        fontSize=12,
        leading=15,
        textColor=theme.accent,
    )
    total_value_style = ParagraphStyle(
        "TotalCardValue",
        fontName=theme.body_bold,
        fontSize=14,
        leading=17,
        textColor=theme.brand,
    )

    total_seconds = sum(getattr(e, "duration_seconds", 0) or 0 for e in data.entries)
    cells = [
        [
            Paragraph("ENGINEER", label_style),
            Paragraph("CLIENT", label_style),
            Paragraph("ENGAGEMENT", label_style),
            Paragraph("TOTAL HOURS", label_style),
        ],
        [
            Paragraph(data.engineer_name, value_style),
            Paragraph(data.client_name, value_style),
            Paragraph(data.engagement_name or "—", value_style),
            Paragraph(_duration_hhmm(total_seconds), total_value_style),
        ],
    ]
    col_widths = [
        USABLE_WIDTH_CM * 0.30 * cm,
        USABLE_WIDTH_CM * 0.25 * cm,
        USABLE_WIDTH_CM * 0.30 * cm,
        USABLE_WIDTH_CM * 0.15 * cm,
    ]
    table = Table(cells, colWidths=col_widths)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), theme.callout_bg),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
                ("TOPPADDING", (0, 1), (-1, 1), 0),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
                ("LINEABOVE", (0, 0), (-1, 0), 2.5, theme.brand),
                ("LINEBELOW", (0, 1), (-1, 1), 0.5, theme.grid_light),
            ]
        )
    )
    return [table, Spacer(1, 12)]


def _build_intro(template: SignoffTemplate, theme: _Theme) -> list:
    style = ParagraphStyle(
        "Intro",
        fontName=theme.body_regular,
        fontSize=10,
        leading=14,
        textColor=theme.accent,
    )
    return [Paragraph(template.intro_markdown, style), Spacer(1, 10)]


def _build_entries_table(data: SignoffData, template: SignoffTemplate, theme: _Theme) -> list:
    columns = list(template.columns_to_show)
    if template.show_billable and "billable" not in columns:
        columns.append("billable")

    col_widths = [DEFAULT_COL_WIDTHS_CM.get(c, 3.0) * cm for c in columns]
    if columns:
        scale = (USABLE_WIDTH_CM * cm) / sum(col_widths)
        col_widths = [w * scale for w in col_widths]

    headers = [DEFAULT_COLUMN_LABELS[c] for c in columns]
    story: list = []
    grouped = _group_by_date(data.entries)

    for date_key, entries in grouped.items():
        date_style = ParagraphStyle(
            "DateGroup",
            fontName=theme.display_bold,
            fontSize=DATE_GROUP_FONT_SIZE + 1,
            leading=DATE_GROUP_FONT_SIZE + 4,
            textColor=theme.brand,
        )
        story.append(Spacer(1, 6))
        story.append(Paragraph(_fmt_date_group(date_key), date_style))
        story.append(Spacer(1, 3))

        rows = [headers]
        day_seconds = 0
        for entry in entries:
            dur_sec = getattr(entry, "duration_seconds", 0) or 0
            day_seconds += dur_sec

            time_range = _fmt_time(entry.start_time)
            if entry.end_time:
                time_range += f" – {_fmt_time(entry.end_time)}"

            cell = {
                "time": time_range or " ",
                "duration": _duration_hhmm(dur_sec),
                "project": _wrap_cell(entry.project.name if entry.project else "", theme),
                "task": _wrap_cell(entry.task.name if entry.task else "", theme),
                "notes": _wrap_cell(entry.notes, theme),
                "billable": "✓" if entry.billable else "—",
            }
            rows.append([cell[c] if cell[c] != "" else " " for c in columns])

        if template.show_daily_totals:
            totals_row = [""] * len(columns)
            if "duration" in columns:
                totals_row[columns.index("duration")] = _duration_hhmm(day_seconds)
            label_col = "task" if "task" in columns else ("project" if "project" in columns else columns[0])
            totals_row[columns.index(label_col)] = Paragraph(
                "<i>Day total</i>",
                ParagraphStyle(
                    "DayTotal",
                    fontName=theme.body_italic,
                    fontSize=FONT_SIZE,
                    leading=FONT_SIZE + 2,
                    textColor=theme.muted_text,
                    alignment=TA_RIGHT,
                ),
            )
            rows.append(totals_row)

        table = Table(rows, colWidths=col_widths, repeatRows=1)
        style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), theme.header_bg),
            ("TEXTCOLOR", (0, 0), (-1, 0), theme.header_fg),
            ("FONTNAME", (0, 0), (-1, 0), theme.display_bold),
            ("FONTSIZE", (0, 0), (-1, 0), HEADER_FONT_SIZE),
            ("TOPPADDING", (0, 0), (-1, 0), HEADER_PAD_V),
            ("BOTTOMPADDING", (0, 0), (-1, 0), HEADER_PAD_V),
            ("LINEBELOW", (0, 0), (-1, 0), 2.0, theme.brand),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("LEFTPADDING", (0, 0), (-1, -1), CELL_PAD_H),
            ("RIGHTPADDING", (0, 0), (-1, -1), CELL_PAD_H),
            ("TOPPADDING", (0, 1), (-1, -1), CELL_PAD_V),
            ("BOTTOMPADDING", (0, 1), (-1, -1), CELL_PAD_V),
            ("FONTNAME", (0, 1), (-1, -1), theme.body_regular),
            ("FONTSIZE", (0, 1), (-1, -1), FONT_SIZE),
            ("LINEBELOW", (0, 0), (-1, -2), 0.5, theme.grid_light),
            ("BOX", (0, 0), (-1, -1), 0.75, theme.grid_dark),
        ]
        if "duration" in columns:
            d_idx = columns.index("duration")
            style_cmds.append(("ALIGN", (d_idx, 1), (d_idx, -1), "CENTER"))
        if "billable" in columns:
            b_idx = columns.index("billable")
            style_cmds.append(("ALIGN", (b_idx, 0), (b_idx, -1), "CENTER"))

        data_start = 1
        data_end = len(rows) - (2 if template.show_daily_totals else 1)
        for offset, row_num in enumerate(range(data_start, data_end + 1)):
            bg = theme.row_alt_bg if offset % 2 == 1 else theme.row_normal_bg
            style_cmds.append(("BACKGROUND", (0, row_num), (-1, row_num), bg))
        if template.show_daily_totals:
            last = len(rows) - 1
            style_cmds.append(("BACKGROUND", (0, last), (-1, last), theme.callout_bg))
            style_cmds.append(("LINEABOVE", (0, last), (-1, last), 1.0, theme.brand))

        table.setStyle(TableStyle(style_cmds))
        story.append(KeepTogether([table]) if len(rows) <= 6 else table)

    return story


def _build_grand_total(data: SignoffData, theme: _Theme) -> list:
    total_seconds = sum(getattr(e, "duration_seconds", 0) or 0 for e in data.entries)
    billable_seconds = sum((getattr(e, "duration_seconds", 0) or 0) for e in data.entries if e.billable)
    entry_count = len(data.entries)

    summary_style = ParagraphStyle(
        "SummaryLabel",
        fontName=theme.body_bold,
        fontSize=10,
        leading=13,
        textColor=theme.totals_fg,
    )
    cells = [
        [
            Paragraph(f"Entries: {entry_count}", summary_style),
            Paragraph(f"Total: {_duration_hhmm(total_seconds)}", summary_style),
            Paragraph(f"Billable: {_duration_hhmm(billable_seconds)}", summary_style),
        ]
    ]
    third = USABLE_WIDTH_CM / 3.0
    summary = Table(cells, colWidths=[third * cm] * 3)
    summary.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), theme.totals_bg),
                ("TEXTCOLOR", (0, 0), (-1, -1), theme.totals_fg),
                ("ALIGN", (0, 0), (0, 0), "LEFT"),
                ("ALIGN", (1, 0), (1, 0), "CENTER"),
                ("ALIGN", (2, 0), (2, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return [Spacer(1, 14), summary]


def _build_terms(template: SignoffTemplate, theme: _Theme) -> list:
    style = ParagraphStyle(
        "Terms",
        fontName=theme.body_italic,
        fontSize=8,
        leading=11,
        textColor=theme.muted_text,
    )
    return [Spacer(1, 14), Paragraph(template.terms_markdown, style)]


def _build_signature_block(data: SignoffData, template: SignoffTemplate, theme: _Theme) -> list:
    title_style = ParagraphStyle(
        "SigTitle",
        fontName=theme.display_bold,
        fontSize=16,
        leading=20,
        textColor=theme.brand,
        alignment=TA_CENTER,
    )
    note_style = ParagraphStyle(
        "SigNote",
        fontName=theme.body_regular,
        fontSize=10,
        leading=14,
        textColor=theme.accent,
        alignment=TA_CENTER,
    )
    label_style = ParagraphStyle(
        "SigFieldLabel",
        fontName=theme.body_bold,
        fontSize=9,
        leading=11,
        textColor=theme.muted_text,
    )

    story = []
    story.append(Spacer(1, 30))
    story.append(Paragraph(template.signature_block_label, title_style))
    story.append(Spacer(1, 12))

    intro_text = (
        f"By signing below I, as authorised approver for "
        f'<font name="{theme.body_bold}" color="{template.primary_color_hex}">{data.client_name}</font>, '
        f"confirm that the time entries above accurately reflect work performed by "
        f'<font name="{theme.body_bold}" color="{template.accent_color_hex}">{data.engineer_name}</font> '
        f"during the period "
        f'<font name="{theme.body_bold}" color="{template.accent_color_hex}">'
        f"{_fmt_date(data.period_start)} to {_fmt_date(data.period_end)}</font>."
    )
    story.append(Paragraph(intro_text, note_style))
    story.append(Spacer(1, 40))

    placeholder_style = ParagraphStyle(
        "FieldPlaceholder",
        fontName=theme.body_italic,
        fontSize=8,
        leading=10,
        textColor=theme.placeholder_text,
        alignment=TA_CENTER,
    )

    def field_cell(label: str, height_pt: float) -> Table:
        inner = Table(
            [
                [
                    Paragraph(
                        "[ signature field — DocuSeal overlays here ]",
                        placeholder_style,
                    )
                ]
            ],
            colWidths=[None],
            rowHeights=[height_pt],
        )
        inner.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.75, theme.sig_line),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fafafa")),
                ]
            )
        )
        wrapper = Table([[Paragraph(label, label_style)], [inner]], colWidths=[None])
        wrapper.setStyle(
            TableStyle(
                [
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, 0), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
                    ("TOPPADDING", (0, 1), (-1, 1), 0),
                    ("BOTTOMPADDING", (0, 1), (-1, 1), 0),
                ]
            )
        )
        return wrapper

    layout = Table(
        [[field_cell("SIGNATURE", 70), field_cell("DATE SIGNED", 70)]],
        colWidths=[USABLE_WIDTH_CM * 0.65 * cm, USABLE_WIDTH_CM * 0.32 * cm],
    )
    layout.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 12),
                ("LEFTPADDING", (1, 0), (1, 0), 0),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
            ]
        )
    )
    story.append(layout)
    story.append(Spacer(1, 16))

    name_title = Table(
        [[field_cell("PRINTED NAME", 30), field_cell("TITLE", 30)]],
        colWidths=[USABLE_WIDTH_CM * 0.48 * cm, USABLE_WIDTH_CM * 0.48 * cm],
    )
    name_title.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 12),
                ("LEFTPADDING", (1, 0), (1, 0), 0),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
            ]
        )
    )
    story.append(name_title)
    story.append(Spacer(1, 30))

    audit_style = ParagraphStyle(
        "SigAudit",
        fontName=theme.body_regular,
        fontSize=7,
        leading=10,
        textColor=theme.muted_text,
        alignment=TA_CENTER,
    )
    story.append(
        Paragraph(
            "Electronic signature handled by DocuSeal. A Certificate of Completion "
            "containing IP address, user-agent, view/sign timestamps, and signer "
            "identity verification is generated automatically and attached to the "
            "signed document.",
            audit_style,
        )
    )

    return story


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _page_footer_factory(theme: _Theme):
    def _page_footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(theme.body_regular, 7)
        canvas.setFillColor(theme.muted_text)
        canvas.drawRightString(doc.pagesize[0] - MARGIN, 0.5 * cm, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    return _page_footer


def build_signoff_pdf(data: SignoffData, template: SignoffTemplate | None = None) -> tuple[bytes, SignatureAreas]:
    """Return ``(pdf_bytes, sig_areas)``."""
    template = template or SignoffTemplate()
    _register_fonts(template)
    theme = _build_theme(template)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=PAGE_SIZE,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=BOTTOM_MARGIN,
        title=f"Timesheet — {data.engineer_name} — {data.client_name}",
        author=data.my_company_name,
    )

    story: list = []
    story.extend(_build_top_bar(data, template, theme))
    story.extend(_build_engagement_card(data, theme))
    if template.intro_markdown:
        story.extend(_build_intro(template, theme))
    story.extend(_build_entries_table(data, template, theme))
    story.extend(_build_grand_total(data, theme))
    if template.terms_markdown:
        story.extend(_build_terms(template, theme))
    story.append(PageBreak())
    story.extend(_build_signature_block(data, template, theme))

    footer = _page_footer_factory(theme)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)

    sig_areas = SignatureAreas(
        signature=(36, 280, 480, 70),
        date=(560, 280, 240, 70),
        name=(36, 195, 380, 30),
        title=(420, 195, 380, 30),
        page_index=max(doc.page - 1, 0),
    )

    buffer.seek(0)
    return buffer.getvalue(), sig_areas


# ---------------------------------------------------------------------------
# Sample-data harness
# ---------------------------------------------------------------------------


def _sample_data() -> SignoffData:
    def entry(start_h, start_m, end_h, end_m, project, task, notes, billable=True):
        start = datetime(2026, 5, 4) + timedelta(days=entry.day_offset)
        start = start.replace(hour=start_h, minute=start_m)
        end = start.replace(hour=end_h, minute=end_m)
        return SimpleNamespace(
            start_time=start,
            end_time=end,
            duration_seconds=int((end - start).total_seconds()),
            project=SimpleNamespace(name=project),
            task=SimpleNamespace(name=task),
            notes=notes,
            billable=billable,
        )

    entries = []

    entry.day_offset = 0
    entries.append(
        entry(
            9,
            0,
            12,
            30,
            "Data Pipeline",
            "ETL refactor",
            "Replaced legacy Airflow DAGs with the new dbt-based ingestion path; "
            "verified parity on 2024 archive backfill.",
        )
    )
    entries.append(
        entry(
            13,
            30,
            17,
            30,
            "Data Pipeline",
            "Code review",
            "Reviewed pull requests #412, #418, #421 from the offshore team; "
            "left comments on schema-evolution edge cases.",
        )
    )

    entry.day_offset = 1
    entries.append(
        entry(
            9,
            15,
            12,
            0,
            "Data Pipeline",
            "Schema migration",
            "Ran the production migration adding the dim_customer SCD2 columns; "
            "backfilled 14M historical rows in 41 minutes.",
        )
    )
    entries.append(
        entry(
            13,
            0,
            18,
            30,
            "Data Pipeline",
            "Incident response",
            "Investigated pager: dim_account null-rate jumped to 3.2%. Root cause "
            "was an upstream Salesforce field rename; coordinated fix with their "
            "team and re-ran the affected partitions.",
        )
    )

    entry.day_offset = 2
    entries.append(
        entry(
            8,
            30,
            12,
            0,
            "Reporting Layer",
            "Looker model build",
            "Built the Revenue by Segment explore against the new dim_customer "
            "dimension; validated totals against finance close numbers.",
        )
    )
    entries.append(
        entry(
            13,
            0,
            17,
            0,
            "Reporting Layer",
            "Stakeholder meeting",
            "Quarterly review with FP&A leadership; walked through the new "
            "attribution methodology and gathered three feature requests for next sprint.",
        )
    )

    entry.day_offset = 3
    entries.append(
        entry(
            9,
            0,
            13,
            0,
            "Data Pipeline",
            "Documentation",
            "Wrote the runbook for the new ingestion pipeline; covered failure modes, "
            "on-call rotation, escalation paths, and SLO definitions.",
        )
    )
    entries.append(
        entry(
            14,
            0,
            17,
            30,
            "Data Pipeline",
            "Pair programming",
            "Paired with Jordan on the customer-360 join optimization; reduced query "
            "time from 47s to 8s by partitioning correctly.",
        )
    )

    entry.day_offset = 4
    entries.append(
        entry(
            9,
            30,
            12,
            30,
            "Data Pipeline",
            "Sprint planning",
            "Sprint retro and planning for the next two-week cycle; committed to 3 " "stories totalling 21 points.",
        )
    )
    entries.append(
        entry(
            13,
            30,
            16,
            30,
            "Reporting Layer",
            "Bug fix",
            "Fixed off-by-one in the rolling 28-day active-user metric; deployed and " "verified in production.",
        )
    )

    return SignoffData(
        my_company_name="MacJediWizard Consulting",
        client_name="Acme Corp",
        engineer_name="Alice Chen",
        engagement_name="Data Platform Modernisation",
        period_start=date(2026, 5, 4),
        period_end=date(2026, 5, 8),
        entries=entries,
    )


def default_preview_template() -> SignoffTemplate:
    """Generic default template used by the admin preview route when an
    in-flight template form has not yet been saved. Returns sensible
    fallback content with no client-specific branding. Real templates
    are persisted in ``timesheet_signoff_templates`` and built from DB
    rows by the service layer."""
    return SignoffTemplate(
        intro_markdown=(
            "Please review the time entries below for accuracy and sign at the "
            "bottom to authorise billing for this period. If anything is "
            "incorrect, decline the request with a note and we will reissue."
        ),
        terms_markdown=(
            "This document constitutes an electronic record under the U.S. "
            "Electronic Signatures in Global and National Commerce Act (E-SIGN) "
            "and equivalent local statutes. The signing party affirms they are "
            "authorised to approve timesheets on behalf of the client. Disputes "
            "must be raised within 30 days of signing per the Master Services "
            "Agreement."
        ),
        columns_to_show=["time", "duration", "project", "task", "notes"],
        show_billable=False,
        show_daily_totals=True,
        signature_block_label="Client Approval",
    )


# Backwards-compat alias for the standalone runner at /tmp/.
_sample_template = default_preview_template
