"""OSS configuration and failure boundaries without cloud credentials or network."""
import io
from types import SimpleNamespace

import pytest


class Bucket:
    def __init__(self, acl='private', location='oss-cn-hangzhou', versioning=None):
        self.info = SimpleNamespace(acl=acl, location=location, versioning_status=versioning,
                                    cross_region_replication=None)
        self.values = {}
        self.headers = None

    def get_bucket_info(self):
        return self.info

    def put_object(self, key, content, headers):
        self.values[key] = content
        self.headers = headers

    def get_object(self, key):
        return io.BytesIO(self.values[key])

    def delete_object(self, key):
        self.values.pop(key, None)


def test_oss_requires_mainland_private_unversioned_bucket_and_opaque_keys():
    from app.backend.cloud.object_store import AliyunObjectStore, ObjectStoreUnavailable
    for region in ['cn-hongkong', 'us-west-1', 'https://untrusted.example']:
        with pytest.raises(ValueError):
            AliyunObjectStore(region, 'synthetic-bucket', client=Bucket())
    for bucket in [Bucket(acl='public-read'), Bucket(location='oss-cn-hongkong'),
                   Bucket(versioning='Enabled'), Bucket(versioning='Suspended')]:
        with pytest.raises(ObjectStoreUnavailable):
            AliyunObjectStore('cn-hangzhou', 'synthetic-bucket', client=bucket).check()
    store = AliyunObjectStore('cn-hangzhou', 'synthetic-bucket', client=Bucket())
    for key in ['../private', 'photos/name.jpg', 'https://untrusted.example', 'photos/'+('a'*63)+'.enc']:
        with pytest.raises(ValueError):
            store.put(key, b'ciphertext')


def test_oss_transfers_opaque_bytes_privately_and_bounds_download_size():
    from app.backend.cloud.object_store import AliyunObjectStore, ObjectStoreUnavailable
    bucket = Bucket()
    store = AliyunObjectStore('cn-hangzhou', 'synthetic-bucket', client=bucket)
    assert store.check()
    key = 'photos/'+('a'*64)+'.enc'
    store.put(key, b'synthetic-ciphertext')
    assert bucket.headers['x-oss-object-acl'] == 'private'
    assert bucket.headers['x-oss-server-side-encryption'] == 'AES256'
    assert bucket.headers['Content-Type'] == 'application/octet-stream'
    assert store.get(key, 100) == b'synthetic-ciphertext'
    with pytest.raises(ObjectStoreUnavailable):
        store.get(key, 2)
    store.delete(key)
    assert bucket.values == {}


def test_oss_errors_are_sanitized_and_missing_provider_does_not_use_local_disk():
    from app.backend.cloud.object_store import AliyunObjectStore, ObjectStoreUnavailable, object_store_from_env
    class BrokenBucket(Bucket):
        def get_bucket_info(self):
            raise OSError('raw-secret-access-key')
    with pytest.raises(ObjectStoreUnavailable) as error:
        AliyunObjectStore('cn-hangzhou', 'synthetic-bucket', client=BrokenBucket()).check()
    assert 'raw-secret' not in str(error.value)
    assert object_store_from_env({}) is None
    with pytest.raises(ValueError):
        object_store_from_env({'OSS_PROVIDER':'filesystem'})
