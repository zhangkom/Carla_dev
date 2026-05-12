# /**
# * File name: render_outputs.py
# * Brief: MGSC DAW 渲染输出处理模块
# * Function:
# *     生成安全文件名、混音/编码 MP3、构建 base64 响应和渲染 timing 摘要
# * Author: 咪咕数创工程架构组
# *     MGSC AI Software Architecture group
# * Version: V2.5.10
# * Date: 2026/05/01
# */

from __future__ import annotations

import base64
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .config import ServiceConfig
from .renderer import RenderError


def sanitize_filename_component(value: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*\s]+', "_", value.strip())
    sanitized = re.sub(r"_+", "_", sanitized).strip("._")
    return sanitized or "untitled"


def recorder_safe_basename(output_basename: str, job_id: str) -> str:
    if output_basename.isascii():
        return output_basename
    return f"render_{job_id}"


def float_timing(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def base64_mp3_payload(mp3_path: Path) -> dict[str, object]:
    raw = mp3_path.read_bytes()
    return {
        "filename": mp3_path.name,
        "mime_type": "audio/mpeg",
        "encoding": "base64",
        "size_bytes": len(raw),
        "base64": base64.b64encode(raw).decode("ascii"),
    }


def mix_wav_files(
    config: ServiceConfig,
    wav_paths: list[Path],
    output_path: Path,
) -> dict[str, object]:
    if not wav_paths:
        raise RenderError("Auto route did not produce any WAV files")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    if len(wav_paths) == 1:
        shutil.copy2(wav_paths[0], output_path)
        return {
            "mix_wav_seconds": round(time.monotonic() - started, 3),
            "mix_input_count": 1,
            "wav_bytes": file_size(output_path),
        }

    ffmpeg = config.ffmpeg or "ffmpeg"
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for wav_path in wav_paths:
        command.extend(["-i", str(wav_path)])
    command.extend(
        [
            "-filter_complex",
            f"amix=inputs={len(wav_paths)}:duration=longest:dropout_transition=0:normalize=0[mix]",
            "-map",
            "[mix]",
            "-ar",
            str(config.audio.sample_rate),
            "-ac",
            str(config.encoding.mp3_channels),
            str(output_path),
        ]
    )
    subprocess.run(command, check=True)
    return {
        "mix_wav_seconds": round(time.monotonic() - started, 3),
        "mix_input_count": len(wav_paths),
        "wav_bytes": file_size(output_path),
    }


def encode_mp3_file(
    config: ServiceConfig,
    wav_path: Path,
    mp3_path: Path,
) -> dict[str, object]:
    ffmpeg = config.ffmpeg or "ffmpeg"
    mode_args = ["-q:a", str(config.encoding.mp3_quality)]
    if config.encoding.mp3_mode == "cbr":
        mode_args = ["-b:a", config.encoding.mp3_bitrate]

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
            str(config.encoding.mp3_sample_rate or config.audio.sample_rate),
            "-ac",
            str(config.encoding.mp3_channels),
            "-codec:a",
            "libmp3lame",
            *mode_args,
            "-compression_level",
            str(config.encoding.mp3_compression_level),
            "-id3v2_version",
            str(config.encoding.mp3_id3v2_version),
            "-write_id3v1",
            "1",
            str(mp3_path),
        ],
        check=True,
    )
    return {
        "ffmpeg_mp3_seconds": round(time.monotonic() - started, 3),
        "mp3_bytes": file_size(mp3_path),
    }


def render_timing_summary(
    *,
    timings: dict[str, float],
    renderer_timings: dict[str, Any],
    mp3_path: Path,
    wav_path: Path,
) -> dict[str, object]:
    request_total = float_timing(timings.get("request_total_seconds"))
    renderer_total = float_timing(renderer_timings.get("total_seconds"))
    subprocess_total = float_timing(renderer_timings.get("subprocess_seconds"))
    return {
        "mp3_generation_seconds": request_total,
        "renderer_total_seconds": renderer_total or subprocess_total,
        "record_audio_seconds": float_timing(renderer_timings.get("record_audio_seconds")),
        "ffmpeg_mp3_seconds": float_timing(renderer_timings.get("ffmpeg_mp3_seconds")),
        "midi_policy_seconds": float_timing(timings.get("midi_policy_seconds")),
        "output_finalize_seconds": float_timing(timings.get("output_finalize_seconds")),
        "mp3_base64_seconds": float_timing(timings.get("mp3_base64_seconds")),
        "mp3_bytes": file_size(mp3_path),
        "wav_bytes": file_size(wav_path),
    }


def renderer_stage_seconds(renderer_timings: dict[str, Any]) -> dict[str, float]:
    ignored = {
        "midi_length_seconds",
        "record_target_seconds",
        "subprocess_seconds",
        "total_seconds",
    }
    stages: dict[str, float] = {}
    for key, value in renderer_timings.items():
        if key in ignored or not key.endswith("_seconds"):
            continue
        parsed = float_timing(value)
        if parsed is not None:
            stages[key] = parsed
    return dict(sorted(stages.items(), key=lambda item: item[1], reverse=True))


def renderer_record_audio_breakdown(renderer_timings: dict[str, Any]) -> dict[str, object]:
    breakdown_keys = [
        "record_audio_seconds",
        "transport_relocate_seconds",
        "transport_play_seconds",
        "record_idle_wall_seconds",
        "record_idle_engine_idle_seconds",
        "record_idle_sleep_seconds",
        "record_idle_loop_overhead_seconds",
        "transport_pause_seconds",
        "post_pause_idle_seconds",
        "post_pause_idle_wall_seconds",
        "post_pause_idle_engine_idle_seconds",
        "post_pause_idle_sleep_seconds",
        "post_pause_idle_loop_overhead_seconds",
    ]
    breakdown: dict[str, object] = {}
    for key in breakdown_keys:
        parsed = float_timing(renderer_timings.get(key))
        if parsed is not None:
            breakdown[key] = parsed
    for key in ("record_idle_iterations", "post_pause_idle_iterations"):
        value = renderer_timings.get(key)
        if isinstance(value, bool) or value is None:
            continue
        try:
            breakdown[key] = int(value)
        except (TypeError, ValueError):
            continue
    return breakdown
