"""Constrain permanent account deletion to an authenticated owner."""
from alembic import op
from sqlalchemy import text


revision = "0004_account_privacy"
down_revision = "0003_account_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text("""
        CREATE FUNCTION cloud_delete_account(p_account_id uuid)
        RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE last_admin boolean;
        BEGIN
            IF NULLIF(current_setting('app.account_id', true), '')::uuid
               IS DISTINCT FROM p_account_id THEN
                RETURN false;
            END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended('domain:' || p_account_id::text, 0));
            PERFORM pg_advisory_xact_lock(hashtextextended('privacy:admin-account-deletion', 0));
            SELECT is_admin AND (
                SELECT count(*) FROM public.accounts
                WHERE is_admin AND status = 'active'
            ) <= 1 INTO last_admin
            FROM public.accounts WHERE id = p_account_id AND status = 'active';
            IF last_admin IS NULL THEN RETURN false; END IF;
            IF last_admin THEN RETURN false; END IF;
            DELETE FROM public.accounts WHERE id = p_account_id AND status = 'active';
            RETURN FOUND;
        END
        $$
    """))
    op.execute(text("REVOKE ALL ON FUNCTION cloud_delete_account(uuid) FROM PUBLIC"))
    op.execute(text("GRANT EXECUTE ON FUNCTION cloud_delete_account(uuid) TO shansuan_app"))


def downgrade() -> None:
    op.execute(text("DROP FUNCTION cloud_delete_account(uuid)"))
