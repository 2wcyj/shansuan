"""Fetch a local Android compiler toolchain from Google and Azul, with hashes."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / '.tools/android'


def fetch(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Shansuan-build/1.0'}), timeout=60)


def download(item):
    name, url, algorithm, expected = item
    archive = TOOLS / url.rsplit('/', 1)[1]
    def digest():
        with archive.open('rb') as source:
            return hashlib.file_digest(source, algorithm).hexdigest()
    if not archive.exists() or (expected and digest() != expected):
        print('Downloading ' + name, flush=True)
        temporary = archive.with_suffix('.part')
        with fetch(url) as response, temporary.open('wb') as output:
            while block := response.read(1024 * 1024):
                output.write(block)
        temporary.replace(archive)
    actual = digest()
    if expected and actual != expected:
        raise RuntimeError(name + ' archive hash mismatch')
    destination = TOOLS / name
    if not (destination / '.complete').is_file():
        destination.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(destination)
        (destination / '.complete').write_text(actual, encoding='ascii')
    with archive.open('rb') as source:
        sha256 = hashlib.file_digest(source, 'sha256').hexdigest()
    print('Ready ' + name, flush=True)
    return {'name': name, 'url': url, 'sha256': sha256, 'verified_algorithm': algorithm, 'verified_digest': actual}


def main():
    TOOLS.mkdir(parents=True, exist_ok=True)
    metadata_url = 'https://api.azul.com/metadata/v1/zulu/packages/?java_version=17&os=windows&arch=x86&archive_type=zip&java_package_type=jdk&latest=true&release_status=ga&availability_types=CA'
    with fetch(metadata_url) as response:
        packages = json.load(response)
    package = next(p for p in packages if 'win_x64' in p['name'] and '-fx-' not in p['name'] and '-crac-' not in p['name'])
    jdk_url = package['download_url']
    with fetch('https://api.azul.com/metadata/v1/zulu/packages/' + package['package_uuid']) as response:
        jdk_hash = json.load(response)['sha256_hash']
    items = [
        ('jdk', jdk_url, 'sha256', jdk_hash),
        ('platform', 'https://dl.google.com/android/repository/platform-35_r02.zip', 'sha1', '0bb560a90a7a2cbd0dd8348224d518b638fe7949'),
        ('build-tools', 'https://dl.google.com/android/repository/build-tools_r35_windows.zip', 'sha1', 'af059bb67cf7786f45ee0db85e2d24985df1b4b6'),
        ('platform-tools', 'https://dl.google.com/android/repository/platform-tools_r37.0.1-win.zip', 'sha1', 'e03e78b1d80b396f1c3358e31251cb31740e1110'),
    ]
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(download, items))
    (TOOLS / 'toolchain.json').write_text(json.dumps(results, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
