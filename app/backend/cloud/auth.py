"""PostgreSQL-backed account authentication for the public cloud runtime."""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import asyncio
import base64
import hashlib
import hmac
import re
import secrets
from typing import Protocol
from uuid import UUID, uuid4

import asyncpg
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.backend.cloud.redis_store import RedisUnavailable


_PASSWORDS = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1,
                            hash_len=32, salt_len=16, type=Type.ID)
_DUMMY_PASSWORD_HASH = _PASSWORDS.hash("not-a-real-user-password-for-timing")
_EMAIL = re.compile(r"^[^\s@]{1,64}@[^\s@.]+(?:\.[^\s@.]+)+$")


class AuthError(Exception):
    """Base class for errors safe to translate into public API responses."""


class InvalidCredentials(AuthError):
    def __init__(self):
        super().__init__("邮箱或密码错误")


class LoginRateLimited(AuthError):
    def __init__(self):
        super().__init__("尝试次数过多，请稍后再试")


class InviteRejected(AuthError):
    def __init__(self):
        super().__init__("邀请码无效或已失效")


class RegistrationRejected(AuthError):
    def __init__(self):
        super().__init__("无法创建账户，请检查信息后重试")


class PermissionDenied(AuthError):
    def __init__(self):
        super().__init__("当前账户无权执行此操作")


@dataclass(frozen=True)
class IssuedSession:
    account_id: UUID
    cookie_token: str
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True)
class AuthPrincipal:
    account_id: UUID
    csrf_hash: bytes
    is_admin: bool


class Mailer(Protocol):
    async def send_password_reset(self, email: str, reset_token: str) -> None: ...


def hash_password(password: str) -> str:
    _validate_password(password)
    return _PASSWORDS.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        return _PASSWORDS.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError, TypeError):
        return False


def normalize_email(email: str) -> str:
    if not isinstance(email, str):
        raise RegistrationRejected()
    normalized = email.strip().casefold()
    if len(normalized) > 320 or not _EMAIL.fullmatch(normalized):
        raise RegistrationRejected()
    return normalized


def _validate_password(password: str) -> None:
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise RegistrationRejected()
    if len(password.encode("utf-8")) > 512:
        raise RegistrationRejected()


class AuthService:
    def __init__(self, database, *, signing_key: bytes, session_days: int = 30,
                 reset_minutes: int = 15, redis=None):
        if len(signing_key) < 32:
            raise ValueError("Session signing key must contain at least 32 bytes")
        self.database = database
        self.signing_key = signing_key
        self.session_days = session_days
        self.reset_minutes = reset_minutes
        self.redis = redis

    @asynccontextmanager
    async def _connection(self):
        if isinstance(self.database, str):
            database_url = self.database.replace("postgresql+asyncpg://", "postgresql://", 1)
            connection = await asyncpg.connect(database_url)
            try:
                yield connection
            finally:
                await connection.close()
        else:
            async with self.database.acquire() as connection:
                yield connection

    async def _set_account(self, connection, account_id: UUID) -> None:
        await connection.execute("SELECT set_config('app.account_id',$1,true)", str(account_id))

    def _token(self, purpose: str, account_id: UUID) -> str:
        nonce = secrets.token_urlsafe(32)
        message = f"{purpose}.v1.{account_id}.{nonce}".encode("ascii")
        signature = base64.urlsafe_b64encode(
            hmac.new(self.signing_key, message, hashlib.sha256).digest()
        ).rstrip(b"=").decode("ascii")
        return f"v1.{account_id}.{nonce}.{signature}"

    def _token_account(self, purpose: str, token: str) -> UUID | None:
        if not isinstance(token, str) or len(token) > 512:
            return None
        parts = token.split(".")
        if len(parts) != 4 or parts[0] != "v1":
            return None
        try:
            account_id = UUID(parts[1])
        except (ValueError, AttributeError):
            return None
        message = f"{purpose}.v1.{account_id}.{parts[2]}".encode("ascii", errors="ignore")
        expected = base64.urlsafe_b64encode(
            hmac.new(self.signing_key, message, hashlib.sha256).digest()
        ).rstrip(b"=").decode("ascii")
        return account_id if hmac.compare_digest(expected, parts[3]) else None

    def _key_hash(self, value: str) -> bytes:
        return hmac.new(self.signing_key, value.encode("utf-8"), hashlib.sha256).digest()

    async def _within_rate_limit(self, connection, key: str, limit: int, window: int) -> bool:
        if self.redis is not None:
            try:
                return await self.redis.within_rate_limit(self._key_hash(key), limit, window)
            except RedisUnavailable:
                # Fall back to the database so a cache outage cannot unlock guessing.
                pass
        return bool(await connection.fetchval(
            "SELECT cloud_auth_rate_limit($1,$2,$3)", self._key_hash(key), limit, window
        ))

    async def create_invite(self, account_id: UUID, *, max_uses: int,
                            expires_at: datetime, remote_key: str = "unknown") -> str:
        now = datetime.now(timezone.utc)
        if not 1 <= max_uses <= 100 or expires_at.tzinfo is None or not now < expires_at <= now + timedelta(days=90):
            raise RegistrationRejected()
        token = self._token("invite", account_id)
        async with self._connection() as connection:
            account_allowed = await self._within_rate_limit(
                connection, f"invite-account:{account_id}", 10, 3600
            )
            ip_allowed = await self._within_rate_limit(connection, f"invite-ip:{remote_key}", 30, 3600)
            if not account_allowed or not ip_allowed:
                raise LoginRateLimited()
            async with connection.transaction():
                await self._set_account(connection, account_id)
                if not await connection.fetchval("SELECT cloud_account_is_admin($1)", account_id):
                    raise PermissionDenied()
                await connection.execute(
                    "INSERT INTO invites(account_id,id,token_hash,expires_at,max_uses,used_count,created_at) "
                    "VALUES($1,$2,$3,$4,$5,0,now())",
                    account_id, uuid4(), hashlib.sha256(token.encode()).digest(), expires_at, max_uses,
                )
        return token

    async def revoke_invite(self, account_id: UUID, token: str, *, remote_key: str = "unknown") -> bool:
        owner_id = self._token_account("invite", token)
        if owner_id != account_id:
            raise InviteRejected()
        async with self._connection() as connection:
            account_allowed = await self._within_rate_limit(
                connection, f"invite-revoke-account:{account_id}", 30, 3600
            )
            ip_allowed = await self._within_rate_limit(connection, f"invite-revoke-ip:{remote_key}", 60, 3600)
            if not account_allowed or not ip_allowed:
                raise LoginRateLimited()
            async with connection.transaction():
                await self._set_account(connection, account_id)
                if not await connection.fetchval("SELECT cloud_account_is_admin($1)", account_id):
                    raise PermissionDenied()
                result = await connection.execute(
                    "UPDATE invites SET revoked_at=now() "
                    "WHERE account_id=$1 AND token_hash=$2 AND revoked_at IS NULL",
                    account_id, hashlib.sha256(token.encode()).digest(),
                )
                return result == "UPDATE 1"

    async def register(self, email: str, password: str, invite_token: str,
                       *, remote_key: str = "unknown") -> IssuedSession:
        normalized = normalize_email(email)
        _validate_password(password)
        owner_id = self._token_account("invite", invite_token)
        if owner_id is None:
            raise InviteRejected()
        password_hash = await asyncio.to_thread(_PASSWORDS.hash, password)
        account_id = uuid4()
        async with self._connection() as connection:
            if not await self._within_rate_limit(connection, f"register-ip:{remote_key}", 30, 3600):
                raise LoginRateLimited()
            try:
                async with connection.transaction():
                    await self._set_account(connection, owner_id)
                    await connection.fetchval(
                        "SELECT cloud_register_account($1,$2,$3,$4,$5)", account_id, normalized,
                        password_hash, owner_id, hashlib.sha256(invite_token.encode()).digest(),
                    )
                    return await self._create_session(connection, account_id)
            except (asyncpg.InvalidParameterValueError, asyncpg.ForeignKeyViolationError):
                raise InviteRejected() from None
            except asyncpg.UniqueViolationError:
                raise RegistrationRejected() from None

    async def login(self, email: str, password: str, *, remote_key: str = "unknown") -> IssuedSession:
        normalized = normalize_email(email)
        async with self._connection() as connection:
            allowed_ip = await self._within_rate_limit(connection, f"login-ip:{remote_key}", 30, 900)
            allowed_email = await self._within_rate_limit(
                connection, f"login-email:{normalized}", 8, 900
            )
            if not allowed_ip or not allowed_email:
                raise LoginRateLimited()
            account = await connection.fetchrow("SELECT * FROM cloud_login_lookup($1)", normalized)
            stored_hash = account["password_hash"] if account else _DUMMY_PASSWORD_HASH
            password_ok = await asyncio.to_thread(verify_password, password, stored_hash)
            if not account or not password_ok or account["status"] != "active":
                raise InvalidCredentials()
            async with connection.transaction():
                await self._set_account(connection, account['id'])
                current = await connection.fetchrow(
                    'SELECT * FROM cloud_lock_account_credentials($1)', account['id'])
                if (not current or current['status'] != 'active'
                        or not hmac.compare_digest(current['password_hash'], stored_hash)):
                    raise InvalidCredentials()
                return await self._create_session(connection, account["id"])

    async def _create_session(self, connection, account_id: UUID) -> IssuedSession:
        token = self._token("session", account_id)
        csrf_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(days=self.session_days)
        token_hash = hashlib.sha256(token.encode()).digest()
        csrf_hash = hashlib.sha256(csrf_token.encode()).digest()
        await self._set_account(connection, account_id)
        await connection.execute(
            "INSERT INTO sessions(account_id,id,token_hash,csrf_hash,expires_at,created_at) "
            "VALUES($1,$2,$3,$4,$5,now())",
            account_id, uuid4(), token_hash, csrf_hash, expires_at,
        )
        if self.redis is not None:
            try:
                await self.redis.save_session(account_id, token_hash, csrf_hash, expires_at)
            except RedisUnavailable:
                # The database row already exists; the reader will fall back to it.
                pass
        return IssuedSession(account_id, token, csrf_token, expires_at)

    async def authenticate(self, cookie_token: str | None) -> AuthPrincipal | None:
        account_id = self._token_account("session", cookie_token or "")
        if account_id is None:
            return None
        token_hash = hashlib.sha256(cookie_token.encode()).digest()
        csrf_hash = None
        if self.redis is not None:
            try:
                record = await self.redis.load_session(account_id, token_hash)
            except RedisUnavailable:
                record = None
            if record is not None:
                csrf_hash = record.csrf_hash
        async with self._connection() as connection:
            async with connection.transaction():
                await self._set_account(connection, account_id)
                if csrf_hash is None:
                    # Sessions created before Redis was enabled, or a cache miss.
                    session = await connection.fetchrow(
                        "SELECT csrf_hash FROM sessions WHERE account_id=$1 AND token_hash=$2 "
                        "AND revoked_at IS NULL AND expires_at>now()",
                        account_id, token_hash,
                    )
                    if not session:
                        return None
                    csrf_hash = bytes(session["csrf_hash"])
                account = await connection.fetchrow("SELECT * FROM cloud_account_status($1)", account_id)
                if not account or account["status"] != "active":
                    return None
                return AuthPrincipal(account_id, csrf_hash, account["is_admin"])

    async def rotate_csrf(self, cookie_token: str | None) -> tuple[AuthPrincipal, str] | None:
        account_id = self._token_account("session", cookie_token or "")
        if account_id is None:
            return None
        token_hash = hashlib.sha256(cookie_token.encode()).digest()
        csrf_token = secrets.token_urlsafe(32)
        csrf_hash = hashlib.sha256(csrf_token.encode()).digest()
        async with self._connection() as connection:
            async with connection.transaction():
                await self._set_account(connection, account_id)
                updated = await connection.fetchrow(
                    "UPDATE sessions SET csrf_hash=$3 WHERE account_id=$1 AND token_hash=$2 "
                    "AND revoked_at IS NULL AND expires_at>now() RETURNING csrf_hash",
                    account_id, token_hash, csrf_hash,
                )
                if not updated:
                    return None
                account = await connection.fetchrow("SELECT * FROM cloud_account_status($1)", account_id)
                if not account or account["status"] != "active":
                    return None
                principal = AuthPrincipal(account_id, bytes(updated["csrf_hash"]), account["is_admin"])
        if self.redis is not None:
            try:
                await self.redis.update_csrf(account_id, token_hash, csrf_hash)
            except RedisUnavailable:
                pass
        return principal, csrf_token

    @staticmethod
    def verify_csrf(principal: AuthPrincipal, supplied: str | None) -> bool:
        if not supplied or len(supplied) > 256:
            return False
        candidate = hashlib.sha256(supplied.encode()).digest()
        return hmac.compare_digest(candidate, principal.csrf_hash)

    async def logout(self, cookie_token: str | None) -> bool:
        account_id = self._token_account("session", cookie_token or "")
        if account_id is None:
            return False
        token_hash = hashlib.sha256(cookie_token.encode()).digest()
        async with self._connection() as connection:
            async with connection.transaction():
                await self._set_account(connection, account_id)
                result = await connection.execute(
                    "UPDATE sessions SET revoked_at=now() WHERE account_id=$1 "
                    "AND token_hash=$2 AND revoked_at IS NULL",
                    account_id, token_hash,
                )
                revoked = result == "UPDATE 1"
        if revoked and self.redis is not None:
            try:
                await self.redis.delete_session(account_id, token_hash)
            except RedisUnavailable:
                pass
        return revoked

    async def change_password(self, account_id: UUID, current_password: str,
                              new_password: str) -> bool:
        _validate_password(new_password)
        new_hash = await asyncio.to_thread(_PASSWORDS.hash, new_password)
        async with self._connection() as connection:
            async with connection.transaction():
                await self._set_account(connection, account_id)
                account = await connection.fetchrow("SELECT * FROM cloud_lock_account_credentials($1)", account_id)
                if not account or not await asyncio.to_thread(verify_password, current_password, account["password_hash"]):
                    return False
                updated = bool(await connection.fetchval(
                    "SELECT cloud_update_password($1,$2)", account_id, new_hash
                ))
        if updated and self.redis is not None:
            # cloud_update_password revokes the PostgreSQL rows; drop the cache too.
            try:
                await self.redis.delete_account_sessions(account_id)
            except RedisUnavailable:
                pass
        return updated

    async def verify_account_password(self, account_id: UUID, password: str) -> tuple[bool, str | None]:
        """Re-authenticate one active account without returning credential material."""
        if not isinstance(password, str) or not 1 <= len(password) <= 128:
            return False, None
        async with self._connection() as connection:
            if not await self._within_rate_limit(connection, f'privacy-reauth:{account_id}', 12, 900):
                raise LoginRateLimited()
            async with connection.transaction():
                await self._set_account(connection, account_id)
                account = await connection.fetchrow(
                    "SELECT * FROM cloud_account_credentials($1)", account_id
                )
        if not account or account['status'] != 'active':
            return False, None
        valid = await asyncio.to_thread(verify_password, password, account['password_hash'])
        return valid, account['email'] if valid else None

    @asynccontextmanager
    async def privacy_transaction(self, principal: AuthPrincipal, password: str,
                                  cookie_token: str | None):
        """Keep account, session and domain data locked through the entire rights operation."""
        account_id = principal.account_id
        # Commit throttling independently so failed reauthentication cannot roll it back.
        async with self._connection() as limiter:
            if not await self._within_rate_limit(limiter, f'privacy-reauth:{account_id}', 12, 900):
                raise LoginRateLimited()
        async with self._connection() as connection:
            async with connection.transaction():
                await self._set_account(connection, account_id)
                await connection.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',
                                         'domain:' + str(account_id))
                account = await connection.fetchrow(
                    'SELECT * FROM cloud_lock_account_credentials($1)', account_id)
                if not account or account['status'] != 'active':
                    raise PermissionDenied()
                session = await connection.fetchrow(
                    'SELECT csrf_hash,expires_at FROM sessions WHERE account_id=$1 AND token_hash=$2 '
                    'AND revoked_at IS NULL FOR UPDATE',
                    account_id, hashlib.sha256((cookie_token or '').encode()).digest())
                if not session or not hmac.compare_digest(bytes(session['csrf_hash']), principal.csrf_hash):
                    raise PermissionDenied()
                if not await asyncio.to_thread(verify_password, password, account['password_hash']):
                    raise PermissionDenied()
                # PostgreSQL now() is fixed at transaction start, before potentially long waits.
                if not await connection.fetchval('SELECT $1::timestamptz > clock_timestamp()', session['expires_at']):
                    raise PermissionDenied()
                yield connection, account['email']

    async def request_password_reset(self, email: str, *, remote_key: str = "unknown",
                                     mailer: Mailer | None = None) -> bool:
        normalized = normalize_email(email)
        async with self._connection() as connection:
            async with connection.transaction():
                allowed_ip = await self._within_rate_limit(connection, f"reset-ip:{remote_key}", 20, 900)
                allowed_email = await self._within_rate_limit(
                    connection, f"reset-email:{normalized}", 4, 3600
                )
                if not allowed_ip or not allowed_email:
                    return False
                account = await connection.fetchrow("SELECT * FROM cloud_login_lookup($1)", normalized)
                if not account or account["status"] != "active" or mailer is None:
                    return False
                account_id = account["id"]
                token = self._token("password-reset", account_id)
                await self._set_account(connection, account_id)
                await connection.execute(
                    "INSERT INTO password_resets(account_id,id,token_hash,expires_at,created_at) "
                    "VALUES($1,$2,$3,$4,now())",
                    account_id, uuid4(), hashlib.sha256(token.encode()).digest(),
                    datetime.now(timezone.utc) + timedelta(minutes=self.reset_minutes),
                )
            await mailer.send_password_reset(normalized, token)
            return True

    async def complete_password_reset(self, token: str, new_password: str) -> bool:
        _validate_password(new_password)
        account_id = self._token_account("password-reset", token)
        if account_id is None:
            return False
        password_hash = await asyncio.to_thread(_PASSWORDS.hash, new_password)
        async with self._connection() as connection:
            async with connection.transaction():
                await self._set_account(connection, account_id)
                # Lock accounts before reset tokens/sessions, matching privacy deletion lock order.
                account = await connection.fetchrow(
                    'SELECT * FROM cloud_lock_account_credentials($1)', account_id)
                if not account or account['status'] != 'active':
                    return False
                token_hash = hashlib.sha256(token.encode()).digest()
                reset = await connection.fetchrow(
                    "SELECT id,expires_at FROM password_resets WHERE account_id=$1 AND token_hash=$2 "
                    "AND used_at IS NULL FOR UPDATE",
                    account_id, token_hash,
                )
                if not reset:
                    return False
                if not await connection.fetchval('SELECT $1::timestamptz > clock_timestamp()', reset['expires_at']):
                    return False
                await connection.execute(
                    "UPDATE password_resets SET used_at=now() WHERE account_id=$1 AND id=$2",
                    account_id, reset["id"],
                )
                updated = bool(await connection.fetchval(
                    "SELECT cloud_update_password($1,$2)", account_id, password_hash
                ))
        if updated and self.redis is not None:
            try:
                await self.redis.delete_account_sessions(account_id)
            except RedisUnavailable:
                pass
        return updated
