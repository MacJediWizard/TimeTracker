"""Admin routes for managing timesheet signoff templates and the
branding assets (logo + TTF fonts) they reference.

Surfaces:
- ``GET  /admin/signoff-templates``                — list page
- ``GET  /admin/signoff-templates/new``            — create form
- ``POST /admin/signoff-templates/new``            — create
- ``GET  /admin/signoff-templates/<id>``           — edit form
- ``POST /admin/signoff-templates/<id>``           — update
- ``POST /admin/signoff-templates/<id>/archive``   — soft-delete
- ``POST /admin/signoff-templates/<id>/restore``   — undo archive
- ``GET  /admin/signoff-templates/<id>/preview``   — inline sample PDF
- ``POST /admin/signoff-templates/<id>/preview``   — inline preview using
                                                    in-flight form state
- ``POST /admin/branding-assets/upload``           — multipart upload
                                                    (logo PNG/SVG or TTF font)

Permission-gated to admins. Uploads land in
``<UPLOAD_FOLDER>/branding/{uuid}.{ext}`` with the original filename
preserved on the ``branding_assets`` row for display purposes."""

from __future__ import annotations

import io
import logging
import uuid
from datetime import datetime
from pathlib import Path

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app import db
from app.models.branding_asset import BrandingAsset
from app.models.timesheet_signoff_template import TimesheetSignoffTemplate
from app.utils.permissions import admin_or_permission_required
from app.utils.timesheet_signoff_pdf import SignoffData, SignoffTemplate, build_signoff_pdf

signoff_templates_bp = Blueprint("signoff_templates", __name__)
_log = logging.getLogger(__name__)


_ALLOWED_LOGO_EXT = {".png", ".jpg", ".jpeg", ".svg", ".webp"}
_ALLOWED_FONT_EXT = {".ttf", ".otf"}
_VALID_COLUMNS = {"time", "duration", "project", "task", "notes", "billable"}
_VALID_LOGO_POSITIONS = {"left", "center", "right"}


def _branding_dir() -> Path:
    root = Path(current_app.config.get("UPLOAD_FOLDER", "/data/uploads"))
    out = root / "branding"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _hex_color(value: str | None, fallback: str) -> str:
    if not value:
        return fallback
    v = value.strip()
    if (
        len(v) == 7
        and v[0] == "#"
        and all(c in "0123456789abcdefABCDEF" for c in v[1:])
    ):
        return v.lower()
    return fallback


def _parse_columns(form) -> list[str]:
    selected = form.getlist("columns_to_show") if hasattr(form, "getlist") else []
    out = [c for c in selected if c in _VALID_COLUMNS]
    if not out:
        out = ["time", "duration", "project", "task", "notes"]
    return out


def _form_to_template_kwargs(form) -> dict:
    return {
        "name": (form.get("name") or "").strip(),
        "is_default": form.get("is_default") == "on",
        "intro_markdown": (form.get("intro_markdown") or "").strip() or None,
        "terms_markdown": (form.get("terms_markdown") or "").strip() or None,
        "columns_to_show": _parse_columns(form),
        "show_billable": form.get("show_billable") == "on",
        "show_daily_totals": form.get("show_daily_totals") == "on",
        "signature_block_label": (
            (form.get("signature_block_label") or "").strip()
            or "Approved by Project Manager"
        ),
        "primary_color_hex": _hex_color(form.get("primary_color_hex"), "#c41e3a"),
        "accent_color_hex": _hex_color(form.get("accent_color_hex"), "#1a1a1a"),
        "logo_asset_id": _opt_int(form.get("logo_asset_id")),
        "logo_position": (
            (form.get("logo_position") or "left").strip().lower()
            if (form.get("logo_position") or "left").strip().lower()
            in _VALID_LOGO_POSITIONS
            else "left"
        ),
        "logo_max_height_pt": _opt_float(form.get("logo_max_height_pt"), 32.0),
        "logo_opacity": max(0.0, min(1.0, _opt_float(form.get("logo_opacity"), 1.0))),
        "body_font_name": (form.get("body_font_name") or "").strip() or None,
        "body_font_regular_asset_id": _opt_int(form.get("body_font_regular_asset_id")),
        "body_font_bold_asset_id": _opt_int(form.get("body_font_bold_asset_id")),
        "body_font_italic_asset_id": _opt_int(form.get("body_font_italic_asset_id")),
        "body_font_bold_italic_asset_id": _opt_int(
            form.get("body_font_bold_italic_asset_id")
        ),
        "display_font_name": (form.get("display_font_name") or "").strip() or None,
        "display_font_regular_asset_id": _opt_int(
            form.get("display_font_regular_asset_id")
        ),
        "display_font_bold_asset_id": _opt_int(form.get("display_font_bold_asset_id")),
    }


def _opt_int(value) -> int | None:
    if value in (None, "", "0"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _opt_float(value, fallback: float) -> float:
    if value in (None, ""):
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _clear_other_defaults(except_id: int | None = None) -> None:
    q = TimesheetSignoffTemplate.query.filter_by(is_default=True)
    if except_id is not None:
        q = q.filter(TimesheetSignoffTemplate.id != except_id)
    for other in q.all():
        other.is_default = False


def _assets_by_kind() -> dict[str, list[BrandingAsset]]:
    logos = (
        BrandingAsset.query.filter_by(kind=BrandingAsset.KIND_LOGO, archived_at=None)
        .order_by(BrandingAsset.uploaded_at.desc())
        .all()
    )
    fonts = (
        BrandingAsset.query.filter_by(
            kind=BrandingAsset.KIND_FONT_TTF, archived_at=None
        )
        .order_by(BrandingAsset.name.asc())
        .all()
    )
    return {"logos": logos, "fonts": fonts}


@signoff_templates_bp.route("/admin/signoff-templates")
@login_required
@admin_or_permission_required("manage_integrations")
def list_templates():
    templates = TimesheetSignoffTemplate.query.order_by(
        (
            TimesheetSignoffTemplate.archived_at.asc().nullsfirst()
            if hasattr(TimesheetSignoffTemplate.archived_at.asc(), "nullsfirst")
            else TimesheetSignoffTemplate.archived_at.asc()
        ),
        TimesheetSignoffTemplate.name.asc(),
    ).all()
    return render_template("admin/signoff_templates/list.html", templates=templates)


@signoff_templates_bp.route("/admin/signoff-templates/new", methods=["GET", "POST"])
@login_required
@admin_or_permission_required("manage_integrations")
def new_template():
    if request.method == "POST":
        kwargs = _form_to_template_kwargs(request.form)
        if not kwargs["name"]:
            flash(_("Template name is required"), "error")
            return render_template(
                "admin/signoff_templates/form.html",
                template=None,
                form_data=kwargs,
                assets=_assets_by_kind(),
            )

        template = TimesheetSignoffTemplate(**kwargs)
        db.session.add(template)
        try:
            db.session.flush()
            if kwargs["is_default"]:
                _clear_other_defaults(except_id=template.id)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            _log.exception("Failed to create signoff template")
            flash(_("Failed to create template: %(error)s", error=str(exc)), "error")
            return render_template(
                "admin/signoff_templates/form.html",
                template=None,
                form_data=kwargs,
                assets=_assets_by_kind(),
            )

        flash(_("Template '%(name)s' created", name=template.name), "success")
        return redirect(
            url_for("signoff_templates.edit_template", template_id=template.id)
        )

    return render_template(
        "admin/signoff_templates/form.html",
        template=None,
        form_data=None,
        assets=_assets_by_kind(),
    )


@signoff_templates_bp.route(
    "/admin/signoff-templates/<int:template_id>", methods=["GET", "POST"]
)
@login_required
@admin_or_permission_required("manage_integrations")
def edit_template(template_id: int):
    template = TimesheetSignoffTemplate.query.get_or_404(template_id)

    if request.method == "POST":
        kwargs = _form_to_template_kwargs(request.form)
        if not kwargs["name"]:
            flash(_("Template name is required"), "error")
            return render_template(
                "admin/signoff_templates/form.html",
                template=template,
                form_data=kwargs,
                assets=_assets_by_kind(),
            )

        for field, value in kwargs.items():
            setattr(template, field, value)
        template.updated_at = datetime.utcnow()

        try:
            if kwargs["is_default"]:
                _clear_other_defaults(except_id=template.id)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            _log.exception("Failed to update signoff template %s", template_id)
            flash(_("Failed to update template: %(error)s", error=str(exc)), "error")
            return render_template(
                "admin/signoff_templates/form.html",
                template=template,
                form_data=kwargs,
                assets=_assets_by_kind(),
            )

        flash(_("Template '%(name)s' updated", name=template.name), "success")
        return redirect(
            url_for("signoff_templates.edit_template", template_id=template.id)
        )

    return render_template(
        "admin/signoff_templates/form.html",
        template=template,
        form_data=None,
        assets=_assets_by_kind(),
    )


@signoff_templates_bp.post("/admin/signoff-templates/<int:template_id>/archive")
@login_required
@admin_or_permission_required("manage_integrations")
def archive_template(template_id: int):
    template = TimesheetSignoffTemplate.query.get_or_404(template_id)
    template.archived_at = datetime.utcnow()
    template.is_default = False
    db.session.commit()
    flash(_("Template '%(name)s' archived", name=template.name), "success")
    return redirect(url_for("signoff_templates.list_templates"))


@signoff_templates_bp.post("/admin/signoff-templates/<int:template_id>/restore")
@login_required
@admin_or_permission_required("manage_integrations")
def restore_template(template_id: int):
    template = TimesheetSignoffTemplate.query.get_or_404(template_id)
    template.archived_at = None
    db.session.commit()
    flash(_("Template '%(name)s' restored", name=template.name), "success")
    return redirect(url_for("signoff_templates.list_templates"))


@signoff_templates_bp.route(
    "/admin/signoff-templates/<int:template_id>/preview", methods=["GET", "POST"]
)
@login_required
@admin_or_permission_required("manage_integrations")
def preview_template(template_id: int):
    template = TimesheetSignoffTemplate.query.get_or_404(template_id)

    if request.method == "POST":
        overrides = _form_to_template_kwargs(request.form)
        signoff_template = _signoff_template_from_kwargs(overrides)
    else:
        from app.services.timesheet_signoff_service import TimesheetSignoffService

        signoff_template = TimesheetSignoffService.build_template_from_orm(template)

    sample = _sample_data_for_preview()
    pdf_bytes, _sig_areas = build_signoff_pdf(sample, signoff_template)
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=False,
        download_name=f"signoff-preview-{template_id}.pdf",
    )


def _signoff_template_from_kwargs(kwargs: dict) -> SignoffTemplate:
    """Translate the form/orm kwargs into the renderer dataclass.
    Mirrors ``TimesheetSignoffService.build_template_from_orm`` but
    accepts raw kwargs so unsaved form state can preview."""

    def asset_path(asset_id: int | None) -> str | None:
        if not asset_id:
            return None
        asset = BrandingAsset.query.get(asset_id)
        if not asset or asset.archived_at:
            return None
        return asset.file_path

    return SignoffTemplate(
        intro_markdown=kwargs.get("intro_markdown") or "",
        terms_markdown=kwargs.get("terms_markdown") or "",
        columns_to_show=list(kwargs.get("columns_to_show") or []),
        show_billable=bool(kwargs.get("show_billable")),
        show_daily_totals=bool(kwargs.get("show_daily_totals")),
        signature_block_label=kwargs.get("signature_block_label")
        or "Approved by Project Manager",
        primary_color_hex=kwargs.get("primary_color_hex") or "#c41e3a",
        accent_color_hex=kwargs.get("accent_color_hex") or "#1a1a1a",
        logo_path=asset_path(kwargs.get("logo_asset_id")),
        logo_position=kwargs.get("logo_position") or "left",
        logo_max_height_pt=kwargs.get("logo_max_height_pt") or 32.0,
        logo_opacity=kwargs.get("logo_opacity")
        if kwargs.get("logo_opacity") is not None
        else 1.0,
        body_font_name=kwargs.get("body_font_name"),
        body_font_regular_path=asset_path(kwargs.get("body_font_regular_asset_id")),
        body_font_bold_path=asset_path(kwargs.get("body_font_bold_asset_id")),
        body_font_italic_path=asset_path(kwargs.get("body_font_italic_asset_id")),
        body_font_bold_italic_path=asset_path(
            kwargs.get("body_font_bold_italic_asset_id")
        ),
        display_font_name=kwargs.get("display_font_name"),
        display_font_regular_path=asset_path(
            kwargs.get("display_font_regular_asset_id")
        ),
        display_font_bold_path=asset_path(kwargs.get("display_font_bold_asset_id")),
    )


def _sample_data_for_preview() -> SignoffData:
    """Synthetic sample for inline rendering — does not touch the DB."""
    from datetime import date, timedelta
    from types import SimpleNamespace

    today = date.today()
    monday = today - timedelta(days=today.weekday())
    friday = monday + timedelta(days=4)

    def entry(
        day_offset: int, h_start: int, h_end: int, project: str, task: str, notes: str
    ):
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
        my_company_name=_resolve_company_name(),
        client_name="Acme Corp (sample)",
        engineer_name="Alice Chen (sample)",
        engagement_name="Data Platform Modernisation",
        period_start=monday,
        period_end=friday,
        entries=[
            entry(
                0,
                9,
                12,
                "Data Pipeline",
                "ETL refactor",
                "Migrated the dim_customer table to SCD2; verified parity.",
            ),
            entry(
                0,
                13,
                17,
                "Data Pipeline",
                "Code review",
                "Reviewed PRs #412, #418, #421 from the offshore team.",
            ),
            entry(
                1,
                9,
                13,
                "Reporting Layer",
                "Looker model",
                "Built Revenue-by-Segment explore; validated against close numbers.",
            ),
            entry(
                2,
                9,
                12,
                "Data Pipeline",
                "Incident response",
                "Investigated dim_account null-rate spike; root cause Salesforce field rename.",
            ),
            entry(
                3,
                10,
                17,
                "Data Pipeline",
                "Documentation",
                "Wrote runbook for ingestion pipeline; covers failure modes and on-call.",
            ),
            entry(
                4,
                9,
                13,
                "Reporting Layer",
                "Bug fix",
                "Fixed off-by-one in rolling 28-day active-user metric.",
            ),
        ],
    )


def _resolve_company_name() -> str:
    from app.models.settings import Settings

    settings = Settings.query.first() if Settings else None
    for attr in ("company_name", "organization_name", "site_name"):
        value = getattr(settings, attr, None) if settings else None
        if value:
            return value
    return "Your Company"


@signoff_templates_bp.post("/admin/branding-assets/upload")
@login_required
@admin_or_permission_required("manage_integrations")
def upload_branding_asset():
    kind = (request.form.get("kind") or "").strip()
    if kind not in (BrandingAsset.KIND_LOGO, BrandingAsset.KIND_FONT_TTF):
        return jsonify({"error": "invalid kind"}), 400

    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "no file provided"}), 400

    original_filename = secure_filename(file.filename)
    ext = Path(original_filename).suffix.lower()

    if kind == BrandingAsset.KIND_LOGO and ext not in _ALLOWED_LOGO_EXT:
        return (
            jsonify({"error": f"logo must be one of {sorted(_ALLOWED_LOGO_EXT)}"}),
            400,
        )
    if kind == BrandingAsset.KIND_FONT_TTF and ext not in _ALLOWED_FONT_EXT:
        return (
            jsonify({"error": f"font must be one of {sorted(_ALLOWED_FONT_EXT)}"}),
            400,
        )

    name = (request.form.get("name") or "").strip() or Path(original_filename).stem

    stored_name = f"{uuid.uuid4().hex}{ext}"
    out_path = _branding_dir() / stored_name
    file.save(out_path)

    asset = BrandingAsset(
        kind=kind,
        name=name,
        file_path=str(out_path),
        mime_type=file.mimetype,
        original_filename=original_filename,
        file_size_bytes=out_path.stat().st_size,
        uploaded_by=current_user.id if hasattr(current_user, "id") else None,
    )
    db.session.add(asset)
    db.session.commit()

    return jsonify(
        {
            "id": asset.id,
            "kind": asset.kind,
            "name": asset.name,
            "original_filename": asset.original_filename,
            "file_size_bytes": asset.file_size_bytes,
        }
    )


@signoff_templates_bp.post("/admin/branding-assets/<int:asset_id>/archive")
@login_required
@admin_or_permission_required("manage_integrations")
def archive_branding_asset(asset_id: int):
    asset = BrandingAsset.query.get_or_404(asset_id)
    asset.archived_at = datetime.utcnow()
    db.session.commit()
    flash(_("Asset '%(name)s' archived", name=asset.name), "success")
    return redirect(url_for("signoff_templates.list_templates"))
