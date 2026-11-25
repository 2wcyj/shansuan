"""Deployment contract: the example environment and Dockerfile stay Huawei-only."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENV_EXAMPLE = ROOT / 'deploy' / 'cloud' / '.env.example'
DOCKERFILE = ROOT / 'deploy' / 'cloud' / 'Dockerfile'
REQUIREMENTS = ROOT / 'deploy' / 'cloud' / 'requirements.lock.txt'


def _keys():
    keys = {}
    for line in ENV_EXAMPLE.read_text(encoding='utf-8').splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in stripped:
            continue
        name, value = stripped.split('=', 1)
        keys[name.strip()] = value.strip()
    return keys


def test_example_environment_covers_every_required_service():
    keys = _keys()
    required = {
        'DATABASE_URL', 'MIGRATION_DATABASE_URL', 'SESSION_SIGNING_KEY', 'FRONTEND_ORIGINS',
        'REDIS_URL', 'KMS_PROVIDER', 'KMS_REGION_ID', 'KMS_KEY_ID',
        'HUAWEI_CLOUD_PROJECT_ID', 'HUAWEI_CLOUD_ACCESS_KEY_ID',
        'HUAWEI_CLOUD_SECRET_ACCESS_KEY',
        'OBS_PROVIDER', 'OBS_REGION_ID', 'OBS_BUCKET',
    }
    assert required <= keys.keys()
    assert keys['KMS_PROVIDER'] == 'huawei'
    assert keys['OBS_PROVIDER'] == 'huawei'


def test_example_environment_has_no_legacy_provider_or_real_secret():
    keys = _keys()
    assert not any(name.startswith('ALIBABA_CLOUD_') for name in keys)
    assert not any(name.startswith('OSS_') and name != 'OBS_PROVIDER' for name in keys)
    # Every non-empty secret-bearing value must be an obvious placeholder.
    for name, value in keys.items():
        if name in {'APP_ENV', 'KMS_PROVIDER', 'KMS_REGION_ID', 'OBS_PROVIDER', 'OBS_REGION_ID'}:
            continue
        assert 'REPLACE' in value or name in {'FRONTEND_ORIGINS'}, f'{name} lacks a placeholder'
        if name in {'DATABASE_URL', 'MIGRATION_DATABASE_URL', 'REDIS_URL'}:
            assert 'REPLACE_PASSWORD' in value


def test_cloud_image_installs_and_imports_huawei_sdks_only():
    requirements = REQUIREMENTS.read_text(encoding='utf-8')
    assert 'huaweicloudsdkcore==' in requirements
    assert 'huaweicloudsdkkms==' in requirements
    assert 'esdk-obs-python==' in requirements
    assert 'redis==' in requirements
    assert 'oss2' not in requirements
    assert 'alibabacloud' not in requirements
    assert 'aliyun-python-sdk' not in requirements
    dockerfile = DOCKERFILE.read_text(encoding='utf-8')
    assert 'huaweicloudsdkkms' in dockerfile
    assert 'import obs' in dockerfile
    assert 'import redis' in dockerfile
    assert 'oss2' not in dockerfile
    assert 'alibabacloud' not in dockerfile

def test_same_origin_deployment_assets_are_present():
    deploy = ROOT / 'deploy' / 'huawei'
    nginx = (deploy / 'nginx.conf').read_text(encoding='utf-8')
    compose = (deploy / 'docker-compose.yml').read_text(encoding='utf-8')
    script = (deploy / 'build-frontend.sh').read_text(encoding='utf-8')

    assert 'listen 443 ssl' in nginx
    assert 'location /api/' in nginx
    assert 'proxy_pass http://backend:8080' in nginx
    assert 'client_max_body_size 30m' in nginx
    assert 'Strict-Transport-Security' in nginx
    # Same origin: the browser must not be given cross-origin API headers.
    assert 'Access-Control-Allow-Origin' not in nginx
    assert 'backend:' in compose and 'nginx:1.27-alpine' in compose
    assert '/etc/shansuan/tls' in compose
    assert 'VITE_API_BASE_URL' in script
    assert 'MODEL_BASE_URL' in ENV_EXAMPLE.read_text(encoding='utf-8')