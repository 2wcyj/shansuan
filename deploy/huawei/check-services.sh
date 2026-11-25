#!/usr/bin/env bash
# Verify Huawei Cloud RDS (PostgreSQL) and DCS (Redis) connectivity from the
# host that will run the app. Uses local clients first, Docker as fallback.
# Never prints passwords.
# Usage: bash deploy/huawei/check-services.sh [/etc/shansuan/cloud.env]
set -euo pipefail

ENV_FILE="${1:-/etc/shansuan/cloud.env}"
[ -f "$ENV_FILE" ] || { echo "FAIL env file not found: $ENV_FILE" >&2; exit 1; }

get() {
  awk -F= -v key="$1" '$1==key { sub($1"=",""); print; exit }' "$ENV_FILE" \
    | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
}

have() { command -v "$1" >/dev/null 2>&1; }
docker_ready() { have docker && docker info >/dev/null 2>&1; }
with_timeout() {
  if have timeout; then timeout 30 "$@"; else "$@"; fi
}

DATABASE_URL="$(get DATABASE_URL)"
REDIS_URL="$(get REDIS_URL)"
FAILED=0
SKIPPED=0

report() {
  local name="$1" code="$2" output="$3"
  printf '%s\n' "$output" | tail -3
  if [ "$code" -eq 0 ]; then
    echo "OK    $name reachable"
  elif [ "$code" -eq 127 ] || [ "$code" -eq 126 ]; then
    echo "SKIP  no local client and Docker unavailable for $name"
    SKIPPED=1
  else
    echo "FAIL  $name unreachable; check VPC, security group, TLS and password" >&2
    FAILED=1
  fi
}

probe_db() {
  if have psql; then
    with_timeout psql "$PSQL_URL" -Atc "SELECT version();" -c "SHOW ssl;"
  elif docker_ready; then
    with_timeout docker run --rm --network host -e PGCONNECT_TIMEOUT=10 postgres:16 \
      psql "$PSQL_URL" -Atc "SELECT version();" -c "SHOW ssl;"
  else
    return 127
  fi
}

probe_redis() {
  if have redis-cli; then
    with_timeout redis-cli --no-auth-warning -u "$REDIS_URL" PING
  elif docker_ready; then
    with_timeout docker run --rm --network host redis:7-alpine \
      redis-cli --no-auth-warning -u "$REDIS_URL" PING
  else
    return 127
  fi
}

if [ -z "$DATABASE_URL" ]; then
  echo "FAIL  DATABASE_URL is empty" >&2
  FAILED=1
else
  PSQL_URL="${DATABASE_URL/postgresql+asyncpg:\/\//postgresql://}"
  PSQL_URL="${PSQL_URL/postgresql+psycopg:\/\//postgresql://}"
  echo "--- RDS for PostgreSQL ---"
  set +e
  db_output="$(probe_db 2>&1)"; db_code=$?
  set -e
  report "RDS" "$db_code" "$db_output"
fi

if [ -z "$REDIS_URL" ]; then
  echo "WARN  REDIS_URL is empty; sessions fall back to PostgreSQL"
else
  echo "--- DCS for Redis ---"
  set +e
  redis_output="$(probe_redis 2>&1)"; redis_code=$?
  set -e
  report "DCS" "$redis_code" "$redis_output"
fi

echo
if [ "$FAILED" -ne 0 ]; then
  echo "Service check failed." >&2
  exit 1
fi
if [ "$SKIPPED" -ne 0 ]; then
  echo "Service check skipped: run this on the ECS host or install psql/redis-cli." >&2
  exit 2
fi
echo "Service check passed."
echo "Next: bash deploy/huawei/preflight.sh $ENV_FILE"