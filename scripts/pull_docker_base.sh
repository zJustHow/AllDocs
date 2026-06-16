#!/usr/bin/env bash
set -euo pipefail

# Backward-compatible wrapper; see pull_docker_images.sh for full image list.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$ROOT/scripts/pull_docker_images.sh"
