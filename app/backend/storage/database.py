"""One writer, encrypted generations, optimistic edits and atomic idempotency."""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import threading
import uuid
from sqlcipher3 import dbapi2 as sql
from app.backend.errors import AppError, conflict
from .crypto import dpapi

SCHEMA = 1
MIGRATIONS = {}  # Future ordered SQL steps, keyed by destination version.


def now():
    return datetime.now().astimezone().isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def atomic_file(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('xb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def connect(path, key):
    conn = sql.connect(str(path), check_same_thread=False, isolation_level=None)
    conn.execute(f'PRAGMA key="x\'{key.hex()}\'"')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA temp_store=MEMORY')
    conn.execute('PRAGMA synchronous=FULL')
    conn.execute('PRAGMA journal_mode=DELETE')
    conn.execute('SELECT count(*) FROM sqlite_master').fetchone()
    conn.row_factory = sql.Row
    return conn


DDL = [
    'CREATE TABLE entities(kind TEXT NOT NULL,id TEXT NOT NULL,day TEXT,body TEXT NOT NULL,version INTEGER NOT NULL CHECK(version>0),created_at TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(kind,id))',
    'CREATE INDEX entities_by_day ON entities(kind,day)',
    'CREATE TABLE history(kind TEXT,id TEXT,version INTEGER,body TEXT NOT NULL,PRIMARY KEY(kind,id,version))',
    'CREATE TABLE requests(key TEXT PRIMARY KEY,digest TEXT NOT NULL,result TEXT NOT NULL)',
    'CREATE TABLE attachments(id TEXT PRIMARY KEY,sha256 TEXT NOT NULL,size INTEGER NOT NULL)',
    'CREATE TABLE entity_photos(kind TEXT,entity_id TEXT,photo_id TEXT,PRIMARY KEY(kind,entity_id,photo_id),FOREIGN KEY(kind,entity_id) REFERENCES entities(kind,id) ON DELETE CASCADE,FOREIGN KEY(photo_id) REFERENCES attachments(id))',
    'CREATE TABLE links(source_kind TEXT,source_id TEXT,target_kind TEXT,target_id TEXT,PRIMARY KEY(source_kind,source_id,target_kind,target_id),FOREIGN KEY(source_kind,source_id) REFERENCES entities(kind,id) ON DELETE CASCADE,FOREIGN KEY(target_kind,target_id) REFERENCES entities(kind,id) ON DELETE CASCADE)',
]


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.lock = threading.RLock()
        self.local = threading.local()
        self.before_write = None
        self.epoch = 0
        self.root.mkdir(parents=True, exist_ok=True)
        active = self.root / 'active.json'
        if not active.exists():
            if (self.root / 'generations').exists() and any((self.root / 'generations').iterdir()):
                raise AppError('数据指针丢失，请使用备份恢复；不会覆盖现有数据', 'storage', 503)
            generation, key = self.create_generation()
            atomic_file(active, encode({'generation':generation,'format':1}).encode())
        self.activate(json.loads(active.read_text(encoding='utf-8'))['generation'])

    def create_generation(self):
        generation = uuid.uuid4().hex
        folder = self.root / 'generations' / generation
        folder.mkdir(parents=True)
        (folder / 'photos').mkdir()
        key = os.urandom(32)
        atomic_file(folder / 'key.dpapi', dpapi(key))
        conn = connect(folder / 'nutrition.db', key)
        try:
            conn.execute('BEGIN IMMEDIATE')
            for statement in DDL:
                conn.execute(statement)
            conn.execute(f'PRAGMA user_version={SCHEMA}')
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
        return generation, key

    def activate(self, generation):
        if len(generation) != 32 or any(c not in '0123456789abcdef' for c in generation):
            raise AppError('数据代标识损坏', 'storage', 503)
        folder = self.root / 'generations' / generation
        if not (folder / 'nutrition.db').is_file():
            raise AppError('数据文件丢失，不能创建空库替代', 'storage', 503)
        key = dpapi((folder / 'key.dpapi').read_bytes(), True)
        conn = connect(folder / 'nutrition.db', key)
        if conn.execute('PRAGMA user_version').fetchone()[0] < SCHEMA:
            from .migrations import migrate
            try:migrate(conn,folder,SCHEMA,MIGRATIONS)
            except BaseException:
                conn.close()
                raise
        if conn.execute('PRAGMA user_version').fetchone()[0] != SCHEMA:
            conn.close()
            raise AppError('数据库版本不兼容，请使用对应版本或有效备份', 'version', 409)
        if conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            conn.close()
            raise AppError('数据库校验失败，现有文件已保留', 'storage', 503)
        with self.lock:
            old = getattr(self, 'conn', None)
            if old:
                old.close()
            self.conn, self.key, self.folder, self.generation = conn, key, folder, generation
            self.epoch += 1

    @contextmanager
    def atomic(self):
        with self.lock:
            depth = getattr(self.local, 'depth', 0)
            if depth == 0:
                if self.before_write:
                    self.before_write()
                self.conn.execute('BEGIN IMMEDIATE')
            self.local.depth = depth + 1
            try:
                yield self.conn
                if depth == 0:
                    self.conn.commit()
            except BaseException:
                if depth == 0:
                    self.conn.rollback()
                raise
            finally:
                self.local.depth = depth

    def get(self, kind, id):
        with self.lock:
            row = self.conn.execute('SELECT * FROM entities WHERE kind=? AND id=?', (kind,id)).fetchone()
            if not row:
                return None
            return {**json.loads(row['body']), **{k:row[k] for k in ['id','day','version','created_at','updated_at']}}

    def require(self, kind, id):
        value = self.get(kind,id)
        if value is None:
            raise AppError('这项内容不存在或已删除', 'not_found', 404)
        return value

    def list(self, kind, day=None):
        with self.lock:
            query, params = 'SELECT id FROM entities WHERE kind=?', [kind]
            if day is not None:
                query += ' AND day=?'
                params.append(day)
            rows = self.conn.execute(query + ' ORDER BY created_at,id', params).fetchall()
            return [self.get(kind,row['id']) for row in rows]

    def put(self, kind, id, body, day=None, version=0):
        with self.atomic():
            old = self.get(kind,id)
            if (old and old['version'] != version) or (not old and version != 0):
                raise conflict()
            data = {k:v for k,v in body.items() if k not in {'id','version','day','created_at','updated_at','request_key'}}
            timestamp = now()
            if old:
                self.conn.execute('INSERT INTO history VALUES (?,?,?,?)', (kind,id,version,encode(old)))
                self.conn.execute('UPDATE entities SET day=?,body=?,version=?,updated_at=? WHERE kind=? AND id=?',
                                  (day,encode(data),version+1,timestamp,kind,id))
            else:
                previous=self.conn.execute('SELECT max(version) FROM history WHERE kind=? AND id=?',(kind,id)).fetchone()[0]
                initial_version=(previous or 0)+1
                self.conn.execute('INSERT INTO entities VALUES (?,?,?,?,?,?,?)',
                                  (kind,id,day,encode(data),initial_version,timestamp,timestamp))
            return self.get(kind,id)

    def delete(self, kind, id, version):
        with self.atomic():
            old = self.require(kind,id)
            if old['version'] != version:
                raise conflict()
            self.conn.execute('INSERT INTO history VALUES (?,?,?,?)', (kind,id,version,encode(old)))
            self.conn.execute('DELETE FROM entities WHERE kind=? AND id=?',(kind,id))
            return {'deleted':True}

    def mutate(self, key, payload, operation):
        if not isinstance(key,str) or not 8 <= len(key) <= 160:
            raise AppError('缺少有效的操作标识，请重试')
        digest = hashlib.sha256(encode(payload).encode()).hexdigest()
        with self.atomic():
            row = self.conn.execute('SELECT digest,result FROM requests WHERE key=?',(key,)).fetchone()
            if row:
                if row['digest'] != digest:
                    raise conflict('操作标识已被其他内容使用，请重新发起')
                return json.loads(row['result'])
            result = operation()
            self.conn.execute('INSERT INTO requests VALUES (?,?,?)',(key,digest,encode(result)))
            return result

    def history(self, kind, id):
        with self.lock:
            return [json.loads(r[0]) for r in self.conn.execute('SELECT body FROM history WHERE kind=? AND id=? ORDER BY version',(kind,id)).fetchall()]

    def snapshot(self, path):
        with self.lock:
            target = connect(path,self.key)
            try:
                self.conn.backup(target)
            finally:
                target.close()

    def close(self):
        with self.lock:
            self.conn.close()
