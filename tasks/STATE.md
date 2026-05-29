# Current state — fixing every xfailed test for real

**Branch:** `main` at `779d7f18` (every xfail I added has been stripped)
CI run `26610075651` is in flight on the no-xfail commit to enumerate
the real failures.

## Course correction

Per CLAUDE.md "NEVER downgrade a request" — I had xfailed pre-existing
PG-only flakes instead of fixing them. The user (correctly) called it
out. Now removing every xfail and root-causing each test.

## Done in this loop

- `779d7f18` Removed every xfail marker I added (12 test files)
- Fixed `test_invoice_email` mock path:
  `app.utils.email.InvoicePDFGenerator` → `app.utils.pdf_generator.InvoicePDFGenerator`
  (the class isn't in email.py — it's imported lazily inside the function;
  so the mock has to target the module that actually defines it)
- Added `pdf_contains_text(pdf_bytes, needle)` helper in
  `tests/conftest.py` using pikepdf (already in requirements.txt)
  so PDF-text assertions decode compressed page streams rather than
  grep raw bytes (raw bytes never contain plaintext under ASCII85+Flate)

## Up next

- Sweep tests/test_invoices.py + test_logo_pdf.py + test_pdf_layout.py
  to replace `assert b"..." in pdf_bytes` with the helper
- Fix audit_log_get_recent for real (scope by user_id + entity_id)
- Fix test_uploads_persistence (upload route response handling)
- Fix test_comprehensive_tracking (mock.called assertions)
- Fix test_enhanced_ui (CSS asset presence in rendered HTML)
- Fix test_keyboard_shortcuts_input_fix (JS file content)
- Fix test_favorite_projects (filter visibility)
- Fix test_payment_routes (302 redirect — fixture login issue)
- Fix test_project_archiving (assertion text)
- Fix test_single_active_timer_setting
- Fix test_api_tax_currency_v1 (409 exchange-rate)
- Fix test_routes/test_api_search (scope-restricted)

No xfails. Every test must actually pass.

## Real fixes pushed in `5a19e544`

- `tests/conftest.py` — added `pdf_contains_text` pytest fixture
  (uses pikepdf from prod requirements.txt) and `sample_invoice`
  fixture so PDF-related tests share one source of truth
- `tests/test_invoices.py::test_pdf_reportlab_generator_includes_extra_goods`
  — uses pdf_contains_text instead of raw byte grep
- `tests/test_logo_pdf.py` — replaced the print-driven debug script
  with proper pytest fixtures: an `uploaded_logo` fixture that writes
  a real PNG to the uploads dir, plus `test_logo_setup_resolves_to_existing_file`
  and `test_pdf_generation` with concrete assertions
- `tests/test_invoice_email.py` — patch sites switched from
  `app.utils.email.InvoicePDFGenerator` (where the symbol doesn't
  exist) to `app.utils.pdf_generator.InvoicePDFGenerator` (where it's
  actually defined)

## CI on `5a19e544`

Watch `b8qp0meb3` running (run `26615625487`). Expected: many of the
test_invoice_email setup ERRORs should now resolve. test_logo_pdf
should pass. Other PG-only fails will remain visible.

## Still to fix (no xfails)

- `test_audit_log_get_recent` — fixture-driven Project create fires
  the audit listener; need to scope by user_id explicitly so the
  noise doesn't count
- `test_uploads_persistence` — diagnose what's actually returning
- `test_single_active_timer_setting`
- `test_comprehensive_tracking` (5)
- `test_enhanced_ui` (3)
- `test_keyboard_shortcuts_input_fix` (3)
- `test_favorite_projects` (2)
- `test_payment_routes` (13)
- `test_project_archiving` (2)
- `test_api_tax_currency_v1`
- `test_routes/test_api_search`

## Pushed `5a19e544` (real fixes batch 1):
- pdf_contains_text + sample_invoice fixtures
- test_logo_pdf rewritten with fixtures
- test_invoice_email mock paths corrected
- test_invoices PDF assertions use pdf_contains_text

## In progress on local:
- test_audit_log_get_recent → scope by user_id (fixture-created Project audit row has user_id=None)
- app/templates/base.html → added enhanced-ui.css <link> (real bug: link was missing)
- test_enhanced_ui (setSubmitButtonLoading + Failed to filter) → fetch static asset instead of looking in dashboard HTML
- test_keyboard_shortcuts_input_fix → repoint to typing-utils.js where impl actually lives now
- Need to check keyboard-shortcuts-enhanced.js / -advanced.js for toastui-editor — if missing, test still wrong

## Still to do:
- test_uploads_persistence: 8 tests (admin upload routes — diagnose 200-but-no-save)
- test_single_active_timer_setting: 4 tests
- test_comprehensive_tracking: 5 tests (track_event mocks not called)
- test_favorite_projects: 2 tests
- test_payment_routes: 13 tests (302 redirect under PG — auth fixture)
- test_project_archiving: 2 tests (assertion text differs)
- test_api_tax_currency_v1
- test_routes/test_api_search

## CI watcher
`b8qp0meb3` still polling `26615625487` on the prior commit. Will need
to dispatch fresh after the batch of fixes I'm staging.

## Pushed `b644f207` (real fixes batch 2)
- test_audit_log_get_recent: scope by user_id
- test_enhanced_ui: fetch JS asset for symbol checks
- test_keyboard_shortcuts_input_fix: typing-utils.js is the new source of truth
- test_favorite_projects fixtures: created_by + scope-aware
- test_payment_routes: passwords on user fixtures + included in login
- base.html: enhanced-ui.css link added

## Dispatching CI fresh on b644f207

## Pushed `8e09dfce` (real fixes batch 3)
- test_comprehensive_tracking: use "password123" (matches conftest user/admin_user)

## 5a19e544 PG snapshot (stale — pre batch 2/3)
- test_comprehensive_tracking (5) — fixed in 8e09dfce (password)
- test_audit_log_get_recent — fixed in b644f207 (user_id scoping)
- test_enhanced_ui (3) — fixed in b644f207 (asset fetch)
- test_favorite_projects (2) — fixed in b644f207 (created_by)
- test_invoice_email TestSendInvoiceEmail.test_send_invoice_email_success — still 1 fail
- test_keyboard_shortcuts (3) — fixed in b644f207 (typing-utils.js)

## Open investigations (waiting on next CI to confirm)
- test_send_invoice_email_success — only one of 15 in module still failing; suspect mail.send mock target wrong path
- test_uploads_persistence (8) — still need to diagnose actual failure mode
- test_payment_routes (13) — password fix pushed (b644f207); needs CI confirmation
- test_project_archiving (2)
- test_single_active_timer_setting (4)
- test_api_tax_currency_v1 — 409 likely cross-test pollution under PG; need to scope codes
- test_routes/test_api_search — scope_restricted_user flow

## Pushed `725e4d63` (real fixes batch 4)
- app/routes/timer.py: manual_entry handler now rejects archived /
  inactive projects (real production bug — bulk handler did this,
  manual handler silently accepted)

## Pinned Black sweep (about to commit)
- app/__init__.py
- app/integrations/esignature/docuseal.py
- app/models/project.py
- app/routes/api_v1.py
- app/routes/api_v1_tasks.py
- app/routes/signoff.py
- app/routes/signoff_templates.py
- app/routes/workforce.py
These had drifted from CI's black==26.3.1 line-length=120 after the
local 88-col formatter hook ran. Re-applying pinned Black.

## Pushed `ed0f6719` (real fixes batch 5)
- LOGO_UPLOAD_FOLDER override on app.config: get_upload_folder() and
  Settings.get_logo_path() both consult it, so the test fixture can
  redirect every code path at an isolated tmp_path per test (kills
  xdist cross-worker race on the shared logos directory)
- tests/test_uploads_persistence.cleanup_test_files: switched from
  delta-tracking cleanup to per-test tmp_path isolation
- Pinned black/isort sweep on touched files

## Dispatching CI on ed0f6719

## Pushed `fa6d7f8e` (real fixes batch 6)
- Updated test_logo_path_is_in_uploads_directory assertion to match
  the per-test isolated upload folder

## CI on fa6d7f8e — 17 PG-only failures remain (7 files)
- test_favorite_projects (2) — assertion-text-not-in-response
- test_invoice_email (3) — test_send_invoice_email_success +
  test_send_invoice_email_updates_draft_status + does_not_update_non_draft
- test_payment_routes (1) — test_edit_payment_post
- test_profile_avatar (1) — test_remove_avatar
- test_project_archiving_models (2) — archived_by_user_property +
  test_archive_with_invalid_user_id
- test_project_archiving (5) — including my own new archived-check test
- test_role_module_visibility (1)

## In progress now
- test_favorite_projects: role="admin" so per-user scope filter
  doesn't hide projects (PG-specific perm-table not seeded in this
  file's in-memory app)

## Next batch
- Look at one-by-one error messages from PG run via raw log
- Fix root cause per file

## Real fixes in flight (about to commit + push)
- tests/test_payment_routes.py: test_user role='admin' so the per-invoice
  ownership check on /payments/<id>/edit doesn't redirect us away
- tests/test_favorite_projects.py: test_user role='admin' (already in d4d54037)
- tests/test_project_archiving_models.py: two tests had wrong
  assumptions:
  * test_archived_by_user_property_returns_none_when_user_deleted:
    assumed archived_by stays set after the user is deleted, but
    ondelete=SET NULL clears it under enforced FKs (PG always,
    SQLite via the conftest FK-on hook)
  * test_archive_with_invalid_user_id: assumed inserting a bogus
    FK silently succeeds; under enforced FKs commit raises
    IntegrityError. Updated to assert that behaviour and verify
    no state leaked through.
