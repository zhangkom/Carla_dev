#!/usr/bin/env bash
# /**
# * File name: deploy_mgsc_daw_service.sh
# * Brief: Ubuntu Docker 部署脚本
# * Function:
# *     加载 MGSC DAW 镜像并创建固定名称的 FastAPI 服务容器
# * Author: 咪咕数创工程架构组
# *     MGSC AI Software Architecture group
# * Version: V2.5.10
# * Date: 2026/04/30
# */
set -euo pipefail

VERSION="${VERSION:-6.5.12.0956}"
IMAGE_NAME="${IMAGE_NAME:-mgsc_daw_service:${VERSION}}"
CONTAINER_NAME="${CONTAINER_NAME:-mgsc_daw_service_kom}"
IMAGE_TAR="${IMAGE_TAR:-mgsc_daw_service_${VERSION}.tar}"
HOST_PORT="${HOST_PORT:-18001}"
CONTAINER_PORT="${CONTAINER_PORT:-8000}"
MAX_PART_BYTES="${MAX_PART_BYTES:-2000000000}"
LOAD_IMAGE="${LOAD_IMAGE:-1}"
START_MODE="${START_MODE:-service}"
RESTART_POLICY="${RESTART_POLICY:-unless-stopped}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="${RUNTIME_DIR:-$ROOT_DIR/runtime}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi

if [ "$START_MODE" != "service" ] && [ "$START_MODE" != "debug" ]; then
  echo "START_MODE must be service or debug" >&2
  exit 1
fi

case "$(uname -s 2>/dev/null || true)" in
  MINGW*|MSYS*|CYGWIN*)
    # Keep container-side Linux paths from being rewritten by Git Bash/MSYS
    # when it invokes Docker Desktop's docker.exe.
    MSYS_EXCLUDES="MUSIC_SERVICE_CONFIG=;WINEPREFIX=;DAW_RUNTIME_ROOT=;WINEPREFIX_SEED="
    if [ -n "${MSYS2_ARG_CONV_EXCL:-}" ]; then
      export MSYS2_ARG_CONV_EXCL="$MSYS_EXCLUDES;$MSYS2_ARG_CONV_EXCL"
    else
      export MSYS2_ARG_CONV_EXCL="$MSYS_EXCLUDES"
    fi
    ;;
esac

cd "$ROOT_DIR"

mapfile -t IMAGE_PARTS < <(find "$ROOT_DIR" -maxdepth 1 -type f -name "${IMAGE_TAR}.part*" | sort)

check_part_sizes() {
  local part size
  for part in "${IMAGE_PARTS[@]}"; do
    size="$(stat -c '%s' "$part")"
    if [ "$size" -gt "$MAX_PART_BYTES" ]; then
      echo "image part is larger than MAX_PART_BYTES=$MAX_PART_BYTES: $part ($size bytes)" >&2
      exit 1
    fi
  done
}

verify_split_sha256() {
  local sums_file expected actual
  sums_file="$ROOT_DIR/SHA256SUMS_${VERSION}.txt"
  if [ ! -f "$sums_file" ]; then
    echo "Skip full image sha256 verification: $sums_file not found"
    return
  fi
  expected="$(awk -v name="$IMAGE_TAR" '{path=$2; sub(/^\*/, "", path); base=path; sub(/^.*\//, "", base); if (base == name) {print $1; exit}}' "$sums_file")"
  if [ -z "$expected" ]; then
    echo "Skip full image sha256 verification: $IMAGE_TAR not listed in $sums_file"
    return
  fi
  actual="$(cat "${IMAGE_PARTS[@]}" | sha256sum | awk '{print $1}')"
  if [ "${actual,,}" != "${expected,,}" ]; then
    echo "split image sha256 mismatch" >&2
    echo "  expected: $expected" >&2
    echo "  actual:   $actual" >&2
    exit 1
  fi
  echo "Split image sha256 OK: $actual"
}

load_image() {
  if [ "$LOAD_IMAGE" = "0" ]; then
    echo "LOAD_IMAGE=0, skip docker load"
    return
  fi

  if [ -f "$IMAGE_TAR" ]; then
    echo "Loading image from full tar: $IMAGE_TAR"
    docker load -i "$IMAGE_TAR"
    return
  fi

  if [ "${#IMAGE_PARTS[@]}" -gt 0 ]; then
    check_part_sizes
    verify_split_sha256
    echo "Loading image from split parts:"
    printf '  %s\n' "${IMAGE_PARTS[@]}"
    cat "${IMAGE_PARTS[@]}" | docker load
    return
  fi

  if docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
    echo "Image already exists locally: $IMAGE_NAME"
    return
  fi

  echo "No image tar or split parts found for $IMAGE_TAR, and image is not loaded: $IMAGE_NAME" >&2
  exit 1
}

load_image

mkdir -p "$RUNTIME_DIR/output" "$RUNTIME_DIR/logs" "$RUNTIME_DIR/service_work" "$RUNTIME_DIR/temp"

if docker ps -a --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"; then
  echo "Removing existing container $CONTAINER_NAME"
  docker rm -f "$CONTAINER_NAME" >/dev/null
fi

if [ "$START_MODE" = "debug" ]; then
  RUN_COMMAND_ARGS="sleep infinity"
else
  RUN_COMMAND_ARGS=""
fi

ADD_HOST_GATEWAY_OPTION=""
if [ "${ADD_HOST_GATEWAY:-0}" = "1" ]; then
  ADD_HOST_GATEWAY_OPTION="--add-host=host.docker.internal:host-gateway"
fi

echo "Creating container $CONTAINER_NAME from $IMAGE_NAME"
docker run -d \
  --name "$CONTAINER_NAME" \
  --security-opt seccomp=unconfined \
  --pids-limit=-1 \
  --ulimit nproc=65535:65535 \
  --shm-size=1g \
  --restart "$RESTART_POLICY" \
  ${ADD_HOST_GATEWAY_OPTION:+$ADD_HOST_GATEWAY_OPTION} \
  -p "$HOST_PORT:$CONTAINER_PORT" \
  -e TZ=Asia/Shanghai \
  -e MUSIC_SERVICE_CONFIG=/home/workspace/config/plugins.deploy.json \
  -e MUSIC_SERVICE_ASYNC_WORKERS="${MUSIC_SERVICE_ASYNC_WORKERS:-1}" \
  -e MUSIC_SERVICE_CALLBACK_TIMEOUT="${MUSIC_SERVICE_CALLBACK_TIMEOUT:-30}" \
  -e MUSIC_SERVICE_CALLBACK_RETRIES="${MUSIC_SERVICE_CALLBACK_RETRIES:-3}" \
  -e MUSIC_SERVICE_DUMMY_NOSLEEP="${MUSIC_SERVICE_DUMMY_NOSLEEP:-1}" \
  -e MUSIC_SERVICE_DUMMY_NOSLEEP_DISABLE_PLUGINS="${MUSIC_SERVICE_DUMMY_NOSLEEP_DISABLE_PLUGINS:-vst_keyzone_classic}" \
  -e MUSIC_SERVICE_ARTIFACT_ARCHIVE_ROOT="${MUSIC_SERVICE_ARTIFACT_ARCHIVE_ROOT:-/home/workspace/temp}" \
  -e WINEPREFIX=/wineprefix \
  -e DAW_RUNTIME_ROOT=/home/runtime \
  -e DAW_SERVICE_PORT="$CONTAINER_PORT" \
  -v "$RUNTIME_DIR/output:/home/runtime/output" \
  -v "$RUNTIME_DIR/logs:/home/runtime/logs" \
  -v "$RUNTIME_DIR/logs:/home/workspace/logs" \
  -v "$RUNTIME_DIR/service_work:/home/runtime/service_work" \
  -v "$RUNTIME_DIR/temp:/home/workspace/temp" \
  "$IMAGE_NAME" \
  ${RUN_COMMAND_ARGS:+$RUN_COMMAND_ARGS} >/dev/null

docker cp "$CONTAINER_NAME:/home/workspace/mgsc_daw_client.py" "$ROOT_DIR/mgsc_daw_client.py"
docker cp "$CONTAINER_NAME:/home/workspace/mgsc_daw_async_client.py" "$ROOT_DIR/mgsc_daw_async_client.py"

if command -v curl >/dev/null 2>&1 && [ "$START_MODE" = "service" ]; then
  echo "Waiting for /mgsc_daw_service/health ..."
  health_ok=0
  for _ in $(seq 1 "${HEALTH_WAIT_ATTEMPTS:-120}"); do
    if curl -fsS "http://127.0.0.1:$HOST_PORT/mgsc_daw_service/health" >/dev/null 2>&1; then
      echo "Health check OK"
      health_ok=1
      break
    fi
    sleep 2
  done
  if [ "$health_ok" != "1" ]; then
    echo "Health check failed: http://127.0.0.1:$HOST_PORT/mgsc_daw_service/health" >&2
    docker logs --tail 80 "$CONTAINER_NAME" >&2 || true
    exit 1
  fi
fi

cat <<EOF
Container is ready:
  name: $CONTAINER_NAME
  image: $IMAGE_NAME
  start mode: $START_MODE
  service port: host $HOST_PORT -> container $CONTAINER_PORT
  external API: http://<ubuntu-server-ip>:$HOST_PORT/mgsc_daw_service/v1/render

If START_MODE=debug, start the service manually:
  docker exec -it $CONTAINER_NAME bash
  cd /home/workspace
  python mgsc_daw_service.py

View service logs:
  docker logs -f $CONTAINER_NAME

From another terminal:
  python mgsc_daw_client.py --server http://127.0.0.1:$HOST_PORT --zip /path/to/bundle.zip --output output.mp3

Async callback client:
  python mgsc_daw_async_client.py --server http://127.0.0.1:$HOST_PORT --zip /path/to/bundle.zip --output output.mp3 --callback-public-host host.docker.internal

Disable fast Dummy render for diagnostics:
  MUSIC_SERVICE_DUMMY_NOSLEEP=0 ./deploy_mgsc_daw_service.sh

Use a custom public host port:
  HOST_PORT=18001 ./deploy_mgsc_daw_service.sh

Use manual/debug container mode:
  START_MODE=debug ./deploy_mgsc_daw_service.sh

Runtime files:
  $RUNTIME_DIR/output
  $RUNTIME_DIR/logs
  $RUNTIME_DIR/service_work
  $RUNTIME_DIR/temp
EOF
