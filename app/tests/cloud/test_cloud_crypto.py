"""Authenticated encryption and per-account key binding for cloud payloads."""
import pytest


class FakeKeyService:
    def check(self):
        return True

    def wrap_key(self, account_id, key):
        return account_id.bytes + key

    def unwrap_key(self, account_id, wrapped):
        if wrapped[:16] != account_id.bytes:
            raise ValueError("Wrapped key belongs to another account")
        return wrapped[16:]


def test_payload_is_authenticated_and_bound_to_account():
    from app.backend.cloud.crypto import CloudCrypto
    from uuid import uuid4
    service = CloudCrypto(FakeKeyService())
    owner, stranger = uuid4(), uuid4()
    key, wrapped = service.create_data_key(owner)

    ciphertext = service.encrypt(owner, key, b"sensitive health data")
    assert ciphertext != b"sensitive health data"
    assert service.decrypt(owner, key, ciphertext) == b"sensitive health data"
    with pytest.raises(Exception):
        service.decrypt(stranger, key, ciphertext)
    with pytest.raises(Exception):
        service.decrypt(owner, b"x" * 32, ciphertext)
    with pytest.raises(ValueError):
        service.unwrap_data_key(stranger, wrapped)


def test_tampered_ciphertext_is_rejected():
    from app.backend.cloud.crypto import CloudCrypto
    from uuid import uuid4
    service = CloudCrypto(FakeKeyService())
    owner = uuid4()
    key, _ = service.create_data_key(owner)
    ciphertext = bytearray(service.encrypt(owner, key, b"profile"))
    ciphertext[-1] ^= 1
    with pytest.raises(Exception):
        service.decrypt(owner, key, bytes(ciphertext))


def test_key_manager_must_return_a_bounded_wrapped_key():
    from app.backend.cloud.crypto import CloudCrypto
    from uuid import uuid4
    class InvalidKeyManager:
        def wrap_key(self, account_id, key): return 'plain-text-key'
        def unwrap_key(self, account_id, wrapped_key): return b'k' * 32
    with pytest.raises(ValueError, match='wrapped data key'):
        CloudCrypto(InvalidKeyManager()).create_data_key(uuid4())
