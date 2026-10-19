"""Real proxy boundary tests; all health data is synthetic and isolated."""
from datetime import date
from contextlib import contextmanager

import httpx
from fastapi.testclient import TestClient

from app.backend.main import create_app
from app.tests.helpers import profile

TOKEN = 'a' * 64
HOST = 'https://192.168.8.8:18766'


@contextmanager
def mobile_client(tmp_path):
    from app.backend.mobile import create_mobile_app
    upstream = create_app(tmp_path)
    transport = httpx.ASGITransport(app=upstream)
    app = create_mobile_app('192.168.8.8', TOKEN, upstream_transport=transport)
    try:
        with TestClient(app, base_url=HOST) as client:
            yield client, upstream
    finally:
        upstream.state.tasks.close()
        upstream.state.store.close()


def authenticate(client):
    client.cookies.set('shansuan_mobile', TOKEN)
    response = client.get('/api/session')
    assert response.status_code == 200
    return {'X-CSRF-Token': response.json()['csrf']}


def test_unpaired_cannot_read_page_session_health_or_photo(tmp_path):
    with mobile_client(tmp_path) as (client, _):
        for path in ['/', '/api/session', '/api/profile', '/api/photos/nope']:
            assert client.get(path).status_code == 403
        client.cookies.set('shansuan_mobile', 'wrong')
        assert client.get('/api/profile').status_code == 403


def test_pairing_and_actual_profile_water_roundtrip(tmp_path):
    with mobile_client(tmp_path) as (client, upstream):
        headers = authenticate(client)
        assert client.get('/api/session').json()['mode'] == 'mobile'
        assert 'data_path' not in client.get('/api/status').text
        assert client.put('/api/profile', json={**profile(), 'version': 0}, headers=headers).status_code == 200
        day = date.today().isoformat()
        response = client.post('/api/life/water', json={'date': day, 'amount': 200, 'request_key': 'mobile-water-1'}, headers=headers)
        assert response.status_code == 200, response.text
        assert upstream.state.store.require('life', day)['water_ml'] == 200
        assert client.get('/api/profile').json()['profile']['age'] == 30
        # Idempotent retry and optimistic version checks survive the proxy.
        assert client.post('/api/life/water', json={'date': day, 'amount': 200, 'request_key': 'mobile-water-1'}, headers=headers).status_code == 200
        assert upstream.state.store.require('life', day)['water_ml'] == 200
        assert client.put('/api/profile', json={**profile(), 'version': 0}, headers=headers).status_code == 409


def test_csrf_origin_host_and_admin_restrictions(tmp_path):
    with mobile_client(tmp_path) as (client, _):
        headers = authenticate(client)
        assert client.put('/api/profile', json=profile()).status_code == 403
        assert client.put('/api/profile', json=profile(), headers={**headers, 'Origin': 'https://evil.example'}).status_code == 403
        assert client.get('/api/profile', headers={'Host': 'evil.example'}).status_code == 403
        assert client.get('/api/profile', headers={'Origin': 'http://192.168.8.8:18766'}).status_code == 403
        for path in ['/api/data/delete', '/api/data/restore/commit', '/api/shutdown']:
            assert client.post(path, json={}, headers=headers).status_code == 403
        assert client.get('/api/data/export/json').status_code == 403
        assert client.get('/api/data/backups').status_code == 403


def test_upstream_session_recovered_after_computer_restart(tmp_path):
    with mobile_client(tmp_path) as (client, upstream):
        authenticate(client)
        assert client.get('/api/profile').status_code == 200
        upstream.state.session = 'changed-after-restart'
        upstream.state.csrf = 'changed-csrf'
        assert client.get('/api/profile').status_code == 200


def test_photo_bytes_arrive_and_can_be_read_only_when_paired(tmp_path):
    import io
    from PIL import Image
    image = io.BytesIO()
    Image.new('RGB', (40, 40), '#94b5a7').save(image, 'JPEG')
    with mobile_client(tmp_path) as (client, _):
        headers = authenticate(client)
        response = client.post('/api/analyses', files={'file': ('meal.jpg', image.getvalue(), 'image/jpeg')}, headers=headers)
        assert response.status_code == 200, response.text
        photo = client.get('/api/photos/' + response.json()['photo_id'])
        assert photo.status_code == 200 and photo.headers['content-type'].startswith('image/jpeg')
        assert photo.content.startswith(b'\xff\xd8')
        client.cookies.clear()
        assert client.get('/api/photos/' + response.json()['photo_id']).status_code == 403


def test_proxy_rejects_oversize_before_upload_and_unsafe_method(tmp_path):
    with mobile_client(tmp_path) as (client, _):
        headers = authenticate(client)
        response = client.post('/api/analyses', content=b'x', headers={**headers, 'Content-Length': str(13 * 1024 * 1024)})
        assert response.status_code == 413
        assert client.request('TRACE', '/api/profile', headers=headers).status_code == 405


def test_connection_configuration_is_encrypted_and_certificate_matches_ip(tmp_path):
    import json
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from app.scripts.mobile import prepare_connection
    first = prepare_connection(tmp_path / 'private', tmp_path / 'share', '192.168.8.8')
    second = prepare_connection(tmp_path / 'private', tmp_path / 'share', '192.168.8.8')
    assert first['token'] == second['token']
    certificate = x509.load_pem_x509_certificate((tmp_path / 'private/server.crt').read_bytes())
    assert certificate.fingerprint(hashes.SHA256()).hex() == first['fingerprint']
    assert str(certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value[0].value) == '192.168.8.8'
    assert first['token'].encode() not in (tmp_path / 'private/connection.enc').read_bytes()
    key = serialization.load_pem_private_key((tmp_path / 'private/server.key').read_bytes(), password=first['token'].encode())
    assert key.public_key().public_numbers() == certificate.public_key().public_numbers()
    exported = json.loads((tmp_path / 'share/电脑连接.shansuan').read_text(encoding='utf-8'))
    assert exported['url'] == 'https://192.168.8.8:18766'
    assert exported['token'] == first['token']
    rotated = prepare_connection(tmp_path / 'private', tmp_path / 'share', '192.168.8.8', reset=True)
    assert rotated['token'] != first['token']


def test_only_explicit_lan_addresses_allowed():
    from app.backend.mobile import private_ipv4
    assert private_ipv4('192.168.1.5') and private_ipv4('172.20.10.7')
    for address in ['0.0.0.0', '127.0.0.1', '169.254.1.2', '8.8.8.8', '172.32.0.1', 'localhost', '::1']:
        assert not private_ipv4(address)
