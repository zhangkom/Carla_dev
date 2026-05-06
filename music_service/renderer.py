# /**
# * File name: renderer.py
# * Brief: MIDI 渲染子进程调度模块
# * Function:
# *     调用 Carla 渲染器生成 WAV 并在服务进程中编码 MP3
# * Author: 咪咕数创工程架构组
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

from .config import ParameterOverride, PluginProfile, ServiceConfig


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


def _read_process_stream(stream: TextIO, lines: list[str], stream_name: str) -> None:
    try:
        for line in iter(stream.readline, ""):
            lines.append(line)
            stripped = line.strip()
            if stripped.startswith("RENDER_EVENT "):
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
            "-b:a",
            str(encoding.get("mp3_bitrate") or config.encoding.mp3_bitrate),
            "-compression_level",
            "0",
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
) -> RenderResult:
    if not plugin.enabled:
        raise RenderError(f"Plugin profile is disabled: {plugin.id}")
    if not plugin.path.is_file():
        raise RenderError(f"Plugin binary not found: {plugin.path}")
    selected_state = plugin_state if plugin_state is not None else plugin.state
    if selected_state and not selected_state.is_file():
        raise RenderError(f"Plugin state file not found: {selected_state}")
    if not midi_path.is_file():
        raise RenderError(f"MIDI file not found: {midi_path}")

    script_path = config.carla_root / "render_midi_to_mp3.py"
    if not script_path.is_file():
        raise RenderError(f"Renderer script not found: {script_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    renderer_plugin_path = plugin.runtime_path or _renderer_path(config, plugin.path)
    command = [
        config.python_executable,
        _renderer_path(config, script_path),
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
        str(config.audio.buffer_size),
        "--sample-rate",
        str(config.audio.sample_rate),
        "--mp3-bitrate",
        config.encoding.mp3_bitrate,
        "--mp3-sample-rate",
        str(config.encoding.mp3_sample_rate or config.audio.sample_rate),
        "--mp3-channels",
        str(config.encoding.mp3_channels),
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
    renderer_skips_mp3 = config.renderer_path_mode in {"wine", "native_bridge"}
    if config.ffmpeg and not renderer_skips_mp3:
        command += ["--ffmpeg", _renderer_executable(config, config.ffmpeg)]
    if max_seconds is not None:
        command += ["--max-seconds", str(max_seconds)]
    if renderer_skips_mp3:
        command += ["--skip-mp3"]

    started = time.monotonic()
    env = os.environ.copy()
    if config.audio.driver.strip().lower() == "dummy":
        env.setdefault("CARLA_DUMMY_OFFLINE", "1")
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
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_read_process_stream,
        args=(process.stderr, stderr_lines, "stderr"),
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
    encoding = result.get("encoding", {})
    if not isinstance(encoding, dict):
        encoding = {}
    if not wav_path.is_file():
        raise RenderError(f"WAV output missing: {wav_path}")
    if renderer_skips_mp3:
        try:
            _encode_mp3_with_linux_ffmpeg(config, wav_path, mp3_path, encoding, timings)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RenderError(f"Linux ffmpeg MP3 encode failed: {exc}") from exc
    if not mp3_path.is_file():
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
