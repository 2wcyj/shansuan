import io
import json
from collections import namedtuple
import pytest
from PIL import Image
from app.backend.storage.database import Store
from app.backend.storage.photos import Photos
from app.backend.storage.backups import Backups
from app.backend.storage.crypto import open_backup,seal_backup
from app.backend.errors import AppError


def populate(s):
    for kind in ['profile','record','life','feedback','plan','chat']:
        s.put(kind,'one',{'private':'backup-secret-marker'},day='2026-10-17')
    out = io.BytesIO(); Image.new('RGB',(20,30),'blue').save(out,format='PNG')
    return Photos(s).add(out.getvalue())


def test_portable_and_local_roundtrip_all_entities_and_photo(tmp_path):
    s = Store(tmp_path/'origin'); b = Backups(s); photo = populate(s)
    blob = b.portable('a-long-password','a-long-password')
    assert b'backup-secret-marker' not in blob
    s.put('record','extra',{'different':True})
    t = b.stage(blob,'a-long-password')
    assert s.get('record','extra')
    with pytest.raises(AppError): b.commit(t['ticket'],'no')
    b.commit(t['ticket'],'整体替换')
    assert s.get('record','extra') is None
    assert Photos(s).read(photo['id'])
    assert len(list(b.directory.glob('pre-restore*'))) == 1
    other = Store(tmp_path/'clean'); other_b = Backups(other)
    result = other_b.stage(blob,'a-long-password')
    other_b.commit(result['ticket'],'整体替换')
    for kind in ['profile','record','life','feedback','plan','chat']:
        assert other.require(kind,'one')['private'] == 'backup-secret-marker'
    assert Photos(other).read(photo['id']) == Photos(s).read(photo['id'])
    local = b.local()
    assert json.loads(b.open_local(local.read_bytes()))['schema'] == 1
    s.close(); other.close()


def test_reject_password_tamper_version_paths_and_space(tmp_path,monkeypatch):
    s = Store(tmp_path); b = Backups(s); populate(s)
    with pytest.raises(AppError,match='密码'):b.portable('short','short')
    blob = b.portable('a-long-password','a-long-password'); original = s.generation
    for bad,password in [(blob,'wrong-password'),(blob[:-4]+b'fail','a-long-password')]:
        with pytest.raises(AppError): b.stage(bad,password)
    payload = json.loads(open_backup('a-long-password',blob))
    payload['schema'] = 999
    with pytest.raises(AppError): b.stage(seal_backup('a-long-password',json.dumps(payload).encode()),'a-long-password')
    payload['schema'] = 1; payload['photos']['../evil'] = 'AAAA'
    with pytest.raises(AppError): b.stage(seal_backup('a-long-password',json.dumps(payload).encode()),'a-long-password')
    monkeypatch.setattr('app.backend.storage.backups.shutil.disk_usage',lambda _:namedtuple('Usage','total used free')(100,99,1))
    with pytest.raises(AppError,match='空间不足'): b.stage(blob,'a-long-password')
    assert s.generation == original and s.require('profile','one')
    s.close()


def test_restore_commit_fault_and_restart_preserve_complete_state(tmp_path,monkeypatch):
    import app.backend.storage.backups as module
    s = Store(tmp_path); b = Backups(s); populate(s)
    blob = b.portable('a-long-password','a-long-password')
    s.put('record','new',{'value':'keep'})
    staged = b.stage(blob,'a-long-password')
    real = module.atomic_file
    def fail_once(path,data):
        if path.name == 'active.json':
            monkeypatch.setattr(module,'atomic_file',real)
            raise OSError('disk fault')
        real(path,data)
    monkeypatch.setattr(module,'atomic_file',fail_once)
    with pytest.raises(OSError): b.commit(staged['ticket'],'整体替换')
    assert s.require('record','new')['value']=='keep'
    s.close(); reopened=Store(tmp_path)
    assert reopened.require('record','new')['value']=='keep'
    reopened.close()


def test_snapshot_failure_blocks_restore_and_delete_scope(tmp_path,monkeypatch):
    s=Store(tmp_path); b=Backups(s); populate(s)
    blob=b.portable('a-long-password','a-long-password'); t=b.stage(blob,'a-long-password')
    original=s.generation
    with monkeypatch.context() as m:
        m.setattr(b,'local',lambda *a:(_ for _ in ()).throw(OSError('full')))
        with pytest.raises(OSError): b.commit(t['ticket'],'整体替换')
    assert s.generation==original
    assert 'backup-secret-marker' in b.export('json').decode()
    s.put('=formula','one',{'a':True})
    assert "'=formula" in b.export('csv').decode('utf-8-sig')
    with pytest.raises(AppError): b.erase('yes',True)
    external=tmp_path/'external-backup.mnab'; external.write_bytes(blob)
    b.erase('删除全部个人数据',True)
    assert not s.list('profile') and not b.listing() and external.exists()
    assert len(list((tmp_path/'generations').iterdir()))==1
    s.close()
