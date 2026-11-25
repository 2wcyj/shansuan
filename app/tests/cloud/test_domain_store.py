"""Compatibility checks for the request-local synchronous domain adapter."""
from uuid import uuid4
import pytest
from app.backend.cloud.domain_store import DomainStore
from app.backend.errors import AppError


def test_deleted_entity_retains_version_history_when_recreated():
    row = {'id': str(uuid4()), 'kind': 'measurement', 'revision': 5,
        'body': {'_domain_format': 1, '_deleted': True,
            'value': {'id': '2026-10-21-weight', 'day': '2026-10-21', 'version': 4,
                      'created_at': '', 'updated_at': '', 'metric': 'weight', 'value': 60}}}
    store = DomainStore([row])
    assert store.get('measurement', '2026-10-21-weight') is None
    assert store.list('measurement') == []
    result = store.put('measurement', '2026-10-21-weight', {'metric': 'weight', 'value': 61},
                       day='2026-10-21', version=0)
    assert result['version'] == 5


def test_domain_atomic_failure_restores_values_and_pending_writes():
    store = DomainStore([])
    with pytest.raises(RuntimeError):
        with store.atomic():
            store.put('record', 'test', {'time': '12:00'})
            raise RuntimeError('operation interrupted')
    assert store.get('record', 'test') is None
    assert store.operations == []
    with pytest.raises(AppError):
        store.put('record', 'test', {}, version=2)


def test_deleting_record_removes_associated_plan_link():
    store = DomainStore([])
    store.put('plan', 'today', {})
    store.put('record', 'lunch', {})
    store.link('plan', 'today', 'record', 'lunch')
    assert len(store.list('domain_link')) == 1
    store.delete('record', 'lunch', 1)
    assert store.list('domain_link') == []
    assert store.get('plan', 'today') is not None
