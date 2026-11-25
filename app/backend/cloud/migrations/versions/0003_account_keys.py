"""Store only KMS-wrapped per-account payload keys."""
from alembic import op
from sqlalchemy import text


revision = "0003_account_keys"
down_revision = "0002_auth_support"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text("""
        CREATE TABLE account_keys (
            account_id UUID PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
            wrapped_key BYTEA NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    op.execute(text("ALTER TABLE account_keys ENABLE ROW LEVEL SECURITY"))
    op.execute(text("ALTER TABLE account_keys FORCE ROW LEVEL SECURITY"))
    op.execute(text("""
        CREATE POLICY tenant_account_isolation ON account_keys
        USING (account_id = NULLIF(current_setting('app.account_id', true), '')::uuid)
        WITH CHECK (account_id = NULLIF(current_setting('app.account_id', true), '')::uuid)
    """))
    op.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON account_keys TO shansuan_app"))


def downgrade() -> None:
    op.execute(text("DROP TABLE account_keys CASCADE"))
