"""Transactional SQL migrations; snapshot and key remain encrypted on disk."""
import shutil
import uuid
from pathlib import Path
from app.backend.errors import AppError


def migrate(conn, folder, target, steps):
    current = conn.execute('PRAGMA user_version').fetchone()[0]
    if current == target:
        return
    if current > target or any(v not in steps for v in range(current + 1, target + 1)):
        raise AppError('数据库版本不兼容，原数据已保留', 'version', 409)
    from .database import connect
    from .crypto import dpapi
    folder = Path(folder)
    snapshot = folder.parent.parent / 'backups' / ('migration-' + uuid.uuid4().hex)
    snapshot.mkdir(parents=True)
    shutil.copy2(folder / 'key.dpapi', snapshot / 'key.dpapi')
    backup = connect(snapshot / 'nutrition.db', dpapi((folder / 'key.dpapi').read_bytes(), True))
    try:
        conn.backup(backup)
        if backup.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise AppError('升级前备份校验失败，未执行升级', 'storage', 503)
        shutil.copytree(folder / 'photos', snapshot / 'photos')
    finally:
        backup.close()
    conn.execute('BEGIN IMMEDIATE')
    try:
        for version in range(current + 1, target + 1):
            for statement in steps[version]:
                conn.execute(statement)
            conn.execute(f'PRAGMA user_version={version}')
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
