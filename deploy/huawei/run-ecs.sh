#!/usr/bin/env bash
# Start the cloud image on a Huawei Cloud ECS host.
# Usage:
#   bash deploy/huawei/run-ecs.sh swr.cn-north-4.myhuaweicloud.com/your-org/shansuan:0.1.0
# The env file must contain the variables listed in deploy/cloud/.env.example.
set -euo pipefail

IMAGE="${1:?usage: run-ecs.sh <image>}"
ENV_FILE="${ENV_FILE:-/etc/shansuan/cloud.env}"
NAME="${CONTAINER_NAME:-shansuan}"
PORT="${HOST_PORT:-8080}"

if [ ! -f "$ENV_FILE" ]; then
  echo "env file not found: $ENV_FILE" >&2
  exit 1
fi

if docker inspect "$NAME" >/dev/null 2>&1; then
  echo "Removing existing container ${NAME}"
  docker rm -f "$NAME" >/dev/null
fi

docker run -d --name "$NAME" --restart unless-stopped \
  --env-file "$ENV_FILE" \
  -p "${PORT}:8080" \
  "$IMAGE"

echo "Waiting for readiness on 127.0.0.1:${PORT}"
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}/health/live" >/dev/null 2>&1; then
    echo "Container is live; inspect /health/ready for dependency status"
    docker ps --filter "name=${NAME}"
    exit 0
  fi
  sleep 1
done

echo "Container did not become live in 30s; check: docker logs ${NAME}" >&2
docker logs --tail 50 "$NAME" >&2 || true
exit 1