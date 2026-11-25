#!/usr/bin/env bash
# Preflight for the cloud env file: catches placeholders and misconfiguration
# before migrations or containers touch real data.
# Usage: bash deploy/huawei/preflight.sh [/etc/shansuan/cloud.env]
set -euo pipefail

ENV_FILE="${1:-/etc/shansuan/cloud.env}"
FAILED=0

fail() { echo "FAIL  $*" >&2; FAILED=1; }
ok() { echo "OK    $*"; }

[ -f "$ENV_FILE" ] || { echo "FAIL  env file not found: $ENV_FILE" >&2; exit 1; }

mode="$(stat -c '%a' "$ENV_FILE" 2>/dev/null || true)"
if [ -n "$mode" ] && [ "$mode" != "600" ]; then
  echo "WARN  permissions are $mode, expected 600" >&2
fi

get() {
  awk -F= -v key="$1" '$1==key { sub($1"=",""); print; exit }' "$ENV_FILE" \
    | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
}

required=(DATABASE_URL SESSION_SIGNING_KEY FRONTEND_ORIGINS KMS_PROVIDER KMS_REGION_ID
          KMS_KEY_ID HUAWEI_CLOUD_PROJECT_ID HUAWEI_CLOUD_ACCESS_KEY_ID
          HUAWEI_CLOUD_SECRET_ACCESS_KEY)
for key in "${required[@]}"; do
  value="$(get "$key")"
  if [ -z "$value" ]; then
    fail "$key is missing"
  elif [[ "$value" == *REPLACE* ]]; then
    fail "$key still contains a placeholder"
  else
    ok "$key set"
  fi
done

database="$(get DATABASE_URL)"
[[ "$database" == postgresql+asyncpg://* ]] || fail "DATABASE_URL must start with postgresql+asyncpg://"
[[ "$database" == *sslmode=require* || "$database" == *ssl=require* ]] \
  || echo "WARN  DATABASE_URL has no sslmode=require; RDS TLS is recommended" >&2

signing="$(get SESSION_SIGNING_KEY)"
[ "${#signing}" -ge 32 ] || fail "SESSION_SIGNING_KEY must be at least 32 characters"

origins="$(get FRONTEND_ORIGINS)"
[[ "$origins" == https://* ]] || fail "FRONTEND_ORIGINS must use https://"
[[ "$origins" != */ ]] || fail "FRONTEND_ORIGINS must not end with a slash"

[ "$(get KMS_PROVIDER)" = "huawei" ] || fail "KMS_PROVIDER must be huawei"
[[ "$(get KMS_REGION_ID)" =~ ^[a-z]{2}-[a-z]+-[0-9]$ ]] || fail "KMS_REGION_ID looks invalid"

redis="$(get REDIS_URL)"
if [ -n "$redis" ]; then
  [[ "$redis" == redis://* || "$redis" == rediss://* ]] \
    || fail "REDIS_URL must use redis:// or rediss://"
  ok "REDIS_URL set"
else
  echo "WARN  REDIS_URL is empty; sessions fall back to PostgreSQL" >&2
fi

obs_provider="$(get OBS_PROVIDER)"
if [ -n "$obs_provider" ]; then
  [ "$obs_provider" = "huawei" ] || fail "OBS_PROVIDER must be huawei"
  [ -n "$(get OBS_REGION_ID)" ] || fail "OBS_REGION_ID is required when OBS is enabled"
  [ -n "$(get OBS_BUCKET)" ] || fail "OBS_BUCKET is required when OBS is enabled"
  ok "OBS configured"
else
  echo "WARN  OBS_PROVIDER is empty; photo APIs will return 503" >&2
fi

model_url="$(get MODEL_BASE_URL)"
model_key="$(get MODEL_API_KEY)"
model_name="$(get MODEL_NAME)"
if [ -n "$model_url" ] || [ -n "$model_key" ] || [ -n "$model_name" ]; then
  [ -n "$model_url" ] && [ -n "$model_key" ] && [ -n "$model_name" ] \
    || fail "MODEL_BASE_URL, MODEL_API_KEY and MODEL_NAME must be set together"
  [[ "$model_url" == https://* ]] || fail "MODEL_BASE_URL must use https://"
  ok "model API configured"
else
  echo "WARN  model API is empty; chat and photo recognition will return 503" >&2
fi

if [ -n "$(get MIGRATION_DATABASE_URL)" ]; then
  ok "MIGRATION_DATABASE_URL present (keep it off the API container)"
fi

if [ "$FAILED" -ne 0 ]; then
  echo "Preflight failed." >&2
  exit 1
fi
echo "Preflight passed."