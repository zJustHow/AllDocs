#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}==>${NC} $*"; }
warn()  { echo -e "${YELLOW}==>${NC} $*"; }
error() { echo -e "${RED}==>${NC} $*" >&2; }

usage() {
  cat <<'EOF'
AllDocs 一键启动脚本

用法:
  ./dev.sh              开发模式：Docker 后端 + 本地 Vite 前端（默认）
  ./dev.sh --docker     生产模式：docker-compose.prod.yml（含 Nginx 前端，端口 3000）
  ./dev.sh --build      重新构建镜像后启动
  ./dev.sh --stop       停止所有 Docker 服务
  ./dev.sh --help       显示此帮助

环境变量:
  USE_DOCKER_MIRROR=1     构建前从镜像站拉取 python:3.11-slim 基础镜像
  SKIP_PIPER=1            跳过 Piper 语音模型检查/下载
  SKIP_NPM_INSTALL=1      跳过前端 npm install
EOF
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    error "未找到命令: $1"
    exit 1
  fi
}

require_docker() {
  require_command docker
  if ! docker info >/dev/null 2>&1; then
    error "Docker 未运行，请先启动 Docker Desktop"
    exit 1
  fi
  if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
  else
    error "未找到 docker compose"
    exit 1
  fi
}

ensure_env() {
  if [[ -f .env ]]; then
    return
  fi
  if [[ -f .env.example ]]; then
    cp .env.example .env
    warn "已根据 .env.example 创建 .env，请编辑 LLM_API_KEY 等配置后重新运行"
  else
    error "缺少 .env 文件"
    exit 1
  fi
}

ensure_piper_models() {
  if [[ "${SKIP_PIPER:-0}" == "1" ]]; then
    return
  fi
  local model_dir="$ROOT/models/piper"
  if [[ -f "$model_dir/zh_CN-huayan-medium.onnx" && -f "$model_dir/en_US-lessac-medium.onnx" ]]; then
    return
  fi
  warn "Piper 语音模型缺失，正在下载（可用 SKIP_PIPER=1 跳过）..."
  bash "$ROOT/scripts/download_piper_models.sh" "$model_dir"
}

patch_env_var() {
  local key="$1"
  local value="$2"
  local file="$ROOT/.env"

  if grep -q "^${key}=" "$file"; then
    sed -i.bak "s|^${key}=.*|${key}=${value}|" "$file"
  else
    printf '%s=%s\n' "$key" "$value" >>"$file"
  fi
  rm -f "$file.bak"
}

ensure_embedding_model() {
  local model_root="$ROOT/models/modelscope"
  local embed_model="$model_root/BAAI/bge-m3/config.json"
  local rerank_model="$model_root/BAAI/bge-reranker-v2-m3/config.json"

  if [[ -f "$embed_model" && -f "$rerank_model" ]]; then
    patch_env_var "EMBEDDING_MODEL" "/app/models/modelscope/BAAI/bge-m3"
    patch_env_var "RERANK_MODEL" "/app/models/modelscope/BAAI/bge-reranker-v2-m3"
    return
  fi

  warn "Embedding / Rerank 模型缺失，正在通过 Docker 容器下载（首次较慢）..."
  require_docker
  "${COMPOSE[@]}" up -d api >/dev/null 2>&1 || true
  docker compose -f "$ROOT/docker-compose.yml" exec -T api python - <<'PY'
import os
import sys
import subprocess

subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "modelscope"])

from modelscope import snapshot_download

models = [
    ("BAAI/bge-m3", "/app/models/modelscope/BAAI/bge-m3"),
    ("BAAI/bge-reranker-v2-m3", "/app/models/modelscope/BAAI/bge-reranker-v2-m3"),
]
for repo_id, local_dir in models:
    if os.path.isfile(os.path.join(local_dir, "config.json")):
        print(f"Already exists: {repo_id}")
        continue
    print(f"Downloading {repo_id} -> {local_dir} ...")
    snapshot_download(repo_id, local_dir=local_dir)
    print(f"Ready: {repo_id}")
PY

  if [[ -f "$embed_model" ]]; then
    patch_env_var "EMBEDDING_MODEL" "/app/models/modelscope/BAAI/bge-m3"
  fi
  if [[ -f "$rerank_model" ]]; then
    patch_env_var "RERANK_MODEL" "/app/models/modelscope/BAAI/bge-reranker-v2-m3"
  else
    warn "Rerank 模型仍未就绪，可在 .env 中设置 RERANK_ENABLED=false 临时跳过"
  fi
}

ensure_frontend_deps() {
  if [[ "${SKIP_NPM_INSTALL:-0}" == "1" ]]; then
    return
  fi
  if [[ -d "$ROOT/frontend/node_modules" ]]; then
    return
  fi
  info "安装前端依赖..."
  (cd "$ROOT/frontend" && npm install)
}

wait_for_api() {
  local url="http://localhost:8000/health"
  local retries=60
  info "等待 API 就绪 ($url) ..."
  for ((i = 1; i <= retries; i++)); do
    if curl -sf "$url" >/dev/null 2>&1; then
      info "API 已就绪"
      return 0
    fi
    sleep 2
  done
  error "API 启动超时，请检查日志: ${COMPOSE[*]} logs api"
  exit 1
}

print_urls() {
  local frontend_url="${1:-http://localhost:3000}"
  echo
  info "AllDocs 已启动"
  echo "  前端:  ${frontend_url}"
  echo "  API:   http://localhost:8000"
  echo "  文档:  http://localhost:8000/docs"
  echo "  MinIO: http://localhost:9001  (minioadmin / minioadmin)"
  echo
  echo "  查看日志: ${COMPOSE[*]} logs -f api worker-ingestion worker-maintenance"
  echo "  停止服务: ./dev.sh --stop"
  echo
}

start_backend() {
  local build_flag=()
  if [[ "${BUILD:-0}" == "1" ]]; then
    build_flag=(--build)
  fi

  if [[ "${USE_DOCKER_MIRROR:-0}" == "1" ]]; then
    bash "$ROOT/scripts/pull_docker_base.sh"
  fi

  info "启动 Docker 服务..."
  "${COMPOSE[@]}" up -d "${build_flag[@]}" postgres redis qdrant minio api worker-ingestion worker-maintenance
  # Celery worker 不热重载代码，每次开发启动时重启以加载最新任务定义
  "${COMPOSE[@]}" restart worker-ingestion worker-maintenance
  wait_for_api
}

start_dev() {
  start_backend
  ensure_frontend_deps
  print_urls
  info "启动 Vite 开发服务器（Ctrl+C 停止前端，Docker 服务继续运行）..."
  cd "$ROOT/frontend"
  exec npm run dev
}

start_docker() {
  local build_flag=()
  if [[ "${BUILD:-0}" == "1" ]]; then
    build_flag=(--build)
  fi

  if [[ "${USE_DOCKER_MIRROR:-0}" == "1" ]]; then
    bash "$ROOT/scripts/pull_docker_base.sh"
  fi

  info "启动生产 Compose（含 Nginx 前端）..."
  FRONTEND_PORT=3000 "${COMPOSE[@]}" -f docker-compose.prod.yml up -d "${build_flag[@]}"
  wait_for_api
  print_urls "http://localhost:3000"
}

stop_all() {
  info "停止 Docker 服务..."
  "${COMPOSE[@]}" down
  info "已停止"
}

MODE="dev"
BUILD=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --docker|--prod)
      MODE="docker"
      ;;
    --build)
      BUILD=1
      ;;
    --stop)
      MODE="stop"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      error "未知参数: $1"
      usage
      exit 1
      ;;
  esac
  shift
done

require_docker

case "$MODE" in
  stop)
    stop_all
    ;;
  dev)
    ensure_env
    ensure_embedding_model
    ensure_piper_models
    start_dev
    ;;
  docker)
    ensure_env
    ensure_embedding_model
    ensure_piper_models
    start_docker
    ;;
esac
