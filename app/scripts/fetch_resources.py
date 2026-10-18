"""Install-time public downloads only. Never used by the running application."""
import io
import json
from pathlib import Path
import shutil
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / '.tools'
TOOLS.mkdir(exist_ok=True)


def fetch(url, path):
    req = urllib.request.Request(url, headers={'User-Agent': 'MyNutritionAssistant-setup'})
    with urllib.request.urlopen(req, timeout=60) as response, path.open('wb') as target:
        shutil.copyfileobj(response, target)


class RangeReader(io.RawIOBase):
    def __init__(self, url):
        req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'MyNutritionAssistant-setup'})
        with urllib.request.urlopen(req, timeout=60) as r:
            self.url = r.url
            self.length = int(r.headers['Content-Length'])
        self.position = 0

    def seekable(self): return True
    def tell(self): return self.position
    def seek(self, offset, whence=0):
        self.position = offset if whence == 0 else (self.position if whence == 1 else self.length) + offset
        return self.position

    def read(self, n=-1):
        if n == 0: return b''
        end = self.length - 1 if n < 0 else min(self.length - 1, self.position + n - 1)
        req = urllib.request.Request(self.url, headers={'Range': f'bytes={self.position}-{end}', 'User-Agent': 'MyNutritionAssistant-setup'})
        with urllib.request.urlopen(req, timeout=120) as r:
            if r.status != 206:
                raise RuntimeError('Release server does not support partial download')
            data = r.read()
        self.position += len(data)
        return data


def ollama():
    req = urllib.request.Request('https://api.github.com/repos/ollama/ollama/releases/latest', headers={'User-Agent': 'MyNutritionAssistant-setup'})
    release = json.load(urllib.request.urlopen(req, timeout=30))
    asset = next(a for a in release['assets'] if a['name'] == 'ollama-windows-amd64.zip')
    dest = TOOLS / 'ollama'
    dest.mkdir(exist_ok=True)
    with zipfile.ZipFile(RangeReader(asset['browser_download_url'])) as archive:
        names = [n for n in archive.namelist() if not any(x in n.lower() for x in ('cuda', 'vulkan', 'rocm', 'mlx')) and not n.endswith('/')]
        print('CPU runtime files:', names, flush=True)
        for name in names:
            target = (dest / name).resolve()
            if not target.is_relative_to(dest.resolve()): raise ValueError('Invalid release path')
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as source, target.open('wb') as out:
                shutil.copyfileobj(source, out)
            print(name, target.stat().st_size, flush=True)
    (dest / 'release.json').write_text(json.dumps({'tag': release['tag_name'], 'source': asset['browser_download_url']}), encoding='utf-8')


def food():
    path = TOOLS / 'sr-legacy-2018.zip'
    fetch('https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip', path)
    with zipfile.ZipFile(path) as z:
        print(z.namelist(), flush=True)
        z.extractall(TOOLS / 'usda')
    print('USDA downloaded', path.stat().st_size, flush=True)


if __name__ == '__main__':
    import sys
    {'ollama': ollama, 'food': food}[sys.argv[1]]()
