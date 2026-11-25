"""Tenant-bound encrypted photo storage with durable upload/deletion states.

No public URL, local Windows store, original filename, or plaintext file is used.
Account export/deletion still fail closed until the complete object lifecycle is integrated.
"""
from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

from app.backend.cloud.context import current_tenant_id
from app.backend.cloud.domain_store import DomainStore, physical_id
from app.backend.cloud.images import normalize_photo, MAX_UPLOAD
from app.backend.errors import AppError


def unavailable():
    return AppError('云端照片存储暂不可用，请稍后重试', 'photo_storage', 503)


async def object_io(operation, *args):
    # Finish a possibly successful external write before compensation, even on disconnect.
    task = asyncio.create_task(asyncio.to_thread(operation, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        except Exception:
            pass
        raise


class CloudPhotos:
    def __init__(self, repository, objects, *, max_count=50, max_bytes=100*1024*1024):
        if objects is None or repository is None or max_count < 1 or max_bytes < 1:
            raise ValueError('Private storage, repository, and positive quotas are required')
        self.repository, self.objects = repository, objects
        self.max_count, self.max_bytes = max_count, max_bytes

    @staticmethod
    def _id(value):
        try:
            return UUID(str(value))
        except (ValueError, TypeError, AttributeError):
            raise AppError('照片不存在或已删除', 'not_found', 404) from None

    async def _consent(self, connection, account):
        from app.backend.api.cloud_privacy import NOTICE_VERSION
        accepted = await connection.fetchval(
            'SELECT EXISTS(SELECT 1 FROM privacy_consents WHERE account_id=$1 '
            'AND notice_version=$2 AND withdrawn_at IS NULL)', account, NOTICE_VERSION)
        if not accepted:
            raise AppError('请先阅读并明确同意当前敏感个人信息处理说明', 'consent_required', 428)

    @staticmethod
    def _aad(row):
        return f"photo:{row['id']}:{row['object_key']}:{row['media_type']}:{row['byte_size']}".encode('ascii')

    async def add(self, content, declared_mime):
        normalized = await asyncio.to_thread(normalize_photo, content, declared_mime)
        account = current_tenant_id()
        attachment = uuid4()
        key, wrapped = await asyncio.to_thread(self.repository.crypto.create_data_key, account)
        row = {'id':attachment, 'object_key':'photos/'+uuid4().hex+uuid4().hex+'.enc',
               'media_type':'image/jpeg', 'byte_size':len(normalized)}
        encrypted = self.repository.crypto.encrypt(account, key, normalized, self._aad(row))
        async with self.repository.atomic():
            await self.repository.lock_account()
            async with self.repository._tenant_connection() as (_, connection):
                await self._consent(connection, account)
                total = await connection.fetchrow(
                    'SELECT count(*) AS count,COALESCE(sum(byte_size),0) AS bytes FROM attachments WHERE account_id=$1', account)
                if total['count'] >= self.max_count or total['bytes']+len(normalized) > self.max_bytes:
                    raise AppError('当前账户照片存储已达上限，请清理后再试', 'photo_quota', 429)
                await connection.execute(
                    "INSERT INTO attachments(account_id,id,object_key,wrapped_data_key,media_type,byte_size,state) "
                    "VALUES($1,$2,$3,$4,$5,$6,'pending')", account, attachment, row['object_key'], wrapped,
                    row['media_type'], row['byte_size'])
        try:
            await object_io(self.objects.put, row['object_key'], encrypted)
            async with self.repository.atomic():
                await self.repository.lock_account()
                async with self.repository._tenant_connection() as (_, connection):
                    await self._consent(connection, account)
                    state = await connection.fetchval('SELECT state FROM attachments WHERE account_id=$1 AND id=$2', account, attachment)
                    if state != 'pending':
                        raise unavailable()
                    store = DomainStore(await self.repository.list())
                    analysis = store.put('analysis', attachment.hex, {'photo_id':attachment.hex, 'status':'draft', 'items':[]})
                    await store.flush(self.repository)
                    await connection.execute(
                        'INSERT INTO entity_photos(account_id,id,entity_id,attachment_id) VALUES($1,$2,$3,$4)',
                        account, uuid4(), physical_id(account, 'analysis', attachment.hex), attachment)
                    await connection.execute("UPDATE attachments SET state='active' WHERE account_id=$1 AND id=$2", account, attachment)
            return analysis
        except BaseException as error:
            # The row was committed before the external call. If cleanup fails it remains discoverable.
            try:
                await self._discard_upload(attachment)
            except Exception:
                pass
            if isinstance(error, (AppError, asyncio.CancelledError)):
                raise
            raise unavailable() from None

    async def read(self, value):
        attachment = self._id(value)
        async with self.repository.atomic():
            await self.repository.lock_account()
            async with self.repository._tenant_connection() as (account, connection):
                await self._consent(connection, account)
                row = await connection.fetchrow(
                    "SELECT * FROM attachments WHERE account_id=$1 AND id=$2 AND state='active'", account, attachment)
                if row is None:
                    raise AppError('照片不存在或已删除', 'not_found', 404)
                try:
                    if row['media_type'] != 'image/jpeg' or not 0 < row['byte_size'] <= MAX_UPLOAD:
                        raise ValueError('Invalid photo metadata')
                    encrypted = await object_io(self.objects.get, row['object_key'], row['byte_size']+29)
                    key = await asyncio.to_thread(self.repository.crypto.unwrap_data_key, account, row['wrapped_data_key'])
                    data = self.repository.crypto.decrypt(account, key, encrypted, self._aad(row))
                    if len(data) != row['byte_size']:
                        raise ValueError('Invalid photo length')
                    return data
                except Exception:
                    raise unavailable() from None

    async def _remove_object(self, attachment):
        async with self.repository.atomic():
            await self.repository.lock_account()
            async with self.repository._tenant_connection() as (account, connection):
                row = await connection.fetchrow(
                    "SELECT * FROM attachments WHERE account_id=$1 AND id=$2 AND state='deleting'", account, attachment)
                if row is None:
                    return
                try:
                    await object_io(self.objects.delete, row['object_key'])
                except Exception:
                    raise unavailable() from None
                await connection.execute('DELETE FROM attachments WHERE account_id=$1 AND id=$2', account, attachment)

    async def _discard_upload(self, attachment):
        async with self.repository.atomic():
            await self.repository.lock_account()
            async with self.repository._tenant_connection() as (account, connection):
                await connection.execute("UPDATE attachments SET state='deleting' WHERE account_id=$1 AND id=$2 AND state='pending'", account, attachment)
        await self._remove_object(attachment)

    async def delete(self, value):
        attachment = self._id(value)
        async with self.repository.atomic():
            await self.repository.lock_account()
            async with self.repository._tenant_connection() as (account, connection):
                await self._consent(connection, account)
                row = await connection.fetchrow('SELECT * FROM attachments WHERE account_id=$1 AND id=$2', account, attachment)
                if row is None or row['state'] == 'pending':
                    raise AppError('照片不存在或已删除', 'not_found', 404)
                store = DomainStore(await self.repository.list())
                analysis = store.get('analysis', attachment.hex)
                if analysis:
                    if analysis.get('record_id'):
                        raise AppError('照片关联实际饮食，请先在饮食记录中处理关联', 'photo_linked', 409)
                    store.delete('analysis', attachment.hex, analysis['version'])
                    await store.flush(self.repository)
                await connection.execute("UPDATE attachments SET state='deleting' WHERE account_id=$1 AND id=$2", account, attachment)
        await self._remove_object(attachment)
        return {'deleted':True}

    async def cleanup_pending(self):
        """Per-account reconciliation; a future worker must schedule this for all owners."""
        async with self.repository.atomic():
            await self.repository.lock_account()
            async with self.repository._tenant_connection() as (account, connection):
                await connection.execute("UPDATE attachments SET state='deleting' WHERE account_id=$1 AND state='pending' AND created_at<clock_timestamp()-interval '1 hour'", account)
                ids = await connection.fetch("SELECT id FROM attachments WHERE account_id=$1 AND state='deleting'", account)
        for row in ids:
            await self._remove_object(row['id'])
        return len(ids)
