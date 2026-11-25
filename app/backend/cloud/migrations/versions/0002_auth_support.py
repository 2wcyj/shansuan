"""Add account authorization metadata, reset tokens, and bounded auth throttling."""
from alembic import op
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKeyConstraint,
    LargeBinary,
    PrimaryKeyConstraint,
    text,
    Uuid,
    Integer,
)


revision = "0002_auth_support"
down_revision = "0001_accounts_entities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", Column(
        "is_admin", Boolean(), nullable=False, server_default=text("false")
    ))
    op.add_column("sessions", Column(
        "csrf_hash", LargeBinary(32), nullable=False,
        server_default=text("decode(repeat('00', 32), 'hex')"),
    ))
    op.execute(text("ALTER TABLE sessions ALTER COLUMN csrf_hash DROP DEFAULT"))
    op.create_table(
        "password_resets",
        Column("account_id", Uuid(), nullable=False),
        Column("id", Uuid(), nullable=False),
        Column("token_hash", LargeBinary(32), nullable=False, unique=True),
        Column("expires_at", DateTime(timezone=True), nullable=False),
        Column("used_at", DateTime(timezone=True)),
        Column("created_at", DateTime(timezone=True),
                                          nullable=False, server_default=text("now()")),
        ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        PrimaryKeyConstraint("account_id", "id"),
    )
    op.create_index("ix_password_resets_account_expires", "password_resets", ["account_id", "expires_at"])
    op.create_table(
        "auth_rate_limits",
        Column("key_hash", LargeBinary(32), primary_key=True),
        Column("window_started", DateTime(timezone=True), nullable=False),
        Column("attempts", Integer(), nullable=False),
    )
    op.execute(text("ALTER TABLE password_resets ENABLE ROW LEVEL SECURITY"))
    op.execute(text("ALTER TABLE password_resets FORCE ROW LEVEL SECURITY"))
    op.execute(text("""
        CREATE POLICY tenant_account_isolation ON password_resets
        USING (account_id = NULLIF(current_setting('app.account_id', true), '')::uuid)
        WITH CHECK (account_id = NULLIF(current_setting('app.account_id', true), '')::uuid)
    """))
    op.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON password_resets TO shansuan_app"))
    op.execute(text("""
        CREATE FUNCTION cloud_login_lookup(p_email text)
        RETURNS TABLE(id uuid, email text, password_hash text, status text, is_admin boolean)
        LANGUAGE sql SECURITY DEFINER STABLE
        SET search_path = pg_catalog, public
        AS $$
            SELECT a.id, a.email::text, a.password_hash::text, a.status::text, a.is_admin
            FROM public.accounts AS a
            WHERE lower(a.email) = lower(p_email)
            LIMIT 1
        $$
    """))
    op.execute(text("""
        CREATE FUNCTION cloud_account_is_admin(p_account_id uuid)
        RETURNS boolean LANGUAGE sql SECURITY DEFINER STABLE
        SET search_path = pg_catalog, public
        AS $$
            SELECT COALESCE(
                p_account_id = NULLIF(current_setting('app.account_id', true), '')::uuid
                AND (SELECT a.is_admin FROM public.accounts AS a WHERE a.id = p_account_id),
                false
            )
        $$
    """))
    op.execute(text("""
        CREATE FUNCTION cloud_auth_rate_limit(p_key_hash bytea, p_limit integer, p_window_seconds integer)
        RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE allowed boolean;
        BEGIN
            INSERT INTO public.auth_rate_limits AS current_bucket (key_hash, window_started, attempts)
            VALUES (p_key_hash, clock_timestamp(), 1)
            ON CONFLICT (key_hash) DO UPDATE SET
                attempts = CASE
                    WHEN current_bucket.window_started + make_interval(secs => p_window_seconds) <= clock_timestamp()
                    THEN 1 ELSE current_bucket.attempts + 1 END,
                window_started = CASE
                    WHEN current_bucket.window_started + make_interval(secs => p_window_seconds) <= clock_timestamp()
                    THEN clock_timestamp() ELSE current_bucket.window_started END
            RETURNING attempts <= p_limit INTO allowed;
            RETURN allowed;
        END
        $$
    """))
    op.execute(text("""
        CREATE FUNCTION cloud_register_account(
            p_id uuid, p_email text, p_password_hash text, p_owner uuid, p_invite_hash bytea
        ) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE uses integer;
        BEGIN
            IF NULLIF(current_setting('app.account_id', true), '')::uuid IS DISTINCT FROM p_owner THEN
                RAISE EXCEPTION 'invalid invite' USING ERRCODE = '22023';
            END IF;
            SELECT i.used_count INTO uses
            FROM public.invites AS i
            WHERE i.account_id = p_owner AND i.token_hash = p_invite_hash
              AND i.revoked_at IS NULL AND i.expires_at > now() AND i.used_count < i.max_uses
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'invalid invite' USING ERRCODE = '22023';
            END IF;
            UPDATE public.invites AS i SET used_count = i.used_count + 1
            WHERE i.account_id = p_owner AND i.token_hash = p_invite_hash;
            INSERT INTO public.accounts (id,email,password_hash,status,is_admin)
            VALUES (p_id, lower(trim(p_email)), p_password_hash, 'active', false);
            RETURN p_id;
        END
        $$
    """))
    op.execute(text("""
        CREATE FUNCTION cloud_update_password(p_account_id uuid, p_password_hash text)
        RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            IF NULLIF(current_setting('app.account_id', true), '')::uuid IS DISTINCT FROM p_account_id THEN
                RETURN false;
            END IF;
            UPDATE public.accounts SET password_hash = p_password_hash
            WHERE id = p_account_id AND status = 'active';
            IF NOT FOUND THEN RETURN false; END IF;
            UPDATE public.sessions SET revoked_at = now()
            WHERE account_id = p_account_id AND revoked_at IS NULL;
            RETURN true;
        END
        $$
    """))
    op.execute(text("""
        CREATE FUNCTION cloud_account_status(p_account_id uuid)
        RETURNS TABLE(status text, is_admin boolean) LANGUAGE sql SECURITY DEFINER STABLE
        SET search_path = pg_catalog, public
        AS $$
            SELECT a.status::text, a.is_admin
            FROM public.accounts AS a
            WHERE a.id = p_account_id
              AND p_account_id = NULLIF(current_setting('app.account_id', true), '')::uuid
        $$
    """))
    op.execute(text("""
        CREATE FUNCTION cloud_account_credentials(p_account_id uuid)
        RETURNS TABLE(email text, password_hash text, status text, is_admin boolean)
        LANGUAGE sql SECURITY DEFINER STABLE
        SET search_path = pg_catalog, public
        AS $$
            SELECT a.email::text, a.password_hash::text, a.status::text, a.is_admin
            FROM public.accounts AS a
            WHERE a.id = p_account_id
              AND p_account_id = NULLIF(current_setting('app.account_id', true), '')::uuid
        $$
    """))
    for statement in (
        "REVOKE ALL ON FUNCTION cloud_login_lookup(text) FROM PUBLIC",
        "REVOKE ALL ON FUNCTION cloud_account_is_admin(uuid) FROM PUBLIC",
        "REVOKE ALL ON FUNCTION cloud_auth_rate_limit(bytea, integer, integer) FROM PUBLIC",
        "REVOKE ALL ON FUNCTION cloud_register_account(uuid, text, text, uuid, bytea) FROM PUBLIC",
        "REVOKE ALL ON FUNCTION cloud_update_password(uuid, text) FROM PUBLIC",
        "REVOKE ALL ON FUNCTION cloud_account_status(uuid) FROM PUBLIC",
        "REVOKE ALL ON FUNCTION cloud_account_credentials(uuid) FROM PUBLIC",
        "GRANT EXECUTE ON FUNCTION cloud_login_lookup(text) TO shansuan_app",
        "GRANT EXECUTE ON FUNCTION cloud_account_is_admin(uuid) TO shansuan_app",
        "GRANT EXECUTE ON FUNCTION cloud_auth_rate_limit(bytea, integer, integer) TO shansuan_app",
        "GRANT EXECUTE ON FUNCTION cloud_register_account(uuid, text, text, uuid, bytea) TO shansuan_app",
        "GRANT EXECUTE ON FUNCTION cloud_update_password(uuid, text) TO shansuan_app",
        "GRANT EXECUTE ON FUNCTION cloud_account_status(uuid) TO shansuan_app",
        "GRANT EXECUTE ON FUNCTION cloud_account_credentials(uuid) TO shansuan_app",
    ):
        op.execute(text(statement))


def downgrade() -> None:
    op.execute(text("DROP FUNCTION cloud_account_status(uuid)"))
    op.execute(text("DROP FUNCTION cloud_account_credentials(uuid)"))
    op.execute(text("DROP FUNCTION cloud_update_password(uuid, text)"))
    op.execute(text("DROP FUNCTION cloud_register_account(uuid, text, text, uuid, bytea)"))
    op.execute(text("DROP FUNCTION cloud_auth_rate_limit(bytea, integer, integer)"))
    op.execute(text("DROP FUNCTION cloud_account_is_admin(uuid)"))
    op.execute(text("DROP FUNCTION cloud_login_lookup(text)"))
    op.drop_table("auth_rate_limits")
    op.drop_table("password_resets")
    op.drop_column("sessions", "csrf_hash")
    op.drop_column("accounts", "is_admin")
