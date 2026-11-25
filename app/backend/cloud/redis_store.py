"""Huawei Cloud DCS for Redis session and rate-limit storage.

The PostgreSQL tables remain the durable record used by transactional privacy
operations; Redis is the shared fast path so several instances see the same
session and throttling state.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os


class RedisUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('Cloud cache service unavailable')


@dataclass(frozen=True)
class SessionRecord:
    csrf_hash: bytes
    expires_at: datetime


class RedisAuthStore:
    def __init__(self, client, *, prefix: str = 'shansuan'):
        self._client = client
        self.prefix = prefix

    @staticmethod
    def _token_hex(token_hash: bytes) -> str:
        return bytes(token_hash).hex()

    def _session_key(self, account_id, token_hash: bytes) -> str:
        return f'{self.prefix}:sess:{account_id}:{self._token_hex(token_hash)}'

    def _index_key(self, account_id) -> str:
        return f'{self.prefix}:acct:{account_id}:sessions'

    def _rate_key(self, key_hash: bytes) -> str:
        return f'{self.prefix}:rl:{bytes(key_hash).hex()}'

    async def ping(self) -> bool:
        try:
            return bool(await self._client.ping())
        except Exception:
            raise RedisUnavailable() from None

    async def save_session(self, account_id, token_hash: bytes, csrf_hash: bytes,
                           expires_at: datetime) -> None:
        if expires_at.tzinfo is None:
            raise ValueError('Session expiry must be timezone aware')
        key = self._session_key(account_id, token_hash)
        epoch = int(expires_at.timestamp())
        try:
            async with self._client.pipeline(transaction=True) as pipe:
                pipe.hset(key, mapping={
                    'csrf': bytes(csrf_hash).hex(),
                    'exp': int(expires_at.timestamp()),
                })
                pipe.expireat(key, epoch)
                pipe.sadd(self._index_key(account_id), self._token_hex(token_hash))
                await pipe.execute()
        except Exception:
            raise RedisUnavailable() from None

    async def load_session(self, account_id, token_hash: bytes) -> SessionRecord | None:
        try:
            values = await self._client.hgetall(self._session_key(account_id, token_hash))
        except Exception:
            raise RedisUnavailable() from None
        if not values:
            return None
        try:
            csrf = bytes.fromhex(values[b'csrf'].decode('ascii'))
            expires_at = datetime.fromtimestamp(int(values[b'exp']), tz=timezone.utc)
        except (KeyError, ValueError):
            return None
        if expires_at <= datetime.now(timezone.utc):
            return None
        return SessionRecord(csrf, expires_at)

    async def update_csrf(self, account_id, token_hash: bytes, csrf_hash: bytes) -> bool:
        try:
            updated = await self._client.hset(
                self._session_key(account_id, token_hash), 'csrf', bytes(csrf_hash).hex())
        except Exception:
            raise RedisUnavailable() from None
        return bool(updated)

    async def delete_session(self, account_id, token_hash: bytes) -> bool:
        try:
            async with self._client.pipeline(transaction=True) as pipe:
                pipe.delete(self._session_key(account_id, token_hash))
                pipe.srem(self._index_key(account_id), self._token_hex(token_hash))
                removed, _ = await pipe.execute()
        except Exception:
            raise RedisUnavailable() from None
        return bool(removed)

    async def delete_account_sessions(self, account_id) -> int:
        index = self._index_key(account_id)
        try:
            members = await self._client.smembers(index)
            if not members:
                return 0
            keys = [f'{self.prefix}:sess:{account_id}:{member.decode("ascii")}'
                    if isinstance(member, bytes) else
                    f'{self.prefix}:sess:{account_id}:{member}' for member in members]
            async with self._client.pipeline(transaction=True) as pipe:
                for key in keys:
                    pipe.delete(key)
                pipe.delete(index)
                results = await pipe.execute()
        except Exception:
            raise RedisUnavailable() from None
        return len(keys)

    async def within_rate_limit(self, key_hash: bytes, limit: int, window: int) -> bool:
        if limit < 1 or window < 1:
            raise ValueError('Rate limit and window must be positive')
        key = self._rate_key(key_hash)
        try:
            current = await self._client.incr(key)
            if current == 1:
                await self._client.expire(key, window)
            return int(current) <= limit
        except Exception:
            raise RedisUnavailable() from None


def redis_store_from_env(environ=None):
    values = os.environ if environ is None else environ
    url = (values.get('REDIS_URL') or values.get('DCS_REDIS_URL') or '').strip()
    if not url:
        return None
    if not url.startswith(('redis://', 'rediss://')):
        raise ValueError('REDIS_URL must use redis:// or rediss://')
    try:
        from redis.asyncio import Redis
    except ImportError:
        raise ValueError('The redis package is required when REDIS_URL is configured') from None
    client = Redis.from_url(
        url,
        decode_responses=False,
        socket_timeout=3,
        socket_connect_timeout=3,
        health_check_interval=30,
    )
    return RedisAuthStore(client)