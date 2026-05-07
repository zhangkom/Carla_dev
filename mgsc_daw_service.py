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
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from xml.sax.saxutils import escape


WORKSPACE = Path(os.environ.get("DAW_WORKSPACE", "/home/workspace"))
RUNTIME_ROOT = Path(os.environ.get("DAW_RUNTIME_ROOT", "/home/runtime"))
WINEPREFIX = Path(os.environ.get("WINEPREFIX", "/wineprefix"))
WINEPREFIX_SEED = Path(os.environ.get("WINEPREFIX_SEED", "/home/runtime/wineprefix_seed"))
PLUGIN_MARKER = WINEPREFIX / "drive_c" / "VSTPlugins" / "KongAudio" / "Qin_RV.DLL"
KONG_QIN_RV_LIBRARY_INSTRUMENTS = (
    "ChineeGaoHu",
    "ChineeYangQin",
    "ChineeGuZheng_Classic",
)
STEINBERG_VST_PLUGINS = (
    "ABPL",
    "AGML",
    "DRUM PRO",
    "DSK Asian DreamZ",
    "DSK ElectriK GuitarZ",
    "DSK Saxophones",
    "EZkeys",
    "Keyzone Classic",
    "MTPDK-2.1.4-VST2-64bit-Windows-FULL",
    "Sonatina Orchestra",
    "Sylenth1",
    "Tunefish4",
    "Vital",
)
STEINBERG_VST_STATE_SPECS = (
    {
        "preset": "Keyzone Classic/Keyzone Classic/Steinway Piano.txt",
        "state": "keyzone_steinway_piano.carxs",
        "plugin_name": "Keyzone Classic",
        "binary": "/wineprefix/drive_c/VSTPlugins/Keyzone Classic/Keyzone Classic.dll",
    },
    {
        "preset": "DSK Saxophones/DSK Saxophones/Soprano Sax.txt",
        "state": "dsk_soprano_sax.carxs",
        "plugin_name": "DSK Saxophones",
        "binary": "/wineprefix/drive_c/VSTPlugins/DSK Saxophones/DSK Saxophones.dll",
    },
    {
        "preset": "Sonatina Orchestra/Sonatina Orchestra/Sonatina Violin/Solo Violin.txt",
        "state": "sonatina_solo_violin.carxs",
        "plugin_name": "Sonatina Orchestra",
        "binary": "/wineprefix/drive_c/VSTPlugins/Sonatina Orchestra/Sonatina Orchestra.dll",
    },
)


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
        if target_dir.is_dir() and any(target_dir.glob("*.dll")):
            continue

        if target_dir.exists():
            shutil.rmtree(target_dir)
        log(f"materializing Steinberg VST: {source_dir} -> {target_dir}")
        shutil.copytree(source_dir, target_dir)


def ensure_kong_qin_rv_libraries() -> None:
    if os.environ.get("KONG_QIN_RV_LIBRARY_MATERIALIZE", "true").lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return

    source_root = Path(
        os.environ.get(
            "KONG_QIN_RV_LIBRARY_SOURCE",
            str(WORKSPACE / "assets" / "kong_audio" / "qin_rv_v2_2" / "library"),
        )
    )
    target_root = Path(
        os.environ.get(
            "KONG_QIN_RV_LIBRARY_TARGET",
            str(WINEPREFIX / "kong-library-drive" / "Kong Audio Library"),
        )
    )
    instrument_names = split_env_list(
        os.environ.get(
            "KONG_QIN_RV_LIBRARY_INSTRUMENTS",
            ",".join(KONG_QIN_RV_LIBRARY_INSTRUMENTS),
        )
    )
    if all(
        (target_root / instrument_name / f"{instrument_name}.KAI").is_file()
        for instrument_name in instrument_names
    ):
        return

    if not source_root.is_dir():
        log(f"Kong Qin_RV library source missing, skip: {source_root}")
        return

    target_root.mkdir(parents=True, exist_ok=True)

    for instrument_name in instrument_names:
        source_dir = source_root / instrument_name
        if not source_dir.is_dir():
            log(f"Kong Qin_RV instrument source missing, skip: {source_dir}")
            continue

        target_dir = target_root / instrument_name
        target_kai = target_dir / f"{instrument_name}.KAI"
        if target_kai.is_file():
            continue

        if target_dir.exists():
            shutil.rmtree(target_dir)
        log(f"materializing Kong Qin_RV instrument: {source_dir} -> {target_dir}")
        shutil.copytree(source_dir, target_dir)


def read_vst2_chunk(preset_path: Path) -> str:
    text = preset_path.read_text(encoding="utf-8", errors="ignore").strip()
    chunk = "".join(line.strip() for line in text.splitlines() if line.strip())
    if not chunk:
        raise RuntimeError(f"VST2 preset chunk is empty: {preset_path}")
    if not re.fullmatch(r"[A-Za-z0-9+/=]+", chunk):
        raise RuntimeError(f"VST2 preset chunk is not base64 text: {preset_path}")
    return chunk


def build_vst2_state_xml(
    plugin_name: str,
    binary: str,
    chunk: str,
    unique_id: int = 0,
    volume: str = "1.0",
    control_channel: str = "-1",
    options: str = "0x3fb",
) -> str:
    return """<?xml version='1.0' encoding='UTF-8'?>
<!DOCTYPE CARLA-PRESET>
<CARLA-PRESET VERSION='2.0'>
  <Info>
   <Type>VST2</Type>
   <Name>{plugin_name}</Name>
   <Binary>{binary}</Binary>
   <UniqueID>{unique_id}</UniqueID>
  </Info>

  <Data>
   <Active>Yes</Active>
   <Volume>{volume}</Volume>
   <ControlChannel>{control_channel}</ControlChannel>
   <Options>{options}</Options>

   <Chunk>
{chunk}
   </Chunk>
  </Data>
</CARLA-PRESET>
""".format(
        plugin_name=escape(plugin_name),
        binary=escape(binary),
        unique_id=unique_id,
        volume=escape(volume),
        control_channel=escape(control_channel),
        options=escape(options),
        chunk=chunk,
    )


def resolve_state_path(value: str, state_root: Path) -> Path:
    state_path = Path(value)
    if state_path.is_absolute():
        return state_path
    if len(state_path.parts) > 1:
        return WORKSPACE / state_path
    return state_root / state_path


def load_steinberg_vst_state_specs() -> list[dict[str, str]]:
    config_path = Path(
        os.environ.get("MUSIC_SERVICE_CONFIG", str(WORKSPACE / "config" / "plugins.deploy.json"))
    )
    if not config_path.is_file():
        return list(STEINBERG_VST_STATE_SPECS)

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log(f"failed to read VST state specs from config, use fallback: {exc}")
        return list(STEINBERG_VST_STATE_SPECS)

    plugins = {
        str(plugin.get("id", "")): plugin
        for plugin in data.get("plugins", [])
        if isinstance(plugin, dict)
    }
    specs: list[dict[str, str]] = []
    for style in data.get("styles", []):
        if not isinstance(style, dict):
            continue
        preset = str(style.get("vst2_preset", "")).strip()
        state = str(style.get("state", "")).strip()
        if not preset or not state:
            continue

        plugin = plugins.get(str(style.get("plugin_id", "")).strip())
        if not plugin or str(plugin.get("type", "")).lower() != "vst2":
            continue

        specs.append(
            {
                "preset": preset,
                "state": state,
                "plugin_name": str(plugin.get("name") or style.get("plugin_id")),
                "binary": str(plugin.get("path") or ""),
            }
        )

    if not specs:
        return list(STEINBERG_VST_STATE_SPECS)
    return specs


def ensure_steinberg_vst_states() -> None:
    if os.environ.get("STEINBERG_VST_STATES", "true").lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return

    vst_root = Path(
        os.environ.get("STEINBERG_VST_TARGET", str(WINEPREFIX / "drive_c" / "VSTPlugins"))
    )
    state_root = Path(os.environ.get("STEINBERG_VST_STATE_DIR", str(WORKSPACE / "states" / "generated")))
    force = os.environ.get("STEINBERG_VST_STATES_FORCE", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    state_root.mkdir(parents=True, exist_ok=True)

    for spec in load_steinberg_vst_state_specs():
        preset_path = vst_root / spec["preset"]
        if not preset_path.is_file():
            log(f"Steinberg VST preset missing, skip state: {preset_path}")
            continue

        state_path = resolve_state_path(spec["state"], state_root)
        if state_path.is_file() and not force:
            continue

        state_path.parent.mkdir(parents=True, exist_ok=True)
        chunk = read_vst2_chunk(preset_path)
        state_path.write_text(
            build_vst2_state_xml(
                plugin_name=spec["plugin_name"],
                binary=spec["binary"],
                chunk=chunk,
            ),
            encoding="utf-8",
        )
        log(f"generated Steinberg VST state: {state_path}")


def main() -> int:
    set_default_env()
    ensure_runtime_dirs()
    ensure_wineprefix()
    ensure_kong_qin_rv_libraries()
    ensure_steinberg_vst_plugins()
    ensure_steinberg_vst_states()
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
