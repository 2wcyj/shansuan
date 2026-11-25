"""One-time operator command for creating the initial cloud administrator."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import secrets
from uuid import uuid4

import asyncpg

from app.backend.cloud.auth import hash_password, normalize_email


async def create_admin_account(database_url: str, email: str, password: str):
    """Create the sole initial admin using the isolated migration login."""
    normalized = normalize_email(email)
    password_hash = await asyncio.to_thread(hash_password, password)
    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    connection = await asyncpg.connect(dsn)
    try:
        role = await connection.fetchrow(
            "SELECT current_user, r.rolsuper, r.rolcreaterole, r.rolbypassrls "
            "FROM pg_roles AS r WHERE r.rolname=current_user"
        )
        if (role is None or role["current_user"] != "shansuan_migrator"
                or role["rolsuper"] or not role["rolcreaterole"] or role["rolbypassrls"]):
            raise ValueError("Bootstrap requires the dedicated non-superuser migration account")
        if await connection.fetchval("SELECT count(*) FROM accounts WHERE is_admin"):
            raise ValueError("An administrator already exists; bootstrap is disabled")
        account_id = uuid4()
        try:
            await connection.execute(
                "INSERT INTO accounts(id,email,password_hash,status,is_admin,created_at) "
                "VALUES($1,$2,$3,'active',true,now())",
                account_id, normalized, password_hash,
            )
        except asyncpg.UniqueViolationError:
            raise ValueError("The initial administrator account could not be created") from None
        return account_id
    finally:
        await connection.close()


async def _run_cli() -> int:
    parser = argparse.ArgumentParser(prog="shansuan-cloud-admin")
    parser.add_argument("command", choices=("bootstrap-admin",))
    parser.parse_args()
    database_url = os.environ.get("MIGRATION_DATABASE_URL", "").strip()
    if not database_url:
        print("Set MIGRATION_DATABASE_URL for the isolated migration account in a secure shell.")
        return 2
    email = input("Initial administrator email: ").strip()
    password = getpass.getpass("Initial administrator password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if not secrets.compare_digest(password, confirmation):
        print("Passwords do not match.")
        return 2
    try:
        await create_admin_account(database_url, email, password)
    except (ValueError, asyncpg.PostgresError):
        print("Administrator bootstrap failed. Check the migration role and database state.")
        return 1
    print("Initial administrator account created. Clear MIGRATION_DATABASE_URL from this shell.")
    return 0


def main() -> int:
    return asyncio.run(_run_cli())


if __name__ == "__main__":
    raise SystemExit(main())
