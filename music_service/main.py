# /**
# * File name: main.py
# * Brief: MGSC DAW 渲染服务模块
# * Function:
# *     提供 FastAPI 渲染接口、音源配置、MIDI 策略和渲染调度能力
# * Author: 咪咕数创工程架构组
# *     MGSC AI Software Architecture group
# * Version: V2.5.10
# * Date: 2026/04/30
# */

from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import subprocess
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

from .async_jobs import (
    get_async_executor,
    normalize_callback_url,
    read_async_status,
    run_async_render_and_callback,
    timestamp_now,
    write_async_status,
)
from .auto_routes import (
    build_auto_render_routes,
    is_auto_style_request,
    resolve_auto_style,
    route_plugin,
    route_policy,
    route_style,
)
from .config import (
    ConfigError,
    MidiPolicy,
    ParameterOverride,
    PluginProfile,
    ServiceConfig,
    StyleProfile,
    load_config,
)
from .instrument_mapping import (
    InstrumentMappingError,
    instrument_mapping_path,
    load_instrument_mappings,
    style_for_programs_from_mapping,
)
from .midi_policy import MidiPolicyError, analyze_midi_channels, isolate_midi_track, preprocess_midi
from .render_outputs import (
    base64_mp3_payload as _base64_mp3_payload,
    encode_mp3_file as _encode_mp3_file,
    float_timing as _float_timing,
    mix_wav_files as _mix_wav_files,
    recorder_safe_basename,
    render_timing_summary as _render_timing_summary,
    renderer_record_audio_breakdown as _renderer_record_audio_breakdown,
    renderer_stage_seconds as _renderer_stage_seconds,
    sanitize_filename_component,
)
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


def _zip_member_basename(value: object) -> str | None:
    path_text = _optional_string(value, "conf.json route json path")
    if not path_text:
        return None
    return PurePosixPath(path_text.replace("\\", "/")).name.lower()


def _find_zip_member_by_name(files: list[zipfile.ZipInfo], requested_name: str) -> zipfile.ZipInfo | None:
    normalized_request = requested_name.replace("\\", "/").lower().lstrip("/")
    requested_basename = PurePosixPath(normalized_request).name
    for info in files:
        normalized_member = info.filename.replace("\\", "/").lower().lstrip("/")
        if normalized_member == normalized_request:
            return info
    for info in files:
        member_basename = PurePosixPath(info.filename.replace("\\", "/")).name.lower()
        if member_basename == requested_basename:
            return info
    return None


def _merge_route_json(config: dict[str, Any], route_config: dict[str, Any], *, label: str) -> None:
    for key in ("tracks", "vst", "sf2"):
        if key not in route_config:
            continue
        if key in config:
            raise HTTPException(status_code=400, detail=f"Duplicate {key} in conf.json and {label}")
        config[key] = route_config[key]


def _load_linked_route_jsons(
    archive: zipfile.ZipFile,
    files: list[zipfile.ZipInfo],
    config: dict[str, Any],
) -> list[str]:
    loaded: list[str] = []
    refs = [
        ("vstConf", _first_present(config.get("vstConf"), config.get("vst_conf"), config.get("vst_json"))),
        ("sf2Conf", _first_present(config.get("sf2Conf"), config.get("sf2_conf"), config.get("sf2_json"))),
    ]
    for label, ref_value in refs:
        requested_name = _zip_member_basename(ref_value)
        if not requested_name:
            continue
        member = _find_zip_member_by_name(files, requested_name)
        if member is None:
            raise HTTPException(
                status_code=400,
                detail=f"conf.json {label} references {requested_name}, but it was not found in the zip bundle",
            )
        route_config = _read_conf_json(archive.read(member), member.filename)
        _merge_route_json(config, route_config, label=member.filename)
        loaded.append(_repair_zip_member_name(member.filename))
    return loaded


def _artifact_archive_root(config: ServiceConfig) -> Path | None:
    raw_value = os.environ.get("MUSIC_SERVICE_ARTIFACT_ARCHIVE_ROOT")
    if raw_value is not None:
        value = raw_value.strip()
        if value.lower() in {"0", "false", "off", "no", "none"}:
            return None
        if value:
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = config.carla_root / path
            return path.resolve()
    return (config.carla_root / "temp").resolve()


def _artifact_archive_dir(config: ServiceConfig, job_id: str) -> Path | None:
    root = _artifact_archive_root(config)
    if root is None:
        return None
    return root / datetime.now().strftime("%Y%m%d") / job_id


def _artifact_safe_name(prefix: str, filename: str | None, fallback_suffix: str) -> str:
    candidate = Path(filename or "").name
    suffix = Path(candidate).suffix or fallback_suffix
    stem = sanitize_filename_component(Path(candidate).stem) or "upload"
    return f"{prefix}_{stem}{suffix}"


def _archive_bytes(
    archive_dir: Path | None,
    filename: str,
    data: bytes,
    *,
    logger: logging.Logger,
) -> Path | None:
    if archive_dir is None:
        return None
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        target = archive_dir / filename
        target.write_bytes(data)
        return target
    except OSError:
        logger.warning("failed to archive input artifact path=%s", archive_dir, exc_info=True)
        return None


def _archive_file(
    archive_dir: Path | None,
    source_path: Path,
    *,
    logger: logging.Logger,
) -> Path | None:
    if archive_dir is None or not source_path.is_file():
        return None
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        target = archive_dir / source_path.name
        if source_path.resolve() != target.resolve():
            shutil.copy2(source_path, target)
        return target
    except OSError:
        logger.warning("failed to archive output artifact source=%s dir=%s", source_path, archive_dir, exc_info=True)
        return None


def _archive_response(archive_dir: Path | None, files: dict[str, Path | None]) -> dict[str, object] | None:
    if archive_dir is None:
        return None
    payload: dict[str, object] = {"dir": str(archive_dir)}
    archived_files = {key: str(value) for key, value in files.items() if value is not None}
    if archived_files:
        payload["files"] = archived_files
    return payload


async def _load_zip_bundle(upload: UploadFile) -> tuple[str, bytes, dict[str, Any], str, bytes]:
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
        _load_linked_route_jsons(archive, files, config)
        midi_bytes = archive.read(midi_member)
        if not midi_bytes:
            raise HTTPException(status_code=400, detail=f"MIDI file is empty: {midi_member.filename}")
        return (
            _repair_zip_member_name(midi_member.filename),
            midi_bytes,
            config,
            _repair_zip_member_name(conf_member.filename),
            raw_zip,
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


@app.get("/mgsc_daw_service/health")
def health() -> dict[str, str]:
    try:
        config = get_config()
    except ConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "config": str(config.config_path)}


@app.get("/mgsc_daw_service/v1/catalog")
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
                        "vst2_preset": style.vst2_preset,
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


@app.get("/mgsc_daw_service/v1/plugins")
def list_plugins() -> dict[str, list[dict[str, object]]]:
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


@app.get("/mgsc_daw_service/v1/styles")
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
                "vst2_preset": style.vst2_preset,
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


@app.get("/mgsc_daw_service/v1/instrument-mappings")
def list_instrument_mappings() -> dict[str, object]:
    config = get_config()
    try:
        mappings = load_instrument_mappings(config)
        mapping_path = instrument_mapping_path(config)
    except InstrumentMappingError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    plugin_counts: dict[str, int] = {}
    bank_counts: dict[str, int] = {}
    items: list[dict[str, object]] = []
    for entry in mappings:
        plugin_counts[entry.plugin_id] = plugin_counts.get(entry.plugin_id, 0) + 1
        bank_counts[str(entry.bank)] = bank_counts.get(str(entry.bank), 0) + 1
        style = None
        try:
            style, match = style_for_programs_from_mapping(
                config,
                [entry.program + 1],
                channel=10 if entry.bank == 128 else 1,
                bank_programs=[
                    {
                        "bank": entry.bank,
                        "bank_candidates": [entry.bank],
                        "program": entry.program + 1,
                        "gm_program": entry.program,
                    }
                ],
            )
        except InstrumentMappingError:
            match = {}
        items.append(
            {
                "id": entry.id,
                "bank": entry.bank,
                "program": entry.program,
                "plugin_id": entry.plugin_id,
                "plugin_name": entry.plugin_name,
                "plugin_type": entry.plugin_type,
                "target_bank": entry.target_bank,
                "target_program": entry.target_program,
                "implementation": entry.implementation,
                "needs_confirmation": list(entry.needs_confirmation),
                "notes": list(entry.notes),
                "resolved_style_id": style.id if style else None,
                "resolved_plugin_id": style.plugin_id if style else None,
                "fallback": bool(match.get("fallback")) if isinstance(match, dict) else None,
                "fallback_reason": match.get("fallback_reason") if isinstance(match, dict) else None,
            }
        )

    return {
        "mapping_source": str(mapping_path),
        "mapping_count": len(mappings),
        "plugin_counts": plugin_counts,
        "bank_counts": bank_counts,
        "mappings": items,
    }


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


def _normalized_lookup_text(value: object) -> str:
    return re.sub(r"[^0-9a-z]+", "", str(value or "").casefold())


def _optional_route_int(value: object) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _looks_like_drum_route(item: dict[str, Any]) -> bool:
    route_text = " ".join(
        str(item.get(key) or "")
        for key in ("track_name", "sf2_path", "vst_path", "patch", "patch_name", "param_key_name")
    )
    normalized_tokens = {
        token
        for token in re.split(r"[^0-9a-z]+", route_text.casefold())
        if token
    }
    compact_text = _normalized_lookup_text(route_text)
    return (
        "drum" in compact_text
        or "drumkit" in compact_text
        or bool(normalized_tokens & {"kit", "rock"})
    )


def _style_from_web_bank_patch(
    config: ServiceConfig,
    item: dict[str, Any],
) -> tuple[StyleProfile | None, dict[str, object] | None]:
    raw_bank = item.get("bank")
    raw_patch = _first_present(item.get("patch"), item.get("program"), item.get("patch_name"))
    bank = _optional_route_int(raw_bank)
    program = _optional_route_int(raw_patch)
    if program is None and item.get("patch") not in (None, ""):
        program = _optional_route_int(item.get("patch_name"))
    if program is None:
        return None, None

    bank_candidates: list[int] = []
    if _looks_like_drum_route(item):
        bank_candidates.append(128)
    if bank is not None:
        bank_candidates.append(bank)
    bank_candidates.append(0)

    for bank_candidate in dict.fromkeys(bank_candidates):
        try:
            style, match = style_for_programs_from_mapping(
                config,
                [program],
                channel=10 if bank_candidate == 128 else None,
                bank_programs=[
                    {
                        "bank": bank_candidate,
                        "bank_candidates": [bank_candidate],
                        "program": program + 1,
                        "gm_program": program,
                    }
                ],
            )
        except InstrumentMappingError:
            continue
        if match.get("fallback"):
            continue
        return style, {
            **match,
            "source": "web_bank_patch",
            "web_bank": bank_candidate,
            "web_program": program,
        }
    return None, None


def _style_from_legacy_vst_fields(
    config: ServiceConfig,
    *,
    vst_path: str | None,
    param_key_name: str | None,
) -> StyleProfile | None:
    normalized_vst_path = _normalized_lookup_text(vst_path)
    normalized_param = _normalized_lookup_text(param_key_name)
    if not normalized_vst_path and not normalized_param:
        return None

    best_match: tuple[int, StyleProfile] | None = None
    for style in config.styles:
        search_text = _normalized_lookup_text(
            " ".join(
                [
                    style.id,
                    style.name,
                    style.instrument,
                    style.articulation,
                    style.vst2_preset,
                ]
            )
        )
        plugin = config.get_plugin(style.plugin_id)
        plugin_text = _normalized_lookup_text(
            " ".join([plugin.id, plugin.name, str(plugin.path)]) if plugin else style.plugin_id
        )
        score = 0
        if normalized_param and normalized_param in search_text:
            score += 10
        if normalized_vst_path and (
            normalized_vst_path in search_text
            or normalized_vst_path in plugin_text
            or plugin_text in normalized_vst_path
        ):
            score += 5
        if score and (best_match is None or score > best_match[0]):
            best_match = (score, style)
    return best_match[1] if best_match else None


def _style_from_legacy_sf2_fields(
    config: ServiceConfig,
    *,
    sf2_path: str | None,
    bank: object,
    patch: object,
) -> StyleProfile | None:
    normalized_sf2_path = _normalized_lookup_text(sf2_path)
    for style in config.styles:
        plugin = config.get_plugin(style.plugin_id)
        if plugin is None or plugin.type != "sf2":
            continue
        style_text = _normalized_lookup_text(" ".join([style.id, style.name, str(plugin.path)]))
        if normalized_sf2_path and normalized_sf2_path not in style_text:
            continue
        return style

    if not normalized_sf2_path and patch not in (None, ""):
        try:
            program = int(patch) + 1
            bank_value = int(bank) if bank not in (None, "") else 0
            style, _match = style_for_programs_from_mapping(
                config,
                [program],
                bank_programs=[{"bank": bank_value, "program": program}],
            )
            return style
        except (TypeError, ValueError, InstrumentMappingError):
            return None
    return None


def _manual_track_key(item: dict[str, Any]) -> tuple[str, object] | None:
    track_id = _optional_route_int(item.get("id"))
    if track_id is not None:
        return ("id", track_id)
    track_name = str(item.get("track_name") or "").strip()
    if track_name:
        return ("track_name", _normalized_lookup_text(track_name))
    return None


def _manual_track_priority(item: dict[str, Any]) -> tuple[int, int]:
    source = str(item.get("_manual_source") or "")
    source_rank = {"tracks": 3, "vst": 2, "sf2": 1}.get(source, 0)
    if item.get("style_id") not in (None, ""):
        return (100, source_rank)
    if item.get("plugin_id") not in (None, ""):
        return (90, source_rank)
    if _optional_route_int(_first_present(item.get("patch"), item.get("program"), item.get("patch_name"))) is not None:
        return (80, source_rank)
    if item.get("patch") not in (None, "") and _optional_route_int(item.get("patch_name")) is not None:
        return (80, source_rank)
    if item.get("param_key_name") not in (None, "") or item.get("InstrumentList") not in (None, ""):
        return (60, source_rank)
    if item.get("vst_path") not in (None, ""):
        return (50, source_rank)
    if item.get("sf2_path") not in (None, ""):
        return (40, source_rank)
    return (0, source_rank)


def _manual_track_items(config: dict[str, Any]) -> list[dict[str, Any]]:
    tracks: list[dict[str, Any]] = []
    for candidate in ("tracks", "vst", "sf2"):
        if candidate in config:
            raw_tracks = config.get(candidate)
            if raw_tracks is None:
                continue
            if not isinstance(raw_tracks, list):
                raise HTTPException(status_code=400, detail=f"conf.json {candidate} must be an array")
            for index, item in enumerate(raw_tracks):
                if not isinstance(item, dict):
                    raise HTTPException(status_code=400, detail=f"conf.json {candidate}[{index}] must be an object")
                track_item = dict(item)
                track_item["_manual_source"] = candidate
                track_item["_manual_index"] = len(tracks)
                tracks.append(track_item)

    selected_by_key: dict[tuple[str, object], dict[str, Any]] = {}
    result: list[dict[str, Any]] = []
    for item in tracks:
        key = _manual_track_key(item)
        if key is None:
            result.append(item)
            continue
        current = selected_by_key.get(key)
        if current is None:
            selected_by_key[key] = item
            result.append(item)
            continue
        current_priority = _manual_track_priority(current)
        item_priority = _manual_track_priority(item)
        current_sources = list(current.get("_manual_duplicate_sources") or [current.get("_manual_source")])
        current_sources.append(item.get("_manual_source"))
        if item_priority > current_priority:
            item["_manual_duplicate_sources"] = current_sources
            selected_by_key[key] = item
            result[result.index(current)] = item
        else:
            current["_manual_duplicate_sources"] = current_sources
    return result



def _build_manual_track_routes(
    config: ServiceConfig,
    bundle_config: dict[str, Any],
) -> list[dict[str, object]]:
    routes: list[dict[str, object]] = []
    for index, item in enumerate(_manual_track_items(bundle_config)):
        manual_source = str(item.get("_manual_source") or "tracks")
        track_id = _optional_int(item.get("id"), f"conf.json tracks[{index}].id")
        track_name = _optional_string(item.get("track_name"), f"conf.json tracks[{index}].track_name")
        style_id = _optional_string(item.get("style_id"), f"conf.json tracks[{index}].style_id")
        plugin_id = _optional_string(item.get("plugin_id"), f"conf.json tracks[{index}].plugin_id")
        midi_source_channel = _optional_int(
            _first_present(item.get("midi_source_channel"), item.get("source_channel")),
            f"conf.json tracks[{index}].midi_source_channel",
        )
        midi_target_channel = _optional_int(
            _first_present(item.get("midi_target_channel"), item.get("target_channel")),
            f"conf.json tracks[{index}].midi_target_channel",
        )

        if style_id:
            style = config.get_style(style_id)
            if style is None:
                raise HTTPException(status_code=404, detail=f"Unknown style in tracks[{index}]: {style_id}")
            match_info: dict[str, object] = {"source": f"conf.json {manual_source}", "direct_style_id": style_id}
        else:
            style, match_info_or_none = _style_from_web_bank_patch(config, item)
            match_info = match_info_or_none or {"source": f"conf.json {manual_source}"}
            if style is None:
                style = _style_from_legacy_vst_fields(
                    config,
                    vst_path=_optional_string(item.get("vst_path"), f"conf.json tracks[{index}].vst_path"),
                    param_key_name=_optional_string(
                        _first_present(item.get("param_key_name"), item.get("InstrumentList")),
                        f"conf.json tracks[{index}].param_key_name",
                    ),
                )
                if style is not None:
                    match_info["source"] = "legacy_vst_fields"
            if style is None and manual_source == "sf2":
                style = _style_from_legacy_sf2_fields(
                    config,
                    sf2_path=_optional_string(item.get("sf2_path"), f"conf.json tracks[{index}].sf2_path"),
                    bank=item.get("bank"),
                    patch=item.get("patch"),
                )
                if style is not None:
                    match_info["source"] = "legacy_sf2_fields"
            if style is None and plugin_id is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"conf.json {manual_source}[{index}] requires style_id, plugin_id, "
                        "web bank/patch, or recognizable legacy vst/sf2 fields"
                    ),
                )

        plugin, resolved_style = _resolve_plugin_and_style(
            config,
            plugin_id=plugin_id,
            style_id=style.id if style else None,
        )
        if not plugin.enabled:
            raise HTTPException(status_code=400, detail=f"Plugin is disabled: {plugin.id}")
        if resolved_style is not None and not resolved_style.enabled:
            raise HTTPException(status_code=400, detail=f"Style is disabled: {resolved_style.id}")

        policy = _build_effective_midi_policy(
            style=resolved_style,
            apply_midi_policy=True,
            midi_source_channel=midi_source_channel,
            midi_target_channel=midi_target_channel,
        )
        if policy is None:
            policy = MidiPolicy(enabled=True, source_channel=midi_source_channel, target_channel=midi_target_channel)
        routes.append(
            {
                "mode": "manual_track",
                "track_id": track_id,
                "track_name": track_name,
                "style": resolved_style,
                "plugin": plugin,
                "policy": policy,
                "match": {
                    **match_info,
                    "route_file": f"conf.json {manual_source}",
                    "route_sources": item.get("_manual_duplicate_sources") or [manual_source],
                    "legacy_vst_path": item.get("vst_path"),
                    "legacy_sf2_path": item.get("sf2_path"),
                    "legacy_param_key_name": item.get("param_key_name"),
                    "legacy_param_value_name": item.get("param_value_name"),
                    "legacy_bank": item.get("bank"),
                    "legacy_patch": item.get("patch"),
                    "legacy_patch_name": item.get("patch_name"),
                },
                "note_on_count": None,
                "note_tick_duration": None,
                "bank_programs": [],
                "track_names": [track_name] if track_name else [],
            }
        )
    return routes


async def _clone_upload_for_background(upload: UploadFile | None) -> UploadFile | None:
    if upload is None:
        return None
    data = await _read_upload_bytes(upload)
    return UploadFile(file=io.BytesIO(data), filename=upload.filename)


async def _clone_render_uploads(
    midi: UploadFile | None,
    data: UploadFile | None,
    bundle: UploadFile | None,
) -> tuple[UploadFile | None, UploadFile | None, UploadFile | None]:
    if data is not None and bundle is not None:
        raise HTTPException(status_code=400, detail="Use either data or bundle for zip upload, not both")
    bundle_upload = data or bundle
    if midi is not None and bundle_upload is not None:
        raise HTTPException(status_code=400, detail="Use either midi upload or zip bundle upload, not both")
    if midi is None and bundle_upload is None:
        raise HTTPException(status_code=400, detail="Upload a zip bundle in data/bundle or a MIDI file in midi")

    cloned_midi = await _clone_upload_for_background(midi)
    cloned_data = await _clone_upload_for_background(data)
    cloned_bundle = await _clone_upload_for_background(bundle)
    return cloned_midi, cloned_data, cloned_bundle


@app.post("/mgsc_daw_service/v1/render")
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
    callbackurl: str | None = Form(None),
) -> dict[str, object]:
    try:
        normalized_callback_url = normalize_callback_url(callbackurl)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if normalized_callback_url is None:
        return await _render_midi_from_uploads(
            plugin_id=plugin_id,
            style_id=style_id,
            midi=midi,
            data=data,
            bundle=bundle,
            style_name=style_name,
            max_seconds=max_seconds,
            parameters_json=parameters_json,
            apply_midi_policy=apply_midi_policy,
            midi_source_channel=midi_source_channel,
            midi_target_channel=midi_target_channel,
        )

    job_id = uuid.uuid4().hex
    config = get_config()
    logger = get_logger(config)
    cloned_midi, cloned_data, cloned_bundle = await _clone_render_uploads(midi, data, bundle)
    render_kwargs: dict[str, object] = {
        "plugin_id": plugin_id,
        "style_id": style_id,
        "midi": cloned_midi,
        "data": cloned_data,
        "bundle": cloned_bundle,
        "style_name": style_name,
        "max_seconds": max_seconds,
        "parameters_json": parameters_json,
        "apply_midi_policy": apply_midi_policy,
        "midi_source_channel": midi_source_channel,
        "midi_target_channel": midi_target_channel,
    }
    accepted_payload = {
        "job_id": job_id,
        "status": "accepted",
        "async": True,
        "callbackurl": normalized_callback_url,
        "status_url": f"/mgsc_daw_service/v1/jobs/{job_id}/status",
        "accepted_at": timestamp_now(),
    }
    write_async_status(config.work_dir, job_id, accepted_payload)
    logger.info("async render accepted job_id=%s callbackurl=%s", job_id, normalized_callback_url)

    get_async_executor().submit(
        run_async_render_and_callback,
        callbackurl=normalized_callback_url,
        job_id=job_id,
        render_kwargs=render_kwargs,
        render_callable=_render_midi_from_uploads,
        work_dir=config.work_dir,
        logger=logger,
    )

    return accepted_payload


async def _render_midi_from_uploads(
    plugin_id: str | None = None,
    style_id: str | None = None,
    midi: UploadFile | None = None,
    data: UploadFile | None = None,
    bundle: UploadFile | None = None,
    style_name: str | None = None,
    max_seconds: float | None = None,
    parameters_json: str | None = None,
    apply_midi_policy: bool | None = None,
    midi_source_channel: int | None = None,
    midi_target_channel: int | None = None,
    job_id_override: str | None = None,
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

    job_id = job_id_override or uuid.uuid4().hex
    job_dir = config.work_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    archive_dir = _artifact_archive_dir(config, job_id)
    archived_files: dict[str, Path | None] = {}

    stage_started = time.monotonic()
    bundle_config: dict[str, Any] = {}
    bundle_conf_name: str | None = None
    input_mode = "midi"
    if bundle_upload is not None:
        input_mode = "zip"
        midi_filename, midi_bytes, bundle_config, bundle_conf_name, raw_zip = await _load_zip_bundle(bundle_upload)
        archived_files["input_zip"] = _archive_bytes(
            archive_dir,
            _artifact_safe_name("input", bundle_upload.filename, ".zip"),
            raw_zip,
            logger=logger,
        )
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
        archived_files["input_midi"] = _archive_file(archive_dir, midi_path, logger=logger)
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
    manual_render_routes = _build_manual_track_routes(config, bundle_config)
    if manual_render_routes and is_auto_style_request(style_id):
        raise HTTPException(status_code=400, detail="Use either conf.json tracks/vst/sf2 or style_id=auto, not both")

    if not manual_render_routes and is_auto_style_request(style_id):
        stage_started = time.monotonic()
        try:
            midi_channel_analysis = analyze_midi_channels(midi_path)
        except MidiPolicyError as exc:
            logger.exception("render auto style analysis failed job_id=%s error=%s", job_id, exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        auto_style, auto_route_info = resolve_auto_style(config, midi_channel_analysis)
        style_id = auto_style.id
        selected_source_channel = auto_route_info.get("selected_source_channel")
        if midi_source_channel is None and isinstance(selected_source_channel, int):
            midi_source_channel = selected_source_channel
        record_timing(timings, "auto_route_seconds", stage_started)
    else:
        timings["auto_route_seconds"] = 0.0

    stage_started = time.monotonic()
    if manual_render_routes:
        plugin = route_plugin(manual_render_routes[0])
        first_style = manual_render_routes[0].get("style")
        style = first_style if isinstance(first_style, StyleProfile) else None
    else:
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
    if manual_render_routes:
        logger.info("manual track routes selected job_id=%s route_count=%s", job_id, len(manual_render_routes))

    stage_started = time.monotonic()
    request_parameter_overrides = list(_parse_request_parameters(parameters_json))
    parameter_overrides = list(style.parameters if style else ())
    parameter_overrides.extend(request_parameter_overrides)
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

    auto_render_routes: list[dict[str, object]] = []
    if auto_route_info is not None and midi_channel_analysis is not None:
        auto_render_routes = build_auto_render_routes(config, midi_channel_analysis)
    route_mix_info: dict[str, object] | None = auto_route_info
    route_mix_kind = "auto"
    route_mix_mode = "multi_channel_mix"
    if manual_render_routes:
        auto_render_routes = manual_render_routes
        first_route_match = manual_render_routes[0].get("match")
        manual_source = (
            first_route_match.get("source")
            if isinstance(first_route_match, dict)
            else "conf.json tracks"
        )
        route_mix_info = {
            "enabled": True,
            "mode": "manual_track",
            "source": manual_source,
        }
        route_mix_kind = "manual_track"
        route_mix_mode = "manual_track_mix"

    if route_mix_info is not None and auto_render_routes and (manual_render_routes or len(auto_render_routes) > 1):
        route_started = time.monotonic()
        route_details: list[dict[str, object]] = []
        route_wav_paths: list[Path] = []
        route_result_timings: list[dict[str, Any]] = []
        route_midi_policy_seconds = 0.0

        selected_style_name = style_name or ("Manual Tracks" if manual_render_routes else "Auto Mix")
        output_style_name = sanitize_filename_component(selected_style_name)
        output_basename = f"{original_midi_stem}_{output_style_name}_{output_timestamp}"
        final_mp3_path = config.output_dir / f"{output_basename}.mp3"
        final_wav_path = config.output_dir / f"{output_basename}.wav"

        logger.info(
            "%s route multi start job_id=%s route_count=%s output=%s",
            route_mix_kind,
            job_id,
            len(auto_render_routes),
            output_basename,
        )

        try:
            for route_index, route in enumerate(auto_render_routes, start=1):
                current_route_style_value = route.get("style")
                current_route_style = (
                    current_route_style_value if isinstance(current_route_style_value, StyleProfile) else None
                )
                current_route_plugin = route_plugin(route)
                current_route_policy = route_policy(route)
                route_channel = route.get("channel")
                route_track_id = route.get("track_id")
                route_track_name = route.get("track_name")
                route_label = (
                    f"track{route_track_id}_{sanitize_filename_component(str(route_track_name))}"
                    if manual_render_routes
                    else f"ch{int(route_channel)}"
                )

                stage_started = time.monotonic()
                route_midi_path = job_dir / f"{route_mix_kind}_route_{route_index:02d}_{route_label}.mid"
                if manual_render_routes:
                    route_stats = isolate_midi_track(
                        input_path=midi_path,
                        output_path=route_midi_path,
                        policy=current_route_policy,
                        track_id=int(route_track_id) if isinstance(route_track_id, int) else None,
                        track_name=str(route_track_name) if route_track_name else None,
                    )
                else:
                    route_stats = preprocess_midi(
                        input_path=midi_path,
                        output_path=route_midi_path,
                        policy=current_route_policy,
                    )
                route_midi_policy_seconds += time.monotonic() - stage_started

                route_parameters = list(current_route_style.parameters if current_route_style else ())
                route_parameters.extend(request_parameter_overrides)
                route_state = (
                    current_route_style.state
                    if current_route_style and current_route_style.state
                    else current_route_plugin.state
                )
                route_style_name = current_route_style.name if current_route_style else current_route_plugin.name
                route_style_id = current_route_style.id if current_route_style else None
                route_output_basename = (
                    f"render_{job_id}_route{route_index:02d}_{route_label}_{route_style_id or current_route_plugin.id}"
                )

                route_result = run_render(
                    config=effective_config,
                    plugin=current_route_plugin,
                    midi_path=route_midi_path,
                    output_dir=effective_config.output_dir,
                    style_name=route_style_name,
                    output_basename=route_output_basename,
                    max_seconds=max_seconds,
                    plugin_state=route_state,
                    parameter_overrides=route_parameters,
                )
                route_wav_paths.append(route_result.wav_path)
                route_result_timings.append(route_result.timings)
                route_details.append(
                    {
                        "channel": route_channel,
                        "track_id": route_track_id,
                        "track_name": route_track_name,
                        "plugin_id": current_route_plugin.id,
                        "style_id": route_style_id,
                        "style_name": route_style_name,
                        "match": route["match"],
                        "note_on_count": route["note_on_count"],
                        "note_tick_duration": route["note_tick_duration"],
                        "bank_programs": route["bank_programs"],
                        "track_names": route["track_names"],
                        "parameters_applied": len(route_parameters),
                        "midi_policy": route_stats,
                        "wav_path": str(route_result.wav_path),
                        "mp3_path": str(route_result.mp3_path),
                        "renderer_timings": route_result.timings,
                    }
                )
        except MidiPolicyError as exc:
            logger.exception("%s route MIDI policy failed job_id=%s error=%s", route_mix_kind, job_id, exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (RenderError, OSError, subprocess.CalledProcessError, TypeError) as exc:
            logger.exception("%s route render failed job_id=%s error=%s", route_mix_kind, job_id, exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        timings["midi_channel_analysis_seconds"] = 0.0
        timings["midi_policy_seconds"] = round(route_midi_policy_seconds, 3)
        record_timing(timings, "renderer_subprocess_seconds", route_started)

        stage_started = time.monotonic()
        try:
            mix_stats = _mix_wav_files(effective_config, route_wav_paths, final_wav_path)
            encode_stats = _encode_mp3_file(effective_config, final_wav_path, final_mp3_path)
        except (OSError, subprocess.CalledProcessError, RenderError) as exc:
            logger.exception("auto route output finalize failed job_id=%s error=%s", job_id, exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        record_timing(timings, "output_finalize_seconds", stage_started)

        stage_started = time.monotonic()
        mp3_file = _base64_mp3_payload(final_mp3_path)
        record_timing(timings, "mp3_base64_seconds", stage_started)
        timings["request_total_seconds"] = round(time.monotonic() - request_started, 3)

        renderer_timings: dict[str, Any] = {
            "auto_route_multi": True,
            "route_kind": route_mix_kind,
            "route_count": len(auto_render_routes),
            "route_renderer_timings": route_result_timings,
            "total_seconds": round(time.monotonic() - route_started, 3),
            "subprocess_seconds": timings["renderer_subprocess_seconds"],
            **mix_stats,
            **encode_stats,
        }
        encoding = {
            "mp3_bitrate": effective_config.encoding.mp3_bitrate,
            "mp3_sample_rate": effective_config.encoding.mp3_sample_rate or effective_config.audio.sample_rate,
            "mp3_channels": effective_config.encoding.mp3_channels,
            "mp3_id3v2_version": effective_config.encoding.mp3_id3v2_version,
        }
        timing_summary = _render_timing_summary(
            timings=timings,
            renderer_timings=renderer_timings,
            mp3_path=final_mp3_path,
            wav_path=final_wav_path,
        )
        renderer_stage_seconds = _renderer_stage_seconds(renderer_timings)
        record_audio_breakdown = _renderer_record_audio_breakdown(renderer_timings)
        archived_files["mp3"] = _archive_file(archive_dir, final_mp3_path, logger=logger)
        archived_files["wav"] = _archive_file(archive_dir, final_wav_path, logger=logger)
        artifact_archive = _archive_response(archive_dir, archived_files)
        auto_route_response = {
            **route_mix_info,
            "mode": route_mix_mode,
            "route_count": len(auto_render_routes),
            "routes": route_details,
        }
        midi_policy_stats = {
            "enabled": True,
            "auto_route_multi": True,
            "route_kind": route_mix_kind,
            "route_count": len(auto_render_routes),
            "channel_analysis": midi_channel_analysis,
            "routes": [
                {
                    "channel": detail.get("channel"),
                    "track_id": detail.get("track_id"),
                    "track_name": detail.get("track_name"),
                    "plugin_id": detail["plugin_id"],
                    "style_id": detail["style_id"],
                    "midi_policy": detail["midi_policy"],
                }
                for detail in route_details
            ],
        }
        logger.info(
            (
                "%s route multi complete job_id=%s output=%s routes=%s "
                "mp3_generation=%.3fs renderer=%.3fs mix=%.3fs mp3=%.3fs "
                "mp3_bytes=%s wav_bytes=%s"
            ),
            route_mix_kind,
            job_id,
            final_mp3_path.name,
            len(auto_render_routes),
            timing_summary.get("mp3_generation_seconds") or 0.0,
            timing_summary.get("renderer_total_seconds") or 0.0,
            renderer_timings.get("mix_wav_seconds") or 0.0,
            renderer_timings.get("ffmpeg_mp3_seconds") or 0.0,
            timing_summary.get("mp3_bytes"),
            timing_summary.get("wav_bytes"),
        )
        return {
            "job_id": job_id,
            "plugin_id": "manual_track_mix" if manual_render_routes else "auto_mix",
            "style_id": "manual_track_mix" if manual_render_routes else "auto_mix",
            "input": {
                "mode": input_mode,
                "midi_filename": midi_filename,
                "conf_filename": bundle_conf_name,
            },
            "parameters_applied": sum(int(route_detail["parameters_applied"]) for route_detail in route_details),
            "render_options": render_options,
            "midi_policy_applied": True,
            "midi_policy": midi_policy_stats,
            "auto_route": auto_route_response,
            "mp3_path": str(final_mp3_path),
            "wav_path": str(final_wav_path),
            "output_basename": output_basename,
            "mp3_file": mp3_file,
            "encoding": encoding,
            "elapsed_seconds": timings["request_total_seconds"],
            "timings": timings,
            "renderer_timings": renderer_timings,
            "timing_summary": timing_summary,
            "renderer_stage_seconds": renderer_stage_seconds,
            "record_audio_breakdown": record_audio_breakdown,
            "artifact_archive": artifact_archive,
            "download": {
                "mp3": f"/mgsc_daw_service/v1/jobs/{job_id}/{final_mp3_path.name}",
                "wav": f"/mgsc_daw_service/v1/jobs/{job_id}/{final_wav_path.name}",
            },
        }

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
    archived_files["mp3"] = _archive_file(archive_dir, final_mp3_path, logger=logger)
    archived_files["wav"] = _archive_file(archive_dir, final_wav_path, logger=logger)
    artifact_archive = _archive_response(archive_dir, archived_files)
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
        "artifact_archive": artifact_archive,
        "download": {
            "mp3": f"/mgsc_daw_service/v1/jobs/{job_id}/{final_mp3_path.name}",
            "wav": f"/mgsc_daw_service/v1/jobs/{job_id}/{final_wav_path.name}",
        },
    }


@app.get("/mgsc_daw_service/v1/jobs/{job_id}/status")
def get_job_status(job_id: str) -> dict[str, object]:
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    config = get_config()
    status = read_async_status(config.work_dir, job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Job status not found")
    return status


@app.get("/mgsc_daw_service/v1/jobs/{job_id}/{filename}")
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
