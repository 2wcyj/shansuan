FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/shansuan
COPY deploy/cloud/requirements.lock.txt /tmp/requirements.lock.txt
RUN python -m pip install --no-cache-dir --requirement /tmp/requirements.lock.txt \
    && rm /tmp/requirements.lock.txt \
    && groupadd --system --gid 10001 shansuan \
    && useradd --system --uid 10001 --gid shansuan --home-dir /nonexistent --shell /usr/sbin/nologin shansuan

COPY app/backend /srv/shansuan/app/backend
COPY app/resources /srv/shansuan/app/resources
RUN python -c "from app.backend.cloud.crypto import CloudCrypto; from app.backend.cloud.photos import CloudPhotos; from app.backend.cloud.redis_store import RedisAuthStore; import obs; from huaweicloudsdkkms.v2 import KmsClient; import redis"

USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/live', timeout=2)"
CMD ["uvicorn", "app.backend.cloud_main:app", "--host", "0.0.0.0", "--port", "8080", "--no-server-header"]
