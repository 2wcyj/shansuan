"""Request-local, in-memory adapter for the existing synchronous domain rules.

No local Store, SQLCipher database or Windows data directory is opened here.
The outer repository transaction serializes one account and persists encrypted changes.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from uuid import UUID, NAMESPACE_URL, uuid5

from app.backend.cloud.context import current_tenant_id, tenant_context
from app.backend.errors import AppError, conflict


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def physical_id(account_id, kind, logical_id):
    if kind == 'profile' and logical_id == 'self':
        return uuid5(NAMESPACE_URL, f'shansuan:profile:{account_id}')
    if kind == 'draft' and logical_id == 'onboarding':
        return uuid5(NAMESPACE_URL, f'shansuan:profile-draft:{account_id}')
    if kind == 'measurement':
        day, metric = logical_id.rsplit('-', 1)
        return uuid5(NAMESPACE_URL, f'shansuan:measurement:{account_id}:{day}:{metric}')
    return uuid5(NAMESPACE_URL, f'shansuan:domain:{account_id}:{kind}:{logical_id}')


class DomainStore:
    def __init__(self, rows):
        self.values = {}
        self.persisted = {}
        self.deleted_versions = {}
        self.operations = []
        for row in rows:
            body = deepcopy(row['body'])
            if body.get('_domain_format') == 1:
                value = body['value']
                logical_id = value['id']
            else:
                # Compatibility with the first cloud profile implementation.
                kind = row['kind']
                logical_id = ('self' if kind == 'profile' else 'onboarding' if kind == 'draft'
                              else f"{body.get('day')}-{body.get('metric')}" if kind == 'measurement'
                              else row['id'])
                value = {**body, 'id': logical_id, 'version': row['revision'],
                         'day': body.get('day'), 'created_at': '', 'updated_at': ''}
            identity = (row['kind'], logical_id)
            if body.get('_domain_format') == 1 and body.get('_deleted') is True:
                self.deleted_versions[identity] = value['version']
            else:
                self.values[identity] = value
            self.persisted[identity] = (UUID(row['id']), row['revision'])

    @contextmanager
    def atomic(self):
        prior, position = deepcopy(self.values), len(self.operations)
        versions = dict(self.deleted_versions)
        try:
            yield
        except BaseException:
            self.values = prior
            self.deleted_versions = versions
            del self.operations[position:]
            raise

    def get(self, kind, id):
        return deepcopy(self.values.get((kind, id)))

    def require(self, kind, id):
        value = self.get(kind, id)
        if value is None:
            raise AppError('这项内容不存在或已删除', 'not_found', 404)
        return value

    def list(self, kind, day=None):
        return sorted([deepcopy(value) for (key, _), value in self.values.items()
                       if key == kind and (day is None or value.get('day') == day)],
                      key=lambda value: (value.get('created_at', ''), value['id']))

    def put(self, kind, id, body, day=None, version=0):
        old = self.get(kind, id)
        if (old['version'] if old else 0) != version:
            raise conflict()
        data = {key: value for key, value in body.items()
                if key not in {'id', 'version', 'day', 'created_at', 'updated_at', 'request_key'}}
        timestamp = datetime.now().astimezone().isoformat()
        next_version = old['version'] + 1 if old else self.deleted_versions.get((kind, id), 0) + 1
        value = {**deepcopy(data), 'id': id, 'day': day, 'version': next_version,
                 'created_at': old['created_at'] if old else timestamp, 'updated_at': timestamp}
        self.values[(kind, id)] = value
        self.operations.append(('put', kind, id, deepcopy(value)))
        return deepcopy(value)

    def delete(self, kind, id, version):
        old = self.require(kind, id)
        if old['version'] != version:
            raise conflict()
        del self.values[(kind, id)]
        self.deleted_versions[(kind, id)] = old['version']
        self.operations.append(('delete', kind, id, old))
        if kind != 'domain_link':
            for link in self.list('domain_link'):
                if ((link['source_kind'], link['source_id']) == (kind, id)
                        or (link['target_kind'], link['target_id']) == (kind, id)):
                    self.delete('domain_link', link['id'], link['version'])
        return {'deleted': True}

    def mutate(self, key, payload, operation):
        if not isinstance(key, str) or not 8 <= len(key) <= 160:
            raise AppError('缺少有效的操作标识，请重试')
        identity = hashlib.sha256(key.encode()).hexdigest()
        digest = hashlib.sha256(encode(payload).encode()).hexdigest()
        old = self.get('mutation_request', identity)
        if old:
            if old['digest'] != digest:
                raise conflict('操作标识已被其他内容使用，请重新发起')
            return old['result']
        with self.atomic():
            result = operation()
            self.put('mutation_request', identity, {'digest': digest, 'result': result})
            return result

    def link(self, source_kind, source_id, target_kind, target_id):
        self.require(source_kind, source_id)
        self.require(target_kind, target_id)
        identity = hashlib.sha256(encode([source_kind, source_id, target_kind, target_id]).encode()).hexdigest()
        if not self.get('domain_link', identity):
            self.put('domain_link', identity, {'source_kind': source_kind, 'source_id': source_id,
                'target_kind': target_kind, 'target_id': target_id})

    async def flush(self, repository):
        account = current_tenant_id()
        for action, kind, logical_id, value in self.operations:
            identity = (kind, logical_id)
            physical, revision = self.persisted.get(identity,
                (physical_id(account, kind, logical_id), 0))
            if action == 'delete':
                stored = await repository.put(kind, {'_domain_format': 1, '_deleted': True,
                    'value': value}, entity_id=physical, expected_revision=revision)
                if stored is None:
                    raise conflict()
                self.persisted[identity] = (physical, stored['revision'])
            else:
                stored = await repository.put(kind, {'_domain_format': 1, 'value': value},
                    entity_id=physical, expected_revision=revision)
                if stored is None:
                    raise conflict()
                self.persisted[identity] = (physical, stored['revision'])


async def run_domain(repository, account_id, operation):
    with tenant_context(account_id):
        async with repository.atomic():
            # Serializes the complete read / calculate / write cycle for this account only.
            await repository.lock_account()
            store = DomainStore(await repository.list())
            result = operation(store)
            await store.flush(repository)
            return result
