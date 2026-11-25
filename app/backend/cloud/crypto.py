"""Authenticated payload encryption using per-account keys wrapped by a KMS adapter."""
from __future__ import annotations

from typing import Protocol
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import secrets


class KeyManager(Protocol):
    def wrap_key(self, account_id: UUID, key: bytes) -> bytes: ...
    def unwrap_key(self, account_id: UUID, wrapped_key: bytes) -> bytes: ...


class CloudCrypto:
    def __init__(self, key_manager: KeyManager):
        if key_manager is None:
            raise ValueError("A cloud KMS key manager is required")
        self.key_manager = key_manager

    def create_data_key(self, account_id: UUID) -> tuple[bytes, bytes]:
        key = secrets.token_bytes(32)
        wrapped = self.key_manager.wrap_key(account_id, key)
        if not isinstance(wrapped, bytes) or len(wrapped) > 32775:
            raise ValueError('Key manager returned an invalid wrapped data key')
        return key, wrapped

    def unwrap_data_key(self, account_id: UUID, wrapped_key: bytes) -> bytes:
        key = self.key_manager.unwrap_key(account_id, bytes(wrapped_key))
        if not isinstance(key, bytes) or len(key) != 32:
            raise ValueError("KMS returned an invalid account data key")
        return key

    @staticmethod
    def encrypt(account_id: UUID, key: bytes, plaintext: bytes,
                associated_data: bytes = b"") -> bytes:
        if not isinstance(key, bytes) or len(key) != 32:
            raise ValueError("AES-256-GCM requires a 32-byte data key")
        nonce = secrets.token_bytes(12)
        aad = b"shansuan-cloud-v1:" + account_id.bytes + b":" + associated_data
        return b"\x01" + nonce + AESGCM(key).encrypt(nonce, plaintext, aad)

    @staticmethod
    def decrypt(account_id: UUID, key: bytes, ciphertext: bytes,
                associated_data: bytes = b"") -> bytes:
        value = bytes(ciphertext)
        if len(value) < 1 + 12 + 16 or value[0] != 1:
            raise ValueError("Invalid encrypted payload")
        aad = b"shansuan-cloud-v1:" + account_id.bytes + b":" + associated_data
        return AESGCM(key).decrypt(value[1:13], value[13:], aad)
