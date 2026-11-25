#!/usr/bin/env bash
# Post-deploy verification against the public HTTPS origin.
# Usage: bash deploy/huawei/verify.sh https://app.example.cn
set -euo pipefail

BASE="${1:?usage: verify.sh https://your-domain}"
FAILED=0

# check <name> <accepted codes, space separated> <url>
check() {
  local name="$1" expected="$2" url="$3" code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$url" || true)"
  if [[ " $expected " == *" $code "* ]]; then
    echo "PASS  $name  ($code)"
  else
    echo "FAIL  $name  expected [$expected] got ${code:-none}  $url"
    FAILED=1
  fi
}

check "live"                       "200"     "$BASE/health/live"
check "ready"                      "200"     "$BASE/health/ready"
check "spa"                        "200"     "$BASE/"
check "profile requires auth"      "401 403" "$BASE/api/profile"
check "chat requires auth"         "401 403" "$BASE/api/chat"
check "reports requires auth"      "401 403" "$BASE/api/reports?end=2026-01-01"
check "vitals requires auth"       "401 403" "$BASE/api/vitals?date=2026-01-01"

echo
echo "--- readiness body ---"
curl -fsS --max-time 15 "$BASE/health/ready" || true
echo

if [ "$FAILED" -ne 0 ]; then
  echo "Verification failed; inspect: docker compose logs backend" >&2
  exit 1
fi
echo "All basic checks passed."
echo "Still do manually: two-account isolation, photo upload, mobile network walkthrough."