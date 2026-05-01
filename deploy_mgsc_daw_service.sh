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

IMAGE_NAME="${IMAGE_NAME:-mgsc_daw_service:v6.4.39}"
CONTAINER_NAME="${CONTAINER_NAME:-mgsc_daw_service_kom}"
IMAGE_TAR="${IMAGE_TAR:-mgsc_daw_service_v6.4.39.tar}"
HOST_PORT="${HOST_PORT:-8000}"
CONTAINER_PORT="${CONTAINER_PORT:-8000}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="${RUNTIME_DIR:-$ROOT_DIR/runtime}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi

cd "$ROOT_DIR"

if [ -f "$IMAGE_TAR" ]; then
  echo "Loading image from $IMAGE_TAR"
  docker load -i "$IMAGE_TAR"
fi

mkdir -p "$RUNTIME_DIR/output" "$RUNTIME_DIR/logs" "$RUNTIME_DIR/service_work"

if docker ps -a --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"; then
  echo "Removing existing container $CONTAINER_NAME"
  docker rm -f "$CONTAINER_NAME" >/dev/null
fi

echo "Creating container $CONTAINER_NAME from $IMAGE_NAME"
docker run -d \
  --name "$CONTAINER_NAME" \
  --security-opt seccomp=unconfined \
  --pids-limit=-1 \
  --ulimit nproc=65535:65535 \
  --shm-size=1g \
  -p "$HOST_PORT:$CONTAINER_PORT" \
  -e TZ=Asia/Shanghai \
  -e MUSIC_SERVICE_CONFIG=/home/workspace/config/plugins.deploy.json \
  -e WINEPREFIX=/wineprefix \
  -e DAW_RUNTIME_ROOT=/home/runtime \
  -e DAW_SERVICE_PORT="$CONTAINER_PORT" \
  -v "$RUNTIME_DIR/output:/home/runtime/output" \
  -v "$RUNTIME_DIR/logs:/home/runtime/logs" \
  -v "$RUNTIME_DIR/service_work:/home/runtime/service_work" \
  "$IMAGE_NAME" \
  sleep infinity >/dev/null

docker cp "$CONTAINER_NAME:/home/workspace/mgsc_daw_client.py" "$ROOT_DIR/mgsc_daw_client.py"

cat <<EOF
Container is ready:
  name: $CONTAINER_NAME
  image: $IMAGE_NAME
  service port: host $HOST_PORT -> container $CONTAINER_PORT
  external API: http://<ubuntu-server-ip>:$HOST_PORT/v1/render

Start the service:
  docker exec -it $CONTAINER_NAME bash
  cd /home/workspace
  python mgsc_daw_service.py

From another terminal:
  python mgsc_daw_client.py --server http://127.0.0.1:$HOST_PORT --zip /path/to/bundle.zip --output output.mp3

Use a custom public host port:
  HOST_PORT=18000 ./deploy_mgsc_daw_service.sh

Runtime files:
  $RUNTIME_DIR/output
  $RUNTIME_DIR/logs
  $RUNTIME_DIR/service_work
EOF
