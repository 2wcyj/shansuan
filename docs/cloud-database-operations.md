# Cloud database and first-admin operations

This document describes the cloud-only identity database. The Windows desktop database and its local data directory are separate and are not accessed by these commands.

## Separate database identities

Create a dedicated migration login and a runtime login with your database provider or DBA console. Set strong, unique passwords through the provider's secret manager; do not put passwords in this file or a checked-in shell script.

```sql
CREATE ROLE shansuan_migrator LOGIN NOSUPERUSER NOCREATEDB CREATEROLE NOINHERIT NOBYPASSRLS;
CREATE ROLE shansuan_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
GRANT CONNECT ON DATABASE shansuan TO shansuan_migrator, shansuan_runtime;
GRANT CREATE, USAGE ON SCHEMA public TO shansuan_migrator;
```

Run Alembic only from a controlled operator shell using `MIGRATION_DATABASE_URL`, whose login must be `shansuan_migrator`. The cloud API container receives only `DATABASE_URL` for `shansuan_runtime`; never provide it the migration URL. After migrations create the limited `shansuan_app` group role, grant that role to the runtime login:

```sql
GRANT shansuan_app TO shansuan_runtime;
```

The migration login owns the schema objects and can create non-login roles, but is not a superuser and cannot bypass RLS. The runtime login receives only the app role. Do not make it a table owner, superuser, or `BYPASSRLS` role.

## Migrate and create the first administrator

Run these from the repository root in a protected operator shell. The migration URL should be injected from a secret manager or entered only into that shell. It must not be set in Netlify or the running API container.

```powershell
$env:MIGRATION_DATABASE_URL = '<migration-role connection URL>'
.\.venv\Scripts\alembic.exe -c app/backend/cloud/alembic.ini upgrade head
.\.venv\Scripts\python.exe -m app.backend.cloud.admin_cli bootstrap-admin
Remove-Item Env:MIGRATION_DATABASE_URL
```

The bootstrap command prompts for the administrator email and password without echoing the password. It only accepts the dedicated migration login, creates at most one initial administrator, and stores an Argon2id hash. Single-use, expiring invitations are supported by the authenticated `POST /api/auth/invites` endpoint, with CSRF and administrator checks. The invitation management frontend is not implemented yet. The endpoint returns the raw invitation token; share it privately with the intended tester. The database keeps only its SHA-256 hash.

If the initial migration login is retained for schema updates, keep its credentials out of the app service and limit operator access. Prefer a short-lived credential when the database provider supports it.

## Password recovery email

Sensitive export/deletion and password changes require migration `0005_privacy_lock`.
Apply `alembic upgrade head` before starting the updated API. Export/deletion hold
account and session locks through password verification and data access. Login
rechecks the password hash while holding the account lock before issuing a session;
a concurrent reset invalidates a login verified with the previous password. Expiry
checks after lock waits use the database's real clock, not transaction-start time.

Password recovery sends a short-lived, single-use reset token through the first-party SMTP adapter. Configure all of the following on the API host, using the SMTP provider's secret store for the password:

- `SMTP_HOST`
- `SMTP_PORT` (STARTTLS)
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_SENDER`
- `PASSWORD_RESET_URL` (HTTPS URL on the configured frontend origin)

The reset URL is unavailable until the frontend includes a password-reset page. With no complete SMTP configuration, the API returns an explicit unavailable response for password recovery instead of pretending to send an email. The reset token is stored only as a hash, expires after 15 minutes, and revokes existing sessions when used.

## Local integration tests

Cloud database tests start a disposable local `postgres:16-alpine` container and remove it after each test session:

```powershell
.\.venv\Scripts\python.exe -m pytest app/tests/cloud app/tests/test_cloud_boot.py -q
```

These tests need the Docker engine and do not use production credentials or cloud resources.
