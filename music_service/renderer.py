from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import ParameterOverride, PluginProfile, ServiceConfig


class RenderError(RuntimeError):
    pass


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


def run_render(
    config: ServiceConfig,
    plugin: PluginProfile,
    midi_path: Path,
    output_dir: Path,
    style_name: str | None = None,
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
    command = [
        config.python_executable,
        str(script_path),
        "--json",
        "--midi",
        str(midi_path),
        "--output-dir",
        str(output_dir),
        "--plugin-type",
        plugin.type,
        "--plugin-path",
        str(plugin.path),
        "--plugin-name",
        plugin.name,
        "--plugin-label",
        plugin.label,
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

    if style_name:
        command += ["--style-name", style_name]
    if selected_state:
        command += ["--plugin-state", str(selected_state)]
    for parameter in parameter_overrides:
        command += ["--set-param", f"{parameter.index}={parameter.value}"]
    if config.ffmpeg:
        command += ["--ffmpeg", config.ffmpeg]
    if max_seconds is not None:
        command += ["--max-seconds", str(max_seconds)]

    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=str(config.carla_root),
        capture_output=True,
        text=True,
        timeout=config.render_timeout_seconds,
        check=False,
    )
    elapsed = time.monotonic() - started

    if completed.returncode != 0:
        raise RenderError(
            "Renderer failed with exit code "
            f"{completed.returncode}. stdout={completed.stdout!r} stderr={completed.stderr!r}"
        )

    result = _extract_json_result(completed.stdout)
    mp3_path = Path(result["mp3"]).resolve()
    wav_path = Path(result["wav"]).resolve()
    timings = result.get("timings", {})
    if not isinstance(timings, dict):
        timings = {}
    timings["subprocess_seconds"] = round(elapsed, 3)
    encoding = result.get("encoding", {})
    if not isinstance(encoding, dict):
        encoding = {}
    if not mp3_path.is_file():
        raise RenderError(f"MP3 output missing: {mp3_path}")
    if not wav_path.is_file():
        raise RenderError(f"WAV output missing: {wav_path}")

    return RenderResult(
        mp3_path=mp3_path,
        wav_path=wav_path,
        elapsed_seconds=elapsed,
        timings=timings,
        encoding=encoding,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
