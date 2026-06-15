#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_ROOT="${1:-$ROOT/models/modelscope}"

mkdir -p "$MODEL_ROOT"

download_model() {
  local model_id="$1"
  local local_dir="$2"
  local name="${model_id##*/}"

  if [[ -f "$local_dir/config.json" ]]; then
    echo "Already exists: $model_id"
    return 0
  fi

  echo "Downloading $model_id -> $local_dir ..."
  mkdir -p "$local_dir"

  if python3 - <<'PY' "$model_id" "$local_dir"
import sys
from modelscope import snapshot_download

snapshot_download(sys.argv[1], local_dir=sys.argv[2])
PY
  then
    echo "Ready: $model_id"
    return 0
  fi

  echo "ModelScope download failed for $model_id" >&2
  return 1
}

ensure_modelscope() {
  if python3 -c "import modelscope" >/dev/null 2>&1; then
    return 0
  fi

  echo "Installing modelscope (Tsinghua PyPI mirror) ..."
  python3 -m pip install --user -q \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --trusted-host pypi.tuna.tsinghua.edu.cn \
    modelscope
}

ensure_modelscope

download_model "BAAI/bge-m3" "$MODEL_ROOT/BAAI/bge-m3"
download_model "BAAI/bge-reranker-v2-m3" "$MODEL_ROOT/BAAI/bge-reranker-v2-m3"

echo "Embedding models ready under $MODEL_ROOT"
