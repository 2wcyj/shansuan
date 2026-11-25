"""Real PostgreSQL account locks protect domain read / calculate / write cycles."""
import asyncio
from uuid import uuid4

import asyncpg

from app.backend.cloud.context import tenant_context
from app.backend.cloud.crypto import CloudCrypto
from app.backend.cloud.domain_store import run_domain
from app.backend.cloud.repository import TenantRepository
from app.tests.cloud.test_cloud_crypto import FakeKeyService


def test_domain_concurrent_mutations_and_tombstones_are_tenant_private(postgres_database):
    accounts = [uuid4(), uuid4()]

    async def exercise():
        connection = await asyncpg.connect(
            host=postgres_database['host'], port=postgres_database['port'], user='postgres',
            password=postgres_database['admin_password'], database=postgres_database['database'])
        try:
            await connection.executemany(
                "INSERT INTO accounts(id,email,password_hash,status,is_admin,created_at) "
                "VALUES($1,$2,'synthetic-test-only','active',false,now())",
                [(account, f'{account}@example.test') for account in accounts])
        finally:
            await connection.close()

        pool = await asyncpg.create_pool(postgres_database['runtime_url'], min_size=1, max_size=3)
        repository = TenantRepository(pool, CloudCrypto(FakeKeyService()))
        try:
            async def increment(account, request_key):
                def operation(store):
                    def write():
                        old = store.get('counter', 'self')
                        return store.put('counter', 'self', {'count': (old['count'] if old else 0) + 1},
                                         version=old['version'] if old else 0)
                    return store.mutate(request_key, {'action': 'increment'}, write)
                return await run_domain(repository, account, operation)

            # One duplicated key per account, interleaved on a shared real connection pool.
            results = await asyncio.gather(*[
                increment(account, f'counter-request-{index // 2}')
                for index in range(8) for account in accounts])
            for offset in (0, 1):
                own = results[offset::2]
                for index in range(0, len(own), 2):
                    assert own[index] == own[index + 1]
            for account in accounts:
                counter = await run_domain(repository, account, lambda store: store.require('counter', 'self'))
                assert counter['count'] == 4
                assert counter['version'] == 4

            await run_domain(repository, accounts[0], lambda store: store.delete('counter', 'self', 4))
            assert await run_domain(repository, accounts[0], lambda store: store.list('counter')) == []
            assert (await run_domain(repository, accounts[1], lambda store: store.require('counter', 'self')))['count'] == 4
            restored = await increment(accounts[0], 'counter-after-delete')
            assert restored['version'] == 5
            assert restored['count'] == 1
            # A replay after deletion preserves the original response without writing again.
            replay = await increment(accounts[0], 'counter-request-0')
            assert replay['count'] == 1
            assert replay['version'] == 1
            assert (await run_domain(repository, accounts[0], lambda store: store.require('counter', 'self')))['version'] == 5
            for account in accounts:
                with tenant_context(account):
                    rows = await repository.list()
                    assert len([row for row in rows if row['kind'] == 'mutation_request']) == (5 if account == accounts[0] else 4)
            async with pool.acquire() as returned:
                assert await returned.fetchval('SELECT count(*) FROM entities') == 0
                assert await returned.fetchval("SELECT current_setting('app.account_id',true)") in (None, '')
        finally:
            await pool.close()

    asyncio.run(exercise())
