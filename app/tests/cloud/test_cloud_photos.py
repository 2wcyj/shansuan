"""Private photo lifecycle against real PostgreSQL/RLS, with synthetic object bytes only."""
import asyncio
from contextlib import ExitStack
import io
import re
import uuid

import asyncpg
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from app.backend.cloud.auth import AuthService, hash_password
from app.backend.cloud.config import CloudSettings
from app.backend.cloud.crypto import CloudCrypto
from app.backend.cloud.context import tenant_context
from app.backend.cloud.repository import TenantRepository
from app.tests.cloud.test_cloud_crypto import FakeKeyService


class MemoryObjects:
    """External storage double; a timed-out write may already have stored bytes."""
    def __init__(self):
        self.values = {}
        self.calls = []
        self.fail_put = False
        self.fail_delete = False
        self.after_put = None

    def check(self):
        return True

    def put(self, key, content):
        self.calls.append(('put', key))
        self.values[key] = bytes(content)
        if self.after_put:
            self.after_put()
        if self.fail_put:
            raise OSError('synthetic storage secret must not be returned')

    def get(self, key, limit):
        self.calls.append(('get', key))
        value = self.values[key]
        if len(value) > limit:
            raise OSError('oversized object')
        return value

    def delete(self, key):
        self.calls.append(('delete', key))
        if self.fail_delete:
            raise OSError('synthetic delete secret must not be returned')
        self.values.pop(key, None)


def image_bytes(fmt='PNG'):
    output = io.BytesIO()
    image = Image.new('RGB', (50, 40), 'green')
    exif = Image.Exif()
    exif[270] = 'synthetic-private-exif-marker'
    image.save(output, format=fmt, exif=exif)
    return output.getvalue()


@pytest.fixture
def photo_app(postgres_database, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgresql+asyncpg://unused@localhost/shansuan')
    monkeypatch.setenv('SESSION_SIGNING_KEY', 'photo-synthetic-signing-key-000001')
    monkeypatch.setenv('FRONTEND_ORIGINS', 'https://app.example.cn')
    monkeypatch.setenv('APP_ENV', 'test')
    from app.backend.cloud_main import create_cloud_app
    service = AuthService(postgres_database['runtime_url'], signing_key=b'p' * 40)
    accounts = [uuid.uuid4(), uuid.uuid4()]
    async def seed():
        connection = await asyncpg.connect(host=postgres_database['host'], port=postgres_database['port'],
            user='postgres', password=postgres_database['admin_password'], database=postgres_database['database'])
        try:
            await connection.executemany(
                "INSERT INTO accounts(id,email,password_hash,status,is_admin) VALUES($1,$2,$3,'active',false)",
                [(account, str(account)+'@example.test', hash_password('photo-test-password')) for account in accounts])
        finally:
            await connection.close()
        return [await service.login(str(account)+'@example.test', 'photo-test-password', remote_key=str(account)) for account in accounts]
    sessions = asyncio.run(seed())
    repository = TenantRepository(postgres_database['runtime_url'], CloudCrypto(FakeKeyService()))
    objects = MemoryObjects()
    app = create_cloud_app(CloudSettings('postgresql+asyncpg://unused@localhost/shansuan', b'p'*40,
        ('https://app.example.cn',), 'test'), auth_service=service, tenant_repository=repository)
    app.state.object_store = objects
    with ExitStack() as stack:
        # Separate cookie jars; no production database, credentials, or real image.
        clients = [stack.enter_context(TestClient(app)), stack.enter_context(TestClient(app))]
        headers = []
        from app.backend.api.cloud_privacy import NOTICE_VERSION
        for client, session in zip(clients, sessions):
            client.cookies.set('shansuan_session', session.cookie_token)
            header = {'Origin':'https://app.example.cn', 'X-CSRF-Token':session.csrf_token}
            headers.append(header)
            assert client.post('/api/privacy/consent', headers=header,
                json={'notice_version':NOTICE_VERSION, 'confirmed':True}).status_code == 200
        yield app, clients, headers, accounts, objects, repository


def upload(client, headers, content=None, mime='image/png'):
    return client.post('/api/analyses', headers=headers,
        files={'file':('sensitive-original-name.png', image_bytes() if content is None else content, mime)})


def test_photos_are_encrypted_and_account_isolated_without_creating_intake(photo_app):
    app, clients, headers, accounts, objects, repository = photo_app
    response = upload(clients[0], headers[0])
    assert response.status_code == 200, response.text
    photo = response.json()
    assert photo['status'] == 'draft' and photo['items'] == []
    assert re.fullmatch(r'[0-9a-f]{32}', photo['photo_id'])
    assert 'object_key' not in photo and 'wrapped_data_key' not in photo
    assert clients[0].get('/api/analyses').json()['items'][0]['id'] == photo['id']
    assert clients[1].get('/api/analyses').json()['items'] == []
    calls = len(objects.calls)
    assert clients[1].get('/api/photos/'+photo['photo_id']).status_code == 404
    assert clients[1].delete('/api/photos/'+photo['photo_id'], headers=headers[1]).status_code == 404
    assert len(objects.calls) == calls, 'unauthorized lookups must not touch object storage'
    actual = clients[0].get('/api/photos/'+photo['photo_id'])
    assert actual.status_code == 200 and actual.headers['content-type'] == 'image/jpeg'
    assert actual.headers['cache-control'] == 'no-store'
    assert b'synthetic-private-exif-marker' not in actual.content
    assert Image.open(io.BytesIO(actual.content)).format == 'JPEG'
    [(key, ciphertext)] = objects.values.items()
    assert re.fullmatch(r'photos/[0-9a-f]{64}\.enc', key)
    assert image_bytes() not in ciphertext and actual.content not in ciphertext
    assert 'sensitive' not in key and str(accounts[0]) not in key
    from datetime import date
    assert clients[0].get('/api/records', params={'date':date.today().isoformat()}).json()['record_count'] == 0


def test_photo_upload_validates_type_size_and_consent_before_storage(photo_app):
    _, clients, headers, _, objects, _ = photo_app
    assert upload(clients[0], headers[0], b'not an image').status_code == 400
    assert upload(clients[0], headers[0], mime='image/jpeg').status_code == 400
    assert upload(clients[0], headers[0], b'x'*(12*1024*1024+1)).status_code == 413
    assert upload(clients[0], headers[0], image_bytes('GIF'), 'image/gif').status_code == 400
    assert upload(clients[0], {'Origin':headers[0]['Origin']}).status_code == 403
    assert objects.values == {}
    assert clients[0].post('/api/privacy/consent/withdraw', headers=headers[0]).status_code == 200
    assert upload(clients[0], headers[0]).status_code == 428
    assert clients[0].get('/api/analyses').status_code == 428
    clients[0].cookies.clear()
    assert upload(clients[0], headers[0]).status_code == 401
    assert objects.values == {}


def test_tampered_object_fails_closed_and_delete_removes_bytes_and_analysis(photo_app):
    _, clients, headers, _, objects, _ = photo_app
    photo = upload(clients[0], headers[0]).json()
    key = next(iter(objects.values))
    original = objects.values[key]
    objects.values[key] = original[:-1]+bytes([original[-1]^1])
    failed = clients[0].get('/api/photos/'+photo['photo_id'])
    assert failed.status_code == 503
    assert key not in failed.text and 'Traceback' not in failed.text
    objects.values[key] = original
    assert clients[0].delete('/api/photos/'+photo['photo_id'], headers=headers[0]).status_code == 200
    assert objects.values == {}
    assert clients[0].get('/api/photos/'+photo['photo_id']).status_code == 404
    assert clients[0].get('/api/analyses').json()['items'] == []


def test_uncertain_upload_failure_is_durably_tracked_until_cleanup_succeeds(photo_app):
    app, clients, headers, accounts, objects, repository = photo_app
    objects.fail_put = objects.fail_delete = True
    response = upload(clients[0], headers[0])
    assert response.status_code == 503 and 'secret' not in response.text
    assert len(objects.values) == 1
    assert clients[0].get('/api/analyses').json()['items'] == []
    async def inspect_and_cleanup():
        with tenant_context(accounts[0]):
            async with repository._tenant_connection() as (_, connection):
                rows = await connection.fetch('SELECT id,state FROM attachments WHERE account_id=$1', accounts[0])
            assert len(rows) == 1 and rows[0]['state'] == 'deleting'
            objects.fail_put = objects.fail_delete = False
            assert await app.state.cloud_photos.cleanup_pending() == 1
            async with repository._tenant_connection() as (_, connection):
                assert await connection.fetchval('SELECT count(*) FROM attachments WHERE account_id=$1', accounts[0]) == 0
    asyncio.run(inspect_and_cleanup())
    assert objects.values == {}


def test_delete_failure_revokes_access_and_is_retryable(photo_app):
    _, clients, headers, _, objects, _ = photo_app
    photo = upload(clients[0], headers[0]).json()
    objects.fail_delete = True
    assert clients[0].delete('/api/photos/'+photo['photo_id'], headers=headers[0]).status_code == 503
    assert clients[0].get('/api/photos/'+photo['photo_id']).status_code == 404
    assert clients[0].get('/api/analyses').json()['items'] == []
    assert len(objects.values) == 1
    objects.fail_delete = False
    assert clients[0].delete('/api/photos/'+photo['photo_id'], headers=headers[0]).status_code == 200
    assert objects.values == {}


def test_withdrawal_while_uploading_cannot_publish_photo(photo_app):
    _, clients, headers, _, objects, _ = photo_app
    def withdraw():
        assert clients[0].post('/api/privacy/consent/withdraw', headers=headers[0]).status_code == 200
    objects.after_put = withdraw
    response = upload(clients[0], headers[0])
    assert response.status_code == 428, response.text
    assert objects.values == {}, 'withdrawal during transfer must clean uploaded ciphertext'


def test_account_photo_quota_counts_active_and_pending_bytes(photo_app):
    app, clients, headers, _, objects, _ = photo_app
    from app.backend.cloud.photos import CloudPhotos
    app.state.cloud_photos = CloudPhotos(app.state.tenant_repository, objects, max_count=1)
    photo = upload(clients[0], headers[0])
    assert photo.status_code == 200
    rejected = upload(clients[0], headers[0])
    assert rejected.status_code == 429
    assert len(objects.values) == 1


def test_unconfigured_cloud_photo_service_does_not_fall_back_to_local_storage(photo_app):
    app, clients, headers, _, objects, _ = photo_app
    app.state.cloud_photos = None
    response = upload(clients[0], headers[0])
    assert response.status_code == 503
    assert objects.values == {}


def test_large_upload_never_spools_plaintext_to_a_temporary_file(photo_app, monkeypatch):
    _, clients, headers, _, _, _ = photo_app
    import starlette.formparsers
    def forbid_plaintext_file(*args, **kwargs):
        raise AssertionError('Cloud photo plaintext must remain in bounded memory')
    monkeypatch.setattr(starlette.formparsers, 'SpooledTemporaryFile', forbid_plaintext_file)
    # A valid image with synthetic trailing padding crosses Starlette's usual spool threshold.
    response = upload(clients[0], headers[0], image_bytes()+b'\0'*(2*1024*1024))
    assert response.status_code == 200, response.text


def test_malformed_or_multiple_upload_parts_are_rejected_without_storage(photo_app):
    _, clients, headers, _, objects, _ = photo_app
    bad = clients[0].post('/api/analyses', headers={**headers[0], 'Content-Type':'multipart/form-data'}, content=b'invalid')
    assert bad.status_code == 400
    response = clients[0].post('/api/analyses', headers=headers[0], files=[
        ('file', ('first.png', image_bytes(), 'image/png')),
        ('file', ('second.png', image_bytes(), 'image/png'))])
    assert response.status_code == 400
    assert objects.values == {}


def test_byte_quota_rejects_before_external_upload(photo_app):
    app, clients, headers, _, objects, _ = photo_app
    from app.backend.cloud.photos import CloudPhotos
    app.state.cloud_photos = CloudPhotos(app.state.tenant_repository, objects, max_bytes=10)
    assert upload(clients[0], headers[0]).status_code == 429
    assert objects.values == {}


def test_expired_pending_reservation_is_cleaned_after_restart(photo_app):
    app, clients, headers, accounts, objects, repository = photo_app
    photo = upload(clients[0], headers[0]).json()
    async def simulate_interruption():
        with tenant_context(accounts[0]):
            async with repository._tenant_connection() as (_, connection):
                await connection.execute("UPDATE attachments SET state='pending',created_at=clock_timestamp()-interval '2 hours' WHERE account_id=$1", accounts[0])
            from app.backend.cloud.photos import CloudPhotos
            restarted = CloudPhotos(repository, objects)
            assert await restarted.cleanup_pending() == 1
    asyncio.run(simulate_interruption())
    assert objects.values == {}
    assert clients[0].get('/api/photos/'+photo['photo_id']).status_code == 404
