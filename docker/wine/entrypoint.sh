#!/usr/bin/env bash
# /**
# * File name: entrypoint.sh
# * Brief: MGSC DAW Docker/Wine 运行环境文件
# * Function:
# *     构建和启动云端 DAW 渲染服务所需的 Wine 容器运行环境
# * Author: 咪咕数创工程架构组
# *     MGSC AI Software Architecture group
# * Version: V2.5.10
# * Date: 2026/04/30
# */

set -euo pipefail

export WINEPREFIX="${WINEPREFIX:-/wineprefix}"
export DISPLAY="${DISPLAY:-:99}"
export WINEDEBUG="${WINEDEBUG:--all}"
export VNC_GEOMETRY="${VNC_GEOMETRY:-1280x720}"
export VNC_PORT="${VNC_PORT:-5900}"

if [ -z "${WINE_BIN:-}" ]; then
  if command -v wine >/dev/null 2>&1; then
    export WINE_BIN=wine
  elif command -v wine64-stable >/dev/null 2>&1; then
    export WINE_BIN=wine64-stable
  else
    export WINE_BIN=wine
  fi
fi

mkdir -p "$WINEPREFIX" /app/output /app/service_work /app/logs

if command -v wineboot >/dev/null 2>&1; then
  env -u DISPLAY timeout "${WINEBOOT_TIMEOUT_SECONDS:-300}" wineboot -u >/tmp/wineboot.log 2>&1 || {
    cat /tmp/wineboot.log >&2 || true
    exit 1
  }
else
  env -u DISPLAY timeout "${WINEBOOT_TIMEOUT_SECONDS:-300}" "$WINE_BIN" wineboot -u >/tmp/wineboot.log 2>&1 || {
    cat /tmp/wineboot.log >&2 || true
    exit 1
  }
fi

if ! pgrep -f "Xvfb ${DISPLAY}" >/dev/null 2>&1; then
  Xvfb "$DISPLAY" -screen 0 "${VNC_GEOMETRY}x24" >/tmp/xvfb.log 2>&1 &
fi

mkdir -p "$WINEPREFIX/dosdevices"
if [ -d /kong-installer ]; then
  ln -sfn /kong-installer "$WINEPREFIX/dosdevices/d:"
fi
if [ -d /kong-library ]; then
  kong_drive_root=/kong-library
  if [ "${KONG_LIBRARY_MATERIALIZE:-false}" = "true" ]; then
    kong_drive_root="$WINEPREFIX/kong-library-drive"
    mkdir -p "$kong_drive_root/Kong Audio Library"
    if [ -f /kong-library/Locate_Library_Here.exe ]; then
      cp -f /kong-library/Locate_Library_Here.exe "$kong_drive_root/Kong Audio Library/Locate_Library_Here.exe"
    fi
    old_ifs="$IFS"
    IFS=", "
    for folder in ${KONG_LIBRARY_FOLDERS:-}; do
      if [ -n "$folder" ] && [ -d "/kong-library/$folder" ] && [ ! -d "$kong_drive_root/Kong Audio Library/$folder" ]; then
        cp -a "/kong-library/$folder" "$kong_drive_root/Kong Audio Library/"
      fi
    done
    IFS="$old_ifs"
  fi
  ln -sfn "$kong_drive_root" "$WINEPREFIX/dosdevices/e:"

  python3 - <<'PY'
import os
from pathlib import Path

prefix = Path(os.environ.get("WINEPREFIX", "/wineprefix"))
xml_path = prefix / "drive_c" / "VSTPlugins" / "KongAudio" / "Qin_RV.XML"
library_root = Path(os.environ.get("KONG_LIBRARY_XML_ROOT", "E:\\Kong Audio Library"))
drive_target = (prefix / "dosdevices" / "e:")
if xml_path.exists() and drive_target.exists():
    real_root = drive_target / "Kong Audio Library"
    if real_root.exists():
        text = xml_path.read_text(encoding="utf-8", errors="ignore")
        updated = text
        for item in real_root.iterdir():
            if not item.is_dir():
                continue
            name = item.name
            updated = updated.replace(f"E:\\\\{name}", f"{library_root}\\{name}")
            updated = updated.replace(f"E:\\{name}", f"{library_root}\\{name}")
        if updated != text:
            xml_path.write_text(updated, encoding="utf-8")

system_reg = prefix / "system.reg"
instruments = [
    item.strip()
    for item in os.environ.get("KONG_REGISTER_INSTRUMENTS", "").replace(";", ",").split(",")
    if item.strip()
]
version = os.environ.get("KONG_INSTRUMENT_VERSION", "v2.1.2.0")
if instruments and system_reg.exists():
    text = system_reg.read_text(encoding="utf-8", errors="ignore")
    updated = text
    for instrument in instruments:
        key = f"[Software\\\\Wow6432Node\\\\Kong Audio\\\\Qin Engine\\\\{instrument}]"
        if key not in updated:
            updated += f"\n{key} 1777370714\n\"Version\"=\"{version}\"\n"
    if updated != text:
        system_reg.write_text(updated, encoding="utf-8")
PY
fi

if [ "${ENABLE_VNC:-false}" = "true" ]; then
  if command -v fluxbox >/dev/null 2>&1 && ! pgrep -f "fluxbox" >/dev/null 2>&1; then
    DISPLAY="$DISPLAY" fluxbox >/tmp/fluxbox.log 2>&1 &
  fi

  if command -v x11vnc >/dev/null 2>&1 && ! pgrep -f "x11vnc .*${DISPLAY}" >/dev/null 2>&1; then
    if [ -n "${VNC_PASSWORD:-}" ]; then
      mkdir -p /tmp/vnc
      x11vnc -storepasswd "$VNC_PASSWORD" /tmp/vnc/passwd >/tmp/x11vnc-passwd.log 2>&1
      DISPLAY="$DISPLAY" x11vnc -display "$DISPLAY" -rfbport "$VNC_PORT" -rfbauth /tmp/vnc/passwd -forever -shared -noxdamage -repeat >/tmp/x11vnc.log 2>&1 &
    else
      DISPLAY="$DISPLAY" x11vnc -display "$DISPLAY" -rfbport "$VNC_PORT" -nopw -forever -shared -noxdamage -repeat >/tmp/x11vnc.log 2>&1 &
    fi
  fi
fi

if [ "${START_WINEFILE:-false}" = "true" ]; then
  DISPLAY="$DISPLAY" "$WINE_BIN" winefile >/tmp/winefile.log 2>&1 &
fi

exec "$@"
