"""Pinned, local-only model runtime; setup downloads are a separate operation."""
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
MODEL = 'qwen3-vl:2b-instruct'
BASE = 'http://127.0.0.1:11439'


def status():
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(BASE + '/api/tags', timeout=2) as response:
            return json.load(response)
    except (OSError, ValueError):
        return None


def start():
    if status() is not None:
        return None
    runtime = ROOT / '.tools/ollama/ollama.exe'
    if not runtime.is_file():
        raise RuntimeError('缺少本地模型运行时，请先完成安装准备')
    env = os.environ.copy()
    env.update(OLLAMA_HOST='127.0.0.1:11439', OLLAMA_MODELS=str(ROOT / '.tools/models'),
               OLLAMA_NO_CLOUD='1', OLLAMA_CONTEXT_LENGTH='4096', OLLAMA_NUM_PARALLEL='1',
               OLLAMA_MAX_LOADED_MODELS='1', HTTP_PROXY='http://127.0.0.1:9',
               HTTPS_PROXY='http://127.0.0.1:9', ALL_PROXY='http://127.0.0.1:9',
               NO_PROXY='127.0.0.1,localhost')
    process = subprocess.Popen([str(runtime), 'serve'], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=0x08000200)
    for _ in range(40):
        if status() is not None:
            return process
        if process.poll() is not None:
            raise RuntimeError('本地模型启动失败，请检查内存与端口')
        time.sleep(.5)
    process.terminate()
    raise RuntimeError('本地模型启动超时，可先使用手动记餐')


if __name__ == '__main__':
    start()
    print(json.dumps(status(), ensure_ascii=True))
