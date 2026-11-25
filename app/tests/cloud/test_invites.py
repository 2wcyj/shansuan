"""Invite issuance, one-use registration, and credential reset integration tests."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import uuid

import asyncpg
import pytest


async def _seed_admin(postgres_database, account_id: uuid.UUID) -> None:
    connection = await asyncpg.connect(
        host=postgres_database["host"], port=postgres_database["port"],
        user="postgres", password=postgres_database["admin_password"],
        database=postgres_database["database"],
    )
    try:
        await connection.execute(
            "INSERT INTO accounts (id,email,password_hash,status,is_admin,created_at) "
            "VALUES ($1,$2,$3,'active',true,now())",
            account_id, f"admin-{account_id}@example.test", "$argon2id$test-only",
        )
    finally:
        await connection.close()


def test_invite_is_stored_only_as_a_hash_and_cannot_register_twice(postgres_database):
    from app.backend.cloud.auth import AuthService, InviteRejected

    service = AuthService(postgres_database["runtime_url"], signing_key=b"i" * 40)
    owner = uuid.uuid4()

    async def register_once():
        await _seed_admin(postgres_database, owner)
        token = await service.create_invite(owner, max_uses=1,
                                             expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
        first = await service.register("one@example.test", "a-long-registration-passphrase", token)
        assert first.account_id != owner
        with pytest.raises(InviteRejected, match="邀请码无效或已失效"):
            await service.register("two@example.test", "another-long-passphrase", token)
        admin = await asyncpg.connect(
            host=postgres_database["host"], port=postgres_database["port"],
            user="postgres", password=postgres_database["admin_password"],
            database=postgres_database["database"],
        )
        try:
            stored = await admin.fetchval("SELECT token_hash FROM invites WHERE account_id=$1", owner)
            assert stored == hashlib.sha256(token.encode()).digest()
            assert await admin.fetchval("SELECT count(*) FROM accounts WHERE email='two@example.test'") == 0
        finally:
            await admin.close()

    asyncio.run(register_once())


def test_concurrent_registration_cannot_exceed_invite_use_limit(postgres_database):
    from app.backend.cloud.auth import AuthService, InviteRejected

    service = AuthService(postgres_database["runtime_url"], signing_key=b"c" * 40)
    owner = uuid.uuid4()

    async def compete():
        await _seed_admin(postgres_database, owner)
        token = await service.create_invite(owner, max_uses=1,
                                             expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
        async def attempt(email):
            try:
                return await service.register(email, "long-concurrent-passphrase", token)
            except InviteRejected:
                return None
        results = await asyncio.gather(attempt("first@example.test"), attempt("second@example.test"))
        assert sum(result is not None for result in results) == 1

    asyncio.run(compete())


def test_admin_can_revoke_an_invite_before_it_is_used(postgres_database):
    from app.backend.cloud.auth import AuthService, InviteRejected

    service = AuthService(postgres_database["runtime_url"], signing_key=b"v" * 40)
    owner = uuid.uuid4()

    async def revoke_before_use():
        await _seed_admin(postgres_database, owner)
        token = await service.create_invite(
            owner, max_uses=3, expires_at=datetime.now(timezone.utc) + timedelta(days=1)
        )
        assert await service.revoke_invite(owner, token)
        with pytest.raises(InviteRejected):
            await service.register("revoked@example.test", "revoked-invite-password", token)

    asyncio.run(revoke_before_use())


def test_expired_and_malformed_invites_create_no_accounts(postgres_database):
    from app.backend.cloud.auth import AuthService, InviteRejected

    service = AuthService(postgres_database["runtime_url"], signing_key=b"e" * 40)

    async def reject_invalid():
        owner = uuid.uuid4()
        await _seed_admin(postgres_database, owner)
        expired_token = service._token("invite", owner)
        admin = await asyncpg.connect(
            host=postgres_database["host"], port=postgres_database["port"],
            user="postgres", password=postgres_database["admin_password"],
            database=postgres_database["database"],
        )
        try:
            await admin.execute(
                "INSERT INTO invites(account_id,id,token_hash,expires_at,max_uses,used_count,created_at) "
                "VALUES($1,$2,$3,now()-interval '1 hour',1,0,now())",
                owner, uuid.uuid4(), hashlib.sha256(expired_token.encode()).digest(),
            )
        finally:
            await admin.close()
        for token in ("bad-token", "v1." + str(uuid.uuid4()) + ".random", expired_token):
            with pytest.raises(InviteRejected, match="邀请码无效或已失效"):
                await service.register("nobody@example.test", "long-enough-passphrase", token)
        admin = await asyncpg.connect(
            host=postgres_database["host"], port=postgres_database["port"],
            user="postgres", password=postgres_database["admin_password"],
            database=postgres_database["database"],
        )
        try:
            assert await admin.fetchval(
                "SELECT count(*) FROM accounts WHERE email='nobody@example.test'"
            ) == 0
        finally:
            await admin.close()
    asyncio.run(reject_invalid())
