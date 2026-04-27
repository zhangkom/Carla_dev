#!/usr/bin/env python
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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a MIDI file through Carla + a VST2/VST3 plugin and export WAV/MP3."
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
        choices=("vst2", "vst3"),
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
        "--plugin-state",
        help="Optional .carxs state file exported from Carla GUI for the selected plugin.",
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
        "--json",
        action="store_true",
        dest="json_output",
        help="Print a machine-readable JSON result.",
    )
    return parser


def resolve_script_paths() -> tuple[Path, Path, Path]:
    carla_root = Path(__file__).resolve().parent
    bin_dir = carla_root / "bin"
    resources_dir = bin_dir / "resources"
    backend_dll = bin_dir / "libcarla_standalone2.dll"
    return carla_root, resources_dir, backend_dll


def infer_plugin_type(plugin_path: Path, explicit_type: str | None) -> str:
    if explicit_type:
        return explicit_type

    lower_path = str(plugin_path).lower()
    if lower_path.endswith(".vst3") or ".vst3" + os.sep.lower() in lower_path:
        return "vst3"
    if lower_path.endswith(".dll"):
        return "vst2"

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
        ffmpeg = Path(explicit_path).expanduser().resolve()
        if not ffmpeg.is_file():
            raise FileNotFoundError(f"ffmpeg not found: {ffmpeg}")
        return str(ffmpeg)

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg

    raise FileNotFoundError("ffmpeg not found in PATH. Use --ffmpeg to point to ffmpeg.exe")


def create_host(resources_dir: Path, backend_dll: Path):
    sys.path.insert(0, str(resources_dir))
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
        PLUGIN_VST2,
        PLUGIN_VST3,
        CarlaHostDLL,
    )

    return {
        "CarlaHostDLL": CarlaHostDLL,
        "BINARY_NATIVE": BINARY_NATIVE,
        "PLUGIN_INTERNAL": PLUGIN_INTERNAL,
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


def idle_for(host, seconds: float) -> None:
    end = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < end:
        host.engine_idle()
        time.sleep(0.02)


def render(args: argparse.Namespace) -> tuple[Path, Path]:
    carla_root, resources_dir, backend_dll = resolve_script_paths()
    midi_path, plugin_state, plugin_path, plugin_type, plugin_name = validate_paths(args)
    mp3_path, wav_path, remove_wav_after = resolve_output_paths(
        args,
        midi_path,
        carla_root,
        plugin_state,
        plugin_name,
    )
    ffmpeg = find_ffmpeg(args.ffmpeg)

    api = create_host(resources_dir, backend_dll)
    host = api["CarlaHostDLL"](str(backend_dll), False)

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
        str(carla_root / "bin"),
    )
    host.set_engine_option(
        api["ENGINE_OPTION_PATH_RESOURCES"],
        0,
        str(resources_dir),
    )

    if not host.engine_init(args.audio_driver, "CodexMidiRender"):
        raise RuntimeError(f"Carla engine init failed: {host.get_last_error()}")

    try:
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

        plugin_type_constant = api["PLUGIN_VST3"] if plugin_type == "vst3" else api["PLUGIN_VST2"]

        if not host.add_plugin(
            api["BINARY_NATIVE"],
            plugin_type_constant,
            str(plugin_path),
            plugin_name,
            args.plugin_label,
            0,
            None,
            api["PLUGIN_OPTIONS_NULL"],
        ):
            raise RuntimeError(f"Failed to add {plugin_name}: {host.get_last_error()}")

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

        host.set_custom_data(0, api["CUSTOM_DATA_TYPE_STRING"], "file", str(midi_path))
        host.set_custom_data(2, api["CUSTOM_DATA_TYPE_STRING"], "file", str(wav_path))

        if plugin_state:
            if not host.load_plugin_state(1, str(plugin_state)):
                raise RuntimeError(f"Failed to load plugin state: {host.get_last_error()}")

        idle_for(host, args.warmup_seconds)

        midi_length_seconds = host.get_current_parameter_value(0, 4)
        if midi_length_seconds <= 0:
            raise RuntimeError("Failed to read MIDI duration from Carla")

        total_seconds = midi_length_seconds + max(0.0, args.tail_seconds)
        if args.max_seconds is not None:
            total_seconds = min(total_seconds, max(0.1, args.max_seconds))
        host.transport_relocate(0)
        host.transport_play()
        idle_for(host, total_seconds)
        host.transport_pause()
        idle_for(host, 0.2)
    finally:
        host.engine_close()

    if not wav_path.is_file() or wav_path.stat().st_size <= 44:
        raise RuntimeError(f"WAV render did not succeed: {wav_path}")

    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-i",
            str(wav_path),
            "-codec:a",
            "libmp3lame",
            "-q:a",
            "2",
            str(mp3_path),
        ],
        check=True,
    )

    if remove_wav_after:
        try:
            wav_path.unlink()
        except OSError:
            pass

    return mp3_path, wav_path


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    try:
        mp3_path, wav_path = render(args)
    except Exception as exc:
        if getattr(args, "json_output", False):
            print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json_output:
        print(json.dumps({"mp3": str(mp3_path), "wav": str(wav_path)}, ensure_ascii=False))
    else:
        print(f"MP3 written to: {mp3_path}")
        print(f"WAV written to: {wav_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
