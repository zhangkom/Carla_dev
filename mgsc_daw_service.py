# /**
# * File name: mgsc_daw_service.py
# * Brief: 容器内 FastAPI 服务启动脚本
# * Function:
# *     初始化容器运行环境并启动 MGSC DAW FastAPI 渲染服务
# * Author: 咪咕数创工程架构组
# *     MGSC AI Software Architecture group
# * Version: V2.5.10
# * Date: 2026/04/30
# */
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


WORKSPACE = Path(os.environ.get("DAW_WORKSPACE", "/home/workspace"))
RUNTIME_ROOT = Path(os.environ.get("DAW_RUNTIME_ROOT", "/home/runtime"))
WINEPREFIX = Path(os.environ.get("WINEPREFIX", "/wineprefix"))
WINEPREFIX_SEED = Path(os.environ.get("WINEPREFIX_SEED", "/home/runtime/wineprefix_seed"))
PLUGIN_MARKER = WINEPREFIX / "drive_c" / "VSTPlugins" / "KongAudio" / "Qin_RV.DLL"
STEINBERG_VST_PLUGINS = ("Keyzone Classic", "DSK Saxophones", "Sonatina Orchestra")


def log(message: str) -> None:
    print(f"[mgsc_daw_service] {message}", flush=True)


def set_default_env() -> None:
    defaults = {
        "MUSIC_SERVICE_CONFIG": str(WORKSPACE / "config" / "plugins.deploy.json"),
        "WINEPREFIX": str(WINEPREFIX),
        "WINEARCH": "win64",
        "WINEDEBUG": "-all",
        "WINE_BIN": "wine",
        "DISPLAY": ":99",
        "TZ": "Asia/Shanghai",
        "PYTHONUNBUFFERED": "1",
    }
    for key, value in defaults.items():
        if not os.environ.get(key):
            os.environ[key] = value


def ensure_runtime_dirs() -> None:
    for path in (
        RUNTIME_ROOT,
        RUNTIME_ROOT / "output",
        RUNTIME_ROOT / "logs",
        RUNTIME_ROOT / "service_work",
        WINEPREFIX,
    ):
        path.mkdir(parents=True, exist_ok=True)

    workspace_logs = WORKSPACE / "logs"
    if not workspace_logs.exists():
        try:
            workspace_logs.symlink_to(RUNTIME_ROOT / "logs", target_is_directory=True)
        except OSError:
            workspace_logs.mkdir(parents=True, exist_ok=True)


def ensure_wineprefix() -> None:
    if PLUGIN_MARKER.is_file():
        return
    if not WINEPREFIX_SEED.is_dir():
        raise RuntimeError(f"Wine prefix seed not found: {WINEPREFIX_SEED}")

    log(f"seeding Wine prefix from {WINEPREFIX_SEED} to {WINEPREFIX}")
    if WINEPREFIX.exists():
        for item in WINEPREFIX.iterdir():
            if item.is_symlink() or item.is_file():
                item.unlink()
            else:
                shutil.rmtree(item)
    WINEPREFIX.mkdir(parents=True, exist_ok=True)
    shutil.copytree(WINEPREFIX_SEED, WINEPREFIX, symlinks=True, dirs_exist_ok=True)


def process_is_running(pattern: str) -> bool:
    try:
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def ensure_xvfb() -> None:
    display = os.environ.get("DISPLAY", ":99")
    if process_is_running(f"Xvfb {display}"):
        return
    if shutil.which("Xvfb") is None:
        log("Xvfb not found; continuing without starting a virtual display")
        return
    subprocess.Popen(
        ["Xvfb", display, "-screen", "0", "1280x720x24"],
        stdout=open("/tmp/mgsc-daw-xvfb.log", "ab"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    time.sleep(1.0)


def ensure_wineboot() -> None:
    if (WINEPREFIX / "system.reg").is_file():
        return
    wineboot = shutil.which("wineboot")
    if wineboot is None:
        log("wineboot not found; skipping Wine initialization")
        return
    subprocess.run(
        [wineboot, "-u"],
        stdout=open("/tmp/mgsc-daw-wineboot.log", "ab"),
        stderr=subprocess.STDOUT,
        check=False,
    )


def split_env_list(value: str) -> list[str]:
    return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]


def ensure_steinberg_vst_plugins() -> None:
    if os.environ.get("STEINBERG_VST_MATERIALIZE", "true").lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return

    source_root = Path(
        os.environ.get("STEINBERG_VST_SOURCE", str(WORKSPACE / "assets" / "Steinberg" / "VstPlugins"))
    )
    if not source_root.is_dir():
        return

    target_root = Path(
        os.environ.get("STEINBERG_VST_TARGET", str(WINEPREFIX / "drive_c" / "VSTPlugins"))
    )
    plugin_names = split_env_list(
        os.environ.get("STEINBERG_VST_PLUGINS", ",".join(STEINBERG_VST_PLUGINS))
    )
    target_root.mkdir(parents=True, exist_ok=True)

    for plugin_name in plugin_names:
        source_dir = source_root / plugin_name
        if not source_dir.is_dir():
            log(f"Steinberg VST source missing, skip: {source_dir}")
            continue

        target_dir = target_root / plugin_name
        target_dll = target_dir / f"{plugin_name}.dll"
        if target_dll.is_file():
            continue

        if target_dir.exists():
            shutil.rmtree(target_dir)
        log(f"materializing Steinberg VST: {source_dir} -> {target_dir}")
        shutil.copytree(source_dir, target_dir)


def main() -> int:
    set_default_env()
    ensure_runtime_dirs()
    ensure_wineprefix()
    ensure_steinberg_vst_plugins()
    ensure_xvfb()
    ensure_wineboot()

    os.chdir(WORKSPACE)
    port = os.environ.get("DAW_SERVICE_PORT", "8000")
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "music_service.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        port,
    ]
    log("starting service: " + " ".join(command))
    os.execvp(sys.executable, command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
