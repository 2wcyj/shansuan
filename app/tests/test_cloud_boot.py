import importlib
import sys

import pytest
from fastapi.testclient import TestClient


def test_cloud_settings_fail_closed_without_required_secrets(monkeypatch):
    from app.backend.cloud.config import CloudSettings

    for key in ('DATABASE_URL', 'SESSION_SIGNING_KEY', 'FRONTEND_ORIGINS'):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValueError, match='DATABASE_URL'):
        CloudSettings.from_env()


def test_cloud_settings_reject_short_session_key_and_wildcard_origin(monkeypatch):
    from app.backend.cloud.config import CloudSettings

    monkeypatch.setenv('DATABASE_URL', 'postgresql+asyncpg://app:secret@db.example/test')
    monkeypatch.setenv('SESSION_SIGNING_KEY', 'too-short')
    monkeypatch.setenv('FRONTEND_ORIGINS', 'https://app.example.cn')
    with pytest.raises(ValueError, match='32 bytes'):
        CloudSettings.from_env()
    monkeypatch.setenv('SESSION_SIGNING_KEY', 's' * 40)
    monkeypatch.setenv('FRONTEND_ORIGINS', '*')
    with pytest.raises(ValueError, match='wildcard'):
        CloudSettings.from_env()


def test_cloud_settings_repr_never_exposes_session_secret():
    from app.backend.cloud.config import CloudSettings

    settings = CloudSettings('postgresql+asyncpg://app:secret@db.example/test', 's' * 40,
                             ('https://app.example.cn',), 'test')
    assert 's' * 40 not in repr(settings)
    assert 'secret' not in repr(settings)


def test_live_health_has_no_user_or_configuration_details(monkeypatch):
    for key, value in {
        'DATABASE_URL': 'postgresql+asyncpg://app:secret@db.example/test',
        'SESSION_SIGNING_KEY': 's' * 40,
        'FRONTEND_ORIGINS': 'https://app.example.cn',
        'APP_ENV': 'test',
    }.items():
        monkeypatch.setenv(key, value)
    sys.modules.pop('app.backend.cloud_main', None)
    module = importlib.import_module('app.backend.cloud_main')
    with TestClient(module.app) as client:
        response = client.get('/health/live')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}
    assert 'secret' not in response.text


def test_cloud_readiness_never_claims_ready_without_database(monkeypatch):
    from app.backend.cloud.config import CloudSettings
    from app.backend.cloud_main import create_cloud_app

    settings = CloudSettings('postgresql+asyncpg://app:secret@db.example/test', 's' * 40,
                             ('https://app.example.cn',), 'test')
    with TestClient(create_cloud_app(settings)) as client:
        response = client.get('/health/ready')
    assert response.status_code == 503
    assert response.json() == {'status': 'not_ready', 'dependencies': {'database': False}}


def test_cloud_readiness_fails_closed_without_leaking_dependency_errors():
    from app.backend.cloud.config import CloudSettings
    from app.backend.cloud_main import create_cloud_app

    def failed_probe():
        raise RuntimeError('database password must never reach a response')

    settings = CloudSettings('postgresql+asyncpg://app:secret@db.example/test', 's' * 40,
                             ('https://app.example.cn',), 'test')
    with TestClient(create_cloud_app(settings, failed_probe)) as client:
        response = client.get('/health/ready')
    assert response.status_code == 503
    assert response.json() == {'status': 'not_ready', 'dependencies': {'database': False}}
    assert 'password' not in response.text


def test_production_server_starts_but_reports_not_ready_when_database_is_down(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgresql+asyncpg://app:unused@localhost/test')
    monkeypatch.setenv('SESSION_SIGNING_KEY', 't' * 40)
    monkeypatch.setenv('FRONTEND_ORIGINS', 'https://app.example.cn')
    monkeypatch.setenv('APP_ENV', 'test')
    from app.backend.cloud.config import CloudSettings
    from app.backend.cloud_main import create_cloud_app
    from app.tests.cloud.test_cloud_crypto import FakeKeyService
    monkeypatch.setattr(FakeKeyService, 'check', lambda self: True, raising=False)
    monkeypatch.setattr('app.backend.cloud_main.key_manager_from_env', lambda environment: FakeKeyService())

    settings = CloudSettings(
        'postgresql+asyncpg://app:secret@db.invalid/test', 'k' * 40,
        ('https://app.example.cn',), 'production',
    )
    with TestClient(create_cloud_app(settings)) as client:
        response = client.get('/health/ready')
    assert response.status_code == 503
    assert response.json() == {'status': 'not_ready', 'dependencies': {'database': False, 'kms': True}}


def test_production_refuses_to_start_without_kms(monkeypatch):
    from app.backend.cloud_main import create_cloud_app
    from app.backend.cloud.config import CloudSettings
    for key in ('KMS_PROVIDER', 'KMS_REGION_ID', 'KMS_KEY_ID'):
        monkeypatch.delenv(key, raising=False)
    settings = CloudSettings('postgresql+asyncpg://synthetic@db.invalid/test', b'k' * 40,
                             ('https://app.example.cn',), 'production')
    with pytest.raises(ValueError, match='KMS'):
        with TestClient(create_cloud_app(settings)):
            pytest.fail('unconfigured production server accepted startup')


def test_kms_outage_fails_startup_and_later_readiness_without_secret_leak(monkeypatch):
    from app.backend.cloud_main import create_cloud_app
    from app.backend.cloud.config import CloudSettings
    from app.backend.cloud.kms import KMSUnavailable

    class UnavailableManager:
        available = False
        checks = 0
        def check(self):
            self.checks += 1
            if not self.available:
                raise KMSUnavailable()
            return True

    manager = UnavailableManager()
    monkeypatch.setattr('app.backend.cloud_main.key_manager_from_env', lambda environment: manager)
    settings = CloudSettings('postgresql+asyncpg://synthetic@db.invalid/test', b'k' * 40,
                             ('https://app.example.cn',), 'production')
    with pytest.raises(KMSUnavailable):
        with TestClient(create_cloud_app(settings)):
            pytest.fail('KMS outage allowed startup')
    manager.available = True
    # Inject auth only to avoid connecting to a real database; startup check is cached.
    with TestClient(create_cloud_app(settings, readiness_probe=lambda: True, auth_service=object())) as client:
        assert client.get('/health/ready').json() == {
            'status': 'ready', 'dependencies': {'database': True, 'kms': True}}
        manager.available = False
        response = client.get('/health/ready')
        assert response.status_code == 200
        assert response.json() == {'status': 'ready', 'dependencies': {'database': True, 'kms': True}}
        checks_after_start = manager.checks
        assert checks_after_start == 2, 'one failed startup probe and one successful startup probe are expected'
        assert manager.checks == checks_after_start, 'readiness polling must not incur repeated KMS operations'
