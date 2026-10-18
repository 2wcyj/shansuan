"""Release checks exercise actual resources and a clean offline Python install."""
from pathlib import Path
import hashlib,json,os,subprocess,sys
ROOT=Path(__file__).resolve().parents[2]

def test_release_resources_model_hash_and_complete_acceptance():
    m=json.loads((ROOT/'app/resources/delivery-manifest.json').read_text(encoding='utf-8'));assert m['model']=='qwen3-vl:2b-instruct'
    for item in m['files']:
        path=ROOT/item['path'];assert path.is_file(),item
        assert path.stat().st_size==item['bytes']
        with path.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==item['sha256'],item['path']
    assert (ROOT/'app/frontend/dist/index.html').is_file()
    for name in ['启动.cmd','停止.cmd','测试.cmd','docs/user-guide.md','docs/installation.md','docs/acceptance-results.md']:
        assert (ROOT/name).is_file()
    acceptance=(ROOT/'docs/acceptance-results.md').read_text(encoding='utf-8')
    for n in range(1,42):assert f'| A{n:02d} |' in acceptance
    assert '待人工验收' in acceptance and 'A34' in acceptance

def test_new_environment_install_from_local_wheels_and_open_encrypted_store(tmp_path):
    env={**os.environ,'PYTHONUTF8':'1','PIP_NO_INDEX':'1','PIP_DISABLE_PIP_VERSION_CHECK':'1','PYTHONNOUSERSITE':'1','HTTP_PROXY':'http://127.0.0.1:9','HTTPS_PROXY':'http://127.0.0.1:9'}
    venv=tmp_path/'offline-env'
    r=subprocess.run([sys.executable,'-m','venv',str(venv)],env=env,capture_output=True,timeout=60);assert r.returncode==0,r.stderr.decode('utf-8',errors='replace')
    python=venv/'Scripts/python.exe';r=subprocess.run([str(python),'-m','pip','install','--no-index','--find-links',str(ROOT/'.tools/wheels'),'-r',str(ROOT/'requirements.lock.txt')],env=env,capture_output=True,timeout=120)
    assert r.returncode==0,r.stdout.decode('utf-8',errors='replace')+r.stderr.decode('utf-8',errors='replace')
    script="from app.backend.main import create_app;import sys;from pathlib import Path;a=create_app(Path(sys.argv[1]));s=a.state.store;s.put('test','offline',{'v':'offline-private-marker'});a.state.tasks.close();s.close();a=create_app(Path(sys.argv[1]));assert a.state.store.require('test','offline')['v']=='offline-private-marker';a.state.tasks.close();a.state.store.close();print('offline-import-and-reopen-ok')"
    r=subprocess.run([str(python),'-c',script,str(tmp_path/'offline-data')],cwd=ROOT,env=env,capture_output=True,timeout=30)
    assert r.returncode==0,r.stderr.decode('utf-8',errors='replace');assert b'offline-import-and-reopen-ok' in r.stdout
    for p in (tmp_path/'offline-data').rglob('*'):
        if p.is_file():assert b'offline-private-marker' not in p.read_bytes()
