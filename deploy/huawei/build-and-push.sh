#!/usr/bin/env bash
# Build the cloud image and push it to Huawei Cloud SWR.
# Usage:
#   SWR_REGION=cn-north-4 SWR_ORGANIZATION=your-org IMAGE_TAG=0.1.0 \
#     bash deploy/huawei/build-and-push.sh
# Set SKIP_PUSH=1 to build without pushing.
set -euo pipefail

REGION="${SWR_REGION:-cn-north-4}"
ORGANIZATION="${SWR_ORGANIZATION:?set SWR_ORGANIZATION to your SWR organization}"
REPOSITORY="${SWR_REPOSITORY:-shansuan}"
TAG="${IMAGE_TAG:-0.1.0}"
IMAGE="swr.${REGION}.myhuaweicloud.com/${ORGANIZATION}/${REPOSITORY}:${TAG}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [ ! -f deploy/cloud/Dockerfile ]; then
  echo "deploy/cloud/Dockerfile not found; run from the repository" >&2
  exit 1
fi

echo "Building ${IMAGE}"
docker build -f deploy/cloud/Dockerfile -t "${IMAGE}" .

if [ "${SKIP_PUSH:-0}" = "1" ]; then
  echo "SKIP_PUSH=1: image built locally, not pushed"
  exit 0
fi

docker push "${IMAGE}"
echo "Pushed ${IMAGE}"