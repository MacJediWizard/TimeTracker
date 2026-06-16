# SOW auto-provisioning (Claude API)

Turn a customer **Statement of Work** into a ready-to-work project. Paste or upload an SOW,
let Claude parse it into a structured plan, review and edit a preview, then provision a
**Client, Project, Kanban board, and Tasks** in one step — no more hand-entering every SOW.

This uses a dedicated **Claude API** provider that is separate from the AI Helper (the
Ollama / OpenAI-compatible chat assistant). Configuring one does not affect the other.

## Configuration

Admin → **Settings → Claude / SOW**:

1. **Availability** — `Enabled` to turn the feature on (defaults to off / environment).
2. **Model** — `claude-opus-4-8` (default), `claude-opus-4-7`, `claude-opus-4-6`,
   `claude-sonnet-4-6`, or `claude-haiku-4-5`.
3. **Effort** — `low` / `medium` / `high` (default) / `xhigh` / `max`.
   `xhigh` and `max` are Opus-only and are disabled for Sonnet; Haiku ignores effort entirely
   (the selector reflects this automatically and the server enforces it).
4. **Anthropic API key** — stored server-side and encrypted; never sent to browsers.
5. **Timeout** — request timeout in seconds (default 120).
6. **Test Claude connection** — sends a tiny request to confirm the key, model, and effort work.

### Environment variables (optional)

Database settings take precedence; these are fallbacks:

| Variable | Purpose |
|---|---|
| `CLAUDE_ENABLED` | Enable the provider when no DB override is set |
| `CLAUDE_API_KEY` | Anthropic API key |
| `CLAUDE_MODEL` | Default model |
| `CLAUDE_EFFORT` | Default effort |
| `CLAUDE_TIMEOUT_SECONDS` | Request timeout |

## Using it

Projects → **Provision from SOW** (visible to admins and users with `create_projects`):

1. **Paste SOW text** or **upload a file** (PDF, DOCX, or plain text).
2. Click **Parse with Claude**. The SOW is parsed into a structured plan.
3. **Review & edit** the preview — client, project (name, code, description, billable, rate,
   budget, start/end dates), and the task list (name, status, priority, estimate, due date).
   Add or remove tasks as needed.
4. Click **Create project, tasks & board**. TimeTracker provisions everything and links you
   straight to the new project and its Kanban board.

The two steps are deliberate: Claude proposes, you confirm. Nothing is written to the database
until you click create, and provisioning is **atomic** — if any task fails, the whole project is
rolled back so a misparse never leaves a half-built project behind.

### How provisioning maps the plan

- **Client** is matched by name (case-sensitive). An existing client is reused; otherwise a new
  one is created from the SOW's client details.
- **Project** is created via the standard project service (validation, events, and audit hooks
  all fire normally). SOW start/end dates are stored on the project's custom fields.
- **Kanban** uses the project's default columns; each task's status is validated against those
  columns and falls back to `todo` if the model emits an unknown status.

## API

All endpoints are gated to admins or users with `create_projects` (or `manage_settings` for the
test endpoint).

**Session (web app):**

| Method & path | Purpose |
|---|---|
| `POST /api/ai/sow/test` | Test the configured Claude provider |
| `POST /api/ai/sow/parse` | Parse SOW text or an uploaded PDF/DOCX into a plan (no writes) |
| `POST /api/ai/sow/provision` | Provision a confirmed plan |

**Token-auth (API v1):**

| Method & path | Scope |
|---|---|
| `POST /api/v1/ai/sow/parse` | `write:ai` |
| `POST /api/v1/ai/sow/provision` | `write:ai` |

`parse` returns `{ "plan": { "client": {...}, "project": {...}, "tasks": [...] } }`. Send that
(edited as needed) back to `provision` as `{ "plan": { ... } }`.

## Notes

- Defaults to disabled with model `claude-opus-4-8` / effort `high`.
- Structured outputs guarantee valid plan JSON; prompt caching reuses the instruction prefix
  across re-parses to reduce cost.
- Requires the `anthropic` and `python-docx` packages (already in `requirements.txt`).
- Database migration `161` adds the Claude settings columns.
