"""Lock account credentials for sensitive operations and password changes."""
from alembic import op
from sqlalchemy import text

revision = '0005_privacy_lock'
down_revision = '0004_account_privacy'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(text("""
        CREATE FUNCTION cloud_lock_account_credentials(p_account_id uuid)
        RETURNS TABLE(email text, password_hash text, status text, is_admin boolean)
        LANGUAGE sql SECURITY DEFINER VOLATILE
        SET search_path = pg_catalog, public
        AS $$
            SELECT a.email::text, a.password_hash::text, a.status::text, a.is_admin
            FROM public.accounts AS a
            WHERE a.id = p_account_id
              AND p_account_id = NULLIF(current_setting('app.account_id', true), '')::uuid
            FOR UPDATE OF a
        $$
    """))
    op.execute(text('REVOKE ALL ON FUNCTION cloud_lock_account_credentials(uuid) FROM PUBLIC'))
    op.execute(text('GRANT EXECUTE ON FUNCTION cloud_lock_account_credentials(uuid) TO shansuan_app'))


def downgrade():
    op.execute(text('DROP FUNCTION cloud_lock_account_credentials(uuid)'))
