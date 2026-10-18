"""Install a per-user desktop entry using existing Windows/Edge resources."""
import argparse
import base64
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.scripts.desktop import NAME, LaunchError, default_config, find_edge, inspect_service, same_directory


def desktop_folder():
    buffer = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buffer) != 0:
        raise LaunchError('无法找到当前账户的桌面文件夹。')
    return Path(buffer.value)


def choose_data_dir(port, supplied=None):
    running = inspect_service(port)
    if supplied is not None:
        root = Path(supplied).resolve()
        if running and not same_directory(root, running['data_dir']):
            raise LaunchError('指定的目录与当前运行中的资料不同，未修改桌面入口。')
    elif running:
        root = Path(running['data_dir'])
    else:
        candidates = [Path(os.environ['LOCALAPPDATA']) / 'MyNutritionAssistant']
        packages = Path.home() / 'AppData/Local/Packages'
        candidates.extend(packages.glob('OpenAI.Codex_*/LocalCache/Local/MyNutritionAssistant'))
        existing = []
        for path in candidates:
            if (path / 'active.json').is_file() and not any(same_directory(path, p) for p in existing):
                existing.append(path.resolve())
        if len(existing) > 1:
            raise LaunchError('发现多个个人数据目录，请使用 --data-dir 明确指定原来的目录，避免打开错误档案。')
        root = existing[0] if existing else candidates[0].resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def shortcut_settings(shortcut, config):
    return {'path': str(Path(shortcut).resolve()), 'target': str(ROOT / '.venv/Scripts/pythonw.exe'),
        'arguments': subprocess.list2cmdline([str(ROOT / 'app/scripts/desktop.py'), '--config', str(config.resolve())]),
        'working_directory': str(ROOT), 'icon': str(ROOT / 'app/resources/app.ico'),
        'description': '膳算 · 个人营养与生活管理 · 本机私有'}


def powershell_path():
    # Explorer and embedded terminals need not have the same PATH.
    path = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    if not path.is_file():
        raise LaunchError('找不到Windows内置PowerShell，无法创建桌面入口。')
    return path


def write_shortcut(settings):
    # Structured stdin keeps Unicode paths, quotes and spaces out of shell code.
    script = r'''
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$settings = [Console]::In.ReadToEnd() | ConvertFrom-Json
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($settings.path)
if ((Test-Path -LiteralPath $settings.path) -and $link.TargetPath -and
    -not ($link.TargetPath -eq $settings.target -and $link.Arguments -eq $settings.arguments)) {
    throw '同名桌面入口已存在且指向其他程序，未覆盖。'
}
$link.TargetPath = $settings.target
$link.Arguments = $settings.arguments
$link.WorkingDirectory = $settings.working_directory
$link.IconLocation = $settings.icon + ',0'
$link.Description = $settings.description
$link.WindowStyle = 1
$link.Save()
'''
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    result = subprocess.run([str(powershell_path()), '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
        input=json.dumps(settings, ensure_ascii=False), text=True, encoding='utf-8', capture_output=True,
        creationflags=0x08000000, timeout=20)
    if result.returncode:
        raise LaunchError('桌面入口创建失败：' + result.stderr.strip())


def install(*, config=None, shortcut=None, data_dir=None, port=18765):
    find_edge()
    for required in ['.venv/Scripts/pythonw.exe', 'app/frontend/dist/index.html', 'app/resources/app.ico']:
        if not (ROOT / required).is_file():
            raise LaunchError('缺少应用文件：' + required)
    config = Path(config) if config is not None else default_config()
    shortcut = Path(shortcut) if shortcut is not None else desktop_folder() / (NAME + '.lnk')
    if not 1024 <= port <= 65535:
        raise LaunchError('本机端口必须在1024至65535之间。')
    root = choose_data_dir(port, data_dir)
    settings = {'format': 1, 'data_dir': str(root), 'port': port,
        'browser_profile': str((config.parent / 'browser').resolve()),
        'requires_existing_data': (root / 'active.json').is_file()}
    config.parent.mkdir(parents=True, exist_ok=True)
    # Verify/write the link first; a naming conflict must not change an existing
    # installation's configuration. No personal records are copied or migrated.
    write_shortcut(shortcut_settings(shortcut, config))
    temporary = config.with_suffix('.tmp')
    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, config)
    return {'shortcut': str(shortcut), 'config': str(config), 'data_dir': str(root)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--port', type=int, default=18765)
    args = parser.parse_args()
    try:
        installed = install(data_dir=args.data_dir, port=args.port)
        print('桌面入口已创建：' + installed['shortcut'])
        print('继续使用个人数据：' + installed['data_dir'])
    except (LaunchError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
