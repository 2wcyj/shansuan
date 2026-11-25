"""Metadata for the cloud account and tenant-owned records."""
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)


metadata = MetaData()
accounts = Table(
    "accounts", metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("email", String(320), nullable=False, unique=True),
    Column("password_hash", String(512), nullable=False),
    Column("status", String(20), nullable=False),
    Column("is_admin", Boolean, nullable=False, server_default="false"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("status IN ('active', 'suspended', 'deleting', 'deleted')", name="ck_accounts_status"),
)
account_keys = Table(
    "account_keys", metadata,
    Column("account_id", Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"),
           primary_key=True, nullable=False),
    Column("wrapped_key", LargeBinary, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


def _tenant_table(name: str, *columns: Column, constraints=(), indexes=()) -> Table:
    table = Table(
        name, metadata,
        Column("account_id", Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"),
               primary_key=True, nullable=False),
        Column("id", Uuid(as_uuid=True), primary_key=True),
        *columns,
        *constraints,
    )
    for index_name, *column_names in indexes:
        Index(index_name, *(table.c[column_name] for column_name in column_names))
    if not indexes:
        Index(f"ix_{name}_account_id", table.c.account_id)
    return table


sessions = _tenant_table(
    "sessions",
    Column("token_hash", LargeBinary(32), nullable=False, unique=True),
    Column("csrf_hash", LargeBinary(32), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    indexes=(("ix_sessions_account_expires", "account_id", "expires_at"),),
)
privacy_consents = _tenant_table(
    "privacy_consents",
    Column("notice_version", String(64), nullable=False),
    Column("granted_at", DateTime(timezone=True), nullable=False),
    Column("withdrawn_at", DateTime(timezone=True)),
    Column("user_agent_digest", LargeBinary(32)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
entities = _tenant_table(
    "entities",
    Column("kind", String(40), nullable=False),
    Column("body_ciphertext", LargeBinary, nullable=False),
    Column("revision", Integer, nullable=False, server_default="1"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    indexes=(("ix_entities_account_kind", "account_id", "kind"),),
)
history = _tenant_table(
    "history",
    Column("entity_id", Uuid(as_uuid=True), nullable=False),
    Column("body_ciphertext", LargeBinary, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    constraints=(ForeignKeyConstraint(["account_id", "entity_id"], ["entities.account_id", "entities.id"],
                                      ondelete="CASCADE", name="fk_history_entity"),),
    indexes=(("ix_history_account_entity_created", "account_id", "entity_id", "created_at"),),
)
requests = _tenant_table(
    "requests",
    Column("idempotency_hash", LargeBinary(32), nullable=False),
    Column("result_ciphertext", LargeBinary),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    constraints=(UniqueConstraint("account_id", "idempotency_hash", name="uq_requests_account_idempotency"),),
    indexes=(("ix_requests_account_expires", "account_id", "expires_at"),),
)
attachments = _tenant_table(
    "attachments",
    Column("object_key", String(128), nullable=False),
    Column("wrapped_data_key", LargeBinary, nullable=False),
    Column("media_type", String(100), nullable=False),
    Column("byte_size", BigInteger, nullable=False),
    Column("state", String(16), nullable=False, server_default="active"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    constraints=(UniqueConstraint("account_id", "object_key", name="uq_attachments_account_object_key"),
        CheckConstraint("state IN ('pending','active','deleting')", name="ck_attachments_state")),
    indexes=(("ix_attachments_account_state_created", "account_id", "state", "created_at"),),
)
entity_photos = _tenant_table(
    "entity_photos",
    Column("entity_id", Uuid(as_uuid=True), nullable=False),
    Column("attachment_id", Uuid(as_uuid=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    constraints=(
        ForeignKeyConstraint(["account_id", "entity_id"], ["entities.account_id", "entities.id"],
                             ondelete="CASCADE", name="fk_entity_photos_entity"),
        ForeignKeyConstraint(["account_id", "attachment_id"], ["attachments.account_id", "attachments.id"],
                             ondelete="CASCADE", name="fk_entity_photos_attachment"),
        UniqueConstraint("account_id", "entity_id", "attachment_id", name="uq_entity_photos_link"),
    ),
)
links = _tenant_table(
    "links",
    Column("source_entity_id", Uuid(as_uuid=True), nullable=False),
    Column("target_entity_id", Uuid(as_uuid=True), nullable=False),
    Column("relationship", String(40), nullable=False),
    constraints=(
        ForeignKeyConstraint(["account_id", "source_entity_id"], ["entities.account_id", "entities.id"],
                             ondelete="CASCADE", name="fk_links_source"),
        ForeignKeyConstraint(["account_id", "target_entity_id"], ["entities.account_id", "entities.id"],
                             ondelete="CASCADE", name="fk_links_target"),
        UniqueConstraint("account_id", "source_entity_id", "target_entity_id", "relationship",
                         name="uq_links_relationship"),
    ),
)
tasks = _tenant_table(
    "tasks",
    Column("kind", String(40), nullable=False),
    Column("status", String(20), nullable=False),
    Column("result_ciphertext", LargeBinary),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    indexes=(("ix_tasks_account_status_created", "account_id", "status", "created_at"),),
)
invites = _tenant_table(
    "invites",
    Column("token_hash", LargeBinary(32), nullable=False, unique=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("max_uses", Integer, nullable=False),
    Column("used_count", Integer, nullable=False, server_default="0"),
    Column("revoked_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("max_uses > 0 AND used_count >= 0 AND used_count <= max_uses", name="ck_invites_use_count"),
)
audit_events = _tenant_table(
    "audit_events",
    Column("event_type", String(64), nullable=False),
    Column("target_id", Uuid(as_uuid=True)),
    Column("request_id", Uuid(as_uuid=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    indexes=(("ix_audit_events_account_created", "account_id", "created_at"),),
)
password_resets = _tenant_table(
    "password_resets",
    Column("token_hash", LargeBinary(32), nullable=False, unique=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    indexes=(("ix_password_resets_account_expires", "account_id", "expires_at"),),
)
auth_rate_limits = Table(
    "auth_rate_limits", metadata,
    Column("key_hash", LargeBinary(32), primary_key=True),
    Column("window_started", DateTime(timezone=True), nullable=False),
    Column("attempts", Integer, nullable=False),
)

TENANT_TABLES = (
    account_keys, sessions, privacy_consents, entities, history, requests, attachments,
    entity_photos, links, tasks, invites, audit_events, password_resets,
)
