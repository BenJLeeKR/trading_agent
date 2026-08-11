#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

IMAGE_TAG="${HARNESS_DEV_FRONTEND_IMAGE_TAG:-agent-trading-dev-frontend-validate:node20}"
DOCKERFILE_PATH="${HARNESS_DEV_FRONTEND_DOCKERFILE_PATH:-$ROOT_DIR/Dockerfile.dev-frontend-validation}"
CONTAINER_PREFIX="${HARNESS_DEV_FRONTEND_CONTAINER_PREFIX:-agent-trading-dev-frontend-check}"
NETWORK_MODE="${HARNESS_DEV_FRONTEND_NETWORK_MODE:-none}"
KEEP_CONTAINER="${HARNESS_DEV_FRONTEND_KEEP_CONTAINER:-0}"
REBUILD_IMAGE="${HARNESS_DEV_FRONTEND_REBUILD_IMAGE:-0}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
CONTAINER_NAME="${CONTAINER_PREFIX}-${TIMESTAMP}-$$"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

require_dev_workspace() {
  [[ "$ROOT_DIR" == "/workspace/agent_trading_dev" ]] || fail \
    "docker_dev_frontend_exec.sh 는 /workspace/agent_trading_dev 작업 경로에서만 사용할 수 있습니다."
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "필수 명령이 없습니다: $1"
}

ensure_image() {
  [[ -f "$DOCKERFILE_PATH" ]] || fail "frontend 검증 Dockerfile 이 없습니다: $DOCKERFILE_PATH"
  if [[ "$REBUILD_IMAGE" == "1" ]] || ! docker image inspect "$IMAGE_TAG" >/dev/null 2>&1; then
    echo "dev_frontend_validation_image_build=1"
    docker build -f "$DOCKERFILE_PATH" -t "$IMAGE_TAG" "$ROOT_DIR"
  else
    echo "dev_frontend_validation_image_build=0"
  fi
}

main() {
  require_dev_workspace
  require_command docker
  [[ "$#" -gt 0 ]] || fail "컨테이너 안에서 실행할 frontend 명령이 필요합니다."

  ensure_image

  local rm_flag="--rm"
  if [[ "$KEEP_CONTAINER" == "1" ]]; then
    rm_flag=""
  fi

  local inner_cmd="$*"

  echo "dev_frontend_validation_container_name=$CONTAINER_NAME"
  echo "dev_frontend_validation_image=$IMAGE_TAG"
  echo "dev_frontend_validation_workspace=$ROOT_DIR"
  echo "dev_frontend_validation_network_mode=$NETWORK_MODE"
  echo "dev_frontend_validation_keep_container=$KEEP_CONTAINER"

  exec docker run $rm_flag \
    --name "$CONTAINER_NAME" \
    --label "com.agent-trading.role=dev-frontend-validation" \
    --label "com.agent-trading.visibility=dozzle" \
    --label "com.agent-trading.workspace=agent_trading_dev" \
    --network "$NETWORK_MODE" \
    --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=256m \
    --tmpfs /work:rw,nosuid,size=1024m \
    -v "$ROOT_DIR/admin_ui:/src:ro" \
    "$IMAGE_TAG" \
    bash -lc "tar -C /src --exclude=node_modules -cf - . | tar -C /work -xf - && mkdir -p /work/node_modules && cp -as /opt/admin_ui/node_modules/. /work/node_modules/ && cd /work && $inner_cmd"
}

main "$@"
