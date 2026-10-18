"""Repair stalled install-time range transfers, verifying the registry digest."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time
import urllib.request
import argparse

ROOT=Path(__file__).resolve().parents[2]
DIGEST=argparse.ArgumentParser()
DIGEST.add_argument('digest')
DIGEST=DIGEST.parse_args().digest
if len(DIGEST)!=64 or any(c not in '0123456789abcdef' for c in DIGEST):
    raise ValueError('Invalid SHA256 digest')
BLOBS=ROOT/'.tools/models/blobs'
PART=BLOBS/('sha256-'+DIGEST+'-partial')
URL='https://registry.ollama.ai/v2/library/qwen3-vl/blobs/sha256:'+DIGEST


def transfer(path):
    state=json.loads(path.read_text())
    pos=state['Offset']+state['Completed']
    end=state['Offset']+state['Size']
    while pos<end:
        stop=min(pos+8*1024*1024,end)-1
        for attempt in range(5):
            try:
                request=urllib.request.Request(URL,headers={'Range':f'bytes={pos}-{stop}'})
                with urllib.request.urlopen(request,timeout=40) as response:
                    if response.status!=206 or not response.headers.get('Content-Range','').startswith(f'bytes {pos}-'):
                        raise RuntimeError('Invalid range response')
                    data=response.read()
                if len(data)!=stop-pos+1: raise RuntimeError('Truncated transfer')
                with PART.open('r+b') as target:
                    target.seek(pos); target.write(data)
                pos=stop+1
                state['Completed']=pos-state['Offset']
                path.write_text(json.dumps(state))
                print('chunk',state['N'],state['Completed'],'/',state['Size'],flush=True)
                break
            except Exception as error:
                print('retry',state['N'],type(error).__name__,flush=True)
                if attempt==4: raise
                time.sleep(1)
    return state['N']


if __name__=='__main__':
    paths=list(BLOBS.glob('sha256-'+DIGEST+'-partial-*'))
    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(transfer,paths))
    with PART.open('rb') as f:
        assert hashlib.file_digest(f,'sha256').hexdigest()==DIGEST,'Model checksum mismatch'
    PART.replace(BLOBS/('sha256-'+DIGEST))
    for p in paths:p.unlink()
    print('SHA256 verified',flush=True)
