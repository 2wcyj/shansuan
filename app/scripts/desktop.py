"""Open the local application in a dedicated Edge window, without a console.

Uses the existing encrypted store and backend. No runtime download or cloud app.
The installed shortcut passes an absolute config path, so launching from Explorer
does not change the data location when its environment differs from Codex.
"""
import argparse
import ctypes
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
NAME = '膳算'
NO_WINDOW = 0x08000000


class LaunchError(RuntimeError):
    pass


def default_config():
    return Path(os.environ['LOCALAPPDATA']) / 'MyNutritionAssistantDesktop' / 'desktop.json'


def read_settings(path):
    try:
        settings = json.loads(Path(path).read_text(encoding='utf-8'))
        if settings['format'] != 1 or type(settings['port']) is not int or not 1024 <= settings['port'] <= 65535:
            raise ValueError('invalid desktop configuration')
        for key in ['data_dir', 'browser_profile']:
            if not isinstance(settings[key], str) or not Path(settings[key]).is_absolute():
                raise ValueError('absolute paths required')
        return settings
    except (OSError, ValueError, KeyError, TypeError):
        raise LaunchError('桌面入口配置缺失或损坏，请双击项目中的“安装桌面应用.cmd”重新创建。') from None


def find_edge():
    candidates = [Path(os.environ.get(key, '')) / suffix for key, suffix in [
        ('PROGRAMFILES(X86)', 'Microsoft/Edge/Application/msedge.exe'),
        ('PROGRAMFILES', 'Microsoft/Edge/Application/msedge.exe'),
        ('LOCALAPPDATA', 'Microsoft/Edge/Application/msedge.exe'),
    ]]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise LaunchError('没有找到 Microsoft Edge。请安装或修复这台电脑的 Edge 后重试；原有个人资料不受影响。')


def url_for(port):
    return f'http://127.0.0.1:{port}'


def inspect_service(port):
    # Windows can take longer than the HTTP timeout to reject a connection to
    # an unused port. A successful exclusive bind proves no service is there.
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(('127.0.0.1', port))
        except OSError:
            pass
        else:
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    try:
        with opener.open(url_for(port) + '/api/session', timeout=1) as response:
            session = json.load(response)
        if not isinstance(session, dict) or session.get('app') != 'mna':
            raise LaunchError('本机端口被其他程序占用，请关闭冲突程序后重试。')
        with opener.open(url_for(port) + '/api/status', timeout=1) as response:
            status = json.load(response)
        if not isinstance(status, dict) or status.get('app') != 'mna':
            raise LaunchError('本机端口未返回正确的应用响应，请关闭冲突程序后重试。')
        root = Path(status['data_path']).resolve()
        if session.get('data_id') != hashlib.sha256(str(root).casefold().encode()).hexdigest():
            raise LaunchError('本机服务的数据目录校验失败，已停止打开，避免连接错误的资料。')
        return {'data_dir': str(root), 'session': session}
    except urllib.error.HTTPError:
        raise LaunchError('本机端口未返回正确的应用响应，请关闭冲突程序后重试。') from None
    except urllib.error.URLError as error:
        if isinstance(error.reason, ConnectionRefusedError) or getattr(error.reason, 'winerror', None) == 10061:
            return None
        raise LaunchError('无法确认本机服务状态，请稍后重试；原有资料未改动。') from None
    except (ValueError, KeyError, TypeError, TimeoutError, OSError):
        raise LaunchError('本机端口暂未就绪或被其他程序占用，请稍后重试。') from None


def same_directory(left, right):
    try:
        if Path(left).samefile(right):
            return True
    except OSError:
        pass
    return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(Path(right).resolve()))


def require_directory(service, data_dir):
    if service and not same_directory(service['data_dir'], data_dir):
        raise LaunchError('当前端口正在使用另一个数据目录。请先停止原实例；不会替换或新建你的个人资料。')
    return service


def ensure_service(settings, *, no_model=False, timeout=60):
    port = settings['port']
    root = Path(settings['data_dir']).resolve()
    existing = require_directory(inspect_service(port), root)
    if existing:
        return {'started': False, 'pid': None}
    python = ROOT / '.venv/Scripts/python.exe'
    if not python.is_file() or not (ROOT / 'app/frontend/dist/index.html').is_file():
        raise LaunchError('应用文件或本地运行环境缺失，请恢复原项目文件夹；个人资料不会被空库覆盖。')
    # The installed data directory must still exist. Never silently create an
    # empty replacement when a disk/directory disappears after installation.
    if not root.is_dir():
        raise LaunchError('找不到原来的个人数据目录，请恢复目录后再打开。不会自动创建空白档案。')
    if settings.get('requires_existing_data') and not (root / 'active.json').is_file():
        raise LaunchError('原有个人数据入口缺失，请从备份恢复后再打开。不会自动创建空白档案。')
    logs = Path(settings['browser_profile']).parent / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / 'startup.log'
    if log_path.exists() and log_path.stat().st_size > 1024 * 1024:
        log_path.replace(logs / 'startup.previous.log')
    command = [str(python), str(ROOT / 'app/scripts/run.py'), '--data-dir', str(root),
               '--port', str(port), '--no-browser']
    if no_model:
        command.append('--no-model')
    with log_path.open('ab') as log:
        process = subprocess.Popen(command, cwd=ROOT, env={**os.environ, 'PYTHONUTF8': '1'},
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=NO_WINDOW)
    until = time.monotonic() + timeout
    try:
        while time.monotonic() < until:
            service = require_directory(inspect_service(port), root)
            if service:
                return {'started': process.poll() is None, 'pid': process.pid}
            if process.poll() is not None:
                raise LaunchError('本地服务启动失败，请检查磁盘空间和文件权限。诊断日志位于桌面应用配置目录的 logs 文件夹。')
            time.sleep(.2)
        raise LaunchError('启动等待超时，请稍后重新打开。原有资料已保留；可检查桌面应用配置目录中的启动日志。')
    except Exception:
        # Only stop this launch's child; never interrupt an existing instance.
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        raise


def app_command(edge, settings):
    return [str(edge), '--app=' + url_for(settings['port']) + '/',
        '--user-data-dir=' + settings['browser_profile'], '--no-first-run',
        '--no-default-browser-check', '--disable-background-networking',
        '--disable-component-update', '--disable-sync', '--window-size=1040,900']


def launch(settings, *, no_model=False, timeout=60):
    edge = find_edge()
    service = ensure_service(settings, no_model=no_model, timeout=timeout)
    Path(settings['browser_profile']).mkdir(parents=True, exist_ok=True)
    subprocess.Popen(app_command(edge, settings), cwd=ROOT, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    return service


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=default_config())
    args = parser.parse_args()
    try:
        launch(read_settings(args.config))
    except (LaunchError, OSError) as error:
        ctypes.windll.user32.MessageBoxW(None, str(error), NAME + ' · 无法打开', 0x10)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
