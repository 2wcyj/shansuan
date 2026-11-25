#!/usr/bin/env bash
# Build the SPA for same-origin hosting (leave VITE_API_BASE_URL empty).
# Output: deploy/huawei/web
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FRONTEND="$ROOT/app/frontend"
OUTPUT="$ROOT/deploy/huawei/web"

cd "$FRONTEND"

if [ -n "${VITE_API_BASE_URL:-}" ]; then
  echo "VITE_API_BASE_URL must stay empty for same-origin deployment" >&2
  exit 1
fi

if command -v pnpm >/dev/null 2>&1; then
  pnpm install --frozen-lockfile
  pnpm build
elif command -v corepack >/dev/null 2>&1; then
  corepack pnpm install --frozen-lockfile
  corepack pnpm build
else
  echo "pnpm or corepack is required to build the frontend" >&2
  exit 1
fi

rm -rf "$OUTPUT"
cp -r dist "$OUTPUT"
echo "Frontend written to deploy/huawei/web"
echo "Upload it with the compose file and nginx.conf to the ECS host."