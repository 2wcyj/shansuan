import io
import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from app.backend.storage.database import Store, atomic_file
from app.backend.storage.photos import Photos
from app.backend.main import create_app
from app.backend.errors import AppError


def test_reopen_version_and_rollback(tmp_path):
    s = Store(tmp_path)
    a = s.put('test','one',{'text':'private-p1-marker'})
    with pytest.raises(AppError):
        s.put('test','one',{'text':'stale'},version=0)
    with pytest.raises(RuntimeError):
        with s.atomic():
            s.put('test','two',{'text':'not-committed'})
            raise RuntimeError('fault')
    assert s.get('test','two') is None
    assert s.get('test','one') == a
    s.close()
    s = Store(tmp_path)
    assert s.require('test','one')['text'] == 'private-p1-marker'
    for path in tmp_path.rglob('*'):
        if path.is_file():
            assert b'private-p1-marker' not in path.read_bytes()
    s.close()


def test_idempotency_concurrent_and_payload_conflict(tmp_path):
    s = Store(tmp_path)
    def write(_):
        return s.mutate('one-request-key',{'same':True},lambda:s.put('test','same',{'ok':True}))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(write,range(20)))
    assert all(r == results[0] for r in results)
    assert len(s.list('test')) == 1
    with pytest.raises(AppError):
        s.mutate('one-request-key',{'different':True},lambda:{})
    s.close()


def test_corrupt_key_or_pointer_never_recreates_data(tmp_path):
    s = Store(tmp_path)
    path = s.folder / 'nutrition.db'
    s.put('test','a',{'safe':True})
    key_file = s.folder / 'key.dpapi'
    s.close()
    original = path.read_bytes()
    key_file.write_bytes(b'broken')
    with pytest.raises(Exception):
        Store(tmp_path)
    assert path.read_bytes() == original
    (tmp_path / 'active.json').unlink()
    with pytest.raises(AppError):
        Store(tmp_path)
    assert path.read_bytes() == original


def test_photo_encryption_validation_and_db_link(tmp_path):
    s = Store(tmp_path)
    photos = Photos(s)
    image = Image.new('RGB',(30,20),'green')
    out = io.BytesIO(); image.save(out,format='PNG')
    a = photos.add(out.getvalue())
    data = photos.read(a['photo_id'])
    assert Image.open(io.BytesIO(data)).format == 'JPEG'
    assert data not in (s.folder / 'photos' / (a['id']+'.enc')).read_bytes()
    assert len(s.list('analysis')) == 1
    with pytest.raises(AppError):
        photos.add(b'not an image')
    assert len(s.list('analysis')) == 1
    assert s.conn.execute('PRAGMA foreign_key_check').fetchall() == []
    s.close()


def test_local_session_origin_csrf_and_cache(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app,base_url='http://127.0.0.1:18765') as client:
        assert client.get('/api/status').status_code == 403
        assert client.get('/api/session',headers={'Origin':'https://evil.example'}).status_code == 403
        assert client.get('/api/session',headers={'Host':'evil.example'}).status_code == 403
        result = client.get('/api/session')
        assert result.headers['cache-control'] == 'no-store'
        assert client.get('/api/status').status_code == 200
        assert client.post('/api/missing').status_code == 403
        assert client.post('/api/missing',headers={'X-CSRF-Token':result.json()['csrf'],'Origin':'null'}).status_code == 403
    app.state.store.close()


def test_real_migration_snapshot_and_failure_rollback(tmp_path):
    from app.backend.storage.migrations import migrate
    from app.backend.storage.database import connect
    s = Store(tmp_path)
    s.put('private','x',{'value':'migration-private-marker'})
    with pytest.raises(Exception):
        migrate(s.conn,s.folder,2,{2:['CREATE TABLE migration_probe(id TEXT)','INVALID SQL']})
    assert s.conn.execute('PRAGMA user_version').fetchone()[0] == 1
    assert not s.conn.execute("SELECT name FROM sqlite_master WHERE name='migration_probe'").fetchall()
    snapshot = next((tmp_path / 'backups').glob('migration-*/nutrition.db'))
    assert b'migration-private-marker' not in snapshot.read_bytes()
    old = connect(snapshot,s.key)
    assert old.execute('SELECT count(*) FROM entities').fetchone()[0] == 1
    old.close()
    migrate(s.conn,s.folder,2,{2:['CREATE TABLE migration_probe(id TEXT)']})
    assert s.conn.execute('PRAGMA user_version').fetchone()[0] == 2
    assert s.require('private','x')['value'] == 'migration-private-marker'
    s.close()
