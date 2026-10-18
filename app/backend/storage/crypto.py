"""Authenticated file encryption and Windows user-scoped key protection."""
import ctypes
from ctypes import wintypes
import os
import struct
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b'MNA1'


class CryptoError(ValueError):
    pass


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def dpapi(data: bytes, decrypt=False) -> bytes:
    if os.name != 'nt':
        raise RuntimeError('本版本需要Windows账户密钥保护')
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        ok = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    else:
        ok = crypt.CryptProtectData(ctypes.byref(source), 'Nutrition key', None, None, None, 1, ctypes.byref(target))
    if not ok:
        raise CryptoError('Windows账户无法解开密钥，请从便携备份恢复')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def encrypt(key: bytes, data: bytes, context=b'mna-file-v1') -> bytes:
    nonce = os.urandom(12)
    return MAGIC + nonce + AESGCM(key).encrypt(nonce, data, context)


def decrypt(key: bytes, data: bytes, context=b'mna-file-v1') -> bytes:
    if len(data) < 32 or data[:4] != MAGIC:
        raise CryptoError('文件格式无效')
    try:
        return AESGCM(key).decrypt(data[4:16], data[16:], context)
    except Exception as e:
        raise CryptoError('文件校验失败或密钥不正确') from e


def password_key(password: str, salt: bytes) -> bytes:
    if not 10 <= len(password) <= 1024:
        raise CryptoError('备份密码需要10至1024个字符')
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode('utf-8'))


def seal_backup(password: str, payload: bytes) -> bytes:
    salt = os.urandom(16)
    return b'MNAB' + struct.pack('>I', 1) + salt + encrypt(password_key(password, salt), payload, b'mna-backup-v1')


def open_backup(password: str, data: bytes) -> bytes:
    if len(data) < 56 or data[:8] != b'MNAB\x00\x00\x00\x01':
        raise CryptoError('不支持的备份格式或版本')
    try:
        return decrypt(password_key(password, data[8:24]), data[24:], b'mna-backup-v1')
    except CryptoError as e:
        raise CryptoError('备份密码错误或文件已损坏') from e
