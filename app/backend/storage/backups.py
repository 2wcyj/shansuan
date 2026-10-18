"""Authenticated portable backups and staged, whole-generation restore."""
import base64
import csv
from datetime import date
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import time
import uuid
from app.backend.errors import AppError
from .crypto import seal_backup, open_backup, encrypt, decrypt, dpapi, CryptoError
from .database import atomic_file, encode, connect, SCHEMA, now

LIMIT = 256 * 1024 * 1024


class Backups:
    def __init__(self, store):
        self.store, self.tickets = store, {}
        self.directory = store.root / 'backups'
        self.directory.mkdir(exist_ok=True)
        self.warning = None
        store.before_write = self.daily
        for folder in (store.root/'generations').iterdir():
            if (folder/'.staged').is_file():
                if folder.name==store.generation:(folder/'.staged').unlink()
                else:shutil.rmtree(folder)

    def payload(self):
        s = self.store
        with s.lock:
            path = s.folder / (uuid.uuid4().hex + '.snapshot')
            try:
                s.snapshot(path)
                photos = {}
                from .photos import Photos
                for row in s.conn.execute('SELECT id FROM attachments').fetchall():
                    Photos(s).read(row[0])  # authenticate each attachment before success
                    photos[row[0]] = base64.b64encode((s.folder / 'photos' / (row[0]+'.enc')).read_bytes()).decode()
                payload = encode({'format':1,'schema':SCHEMA,'created_at':now(),'key':base64.b64encode(s.key).decode(),
                                  'db':base64.b64encode(path.read_bytes()).decode(),'photos':photos}).encode()
                if len(payload) > LIMIT:
                    raise AppError('数据超过第一版256MB备份上限，请先清理不再需要的照片', 'backup_size',413)
                return payload
            finally:
                path.unlink(missing_ok=True)

    def portable(self, password, confirmation):
        if password != confirmation:
            raise AppError('两次输入的备份密码不一致', 'password')
        payload = self.payload()
        try:blob = seal_backup(password, payload)
        except CryptoError as e:raise AppError(str(e),'password',422) from e
        if open_backup(password,blob) != payload:
            raise AppError('备份校验失败', 'backup',503)
        return blob

    def local(self, reason='manual'):
        with self.store.lock:
            payload, key = self.payload(), os.urandom(32)
            wrapped = dpapi(key)
            blob = b'MNAL' + len(wrapped).to_bytes(4,'big') + wrapped + encrypt(key,payload,b'local-backup-v1')
            if self.open_local(blob) != payload:
                raise AppError('自动备份校验失败', 'backup',503)
            path = self.directory / (reason + '-' + date.today().isoformat() + '-' + uuid.uuid4().hex + '.mnal')
            atomic_file(path,blob)
            return path

    def manual(self):
        with self.store.lock:
            path=self.local('manual')
            previous=sorted(self.directory.glob('manual-*.mnal'),key=lambda p:p.stat().st_mtime,reverse=True)
            for old in previous[14:]:old.unlink()
            return path

    @staticmethod
    def open_local(blob):
        if blob[:4] != b'MNAL':
            raise CryptoError('本机备份格式不正确')
        n = int.from_bytes(blob[4:8],'big')
        return decrypt(dpapi(blob[8:8+n],True),blob[8+n:],b'local-backup-v1')

    def daily(self):
        if list(self.directory.glob('daily-' + date.today().isoformat() + '-*.mnal')):
            return
        try:
            self.local('daily')
            daily = sorted(self.directory.glob('daily-*.mnal'),key=lambda p:p.stat().st_mtime,reverse=True)
            for old in daily[14:]:
                old.unlink()
            self.warning = None
        except Exception:
            self.warning = '自动备份未成功，请检查磁盘空间与权限；已阻止本次写入'
            raise AppError(self.warning,'backup',503)

    def listing(self):
        return [{'name':p.name,'bytes':p.stat().st_size} for p in sorted(self.directory.glob('*.mnal'),reverse=True)]

    def stage(self, blob, password=None, local=False):
        for token,ticket in list(self.tickets.items()):
            if ticket['expires']<time.monotonic():
                folder=self.store.root/'generations'/ticket['generation']
                if folder.name!=self.store.generation and (folder/'.staged').is_file():shutil.rmtree(folder)
                del self.tickets[token]
        if len(blob) > LIMIT * 2:
            raise AppError('备份文件超过大小上限','backup_size',413)
        try:
            raw = self.open_local(blob) if local else open_backup(password or '',blob)
            data = json.loads(raw)
            if data['format'] != 1 or data['schema'] != SCHEMA:
                raise AppError('备份版本不兼容，未覆盖当前数据','version',409)
            if not isinstance(data['photos'],dict) or len(data['photos']) > 10000:
                raise ValueError()
            key = base64.b64decode(data['key'],validate=True)
            db = base64.b64decode(data['db'],validate=True)
            if len(key) != 32 or len(db) > LIMIT:
                raise ValueError()
        except AppError:
            raise
        except Exception as e:
            raise AppError('备份密码错误、文件损坏或格式不受支持；当前数据未变','backup',422) from e
        if shutil.disk_usage(self.store.root).free < len(raw)*3 + 8*1024*1024:
            raise AppError('磁盘空间不足，请腾出空间后重试','disk',507)
        generation = uuid.uuid4().hex
        folder = self.store.root / 'generations' / generation
        folder.mkdir()
        (folder / 'photos').mkdir()
        atomic_file(folder/'.staged',b'1')
        conn = None
        try:
            atomic_file(folder / 'key.dpapi',dpapi(key))
            atomic_file(folder / 'nutrition.db',db)
            conn = connect(folder / 'nutrition.db',key)
            if conn.execute('PRAGMA user_version').fetchone()[0] != SCHEMA or conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or conn.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError()
            attachments = conn.execute('SELECT * FROM attachments').fetchall()
            if set(data['photos']) != {r['id'] for r in attachments}:
                raise ValueError()
            for row in attachments:
                id = row['id']
                if len(id) != 32 or any(c not in '0123456789abcdef' for c in id):
                    raise ValueError()
                encrypted = base64.b64decode(data['photos'][id],validate=True)
                image = decrypt(key,encrypted,id.encode())
                if len(image) != row['size'] or hashlib.sha256(image).hexdigest() != row['sha256']:
                    raise ValueError()
                atomic_file(folder / 'photos' / (id+'.enc'),encrypted)
            counts = {r[0]:r[1] for r in conn.execute('SELECT kind,count(*) FROM entities GROUP BY kind').fetchall()}
            token = uuid.uuid4().hex
            self.tickets[token] = {'generation':generation,'epoch':self.store.epoch,'expires':time.monotonic()+600}
            return {'ticket':token,'created_at':data['created_at'],'counts':counts,'scope':'整体替换当前个人数据，不合并；外部备份不变'}
        except Exception as e:
            if conn:
                conn.close(); conn = None
            shutil.rmtree(folder)
            raise AppError('备份内容或关联校验失败，当前数据未变','backup',422) from e
        finally:
            if conn:
                conn.close()

    def commit(self, token, confirmation):
        if confirmation != '整体替换':
            raise AppError('请输入“整体替换”确认恢复')
        s = self.store
        with s.lock:
            ticket = self.tickets.get(token)
            if not ticket or ticket['expires'] < time.monotonic() or ticket['epoch'] != s.epoch:
                raise AppError('恢复校验已过期，请重新选择备份','conflict',409)
            snapshot = self.local('pre-restore')  # never overwrite if this fails
            old = s.generation
            try:
                # Validate/activate before pointer commit. Both complete under one writer lock.
                s.activate(ticket['generation'])
                atomic_file(s.root / 'active.json',encode({'format':1,'generation':s.generation}).encode())
            except BaseException:
                s.activate(old)
                atomic_file(s.root / 'active.json',encode({'format':1,'generation':old}).encode())
                raise
            (s.folder/'.staged').unlink(missing_ok=True)
            self.tickets.clear()
            return {'restored':True,'rollback_backup':snapshot.name}

    def export(self, format):
        with self.store.lock:
            rows = self.store.conn.execute('SELECT kind,id FROM entities ORDER BY kind,id').fetchall()
            data = {kind:[self.store.get(kind,r['id']) for r in rows if r['kind']==kind] for kind in sorted({r['kind'] for r in rows})}
            if format == 'json':
                return encode({'exported_at':now(),'data':data}).encode('utf-8')
            if format != 'csv':
                raise AppError('请选择JSON或CSV格式')
            out = io.StringIO(newline='')
            writer = csv.writer(out)
            writer.writerow(['类型','编号','日期','数据JSON'])
            def safe(v):
                text = str(v or '')
                return "'"+text if text.lstrip().startswith(('=','+','-','@','\t','\r')) else text
            for kind, entries in data.items():
                for item in entries:
                    writer.writerow([safe(kind),safe(item['id']),safe(item['day']),safe(encode(item))])
            return out.getvalue().encode('utf-8-sig')

    def erase(self, confirmation, include_backups=False):
        if confirmation != '删除全部个人数据':
            raise AppError('请输入“删除全部个人数据”确认操作')
        s = self.store
        with s.lock:
            old_folders = list((s.root / 'generations').iterdir())
            generation, _ = s.create_generation()
            old=s.generation
            try:
                s.activate(generation)
                atomic_file(s.root / 'active.json',encode({'format':1,'generation':generation}).encode())
            except BaseException:
                s.activate(old)
                raise
            for folder in old_folders:
                if folder.is_relative_to(s.root / 'generations'):
                    shutil.rmtree(folder)
            if include_backups:
                shutil.rmtree(self.directory)
                self.directory.mkdir()
            self.tickets.clear()
            return {'deleted':True,'backups_deleted':include_backups,'external_backups':'其他位置的备份需自行删除；普通删除不等于磁盘安全擦除'}
