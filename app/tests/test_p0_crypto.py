import os
import base64
import json
import pytest
from sqlcipher3 import dbapi2 as sqlite
from app.backend.storage.crypto import dpapi, encrypt, decrypt, seal_backup, open_backup, CryptoError


def test_dpapi_account_key_and_encrypted_image():
    key = os.urandom(32)
    wrapped = dpapi(key)
    assert wrapped != key and dpapi(wrapped, True) == key
    image = b'private-photo-marker' * 80
    encrypted = encrypt(key, image)
    assert image[:20] not in encrypted
    assert decrypt(key, encrypted) == image
    with pytest.raises(CryptoError):
        decrypt(os.urandom(32), encrypted)
    damaged = encrypted[:-1] + bytes([encrypted[-1] ^ 1])
    with pytest.raises(CryptoError):
        decrypt(key, damaged)


def test_sqlcipher_real_file_reopen_and_wrong_key(tmp_path):
    path = tmp_path / 'data.db'
    key = os.urandom(32).hex()
    conn = sqlite.connect(str(path))
    conn.execute(f'PRAGMA key="x\'{key}\'"')
    assert conn.execute('PRAGMA cipher_version').fetchone()[0]
    conn.execute('CREATE TABLE secret(value TEXT)')
    conn.execute('INSERT INTO secret VALUES (?)', ('P0-private-health-marker',))
    conn.commit()
    conn.close()
    assert b'P0-private-health-marker' not in path.read_bytes()
    assert not path.read_bytes().startswith(b'SQLite format')
    conn = sqlite.connect(str(path))
    conn.execute(f'PRAGMA key="x\'{key}\'"')
    assert conn.execute('SELECT value FROM secret').fetchone()[0] == 'P0-private-health-marker'
    conn.close()
    conn = sqlite.connect(str(path))
    conn.execute('PRAGMA key="wrong"')
    with pytest.raises(sqlite.DatabaseError):
        conn.execute('SELECT * FROM secret').fetchall()
    conn.close()


def test_portable_password_independent_of_dpapi():
    payload = os.urandom(32) + b'portable-health-marker'
    backup = seal_backup('portable-password-1', payload)
    assert b'portable-health-marker' not in backup
    assert open_backup('portable-password-1', backup) == payload
    with pytest.raises(CryptoError):
        open_backup('different-password', backup)
    with pytest.raises(CryptoError):
        open_backup('portable-password-1', backup[:-4])
    with pytest.raises(CryptoError):
        seal_backup('short', payload)


def test_encrypted_sqlcipher_snapshot_portable_restore(tmp_path):
    key = os.urandom(32)
    original = sqlite.connect(str(tmp_path/'original.db'))
    original.execute(f'PRAGMA key="x\'{key.hex()}\'"')
    original.execute('CREATE TABLE facts(value TEXT)')
    original.execute('INSERT INTO facts VALUES (?)', ('portable-real-db-health-marker',))
    original.commit()
    snapshot = sqlite.connect(str(tmp_path/'snapshot.db'))
    snapshot.execute(f'PRAGMA key="x\'{key.hex()}\'"')
    original.backup(snapshot)
    snapshot.close()
    original.close()
    payload = json.dumps({'key':key.hex(),'db':base64.b64encode((tmp_path/'snapshot.db').read_bytes()).decode()}).encode()
    backup = seal_backup('independent-account-password',payload)
    # No original DPAPI material is present in this portable container.
    recovered = json.loads(open_backup('independent-account-password',backup))
    target = tmp_path/'other-environment.db'
    target.write_bytes(base64.b64decode(recovered['db']))
    conn = sqlite.connect(str(target))
    conn.execute(f'PRAGMA key="x\'{recovered["key"]}\'"')
    assert conn.execute('SELECT value FROM facts').fetchone()[0]=='portable-real-db-health-marker'
    assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    conn.close()
    for f in tmp_path.iterdir():
        assert b'portable-real-db-health-marker' not in f.read_bytes()
