"""Private mainland OSS adapter. Only opaque encrypted bytes reach this boundary."""
from __future__ import annotations

import os
import re
from typing import Protocol

from app.backend.cloud.kms import AliyunKeyManager, HuaweiKeyManager


class ObjectStoreUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('Private object storage unavailable')


class PrivateObjectStore(Protocol):
    def check(self) -> bool: ...
    def put(self, key: str, content: bytes) -> None: ...
    def get(self, key: str, limit: int) -> bytes: ...
    def delete(self, key: str) -> None: ...


class AliyunObjectStore:
    def __init__(self, region: str, bucket: str, *, client=None):
        if region not in AliyunKeyManager.REGIONS:
            raise ValueError('OSS_REGION_ID must be an approved mainland region')
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', bucket):
            raise ValueError('OSS_BUCKET must be a bucket name, not a URL')
        self.region = region
        if client is None:
            import oss2
            from alibabacloud_credentials.client import Client as CredentialsClient
            credentials = CredentialsClient()
            class DefaultCredentials(oss2.credentials.CredentialsProvider):
                def get_credentials(self):
                    value = credentials.get_credential()
                    return oss2.credentials.Credentials(value.access_key_id,
                        value.access_key_secret, value.security_token or '')
            client = oss2.Bucket(oss2.ProviderAuthV4(DefaultCredentials()),
                f'https://oss-{region}.aliyuncs.com', bucket, region=region,
                connect_timeout=10, enable_crc=True)
        self._bucket = client

    @staticmethod
    def _key(key):
        if not isinstance(key, str) or not re.fullmatch(r'photos/[0-9a-f]{64}\.enc', key):
            raise ValueError('Only server-generated object identities are accepted')
        return key

    def check(self):
        try:
            info = self._bucket.get_bucket_info()
            # Versioned buckets need explicit version erasure before they can meet deletion promises.
            if (info.acl != 'private' or info.location != 'oss-'+self.region
                    or info.versioning_status not in {None, ''}
                    or info.cross_region_replication not in {None, '', 'Disabled'}):
                raise ValueError('Unsafe bucket configuration')
            return True
        except Exception:
            raise ObjectStoreUnavailable() from None

    def put(self, key, content):
        self._key(key)
        try:
            self._bucket.put_object(key, content, headers={
                'Content-Type':'application/octet-stream', 'x-oss-object-acl':'private',
                'x-oss-server-side-encryption':'AES256'})
        except Exception:
            raise ObjectStoreUnavailable() from None

    def get(self, key, limit):
        self._key(key)
        try:
            result = self._bucket.get_object(key)
            try:
                value = result.read(limit+1)
            finally:
                result.close()
            if len(value) > limit:
                raise ValueError('Object exceeds expected size')
            return value
        except Exception:
            raise ObjectStoreUnavailable() from None

    def delete(self, key):
        self._key(key)
        try:
            self._bucket.delete_object(key)
        except Exception:
            raise ObjectStoreUnavailable() from None


class HuaweiObjectStore:
    """Private Huawei Cloud OBS adapter. Content is already encrypted by CloudPhotos."""

    def __init__(self, region: str, bucket: str, *, access_key: str = '',
                 secret_key: str = '', security_token: str = '', client=None):
        if region not in HuaweiKeyManager.REGIONS:
            raise ValueError('OBS_REGION_ID must be an approved Huawei Cloud region')
        if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', bucket):
            raise ValueError('OBS_BUCKET must be a bucket name, not a URL')
        self.region = region
        self.bucket = bucket
        if client is None:
            if not access_key or not secret_key:
                raise ValueError('Huawei Cloud OBS requires access key and secret key')
            from obs import ObsClient
            client = ObsClient(
                access_key_id=access_key,
                secret_access_key=secret_key,
                security_token=security_token or None,
                server=f'https://obs.{region}.myhuaweicloud.com',
                connection_timeout=10,
                max_retry_count=0,
            )
        self._client = client

    @staticmethod
    def _key(key):
        if not isinstance(key, str) or not re.fullmatch(r'photos/[0-9a-f]{64}\.enc', key):
            raise ValueError('Only server-generated object identities are accepted')
        return key

    def check(self):
        try:
            self._client.headBucket(self.bucket)
            acl = self._client.getBucketAcl(self.bucket)
            for grant in getattr(getattr(acl, 'body', None), 'grants', None) or []:
                uri = getattr(getattr(grant, 'grantee', None), 'uri', None) or ''
                if 'AllUsers' in uri or 'AuthenticatedUsers' in uri:
                    raise ValueError('Bucket grants public or cross-account read access')
            return True
        except Exception:
            raise ObjectStoreUnavailable() from None

    def put(self, key, content):
        self._key(key)
        try:
            response = self._client.putObject(
                self.bucket, key, content,
                headers={'Content-Type': 'application/octet-stream',
                         'x-obs-acl': 'private',
                         'x-obs-server-side-encryption': 'AES256'})
            status = getattr(response, 'status', 200)
            if status >= 300:
                raise ValueError('Upload rejected')
        except Exception:
            raise ObjectStoreUnavailable() from None

    def get(self, key, limit):
        self._key(key)
        try:
            metadata = self._client.getObjectMetadata(self.bucket, key)
            size = getattr(getattr(metadata, 'body', None), 'contentLength', None)
            if size is not None and int(size) > limit:
                raise ValueError('Object exceeds expected size')
            response = self._client.getObject(self.bucket, key)
            body = response.body
            stream = body if hasattr(body, 'read') else getattr(body, 'stream', None)
            if stream is None:
                raise ValueError('Object body is not readable')
            try:
                value = stream.read(limit + 1)
            finally:
                close = getattr(body, 'close', None)
                if callable(close):
                    close()
            if value is None or len(value) > limit:
                raise ValueError('Object exceeds expected size')
            return bytes(value)
        except Exception:
            raise ObjectStoreUnavailable() from None

    def delete(self, key):
        self._key(key)
        try:
            self._client.deleteObject(self.bucket, key)
        except Exception:
            raise ObjectStoreUnavailable() from None


def object_store_from_env(environ=None):
    values = os.environ if environ is None else environ
    provider = (values.get('OBS_PROVIDER') or values.get('OSS_PROVIDER') or '').strip().lower()
    if not provider:
        return None
    if provider == 'huawei':
        return HuaweiObjectStore(
            (values.get('OBS_REGION_ID') or values.get('OSS_REGION_ID') or '').strip(),
            (values.get('OBS_BUCKET') or values.get('OSS_BUCKET') or '').strip(),
            access_key=(values.get('HUAWEI_CLOUD_ACCESS_KEY_ID')
                        or values.get('HUAWEICLOUD_SDK_AK', '')).strip(),
            secret_key=(values.get('HUAWEI_CLOUD_SECRET_ACCESS_KEY')
                        or values.get('HUAWEICLOUD_SDK_SK', '')).strip(),
            security_token=values.get('HUAWEI_CLOUD_SECURITY_TOKEN', '').strip(),
        )
    if provider == 'aliyun':
        return AliyunObjectStore(values.get('OSS_REGION_ID', '').strip(),
                                 values.get('OSS_BUCKET', '').strip())
    raise ValueError('OBS_PROVIDER must be huawei (or legacy aliyun); no local fallback is allowed')
