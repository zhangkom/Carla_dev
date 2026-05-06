#!/usr/bin/env python
# /**
# * File name: render_midi_to_mp3.py
# * Brief: MGSC DAW MIDI 渲染脚本
# * Function:
# *     调用 Carla 引擎加载插件并将 MIDI 渲染为 MP3/WAV 音频
# * Author: 咪咕数创工程架构组
# *     MGSC AI Software Architecture group
# * Version: V2.5.10
# * Date: 2026/04/30
# */

# -*- coding: utf-8 -*-

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a MIDI file through Carla + a VST2/VST3/SF2 plugin and export WAV/MP3."
    )
    parser.add_argument("--midi", required=True, help="Input MIDI file path")
    parser.add_argument(
        "--style-name",
        help="Style label used in the default output filename, for example orchestral or lofi.",
    )
    parser.add_argument(
        "--mp3",
        help="Output MP3 path. Defaults to <carla_root>/output/<song>_<style>.mp3.",
    )
    parser.add_argument(
        "--wav",
        help="Output WAV path. Defaults to <carla_root>/output/<song>_<style>.wav.",
    )
    parser.add_argument(
        "--output-dir",
        help="Default output directory used when --mp3/--wav are not set. Defaults to <carla_root>/output.",
    )
    parser.add_argument(
        "--output-basename",
        help="Explicit output filename base without extension. Overrides the default <song>_<style> name.",
    )
    parser.add_argument(
        "--keep-wav",
        action="store_true",
        help="Deprecated compatibility flag. WAV is kept by default now.",
    )
    parser.add_argument(
        "--surge-state",
        dest="surge_state",
        help="Optional Surge XT .carxs state file exported from Carla GUI.",
    )
    parser.add_argument(
        "--surge-vst3",
        default=r"C:\Program Files\Common Files\VST3\Surge Synth Team\Surge XT.vst3\Contents\x86_64-win\Surge XT.vst3",
        help="Path to Surge XT VST3 binary.",
    )
    parser.add_argument(
        "--plugin-type",
        choices=("vst2", "vst3", "sf2"),
        help="Plugin format to load. Defaults to VST3 for --surge-vst3 compatibility or inferred from --plugin-path.",
    )
    parser.add_argument(
        "--plugin-path",
        help="Path to the VST2 .dll or VST3 binary to load.",
    )
    parser.add_argument(
        "--plugin-name",
        help="Display name passed to Carla. Defaults to the plugin file stem.",
    )
    parser.add_argument(
        "--plugin-label",
        default="",
        help="Optional Carla plugin label. Usually empty for VST2/VST3 plugins.",
    )
    parser.add_argument(
        "--plugin-load-mode",
        choices=("add_plugin", "load_file"),
        default="add_plugin",
        help=(
            "How to load the instrument plugin. Use load_file for Linux Carla "
            "loading Windows VSTs through Carla's Wine bridge."
        ),
    )
    parser.add_argument(
        "--plugin-state",
        help="Optional .carxs state file exported from Carla GUI for the selected plugin.",
    )
    parser.add_argument(
        "--set-param",
        action="append",
        default=[],
        metavar="INDEX=VALUE",
        help="Override a Carla parameter on the instrument plugin after loading state. Can be repeated.",
    )
    parser.add_argument(
        "--audio-driver",
        default="DirectSound",
        help="Carla audio driver. Default: DirectSound",
    )
    parser.add_argument(
        "--audio-device",
        default="Primary Sound Driver",
        help="Audio output device. Default: Primary Sound Driver",
    )
    parser.add_argument(
        "--buffer-size", type=int, default=512, help="Audio buffer size. Default: 512"
    )
    parser.add_argument(
        "--sample-rate", type=int, default=44100, help="Sample rate. Default: 44100"
    )
    parser.add_argument(
        "--tail-seconds",
        type=float,
        default=2.0,
        help="Extra recording time after the MIDI ends. Default: 2.0",
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        help="Optional maximum render duration, useful for quick preview exports.",
    )
    parser.add_argument(
        "--warmup-seconds",
        type=float,
        default=0.3,
        help="Engine warmup time before measuring duration. Default: 0.3",
    )
    parser.add_argument(
        "--ffmpeg",
        help="Explicit ffmpeg executable path. Defaults to PATH lookup.",
    )
    parser.add_argument(
        "--carla-backend",
        help="Explicit Carla standalone backend library path, for example libcarla_standalone2.so.",
    )
    parser.add_argument(
        "--carla-bin-dir",
        help="Explicit Carla binaries directory. Defaults to <carla_root>/bin.",
    )
    parser.add_argument(
        "--carla-resources-dir",
        help="Explicit Carla resources directory. Defaults to <carla_root>/bin/resources.",
    )
    parser.add_argument(
        "--carla-frontend-dir",
        help="Explicit Carla Python frontend directory that contains carla_backend.py.",
    )
    parser.add_argument(
        "--skip-mp3",
        action="store_true",
        help="Render WAV only and skip MP3 encoding. The API service may encode MP3 outside Wine.",
    )
    parser.add_argument(
        "--mp3-bitrate",
        default="320k",
        help="MP3 bitrate for libmp3lame CBR output. Default: 320k",
    )
    parser.add_argument(
        "--mp3-sample-rate",
        type=int,
        help="MP3 sample rate. Defaults to --sample-rate.",
    )
    parser.add_argument(
        "--mp3-channels",
        type=int,
        choices=(1, 2),
        default=2,
        help="MP3 channel count. Default: 2 stereo.",
    )
    parser.add_argument(
        "--mp3-id3v2-version",
        type=int,
        choices=(3, 4),
        default=3,
        help="ID3v2 tag version for MP3 compatibility. Default: 3.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print a machine-readable JSON result.",
    )
    parser.add_argument(
        "--progress-interval-seconds",
        type=float,
        default=10.0,
        help="Renderer progress event interval written to stderr. Default: 10.0",
    )
    return parser


def resolve_script_paths(args: argparse.Namespace) -> tuple[Path, Path, Path, Path, Path]:
    carla_root = Path(__file__).resolve().parent
    bin_dir = Path(args.carla_bin_dir).expanduser().resolve() if args.carla_bin_dir else (carla_root / "bin")
    resources_dir = (
        Path(args.carla_resources_dir).expanduser().resolve()
        if args.carla_resources_dir
        else (bin_dir / "resources")
    )
    frontend_dir = (
        Path(args.carla_frontend_dir).expanduser().resolve()
        if args.carla_frontend_dir
        else resources_dir
    )
    if args.carla_backend:
        backend_path = Path(args.carla_backend).expanduser().resolve()
    else:
        backend_path = bin_dir / "libcarla_standalone2.dll"
    return carla_root, bin_dir, resources_dir, frontend_dir, backend_path


def infer_plugin_type(plugin_path: Path, explicit_type: str | None) -> str:
    if explicit_type:
        return explicit_type

    lower_path = str(plugin_path).lower()
    if lower_path.endswith(".vst3") or ".vst3" + os.sep.lower() in lower_path:
        return "vst3"
    if lower_path.endswith(".dll"):
        return "vst2"
    if lower_path.endswith(".sf2") or lower_path.endswith(".sf3"):
        return "sf2"

    raise ValueError(f"Cannot infer plugin type from path: {plugin_path}. Use --plugin-type.")


def resolve_plugin_name(args: argparse.Namespace, plugin_path: Path, using_default_surge: bool) -> str:
    if args.plugin_name:
        return args.plugin_name
    if using_default_surge:
        return "Surge XT"
    return plugin_path.stem


def validate_paths(args: argparse.Namespace) -> tuple[Path, Path | None, Path, str, str]:
    midi_path = Path(args.midi).expanduser().resolve()
    if not midi_path.is_file():
        raise FileNotFoundError(f"MIDI file not found: {midi_path}")

    plugin_state = None
    plugin_state_arg = args.plugin_state or args.surge_state
    if plugin_state_arg:
        plugin_state = Path(plugin_state_arg).expanduser().resolve()
        if not plugin_state.is_file():
            raise FileNotFoundError(f"Plugin state file not found: {plugin_state}")

    using_default_surge = not args.plugin_path
    plugin_path_arg = args.plugin_path or args.surge_vst3
    plugin_path = Path(plugin_path_arg).expanduser().resolve()
    if not plugin_path.is_file():
        raise FileNotFoundError(f"Plugin binary not found: {plugin_path}")

    plugin_type = infer_plugin_type(plugin_path, args.plugin_type or ("vst3" if using_default_surge else None))
    plugin_name = resolve_plugin_name(args, plugin_path, using_default_surge)

    return midi_path, plugin_state, plugin_path, plugin_type, plugin_name


def sanitize_filename_component(value: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*\s]+', "_", value.strip())
    sanitized = re.sub(r"_+", "_", sanitized).strip("._")
    return sanitized or "untitled"


def build_default_basename(
    args: argparse.Namespace,
    midi_path: Path,
    plugin_state: Path | None,
    plugin_name: str,
) -> str:
    if args.output_basename:
        return sanitize_filename_component(args.output_basename)

    song_name = sanitize_filename_component(midi_path.stem)

    if args.style_name:
        style_name = sanitize_filename_component(args.style_name)
    elif plugin_state is not None:
        style_name = sanitize_filename_component(plugin_state.stem)
    else:
        style_name = sanitize_filename_component(plugin_name)

    return f"{song_name}_{style_name}"


def resolve_output_paths(
    args: argparse.Namespace,
    midi_path: Path,
    carla_root: Path,
    plugin_state: Path | None,
    plugin_name: str,
) -> tuple[Path, Path, bool]:
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else (carla_root / "output")
    output_dir.mkdir(parents=True, exist_ok=True)
    default_basename = build_default_basename(args, midi_path, plugin_state, plugin_name)

    mp3_path = Path(args.mp3).expanduser().resolve() if args.mp3 else (output_dir / f"{default_basename}.mp3")
    if args.wav:
        wav_path = Path(args.wav).expanduser().resolve()
    else:
        wav_path = output_dir / f"{default_basename}.wav"

    remove_wav_after = False
    return mp3_path, wav_path, remove_wav_after


def find_ffmpeg(explicit_path: str | None) -> str:
    if explicit_path:
        if not re.match(r"^[A-Za-z]:[\\/]", explicit_path) and "/" not in explicit_path and "\\" not in explicit_path:
            ffmpeg = shutil.which(explicit_path)
            if ffmpeg:
                return ffmpeg
            raise FileNotFoundError(f"ffmpeg not found in PATH: {explicit_path}")
        ffmpeg = Path(explicit_path).expanduser().resolve()
        if not ffmpeg.is_file():
            raise FileNotFoundError(f"ffmpeg not found: {ffmpeg}")
        return str(ffmpeg)

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg

    raise FileNotFoundError("ffmpeg not found in PATH. Use --ffmpeg to point to ffmpeg.exe")


def parse_parameter_overrides(raw_values: list[str]) -> list[tuple[int, float]]:
    overrides: list[tuple[int, float]] = []
    for raw_value in raw_values:
        if "=" not in raw_value:
            raise ValueError(f"Invalid --set-param value {raw_value!r}; expected INDEX=VALUE")
        raw_index, raw_parameter_value = raw_value.split("=", 1)
        try:
            parameter_index = int(raw_index.strip())
            parameter_value = float(raw_parameter_value.strip())
        except ValueError as exc:
            raise ValueError(f"Invalid --set-param value {raw_value!r}; expected INDEX=VALUE") from exc
        if parameter_index < 0:
            raise ValueError(f"Invalid --set-param index {parameter_index}; index must be >= 0")
        overrides.append((parameter_index, parameter_value))
    return overrides


def validate_encoding_args(args: argparse.Namespace) -> dict[str, Any]:
    if not re.fullmatch(r"\d+[kKmM]?", str(args.mp3_bitrate).strip()):
        raise ValueError(f"Invalid --mp3-bitrate value: {args.mp3_bitrate!r}")

    mp3_sample_rate = args.mp3_sample_rate or args.sample_rate
    if mp3_sample_rate <= 0:
        raise ValueError("--mp3-sample-rate must be greater than 0")

    return {
        "mp3_codec": "libmp3lame",
        "mp3_bitrate": str(args.mp3_bitrate).strip().lower(),
        "mp3_sample_rate": int(mp3_sample_rate),
        "mp3_channels": int(args.mp3_channels),
        "mp3_mode": "cbr",
        "mp3_id3v2_version": int(args.mp3_id3v2_version),
        "wav_sample_rate": int(args.sample_rate),
        "wav_bit_depth": 16,
        "wav_channels": 2,
    }


def create_host(frontend_dir: Path, backend_dll: Path):
    sys.path.insert(0, str(frontend_dir))
    os.environ["CARLA_BACKEND_PATH"] = str(backend_dll)

    from carla_backend import (  # type: ignore
        BINARY_NATIVE,
        CUSTOM_DATA_TYPE_STRING,
        ENGINE_OPTION_AUDIO_BUFFER_SIZE,
        ENGINE_OPTION_AUDIO_DEVICE,
        ENGINE_OPTION_AUDIO_SAMPLE_RATE,
        ENGINE_OPTION_PATH_BINARIES,
        ENGINE_OPTION_PATH_RESOURCES,
        ENGINE_OPTION_PROCESS_MODE,
        ENGINE_OPTION_TRANSPORT_MODE,
        ENGINE_PROCESS_MODE_CONTINUOUS_RACK,
        ENGINE_TRANSPORT_MODE_INTERNAL,
        PLUGIN_INTERNAL,
        PLUGIN_OPTIONS_NULL,
        PLUGIN_SF2,
        PLUGIN_VST2,
        PLUGIN_VST3,
        CarlaHostDLL,
    )

    return {
        "CarlaHostDLL": CarlaHostDLL,
        "BINARY_NATIVE": BINARY_NATIVE,
        "PLUGIN_INTERNAL": PLUGIN_INTERNAL,
        "PLUGIN_SF2": PLUGIN_SF2,
        "PLUGIN_VST2": PLUGIN_VST2,
        "PLUGIN_VST3": PLUGIN_VST3,
        "PLUGIN_OPTIONS_NULL": PLUGIN_OPTIONS_NULL,
        "CUSTOM_DATA_TYPE_STRING": CUSTOM_DATA_TYPE_STRING,
        "ENGINE_OPTION_PROCESS_MODE": ENGINE_OPTION_PROCESS_MODE,
        "ENGINE_PROCESS_MODE_CONTINUOUS_RACK": ENGINE_PROCESS_MODE_CONTINUOUS_RACK,
        "ENGINE_OPTION_TRANSPORT_MODE": ENGINE_OPTION_TRANSPORT_MODE,
        "ENGINE_TRANSPORT_MODE_INTERNAL": ENGINE_TRANSPORT_MODE_INTERNAL,
        "ENGINE_OPTION_AUDIO_DEVICE": ENGINE_OPTION_AUDIO_DEVICE,
        "ENGINE_OPTION_AUDIO_BUFFER_SIZE": ENGINE_OPTION_AUDIO_BUFFER_SIZE,
        "ENGINE_OPTION_AUDIO_SAMPLE_RATE": ENGINE_OPTION_AUDIO_SAMPLE_RATE,
        "ENGINE_OPTION_PATH_BINARIES": ENGINE_OPTION_PATH_BINARIES,
        "ENGINE_OPTION_PATH_RESOURCES": ENGINE_OPTION_PATH_RESOURCES,
    }


def emit_renderer_event(event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    print(f"RENDER_EVENT {json.dumps(payload, ensure_ascii=False, sort_keys=True)}", file=sys.stderr, flush=True)


def idle_for(
    host,
    seconds: float,
    progress_interval_seconds: float | None = None,
    progress_event: str = "record_audio_progress",
    sleep_seconds_per_iteration: float = 0.02,
) -> dict[str, Any]:
    duration = max(0.0, seconds)
    started = time.monotonic()
    end = started + duration
    progress_interval = max(1.0, float(progress_interval_seconds or 0.0))
    next_progress = started + progress_interval
    interval_started = started
    engine_idle_seconds = 0.0
    sleep_seconds = 0.0
    iterations = 0
    interval_engine_idle_seconds = 0.0
    interval_sleep_seconds = 0.0
    interval_iterations = 0

    if progress_interval_seconds is not None and duration > 0:
        emit_renderer_event(
            progress_event,
            elapsed_seconds=0.0,
            target_seconds=round(duration, 3),
            percent=0.0,
            engine_idle_seconds=0.0,
            sleep_seconds=0.0,
            iterations=0,
        )

    while time.monotonic() < end:
        idle_started = time.monotonic()
        host.engine_idle()
        idle_elapsed = time.monotonic() - idle_started
        engine_idle_seconds += idle_elapsed
        interval_engine_idle_seconds += idle_elapsed
        iterations += 1
        interval_iterations += 1

        if progress_interval_seconds is not None and duration > 0:
            now = time.monotonic()
            if now >= next_progress:
                elapsed = min(now - started, duration)
                emit_renderer_event(
                    progress_event,
                    elapsed_seconds=round(elapsed, 3),
                    target_seconds=round(duration, 3),
                    percent=round((elapsed / duration) * 100.0, 1),
                    interval_wall_seconds=round(now - interval_started, 3),
                    interval_engine_idle_seconds=round(interval_engine_idle_seconds, 3),
                    interval_sleep_seconds=round(interval_sleep_seconds, 3),
                    interval_iterations=interval_iterations,
                    engine_idle_seconds=round(engine_idle_seconds, 3),
                    sleep_seconds=round(sleep_seconds, 3),
                    iterations=iterations,
                )
                next_progress = now + progress_interval
                interval_started = now
                interval_engine_idle_seconds = 0.0
                interval_sleep_seconds = 0.0
                interval_iterations = 0

        sleep_duration = min(max(0.0, sleep_seconds_per_iteration), max(0.0, end - time.monotonic()))
        if sleep_duration > 0:
            sleep_started = time.monotonic()
            time.sleep(sleep_duration)
            sleep_elapsed = time.monotonic() - sleep_started
            sleep_seconds += sleep_elapsed
            interval_sleep_seconds += sleep_elapsed

    if progress_interval_seconds is not None and duration > 0:
        finished = time.monotonic()
        emit_renderer_event(
            progress_event,
            elapsed_seconds=round(duration, 3),
            target_seconds=round(duration, 3),
            percent=100.0,
            interval_wall_seconds=round(finished - interval_started, 3),
            interval_engine_idle_seconds=round(interval_engine_idle_seconds, 3),
            interval_sleep_seconds=round(interval_sleep_seconds, 3),
            interval_iterations=interval_iterations,
            engine_idle_seconds=round(engine_idle_seconds, 3),
            sleep_seconds=round(sleep_seconds, 3),
            iterations=iterations,
        )

    wall_seconds = time.monotonic() - started
    return {
        "wall_seconds": round(wall_seconds, 3),
        "engine_idle_seconds": round(engine_idle_seconds, 3),
        "sleep_seconds": round(sleep_seconds, 3),
        "loop_overhead_seconds": round(max(0.0, wall_seconds - engine_idle_seconds - sleep_seconds), 3),
        "iterations": iterations,
    }


def idle_until_transport_frame(
    host,
    target_frame: int,
    sample_rate: int,
    progress_interval_seconds: float | None = None,
    progress_event: str = "record_audio_progress",
    sleep_seconds_per_iteration: float = 0.0,
    stall_timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    started = time.monotonic()
    progress_interval = max(1.0, float(progress_interval_seconds or 0.0))
    next_progress = started + progress_interval
    interval_started = started
    engine_idle_seconds = 0.0
    sleep_seconds = 0.0
    iterations = 0
    interval_engine_idle_seconds = 0.0
    interval_sleep_seconds = 0.0
    interval_iterations = 0
    last_frame_change = started
    current_frame = max(0, int(host.get_current_transport_frame()))
    start_frame = current_frame
    target_frame = max(current_frame, int(target_frame))
    target_seconds = max(0.0, (target_frame - start_frame) / max(1, sample_rate))
    last_reported_frame = current_frame

    if progress_interval_seconds is not None and target_seconds > 0:
        emit_renderer_event(
            progress_event,
            elapsed_seconds=0.0,
            target_seconds=round(target_seconds, 3),
            percent=0.0,
            current_frame=current_frame,
            target_frame=target_frame,
            engine_idle_seconds=0.0,
            sleep_seconds=0.0,
            iterations=0,
        )

    while current_frame < target_frame:
        idle_started = time.monotonic()
        host.engine_idle()
        idle_elapsed = time.monotonic() - idle_started
        engine_idle_seconds += idle_elapsed
        interval_engine_idle_seconds += idle_elapsed
        iterations += 1
        interval_iterations += 1

        now = time.monotonic()
        current_frame = max(0, int(host.get_current_transport_frame()))
        if current_frame > last_reported_frame:
            last_reported_frame = current_frame
            last_frame_change = now
        elif now - last_frame_change >= max(1.0, stall_timeout_seconds):
            raise RuntimeError(
                "Carla transport did not advance while recording; render stalled "
                f"at frame {current_frame} of {target_frame}"
            )

        if progress_interval_seconds is not None and target_seconds > 0 and now >= next_progress:
            rendered_seconds = min(target_seconds, max(0.0, (current_frame - start_frame) / max(1, sample_rate)))
            percent = min(100.0, (rendered_seconds / target_seconds) * 100.0) if target_seconds > 0 else 100.0
            emit_renderer_event(
                progress_event,
                elapsed_seconds=round(rendered_seconds, 3),
                target_seconds=round(target_seconds, 3),
                percent=round(percent, 1),
                current_frame=current_frame,
                target_frame=target_frame,
                interval_wall_seconds=round(now - interval_started, 3),
                interval_engine_idle_seconds=round(interval_engine_idle_seconds, 3),
                interval_sleep_seconds=round(interval_sleep_seconds, 3),
                interval_iterations=interval_iterations,
                engine_idle_seconds=round(engine_idle_seconds, 3),
                sleep_seconds=round(sleep_seconds, 3),
                iterations=iterations,
            )
            next_progress = now + progress_interval
            interval_started = now
            interval_engine_idle_seconds = 0.0
            interval_sleep_seconds = 0.0
            interval_iterations = 0

        sleep_duration = max(0.0, sleep_seconds_per_iteration)
        if sleep_duration > 0:
            sleep_started = time.monotonic()
            time.sleep(sleep_duration)
            sleep_elapsed = time.monotonic() - sleep_started
            sleep_seconds += sleep_elapsed
            interval_sleep_seconds += sleep_elapsed

    if progress_interval_seconds is not None and target_seconds > 0:
        finished = time.monotonic()
        emit_renderer_event(
            progress_event,
            elapsed_seconds=round(target_seconds, 3),
            target_seconds=round(target_seconds, 3),
            percent=100.0,
            current_frame=current_frame,
            target_frame=target_frame,
            interval_wall_seconds=round(finished - interval_started, 3),
            interval_engine_idle_seconds=round(interval_engine_idle_seconds, 3),
            interval_sleep_seconds=round(interval_sleep_seconds, 3),
            interval_iterations=interval_iterations,
            engine_idle_seconds=round(engine_idle_seconds, 3),
            sleep_seconds=round(sleep_seconds, 3),
            iterations=iterations,
        )

    wall_seconds = time.monotonic() - started
    return {
        "wall_seconds": round(wall_seconds, 3),
        "engine_idle_seconds": round(engine_idle_seconds, 3),
        "sleep_seconds": round(sleep_seconds, 3),
        "loop_overhead_seconds": round(max(0.0, wall_seconds - engine_idle_seconds - sleep_seconds), 3),
        "iterations": iterations,
        "current_frame": current_frame,
        "target_frame": target_frame,
        "rendered_seconds": round(target_seconds, 3),
        "realtime_ratio": round(target_seconds / wall_seconds, 3) if wall_seconds > 0 else None,
    }


def record_timing(timings: dict[str, float], name: str, started: float) -> float:
    elapsed = round(time.monotonic() - started, 3)
    timings[name] = elapsed
    emit_renderer_event("stage_timing", stage=name, seconds=elapsed)
    return elapsed


def render(args: argparse.Namespace) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    total_started = time.monotonic()
    timings: dict[str, Any] = {}
    if args.audio_driver.strip().lower() == "dummy":
        os.environ.setdefault("CARLA_DUMMY_OFFLINE", "1")
    emit_renderer_event(
        "render_start",
        midi=str(args.midi),
        plugin_name=args.plugin_name,
        plugin_path=str(args.plugin_path) if args.plugin_path else None,
    )

    stage_started = time.monotonic()
    carla_root, bin_dir, resources_dir, frontend_dir, backend_path = resolve_script_paths(args)
    midi_path, plugin_state, plugin_path, plugin_type, plugin_name = validate_paths(args)
    parameter_overrides = parse_parameter_overrides(args.set_param)
    encoding = validate_encoding_args(args)
    mp3_path, wav_path, remove_wav_after = resolve_output_paths(
        args,
        midi_path,
        carla_root,
        plugin_state,
        plugin_name,
    )
    ffmpeg = None if args.skip_mp3 else find_ffmpeg(args.ffmpeg)
    record_timing(timings, "prepare_seconds", stage_started)

    stage_started = time.monotonic()
    api = create_host(frontend_dir, backend_path)
    host = api["CarlaHostDLL"](str(backend_path), False)

    host.set_engine_option(
        api["ENGINE_OPTION_PROCESS_MODE"],
        api["ENGINE_PROCESS_MODE_CONTINUOUS_RACK"],
        "",
    )
    host.set_engine_option(
        api["ENGINE_OPTION_TRANSPORT_MODE"],
        api["ENGINE_TRANSPORT_MODE_INTERNAL"],
        "",
    )
    host.set_engine_option(
        api["ENGINE_OPTION_AUDIO_DEVICE"],
        0,
        args.audio_device,
    )
    host.set_engine_option(
        api["ENGINE_OPTION_AUDIO_BUFFER_SIZE"],
        args.buffer_size,
        "",
    )
    host.set_engine_option(
        api["ENGINE_OPTION_AUDIO_SAMPLE_RATE"],
        args.sample_rate,
        "",
    )
    host.set_engine_option(
        api["ENGINE_OPTION_PATH_BINARIES"],
        0,
        str(bin_dir),
    )
    host.set_engine_option(
        api["ENGINE_OPTION_PATH_RESOURCES"],
        0,
        str(resources_dir),
    )

    if not host.engine_init(args.audio_driver, "CodexMidiRender"):
        raise RuntimeError(f"Carla engine init failed: {host.get_last_error()}")
    record_timing(timings, "engine_init_seconds", stage_started)

    try:
        stage_started = time.monotonic()
        if not host.add_plugin(
            api["BINARY_NATIVE"],
            api["PLUGIN_INTERNAL"],
            None,
            "MIDI File",
            "midifile",
            0,
            None,
            api["PLUGIN_OPTIONS_NULL"],
        ):
            raise RuntimeError(f"Failed to add MIDI File: {host.get_last_error()}")
        record_timing(timings, "add_midi_file_seconds", stage_started)

        plugin_type_constant = {
            "sf2": api["PLUGIN_SF2"],
            "vst2": api["PLUGIN_VST2"],
            "vst3": api["PLUGIN_VST3"],
        }[plugin_type]

        stage_started = time.monotonic()
        if args.plugin_load_mode == "load_file" and plugin_type in {"vst2", "vst3"}:
            old_cwd = Path.cwd()
            try:
                os.chdir(plugin_path.parent)
                if not host.load_file(str(plugin_path)):
                    raise RuntimeError(f"Failed to load {plugin_name}: {host.get_last_error()}")
            finally:
                os.chdir(old_cwd)
        else:
            plugin_label = args.plugin_label or (plugin_path.stem if plugin_type == "sf2" else "")
            if not host.add_plugin(
                api["BINARY_NATIVE"],
                plugin_type_constant,
                str(plugin_path),
                plugin_name,
                plugin_label,
                0,
                None,
                api["PLUGIN_OPTIONS_NULL"],
            ):
                raise RuntimeError(f"Failed to add {plugin_name}: {host.get_last_error()}")
        instrument_id = host.get_current_plugin_count() - 1
        record_timing(timings, "add_instrument_seconds", stage_started)

        stage_started = time.monotonic()
        if not host.add_plugin(
            api["BINARY_NATIVE"],
            api["PLUGIN_INTERNAL"],
            None,
            "Audio Recorder",
            "audiorecorder",
            0,
            None,
            api["PLUGIN_OPTIONS_NULL"],
        ):
            raise RuntimeError(f"Failed to add Audio Recorder: {host.get_last_error()}")
        recorder_id = host.get_current_plugin_count() - 1
        record_timing(timings, "add_audio_recorder_seconds", stage_started)

        stage_started = time.monotonic()
        host.set_custom_data(0, api["CUSTOM_DATA_TYPE_STRING"], "file", str(midi_path))
        host.set_custom_data(recorder_id, api["CUSTOM_DATA_TYPE_STRING"], "file", str(wav_path))
        record_timing(timings, "set_input_output_seconds", stage_started)

        if plugin_state:
            stage_started = time.monotonic()
            if not host.load_plugin_state(instrument_id, str(plugin_state)):
                raise RuntimeError(f"Failed to load plugin state: {host.get_last_error()}")
            record_timing(timings, "load_plugin_state_seconds", stage_started)

        stage_started = time.monotonic()
        for parameter_index, parameter_value in parameter_overrides:
            host.set_parameter_value(instrument_id, parameter_index, parameter_value)
        record_timing(timings, "apply_parameters_seconds", stage_started)

        stage_started = time.monotonic()
        idle_for(host, args.warmup_seconds)
        record_timing(timings, "warmup_seconds", stage_started)

        stage_started = time.monotonic()
        midi_length_seconds = host.get_current_parameter_value(0, 4)
        if midi_length_seconds <= 0:
            raise RuntimeError("Failed to read MIDI duration from Carla")
        record_timing(timings, "read_midi_duration_seconds", stage_started)

        total_seconds = midi_length_seconds + max(0.0, args.tail_seconds)
        if args.max_seconds is not None:
            total_seconds = min(total_seconds, max(0.1, args.max_seconds))
        timings["midi_length_seconds"] = round(float(midi_length_seconds), 3)
        timings["record_target_seconds"] = round(float(total_seconds), 3)
        emit_renderer_event(
            "record_audio_start",
            midi_length_seconds=timings["midi_length_seconds"],
            record_target_seconds=timings["record_target_seconds"],
            tail_seconds=round(max(0.0, args.tail_seconds), 3),
        )
        record_target_frames = int(round(total_seconds * args.sample_rate))
        timings["record_target_frames"] = record_target_frames

        stage_started = time.monotonic()
        sub_stage_started = time.monotonic()
        host.transport_relocate(0)
        record_timing(timings, "transport_relocate_seconds", sub_stage_started)

        sub_stage_started = time.monotonic()
        host.transport_play()
        record_timing(timings, "transport_play_seconds", sub_stage_started)

        record_idle_stats = idle_until_transport_frame(
            host,
            record_target_frames,
            args.sample_rate,
            args.progress_interval_seconds,
            progress_event="record_audio_progress",
            sleep_seconds_per_iteration=0.0 if args.audio_driver.strip().lower() == "dummy" else 0.02,
            stall_timeout_seconds=max(15.0, min(60.0, total_seconds * 0.5)),
        )
        timings["record_idle_wall_seconds"] = record_idle_stats["wall_seconds"]
        timings["record_idle_engine_idle_seconds"] = record_idle_stats["engine_idle_seconds"]
        timings["record_idle_sleep_seconds"] = record_idle_stats["sleep_seconds"]
        timings["record_idle_loop_overhead_seconds"] = record_idle_stats["loop_overhead_seconds"]
        timings["record_idle_iterations"] = record_idle_stats["iterations"]
        timings["record_current_frame"] = record_idle_stats["current_frame"]
        timings["record_realtime_ratio"] = record_idle_stats["realtime_ratio"]

        sub_stage_started = time.monotonic()
        host.transport_pause()
        record_timing(timings, "transport_pause_seconds", sub_stage_started)

        sub_stage_started = time.monotonic()
        post_pause_idle_stats = idle_for(host, 0.2)
        timings["post_pause_idle_wall_seconds"] = post_pause_idle_stats["wall_seconds"]
        timings["post_pause_idle_engine_idle_seconds"] = post_pause_idle_stats["engine_idle_seconds"]
        timings["post_pause_idle_sleep_seconds"] = post_pause_idle_stats["sleep_seconds"]
        timings["post_pause_idle_loop_overhead_seconds"] = post_pause_idle_stats["loop_overhead_seconds"]
        timings["post_pause_idle_iterations"] = post_pause_idle_stats["iterations"]
        record_timing(timings, "post_pause_idle_seconds", sub_stage_started)

        record_timing(timings, "record_audio_seconds", stage_started)
    finally:
        stage_started = time.monotonic()
        host.engine_close()
        record_timing(timings, "engine_close_seconds", stage_started)

    stage_started = time.monotonic()
    if not wav_path.is_file() or wav_path.stat().st_size <= 44:
        raise RuntimeError(f"WAV render did not succeed: {wav_path}")
    timings["wav_bytes"] = wav_path.stat().st_size
    record_timing(timings, "validate_wav_seconds", stage_started)

    if args.skip_mp3:
        timings["mp3_bytes"] = 0
        timings["ffmpeg_mp3_seconds"] = 0.0
    else:
        assert ffmpeg is not None
        mp3_path.parent.mkdir(parents=True, exist_ok=True)
        stage_started = time.monotonic()
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
                str(encoding["mp3_sample_rate"]),
                "-ac",
                str(encoding["mp3_channels"]),
                "-codec:a",
                "libmp3lame",
                "-b:a",
                encoding["mp3_bitrate"],
                "-compression_level",
                "0",
                "-id3v2_version",
                str(encoding["mp3_id3v2_version"]),
                "-write_id3v1",
                "1",
                str(mp3_path),
            ],
            check=True,
        )
        timings["mp3_bytes"] = mp3_path.stat().st_size if mp3_path.is_file() else 0
        record_timing(timings, "ffmpeg_mp3_seconds", stage_started)

    if remove_wav_after:
        try:
            wav_path.unlink()
        except OSError:
            pass

    timings["total_seconds"] = round(time.monotonic() - total_started, 3)
    emit_renderer_event("render_complete", total_seconds=timings["total_seconds"])
    return mp3_path, wav_path, timings, encoding


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    try:
        mp3_path, wav_path, timings, encoding = render(args)
    except Exception as exc:
        if getattr(args, "json_output", False):
            print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json_output:
        print(
            json.dumps(
                {
                    "mp3": str(mp3_path),
                    "wav": str(wav_path),
                    "timings": timings,
                    "encoding": encoding,
                },
                ensure_ascii=False,
            )
        )
    else:
        print(f"MP3 written to: {mp3_path}")
        print(f"WAV written to: {wav_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
