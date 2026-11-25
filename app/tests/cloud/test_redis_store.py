"""DCS Redis store behaviour with an in-memory client: keys, TTL and limits."""
import asyncio
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest


class FakePipeline:
    def __init__(self, store):
        self.store = store
        self.operations = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def hset(self, key, mapping=None, field=None, value=None):
        self.operations.append(('hset', key, mapping, field, value))

    def expireat(self, key, when):
        self.operations.append(('expireat', key, when))

    def sadd(self, key, member):
        self.operations.append(('sadd', key, member))

    def srem(self, key, member):
        self.operations.append(('srem', key, member))

    def delete(self, key):
        self.operations.append(('delete', key))

    async def execute(self):
        results = [self.store.apply(operation) for operation in self.operations]
        self.operations.clear()
        return results


class FakeRedis:
    def __init__(self):
        self.hashes = {}
        self.sets = {}
        self.expiry = {}
        self.counters = {}

    def pipeline(self, transaction=True):
        return FakePipeline(self)

    def apply(self, operation):
        name, key, *rest = operation
        if name == 'hset':
            mapping, field, value = rest
            self.hashes.setdefault(key, {})
            if mapping:
                self.hashes[key].update(mapping)
            elif field is not None:
                self.hashes[key][field] = value
            return 1
        if name == 'expireat':
            self.expiry[key] = rest[0]
            return True
        if name == 'sadd':
            self.sets.setdefault(key, set()).add(rest[0])
            return 1
        if name == 'srem':
            self.sets.get(key, set()).discard(rest[0])
            return 1
        if name == 'delete':
            existed = key in self.hashes or key in self.sets
            self.hashes.pop(key, None)
            self.sets.pop(key, None)
            return int(existed)
        raise AssertionError(f'unexpected operation {name}')

    async def ping(self):
        return True

    async def hset(self, key, field=None, value=None, mapping=None):
        return self.apply(('hset', key, mapping, field, value))

    async def hgetall(self, key):
        return {name.encode(): str(value).encode()
                for name, value in self.hashes.get(key, {}).items()}

    async def sadd(self, key, member):
        return self.apply(('sadd', key, member))

    async def srem(self, key, member):
        return self.apply(('srem', key, member))

    async def delete(self, key):
        return self.apply(('delete', key))

    async def smembers(self, key):
        return {member.encode() for member in self.sets.get(key, set())}

    async def incr(self, key):
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key, seconds):
        self.expiry[key] = time.monotonic() + seconds
        return True


@pytest.fixture
def client():
    return FakeRedis()


def future(minutes=30):
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def test_session_round_trip_and_csrf_rotation(client):
    from app.backend.cloud.redis_store import RedisAuthStore

    store = RedisAuthStore(client)
    account = uuid4()
    token_hash, csrf_hash = b't' * 32, b'c' * 32
    asyncio.run(store.save_session(account, token_hash, csrf_hash, future()))
    record = asyncio.run(store.load_session(account, token_hash))
    assert record.csrf_hash == csrf_hash
    assert record.expires_at > datetime.now(timezone.utc)

    replaced = b'r' * 32
    assert asyncio.run(store.update_csrf(account, token_hash, replaced))
    assert asyncio.run(store.load_session(account, token_hash)).csrf_hash == replaced
    assert asyncio.run(store.delete_session(account, token_hash))
    assert asyncio.run(store.load_session(account, token_hash)) is None


def test_expired_session_is_not_returned(client):
    from app.backend.cloud.redis_store import RedisAuthStore

    store = RedisAuthStore(client)
    account, token_hash = uuid4(), b't' * 32
    asyncio.run(store.save_session(account, token_hash, b'c' * 32,
                                   datetime.now(timezone.utc) - timedelta(seconds=1)))
    assert asyncio.run(store.load_session(account, token_hash)) is None


def test_password_change_removes_every_account_session(client):
    from app.backend.cloud.redis_store import RedisAuthStore

    store = RedisAuthStore(client)
    account = uuid4()
    first, second = b'a' * 32, b'b' * 32
    asyncio.run(store.save_session(account, first, b'c' * 32, future()))
    asyncio.run(store.save_session(account, second, b'c' * 32, future()))
    assert asyncio.run(store.delete_account_sessions(account)) == 2
    assert asyncio.run(store.load_session(account, first)) is None
    assert asyncio.run(store.load_session(account, second)) is None


def test_rate_limit_counts_within_the_window(client):
    from app.backend.cloud.redis_store import RedisAuthStore

    store = RedisAuthStore(client)
    key_hash = b'k' * 32
    results = [asyncio.run(store.within_rate_limit(key_hash, 3, 900)) for _ in range(4)]
    assert results == [True, True, True, False]
    client.counters.clear()
    assert asyncio.run(store.within_rate_limit(key_hash, 3, 900))


def test_rate_limit_rejects_invalid_configuration(client):
    from app.backend.cloud.redis_store import RedisAuthStore

    store = RedisAuthStore(client)
    with pytest.raises(ValueError):
        asyncio.run(store.within_rate_limit(b'k' * 32, 0, 900))


def test_redis_url_must_be_explicit_and_use_a_redis_scheme():
    from app.backend.cloud.redis_store import redis_store_from_env

    assert redis_store_from_env({}) is None
    with pytest.raises(ValueError):
        redis_store_from_env({'REDIS_URL': 'https://cache.example'})
    with pytest.raises(ValueError):
        redis_store_from_env({'DCS_REDIS_URL': 'cache.example:6379'})