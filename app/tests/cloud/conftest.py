"""Disposable PostgreSQL fixture used by cloud isolation integration tests."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time
import uuid

import asyncpg
from alembic import command
from alembic.config import Config
import pytest


ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = ROOT / "app" / "backend" / "cloud" / "alembic.ini"
DOCKER = (os.environ.get("DOCKER_CLI") or shutil.which("docker") or
          r"C:\Program Files\Docker\Docker\resources\bin\docker.exe")


def _docker(*args: str) -> str:
    completed = subprocess.run(
        [DOCKER, *args], check=True, capture_output=True, text=True, timeout=120
    )
    return completed.stdout.strip()


@pytest.fixture(scope="session")
def postgres_database():
    name = f"shansuan-pg-test-{uuid.uuid4().hex[:12]}"
    password = secrets.token_urlsafe(24)
    container_id = _docker(
        "run", "--detach", "--rm", "--publish", "127.0.0.1::5432",
        "--name", name, "--env", "POSTGRES_USER=postgres", "--env",
        f"POSTGRES_PASSWORD={password}", "--env", "POSTGRES_DB=shansuan_test",
        "postgres:16-alpine",
    )
    try:
        port_output = _docker("port", container_id, "5432/tcp")
        port = int(port_output.rsplit(":", 1)[1])
        runtime_password = secrets.token_hex(24)
        migration_password = secrets.token_hex(24)
        asyncio.run(_prepare_postgres(port, password, migration_password, runtime_password))
        database_url = f"postgresql+asyncpg://shansuan_migrator:{migration_password}@127.0.0.1:{port}/shansuan_test"
        runtime_url = f"postgresql://shansuan_runtime:{runtime_password}@127.0.0.1:{port}/shansuan_test"
        config = Config(str(ALEMBIC_INI))
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
        command.upgrade(config, "head")
        asyncio.run(_grant_runtime_role(port, password))
        yield {"host": "127.0.0.1", "port": port, "database": "shansuan_test",
               "admin_password": password, "migration_url": database_url,
               "runtime_url": runtime_url}
    finally:
        subprocess.run([DOCKER, "rm", "--force", container_id], capture_output=True,
                       text=True, timeout=30)


async def _prepare_postgres(port: int, password: str, migration_password: str,
                           runtime_password: str) -> None:
    deadline = time.monotonic() + 45
    while True:
        try:
            connection = await asyncpg.connect(
                host="127.0.0.1", port=port, user="postgres", password=password,
                database="shansuan_test",
            )
            break
        except (OSError, asyncpg.PostgresError):
            if time.monotonic() >= deadline:
                raise
            await asyncio.sleep(0.25)
    try:
        await connection.execute(
            "CREATE ROLE shansuan_migrator LOGIN NOSUPERUSER NOCREATEDB CREATEROLE "
            f"NOINHERIT NOBYPASSRLS PASSWORD '{migration_password}'"
        )
        await connection.execute(
            "CREATE ROLE shansuan_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
            f"NOBYPASSRLS PASSWORD '{runtime_password}'"
        )
        await connection.execute("GRANT CREATE, USAGE ON SCHEMA public TO shansuan_migrator")
    finally:
        await connection.close()


async def _grant_runtime_role(port: int, admin_password: str) -> None:
    connection = await asyncpg.connect(
        host="127.0.0.1", port=port, user="postgres", password=admin_password,
        database="shansuan_test",
    )
    try:
        await connection.execute("GRANT shansuan_app TO shansuan_runtime")
    finally:
        await connection.close()


@pytest.fixture
def run_async():
    def run(coroutine):
        return asyncio.run(coroutine)
    return run
