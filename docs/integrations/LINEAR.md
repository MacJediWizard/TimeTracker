# Linear integration

TimeTracker can import [Linear](https://linear.app/) issues as **tasks** using a **Personal API key** and the public GraphQL API ([Linear API docs](https://developers.linear.app/docs/graphql/working-with-the-graphql-api)).

## Authentication

Linear is **not** OAuth in this connector: you create a **Personal API Key** in Linear (Settings → API) and paste it into TimeTracker when you connect the integration. The key is stored like other integration credentials.

## What gets synced

- **Issues** are fetched from Linear (paginated) and upserted as **tasks** under per-team **projects** (created or matched by integration metadata).
- **Task name**: `IDENTIFIER: title` (e.g. `ENG-42: Fix login`).
- **Description**: issue URL (when available).
- **Status**: mapped to `done` when the Linear workflow state name is done/completed/canceled (case-insensitive); otherwise `todo`.

Optional JSON **`custom_fields`** on tasks stores integration metadata (e.g. Linear identifier and URL) for matching on later syncs.

## Configuration

| Field | Purpose |
|--------|--------|
| **API key** | Linear personal API key |
| **Team keys (optional)** | Comma-separated team keys (e.g. `ENG,MOB`). If empty, issues from all accessible teams are considered (subject to API visibility). |
| **Automatic sync** | When enabled, runs on the integration schedule like other connectors. |

Use **Test connection** to verify the key; use **Sync now** for a manual import.

## Limits and notes

- Sync walks up to a bounded number of GraphQL pages per run to avoid runaway imports.
- The TimeTracker server must reach `https://api.linear.app`.
- Webhooks are not required; sync is pull-based from Linear.
