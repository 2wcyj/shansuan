"""Browser-facing cloud auth routes, Origin checks, and cookie contracts."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import uuid

import asyncpg
from fastapi.testclient import TestClient

from app.backend.cloud.auth import AuthService, hash_password
from app.backend.cloud.config import CloudSettings


def _cloud_app_factory(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://app:unused@localhost/shansuan")
    monkeypatch.setenv("SESSION_SIGNING_KEY", "t" * 40)
    monkeypatch.setenv("FRONTEND_ORIGINS", "https://app.example.cn")
    monkeypatch.setenv("APP_ENV", "test")
    from app.backend.cloud_main import create_cloud_app
    return create_cloud_app


def test_registration_sets_secure_http_only_session_and_csrf_is_required(postgres_database, monkeypatch):
    signing_key = b"a" * 40
    service = AuthService(postgres_database["runtime_url"], signing_key=signing_key)
    owner_id = uuid.uuid4()
    email = f"owner-{owner_id}@example.test"

    async def seed_and_invite():
        admin = await asyncpg.connect(
            host=postgres_database["host"], port=postgres_database["port"],
            user="postgres", password=postgres_database["admin_password"],
            database=postgres_database["database"],
        )
        try:
            await admin.execute(
                "INSERT INTO accounts(id,email,password_hash,status,is_admin,created_at) "
                "VALUES($1,$2,'test-hash','active',true,now())", owner_id, email,
            )
        finally:
            await admin.close()
        return await service.create_invite(
            owner_id, max_uses=1, expires_at=datetime.now(timezone.utc) + timedelta(days=1)
        )

    invite = asyncio.run(seed_and_invite())
    settings = CloudSettings(
        "postgresql+asyncpg://runtime:unused@localhost/shansuan", signing_key,
        ("https://app.example.cn",), "production",
    )
    from app.tests.cloud.test_cloud_crypto import FakeKeyService
    app = _cloud_app_factory(monkeypatch)(settings, auth_service=service,
        key_manager=FakeKeyService())
    with TestClient(app, base_url="https://app.example.cn") as client:
        response = client.post(
            "/api/auth/register",
            json={"email": "friend@example.test", "password": "a-long-registration-passphrase",
                  "invite_token": invite},
            headers={"Origin": "https://app.example.cn"},
        )
        assert response.status_code == 201
        assert response.json()["account_id"]
        assert "secure" in response.headers["set-cookie"].lower()
        assert "httponly" in response.headers["set-cookie"].lower()
        assert "samesite=lax" in response.headers["set-cookie"].lower()
        assert client.cookies.get("shansuan_csrf") == response.json()["csrf"]
        assert "httponly" not in response.headers.get_list("set-cookie")[1].lower()

        session = client.get("/api/auth/session")
        assert session.status_code == 200
        assert session.json()["authenticated"] is True
        assert session.json()["csrf"] == response.json()["csrf"]
        assert client.get("/api/auth/me").status_code == 200

        no_csrf = client.post("/api/auth/logout", headers={"Origin": "https://app.example.cn"})
        assert no_csrf.status_code == 403
        non_admin = client.post(
            "/api/auth/invites", json={"max_uses": 1},
            headers={"Origin": "https://app.example.cn", "X-CSRF-Token": session.json()["csrf"]},
        )
        assert non_admin.status_code == 403
        logout = client.post(
            "/api/auth/logout",
            headers={"Origin": "https://app.example.cn", "X-CSRF-Token": session.json()["csrf"]},
        )
        assert logout.status_code == 204
        assert client.get("/api/auth/me").status_code == 401


def test_mutating_auth_route_rejects_an_unregistered_origin(postgres_database, monkeypatch):
    settings = CloudSettings(
        "postgresql+asyncpg://runtime:unused@localhost/shansuan", b"o" * 40,
        ("https://app.example.cn",), "test",
    )
    service = AuthService(postgres_database["runtime_url"], signing_key=b"o" * 40)
    with TestClient(_cloud_app_factory(monkeypatch)(settings, auth_service=service)) as client:
        response = client.post(
            "/api/auth/login", json={"email": "x@example.test", "password": "incorrect"},
            headers={"Origin": "https://attacker.example"},
        )
    assert response.status_code == 403
    assert response.json() == {"detail": "请求来源校验失败"}


def test_password_recovery_fails_closed_when_no_mailer_is_configured(postgres_database, monkeypatch):
    settings = CloudSettings(
        "postgresql+asyncpg://runtime:unused@localhost/shansuan", b"m" * 40,
        ("https://app.example.cn",), "test",
    )
    service = AuthService(postgres_database["runtime_url"], signing_key=b"m" * 40)
    with TestClient(_cloud_app_factory(monkeypatch)(settings, auth_service=service)) as client:
        response = client.post(
            "/api/auth/password/forgot", json={"email": "someone@example.test"},
            headers={"Origin": "https://app.example.cn"},
        )
    assert response.status_code == 503
    assert response.json() == {"detail": "密码恢复暂不可用，请联系管理员"}


def test_login_response_does_not_reveal_whether_an_email_exists(postgres_database, monkeypatch):
    account_id = uuid.uuid4()
    email = f"known-{account_id}@example.test"
    password = "known-account-password-is-long"
    async def seed_account():
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
    asyncio.run(seed_account())
    service = AuthService(postgres_database["runtime_url"], signing_key=b"n" * 40)
    settings = CloudSettings(
        "postgresql+asyncpg://runtime:unused@localhost/shansuan", b"n" * 40,
        ("https://app.example.cn",), "test",
    )
    with TestClient(_cloud_app_factory(monkeypatch)(settings, auth_service=service)) as client:
        unknown = client.post(
            "/api/auth/login", json={"email": "unknown@example.test", "password": password},
            headers={"Origin": "https://app.example.cn"},
        )
        wrong = client.post(
            "/api/auth/login", json={"email": email, "password": "wrong-password"},
            headers={"Origin": "https://app.example.cn"},
        )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json() == {"detail": "邮箱或密码错误"}
