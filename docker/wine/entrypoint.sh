#!/usr/bin/env bash
set -euo pipefail

export WINEPREFIX="${WINEPREFIX:-/wineprefix}"
export DISPLAY="${DISPLAY:-:99}"
export WINEDEBUG="${WINEDEBUG:--all}"

mkdir -p "$WINEPREFIX" /app/output /app/service_work /app/logs

if ! pgrep -f "Xvfb ${DISPLAY}" >/dev/null 2>&1; then
  Xvfb "$DISPLAY" -screen 0 1280x720x24 >/tmp/xvfb.log 2>&1 &
fi

wineboot -u >/tmp/wineboot.log 2>&1 || true

mkdir -p "$WINEPREFIX/dosdevices"
if [ -d /kong-library ]; then
  ln -sfn /kong-library "$WINEPREFIX/dosdevices/e:"
fi

exec "$@"
