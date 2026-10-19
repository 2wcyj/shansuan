"""Create a private, encrypted pairing configuration for the LAN gateway."""
import argparse
import ctypes
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import tempfile
from ctypes import wintypes

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def _protect(data):
    if os.name != 'nt':
        raise RuntimeError('手机连接凭据只支持 Windows DPAPI 加密')

    class DataBlob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]

    raw = (ctypes.c_byte * len(data)).from_buffer_copy(data)
    source = DataBlob(len(data), raw)
    target = DataBlob()
    crypt = ctypes.windll.crypt32.CryptProtectData
    crypt.argtypes = [ctypes.POINTER(DataBlob), wintypes.LPCWSTR, ctypes.POINTER(DataBlob),
                      ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob)]
    crypt.restype = wintypes.BOOL
    if not crypt(ctypes.byref(source), 'Shansuan mobile pairing', None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


def prepare_connection(private_dir, share_dir, host, reset=False):
    address = ipaddress.ip_address(host)
    if address.version != 4 or not any(address in ipaddress.ip_network(n) for n in
            ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
        raise ValueError('只能使用明确指定的家庭或办公局域网 IPv4 地址')
    private = Path(private_dir).resolve()
    share = Path(share_dir).resolve()
    private.mkdir(parents=True, exist_ok=True)
    share.mkdir(parents=True, exist_ok=True)
    state_path = private / 'connection.enc'
    certificate_path = private / 'server.crt'
    key_path = private / 'server.key'
    state = None
    if state_path.exists() and not reset:
        # DPAPI ciphertext is intentionally opaque; the stable token is retained in a
        # separate DPAPI-protected payload and can only be unwrapped by this Windows user.
        state = _unprotect(state_path.read_bytes())
        state = json.loads(state.decode('utf-8'))
    if state is None or state.get('host') != str(address) or reset:
        token = secrets.token_urlsafe(48)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, str(address))])
        certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc))
            .not_valid_after(datetime.now(timezone.utc)+timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(address)]), critical=False)
            .sign(key, hashes.SHA256()))
        certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(token.encode('utf-8'))))
        state = {'host': str(address), 'token': token}
        state_path.write_bytes(_protect(json.dumps(state, separators=(',', ':')).encode('utf-8')))
    certificate = x509.load_pem_x509_certificate(certificate_path.read_bytes())
    fingerprint = certificate.fingerprint(hashes.SHA256()).hex()
    exported = {'format': 1, 'url': f'https://{address}:18766', 'token': state['token'], 'fingerprint': fingerprint}
    target = share / '电脑连接.shansuan'
    fd, temporary = tempfile.mkstemp(prefix='.shansuan-', dir=share)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(exported, output, ensure_ascii=False, indent=2)
            output.flush(); os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    return {'token': state['token'], 'fingerprint': fingerprint, 'url': exported['url'], 'file': str(target)}


def _unprotect(data):
    if os.name != 'nt':
        raise RuntimeError('手机连接凭据只支持 Windows DPAPI 解密')

    class DataBlob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]

    raw = (ctypes.c_byte * len(data)).from_buffer_copy(data)
    source = DataBlob(len(data), raw); target = DataBlob()
    crypt = ctypes.windll.crypt32.CryptUnprotectData
    crypt.argtypes = [ctypes.POINTER(DataBlob), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(DataBlob),
                      ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob)]
    crypt.restype = wintypes.BOOL
    if not crypt(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


def main():
    parser = argparse.ArgumentParser(description='准备膳算安卓局域网连接')
    parser.add_argument('--host', required=True, help='电脑当前 Wi-Fi 的局域网 IPv4 地址')
    parser.add_argument('--reset', action='store_true', help='重新配对并撤销旧连接文件')
    args = parser.parse_args()
    base = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'ShansuanMobile'
    result = prepare_connection(base / 'private', Path.home() / 'Desktop' / '膳算手机连接', args.host, args.reset)
    print(f"手机连接文件已生成：{result['file']}\n访问地址：{result['url']}\n证书指纹：{result['fingerprint']}")


def lan_ipv4_addresses():
    found = set()
    for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_DGRAM):
        candidate = info[4][0]
        address = ipaddress.ip_address(candidate)
        if any(address in ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
            found.add(candidate)
    return sorted(found)


def launch(host_override=None):
    from app.backend.mobile import private_ipv4
    candidates = lan_ipv4_addresses()
    if host_override:
        candidates = [host_override]
    if len(candidates) != 1:
        raise SystemExit('检测到多个或没有可用的局域网地址：' + ('、'.join(candidates) if candidates else '请连接 Wi-Fi') + '。请运行“启动手机连接.cmd --host 局域网IPv4”明确选择。')
    host = candidates[0]
    if not private_ipv4(host):
        raise SystemExit('未检测到允许的局域网地址。')
    try:
        import urllib.request
        with urllib.request.urlopen(f'http://127.0.0.1:18765/api/status', timeout=3) as response:
            status = json.load(response)
    except Exception:
        raise SystemExit('请先启动电脑上的膳算，再启动手机连接。') from None
    root = status.get('data_path')
    if not root or not Path(root).is_dir():
        raise SystemExit('无法确认膳算本机数据目录；为保护资料，已停止手机连接。')
    from app.backend.mobile import create_mobile_app
    import uvicorn
    private = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'ShansuanMobile' / 'private'
    share = Path.home() / 'Desktop' / '膳算手机连接'
    config = prepare_connection(private, share, host)
    print(f"手机连接已启动：{config['url']}\n请将桌面上的连接文件私下导入膳算安卓应用。电脑和手机需连接同一 Wi-Fi。", flush=True)
    uvicorn.run(create_mobile_app(host, config['token']), host=host, port=18766,
        ssl_certfile=str(private / 'server.crt'), ssl_keyfile=str(private / 'server.key'),
        access_log=False, log_level='warning')


if __name__ == '__main__':
    if os.environ.get('SHANSUAN_MOBILE_LAUNCH') == '1':
        parser = argparse.ArgumentParser(description='启动膳算手机局域网连接')
        parser.add_argument('--host', help='电脑当前 Wi-Fi 的局域网 IPv4 地址（多个网卡时指定）')
        launch(parser.parse_args().host)
    else:
        main()
