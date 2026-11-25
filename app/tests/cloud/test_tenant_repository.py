"""Tenant repository keeps tenant identity in request context and PostgreSQL RLS."""
import asyncio
import uuid

import asyncpg
import pytest

from .test_cloud_crypto import FakeKeyService


def test_repository_requires_context_and_isolates_crud(postgres_database, run_async):
    from app.backend.cloud.context import TenantContextError, tenant_context
    from app.backend.cloud.crypto import CloudCrypto
    from app.backend.cloud.repository import TenantRepository

    account_a, account_b = uuid.uuid4(), uuid.uuid4()
    async def seed():
        connection = await asyncpg.connect(
            host=postgres_database["host"], port=postgres_database["port"],
            user="postgres", password=postgres_database["admin_password"],
            database=postgres_database["database"],
        )
        try:
            await connection.executemany(
                "INSERT INTO accounts(id,email,password_hash,status,is_admin,created_at) "
                "VALUES($1,$2,'not-a-real-hash','active',false,now())",
                [(account_a, f"{account_a}@example.test"),
                 (account_b, f"{account_b}@example.test")],
            )
        finally:
            await connection.close()
    run_async(seed())

    crypto = CloudCrypto(FakeKeyService())
    repository = TenantRepository(postgres_database["runtime_url"], crypto)
    with pytest.raises(TenantContextError):
        run_async(repository.list("profile"))

    async def exercise():
        with tenant_context(account_a):
            created = await repository.create("profile", {"name": "私有档案"})
            profile_id = created["id"]
        with tenant_context(account_b):
            assert await repository.get(profile_id) is None
            assert await repository.list("profile") == []
            assert await repository.update(profile_id, {"name": "越权修改"}) is None
            assert not await repository.delete(profile_id)
        with tenant_context(account_a):
            current = await repository.get(profile_id)
            assert current["body"] == {"name": "私有档案"}
            assert (await repository.update(profile_id, {"name": "已更新"}))["revision"] == 2
            assert (await repository.get(profile_id))["body"] == {"name": "已更新"}
            assert await repository.delete(profile_id)
            assert await repository.get(profile_id) is None
    run_async(exercise())

    async def pooled_access():
        pool = await asyncpg.create_pool(postgres_database['runtime_url'], min_size=1, max_size=1)
        try:
            pooled_repository = TenantRepository(pool, crypto)
            async def own_record(account_id, marker):
                with tenant_context(account_id):
                    entity = await pooled_repository.create('pool_test', {'marker': marker})
                    await asyncio.sleep(0)
                    rows = await pooled_repository.list('pool_test')
                    assert all(row['body']['marker'] == marker for row in rows)
                    return entity['id']
            first, second = await asyncio.gather(
                own_record(account_a, 'first'), own_record(account_b, 'second'))
            with tenant_context(account_a):
                assert await pooled_repository.get(second) is None
            with tenant_context(account_b):
                assert await pooled_repository.get(first) is None
            async with pool.acquire() as connection:
                assert await connection.fetchval('SELECT count(*) FROM entities') == 0
                encrypted = await connection.fetchval(
                    "SELECT current_setting('app.account_id',true)")
                assert encrypted in (None, '')
        finally:
            await pool.close()
    run_async(pooled_access())


def test_request_context_does_not_leak_across_async_tasks():
    from app.backend.cloud.context import current_tenant_id, tenant_context
    first, second = uuid.uuid4(), uuid.uuid4()
    async def read(value):
        with tenant_context(value):
            await asyncio.sleep(0)
            return current_tenant_id()
    async def check():
        return await asyncio.gather(read(first), read(second))
    assert asyncio.run(check()) == [first, second]


def test_domain_payload_history_and_idempotent_response_are_ciphertext_at_rest(
        postgres_database, run_async):
    from app.backend.cloud.domain_store import run_domain
    from app.backend.cloud.context import tenant_context
    from app.backend.cloud.crypto import CloudCrypto
    from app.backend.cloud.repository import TenantRepository

    account_id = uuid.uuid4()

    async def seed():
        connection = await asyncpg.connect(
            host=postgres_database["host"], port=postgres_database["port"],
            user="postgres", password=postgres_database["admin_password"],
            database=postgres_database["database"],
        )
        try:
            await connection.execute(
                "INSERT INTO accounts(id,email,password_hash,status,is_admin,created_at) "
                "VALUES($1,$2,'synthetic-test-only','active',false,now())",
                account_id, f"{account_id}@example.test",
            )
        finally:
            await connection.close()

    run_async(seed())
    repository = TenantRepository(
        postgres_database["runtime_url"], CloudCrypto(FakeKeyService()))
    secret = "SYNTHETIC-HEALTH-PAYLOAD-7fe12"
    response_marker = "SYNTHETIC-IDEMPOTENT-RESPONSE-954ac"

    async def persist_sensitive_data():
        with tenant_context(account_id):
            initial = await repository.create("profile", {"notes": secret})
            await repository.put(
                "profile", {"notes": secret + " revised"},
                entity_id=uuid.UUID(initial["id"]), expected_revision=1,
            )

            def operation(store):
                return store.mutate(
                    "request-secret-123", {"action": "synthetic"},
                    lambda: {"receipt": response_marker},
                )

            result = await run_domain(repository, account_id, operation)
            assert result == {"receipt": response_marker}

        connection = await asyncpg.connect(
            host=postgres_database["host"], port=postgres_database["port"],
            user="postgres", password=postgres_database["admin_password"],
            database=postgres_database["database"],
        )
        try:
            for table, column in (("entities", "body_ciphertext"),
                                  ("history", "body_ciphertext")):
                ciphertexts = await connection.fetch(
                    f"SELECT {column} FROM {table} WHERE account_id=$1", account_id)
                assert ciphertexts
                for row in ciphertexts:
                    stored = bytes(row[column])
                    assert secret.encode() not in stored
                    assert response_marker.encode() not in stored
        finally:
            await connection.close()

    run_async(persist_sensitive_data())
