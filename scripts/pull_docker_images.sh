#!/usr/bin/env bash
set -euo pipefail

# Pre-pull Docker Hub images via registry mirrors before compose build.
# BuildKit still resolves image metadata through daemon mirrors; pulling and
# retagging locally avoids flaky mirror TLS timeouts during `docker compose build`.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

DEFAULT_MIRRORS=(
  docker.m.daocloud.io
  docker.1ms.run
  docker.xuanyuan.me
)

if [[ -n "${DOCKER_MIRROR:-}" ]]; then
  MIRRORS=("$DOCKER_MIRROR" "${DEFAULT_MIRRORS[@]}")
else
  MIRRORS=("${DEFAULT_MIRRORS[@]}")
fi

# mirror_path -> local tag (empty local tag means same as mirror_path without library/ prefix)
IMAGES=(
  "library/node:20-alpine|node:20-alpine"
  "library/nginx:1.27-alpine|nginx:1.27-alpine"
  "library/python:3.11-slim|python:3.11-slim"
  "library/postgres:16-alpine|postgres:16-alpine"
  "library/redis:7-alpine|redis:7-alpine"
  "qdrant/qdrant:v1.12.1|qdrant/qdrant:v1.12.1"
  "minio/minio:latest|minio/minio:latest"
)

PULL_RETRIES="${PULL_RETRIES:-3}"
PULL_RETRY_DELAY="${PULL_RETRY_DELAY:-5}"

pull_one() {
  local mirror_path="$1"
  local local_tag="$2"

  if docker image inspect "$local_tag" >/dev/null 2>&1; then
    echo "==> ${local_tag} already present, skipping"
    return 0
  fi

  local mirror
  for mirror in "${MIRRORS[@]}"; do
    local attempt=1
    while (( attempt <= PULL_RETRIES )); do
      echo "==> Pulling ${mirror}/${mirror_path} (attempt ${attempt}/${PULL_RETRIES}) ..."
      if docker pull "${mirror}/${mirror_path}"; then
        docker tag "${mirror}/${mirror_path}" "${local_tag}"
        echo "==> Tagged ${mirror}/${mirror_path} as ${local_tag}"
        return 0
      fi
      (( attempt++ )) || true
      sleep "$PULL_RETRY_DELAY"
    done
  done

  echo "==> Mirror pulls failed for ${local_tag}; trying docker.io directly ..."
  docker pull "$local_tag"
}

main() {
  cd "$ROOT"

  local entry mirror_path local_tag
  for entry in "${IMAGES[@]}"; do
    mirror_path="${entry%%|*}"
    local_tag="${entry##*|}"
    pull_one "$mirror_path" "$local_tag"
  done

  echo "==> All base images ready"
}

main "$@"
