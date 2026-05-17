# /**
# * File name: renderer.py
# * Brief: MIDI 渲染子进程调度模块
# * Function:
# *     调用 Carla 渲染器生成 WAV 并在服务进程中编码 MP3
# * Author: 软件工程架构组
# *     MGSC AI Software Architecture group
# * Version: V2.5.10
# * Date: 2026/04/30
# */
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, TextIO

from .config import ParameterOverride, PluginProfile, ServiceConfig, plugin_path_exists


class RenderError(RuntimeError):
    pass


_LOGGER = logging.getLogger("music_service")


@dataclass(frozen=True)
class RenderResult:
    mp3_path: Path
    wav_path: Path
    elapsed_seconds: float
    timings: dict[str, Any]
    encoding: dict[str, Any]
    stdout: str
    stderr: str


def _env_enabled(name: str) -> bool:
    value = os.environ.get(name, "").strip().lower()
    return bool(value) and value not in {"0", "false", "off", "no"}


def _env_csv_set(name: str, default: str = "") -> set[str]:
    value = os.environ.get(name, default)
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def _plugin_match_candidates(plugin: PluginProfile) -> set[str]:
    return {
        candidate.strip().lower()
        for candidate in {
            plugin.id,
            plugin.name,
            plugin.label,
            plugin.path.name,
            str(plugin.path),
        }
        if candidate and candidate.strip()
    }


def _env_plugin_value(name: str, plugin: PluginProfile) -> str | None:
    candidates = _plugin_match_candidates(plugin)
    raw_value = os.environ.get(name, "")
    for item in re.split(r"[;,]", raw_value):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        if key.strip().lower() in candidates:
            value = value.strip()
            if value:
                return value
    return None


def _positive_float_text(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = float(value)
    except ValueError:
        raise RenderError(f"Expected a positive numeric value, got: {value!r}") from None
    if parsed <= 0:
        raise RenderError(f"Expected a positive numeric value, got: {value!r}")
    return value.strip()


def _positive_int_text(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = int(value)
    except ValueError:
        raise RenderError(f"Expected a positive integer value, got: {value!r}") from None
    if parsed <= 0:
        raise RenderError(f"Expected a positive integer value, got: {value!r}")
    return str(parsed)


def _dummy_sleep_divisor_for_plugin(plugin: PluginProfile) -> str | None:
    return _positive_float_text(
        _env_plugin_value("MUSIC_SERVICE_DUMMY_SLEEP_DIVISOR_BY_PLUGIN", plugin)
        or os.environ.get("MUSIC_SERVICE_DUMMY_SLEEP_DIVISOR")
    )


def _warmup_seconds_for_plugin(plugin: PluginProfile) -> str | None:
    return _positive_float_text(
        _env_plugin_value("MUSIC_SERVICE_RENDER_WARMUP_SECONDS_BY_PLUGIN", plugin)
        or os.environ.get("MUSIC_SERVICE_RENDER_WARMUP_SECONDS")
    )


def _buffer_size_for_plugin(config: ServiceConfig, plugin: PluginProfile) -> str:
    return _positive_int_text(
        _env_plugin_value("MUSIC_SERVICE_BUFFER_SIZE_BY_PLUGIN", plugin)
        or os.environ.get("MUSIC_SERVICE_BUFFER_SIZE")
    ) or str(config.audio.buffer_size)


def _dummy_nosleep_disabled_for_plugin(plugin: PluginProfile) -> bool:
    disabled_plugins = _env_csv_set(
        "MUSIC_SERVICE_DUMMY_NOSLEEP_DISABLE_PLUGINS",
        "vst_keyzone_classic",
    )
    if not disabled_plugins:
        return False
    candidates = {
        plugin.id,
        plugin.name,
        plugin.label,
        plugin.path.name,
        str(plugin.path),
    }
    return any(candidate.strip().lower() in disabled_plugins for candidate in candidates if candidate)


def _extract_json_result(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        candidates = [line]
        json_start = line.find("{")
        if json_start > 0:
            candidates.append(line[json_start:])
        for candidate in candidates:
            try:
                value = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and "mp3" in value and "wav" in value:
                return value
    raise RenderError(f"Renderer did not return JSON output. stdout={stdout!r}")


def _extract_renderer_events(stdout: str, stderr: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for raw_line in [*stdout.splitlines(), *stderr.splitlines()]:
        line = raw_line.strip()
        if not line.startswith("RENDER_EVENT "):
            continue
        try:
            event = json.loads(line[len("RENDER_EVENT ") :])
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _read_process_stream(
    stream: TextIO,
    lines: list[str],
    stream_name: str,
    *,
    log_renderer_events: bool,
) -> None:
    try:
        for line in iter(stream.readline, ""):
            lines.append(line)
            stripped = line.strip()
            if log_renderer_events and stripped.startswith("RENDER_EVENT "):
                _LOGGER.info("renderer event stream=%s %s", stream_name, stripped)
    finally:
        stream.close()


def _is_windows_path(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value))


def _to_wine_path(path: Path | str) -> str:
    text = str(path)
    if _is_windows_path(text):
        return text.replace("/", "\\")
    resolved = Path(text).resolve()
    return "Z:" + str(resolved).replace("/", "\\")


def _from_wine_path(path: str) -> Path:
    normalized = path.replace("/", "\\")
    if normalized.lower().startswith("z:\\"):
        return Path("/" + normalized[3:].replace("\\", "/")).resolve()
    return Path(path).resolve()


def _renderer_path(config: ServiceConfig, path: Path | str) -> str:
    if config.renderer_path_mode == "wine":
        return _to_wine_path(path)
    return str(path)


def _renderer_executable(config: ServiceConfig, value: str) -> str:
    if not _is_windows_path(value) and "/" not in value and "\\" not in value:
        return value
    return _renderer_path(config, value)


def _result_path(config: ServiceConfig, path: str) -> Path:
    if config.renderer_path_mode == "wine":
        return _from_wine_path(path)
    return Path(path).resolve()


def _encode_mp3_with_linux_ffmpeg(
    config: ServiceConfig,
    wav_path: Path,
    mp3_path: Path,
    encoding: dict[str, Any],
    timings: dict[str, Any],
) -> None:
    ffmpeg = config.ffmpeg or "ffmpeg"
    mp3_mode = str(encoding.get("mp3_mode") or config.encoding.mp3_mode).lower()
    mode_args = ["-q:a", str(encoding.get("mp3_quality", config.encoding.mp3_quality))]
    if mp3_mode == "cbr":
        mode_args = ["-b:a", str(encoding.get("mp3_bitrate") or config.encoding.mp3_bitrate)]

    started = time.monotonic()
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(wav_path),
            "-map",
            "0:a:0",
            "-vn",
            "-ar",
            str(encoding.get("mp3_sample_rate") or config.audio.sample_rate),
            "-ac",
            str(encoding.get("mp3_channels") or config.encoding.mp3_channels),
            "-codec:a",
            "libmp3lame",
            *mode_args,
            "-compression_level",
            str(encoding.get("mp3_compression_level", config.encoding.mp3_compression_level)),
            "-id3v2_version",
            str(encoding.get("mp3_id3v2_version") or config.encoding.mp3_id3v2_version),
            "-write_id3v1",
            "1",
            str(mp3_path),
        ],
        check=True,
    )
    elapsed = round(time.monotonic() - started, 3)
    timings["linux_ffmpeg_mp3_seconds"] = elapsed
    timings["ffmpeg_mp3_seconds"] = elapsed
    timings["mp3_bytes"] = mp3_path.stat().st_size if mp3_path.is_file() else 0


def _build_renderer_command(
    config: ServiceConfig,
    plugin: PluginProfile,
    midi_path: Path,
    output_dir: Path,
    *,
    style_name: str | None,
    output_basename: str | None,
    max_seconds: float | None,
    selected_state: Path | None,
    parameter_overrides: Iterable[ParameterOverride],
    encode_mp3: bool,
    debug: bool,
) -> tuple[list[str], bool, str | None, str]:
    renderer_plugin_path = plugin.runtime_path or _renderer_path(config, plugin.path)
    buffer_size = _buffer_size_for_plugin(config, plugin)
    command = [
        config.python_executable,
        _renderer_path(config, config.carla_root / "render_midi_to_mp3.py"),
        "--json",
        "--midi",
        _renderer_path(config, midi_path),
        "--output-dir",
        _renderer_path(config, output_dir),
        "--plugin-type",
        plugin.type,
        "--plugin-path",
        renderer_plugin_path,
        "--plugin-name",
        plugin.name,
        "--plugin-label",
        plugin.label,
        "--plugin-load-mode",
        config.plugin_load_mode,
        "--audio-driver",
        config.audio.driver,
        "--audio-device",
        config.audio.device,
        "--buffer-size",
        buffer_size,
        "--sample-rate",
        str(config.audio.sample_rate),
        "--mp3-bitrate",
        config.encoding.mp3_bitrate,
        "--mp3-mode",
        config.encoding.mp3_mode,
        "--mp3-quality",
        str(config.encoding.mp3_quality),
        "--mp3-sample-rate",
        str(config.encoding.mp3_sample_rate or config.audio.sample_rate),
        "--mp3-channels",
        str(config.encoding.mp3_channels),
        "--mp3-compression-level",
        str(config.encoding.mp3_compression_level),
        "--mp3-id3v2-version",
        str(config.encoding.mp3_id3v2_version),
    ]

    if config.carla_backend:
        command += ["--carla-backend", _renderer_path(config, config.carla_backend)]
    if config.carla_bin_dir:
        command += ["--carla-bin-dir", _renderer_path(config, config.carla_bin_dir)]
    if config.carla_resources_dir:
        command += ["--carla-resources-dir", _renderer_path(config, config.carla_resources_dir)]
    if config.carla_frontend_dir:
        command += ["--carla-frontend-dir", _renderer_path(config, config.carla_frontend_dir)]

    if style_name:
        command += ["--style-name", style_name]
    if output_basename:
        command += ["--output-basename", output_basename]
    if selected_state:
        command += ["--plugin-state", _renderer_path(config, selected_state)]
    for parameter in parameter_overrides:
        command += ["--set-param", f"{parameter.index}={parameter.value}"]
    warmup_seconds = _warmup_seconds_for_plugin(plugin)
    if warmup_seconds is not None:
        command += ["--warmup-seconds", warmup_seconds]
    command_skips_mp3 = config.renderer_path_mode in {"wine", "native_bridge"} or not encode_mp3
    if config.ffmpeg and not command_skips_mp3:
        command += ["--ffmpeg", _renderer_executable(config, config.ffmpeg)]
    if max_seconds is not None:
        command += ["--max-seconds", str(max_seconds)]
    if command_skips_mp3:
        command += ["--skip-mp3"]
    if debug:
        command += ["--progress-interval-seconds", "2"]
    return command, command_skips_mp3, warmup_seconds, buffer_size


def _build_renderer_env(
    config: ServiceConfig,
    plugin: PluginProfile,
    *,
    debug: bool,
) -> tuple[dict[str, str] | None, bool, bool, str | None, bool]:
    env = None
    dummy_nosleep_requested = config.audio.driver.strip().lower() == "dummy" and _env_enabled(
        "MUSIC_SERVICE_DUMMY_NOSLEEP"
    )
    dummy_nosleep_enabled = False
    dummy_sleep_divisor = _dummy_sleep_divisor_for_plugin(plugin) if dummy_nosleep_requested else None
    wav_stats_enabled = debug or _env_enabled("MUSIC_SERVICE_RENDER_WAV_STATS")
    if dummy_nosleep_requested or dummy_sleep_divisor is not None or wav_stats_enabled or debug:
        env = os.environ.copy()
        if wav_stats_enabled:
            env.setdefault("CARLA_RENDER_WAV_STATS", "1")
        if debug:
            env["CARLA_RENDER_DEBUG"] = "1"
        if dummy_sleep_divisor is not None:
            env["CARLA_DUMMY_SLEEP_DIVISOR"] = dummy_sleep_divisor
            env.pop("CARLA_DUMMY_NOSLEEP", None)
            dummy_nosleep_enabled = True
        elif dummy_nosleep_requested and _dummy_nosleep_disabled_for_plugin(plugin):
            env.pop("CARLA_DUMMY_NOSLEEP", None)
            _LOGGER.info(
                "renderer dummy nosleep disabled for plugin_id=%s plugin_name=%s",
                plugin.id,
                plugin.name,
            )
        elif dummy_nosleep_requested:
            env.setdefault("CARLA_DUMMY_NOSLEEP", "1")
            dummy_nosleep_enabled = True
    return env, dummy_nosleep_requested, dummy_nosleep_enabled, dummy_sleep_divisor, wav_stats_enabled


def run_render(
    config: ServiceConfig,
    plugin: PluginProfile,
    midi_path: Path,
    output_dir: Path,
    style_name: str | None = None,
    output_basename: str | None = None,
    max_seconds: float | None = None,
    plugin_state: Path | None = None,
    parameter_overrides: Iterable[ParameterOverride] = (),
    encode_mp3: bool = True,
    debug: bool = False,
) -> RenderResult:
    if not plugin.enabled:
        raise RenderError(f"Plugin profile is disabled: {plugin.id}")
    if not plugin_path_exists(plugin.type, plugin.path):
        raise RenderError(f"Plugin path not found or invalid for {plugin.type}: {plugin.path}")
    selected_state = plugin_state if plugin_state is not None else plugin.state
    if selected_state and not selected_state.is_file():
        raise RenderError(f"Plugin state file not found: {selected_state}")
    if not midi_path.is_file():
        raise RenderError(f"MIDI file not found: {midi_path}")

    script_path = config.carla_root / "render_midi_to_mp3.py"
    if not script_path.is_file():
        raise RenderError(f"Renderer script not found: {script_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    command, command_skips_mp3, warmup_seconds, buffer_size = _build_renderer_command(
        config,
        plugin,
        midi_path,
        output_dir,
        style_name=style_name,
        output_basename=output_basename,
        max_seconds=max_seconds,
        selected_state=selected_state,
        parameter_overrides=parameter_overrides,
        encode_mp3=encode_mp3,
        debug=debug,
    )

    started = time.monotonic()
    (
        env,
        dummy_nosleep_requested,
        dummy_nosleep_enabled,
        dummy_sleep_divisor,
        wav_stats_enabled,
    ) = _build_renderer_env(config, plugin, debug=debug)

    if debug:
        _LOGGER.info(
            "renderer start plugin_id=%s style_name=%s output=%s encode_mp3=%s",
            plugin.id,
            style_name,
            output_basename,
            encode_mp3,
        )
        _LOGGER.info(
            "renderer debug config plugin_id=%s plugin_name=%s command=%s env=%s selected_state=%s "
            "plugin_path=%s midi_path=%s output_dir=%s dummy_nosleep_requested=%s "
            "dummy_nosleep_enabled=%s dummy_sleep_divisor=%s warmup_seconds=%s buffer_size=%s "
            "wav_stats=%s audio_driver=%s",
            plugin.id,
            plugin.name,
            json.dumps(command, ensure_ascii=False),
            json.dumps(
                {
                    "CARLA_DUMMY_NOSLEEP": (env or os.environ).get("CARLA_DUMMY_NOSLEEP"),
                    "CARLA_DUMMY_SLEEP_DIVISOR": (env or os.environ).get("CARLA_DUMMY_SLEEP_DIVISOR"),
                    "CARLA_RENDER_DEBUG": (env or os.environ).get("CARLA_RENDER_DEBUG"),
                    "CARLA_RENDER_WAV_STATS": (env or os.environ).get("CARLA_RENDER_WAV_STATS"),
                    "WINEPREFIX": (env or os.environ).get("WINEPREFIX"),
                    "DISPLAY": (env or os.environ).get("DISPLAY"),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            str(selected_state) if selected_state else None,
            str(plugin.path),
            str(midi_path),
            str(output_dir),
            dummy_nosleep_requested,
            dummy_nosleep_enabled,
            dummy_sleep_divisor,
            warmup_seconds,
            buffer_size,
            wav_stats_enabled,
            config.audio.driver,
        )

    log_renderer_events = debug or _env_enabled("MUSIC_SERVICE_LOG_RENDER_EVENTS")
    process = subprocess.Popen(
        command,
        cwd=str(config.carla_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    stdout_thread = threading.Thread(
        target=_read_process_stream,
        args=(process.stdout, stdout_lines, "stdout"),
        kwargs={"log_renderer_events": log_renderer_events},
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_read_process_stream,
        args=(process.stderr, stderr_lines, "stderr"),
        kwargs={"log_renderer_events": log_renderer_events},
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    try:
        returncode = process.wait(timeout=config.render_timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        elapsed = time.monotonic() - started
        raise RenderError(
            f"Renderer timed out after {elapsed:.3f}s. "
            f"stdout={''.join(stdout_lines)!r} stderr={''.join(stderr_lines)!r}"
        ) from exc

    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)
    elapsed = time.monotonic() - started
    stdout = "".join(stdout_lines)
    stderr = "".join(stderr_lines)

    if returncode != 0:
        raise RenderError(
            "Renderer failed with exit code "
            f"{returncode}. stdout={stdout!r} stderr={stderr!r}"
        )

    result = _extract_json_result(stdout)
    mp3_path = _result_path(config, str(result["mp3"]))
    wav_path = _result_path(config, str(result["wav"]))
    timings = result.get("timings", {})
    if not isinstance(timings, dict):
        timings = {}
    timings["subprocess_seconds"] = round(elapsed, 3)
    if debug:
        timings["renderer_events"] = _extract_renderer_events(stdout, stderr)
    encoding = result.get("encoding", {})
    if not isinstance(encoding, dict):
        encoding = {}
    if not wav_path.is_file():
        raise RenderError(f"WAV output missing: {wav_path}")
    if command_skips_mp3 and encode_mp3:
        try:
            _encode_mp3_with_linux_ffmpeg(config, wav_path, mp3_path, encoding, timings)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RenderError(f"Linux ffmpeg MP3 encode failed: {exc}") from exc
    elif not encode_mp3:
        timings["linux_ffmpeg_mp3_seconds"] = 0.0
        timings["ffmpeg_mp3_seconds"] = 0.0
        timings["mp3_bytes"] = 0
    if encode_mp3 and not mp3_path.is_file():
        raise RenderError(f"MP3 output missing: {mp3_path}")

    return RenderResult(
        mp3_path=mp3_path,
        wav_path=wav_path,
        elapsed_seconds=elapsed,
        timings=timings,
        encoding=encoding,
        stdout=stdout,
        stderr=stderr,
    )
