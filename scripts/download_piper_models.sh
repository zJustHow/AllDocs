#!/usr/bin/env bash
set -euo pipefail

MODEL_DIR="${1:-./models/piper}"
HF_ENDPOINT="${HF_ENDPOINT:-https://huggingface.co}"
HF_ENDPOINT="${HF_ENDPOINT%/}"
mkdir -p "$MODEL_DIR"

download_model() {
  local name="$1"
  local lang_path="$2"
  local endpoint="$HF_ENDPOINT"
  local base="${endpoint}/rhasspy/piper-voices/resolve/main"

  if [[ -f "$MODEL_DIR/${name}.onnx" ]]; then
    echo "Already exists: $name"
    return
  fi

  echo "Downloading $name from ${endpoint} ..."
  if ! curl -fL --connect-timeout 15 --retry 2 -o "$MODEL_DIR/${name}.onnx" \
      "${base}/${lang_path}/${name}.onnx"; then
    if [[ "$endpoint" == "https://huggingface.co" ]]; then
      echo "huggingface.co unreachable, retrying via https://hf-mirror.com ..."
      endpoint="https://hf-mirror.com"
      base="${endpoint}/rhasspy/piper-voices/resolve/main"
      curl -fL --connect-timeout 15 --retry 2 -o "$MODEL_DIR/${name}.onnx" \
        "${base}/${lang_path}/${name}.onnx"
    else
      echo "Download failed. Try: HF_ENDPOINT=https://hf-mirror.com $0" >&2
      return 1
    fi
  fi
  curl -fL --connect-timeout 15 --retry 2 -o "$MODEL_DIR/${name}.onnx.json" \
    "${base}/${lang_path}/${name}.onnx.json"
}

download_model "zh_CN-huayan-medium" "zh/zh_CN/huayan/medium"
download_model "en_US-lessac-medium" "en/en_US/lessac/medium"

echo "Piper models ready in $MODEL_DIR"
