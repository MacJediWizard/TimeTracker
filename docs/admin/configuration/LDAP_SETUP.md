# LDAP authentication

TimeTracker can authenticate users against an LDAP directory (OpenLDAP-style `groupOfNames` / `member` checks). LDAP is optional and is controlled with **`AUTH_METHOD`** and environment variables (see root **`env.example`** for a commented template).

## When to use which `AUTH_METHOD`

| Value   | Meaning |
|---------|---------|
| `ldap`  | Directory login only (same username/password form; users are provisioned or synced in the local DB on success). |
| `all`   | Local passwords, OIDC SSO, and LDAP are all available (see [OIDC Setup](OIDC_SETUP.md) for SSO). Login tries local first for users whose `auth_provider` is not `ldap`, then LDAP. |

For LDAP only or combined mode, set the variables documented in `env.example` under **LDAP Authentication**. In production, if LDAP is enabled, **`LDAP_HOST`**, **`LDAP_BASE_DN`**, **`LDAP_BIND_DN`**, and **`LDAP_BIND_PASSWORD`** are required (startup validation).

## Behaviour summary

- **Service account**: Binds with `LDAP_BIND_DN` / `LDAP_BIND_PASSWORD`, searches for the user under `LDAP_USER_DN` + `LDAP_BASE_DN`, optionally verifies membership in `LDAP_REQUIRED_GROUP` (by `cn` under `LDAP_GROUP_DN`), then verifies the password with a second bind as the user.
- **Provisioning**: Users are matched primarily by **email** from `LDAP_USER_EMAIL_ATTR`. Without an email, login cannot create or link an account.
- **Profile sync**: On each successful LDAP login, `full_name` (from `givenName` + `sn`) and admin flag (via `LDAP_ADMIN_GROUP` and legacy `role` field) are updated from the directory.
- **Local passwords**: LDAP-managed accounts have `auth_provider=ldap` and cannot use forgot-password, reset-password, or in-app password change flows.
- **Admin UI**: **Admin → System Settings** includes a read-only LDAP summary and **Test LDAP Connection** (`POST /admin/ldap/test`) for a non-destructive bind and user count under the configured user subtree.

## Kiosk mode

Kiosk login continues to use **local passwords only** (same `requires_password` rules as `local` / `both` / `all` for the form). LDAP-only users must have a usable local password for kiosk, or use standard web login.

## Further reading

- [OIDC Setup](OIDC_SETUP.md) — `AUTH_METHOD` overview including `all`.
- [Docker Compose environment](DOCKER_COMPOSE_SETUP.md#authentication) — variable list entry point.
