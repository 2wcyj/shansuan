"""Cloud key wrapping validates ownership and refuses unconfigured production use."""
import base64
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class LocalKMSTransport:
    """Substitute only the external SDK transport with authenticated local encryption."""
    def __init__(self, key_id):
        self.key_id = key_id
        self.aes = AESGCM(b't' * 32)

    def encrypt_with_options(self, request, runtime):
        nonce = b'\x01' * 12
        aad = json.dumps(request.encryption_context, sort_keys=True).encode()
        ciphertext = nonce + self.aes.encrypt(nonce, base64.b64decode(request.plaintext), aad)
        return SimpleNamespace(body=SimpleNamespace(
            key_id=self.key_id, ciphertext_blob=base64.b64encode(ciphertext).decode()))

    def decrypt_with_options(self, request, runtime):
        ciphertext = base64.b64decode(request.ciphertext_blob)
        aad = json.dumps(request.encryption_context, sort_keys=True).encode()
        plaintext = self.aes.decrypt(ciphertext[:12], ciphertext[12:], aad)
        return SimpleNamespace(body=SimpleNamespace(
            key_id=self.key_id, plaintext=base64.b64encode(plaintext).decode()))


def test_aliyun_key_wrapping_binds_account_and_preserves_data_across_instances():
    from app.backend.cloud.kms import AliyunKeyManager, KMSUnavailable
    from app.backend.cloud.crypto import CloudCrypto
    key_id = '11111111-2222-3333-4444-555555555555'
    transport = LocalKMSTransport(key_id)
    crypto = CloudCrypto(AliyunKeyManager('cn-hangzhou', key_id, client=transport))
    owner, stranger = uuid4(), uuid4()
    key, wrapped = crypto.create_data_key(owner)
    ciphertext = crypto.encrypt(owner, key, b'synthetic-private-profile')
    restarted = CloudCrypto(AliyunKeyManager('cn-hangzhou', key_id, client=transport))
    restored = restarted.unwrap_data_key(owner, wrapped)
    assert restarted.decrypt(owner, restored, ciphertext) == b'synthetic-private-profile'
    assert key not in wrapped
    with pytest.raises(KMSUnavailable):
        restarted.unwrap_data_key(stranger, wrapped)
    tampered = bytearray(wrapped)
    tampered[-2] ^= 1
    with pytest.raises(KMSUnavailable):
        restarted.unwrap_data_key(owner, bytes(tampered))


@pytest.mark.parametrize('region', ['cn-hongkong', 'us-west-1', 'cn-hangzhou.attacker.test'])
def test_kms_rejects_regions_outside_mainland_before_creating_a_client(region):
    from app.backend.cloud.kms import AliyunKeyManager
    with pytest.raises(ValueError):
        AliyunKeyManager(region, '11111111-2222-3333-4444-555555555555')


def test_kms_errors_never_include_sdk_response_or_plaintext():
    from app.backend.cloud.kms import AliyunKeyManager, KMSUnavailable
    class FailingTransport:
        def encrypt_with_options(self, *args):
            raise RuntimeError('AccessKey=secret-value Plaintext=sensitive-material')
    manager = AliyunKeyManager('cn-hangzhou', '11111111-2222-3333-4444-555555555555', client=FailingTransport())
    with pytest.raises(KMSUnavailable) as error:
        manager.wrap_key(uuid4(), b'k' * 32)
    assert 'secret-value' not in str(error.value)
    assert 'sensitive-material' not in str(error.value)


def test_production_kms_configuration_is_required_and_unknown_providers_fail_closed():
    from app.backend.cloud.kms import key_manager_from_env
    with pytest.raises(ValueError, match='KMS'):
        key_manager_from_env('production', {})
    with pytest.raises(ValueError, match='KMS'):
        key_manager_from_env('staging', {'KMS_PROVIDER': 'fake'})
    assert key_manager_from_env('development', {}) is None
    assert key_manager_from_env('test', {}) is None


def test_repository_uses_existing_wrapped_key_without_new_kms_encrypt(postgres_database):
    import asyncio
    import asyncpg
    from app.backend.cloud.context import tenant_context
    from app.backend.cloud.crypto import CloudCrypto
    from app.backend.cloud.kms import AliyunKeyManager
    from app.backend.cloud.repository import TenantRepository
    account_id = uuid4()
    key_id = '11111111-2222-3333-4444-555555555555'
    transport = LocalKMSTransport(key_id)
    crypto = CloudCrypto(AliyunKeyManager('cn-hangzhou', key_id, client=transport))
    repository = TenantRepository(postgres_database['runtime_url'], crypto)

    async def exercise():
        connection = await asyncpg.connect(host=postgres_database['host'], port=postgres_database['port'],
            user='postgres', password=postgres_database['admin_password'], database=postgres_database['database'])
        try:
            await connection.execute("INSERT INTO accounts(id,email,password_hash,status,is_admin) "
                "VALUES($1,$2,'synthetic','active',false)", account_id, f'{account_id}@example.test')
        finally:
            await connection.close()
        with tenant_context(account_id):
            created = await repository.create('profile', {'weight': 65})
            def disabled_encrypt(*args):
                raise RuntimeError('Wrapping unavailable; existing keys must still be readable')
            transport.encrypt_with_options = disabled_encrypt
            restarted = TenantRepository(postgres_database['runtime_url'], crypto)
            assert (await restarted.get(created['id']))['body'] == {'weight': 65}
    asyncio.run(exercise())
