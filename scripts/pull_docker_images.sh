#!/usr/bin/env bash
set -euo pipefail

# Pre-pull base images before compose build.
# Docker Hub images go through registry mirrors; Elastic images use elastic.co
# mirrors (docker.io/elasticsearch/* is blocked on most China mirrors).

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

# mirror_path -> local tag
IMAGES=(
  "library/node:20-alpine|node:20-alpine"
  "library/nginx:1.27-alpine|nginx:1.27-alpine"
  "library/python:3.11-slim|python:3.11-slim"
  "library/postgres:16-alpine|postgres:16-alpine"
  "library/redis:7-alpine|redis:7-alpine"
  "qdrant/qdrant:v1.12.1|qdrant/qdrant:v1.12.1"
  "minio/minio:latest|minio/minio:latest"
)

# repo_path (under docker.elastic.co) -> full local tag
ELASTIC_IMAGES=(
  "elasticsearch/elasticsearch:8.15.0|docker.elastic.co/elasticsearch/elasticsearch:8.15.0"
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

pull_elastic_one() {
  local repo_path="$1"
  local local_tag="$2"

  if docker image inspect "$local_tag" >/dev/null 2>&1; then
    echo "==> ${local_tag} already present, skipping"
    return 0
  fi

  # Elastic blocks docker.io/elasticsearch/* on public mirrors (403). Use
  # docker.elastic.co-specific mirrors instead.
  local sources=(
    "elastic.m.daocloud.io/${repo_path}"
    "elastic.m.ixdev.cn/${repo_path}"
    "m.daocloud.io/docker.elastic.co/${repo_path}"
  )

  local src
  for src in "${sources[@]}"; do
    local attempt=1
    while (( attempt <= PULL_RETRIES )); do
      echo "==> Pulling ${src} (attempt ${attempt}/${PULL_RETRIES}) ..."
      if docker pull "$src"; then
        docker tag "$src" "$local_tag"
        echo "==> Tagged ${src} as ${local_tag}"
        return 0
      fi
      (( attempt++ )) || true
      sleep "$PULL_RETRY_DELAY"
    done
  done

  echo "==> Elastic mirror pulls failed for ${local_tag}; trying docker.elastic.co directly ..."
  local attempt=1
  while (( attempt <= PULL_RETRIES )); do
    echo "==> Pulling ${local_tag} (attempt ${attempt}/${PULL_RETRIES}) ..."
    if docker pull "$local_tag"; then
      return 0
    fi
    (( attempt++ )) || true
    sleep "$PULL_RETRY_DELAY"
  done

  echo "==> ERROR: could not pull ${local_tag}" >&2
  return 1
}

main() {
  cd "$ROOT"

  local entry mirror_path local_tag repo_path
  for entry in "${IMAGES[@]}"; do
    mirror_path="${entry%%|*}"
    local_tag="${entry##*|}"
    pull_one "$mirror_path" "$local_tag"
  done

  for entry in "${ELASTIC_IMAGES[@]}"; do
    repo_path="${entry%%|*}"
    local_tag="${entry##*|}"
    pull_elastic_one "$repo_path" "$local_tag"
  done

  echo "==> All base images ready"
}

main "$@"
