"""Mainland Alibaba Cloud KMS adapter; only account data keys leave this process."""
from __future__ import annotations

import base64
import hmac
import os
import re
import secrets
from uuid import UUID


class KMSUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('Cloud encryption service unavailable')


class AliyunKeyManager:
    # Deliberate allowlist: additional mainland regions require deployment review.
    REGIONS = {'cn-hangzhou', 'cn-shanghai', 'cn-beijing', 'cn-shenzhen',
               'cn-zhangjiakou', 'cn-huhehaote', 'cn-wulanchabu', 'cn-chengdu',
               'cn-guangzhou', 'cn-heyuan', 'cn-qingdao'}

    def __init__(self, region: str, key_id: str, *, client=None):
        if region not in self.REGIONS:
            raise ValueError('KMS_REGION_ID must be an approved mainland region')
        if not isinstance(key_id, str) or not re.fullmatch(r'[A-Za-z0-9-]{8,128}', key_id):
            raise ValueError('KMS_KEY_ID must be a concrete key ID, not an alias or URL')
        self.key_id = key_id
        if client is None:
            from alibabacloud_credentials.client import Client as Credentials
            from alibabacloud_kms20160120.client import Client
            from alibabacloud_tea_openapi.models import Config
            client = Client(Config(credential=Credentials(), region_id=region,
                endpoint=f'kms.{region}.aliyuncs.com', protocol='https',
                connect_timeout=3000, read_timeout=5000))
        self._client = client

    @staticmethod
    def _context(account_id: UUID):
        if not isinstance(account_id, UUID):
            raise ValueError('Account UUID is required')
        return {'application': 'shansuan-cloud-v1', 'account_id': str(account_id)}

    @staticmethod
    def _runtime():
        from darabonba.runtime import RuntimeOptions
        return RuntimeOptions(ignore_ssl=False, autoretry=False,
                              connect_timeout=3000, read_timeout=5000)

    def wrap_key(self, account_id: UUID, key: bytes) -> bytes:
        from alibabacloud_kms20160120.models import EncryptRequest
        context = self._context(account_id)
        if not isinstance(key, bytes) or len(key) != 32:
            raise ValueError('KMS wrapping requires a 32-byte key')
        try:
            response = self._client.encrypt_with_options(EncryptRequest(
                key_id=self.key_id, plaintext=base64.b64encode(key).decode('ascii'),
                encryption_context=context), self._runtime()).body
            if response.key_id != self.key_id:
                raise ValueError('Unexpected KMS key')
            encoded = response.ciphertext_blob.encode('ascii')
            if not 1 <= len(encoded) <= 32768 or not base64.b64decode(encoded, validate=True):
                raise ValueError('Invalid wrapped key')
            return b'SSKMS1:' + encoded
        except Exception:
            raise KMSUnavailable() from None

    def unwrap_key(self, account_id: UUID, wrapped_key: bytes) -> bytes:
        from alibabacloud_kms20160120.models import DecryptRequest
        context = self._context(account_id)
        try:
            if not isinstance(wrapped_key, bytes) or not wrapped_key.startswith(b'SSKMS1:'):
                raise ValueError('Unknown wrapped key format')
            encoded = wrapped_key[7:]
            if not 1 <= len(encoded) <= 32768:
                raise ValueError('Invalid wrapped key length')
            base64.b64decode(encoded, validate=True)
            response = self._client.decrypt_with_options(DecryptRequest(
                ciphertext_blob=encoded.decode('ascii'), encryption_context=context), self._runtime()).body
            if response.key_id != self.key_id:
                raise ValueError('Unexpected KMS key')
            key = base64.b64decode(response.plaintext, validate=True)
            if len(key) != 32:
                raise ValueError('Invalid data key')
            return key
        except Exception:
            raise KMSUnavailable() from None

    def check(self) -> bool:
        # Random synthetic material only; never reads a user's profile or existing key.
        account_id = UUID(bytes=secrets.token_bytes(16))
        key = secrets.token_bytes(32)
        restored = self.unwrap_key(account_id, self.wrap_key(account_id, key))
        if not hmac.compare_digest(key, restored):
            raise KMSUnavailable()
        return True


class HuaweiKeyManager:
    """Huawei Cloud KMS adapter. Only the account data key is sent to KMS."""

    # Deliberate allowlist of Huawei Cloud regions that support KMS.
    REGIONS = {'cn-north-1', 'cn-north-4', 'cn-north-9', 'cn-east-2', 'cn-east-3',
               'cn-south-1', 'cn-southwest-2', 'ap-southeast-1', 'ap-southeast-2',
               'ap-southeast-3', 'af-south-1', 'na-mexico-1', 'sa-brazil-1'}

    PREFIX = b'SSHW1:'

    def __init__(self, region: str, key_id: str, *, project_id: str = '',
                 access_key: str = '', secret_key: str = '', security_token: str = '',
                 client=None):
        if region not in self.REGIONS:
            raise ValueError('KMS_REGION_ID must be an approved Huawei Cloud region')
        if not isinstance(key_id, str) or not re.fullmatch(r'[A-Za-z0-9-]{8,128}', key_id):
            raise ValueError('KMS_KEY_ID must be a concrete key ID, not an alias or URL')
        self.key_id = key_id
        if client is None:
            if not project_id or not access_key or not secret_key:
                raise ValueError('Huawei Cloud KMS requires project, access key and secret key')
            from huaweicloudsdkcore.auth.credentials import BasicCredentials
            from huaweicloudsdkcore.region.region import Region
            from huaweicloudsdkkms.v2 import KmsClient
            credentials = BasicCredentials(access_key, secret_key, project_id)
            if security_token:
                credentials = credentials.with_security_token(security_token)
            client = (KmsClient.new_builder()
                      .with_credentials(credentials)
                      .with_region(Region(region, f'https://kms.{region}.myhuaweicloud.com'))
                      .build())
        self._client = client

    @staticmethod
    def _payload(account_id: UUID, key: bytes) -> bytes:
        if not isinstance(account_id, UUID):
            raise ValueError('Account UUID is required')
        if not isinstance(key, bytes) or len(key) != 32:
            raise ValueError('KMS wrapping requires a 32-byte key')
        # The account binding travels inside the plaintext so decryption is not
        # silently reusable for a different account even without KMS AAD support.
        return account_id.bytes + key

    def wrap_key(self, account_id: UUID, key: bytes) -> bytes:
        from huaweicloudsdkkms.v2.model import CreateEncryptDataRequest, EncryptDataRequestBody
        payload = self._payload(account_id, key)
        try:
            response = self._client.create_encrypt_data(CreateEncryptDataRequest(
                body=EncryptDataRequestBody(
                    key_id=self.key_id,
                    plain_text=base64.b64encode(payload).decode('ascii'))))
            if response.key_id != self.key_id:
                raise ValueError('Unexpected KMS key')
            encoded = response.cipher_text.encode('ascii')
            if not 1 <= len(encoded) <= 32768 or not base64.b64decode(encoded, validate=True):
                raise ValueError('Invalid wrapped key')
            return self.PREFIX + encoded
        except Exception:
            raise KMSUnavailable() from None

    def unwrap_key(self, account_id: UUID, wrapped_key: bytes) -> bytes:
        from huaweicloudsdkkms.v2.model import CreateDecryptDataRequest, DecryptDataRequestBody
        try:
            if not isinstance(wrapped_key, bytes) or not wrapped_key.startswith(self.PREFIX):
                raise ValueError('Unknown wrapped key format')
            encoded = wrapped_key[len(self.PREFIX):]
            if not 1 <= len(encoded) <= 32768:
                raise ValueError('Invalid wrapped key length')
            base64.b64decode(encoded, validate=True)
            response = self._client.create_decrypt_data(CreateDecryptDataRequest(
                body=DecryptDataRequestBody(cipher_text=encoded.decode('ascii'))))
            if response.key_id != self.key_id:
                raise ValueError('Unexpected KMS key')
            payload = base64.b64decode(response.plain_text, validate=True)
            if not isinstance(account_id, UUID):
                raise ValueError('Account UUID is required')
            if payload[:16] != account_id.bytes or len(payload[16:]) != 32:
                raise ValueError('Wrapped key does not belong to this account')
            return payload[16:]
        except Exception:
            raise KMSUnavailable() from None

    def check(self) -> bool:
        account_id = UUID(bytes=secrets.token_bytes(16))
        key = secrets.token_bytes(32)
        restored = self.unwrap_key(account_id, self.wrap_key(account_id, key))
        if not hmac.compare_digest(key, restored):
            raise KMSUnavailable()
        return True


def key_manager_from_env(environment: str, environ=None):
    values = os.environ if environ is None else environ
    provider = values.get('KMS_PROVIDER', '').strip().lower()
    if not provider and environment in {'development', 'test'}:
        return None
    if provider == 'huawei':
        return HuaweiKeyManager(
            values.get('KMS_REGION_ID', '').strip(),
            values.get('KMS_KEY_ID', '').strip(),
            project_id=values.get('HUAWEI_CLOUD_PROJECT_ID', '').strip(),
            access_key=(values.get('HUAWEI_CLOUD_ACCESS_KEY_ID')
                        or values.get('HUAWEICLOUD_SDK_AK', '')).strip(),
            secret_key=(values.get('HUAWEI_CLOUD_SECRET_ACCESS_KEY')
                        or values.get('HUAWEICLOUD_SDK_SK', '')).strip(),
            security_token=values.get('HUAWEI_CLOUD_SECURITY_TOKEN', '').strip(),
        )
    if provider == 'aliyun':
        return AliyunKeyManager(values.get('KMS_REGION_ID', '').strip(),
                                values.get('KMS_KEY_ID', '').strip())
    raise ValueError('KMS_PROVIDER must be huawei (or legacy aliyun); cloud encryption is required')
