"""Encrypted tenant entity repository guarded by request context and PostgreSQL RLS."""
from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
import asyncio
import json
import re
from uuid import UUID, uuid4

import asyncpg

from app.backend.cloud.context import current_tenant_id
from app.backend.cloud.crypto import CloudCrypto


_KIND = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")


class TenantRepository:
    def __init__(self, database, crypto: CloudCrypto):
        if crypto is None:
            raise ValueError("CloudCrypto is required")
        self.database = database
        self.crypto = crypto
        self._transaction = ContextVar("tenant_repository_transaction", default=None)

    @asynccontextmanager
    async def _connection(self):
        if isinstance(self.database, str):
            url = self.database.replace("postgresql+asyncpg://", "postgresql://", 1)
            connection = await asyncpg.connect(url)
            try:
                yield connection
            finally:
                await connection.close()
        else:
            async with self.database.acquire() as connection:
                yield connection

    @asynccontextmanager
    async def _tenant_connection(self):
        account_id = current_tenant_id()
        active = self._transaction.get()
        if active is not None:
            owner, connection, task = active
            if owner != account_id or task is not asyncio.current_task():
                raise RuntimeError("Transaction cannot be shared across accounts or tasks")
            yield account_id, connection
            return
        async with self._connection() as connection:
            async with connection.transaction():
                await connection.execute("SELECT set_config('app.account_id',$1,true)", str(account_id))
                yield account_id, connection

    @asynccontextmanager
    async def atomic(self, *, connection=None):
        if connection is not None:
            account_id = current_tenant_id()
            if self._transaction.get() is not None:
                raise RuntimeError('Cannot replace an active repository transaction')
            configured = await connection.fetchval("SELECT current_setting('app.account_id', true)")
            if configured != str(account_id) or not connection.is_in_transaction():
                raise RuntimeError('External transaction must belong to the current account')
            token = self._transaction.set((account_id, connection, asyncio.current_task()))
            try:
                yield
            finally:
                self._transaction.reset(token)
            return
        async with self._tenant_connection() as (account_id, connection):
            token = self._transaction.set((account_id, connection, asyncio.current_task()))
            try:
                yield
            finally:
                self._transaction.reset(token)

    async def _data_key(self, connection, account_id: UUID) -> bytes:
        stored = await connection.fetchval(
            "SELECT wrapped_key FROM account_keys WHERE account_id=$1", account_id
        )
        if stored is None:
            _, wrapped = await asyncio.to_thread(self.crypto.create_data_key, account_id)
            await connection.execute(
                "INSERT INTO account_keys(account_id,wrapped_key,created_at) VALUES($1,$2,now()) "
                "ON CONFLICT(account_id) DO NOTHING", account_id, wrapped,
            )
            stored = await connection.fetchval(
                "SELECT wrapped_key FROM account_keys WHERE account_id=$1", account_id
            )
        return await asyncio.to_thread(self.crypto.unwrap_data_key, account_id, stored)

    async def lock_account(self):
        if self._transaction.get() is None:
            raise RuntimeError('Account lock requires an enclosing repository transaction')
        async with self._tenant_connection() as (account_id, connection):
            await connection.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',
                                     'domain:' + str(account_id))

    @staticmethod
    def _validate_kind(kind: str) -> None:
        if not isinstance(kind, str) or not _KIND.fullmatch(kind):
            raise ValueError("Invalid entity kind")

    @staticmethod
    def _encode_body(body: dict) -> bytes:
        if not isinstance(body, dict):
            raise ValueError("Entity body must be a JSON object")
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        if len(payload) > 1_000_000:
            raise ValueError("Entity body exceeds the 1 MB limit")
        return payload

    @staticmethod
    def _associated_data(account_id: UUID, entity_id: UUID, kind: str) -> bytes:
        return f"{entity_id}:{kind}".encode("ascii")

    def _decode(self, row, account_id: UUID, key: bytes) -> dict:
        body_bytes = self.crypto.decrypt(
            account_id, key, row["body_ciphertext"],
            self._associated_data(account_id, row["id"], row["kind"]),
        )
        return {"id": str(row["id"]), "kind": row["kind"],
                "revision": row["revision"], "body": json.loads(body_bytes)}

    async def create(self, kind: str, body: dict) -> dict:
        self._validate_kind(kind)
        encoded = self._encode_body(body)
        async with self._tenant_connection() as (account_id, connection):
            entity_id = uuid4()
            key = await self._data_key(connection, account_id)
            encrypted = self.crypto.encrypt(
                account_id, key, encoded, self._associated_data(account_id, entity_id, kind)
            )
            row = await connection.fetchrow(
                "INSERT INTO entities(account_id,id,kind,body_ciphertext,revision,created_at,updated_at) "
                "VALUES($1,$2,$3,$4,1,now(),now()) "
                "RETURNING id,kind,revision,body_ciphertext",
                account_id, entity_id, kind, encrypted,
            )
            return self._decode(row, account_id, key)

    async def put(self, kind: str, body: dict, *, entity_id: UUID,
                  expected_revision: int = 0) -> dict | None:
        """Create or optimistically update an entity with a server-chosen stable id."""
        self._validate_kind(kind)
        if not isinstance(entity_id, UUID) or expected_revision < 0:
            raise ValueError("Invalid entity identity or revision")
        encoded = self._encode_body(body)
        async with self._tenant_connection() as (account_id, connection):
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                f"{account_id}:{kind}:{entity_id}",
            )
            row = await connection.fetchrow(
                "SELECT id,kind,revision,body_ciphertext FROM entities "
                "WHERE account_id=$1 AND id=$2", account_id, entity_id,
            )
            key = await self._data_key(connection, account_id)
            if row is None:
                if expected_revision != 0:
                    return None
                encrypted = self.crypto.encrypt(
                    account_id, key, encoded,
                    self._associated_data(account_id, entity_id, kind),
                )
                row = await connection.fetchrow(
                    "INSERT INTO entities(account_id,id,kind,body_ciphertext,revision,created_at,updated_at) "
                    "VALUES($1,$2,$3,$4,1,now(),now()) "
                    "RETURNING id,kind,revision,body_ciphertext",
                    account_id, entity_id, kind, encrypted,
                )
            else:
                if row["kind"] != kind or row["revision"] != expected_revision:
                    return None
                await self._save_history(connection, account_id, key, row)
                encrypted = self.crypto.encrypt(
                    account_id, key, encoded,
                    self._associated_data(account_id, entity_id, kind),
                )
                row = await connection.fetchrow(
                    "UPDATE entities SET body_ciphertext=$4,revision=revision+1,updated_at=now() "
                    "WHERE account_id=$1 AND id=$2 AND revision=$3 "
                    "RETURNING id,kind,revision,body_ciphertext",
                    account_id, entity_id, expected_revision, encrypted,
                )
                if row is None:
                    return None
            return self._decode(row, account_id, key)

    async def _save_history(self, connection, account_id, key, row):
        history_id = uuid4()
        old = self._decode(row, account_id, key)
        ciphertext = self.crypto.encrypt(
            account_id, key, self._encode_body(old),
            f"history:{history_id}:{row['id']}".encode('ascii'),
        )
        await connection.execute(
            'INSERT INTO history(account_id,id,entity_id,body_ciphertext) VALUES($1,$2,$3,$4)',
            account_id, history_id, row['id'], ciphertext,
        )

    async def get(self, entity_id: UUID | str) -> dict | None:
        async with self._tenant_connection() as (account_id, connection):
            row = await connection.fetchrow(
                "SELECT id,kind,revision,body_ciphertext FROM entities WHERE account_id=$1 AND id=$2",
                account_id, UUID(str(entity_id)),
            )
            result = None
            if row:
                key = await self._data_key(connection, account_id)
                result = self._decode(row, account_id, key)
            return result

    async def list(self, kind: str | None = None) -> list[dict]:
        if kind is not None:
            self._validate_kind(kind)
        async with self._tenant_connection() as (account_id, connection):
            rows = await connection.fetch(
                "SELECT id,kind,revision,body_ciphertext FROM entities "
                "WHERE account_id=$1 AND ($2::text IS NULL OR kind=$2) ORDER BY created_at,id",
                account_id, kind,
            )
            key = await self._data_key(connection, account_id) if rows else None
            return [self._decode(row, account_id, key) for row in rows]

    async def export_history(self) -> list[dict]:
        """Decrypt the current tenant's revision history for an authenticated rights export."""
        async with self._tenant_connection() as (account_id, connection):
            rows = await connection.fetch(
                'SELECT id,entity_id,body_ciphertext,created_at FROM history '
                'WHERE account_id=$1 ORDER BY created_at,id', account_id)
            key = await self._data_key(connection, account_id) if rows else None
            return [{
                'id': str(row['id']), 'entity_id': str(row['entity_id']),
                'created_at': row['created_at'].isoformat(),
                'data': json.loads(self.crypto.decrypt(
                    account_id, key, row['body_ciphertext'],
                    f"history:{row['id']}:{row['entity_id']}".encode('ascii'))),
            } for row in rows]

    async def update(self, entity_id: UUID | str, body: dict,
                     expected_revision: int | None = None) -> dict | None:
        encoded = self._encode_body(body)
        async with self._tenant_connection() as (account_id, connection):
            entity_id = UUID(str(entity_id))
            row = await connection.fetchrow(
                "SELECT id,kind,revision FROM entities WHERE account_id=$1 AND id=$2",
                account_id, entity_id,
            )
            result = None
            if row and (expected_revision is None or row["revision"] == expected_revision):
                key = await self._data_key(connection, account_id)
                encrypted = self.crypto.encrypt(
                    account_id, key, encoded,
                    self._associated_data(account_id, entity_id, row["kind"]),
                )
                updated = await connection.fetchrow(
                    "UPDATE entities SET body_ciphertext=$3,revision=revision+1,updated_at=now() "
                    "WHERE account_id=$1 AND id=$2 AND revision=$4 "
                    "RETURNING id,kind,revision,body_ciphertext",
                    account_id, entity_id, encrypted, row["revision"],
                )
                if updated:
                    result = self._decode(updated, account_id, key)
            return result

    async def delete(self, entity_id: UUID | str) -> bool:
        async with self._tenant_connection() as (account_id, connection):
            result = await connection.execute(
                "DELETE FROM entities WHERE account_id=$1 AND id=$2",
                account_id, UUID(str(entity_id)),
            )
            return result == "DELETE 1"
