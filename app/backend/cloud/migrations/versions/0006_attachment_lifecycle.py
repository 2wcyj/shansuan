"""Durable reservations and retryable object deletion; existing rows stay active."""
from alembic import op
from sqlalchemy import text

revision = '0006_attachment_lifecycle'
down_revision = '0005_privacy_lock'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(text("ALTER TABLE attachments ADD COLUMN state varchar(16) NOT NULL DEFAULT 'active'"))
    op.execute(text("ALTER TABLE attachments ADD CONSTRAINT ck_attachments_state CHECK (state IN ('pending','active','deleting'))"))
    op.execute(text('CREATE INDEX ix_attachments_account_state_created ON attachments(account_id,state,created_at)'))


def downgrade():
    op.execute(text('DROP INDEX ix_attachments_account_state_created'))
    op.execute(text('ALTER TABLE attachments DROP CONSTRAINT ck_attachments_state'))
    op.execute(text('ALTER TABLE attachments DROP COLUMN state'))
