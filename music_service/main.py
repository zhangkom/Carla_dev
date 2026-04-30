from __future__ import annotations

import base64
import io
import json
import logging
import re
import sys
import time
import uuid
import zipfile
from datetime import date, datetime
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .config import (
    ConfigError,
    MidiPolicy,
    ParameterOverride,
    PluginProfile,
    ServiceConfig,
    StyleProfile,
    load_config,
)
from .midi_policy import MidiPolicyError, analyze_midi_channels, preprocess_midi
from .renderer import RenderError, run_render


app = FastAPI(title="Carla Music Service", version="0.1.0")
_CONFIG: ServiceConfig | None = None
_LOGGER = logging.getLogger("music_service")
_LOGGER_DATE: str | None = None


def _normalize_path_text(value: str) -> str:
    return str(Path(value).expanduser()).replace("/", "\\").lower()


def _path_stem_text(value: str | Path) -> str:
    filename = re.split(r"[\\/]", str(value).strip())[-1]
    return filename.rsplit(".", 1)[0].lower()


def _plugin_family_stem(value: str | Path) -> str:
    stem = _path_stem_text(value)
    for suffix in ("_x64", "_x86", "-x64", "-x86"):
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def _read_state_binary(state_path: Path | None) -> str | None:
    if state_path is None or not state_path.is_file():
        return None
    try:
        text = state_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = re.search(r"<Binary>(.*?)</Binary>", text, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


def _state_binary_matches_plugin(
    config: ServiceConfig,
    state_binary: str | None,
    plugin: PluginProfile | None,
) -> bool:
    if state_binary is None or plugin is None:
        return True
    if _normalize_path_text(state_binary) == _normalize_path_text(
        plugin.runtime_path or str(plugin.path)
    ):
        return True
    if config.renderer_path_mode == "native_bridge":
        # GUI states were saved from the Windows x64 wrapper, while Linux Carla
        # loads the direct win32 DLL through the official Wine bridge.
        return _plugin_family_stem(state_binary) == _plugin_family_stem(plugin.path)
    return False


def get_logger(config: ServiceConfig) -> logging.Logger:
    global _LOGGER_DATE
    _LOGGER.setLevel(logging.INFO)
    _LOGGER.propagate = False

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    if not any(getattr(handler, "_music_service_console", False) for handler in _LOGGER.handlers):
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler._music_service_console = True  # type: ignore[attr-defined]
        _LOGGER.addHandler(console_handler)

    today = date.today().isoformat()
    if _LOGGER_DATE != today:
        for handler in list(_LOGGER.handlers):
            if getattr(handler, "_music_service_file", False):
                _LOGGER.removeHandler(handler)
                handler.close()

        log_dir = config.carla_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / f"{today}.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler._music_service_file = True  # type: ignore[attr-defined]
        _LOGGER.addHandler(file_handler)
        _LOGGER_DATE = today

    return _LOGGER


def record_timing(timings: dict[str, float], name: str, started: float) -> None:
    timings[name] = round(time.monotonic() - started, 3)


def sanitize_filename_component(value: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*\s]+', "_", value.strip())
    sanitized = re.sub(r"_+", "_", sanitized).strip("._")
    return sanitized or "untitled"


def recorder_safe_basename(output_basename: str, job_id: str) -> str:
    if output_basename.isascii():
        return output_basename
    return f"render_{job_id}"


def _float_timing(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _base64_mp3_payload(mp3_path: Path) -> dict[str, object]:
    raw = mp3_path.read_bytes()
    return {
        "filename": mp3_path.name,
        "mime_type": "audio/mpeg",
        "encoding": "base64",
        "size_bytes": len(raw),
        "base64": base64.b64encode(raw).decode("ascii"),
    }


def _render_timing_summary(
    *,
    timings: dict[str, float],
    renderer_timings: dict[str, Any],
    mp3_path: Path,
    wav_path: Path,
) -> dict[str, object]:
    request_total = _float_timing(timings.get("request_total_seconds"))
    renderer_total = _float_timing(renderer_timings.get("total_seconds"))
    subprocess_total = _float_timing(renderer_timings.get("subprocess_seconds"))
    return {
        "mp3_generation_seconds": request_total,
        "renderer_total_seconds": renderer_total or subprocess_total,
        "record_audio_seconds": _float_timing(renderer_timings.get("record_audio_seconds")),
        "ffmpeg_mp3_seconds": _float_timing(renderer_timings.get("ffmpeg_mp3_seconds")),
        "midi_policy_seconds": _float_timing(timings.get("midi_policy_seconds")),
        "output_finalize_seconds": _float_timing(timings.get("output_finalize_seconds")),
        "mp3_base64_seconds": _float_timing(timings.get("mp3_base64_seconds")),
        "mp3_bytes": _file_size(mp3_path),
        "wav_bytes": _file_size(wav_path),
    }


def _renderer_stage_seconds(renderer_timings: dict[str, Any]) -> dict[str, float]:
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
        parsed = _float_timing(value)
        if parsed is not None:
            stages[key] = parsed
    return dict(sorted(stages.items(), key=lambda item: item[1], reverse=True))


def _renderer_record_audio_breakdown(renderer_timings: dict[str, Any]) -> dict[str, object]:
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
        parsed = _float_timing(renderer_timings.get(key))
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


def _first_present(*values: object) -> object | None:
    for value in values:
        if value is not None:
            return value
    return None


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{label} must be a string")
    stripped = value.strip()
    return stripped or None


def _optional_bool(value: object, label: str) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
    raise HTTPException(status_code=400, detail=f"{label} must be a boolean")


def _optional_int(value: object, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"{label} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{label} must be an integer") from exc


def _optional_float(value: object, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"{label} must be a number")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{label} must be a number") from exc


def _read_conf_json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        decoded = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(decoded, dict):
        raise HTTPException(status_code=400, detail=f"{label} must be a JSON object")
    return decoded


def _contains_cjk(value: str) -> bool:
    return any(
        "\u3400" <= char <= "\u9fff" or "\uf900" <= char <= "\ufaff"
        for char in value
    )


def _repair_zip_member_name(filename: str) -> str:
    if _contains_cjk(filename):
        return filename

    for source_encoding in ("latin1", "cp437"):
        try:
            candidate = filename.encode(source_encoding).decode("gbk")
        except UnicodeError:
            continue
        if candidate != filename and _contains_cjk(candidate):
            return candidate
    return filename


def _mapping_section(config: dict[str, Any], key: str) -> dict[str, Any]:
    value = config.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail=f"conf.json field {key} must be an object")
    return value


def _optional_mp3_bitrate(value: object, label: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"{label} must be a bitrate number or string")
    if isinstance(value, (int, float)):
        if value <= 0:
            raise HTTPException(status_code=400, detail=f"{label} must be greater than 0")
        return f"{int(value)}k"
    if isinstance(value, str):
        stripped = value.strip().lower()
        if not re.fullmatch(r"\d+[km]?", stripped):
            raise HTTPException(status_code=400, detail=f"{label} must be like 320 or 320k")
        return stripped if stripped[-1] in {"k", "m"} else f"{stripped}k"
    raise HTTPException(status_code=400, detail=f"{label} must be a bitrate number or string")


def _apply_conf_render_options(
    config: ServiceConfig,
    request_config: dict[str, Any],
) -> tuple[ServiceConfig, dict[str, object]]:
    render_config = _mapping_section(request_config, "render")
    output_config = _mapping_section(request_config, "output")

    output_format = (_optional_string(render_config.get("format"), "conf.json render.format") or "mp3").lower()
    if output_format != "mp3":
        raise HTTPException(status_code=400, detail="conf.json render.format currently only supports mp3")

    bitrate = _optional_mp3_bitrate(render_config.get("bitrate"), "conf.json render.bitrate")
    bit_depth = _optional_int(render_config.get("bit_depth"), "conf.json render.bit_depth")
    if bit_depth is not None and bit_depth != 16:
        raise HTTPException(status_code=400, detail="conf.json render.bit_depth currently only supports 16")

    loop = _optional_bool(render_config.get("loop"), "conf.json render.loop")
    samplerate = _optional_int(
        _first_present(output_config.get("samplerate"), output_config.get("sample_rate")),
        "conf.json output.samplerate",
    )
    if samplerate is not None and samplerate <= 0:
        raise HTTPException(status_code=400, detail="conf.json output.samplerate must be greater than 0")

    effective_audio = config.audio
    effective_encoding = config.encoding
    if samplerate is not None:
        effective_audio = replace(effective_audio, sample_rate=samplerate)
        effective_encoding = replace(effective_encoding, mp3_sample_rate=samplerate)
    if bitrate is not None:
        effective_encoding = replace(effective_encoding, mp3_bitrate=bitrate)

    effective_config = replace(config, audio=effective_audio, encoding=effective_encoding)
    return effective_config, {
        "format": output_format,
        "bitrate": bitrate or effective_config.encoding.mp3_bitrate,
        "bit_depth": bit_depth or 16,
        "loop": False if loop is None else loop,
        "samplerate": samplerate or effective_config.audio.sample_rate,
    }


def _apply_conf_defaults(
    config: dict[str, Any],
    *,
    plugin_id: str | None,
    style_id: str | None,
    style_name: str | None,
    max_seconds: float | None,
    apply_midi_policy: bool | None,
    midi_source_channel: int | None,
    midi_target_channel: int | None,
) -> tuple[str | None, str | None, str | None, float | None, bool | None, int | None, int | None]:
    midi_config = _mapping_section(config, "midi")
    render_config = _mapping_section(config, "render")

    plugin_id = plugin_id or _optional_string(config.get("plugin_id"), "conf.json plugin_id")
    style_id = style_id or _optional_string(config.get("style_id"), "conf.json style_id")
    style_name = style_name or _optional_string(config.get("style_name"), "conf.json style_name")
    max_seconds = max_seconds if max_seconds is not None else _optional_float(
        _first_present(config.get("max_seconds"), render_config.get("max_seconds")),
        "conf.json max_seconds",
    )
    apply_midi_policy = apply_midi_policy if apply_midi_policy is not None else _optional_bool(
        _first_present(config.get("apply_midi_policy"), midi_config.get("apply_midi_policy"), midi_config.get("apply_policy")),
        "conf.json apply_midi_policy",
    )
    midi_source_channel = midi_source_channel if midi_source_channel is not None else _optional_int(
        _first_present(config.get("midi_source_channel"), midi_config.get("source_channel")),
        "conf.json midi_source_channel",
    )
    midi_target_channel = midi_target_channel if midi_target_channel is not None else _optional_int(
        _first_present(config.get("midi_target_channel"), midi_config.get("target_channel")),
        "conf.json midi_target_channel",
    )
    return (
        plugin_id,
        style_id,
        style_name,
        max_seconds,
        apply_midi_policy,
        midi_source_channel,
        midi_target_channel,
    )


async def _read_upload_bytes(upload: UploadFile) -> bytes:
    data = await upload.read()
    if not data:
        raise HTTPException(status_code=400, detail=f"Uploaded file is empty: {upload.filename}")
    return data


async def _load_zip_bundle(upload: UploadFile) -> tuple[str, bytes, dict[str, Any], str]:
    suffix = Path(upload.filename or "bundle.zip").suffix.lower()
    if suffix != ".zip":
        raise HTTPException(status_code=400, detail="Zip bundle upload must be a .zip file")

    raw_zip = await _read_upload_bytes(upload)
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw_zip))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Uploaded zip bundle is invalid") from exc

    with archive:
        files = [info for info in archive.infolist() if not info.is_dir()]
        midi_members = [
            info
            for info in files
            if PurePosixPath(info.filename).suffix.lower() in {".mid", ".midi"}
        ]
        conf_members = [
            info
            for info in files
            if PurePosixPath(info.filename).name.lower() == "conf.json"
        ]
        if not conf_members:
            raise HTTPException(status_code=400, detail="Zip bundle must contain conf.json")
        if len(conf_members) > 1:
            raise HTTPException(status_code=400, detail="Zip bundle must contain only one conf.json")
        if not midi_members:
            raise HTTPException(status_code=400, detail="Zip bundle must contain a .mid or .midi file")
        if len(midi_members) > 1:
            raise HTTPException(status_code=400, detail="Zip bundle contains multiple MIDI files")

        conf_member = conf_members[0]
        midi_member = midi_members[0]
        config = _read_conf_json(archive.read(conf_member), conf_member.filename)
        midi_bytes = archive.read(midi_member)
        if not midi_bytes:
            raise HTTPException(status_code=400, detail=f"MIDI file is empty: {midi_member.filename}")
        return (
            _repair_zip_member_name(midi_member.filename),
            midi_bytes,
            config,
            _repair_zip_member_name(conf_member.filename),
        )


def get_config() -> ServiceConfig:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = load_config()
        _CONFIG.work_dir.mkdir(parents=True, exist_ok=True)
        _CONFIG.output_dir.mkdir(parents=True, exist_ok=True)
        get_logger(_CONFIG).info("music service config loaded config=%s", _CONFIG.config_path)
    return _CONFIG


def _plugin_category(plugin: PluginProfile) -> str:
    if plugin.id.startswith("kong_") or "kong" in plugin.name.lower():
        return "kong_audio"
    if plugin.type == "sf2":
        return "soundfont"
    if plugin.type == "vst3":
        return "vst3"
    if plugin.type == "vst2":
        return "vst2"
    return "other"


def _style_ready(config: ServiceConfig, style: StyleProfile, plugin: PluginProfile | None) -> bool:
    state_path = style.state or (plugin.state if plugin else None)
    state_exists = state_path.is_file() if state_path else False
    state_binary = _read_state_binary(state_path)
    state_binary_matches_plugin = _state_binary_matches_plugin(config, state_binary, plugin)
    return bool(
        plugin
        and plugin.enabled
        and style.enabled
        and (state_path is None or state_exists)
        and state_binary_matches_plugin
    )


@app.get("/health")
def health() -> dict[str, str]:
    try:
        config = get_config()
    except ConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "config": str(config.config_path)}


@app.get("/v1/catalog")
def catalog() -> dict[str, object]:
    config = get_config()
    styles_by_plugin: dict[str, list[StyleProfile]] = {}
    for style in config.styles:
        styles_by_plugin.setdefault(style.plugin_id, []).append(style)

    categories: dict[str, int] = {}
    plugins: list[dict[str, object]] = []
    for plugin in config.plugins:
        category = _plugin_category(plugin)
        categories[category] = categories.get(category, 0) + 1
        plugin_styles = styles_by_plugin.get(plugin.id, [])
        plugins.append(
            {
                "id": plugin.id,
                "name": plugin.name,
                "category": category,
                "format": plugin.type,
                "enabled": plugin.enabled,
                "path": str(plugin.path),
                "path_exists": plugin.path.is_file(),
                "runtime_path": plugin.runtime_path,
                "configured_state": str(plugin.state) if plugin.state else None,
                "style_count": len(plugin_styles),
                "ready_style_count": sum(
                    1 for style in plugin_styles if _style_ready(config, style, plugin)
                ),
                "styles": [
                    {
                        "id": style.id,
                        "name": style.name,
                        "instrument": style.instrument,
                        "articulation": style.articulation,
                        "gm_programs": list(style.gm_programs),
                        "enabled": style.enabled,
                        "ready": _style_ready(config, style, plugin),
                    }
                    for style in plugin_styles
                ],
                "notes": plugin.notes,
            }
        )

    return {
        "runtime_model": "per_request_subprocess",
        "loaded_plugin_count": 0,
        "loaded_plugin_note": "The API starts a Carla subprocess for each render and closes it after the job, so plugins are not kept loaded between requests.",
        "configured_plugin_count": len(config.plugins),
        "enabled_plugin_count": sum(1 for plugin in config.plugins if plugin.enabled),
        "style_count": len(config.styles),
        "categories": categories,
        "plugins": plugins,
        "output_dir": str(config.output_dir),
        "work_dir": str(config.work_dir),
    }


@app.get("/v1/plugins")
def list_plugins() -> dict[str, list[dict[str, str | bool]]]:
    config = get_config()
    return {
        "plugins": [
            {
                "id": plugin.id,
                "name": plugin.name,
                "type": plugin.type,
                "enabled": plugin.enabled,
                "path": str(plugin.path),
                "runtime_path": plugin.runtime_path,
                "has_state": plugin.state is not None,
                "notes": plugin.notes,
            }
            for plugin in config.plugins
        ]
    }


@app.get("/v1/styles")
def list_styles() -> dict[str, list[dict[str, object]]]:
    config = get_config()
    styles: list[dict[str, object]] = []
    for style in config.styles:
        plugin = config.get_plugin(style.plugin_id)
        state_path = style.state or (plugin.state if plugin else None)
        state_exists = state_path.is_file() if state_path else False
        state_binary = _read_state_binary(state_path)
        state_binary_matches_plugin = _state_binary_matches_plugin(config, state_binary, plugin)
        styles.append(
            {
                "id": style.id,
                "name": style.name,
                "plugin_id": style.plugin_id,
                "instrument": style.instrument,
                "articulation": style.articulation,
                "gm_programs": list(style.gm_programs),
                "enabled": style.enabled,
                "plugin_enabled": bool(plugin and plugin.enabled),
                "has_state": state_path is not None,
                "state_exists": state_exists,
                "state_binary": state_binary,
                "state_binary_matches_plugin": state_binary_matches_plugin,
                "ready": bool(
                    plugin
                    and plugin.enabled
                    and style.enabled
                    and (state_path is None or state_exists)
                    and state_binary_matches_plugin
                ),
                "parameter_count": len(style.parameters),
                "midi_policy": {
                    "enabled": style.midi_policy.enabled,
                    "source_channel": style.midi_policy.source_channel,
                    "target_channel": style.midi_policy.target_channel,
                    "remove_program_changes": style.midi_policy.remove_program_changes,
                    "remove_bank_select": style.midi_policy.remove_bank_select,
                    "keep_control_changes": list(style.midi_policy.keep_control_changes),
                    "keep_pitch_bend": style.midi_policy.keep_pitch_bend,
                    "keep_note_aftertouch": style.midi_policy.keep_note_aftertouch,
                    "keep_channel_pressure": style.midi_policy.keep_channel_pressure,
                    "keep_sysex": style.midi_policy.keep_sysex,
                    "notes": style.midi_policy.notes,
                },
                "notes": style.notes,
            }
        )
    return {"styles": styles}


def _parse_request_parameters(raw_value: str | None) -> tuple[ParameterOverride, ...]:
    if not raw_value:
        return ()

    try:
        decoded = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="parameters_json must be valid JSON") from exc

    if isinstance(decoded, dict):
        items = [
            {"index": raw_index, "value": raw_parameter_value}
            for raw_index, raw_parameter_value in decoded.items()
        ]
    elif isinstance(decoded, list):
        items = decoded
    else:
        raise HTTPException(status_code=400, detail="parameters_json must be a JSON object or array")

    parameters: list[ParameterOverride] = []
    for item_index, item in enumerate(items):
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail=f"parameters_json[{item_index}] must be an object")
        try:
            parameter_index = int(item["index"])
            parameter_value = float(item["value"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail=f"parameters_json[{item_index}] requires numeric index and value",
            ) from exc
        if parameter_index < 0:
            raise HTTPException(status_code=400, detail=f"parameters_json[{item_index}].index must be >= 0")
        parameters.append(
            ParameterOverride(
                index=parameter_index,
                value=parameter_value,
                name=str(item.get("name", "")),
            )
        )

    return tuple(parameters)


def _is_auto_style_request(style_id: str | None) -> bool:
    return bool(style_id and style_id.strip().lower() in {"auto", "__auto__"})


def _style_by_gm_program(config: ServiceConfig) -> dict[int, StyleProfile]:
    result: dict[int, StyleProfile] = {}
    for style in config.styles:
        if not style.enabled:
            continue
        for program in style.gm_programs:
            result.setdefault(program, style)
    return result


def _selected_channel_programs(midi_channel_analysis: dict[str, object]) -> tuple[int | None, list[int]]:
    selected_channel = midi_channel_analysis.get("selected_source_channel")
    if not isinstance(selected_channel, int):
        return None, []

    for channel_info in midi_channel_analysis.get("channels", []):
        if not isinstance(channel_info, dict):
            continue
        if channel_info.get("channel") != selected_channel:
            continue
        programs = [
            int(program)
            for program in channel_info.get("programs", [])
            if isinstance(program, int)
        ]
        return selected_channel, programs
    return selected_channel, []


def _resolve_auto_style(
    config: ServiceConfig,
    midi_channel_analysis: dict[str, object],
) -> tuple[StyleProfile, dict[str, object]]:
    program_styles = _style_by_gm_program(config)
    selected_channel, programs = _selected_channel_programs(midi_channel_analysis)

    for program in programs:
        candidates = []
        if 1 <= program <= 128:
            candidates.append((program - 1, "midi_payload_plus_one"))
        if 0 <= program <= 127:
            candidates.append((program, "direct"))
        for gm_program, match_mode in candidates:
            style = program_styles.get(gm_program)
            if style is not None:
                return style, {
                    "enabled": True,
                    "selected_style_id": style.id,
                    "selected_plugin_id": style.plugin_id,
                    "selected_source_channel": selected_channel,
                    "channel_programs": programs,
                    "matched_gm_program": gm_program,
                    "match_mode": match_mode,
                    "fallback": False,
                }

    fallback = config.get_style("sf2_musyng_kite_gm")
    if fallback is None or not fallback.enabled:
        raise HTTPException(
            status_code=400,
            detail="Auto style routing did not match a GM program and sf2_musyng_kite_gm is not available",
        )
    return fallback, {
        "enabled": True,
        "selected_style_id": fallback.id,
        "selected_plugin_id": fallback.plugin_id,
        "selected_source_channel": selected_channel,
        "channel_programs": programs,
        "matched_gm_program": None,
        "match_mode": "fallback_sf2_musyng_kite_gm",
        "fallback": True,
    }


def _resolve_plugin_and_style(
    config: ServiceConfig,
    plugin_id: str | None,
    style_id: str | None,
) -> tuple[PluginProfile, StyleProfile | None]:
    if style_id:
        style = config.get_style(style_id)
        if style is None:
            raise HTTPException(status_code=404, detail=f"Unknown style: {style_id}")
        if not style.enabled:
            raise HTTPException(status_code=400, detail=f"Style is disabled: {style_id}")
        plugin = config.get_plugin(style.plugin_id)
        if plugin is None:
            raise HTTPException(status_code=500, detail=f"Style references missing plugin: {style.plugin_id}")
        if plugin_id and plugin_id != plugin.id:
            raise HTTPException(
                status_code=400,
                detail=f"Style {style_id} uses plugin {plugin.id}, not {plugin_id}",
            )
        return plugin, style

    if not plugin_id:
        raise HTTPException(status_code=400, detail="Either plugin_id or style_id is required")

    plugin = config.get_plugin(plugin_id)
    if plugin is None:
        raise HTTPException(status_code=404, detail=f"Unknown plugin: {plugin_id}")
    return plugin, None


def _validate_midi_channel(value: int | None, label: str) -> int | None:
    if value is None:
        return None
    if value < 1 or value > 16:
        raise HTTPException(status_code=400, detail=f"{label} must be a MIDI channel from 1 to 16")
    return value


def _build_effective_midi_policy(
    style: StyleProfile | None,
    apply_midi_policy: bool | None,
    midi_source_channel: int | None,
    midi_target_channel: int | None,
) -> MidiPolicy | None:
    source_channel = _validate_midi_channel(midi_source_channel, "midi_source_channel")
    target_channel = _validate_midi_channel(midi_target_channel, "midi_target_channel")
    base_policy = style.midi_policy if style else MidiPolicy()
    enabled = base_policy.enabled if apply_midi_policy is None else apply_midi_policy
    if not enabled:
        return None
    return replace(
        base_policy,
        enabled=True,
        source_channel=source_channel if source_channel is not None else base_policy.source_channel,
        target_channel=target_channel if target_channel is not None else base_policy.target_channel,
    )


@app.post("/v1/render")
async def render_midi(
    plugin_id: str | None = Form(None),
    style_id: str | None = Form(None),
    midi: UploadFile | None = File(None),
    data: UploadFile | None = File(None),
    bundle: UploadFile | None = File(None),
    style_name: str | None = Form(None),
    max_seconds: float | None = Form(None),
    parameters_json: str | None = Form(None),
    apply_midi_policy: bool | None = Form(None),
    midi_source_channel: int | None = Form(None),
    midi_target_channel: int | None = Form(None),
) -> dict[str, object]:
    request_started = time.monotonic()
    timings: dict[str, float] = {}

    stage_started = time.monotonic()
    config = get_config()
    logger = get_logger(config)
    record_timing(timings, "load_config_seconds", stage_started)

    if data is not None and bundle is not None:
        raise HTTPException(status_code=400, detail="Use either data or bundle for zip upload, not both")
    bundle_upload = data or bundle
    if midi is not None and bundle_upload is not None:
        raise HTTPException(status_code=400, detail="Use either midi upload or zip bundle upload, not both")
    if midi is None and bundle_upload is None:
        raise HTTPException(status_code=400, detail="Upload a zip bundle in data/bundle or a MIDI file in midi")

    job_id = uuid.uuid4().hex
    job_dir = config.work_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=False)

    stage_started = time.monotonic()
    bundle_config: dict[str, Any] = {}
    bundle_conf_name: str | None = None
    input_mode = "midi"
    if bundle_upload is not None:
        input_mode = "zip"
        midi_filename, midi_bytes, bundle_config, bundle_conf_name = await _load_zip_bundle(bundle_upload)
        suffix = PurePosixPath(midi_filename).suffix.lower()
        original_midi_stem = sanitize_filename_component(PurePosixPath(midi_filename).stem)
        midi_path = job_dir / f"input{suffix}"
        midi_path.write_bytes(midi_bytes)
    else:
        assert midi is not None
        midi_filename = midi.filename or "input.mid"
        suffix = Path(midi_filename).suffix.lower()
        if suffix not in {".mid", ".midi"}:
            raise HTTPException(status_code=400, detail="Upload must be a .mid or .midi file")
        original_midi_stem = sanitize_filename_component(Path(midi_filename).stem)
        midi_path = job_dir / f"input{suffix}"
        with midi_path.open("wb") as handle:
            while True:
                chunk = await midi.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
    record_timing(timings, "upload_save_seconds", stage_started)

    (
        plugin_id,
        style_id,
        style_name,
        max_seconds,
        apply_midi_policy,
        midi_source_channel,
        midi_target_channel,
    ) = _apply_conf_defaults(
        bundle_config,
        plugin_id=plugin_id,
        style_id=style_id,
        style_name=style_name,
        max_seconds=max_seconds,
        apply_midi_policy=apply_midi_policy,
        midi_source_channel=midi_source_channel,
        midi_target_channel=midi_target_channel,
    )
    effective_config, render_options = _apply_conf_render_options(config, bundle_config)

    midi_channel_analysis: dict[str, object] | None = None
    auto_route_info: dict[str, object] | None = None
    if _is_auto_style_request(style_id):
        stage_started = time.monotonic()
        try:
            midi_channel_analysis = analyze_midi_channels(midi_path)
        except MidiPolicyError as exc:
            logger.exception("render auto style analysis failed job_id=%s error=%s", job_id, exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        auto_style, auto_route_info = _resolve_auto_style(config, midi_channel_analysis)
        style_id = auto_style.id
        selected_source_channel = auto_route_info.get("selected_source_channel")
        if midi_source_channel is None and isinstance(selected_source_channel, int):
            midi_source_channel = selected_source_channel
        record_timing(timings, "auto_route_seconds", stage_started)
    else:
        timings["auto_route_seconds"] = 0.0

    stage_started = time.monotonic()
    plugin, style = _resolve_plugin_and_style(config, plugin_id, style_id)
    if not plugin.enabled:
        raise HTTPException(status_code=400, detail=f"Plugin is disabled: {plugin.id}")
    record_timing(timings, "resolve_request_seconds", stage_started)

    logger.info(
        "render start job_id=%s input_mode=%s plugin_id=%s style_id=%s midi=%s conf=%s source_channel=%s target_channel=%s render_options=%s",
        job_id,
        input_mode,
        plugin.id,
        style.id if style else None,
        midi_filename,
        bundle_conf_name,
        midi_source_channel,
        midi_target_channel,
        json.dumps(render_options, ensure_ascii=False, sort_keys=True),
    )
    if auto_route_info is not None:
        logger.info(
            "auto route selected job_id=%s route=%s",
            job_id,
            json.dumps(auto_route_info, ensure_ascii=False, sort_keys=True),
        )

    stage_started = time.monotonic()
    parameter_overrides = list(style.parameters if style else ())
    parameter_overrides.extend(_parse_request_parameters(parameters_json))
    selected_state = style.state if style and style.state else plugin.state
    selected_style_name = style_name or (style.name if style else None)
    output_style_name = sanitize_filename_component(selected_style_name or plugin.name)
    output_timestamp = datetime.now().strftime("%Y%m%d%H%M")
    output_basename = f"{original_midi_stem}_{output_style_name}_{output_timestamp}"
    recorder_output_basename = recorder_safe_basename(output_basename, job_id)
    render_midi_path = midi_path
    midi_policy_stats: dict[str, object] | None = None
    effective_midi_policy = _build_effective_midi_policy(
        style=style,
        apply_midi_policy=apply_midi_policy,
        midi_source_channel=midi_source_channel,
        midi_target_channel=midi_target_channel,
    )
    record_timing(timings, "prepare_render_seconds", stage_started)

    if effective_midi_policy is not None and effective_midi_policy.source_channel is None:
        stage_started = time.monotonic()
        if midi_channel_analysis is None:
            try:
                midi_channel_analysis = analyze_midi_channels(midi_path)
            except MidiPolicyError as exc:
                logger.exception("render midi channel analysis failed job_id=%s error=%s", job_id, exc)
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        inferred_source_channel = midi_channel_analysis.get("selected_source_channel")
        if isinstance(inferred_source_channel, int):
            effective_midi_policy = replace(effective_midi_policy, source_channel=inferred_source_channel)
        record_timing(timings, "midi_channel_analysis_seconds", stage_started)
    else:
        timings["midi_channel_analysis_seconds"] = 0.0

    if effective_midi_policy is not None:
        stage_started = time.monotonic()
        render_midi_path = job_dir / "input.policy.mid"
        try:
            midi_policy_stats = preprocess_midi(
                input_path=midi_path,
                output_path=render_midi_path,
                policy=effective_midi_policy,
            )
        except MidiPolicyError as exc:
            logger.exception("render midi policy failed job_id=%s error=%s", job_id, exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if midi_channel_analysis is not None:
            midi_policy_stats["source_channel_auto_selected"] = True
            midi_policy_stats["channel_analysis"] = midi_channel_analysis
        record_timing(timings, "midi_policy_seconds", stage_started)
    else:
        timings["midi_policy_seconds"] = 0.0

    stage_started = time.monotonic()
    try:
        result = run_render(
            config=effective_config,
            plugin=plugin,
            midi_path=render_midi_path,
            output_dir=effective_config.output_dir,
            style_name=selected_style_name,
            output_basename=recorder_output_basename,
            max_seconds=max_seconds,
            plugin_state=selected_state,
            parameter_overrides=parameter_overrides,
        )
    except RenderError as exc:
        logger.exception("render failed job_id=%s error=%s", job_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    record_timing(timings, "renderer_subprocess_seconds", stage_started)

    stage_started = time.monotonic()
    final_mp3_path = config.output_dir / f"{output_basename}.mp3"
    final_wav_path = config.output_dir / f"{output_basename}.wav"
    if recorder_output_basename != output_basename:
        result.mp3_path.replace(final_mp3_path)
        result.wav_path.replace(final_wav_path)
    else:
        final_mp3_path = result.mp3_path
        final_wav_path = result.wav_path
    record_timing(timings, "output_finalize_seconds", stage_started)

    stage_started = time.monotonic()
    mp3_file = _base64_mp3_payload(final_mp3_path)
    record_timing(timings, "mp3_base64_seconds", stage_started)
    timings["request_total_seconds"] = round(time.monotonic() - request_started, 3)

    renderer_timings = result.timings
    timing_summary = _render_timing_summary(
        timings=timings,
        renderer_timings=renderer_timings,
        mp3_path=final_mp3_path,
        wav_path=final_wav_path,
    )
    renderer_stage_seconds = _renderer_stage_seconds(renderer_timings)
    record_audio_breakdown = _renderer_record_audio_breakdown(renderer_timings)
    top_renderer_stage = next(iter(renderer_stage_seconds.items()), None)
    logger.info(
        (
            "mp3 timing job_id=%s style_id=%s output=%s "
            "mp3_generation=%.3fs renderer=%.3fs record_audio=%.3fs "
            "ffmpeg_mp3=%.3fs midi_policy=%.3fs output_finalize=%.3fs "
            "mp3_bytes=%s wav_bytes=%s"
        ),
        job_id,
        style.id if style else None,
        final_mp3_path.name,
        timing_summary.get("mp3_generation_seconds") or 0.0,
        timing_summary.get("renderer_total_seconds") or 0.0,
        timing_summary.get("record_audio_seconds") or 0.0,
        timing_summary.get("ffmpeg_mp3_seconds") or 0.0,
        timing_summary.get("midi_policy_seconds") or 0.0,
        timing_summary.get("output_finalize_seconds") or 0.0,
        timing_summary.get("mp3_bytes"),
        timing_summary.get("wav_bytes"),
    )
    logger.info(
        "renderer timing detail job_id=%s top_stage=%s top_seconds=%.3fs midi_length=%.3fs record_target=%.3fs stages=%s",
        job_id,
        top_renderer_stage[0] if top_renderer_stage else None,
        top_renderer_stage[1] if top_renderer_stage else 0.0,
        _float_timing(renderer_timings.get("midi_length_seconds")) or 0.0,
        _float_timing(renderer_timings.get("record_target_seconds")) or 0.0,
        json.dumps(renderer_stage_seconds, ensure_ascii=False, sort_keys=False),
    )
    logger.info(
        "record audio breakdown job_id=%s style_id=%s breakdown=%s",
        job_id,
        style.id if style else None,
        json.dumps(record_audio_breakdown, ensure_ascii=False, sort_keys=True),
    )
    logger.info(
        "render complete job_id=%s elapsed=%.3fs mp3=%s wav=%s encoding=%s timings=%s renderer_timings=%s",
        job_id,
        timings["request_total_seconds"],
        final_mp3_path,
        final_wav_path,
        json.dumps(result.encoding, ensure_ascii=False, sort_keys=True),
        json.dumps(timings, ensure_ascii=False, sort_keys=True),
        json.dumps(renderer_timings, ensure_ascii=False, sort_keys=True),
    )

    return {
        "job_id": job_id,
        "plugin_id": plugin.id,
        "style_id": style.id if style else None,
        "input": {
            "mode": input_mode,
            "midi_filename": midi_filename,
            "conf_filename": bundle_conf_name,
        },
        "parameters_applied": len(parameter_overrides),
        "render_options": render_options,
        "midi_policy_applied": midi_policy_stats is not None,
        "midi_policy": midi_policy_stats,
        "auto_route": auto_route_info,
        "mp3_path": str(final_mp3_path),
        "wav_path": str(final_wav_path),
        "output_basename": output_basename,
        "mp3_file": mp3_file,
        "encoding": result.encoding,
        "elapsed_seconds": round(result.elapsed_seconds, 3),
        "timings": timings,
        "renderer_timings": renderer_timings,
        "timing_summary": timing_summary,
        "renderer_stage_seconds": renderer_stage_seconds,
        "record_audio_breakdown": record_audio_breakdown,
        "download": {
            "mp3": f"/v1/jobs/{job_id}/{final_mp3_path.name}",
            "wav": f"/v1/jobs/{job_id}/{final_wav_path.name}",
        },
    }


@app.get("/v1/jobs/{job_id}/{filename}")
def download_job_file(job_id: str, filename: str) -> FileResponse:
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    config = get_config()
    job_dir = (config.work_dir / job_id).resolve()
    file_path = (job_dir / filename).resolve()
    if job_dir not in file_path.parents or not file_path.is_file():
        output_dir = config.output_dir.resolve()
        file_path = (output_dir / filename).resolve()
        if output_dir not in file_path.parents or not file_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")

    media_type = "audio/mpeg" if file_path.suffix.lower() == ".mp3" else "audio/wav"
    return FileResponse(file_path, media_type=media_type, filename=file_path.name)
