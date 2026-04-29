#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-mgsc_daw_service:v6.4.30}"
CONTAINER_NAME="${CONTAINER_NAME:-mgsc_daw_service_kom}"
IMAGE_TAR="${IMAGE_TAR:-mgsc_daw_service_v6.4.30.tar}"
HOST_PORT="${HOST_PORT:-8000}"
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
  -p "$HOST_PORT:8000" \
  -e TZ=Asia/Shanghai \
  -e MUSIC_SERVICE_CONFIG=/home/workspace/config/plugins.deploy.json \
  -e WINEPREFIX=/wineprefix \
  -e DAW_RUNTIME_ROOT=/home/runtime \
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
  service port: $HOST_PORT

Start the service:
  docker exec -it $CONTAINER_NAME bash
  cd /home/workspace
  python mgsc_daw_service.py

From another terminal:
  python mgsc_daw_client.py --zip /path/to/bundle.zip --output output.mp3

Runtime files:
  $RUNTIME_DIR/output
  $RUNTIME_DIR/logs
  $RUNTIME_DIR/service_work
EOF
