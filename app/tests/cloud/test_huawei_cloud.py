"""Huawei Cloud KMS/OBS adapters: scheme, sizing and failure boundaries without network."""
import base64
import io
import sys
import types
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_ID = '11111111-2222-3333-4444-555555555555'


class HuaweiKMSTransport:
    """Substitute only the external SDK transport with authenticated local encryption."""

    def __init__(self, key_id=KEY_ID):
        self.key_id = key_id
        self.aes = AESGCM(b'h' * 32)

    def create_encrypt_data(self, request):
        plain = base64.b64decode(request.body.plain_text)
        nonce = b'\x02' * 12
        sealed = nonce + self.aes.encrypt(nonce, plain, None)
        return SimpleNamespace(key_id=self.key_id,
                               cipher_text=base64.b64encode(sealed).decode('ascii'))

    def create_decrypt_data(self, request):
        sealed = base64.b64decode(request.body.cipher_text)
        plain = self.aes.decrypt(sealed[:12], sealed[12:], None)
        return SimpleNamespace(key_id=self.key_id,
                               plain_text=base64.b64encode(plain).decode('ascii'))


@pytest.fixture
def kms_models(monkeypatch):
    """Provide the SDK request models and client builder so logic runs without the real SDK."""
    core = types.ModuleType('huaweicloudsdkcore')
    auth = types.ModuleType('huaweicloudsdkcore.auth')
    credentials = types.ModuleType('huaweicloudsdkcore.auth.credentials')
    region_module = types.ModuleType('huaweicloudsdkcore.region')
    region_class_module = types.ModuleType('huaweicloudsdkcore.region.region')
    package = types.ModuleType('huaweicloudsdkkms')
    version = types.ModuleType('huaweicloudsdkkms.v2')
    models = types.ModuleType('huaweicloudsdkkms.v2.model')

    class Request:
        def __init__(self, body=None):
            self.body = body

    class Body:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Credentials:
        def __init__(self, ak, sk, project_id):
            self.ak, self.sk, self.project_id = ak, sk, project_id

        def with_security_token(self, token):
            self.token = token
            return self

    class Region:
        def __init__(self, region_id, endpoint):
            self.region_id, self.endpoint = region_id, endpoint

    class Builder:
        def with_credentials(self, value):
            return self

        def with_region(self, value):
            return self

        def build(self):
            return SimpleNamespace()

    class KmsClient:
        @staticmethod
        def new_builder():
            return Builder()

    models.CreateEncryptDataRequest = Request
    models.EncryptDataRequestBody = Body
    models.CreateDecryptDataRequest = Request
    models.DecryptDataRequestBody = Body
    version.model = models
    version.KmsClient = KmsClient
    credentials.BasicCredentials = Credentials
    region_class_module.Region = Region
    region_module.region = region_class_module
    auth.credentials = credentials
    core.auth = auth
    core.region = region_module
    package.v2 = version
    package.v2 = version
    for name, module in {
        'huaweicloudsdkcore': core,
        'huaweicloudsdkcore.auth': auth,
        'huaweicloudsdkcore.auth.credentials': credentials,
        'huaweicloudsdkcore.region': region_module,
        'huaweicloudsdkcore.region.region': region_class_module,
        'huaweicloudsdkkms': package,
        'huaweicloudsdkkms.v2': version,
        'huaweicloudsdkkms.v2.model': models,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)


@pytest.fixture
def obs_sdk(monkeypatch):
    module = types.ModuleType('obs')

    class ObsClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    module.ObsClient = ObsClient
    monkeypatch.setitem(sys.modules, 'obs', module)


def test_huawei_kms_wraps_account_key_and_rejects_other_account(kms_models):
    from app.backend.cloud.kms import HuaweiKeyManager, KMSUnavailable
    from app.backend.cloud.crypto import CloudCrypto

    transport = HuaweiKMSTransport()
    crypto = CloudCrypto(HuaweiKeyManager('cn-north-4', KEY_ID, client=transport))
    owner, stranger = uuid4(), uuid4()
    key, wrapped = crypto.create_data_key(owner)
    assert wrapped.startswith(b'SSHW1:')
    assert key not in wrapped

    payload = crypto.encrypt(owner, key, b'synthetic-private-profile')
    restarted = CloudCrypto(HuaweiKeyManager('cn-north-4', KEY_ID, client=transport))
    restored = restarted.unwrap_data_key(owner, wrapped)
    assert restarted.decrypt(owner, restored, payload) == b'synthetic-private-profile'

    with pytest.raises(KMSUnavailable):
        restarted.unwrap_data_key(stranger, wrapped)
    tampered = bytearray(wrapped)
    tampered[-2] ^= 1
    with pytest.raises(KMSUnavailable):
        restarted.unwrap_data_key(owner, bytes(tampered))


def test_huawei_kms_rejects_unapproved_region_and_alias(kms_models):
    from app.backend.cloud.kms import HuaweiKeyManager

    for region in ['cn-hongkong', 'us-west-1', 'kms.cn-north-4.myhuaweicloud.com']:
        with pytest.raises(ValueError):
            HuaweiKeyManager(region, KEY_ID, client=HuaweiKMSTransport())
    for key_id in ['alias/synthetic', 'https://kms.example/key', 'short']:
        with pytest.raises(ValueError):
            HuaweiKeyManager('cn-north-4', key_id, client=HuaweiKMSTransport())


def test_huawei_kms_errors_are_sanitized(kms_models):
    from app.backend.cloud.kms import HuaweiKeyManager, KMSUnavailable

    class FailingTransport:
        def create_encrypt_data(self, request):
            raise RuntimeError('AccessKey=secret-value Plaintext=sensitive-material')

    manager = HuaweiKeyManager('cn-north-4', KEY_ID, client=FailingTransport())
    with pytest.raises(KMSUnavailable) as error:
        manager.wrap_key(uuid4(), b'k' * 32)
    assert 'secret-value' not in str(error.value)


def test_provider_selection_requires_huawei_credentials(kms_models):
    from app.backend.cloud.kms import key_manager_from_env, HuaweiKeyManager

    with pytest.raises(ValueError, match='KMS'):
        key_manager_from_env('production', {'KMS_PROVIDER': 'fake'})
    with pytest.raises(ValueError):
        key_manager_from_env('production', {
            'KMS_PROVIDER': 'huawei', 'KMS_REGION_ID': 'cn-north-4', 'KMS_KEY_ID': KEY_ID})
    manager = key_manager_from_env('production', {
        'KMS_PROVIDER': 'huawei', 'KMS_REGION_ID': 'cn-north-4', 'KMS_KEY_ID': KEY_ID,
        'HUAWEI_CLOUD_PROJECT_ID': 'project-synthetic',
        'HUAWEI_CLOUD_ACCESS_KEY_ID': 'ak-synthetic',
        'HUAWEI_CLOUD_SECRET_ACCESS_KEY': 'sk-synthetic',
    })
    assert isinstance(manager, HuaweiKeyManager)
    assert manager.key_id == KEY_ID


class ObsBucket:
    def __init__(self, grants=None, size=None):
        self.values = {}
        self.headers = None
        self.grants = grants or []
        self.size = size

    def headBucket(self, bucket):
        return SimpleNamespace(status=200)

    def getBucketAcl(self, bucket):
        return SimpleNamespace(body=SimpleNamespace(grants=self.grants),
                               status=200)

    def putObject(self, bucket, key, content, headers=None):
        if self.size is not None:
            raise AssertionError('putObject should not be used in read tests')
        self.values[key] = content
        self.headers = headers
        return SimpleNamespace(status=200)

    def getObjectMetadata(self, bucket, key):
        size = self.size if self.size is not None else len(self.values.get(key, b''))
        return SimpleNamespace(body=SimpleNamespace(contentLength=size), status=200)

    def getObject(self, bucket, key):
        return SimpleNamespace(body=io.BytesIO(self.values[key]), status=200)

    def deleteObject(self, bucket, key):
        self.values.pop(key, None)
        return SimpleNamespace(status=204)


def test_obs_stores_opaque_bytes_privately_and_bounds_download():
    from app.backend.cloud.object_store import HuaweiObjectStore, ObjectStoreUnavailable

    bucket = ObsBucket()
    store = HuaweiObjectStore('cn-north-4', 'synthetic-bucket', client=bucket)
    assert store.check()
    key = 'photos/' + ('a' * 64) + '.enc'
    store.put(key, b'synthetic-ciphertext')
    assert bucket.headers['x-obs-acl'] == 'private'
    assert bucket.headers['x-obs-server-side-encryption'] == 'AES256'
    assert store.get(key, 128) == b'synthetic-ciphertext'
    with pytest.raises(ObjectStoreUnavailable):
        store.get(key, 4)
    store.delete(key)
    assert key not in bucket.values


def test_obs_rejects_public_grants_and_foreign_keys():
    from app.backend.cloud.object_store import HuaweiObjectStore, ObjectStoreUnavailable

    public = ObsBucket(grants=[SimpleNamespace(grantee=SimpleNamespace(
        uri='http://acs.amazonaws.com/groups/global/AllUsers'))])
    with pytest.raises(ObjectStoreUnavailable):
        HuaweiObjectStore('cn-north-4', 'synthetic-bucket', client=public).check()
    for region in ['cn-hongkong', 'us-west-1', 'https://obs.example']:
        with pytest.raises(ValueError):
            HuaweiObjectStore(region, 'synthetic-bucket', client=ObsBucket())
    store = HuaweiObjectStore('cn-north-4', 'synthetic-bucket', client=ObsBucket())
    for key in ['../private', 'photos/name.jpg', 'https://untrusted.example',
                'photos/' + ('a' * 63) + '.enc']:
        with pytest.raises(ValueError):
            store.put(key, b'ciphertext')


def test_obs_provider_selection_has_no_local_fallback(obs_sdk):
    from app.backend.cloud.object_store import object_store_from_env, HuaweiObjectStore

    assert object_store_from_env({}) is None
    with pytest.raises(ValueError):
        object_store_from_env({'OBS_PROVIDER': 'filesystem'})
    store = object_store_from_env({
        'OBS_PROVIDER': 'huawei', 'OBS_REGION_ID': 'cn-north-4', 'OBS_BUCKET': 'synthetic-bucket',
        'HUAWEI_CLOUD_ACCESS_KEY_ID': 'ak-synthetic',
        'HUAWEI_CLOUD_SECRET_ACCESS_KEY': 'sk-synthetic',
    })
    assert isinstance(store, HuaweiObjectStore)