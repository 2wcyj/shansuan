"""Password and account-session authentication integration tests."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import uuid

import asyncpg
import pytest


def test_password_hashes_are_argon2id_and_never_contain_the_password():
    from app.backend.cloud.auth import hash_password, verify_password

    password = "long-passphrase-for-local-test-92"
    stored = hash_password(password)
    assert stored.startswith("$argon2id$")
    assert password not in stored
    assert verify_password(password, stored) is True
    assert verify_password("different-passphrase", stored) is False


def test_privacy_password_reverification_is_rate_limited(postgres_database):
    from app.backend.cloud.auth import AuthService, LoginRateLimited
    service = AuthService(postgres_database['runtime_url'], signing_key=b'p' * 40)
    account_id = uuid.uuid4()

    async def verify_limit():
        for _ in range(12):
            assert await service.verify_account_password(account_id, 'incorrect-password') == (False, None)
        with pytest.raises(LoginRateLimited):
            await service.verify_account_password(account_id, 'incorrect-password')
    asyncio.run(verify_limit())


def test_first_admin_is_created_only_through_the_separate_migration_role(postgres_database):
    from app.backend.cloud.admin_cli import create_admin_account
    from app.backend.cloud.auth import AuthService
    import pytest

    email = "bootstrap-admin@example.test"
    password = "one-time-bootstrap-password"
    service = AuthService(postgres_database["runtime_url"], signing_key=b"z" * 40)

    async def bootstrap_and_issue_invite():
        account_id = await create_admin_account(postgres_database["migration_url"], email, password)
        issued = await service.login(email, password, remote_key="bootstrap-ip")
        principal = await service.authenticate(issued.cookie_token)
        assert principal is not None and principal.is_admin
        invite = await service.create_invite(account_id, max_uses=1,
                                              expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
        assert invite.startswith("v1.")
        with pytest.raises(ValueError, match="administrator already exists"):
            await create_admin_account(
                postgres_database["migration_url"], "second-admin@example.test", password
            )
        with pytest.raises(ValueError, match="migration account"):
            await create_admin_account(
                postgres_database["runtime_url"], "forbidden-admin@example.test", password
            )

    asyncio.run(bootstrap_and_issue_invite())


def test_runtime_role_cannot_create_accounts_without_invite_registration(postgres_database):
    async def attempt_direct_insert():
        connection = await asyncpg.connect(postgres_database["runtime_url"])
        try:
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute(
                    "INSERT INTO accounts(id,email,password_hash,status,created_at) "
                    "VALUES($1,$2,$3,'active',now())",
                    uuid.uuid4(), "bypass@example.test", "$argon2id$not-a-real-hash",
                )
        finally:
            await connection.close()
    asyncio.run(attempt_direct_insert())


def test_login_uses_one_error_for_unknown_email_and_wrong_password(postgres_database):
    from app.backend.cloud.auth import AuthService, InvalidCredentials

    service = AuthService(postgres_database["runtime_url"], signing_key=b"a" * 40)

    async def verify_generic_failure():
        with pytest.raises(InvalidCredentials, match="邮箱或密码错误"):
            await service.login("unknown@example.test", "incorrect-passphrase", remote_key="test-ip")

    asyncio.run(verify_generic_failure())


def test_repeated_login_failures_are_limited_without_echoing_the_email(postgres_database):
    from app.backend.cloud.auth import AuthService, InvalidCredentials, LoginRateLimited

    service = AuthService(postgres_database["runtime_url"], signing_key=b"r" * 40)

    async def exhaust_limit():
        messages = []
        for _ in range(8):
            with pytest.raises(InvalidCredentials) as error:
                await service.login("same@example.test", "wrong-password", remote_key="same-ip")
            messages.append(str(error.value))
        assert len(set(messages)) == 1
        assert "same@example.test" not in messages[0]
        with pytest.raises(LoginRateLimited):
            await service.login("same@example.test", "wrong-password", remote_key="same-ip")
    asyncio.run(exhaust_limit())


def test_revoking_a_session_prevents_future_authentication(postgres_database):
    from app.backend.cloud.auth import AuthService, hash_password

    service = AuthService(postgres_database["runtime_url"], signing_key=b"b" * 40)
    account_id = uuid.uuid4()
    email = f"{account_id}@example.test"
    password = "session-test-password-is-long"

    async def verify_revocation():
        admin = await asyncpg.connect(
            host=postgres_database["host"], port=postgres_database["port"],
            user="postgres", password=postgres_database["admin_password"],
            database=postgres_database["database"],
        )
        try:
            await admin.execute(
                "INSERT INTO accounts (id,email,password_hash,status,is_admin,created_at) "
                "VALUES ($1,$2,$3,'active',false,now())",
                account_id, email, hash_password(password),
            )
        finally:
            await admin.close()
        issued = await service.login(email, password, remote_key="session-test-ip")
        assert len(issued.cookie_token.encode()) >= 32
        await service.authenticate(issued.cookie_token)
        await service.logout(issued.cookie_token)
        assert await service.authenticate(issued.cookie_token) is None

    asyncio.run(verify_revocation())


def test_session_database_stores_only_a_hash_and_suspended_accounts_are_rejected(postgres_database):
    from app.backend.cloud.auth import AuthService, hash_password

    service = AuthService(postgres_database["runtime_url"], signing_key=b"s" * 40)
    account_id = uuid.uuid4()
    email = f"suspended-{account_id}@example.test"
    password = "suspension-test-password"

    async def verify_storage_and_suspension():
        admin = await asyncpg.connect(
            host=postgres_database["host"], port=postgres_database["port"],
            user="postgres", password=postgres_database["admin_password"],
            database=postgres_database["database"],
        )
        try:
            await admin.execute(
                "INSERT INTO accounts(id,email,password_hash,status,is_admin,created_at) "
                "VALUES($1,$2,$3,'active',false,now())", account_id, email, hash_password(password),
            )
        finally:
            await admin.close()
        issued = await service.login(email, password, remote_key="suspension-ip")
        check = await asyncpg.connect(
            host=postgres_database["host"], port=postgres_database["port"],
            user="postgres", password=postgres_database["admin_password"],
            database=postgres_database["database"],
        )
        try:
            stored = await check.fetchrow(
                "SELECT token_hash,expires_at FROM sessions WHERE account_id=$1", account_id
            )
            assert stored["token_hash"] == hashlib.sha256(issued.cookie_token.encode()).digest()
            assert stored["expires_at"] > datetime.now(timezone.utc)
        finally:
            await check.close()
        admin = await asyncpg.connect(
            host=postgres_database["host"], port=postgres_database["port"],
            user="postgres", password=postgres_database["admin_password"],
            database=postgres_database["database"],
        )
        try:
            await admin.execute("UPDATE accounts SET status='suspended' WHERE id=$1", account_id)
        finally:
            await admin.close()
        assert await service.authenticate(issued.cookie_token) is None
    asyncio.run(verify_storage_and_suspension())


def test_password_change_checks_current_password_and_revokes_existing_sessions(postgres_database):
    from app.backend.cloud.auth import AuthService, hash_password, InvalidCredentials

    service = AuthService(postgres_database["runtime_url"], signing_key=b"c" * 40)
    account_id = uuid.uuid4()
    email = f"change-{account_id}@example.test"
    old_password = "current-password-is-long-enough"
    new_password = "replacement-password-is-long"

    async def change_flow():
        admin = await asyncpg.connect(
            host=postgres_database["host"], port=postgres_database["port"],
            user="postgres", password=postgres_database["admin_password"],
            database=postgres_database["database"],
        )
        try:
            await admin.execute(
                "INSERT INTO accounts(id,email,password_hash,status,is_admin,created_at) "
                "VALUES($1,$2,$3,'active',false,now())", account_id, email, hash_password(old_password),
            )
        finally:
            await admin.close()
        issued = await service.login(email, old_password, remote_key="change-ip")
        assert not await service.change_password(account_id, "wrong-current-password", new_password)
        assert await service.change_password(account_id, old_password, new_password)
        assert await service.authenticate(issued.cookie_token) is None
        with pytest.raises(InvalidCredentials):
            await service.login(email, old_password, remote_key="change-old")
        assert (await service.login(email, new_password, remote_key="change-new")).account_id == account_id

    asyncio.run(change_flow())


def test_password_reset_token_is_hashed_single_use_and_revokes_sessions(postgres_database):
    from app.backend.cloud.auth import AuthService, hash_password, InvalidCredentials

    service = AuthService(postgres_database["runtime_url"], signing_key=b"p" * 40)
    account_id = uuid.uuid4()
    email = f"reset-{account_id}@example.test"
    old_password = "old-password-for-reset-flow"
    new_password = "new-password-for-reset-flow"

    class FakeMailer:
        token = None
        async def send_password_reset(self, address, token):
            assert address == email
            self.token = token

    mailer = FakeMailer()

    async def reset_flow():
        admin = await asyncpg.connect(
            host=postgres_database["host"], port=postgres_database["port"],
            user="postgres", password=postgres_database["admin_password"],
            database=postgres_database["database"],
        )
        try:
            await admin.execute(
                "INSERT INTO accounts(id,email,password_hash,status,is_admin,created_at) "
                "VALUES($1,$2,$3,'active',false,now())", account_id, email, hash_password(old_password),
            )
        finally:
            await admin.close()
        session = await service.login(email, old_password, remote_key="reset-ip")
        assert await service.request_password_reset(email, remote_key="reset-ip", mailer=mailer)
        assert mailer.token
        check = await asyncpg.connect(
            host=postgres_database["host"], port=postgres_database["port"],
            user="postgres", password=postgres_database["admin_password"],
            database=postgres_database["database"],
        )
        try:
            stored = await check.fetchval("SELECT token_hash FROM password_resets WHERE account_id=$1", account_id)
            assert stored == hashlib.sha256(mailer.token.encode()).digest()
        finally:
            await check.close()
        assert await service.complete_password_reset(mailer.token, new_password)
        assert not await service.complete_password_reset(mailer.token, "another-new-reset-password")
        assert await service.authenticate(session.cookie_token) is None
        with pytest.raises(InvalidCredentials):
            await service.login(email, old_password, remote_key="old-after-reset")
        assert (await service.login(email, new_password, remote_key="new-after-reset")).account_id == account_id

    asyncio.run(reset_flow())
