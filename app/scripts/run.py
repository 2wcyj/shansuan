"""Single local service; built assets only. Does not download dependencies."""
import argparse
import hashlib
import json
import msvcrt
import os
from pathlib import Path
import socket
import sys
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import uvicorn
from app.backend.main import create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir',default=str(Path(os.environ['LOCALAPPDATA']) / 'MyNutritionAssistant'))
    parser.add_argument('--port',type=int,default=18765)
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--no-model',action='store_true')
    args = parser.parse_args()
    root = Path(args.data_dir).resolve()
    url = f'http://127.0.0.1:{args.port}'
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url + '/api/session',timeout=1) as r:
            existing = json.load(r)
        if existing.get('app') == 'mna':
            if existing.get('data_id')!=hashlib.sha256(str(root).casefold().encode()).hexdigest():
                raise SystemExit('该端口正在使用另一个数据目录，请停止原实例或选择其他端口。')
            if not args.no_browser:
                webbrowser.open(url)
            print('应用已经在运行。',flush=True)
            return
    except OSError:
        pass
    root = Path(args.data_dir).resolve()
    root.mkdir(parents=True,exist_ok=True)
    lock = (root / 'service.lock').open('a+b')
    lock.seek(0)
    if lock.read(1) == b'':
        lock.write(b'1'); lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:
        raise SystemExit('此数据目录已被另一个应用实例使用。')
    probe = socket.socket()
    try:
        probe.bind(('127.0.0.1',args.port))
    except OSError:
        raise SystemExit('本机端口已被其他程序占用，请停止冲突程序。')
    finally:
        probe.close()
    model_process = None
    if not args.no_model:
        from app.scripts.model_runtime import start
        try:
            model_process = start()
        except RuntimeError as e:
            print(str(e),flush=True)
    try:app = create_app(root,args.port)
    except Exception:
        if model_process:model_process.terminate()
        lock.close()
        raise SystemExit('无法打开本机数据，请检查空间、权限和Windows账户密钥；原文件不会被空库覆盖。可参考使用说明从便携备份恢复。')
    server = uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=args.port,access_log=False,log_level='critical'))
    @app.post('/api/shutdown')
    def shutdown():
        server.should_exit = True
        return {'stopping':True}
    if not args.no_browser:
        import threading
        threading.Timer(1.5,lambda:webbrowser.open(url)).start()
    print('应用已启动：' + url,flush=True)
    try:
        server.run()
    finally:
        app.state.tasks.close()
        app.state.store.close()
        if model_process:
            model_process.terminate()
        lock.close()


if __name__ == '__main__':
    main()
