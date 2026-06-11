#!/usr/bin/env bash
set -euo pipefail

# Docker Hub is often unreachable from restricted networks.
# Pull the Python base image via a mirror, then retag for the Dockerfile.
MIRROR="${DOCKER_MIRROR:-docker.m.daocloud.io}"
IMAGE="python:3.11-slim"

echo "Pulling ${IMAGE} from ${MIRROR} ..."
docker pull "${MIRROR}/library/${IMAGE}"
docker tag "${MIRROR}/library/${IMAGE}" "${IMAGE}"
echo "Tagged ${MIRROR}/library/${IMAGE} as ${IMAGE}"
