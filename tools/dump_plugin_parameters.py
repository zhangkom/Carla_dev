#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from render_midi_to_mp3 import create_host, idle_for, infer_plugin_type, resolve_script_paths


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dump Carla parameter indexes for a VST2/VST3 plugin."
    )
    parser.add_argument("--plugin-path", required=True, help="Path to VST2 .dll or VST3 binary")
    parser.add_argument("--plugin-type", choices=("vst2", "vst3"), help="Plugin format")
    parser.add_argument("--plugin-name", help="Display name passed to Carla")
    parser.add_argument("--plugin-label", default="", help="Optional Carla plugin label")
    parser.add_argument("--plugin-state", help="Optional .carxs state file to load before dumping")
    parser.add_argument("--audio-driver", default="DirectSound", help="Carla audio driver")
    parser.add_argument("--audio-device", default="Primary Sound Driver", help="Audio device")
    parser.add_argument("--buffer-size", type=int, default=512, help="Audio buffer size")
    parser.add_argument("--sample-rate", type=int, default=44100, help="Sample rate")
    parser.add_argument("--limit", type=int, help="Maximum number of parameters to print")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Print JSON")
    return parser


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def get_text(mapping: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def get_number(mapping: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def dump_parameters(args: argparse.Namespace) -> list[dict[str, Any]]:
    carla_root, resources_dir, backend_dll = resolve_script_paths()
    plugin_path = Path(args.plugin_path).expanduser().resolve()
    if not plugin_path.is_file():
        raise FileNotFoundError(f"Plugin binary not found: {plugin_path}")

    plugin_state = Path(args.plugin_state).expanduser().resolve() if args.plugin_state else None
    if plugin_state and not plugin_state.is_file():
        raise FileNotFoundError(f"Plugin state file not found: {plugin_state}")

    plugin_type = infer_plugin_type(plugin_path, args.plugin_type)
    plugin_name = args.plugin_name or plugin_path.stem

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
    host.set_engine_option(api["ENGINE_OPTION_AUDIO_DEVICE"], 0, args.audio_device)
    host.set_engine_option(api["ENGINE_OPTION_AUDIO_BUFFER_SIZE"], args.buffer_size, "")
    host.set_engine_option(api["ENGINE_OPTION_AUDIO_SAMPLE_RATE"], args.sample_rate, "")
    host.set_engine_option(api["ENGINE_OPTION_PATH_BINARIES"], 0, str(carla_root / "bin"))
    host.set_engine_option(api["ENGINE_OPTION_PATH_RESOURCES"], 0, str(resources_dir))

    if not host.engine_init(args.audio_driver, "CodexParameterDump"):
        raise RuntimeError(f"Carla engine init failed: {host.get_last_error()}")

    try:
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

        if plugin_state and not host.load_plugin_state(0, str(plugin_state)):
            raise RuntimeError(f"Failed to load plugin state: {host.get_last_error()}")

        idle_for(host, 0.3)
        parameter_count = host.get_parameter_count(0)
        if args.limit is not None:
            parameter_count = min(parameter_count, max(0, args.limit))

        parameters: list[dict[str, Any]] = []
        for parameter_index in range(parameter_count):
            info = json_safe(host.get_parameter_info(0, parameter_index) or {})
            data = json_safe(host.get_parameter_data(0, parameter_index) or {})
            ranges = json_safe(host.get_parameter_ranges(0, parameter_index) or {})
            current = host.get_current_parameter_value(0, parameter_index)
            parameters.append(
                {
                    "index": parameter_index,
                    "name": get_text(info, "name", "label"),
                    "symbol": get_text(info, "symbol"),
                    "current": current,
                    "default": get_number(ranges, "def", "default"),
                    "minimum": get_number(ranges, "min", "minimum"),
                    "maximum": get_number(ranges, "max", "maximum"),
                    "info": info,
                    "data": data,
                    "ranges": ranges,
                }
            )
    finally:
        host.engine_close()

    return parameters


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    try:
        parameters = dump_parameters(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json_output:
        print(json.dumps({"parameters": parameters}, ensure_ascii=False, indent=2))
        return 0

    for parameter in parameters:
        print(
            "{index:4d} {name:32s} current={current} default={default} min={minimum} max={maximum}".format(
                **parameter
            )
        )
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    raise SystemExit(main())

