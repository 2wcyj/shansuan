"""Actual Windows shortcuts and cold local startup; never the personal store."""
import base64
from concurrent.futures import ThreadPoolExecutor
import http.cookiejar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request

import pytest
from PIL import Image
from app.backend.storage.database import Store
from app.backend.domain.profile import save_profile
from app.scripts import desktop, install_desktop
from app.tests.helpers import profile

ROOT=Path(__file__).resolve().parents[2]


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0))
        return s.getsockname()[1]


def settings_for(tmp_path,port=None):
    root=tmp_path/'独立测试资料'
    root.mkdir(exist_ok=True)
    return {'format':1,'port':port or free_port(),'data_dir':str(root),
            'browser_profile':str(tmp_path/'桌面配置'/'browser')}


def read_shortcut(path):
    script=r'''
[Console]::InputEncoding=[System.Text.Encoding]::UTF8
[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
$shell=New-Object -ComObject WScript.Shell
$link=$shell.CreateShortcut([Console]::In.ReadToEnd())
@{target=$link.TargetPath;arguments=$link.Arguments;icon=$link.IconLocation;cwd=$link.WorkingDirectory;description=$link.Description}|ConvertTo-Json -Compress
'''
    encoded=base64.b64encode(script.encode('utf-16le')).decode('ascii')
    r=subprocess.run([str(install_desktop.powershell_path()),'-NoProfile','-NonInteractive','-EncodedCommand',encoded],
        input=str(path),encoding='utf-8',text=True,capture_output=True,timeout=20,creationflags=desktop.NO_WINDOW)
    assert r.returncode==0,r.stderr
    return json.loads(r.stdout)


def opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def shutdown(port):
    client=opener();base=desktop.url_for(port)
    session=json.load(client.open(base+'/api/session',timeout=3))
    client.open(urllib.request.Request(base+'/api/shutdown',data=b'{}',
        headers={'Content-Type':'application/json','X-CSRF-Token':session['csrf']}),timeout=3).close()


@pytest.mark.parametrize('change',[{'format':2},{'port':True},{'port':80},{'data_dir':'relative/path'},{'browser_profile':None}])
def test_invalid_config_never_starts_or_chooses_another_store(tmp_path,change):
    settings={**settings_for(tmp_path),**change}
    path=tmp_path/'desktop.json';path.write_text(json.dumps(settings),encoding='utf-8')
    with pytest.raises(desktop.LaunchError,match='配置缺失或损坏'):
        desktop.read_settings(path)


def test_shortcut_unicode_paths_no_console_and_reinstall_does_not_reset_data(tmp_path):
    settings=settings_for(tmp_path)
    root=Path(settings['data_dir'])
    s=Store(root);s.put('test','kept',{'value':'desktop-private-marker'});s.close()
    pointer=(root/'active.json').read_bytes()
    config=tmp_path/'中文 空格 配置'/'desktop.json'
    shortcut=tmp_path/'膳算.lnk'
    result=install_desktop.install(config=config,shortcut=shortcut,data_dir=root,port=settings['port'])
    assert shortcut.is_file() and shortcut.stat().st_size>0
    actual=read_shortcut(shortcut)
    assert Path(actual['target'])==ROOT/'.venv/Scripts/pythonw.exe'
    assert actual['arguments']==subprocess.list2cmdline([str(ROOT/'app/scripts/desktop.py'),'--config',str(config)])
    assert Path(actual['cwd'])==ROOT
    assert actual['icon'].lower().endswith('app.ico,0')
    assert '膳算' in actual['description']
    saved=desktop.read_settings(result['config'])
    assert desktop.same_directory(saved['data_dir'],root)
    assert saved['requires_existing_data'] is True
    install_desktop.install(config=config,shortcut=shortcut,data_dir=root,port=settings['port'])
    assert (root/'active.json').read_bytes()==pointer
    s=Store(root)
    try:assert s.require('test','kept')['value']=='desktop-private-marker'
    finally:s.close()


def test_existing_unrelated_shortcut_is_not_overwritten_or_config_changed(tmp_path):
    shortcut=tmp_path/'膳算.lnk';config=tmp_path/'config.json'
    initial=install_desktop.shortcut_settings(shortcut,config)
    initial['target']=str(Path(os.environ['SystemRoot'])/'notepad.exe')
    initial['arguments']=''
    install_desktop.write_shortcut(initial)
    before=shortcut.read_bytes()
    config.write_text('existing-config',encoding='utf-8')
    with pytest.raises(desktop.LaunchError,match='桌面入口创建失败'):
        install_desktop.install(config=config,shortcut=shortcut,data_dir=tmp_path/'data',port=free_port())
    assert shortcut.read_bytes()==before
    assert config.read_text(encoding='utf-8')=='existing-config'


def test_wrong_or_missing_original_directory_never_creates_empty_replacement(tmp_path):
    settings=settings_for(tmp_path)
    with pytest.raises(desktop.LaunchError,match='另一个数据目录'):
        desktop.require_directory({'data_dir':str(tmp_path/'other')},settings['data_dir'])
    settings['requires_existing_data']=True
    with pytest.raises(desktop.LaunchError,match='原有个人数据入口缺失'):
        desktop.ensure_service(settings,no_model=True)
    Path(settings['data_dir']).rmdir()
    with pytest.raises(desktop.LaunchError,match='找不到原来的个人数据目录'):
        desktop.ensure_service(settings,no_model=True)
    assert not Path(settings['data_dir']).exists()


@pytest.mark.parametrize('body',[{'app':'other'},[],{'app':'mna','data_id':'wrong'}])
def test_foreign_or_unverifiable_port_is_rejected_without_launch(body,tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            value=body if self.path.endswith('session') else {'app':'mna','data_path':str(tmp_path)}
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(json.dumps(value).encode())
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with pytest.raises(desktop.LaunchError):desktop.inspect_service(server.server_port)
    finally:server.shutdown();server.server_close();thread.join(timeout=5)


def test_cold_start_reuse_reopen_and_real_encrypted_profile(tmp_path):
    settings=settings_for(tmp_path)
    root=Path(settings['data_dir']);s=Store(root)
    saved=save_profile(s,profile());generation=s.generation;s.close()
    settings['requires_existing_data']=True
    processes=[]
    try:
        for iteration in range(2):
            result=desktop.ensure_service(settings,no_model=True,timeout=30)
            assert result['started'] and result['pid']
            processes.append(result['pid'])
            assert desktop.same_directory(desktop.inspect_service(settings['port'])['data_dir'],root)
            client=opener();base=desktop.url_for(settings['port'])
            client.open(base+'/api/session').close()
            loaded=json.load(client.open(base+'/api/profile'))
            assert loaded['profile']==saved['profile']
            assert loaded['profile']['age']==30
            # Two desktop opens reuse one existing service, including concurrent opens.
            with ThreadPoolExecutor(max_workers=2) as pool:
                assert all(not r['started'] for r in pool.map(lambda _:desktop.ensure_service(settings,no_model=True),range(2)))
            with pytest.raises(desktop.LaunchError,match='另一个数据目录'):
                desktop.ensure_service({**settings,'data_dir':str(tmp_path/'wrong')},no_model=True)
            assert not (tmp_path/'wrong').exists()
            # The shipped name and static assets are actually served.
            html=client.open(base+'/').read().decode('utf-8')
            assert '<title>膳算</title>' in html
            manifest=json.load(client.open(base+'/manifest.webmanifest'))
            assert manifest['name']=='膳算' and manifest['display']=='standalone'
            for asset in ['/icon.svg','/icon-192.png','/icon-512.png','/favicon.ico']:
                assert client.open(base+asset).status==200
            shutdown(settings['port'])
            # A service stays visible briefly while it releases the store lock.
            import ctypes
            from ctypes import wintypes
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
            kernel.OpenProcess.restype=wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
            kernel.CloseHandle.argtypes=[wintypes.HANDLE]
            handle=kernel.OpenProcess(0x100000,False,result['pid'])
            if handle:
                try:assert kernel.WaitForSingleObject(handle,15000)==0
                finally:kernel.CloseHandle(handle)
        s=Store(root)
        try:assert s.generation==generation and s.require('profile','self')==saved['profile']
        finally:s.close()
    finally:
        try:
            if desktop.inspect_service(settings['port']):shutdown(settings['port'])
        except (OSError,desktop.LaunchError):pass


def test_icon_and_app_window_command_are_local_and_named_correctly(tmp_path):
    settings=settings_for(tmp_path)
    command=desktop.app_command(desktop.find_edge(),settings)
    assert '--app='+desktop.url_for(settings['port'])+'/' in command
    assert '--user-data-dir='+settings['browser_profile'] in command
    assert '--disable-sync' in command
    with Image.open(ROOT/'app/resources/app.ico') as icon:
        assert (16,16) in icon.ico.sizes() and (256,256) in icon.ico.sizes()
    with Image.open(ROOT/'app/frontend/public/icon-512.png') as icon:
        assert icon.size==(512,512)
    assert desktop.NAME=='膳算'


def test_reset_browser_connections_do_not_block_service_exit(tmp_path):
    """A closed browser must not strand Windows' HTTP listener during shutdown."""
    settings=settings_for(tmp_path)
    proc=subprocess.Popen([sys.executable,str(ROOT/'app/scripts/run.py'),
        '--data-dir',settings['data_dir'],'--port',str(settings['port']),
        '--no-browser','--no-model'],cwd=ROOT,env={**os.environ,'PYTHONUTF8':'1'},
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=desktop.NO_WINDOW)
    connections=[]
    try:
        until=time.monotonic()+15
        while time.monotonic()<until:
            assert proc.poll() is None,'test service exited during startup'
            if desktop.inspect_service(settings['port']):break
            time.sleep(.1)
        else:pytest.fail('test service did not start')
        for _ in range(20):
            connection=socket.create_connection(('127.0.0.1',settings['port']),timeout=3)
            connections.append(connection)
            connection.setsockopt(socket.SOL_SOCKET,socket.SO_LINGER,struct.pack('HH',1,0))
            connection.sendall((f'GET /api/session HTTP/1.1\r\nHost: 127.0.0.1:{settings["port"]}\r\n\r\n').encode())
            assert b'200 OK' in connection.recv(4096)
        shutdown(settings['port'])
        for connection in connections:connection.close()
        stdout,stderr=proc.communicate(timeout=15)
        assert proc.returncode==0,(stdout+stderr).decode('utf-8',errors='replace')
        assert b'Exception in callback' not in stderr,stderr.decode('utf-8',errors='replace')
        assert desktop.inspect_service(settings['port']) is None
        s=Store(Path(settings['data_dir']))
        try:assert s.conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        finally:s.close()
    finally:
        for connection in connections:connection.close()
        if proc.poll() is None:
            proc.terminate();proc.communicate(timeout=10)
