#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

IMAGE_TAG="${HARNESS_DEV_IMAGE_TAG:-agent-trading-dev-validate:py314}"
DOCKERFILE_PATH="${HARNESS_DEV_DOCKERFILE_PATH:-$ROOT_DIR/Dockerfile.dev-validation}"
CONTAINER_PREFIX="${HARNESS_DEV_CONTAINER_PREFIX:-agent-trading-devcheck}"
NETWORK_MODE="${HARNESS_DEV_NETWORK_MODE:-none}"
KEEP_CONTAINER="${HARNESS_DEV_KEEP_CONTAINER:-0}"
REBUILD_IMAGE="${HARNESS_DEV_REBUILD_IMAGE:-0}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
CONTAINER_NAME="${CONTAINER_PREFIX}-${TIMESTAMP}-$$"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

require_dev_workspace() {
  [[ "$ROOT_DIR" == "/workspace/agent_trading_dev" ]] || fail \
    "docker_dev_exec.sh 는 /workspace/agent_trading_dev 작업 경로에서만 사용할 수 있습니다."
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "필수 명령이 없습니다: $1"
}

ensure_image() {
  [[ -f "$DOCKERFILE_PATH" ]] || fail "검증 Dockerfile 이 없습니다: $DOCKERFILE_PATH"
  if [[ "$REBUILD_IMAGE" == "1" ]] || ! docker image inspect "$IMAGE_TAG" >/dev/null 2>&1; then
    echo "dev_validation_image_build=1"
    docker build -f "$DOCKERFILE_PATH" -t "$IMAGE_TAG" "$ROOT_DIR"
  else
    echo "dev_validation_image_build=0"
  fi
}

main() {
  require_dev_workspace
  require_command docker
  [[ "$#" -gt 0 ]] || fail "컨테이너 안에서 실행할 명령이 필요합니다."

  ensure_image

  local rm_flag="--rm"
  if [[ "$KEEP_CONTAINER" == "1" ]]; then
    rm_flag=""
  fi

  echo "dev_validation_container_name=$CONTAINER_NAME"
  echo "dev_validation_image=$IMAGE_TAG"
  echo "dev_validation_workspace=$ROOT_DIR"
  echo "dev_validation_network_mode=$NETWORK_MODE"
  echo "dev_validation_keep_container=$KEEP_CONTAINER"

  exec docker run $rm_flag \
    --name "$CONTAINER_NAME" \
    --label "com.agent-trading.role=dev-validation" \
    --label "com.agent-trading.visibility=dozzle" \
    --label "com.agent-trading.workspace=agent_trading_dev" \
    --workdir /app \
    --network "$NETWORK_MODE" \
    --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=256m \
    --tmpfs /var/tmp:rw,noexec,nosuid,size=128m \
    --tmpfs /app/.pytest_cache:rw,noexec,nosuid,size=128m \
    --tmpfs /app/.ruff_cache:rw,noexec,nosuid,size=128m \
    --tmpfs /app/.mypy_cache:rw,noexec,nosuid,size=128m \
    -e PYTHONPATH=/app/src \
    -e PYTHONUNBUFFERED=1 \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -e PYTHONPYCACHEPREFIX=/tmp/pycache \
    -v "$ROOT_DIR:/app:rw" \
    "$IMAGE_TAG" \
    "$@"
}

main "$@"
