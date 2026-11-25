#!/usr/bin/env bash
# Run Alembic migrations once per release with the migration role.
# Usage: bash deploy/huawei/migrate.sh <image> [revision]
set -euo pipefail

IMAGE="${1:?usage: migrate.sh <image> [revision]}"
REVISION="${2:-head}"
ENV_FILE="${ENV_FILE:-/etc/shansuan/cloud.env}"

if [ ! -f "$ENV_FILE" ]; then
  echo "env file not found: $ENV_FILE" >&2
  exit 1
fi

docker run --rm --env-file "$ENV_FILE" "$IMAGE" \
  sh -c "alembic -c app/backend/cloud/alembic.ini upgrade ${REVISION}"

echo "Migrations applied to ${REVISION}"