#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}==>${NC} $*"; }
warn()  { echo -e "${YELLOW}==>${NC} $*"; }
error() { echo -e "${RED}==>${NC} $*" >&2; }

GENERATE_SECRETS=0
START_STACK=0

usage() {
  cat <<'EOF'
AllDocs 生产服务器首次初始化

用法:
  bash scripts/server-bootstrap.sh                    安装 Docker、创建 .env、下载 Piper / Embedding 模型
  bash scripts/server-bootstrap.sh --generate-secrets 自动生成数据库 / MinIO 密码
  bash scripts/server-bootstrap.sh --start            初始化完成后启动 docker-compose.prod.yml
  bash scripts/server-bootstrap.sh --help             显示此帮助

说明:
  在阿里云 ECS 上首次部署前运行一次。GitHub Actions 不会同步 .env，需在本机生成并保存好密钥。
EOF
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    error "未找到命令: $1"
    exit 1
  fi
}

install_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    info "Docker 与 Compose 插件已安装"
    configure_docker_mirror
    return
  fi

  warn "正在安装 Docker（需要 root 或 sudo）..."
  if curl -fsSL --connect-timeout 15 https://get.docker.com | sh; then
    info "已通过 get.docker.com 安装 Docker"
  else
    warn "get.docker.com 不可用，改用 apt 安装 docker.io + docker-compose-v2..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq docker.io docker-compose-v2
    systemctl enable --now docker
  fi

  if ! docker compose version >/dev/null 2>&1; then
    error "Docker 已安装但未找到 compose 插件，请手动安装 docker-compose-v2 或 docker-compose-plugin"
    exit 1
  fi

  if [[ "${EUID:-$(id -u)}" -ne 0 ]] && ! groups | grep -q '\bdocker\b'; then
    warn "当前用户不在 docker 组，正在添加（需重新登录 SSH 后生效）..."
    sudo usermod -aG docker "$USER" || true
  fi

  info "Docker 安装完成"
  configure_docker_mirror
}

configure_docker_mirror() {
  local primary="${DOCKER_MIRROR:-docker.m.daocloud.io}"
  local mirrors=(
    "$primary"
    docker.1ms.run
    docker.xuanyuan.me
  )
  mkdir -p /etc/docker

  if [[ -f /etc/docker/daemon.json ]] && grep -q "$primary" /etc/docker/daemon.json 2>/dev/null; then
    info "Docker 镜像加速已配置 ($primary 等)"
    return
  fi

  warn "配置 Docker 镜像加速（${primary} 等），解决国内拉取 docker.io 超时..."
  local json_mirrors=""
  local m
  for m in "${mirrors[@]}"; do
    [[ -n "$json_mirrors" ]] && json_mirrors+=", "
    json_mirrors+="\"https://${m}\""
  done
  cat >/etc/docker/daemon.json <<EOF
{
  "registry-mirrors": [${json_mirrors}]
}
EOF
  systemctl restart docker
  info "Docker 镜像加速已启用"
}

ensure_env() {
  if [[ -f .env ]]; then
    info ".env 已存在，跳过创建"
    return
  fi

  if [[ ! -f .env.example ]]; then
    error "缺少 .env.example，请在项目根目录运行此脚本"
    exit 1
  fi

  cp .env.example .env
  info "已根据 .env.example 创建 .env"
}

patch_env_var() {
  local key="$1"
  local value="$2"
  local file=".env"

  if grep -q "^${key}=" "$file"; then
    sed -i.bak "s|^${key}=.*|${key}=${value}|" "$file"
  else
    printf '%s=%s\n' "$key" "$value" >>"$file"
  fi
}

generate_secrets() {
  require_command openssl

  local postgres_password minio_access minio_secret
  postgres_password="$(openssl rand -hex 16)"
  minio_access="alldocs$(openssl rand -hex 4)"
  minio_secret="$(openssl rand -hex 20)"

  patch_env_var "POSTGRES_PASSWORD" "$postgres_password"
  patch_env_var "POSTGRES_URL" "postgresql+asyncpg://alldocs:${postgres_password}@postgres:5432/alldocs"
  patch_env_var "POSTGRES_URL_SYNC" "postgresql://alldocs:${postgres_password}@postgres:5432/alldocs"
  patch_env_var "MINIO_ACCESS_KEY" "$minio_access"
  patch_env_var "MINIO_SECRET_KEY" "$minio_secret"

  rm -f .env.bak
  info "已生成 POSTGRES_PASSWORD / MINIO 密钥并写入 .env"
  warn "请妥善保存 .env，GitHub Actions 不会上传此文件"
}

ensure_piper_models() {
  info "检查 Piper 语音模型..."
  bash "$ROOT/scripts/download_piper_models.sh" "$ROOT/models/piper"
}

ensure_embedding_models() {
  info "检查 Embedding / Rerank 模型（ModelScope，避免 HuggingFace 不可达）..."
  bash "$ROOT/scripts/download_embedding_models.sh" "$ROOT/models/modelscope"

  if [[ -f "$ROOT/models/modelscope/BAAI/bge-m3/config.json" ]]; then
    patch_env_var "EMBEDDING_MODEL" "/app/models/modelscope/BAAI/bge-m3"
  fi
  if [[ -f "$ROOT/models/modelscope/BAAI/bge-reranker-v2-m3/config.json" ]]; then
    patch_env_var "RERANK_MODEL" "/app/models/modelscope/BAAI/bge-reranker-v2-m3"
  fi
}

validate_env() {
  local missing=0

  if grep -q '^LLM_API_KEY=sk-your-key$' .env || grep -q '^LLM_API_KEY=$' .env; then
    warn "请在 .env 中设置 LLM_API_KEY（例如百炼 DashScope 或 DeepSeek）"
    missing=1
  fi

  if grep -q '^POSTGRES_PASSWORD=change-me$' .env; then
    warn "POSTGRES_PASSWORD 仍为默认值，请修改或运行 --generate-secrets"
    missing=1
  fi

  if grep -q '^MINIO_ACCESS_KEY=change-me$' .env || grep -q '^MINIO_SECRET_KEY=change-me$' .env; then
    warn "MinIO 密钥仍为默认值，请修改或运行 --generate-secrets"
    missing=1
  fi

  return "$missing"
}

start_stack() {
  require_command docker
  if ! docker info >/dev/null 2>&1; then
    error "无法连接 Docker daemon，若刚加入 docker 组请重新登录 SSH 后再试"
    exit 1
  fi

  if ! validate_env; then
    error "请先完善 .env 后再启动"
    exit 1
  fi

  info "构建并启动生产环境（首次可能需 20–40 分钟）..."
  bash "$ROOT/scripts/pull_docker_images.sh"
  docker compose -f docker-compose.prod.yml up -d --build
  info "服务已启动，访问 http://<服务器IP>（默认 80 端口）"
}

print_next_steps() {
  echo
  info "初始化完成，后续步骤："
  echo "  1. 编辑 .env，至少设置 LLM_API_KEY"
  echo "  2. 阿里云安全组放行 80（以及 GitHub Actions 所需的 22）"
  echo "  3. 若拉取镜像超时，确认已配置 Docker 镜像加速（bootstrap 会自动配置）"
  echo "  4. 在 GitHub 仓库配置 Secrets: ECS_HOST, ECS_USER, ECS_SSH_KEY"
  echo "  5. push 到 main 触发自动部署，或手动执行:"
  echo "       docker compose -f docker-compose.prod.yml up -d --build"
  echo
  echo "  查看日志: docker compose -f docker-compose.prod.yml logs -f api worker"
  echo
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --generate-secrets)
      GENERATE_SECRETS=1
      ;;
    --start)
      START_STACK=1
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

if [[ ! -f docker-compose.prod.yml ]]; then
  error "未找到 docker-compose.prod.yml，请在 AllDocs 项目根目录运行"
  exit 1
fi

install_docker
ensure_env

if [[ "$GENERATE_SECRETS" == "1" ]]; then
  generate_secrets
fi

ensure_piper_models
ensure_embedding_models

if [[ "$START_STACK" == "1" ]]; then
  start_stack
else
  validate_env || true
  print_next_steps
fi
