#!/usr/bin/env bash
# /**
# * File name: mgsc-daw-entrypoint.sh
# * Brief: MGSC DAW Docker/Wine 入口脚本
# * Function:
# *     初始化 Wine prefix、Xvfb 和运行目录后启动容器命令
# * Author: 咪咕数创工程架构组
# *     MGSC AI Software Architecture group
# * Version: V2.5.10
# * Date: 2026/05/09
# */
set -euo pipefail

export WINEPREFIX="${WINEPREFIX:-/wineprefix}"
export DISPLAY="${DISPLAY:-:99}"
export WINEDEBUG="${WINEDEBUG:--all}"
export VNC_GEOMETRY="${VNC_GEOMETRY:-1280x720}"
export WINE_BIN="${WINE_BIN:-wine}"

mkdir -p \
  "$WINEPREFIX" \
  /home/runtime/logs \
  /home/runtime/output \
  /home/runtime/service_work \
  /home/workspace/logs \
  /home/workspace/temp

echo "[mgsc_daw_service] entrypoint wine prefix: $WINEPREFIX"
if [ -f "$WINEPREFIX/system.reg" ]; then
  echo "[mgsc_daw_service] existing Wine prefix detected; skip wineboot"
elif command -v wineboot >/dev/null 2>&1; then
  timeout "${WINEBOOT_TIMEOUT_SECONDS:-300}" wineboot -u >/tmp/wineboot.log 2>&1 || {
    cat /tmp/wineboot.log >&2 || true
    exit 1
  }
elif command -v "$WINE_BIN" >/dev/null 2>&1; then
  timeout "${WINEBOOT_TIMEOUT_SECONDS:-300}" "$WINE_BIN" wineboot -u >/tmp/wineboot.log 2>&1 || {
    cat /tmp/wineboot.log >&2 || true
    exit 1
  }
fi

if command -v Xvfb >/dev/null 2>&1 && ! pgrep -f "Xvfb ${DISPLAY}" >/dev/null 2>&1; then
  echo "[mgsc_daw_service] starting Xvfb on $DISPLAY"
  Xvfb "$DISPLAY" -screen 0 "${VNC_GEOMETRY}x24" >/tmp/xvfb.log 2>&1 &
fi

mkdir -p "$WINEPREFIX/dosdevices"
[ -d /kong-installer ] && ln -sfn /kong-installer "$WINEPREFIX/dosdevices/d:"
if [ -d "$WINEPREFIX/kong-library-drive/Kong Audio Library" ]; then
  ln -sfn "$WINEPREFIX/kong-library-drive" "$WINEPREFIX/dosdevices/e:"
elif [ -d /kong-library ] && find /kong-library -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
  ln -sfn /kong-library "$WINEPREFIX/dosdevices/e:"
fi

cd /home/workspace
exec "$@"
