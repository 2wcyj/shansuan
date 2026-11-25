"""Initial account and tenant-isolated schema, frozen as revision 0001."""
from alembic import op
from sqlalchemy import text

revision = "0001_accounts_entities"
down_revision = None
branch_labels = None
depends_on = None

_CREATE_TABLES = ('CREATE TABLE accounts (\n'
 '\tid UUID NOT NULL, \n'
 '\temail VARCHAR(320) NOT NULL, \n'
 '\tpassword_hash VARCHAR(512) NOT NULL, \n'
 '\tstatus VARCHAR(20) NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 "\tCONSTRAINT ck_accounts_status CHECK (status IN ('active', 'suspended', 'deleting', "
 "'deleted')), \n"
 '\tUNIQUE (email)\n'
 ')',
 'CREATE TABLE attachments (\n'
 '\taccount_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tobject_key VARCHAR(128) NOT NULL, \n'
 '\twrapped_data_key BYTEA NOT NULL, \n'
 '\tmedia_type VARCHAR(100) NOT NULL, \n'
 '\tbyte_size BIGINT NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tPRIMARY KEY (account_id, id), \n'
 '\tCONSTRAINT uq_attachments_account_object_key UNIQUE (account_id, object_key), \n'
 '\tFOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE CASCADE\n'
 ')',
 'CREATE TABLE audit_events (\n'
 '\taccount_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tevent_type VARCHAR(64) NOT NULL, \n'
 '\ttarget_id UUID, \n'
 '\trequest_id UUID, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tPRIMARY KEY (account_id, id), \n'
 '\tFOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE CASCADE\n'
 ')',
 'CREATE TABLE entities (\n'
 '\taccount_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tkind VARCHAR(40) NOT NULL, \n'
 '\tbody_ciphertext BYTEA NOT NULL, \n'
 "\trevision INTEGER DEFAULT '1' NOT NULL, \n"
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tPRIMARY KEY (account_id, id), \n'
 '\tFOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE CASCADE\n'
 ')',
 'CREATE TABLE invites (\n'
 '\taccount_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\ttoken_hash BYTEA NOT NULL, \n'
 '\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tmax_uses INTEGER NOT NULL, \n'
 "\tused_count INTEGER DEFAULT '0' NOT NULL, \n"
 '\trevoked_at TIMESTAMP WITH TIME ZONE, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tPRIMARY KEY (account_id, id), \n'
 '\tCONSTRAINT ck_invites_use_count CHECK (max_uses > 0 AND used_count >= 0 AND used_count <= '
 'max_uses), \n'
 '\tFOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE CASCADE, \n'
 '\tUNIQUE (token_hash)\n'
 ')',
 'CREATE TABLE privacy_consents (\n'
 '\taccount_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tnotice_version VARCHAR(64) NOT NULL, \n'
 '\tgranted_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\twithdrawn_at TIMESTAMP WITH TIME ZONE, \n'
 '\tuser_agent_digest BYTEA, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tPRIMARY KEY (account_id, id), \n'
 '\tFOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE CASCADE\n'
 ')',
 'CREATE TABLE requests (\n'
 '\taccount_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tidempotency_hash BYTEA NOT NULL, \n'
 '\tresult_ciphertext BYTEA, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (account_id, id), \n'
 '\tCONSTRAINT uq_requests_account_idempotency UNIQUE (account_id, idempotency_hash), \n'
 '\tFOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE CASCADE\n'
 ')',
 'CREATE TABLE sessions (\n'
 '\taccount_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\ttoken_hash BYTEA NOT NULL, \n'
 '\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\trevoked_at TIMESTAMP WITH TIME ZONE, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tPRIMARY KEY (account_id, id), \n'
 '\tFOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE CASCADE, \n'
 '\tUNIQUE (token_hash)\n'
 ')',
 'CREATE TABLE tasks (\n'
 '\taccount_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tkind VARCHAR(40) NOT NULL, \n'
 '\tstatus VARCHAR(20) NOT NULL, \n'
 '\tresult_ciphertext BYTEA, \n'
 '\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tPRIMARY KEY (account_id, id), \n'
 '\tFOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE CASCADE\n'
 ')',
 'CREATE TABLE entity_photos (\n'
 '\taccount_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tentity_id UUID NOT NULL, \n'
 '\tattachment_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tPRIMARY KEY (account_id, id), \n'
 '\tCONSTRAINT fk_entity_photos_entity FOREIGN KEY(account_id, entity_id) REFERENCES entities '
 '(account_id, id) ON DELETE CASCADE, \n'
 '\tCONSTRAINT fk_entity_photos_attachment FOREIGN KEY(account_id, attachment_id) REFERENCES '
 'attachments (account_id, id) ON DELETE CASCADE, \n'
 '\tCONSTRAINT uq_entity_photos_link UNIQUE (account_id, entity_id, attachment_id), \n'
 '\tFOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE CASCADE\n'
 ')',
 'CREATE TABLE history (\n'
 '\taccount_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tentity_id UUID NOT NULL, \n'
 '\tbody_ciphertext BYTEA NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tPRIMARY KEY (account_id, id), \n'
 '\tCONSTRAINT fk_history_entity FOREIGN KEY(account_id, entity_id) REFERENCES entities '
 '(account_id, id) ON DELETE CASCADE, \n'
 '\tFOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE CASCADE\n'
 ')',
 'CREATE TABLE links (\n'
 '\taccount_id UUID NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\tsource_entity_id UUID NOT NULL, \n'
 '\ttarget_entity_id UUID NOT NULL, \n'
 '\trelationship VARCHAR(40) NOT NULL, \n'
 '\tPRIMARY KEY (account_id, id), \n'
 '\tCONSTRAINT fk_links_source FOREIGN KEY(account_id, source_entity_id) REFERENCES entities '
 '(account_id, id) ON DELETE CASCADE, \n'
 '\tCONSTRAINT fk_links_target FOREIGN KEY(account_id, target_entity_id) REFERENCES entities '
 '(account_id, id) ON DELETE CASCADE, \n'
 '\tCONSTRAINT uq_links_relationship UNIQUE (account_id, source_entity_id, target_entity_id, '
 'relationship), \n'
 '\tFOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE CASCADE\n'
 ')')
_CREATE_INDEXES = ('CREATE INDEX ix_attachments_account_id ON attachments (account_id)',
 'CREATE INDEX ix_audit_events_account_created ON audit_events (account_id, created_at)',
 'CREATE INDEX ix_entities_account_kind ON entities (account_id, kind)',
 'CREATE INDEX ix_invites_account_id ON invites (account_id)',
 'CREATE INDEX ix_privacy_consents_account_id ON privacy_consents (account_id)',
 'CREATE INDEX ix_requests_account_expires ON requests (account_id, expires_at)',
 'CREATE INDEX ix_sessions_account_expires ON sessions (account_id, expires_at)',
 'CREATE INDEX ix_tasks_account_status_created ON tasks (account_id, status, created_at)',
 'CREATE INDEX ix_entity_photos_account_id ON entity_photos (account_id)',
 'CREATE INDEX ix_history_account_entity_created ON history (account_id, entity_id, created_at)',
 'CREATE INDEX ix_links_account_id ON links (account_id)')
_TABLE_NAMES = ('accounts',
 'attachments',
 'audit_events',
 'entities',
 'invites',
 'privacy_consents',
 'requests',
 'sessions',
 'tasks',
 'entity_photos',
 'history',
 'links')
_TENANT_TABLE_NAMES = ('sessions',
 'privacy_consents',
 'entities',
 'history',
 'requests',
 'attachments',
 'entity_photos',
 'links',
 'tasks',
 'invites',
 'audit_events')

def upgrade() -> None:
    op.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'shansuan_app') THEN
                CREATE ROLE shansuan_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
            END IF;
            IF EXISTS (
                SELECT 1 FROM pg_roles
                WHERE rolname = 'shansuan_app' AND (rolsuper OR rolbypassrls OR rolcanlogin)
            ) THEN
                RAISE EXCEPTION 'shansuan_app must be a non-login, non-superuser, non-BYPASSRLS role';
            END IF;
        END $$;
    """))
    for statement in _CREATE_TABLES:
        op.execute(text(statement))
    for statement in _CREATE_INDEXES:
        op.execute(text(statement))
    for table in _TENANT_TABLE_NAMES:
        op.execute(text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
        op.execute(text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))
        op.execute(text(f"""
            CREATE POLICY tenant_account_isolation ON "{table}"
            USING (account_id = NULLIF(current_setting('app.account_id', true), '')::uuid)
            WITH CHECK (account_id = NULLIF(current_setting('app.account_id', true), '')::uuid)
        """))
        op.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO shansuan_app'))

def downgrade() -> None:
    for table in reversed(_TABLE_NAMES):
        op.execute(text(f'DROP TABLE "{table}" CASCADE'))
