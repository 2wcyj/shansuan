"""PostgreSQL integration tests for schema and forced tenant isolation."""
from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
import uuid

import asyncpg
from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import MetaData
import app.backend.cloud.models as cloud_models

from .conftest import ALEMBIC_INI


TENANT_TABLES = {
    "sessions", "privacy_consents", "entities", "history", "requests",
    "attachments", "entity_photos", "links", "tasks", "invites", "audit_events",
    "password_resets", "account_keys",
}


def test_delete_account_function_rejects_cross_account_and_last_administrator(postgres_database):
    async def check():
        connection = await asyncpg.connect(
            host=postgres_database['host'], port=postgres_database['port'], user='postgres',
            password=postgres_database['admin_password'], database=postgres_database['database'])
        transaction = connection.transaction()
        await transaction.start()
        try:
            await connection.execute('UPDATE accounts SET is_admin=false WHERE is_admin')
            owner, other = uuid.uuid4(), uuid.uuid4()
            await connection.executemany(
                "INSERT INTO accounts(id,email,password_hash,status,is_admin) VALUES($1,$2,'synthetic','active',$3)",
                [(owner, f'{owner}@example.test', True), (other, f'{other}@example.test', False)])
            await connection.execute('SET LOCAL ROLE shansuan_runtime')
            await connection.execute("SELECT set_config('app.account_id',$1,true)", str(owner))
            assert await connection.fetchval('SELECT cloud_delete_account($1)', other) is False
            assert await connection.fetchval('SELECT cloud_delete_account($1)', owner) is False
            assert await connection.fetchval('SELECT status FROM cloud_account_status($1)', owner) == 'active'
        finally:
            await transaction.rollback()
            await connection.close()
    asyncio.run(check())


def test_tenant_tables_require_account_and_enforce_foreign_keys(postgres_database, run_async):
    async def inspect_schema():
        connection = await asyncpg.connect(postgres_database["runtime_url"])
        try:
            role = await connection.fetchrow(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )
            assert tuple(role) == (False, False)
            for table in sorted(TENANT_TABLES):
                account_column = await connection.fetchrow(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=$1 AND column_name='account_id'",
                    table,
                )
                assert account_column and account_column["is_nullable"] == "NO", table
                account_fk = await connection.fetchval(
                    "SELECT count(*) FROM pg_constraint "
                    "WHERE conrelid=to_regclass('public.' || $1) AND contype='f' "
                    "AND confrelid='public.accounts'::regclass "
                    "AND pg_get_constraintdef(oid) LIKE 'FOREIGN KEY (account_id)%'", table,
                )
                assert account_fk == 1, table
                account_index = await connection.fetchval(
                    "SELECT count(*) FROM pg_indexes WHERE schemaname='public' AND tablename=$1 "
                    "AND indexdef LIKE '%(account_id%'", table,
                )
                assert account_index >= 1, table
                protected = await connection.fetchrow(
                    "SELECT c.relrowsecurity, c.relforcerowsecurity "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public' AND c.relname=$1", table,
                )
                assert protected and tuple(protected) == (True, True), table
                owner = await connection.fetchval(
                    "SELECT tableowner FROM pg_tables WHERE schemaname='public' AND tablename=$1", table
                )
                assert owner == "shansuan_migrator", table
                policy = await connection.fetchval(
                    "SELECT count(*) FROM pg_policies WHERE schemaname='public' "
                    "AND tablename=$1 AND policyname='tenant_account_isolation'", table
                )
                assert policy == 1, table
        finally:
            await connection.close()
    run_async(inspect_schema())


def test_initial_migration_is_independent_of_future_live_models(postgres_database, monkeypatch):
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_database["migration_url"].replace("%", "%%"))
    command.downgrade(config, "base")
    monkeypatch.setattr(cloud_models, "metadata", MetaData())
    monkeypatch.setattr(cloud_models, "TENANT_TABLES", ())
    command.upgrade(config, "0001_accounts_entities")

    async def migrated_tables():
        connection = await asyncpg.connect(
            host=postgres_database["host"], port=postgres_database["port"],
            user="postgres", password=postgres_database["admin_password"],
            database=postgres_database["database"],
        )
        try:
            return await connection.fetchval(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE' "
                "AND table_name <> 'alembic_version'"
            )
        finally:
            await connection.close()
    assert asyncio.run(migrated_tables()) == 12


def test_forced_rls_hides_other_accounts_and_rejects_cross_account_writes(
    postgres_database, run_async
):
    account_a, account_b = uuid.uuid4(), uuid.uuid4()
    entity_a, entity_b = uuid.uuid4(), uuid.uuid4()

    async def exercise_policy():
        admin = await asyncpg.connect(
            host=postgres_database["host"], port=postgres_database["port"],
            user="postgres", password=postgres_database["admin_password"],
            database=postgres_database["database"],
        )
        try:
            await admin.executemany(
                "INSERT INTO accounts (id,email,password_hash,status,created_at) "
                "VALUES ($1,$2,$3,'active',now())",
                [(account_a, f"{account_a}@example.test", "hash-a"),
                 (account_b, f"{account_b}@example.test", "hash-b")],
            )
            await admin.executemany(
                "INSERT INTO entities (id,account_id,kind,body_ciphertext,revision,created_at,updated_at) "
                "VALUES ($1,$2,'profile',decode('00','hex'),1,now(),now())",
                [(entity_a, account_a), (entity_b, account_b)],
            )
        finally:
            await admin.close()

        runtime = await asyncpg.connect(postgres_database["runtime_url"])
        try:
            assert await runtime.fetchval("SELECT count(*) FROM entities") == 0
            async with runtime.transaction():
                await runtime.execute("SELECT set_config('app.account_id',$1,true)", str(account_a))
                visible = await runtime.fetch("SELECT id,account_id FROM entities")
                assert [tuple(row) for row in visible] == [(entity_a, account_a)]
            async with runtime.transaction():
                await runtime.execute("SELECT set_config('app.account_id',$1,true)", str(account_a))
                assert await runtime.execute(
                    "UPDATE entities SET body_ciphertext=decode('01','hex') WHERE id=$1", entity_b
                ) == "UPDATE 0"
                assert await runtime.execute("DELETE FROM entities WHERE id=$1", entity_b) == "DELETE 0"
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                async with runtime.transaction():
                    await runtime.execute("SELECT set_config('app.account_id',$1,true)", str(account_a))
                    await runtime.execute(
                        "INSERT INTO entities (id,account_id,kind,body_ciphertext,revision,created_at,updated_at) "
                        "VALUES ($1,$2,'profile',decode('01','hex'),1,now(),now())",
                        uuid.uuid4(), account_b,
                    )
            async with runtime.transaction():
                await runtime.execute("SELECT set_config('app.account_id',$1,true)", str(account_b))
                unchanged = await runtime.fetchval(
                    "SELECT body_ciphertext FROM entities WHERE id=$1", entity_b
                )
                assert unchanged == b"\x00"
        finally:
            await runtime.close()
    run_async(exercise_policy())


def test_initial_migration_can_downgrade_and_upgrade_again(postgres_database):
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_database["migration_url"].replace("%", "%%"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    async def current_revision():
        connection = await asyncpg.connect(
            host=postgres_database["host"], port=postgres_database["port"],
            user="postgres", password=postgres_database["admin_password"],
            database=postgres_database["database"],
        )
        try:
            return await connection.fetchval("SELECT version_num FROM alembic_version")
        finally:
            await connection.close()
    assert asyncio.run(current_revision()) == "0006_attachment_lifecycle"
