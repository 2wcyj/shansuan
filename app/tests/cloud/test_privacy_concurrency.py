"""Real PostgreSQL races for password reauthentication and privacy operations."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import uuid

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.backend.cloud.auth import AuthService, hash_password
from app.backend.cloud.config import CloudSettings
from app.backend.cloud.crypto import CloudCrypto
from app.backend.cloud.repository import TenantRepository
from app.tests.cloud.test_cloud_crypto import FakeKeyService


@pytest.fixture
def privacy_account(postgres_database, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgresql+asyncpg://unused@localhost/shansuan')
    monkeypatch.setenv('SESSION_SIGNING_KEY', 'r' * 40)
    monkeypatch.setenv('FRONTEND_ORIGINS', 'https://app.example.cn')
    monkeypatch.setenv('APP_ENV', 'test')
    from app.backend.cloud_main import create_cloud_app
    database = postgres_database
    account_id = uuid.uuid4()
    password = 'privacy-concurrency-old-password'
    service = AuthService(database['runtime_url'], signing_key=b'r' * 40)

    async def admin():
        return await asyncpg.connect(host=database['host'], port=database['port'],
            user='postgres', password=database['admin_password'], database=database['database'])

    async def seed():
        connection = await admin()
        try:
            await connection.execute("INSERT INTO accounts(id,email,password_hash,status,is_admin) "
                "VALUES($1,$2,$3,'active',false)", account_id, f'{account_id}@example.test', hash_password(password))
        finally:
            await connection.close()
        return await service.login(f'{account_id}@example.test', password, remote_key=str(account_id))

    session = asyncio.run(seed())
    repository = TenantRepository(database['runtime_url'], CloudCrypto(FakeKeyService()))
    settings = CloudSettings(database['runtime_url'], b'r' * 40, ('https://app.example.cn',), 'test')
    client = TestClient(create_cloud_app(settings, auth_service=service, tenant_repository=repository))
    client.cookies.set('shansuan_session', session.cookie_token)
    headers = {'Origin': 'https://app.example.cn', 'X-CSRF-Token': session.csrf_token}
    yield client, headers, service, account_id, password, admin
    client.close()


@pytest.mark.parametrize('operation', ['export', 'delete'])
def test_privacy_and_password_reset_are_serialized(privacy_account, monkeypatch, operation):
    import app.backend.cloud.auth as auth
    client, headers, service, account_id, password, admin = privacy_account
    entered, release = threading.Event(), threading.Event()
    original = auth.verify_password

    def paused_verify(supplied, stored):
        if supplied == password:
            entered.set()
            assert release.wait(15), 'test did not release password verification'
        return original(supplied, stored)

    monkeypatch.setattr(auth, 'verify_password', paused_verify)

    def privacy_request():
        if operation == 'export':
            return client.post('/api/privacy/export', headers=headers, json={'password': password})
        return client.request('DELETE', '/api/privacy/account', headers=headers, json={
            'password': password, 'confirmation': '删除我的云端账户及全部数据'})

    async def race():
        connection = await admin()
        pid = connection.get_server_pid()
        reset_hash = hash_password('replacement-password-concurrency')

        async def reset():
            async with connection.transaction():
                await connection.execute("SELECT set_config('app.account_id',$1,true)", str(account_id))
                return await connection.fetchval('SELECT cloud_update_password($1,$2)', account_id, reset_hash)

        observer = await admin()
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(privacy_request)
                assert await asyncio.to_thread(entered.wait, 10)
                task = asyncio.create_task(reset())
                try:
                    deadline = time.monotonic() + 10
                    while not task.done():
                        waiting = await observer.fetchval(
                            "SELECT wait_event_type='Lock' FROM pg_stat_activity WHERE pid=$1", pid)
                        if waiting:
                            break
                        assert time.monotonic() < deadline, 'reset neither completed nor waited for a lock'
                        await asyncio.sleep(0.02)
                    assert not task.done(), 'password reset completed while old-password privacy operation was running'
                finally:
                    release.set()
                    reset_result = await task
                    response = await asyncio.to_thread(future.result, 15)
                assert response.status_code == 200, response.text
                assert reset_result is (operation == 'export')
        finally:
            release.set()
            await observer.close()
            await connection.close()
    asyncio.run(race())


@pytest.mark.parametrize('mutation', ['delete', 'password_reset', 'logout'])
def test_waiting_export_rechecks_account_and_session(privacy_account, mutation):
    client, headers, service, account_id, password, admin = privacy_account

    async def race():
        connection = await admin()
        observer = await admin()
        transaction = connection.transaction()
        await transaction.start()
        await connection.execute("SELECT set_config('app.account_id',$1,true)", str(account_id))
        await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", 'domain:' + str(account_id))
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(client.post, '/api/privacy/export',
                    headers=headers, json={'password': password})
                try:
                    deadline = time.monotonic() + 10
                    while not await observer.fetchval(
                        "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' AND NOT granted)"):
                        assert not future.done(), 'export should wait for the account lock'
                        assert time.monotonic() < deadline, 'export did not reach account lock'
                        await asyncio.sleep(0.02)
                    if mutation == 'delete':
                        assert await connection.fetchval('SELECT cloud_delete_account($1)', account_id)
                    elif mutation == 'password_reset':
                        assert await connection.fetchval('SELECT cloud_update_password($1,$2)',
                            account_id, hash_password('replacement-password-before-export'))
                    else:
                        await connection.execute('UPDATE sessions SET revoked_at=now() WHERE account_id=$1', account_id)
                finally:
                    await transaction.commit()
                response = await asyncio.to_thread(future.result, 15)
                assert response.status_code in (401, 403), response.text
                assert 'shansuan-account-export-v1' not in response.text
        finally:
            await observer.close()
            await connection.close()
    asyncio.run(race())


def test_old_password_login_cannot_create_a_session_after_password_reset(privacy_account, monkeypatch):
    import app.backend.cloud.auth as auth
    client, headers, service, account_id, password, admin = privacy_account
    entered, release = threading.Event(), threading.Event()
    original = auth.verify_password

    def paused_verify(supplied, stored):
        entered.set()
        assert release.wait(15)
        return original(supplied, stored)

    monkeypatch.setattr(auth, 'verify_password', paused_verify)

    async def race():
        connection = await admin()
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(asyncio.run, service.login(
                    f'{account_id}@example.test', password, remote_key='login-reset-' + str(account_id)))
                try:
                    assert await asyncio.to_thread(entered.wait, 10)
                    async with connection.transaction():
                        await connection.execute("SELECT set_config('app.account_id',$1,true)", str(account_id))
                        assert await connection.fetchval('SELECT cloud_update_password($1,$2)',
                            account_id, hash_password('password-reset-before-session-created'))
                finally:
                    release.set()
                with pytest.raises(auth.InvalidCredentials):
                    await asyncio.to_thread(future.result, 10)
                assert await connection.fetchval(
                    'SELECT count(*) FROM sessions WHERE account_id=$1 AND revoked_at IS NULL', account_id) == 0
        finally:
            release.set()
            await connection.close()
    asyncio.run(race())


@pytest.mark.parametrize('operation', ['export', 'password_reset'])
def test_credentials_expiring_while_waiting_for_lock_are_rejected(privacy_account, operation):
    client, headers, service, account_id, password, admin = privacy_account
    token = service._token('password-reset', account_id)

    async def race():
        import hashlib
        connection = await admin()
        observer = await admin()
        if operation == 'password_reset':
            await connection.execute(
                "INSERT INTO password_resets(account_id,id,token_hash,expires_at,created_at) "
                "VALUES($1,$2,$3,clock_timestamp()+interval '5 minutes',clock_timestamp())",
                account_id, uuid.uuid4(), hashlib.sha256(token.encode()).digest())
        transaction = connection.transaction()
        await transaction.start()
        await connection.execute("SELECT set_config('app.account_id',$1,true)", str(account_id))
        if operation == 'export':
            await connection.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'domain:' + str(account_id))
        else:
            await connection.fetchrow('SELECT * FROM cloud_lock_account_credentials($1)', account_id)
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                if operation == 'export':
                    future = executor.submit(client.post, '/api/privacy/export',
                        headers=headers, json={'password': password})
                else:
                    future = executor.submit(asyncio.run,
                        service.complete_password_reset(token, 'expired-token-must-not-change-password'))
                try:
                    deadline = time.monotonic() + 10
                    while not await observer.fetchval(
                        "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() "
                        "AND pid<>pg_backend_pid() AND wait_event_type='Lock')"):
                        assert not future.done(), 'operation should wait for the held lock'
                        assert time.monotonic() < deadline, 'operation did not wait for a lock'
                        await asyncio.sleep(0.02)
                    table = 'sessions' if operation == 'export' else 'password_resets'
                    await connection.execute(f'UPDATE {table} SET expires_at=clock_timestamp() WHERE account_id=$1', account_id)
                finally:
                    await transaction.commit()
                result = await asyncio.to_thread(future.result, 15)
                if operation == 'export':
                    assert result.status_code in (401, 403), result.text
                else:
                    assert result is False, 'expired reset token changed the password after lock wait'
        finally:
            await observer.close()
            await connection.close()
    asyncio.run(race())
