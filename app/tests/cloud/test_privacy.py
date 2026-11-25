"""Sensitive-information consent must precede every cloud health-data write."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
from datetime import datetime, timezone
import uuid

import asyncpg
from fastapi import Depends
from fastapi.testclient import TestClient
import pytest

from app.backend.cloud.auth import AuthService, hash_password
from app.backend.cloud.config import CloudSettings


def test_health_write_requires_current_explicit_consent_and_withdrawal_closes_gate(
    postgres_database, monkeypatch
):
    from app.backend.api.cloud_privacy import NOTICE_VERSION, require_current_health_consent, router

    account_id = uuid.uuid4()
    email = f"consent-{account_id}@example.test"
    password = "privacy-consent-test-password"
    signing_key = b"v" * 40
    service = AuthService(postgres_database["runtime_url"], signing_key=signing_key)

    async def seed_login():
        admin = await asyncpg.connect(
            host=postgres_database["host"], port=postgres_database["port"],
            user="postgres", password=postgres_database["admin_password"],
            database=postgres_database["database"],
        )
        try:
            await admin.execute(
                "INSERT INTO accounts(id,email,password_hash,status,is_admin,created_at) "
                "VALUES($1,$2,$3,'active',false,now())",
                account_id, email, hash_password(password),
            )
        finally:
            await admin.close()
        return await service.login(email, password, remote_key="consent-test-ip")

    issued = asyncio.run(seed_login())
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://app:unused@localhost/shansuan")
    monkeypatch.setenv("SESSION_SIGNING_KEY", "t" * 40)
    monkeypatch.setenv("FRONTEND_ORIGINS", "https://app.example.cn")
    monkeypatch.setenv("APP_ENV", "test")
    from app.backend.cloud_main import create_cloud_app

    settings = CloudSettings(
        "postgresql+asyncpg://runtime:unused@localhost/shansuan", signing_key,
        ("https://app.example.cn",), "test",
    )
    app = create_cloud_app(settings, auth_service=service)

    @app.post("/api/test/health-write")
    async def health_write(_principal=Depends(require_current_health_consent)):
        return {"stored": True}

    with TestClient(app) as client:
        client.cookies.set("shansuan_session", issued.cookie_token)
        client.cookies.set("shansuan_csrf", issued.csrf_token)
        headers = {"Origin": "https://app.example.cn", "X-CSRF-Token": issued.csrf_token}
        blocked = client.post("/api/test/health-write", headers=headers)
        assert blocked.status_code == 428
        assert blocked.json()["detail"] == "请先阅读并明确同意当前敏感个人信息处理说明"

        consent = client.post(
            "/api/privacy/consent",
            json={"notice_version": NOTICE_VERSION, "confirmed": True},
            headers={**headers, "User-Agent": "Privacy consent test browser"},
        )
        assert consent.status_code == 200
        assert consent.json()["accepted"] is True
        assert client.post("/api/test/health-write", headers={"Origin": headers["Origin"]}).status_code == 403
        assert client.post("/api/test/health-write", headers=headers).status_code == 200

        async def inspect_consent():
            connection = await asyncpg.connect(
                host=postgres_database["host"], port=postgres_database["port"],
                user="postgres", password=postgres_database["admin_password"],
                database=postgres_database["database"],
            )
            try:
                return await connection.fetchrow(
                    "SELECT user_agent_digest,granted_at,withdrawn_at FROM privacy_consents "
                    "WHERE account_id=$1 AND notice_version=$2 ORDER BY created_at DESC LIMIT 1",
                    account_id, NOTICE_VERSION,
                )
            finally:
                await connection.close()
        row = asyncio.run(inspect_consent())
        expected = hmac.new(signing_key, b"user-agent:Privacy consent test browser", hashlib.sha256).digest()
        assert row["user_agent_digest"] == expected
        assert row["withdrawn_at"] is None

        withdrawn = client.post("/api/privacy/consent/withdraw", headers=headers)
        assert withdrawn.status_code == 200
        assert client.get("/api/privacy/consent").json() == {
            "accepted": False, "notice_version": NOTICE_VERSION,
        }
        assert client.post("/api/test/health-write", headers=headers).status_code == 428
        assert client.get("/api/auth/me").status_code == 200


def test_wrong_or_unconfirmed_notice_version_is_not_accepted(postgres_database, monkeypatch):
    from app.backend.api.cloud_privacy import NOTICE_VERSION

    account_id = uuid.uuid4()
    email = f"stale-{account_id}@example.test"
    password = "privacy-notice-version-password"
    service = AuthService(postgres_database["runtime_url"], signing_key=b"w" * 40)

    async def seed_and_login():
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
        return await service.login(email, password, remote_key="stale-consent-ip")

    issued = asyncio.run(seed_and_login())
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://app:unused@localhost/shansuan")
    monkeypatch.setenv("SESSION_SIGNING_KEY", "t" * 40)
    monkeypatch.setenv("FRONTEND_ORIGINS", "https://app.example.cn")
    monkeypatch.setenv("APP_ENV", "test")
    from app.backend.cloud_main import create_cloud_app

    settings = CloudSettings("postgresql+asyncpg://runtime:unused@localhost/shansuan", b"w" * 40,
                             ("https://app.example.cn",), "test")
    with TestClient(create_cloud_app(settings, auth_service=service)) as client:
        client.cookies.set("shansuan_session", issued.cookie_token)
        response = client.post(
            "/api/privacy/consent", json={"notice_version": "old-draft", "confirmed": True},
            headers={"Origin": "https://app.example.cn", "X-CSRF-Token": issued.csrf_token},
        )
        unconfirmed = client.post(
            "/api/privacy/consent", json={"notice_version": NOTICE_VERSION, "confirmed": False},
            headers={"Origin": "https://app.example.cn", "X-CSRF-Token": issued.csrf_token},
        )
    assert response.status_code == 409
    assert response.json() == {"detail": "请刷新并阅读当前版本的隐私说明"}
    assert unconfirmed.status_code == 400


def test_privacy_notice_is_public_but_consent_requires_authentication(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://app:unused@localhost/shansuan")
    monkeypatch.setenv("SESSION_SIGNING_KEY", "t" * 40)
    monkeypatch.setenv("FRONTEND_ORIGINS", "https://app.example.cn")
    monkeypatch.setenv("APP_ENV", "test")
    from app.backend.api.cloud_privacy import NOTICE_VERSION
    from app.backend.cloud_main import create_cloud_app

    class NoSession:
        async def authenticate(self, token):
            return None

    settings = CloudSettings("postgresql+asyncpg://runtime:unused@localhost/shansuan", b"w" * 40,
                             ("https://app.example.cn",), "test")
    with TestClient(create_cloud_app(settings, auth_service=NoSession())) as client:
        notice = client.get("/api/privacy/notice")
        assert notice.status_code == 200
        body = notice.json()
        assert body["notice_version"] == NOTICE_VERSION
        assert body["draft"] is True
        assert "敏感个人信息" in body["text"]
        assert "撤回" in body["text"]
        assert "中国大陆" in body["text"]
        assert client.get("/api/privacy/consent").status_code == 401
        assert client.post("/api/privacy/consent", json={
            "notice_version": NOTICE_VERSION, "confirmed": True,
        }, headers={"Origin": "https://app.example.cn"}).status_code == 401
