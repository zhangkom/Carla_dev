from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from datetime import date, datetime
from dataclasses import replace
from pathlib import Path

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
from .midi_policy import MidiPolicyError, preprocess_midi
from .renderer import RenderError, run_render


app = FastAPI(title="Carla Music Service", version="0.1.0")
_CONFIG: ServiceConfig | None = None
_LOGGER = logging.getLogger("music_service")
_LOGGER_DATE: str | None = None


def _normalize_path_text(value: str) -> str:
    return str(Path(value).expanduser()).replace("/", "\\").lower()


def _read_state_binary(state_path: Path | None) -> str | None:
    if state_path is None or not state_path.is_file():
        return None
    try:
        text = state_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = re.search(r"<Binary>(.*?)</Binary>", text, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


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


def get_config() -> ServiceConfig:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = load_config()
        _CONFIG.work_dir.mkdir(parents=True, exist_ok=True)
        _CONFIG.output_dir.mkdir(parents=True, exist_ok=True)
        get_logger(_CONFIG).info("music service config loaded config=%s", _CONFIG.config_path)
    return _CONFIG


@app.get("/health")
def health() -> dict[str, str]:
    try:
        config = get_config()
    except ConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "config": str(config.config_path)}


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
        state_binary_matches_plugin = (
            state_binary is None
            or plugin is None
            or _normalize_path_text(state_binary) == _normalize_path_text(str(plugin.path))
        )
        styles.append(
            {
                "id": style.id,
                "name": style.name,
                "plugin_id": style.plugin_id,
                "instrument": style.instrument,
                "articulation": style.articulation,
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
    midi: UploadFile = File(...),
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
    plugin, style = _resolve_plugin_and_style(config, plugin_id, style_id)
    if not plugin.enabled:
        raise HTTPException(status_code=400, detail=f"Plugin is disabled: {plugin.id}")
    record_timing(timings, "resolve_request_seconds", stage_started)

    suffix = Path(midi.filename or "input.mid").suffix.lower()
    if suffix not in {".mid", ".midi"}:
        raise HTTPException(status_code=400, detail="Upload must be a .mid or .midi file")
    original_midi_stem = sanitize_filename_component(Path(midi.filename or "input.mid").stem)

    job_id = uuid.uuid4().hex
    job_dir = config.work_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    midi_path = job_dir / f"input{suffix}"

    logger.info(
        "render start job_id=%s plugin_id=%s style_id=%s midi=%s source_channel=%s target_channel=%s",
        job_id,
        plugin.id,
        style.id if style else None,
        midi.filename,
        midi_source_channel,
        midi_target_channel,
    )

    stage_started = time.monotonic()
    with midi_path.open("wb") as handle:
        while True:
            chunk = await midi.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    record_timing(timings, "upload_save_seconds", stage_started)

    stage_started = time.monotonic()
    parameter_overrides = list(style.parameters if style else ())
    parameter_overrides.extend(_parse_request_parameters(parameters_json))
    selected_state = style.state if style and style.state else plugin.state
    selected_style_name = style_name or (style.name if style else None)
    output_style_name = sanitize_filename_component(selected_style_name or plugin.name)
    output_timestamp = datetime.now().strftime("%Y%m%d%H%M")
    output_basename = f"{original_midi_stem}_{output_style_name}_{output_timestamp}"
    render_midi_path = midi_path
    midi_policy_stats: dict[str, object] | None = None
    effective_midi_policy = _build_effective_midi_policy(
        style=style,
        apply_midi_policy=apply_midi_policy,
        midi_source_channel=midi_source_channel,
        midi_target_channel=midi_target_channel,
    )
    record_timing(timings, "prepare_render_seconds", stage_started)

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
        record_timing(timings, "midi_policy_seconds", stage_started)
    else:
        timings["midi_policy_seconds"] = 0.0

    stage_started = time.monotonic()
    try:
        result = run_render(
            config=config,
            plugin=plugin,
            midi_path=render_midi_path,
            output_dir=config.output_dir,
            style_name=selected_style_name,
            output_basename=output_basename,
            max_seconds=max_seconds,
            plugin_state=selected_state,
            parameter_overrides=parameter_overrides,
        )
    except RenderError as exc:
        logger.exception("render failed job_id=%s error=%s", job_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    record_timing(timings, "renderer_subprocess_seconds", stage_started)
    timings["request_total_seconds"] = round(time.monotonic() - request_started, 3)

    renderer_timings = result.timings
    logger.info(
        "render complete job_id=%s elapsed=%.3fs mp3=%s wav=%s encoding=%s timings=%s renderer_timings=%s",
        job_id,
        timings["request_total_seconds"],
        result.mp3_path,
        result.wav_path,
        json.dumps(result.encoding, ensure_ascii=False, sort_keys=True),
        json.dumps(timings, ensure_ascii=False, sort_keys=True),
        json.dumps(renderer_timings, ensure_ascii=False, sort_keys=True),
    )

    return {
        "job_id": job_id,
        "plugin_id": plugin.id,
        "style_id": style.id if style else None,
        "parameters_applied": len(parameter_overrides),
        "midi_policy_applied": midi_policy_stats is not None,
        "midi_policy": midi_policy_stats,
        "mp3_path": str(result.mp3_path),
        "wav_path": str(result.wav_path),
        "output_basename": output_basename,
        "encoding": result.encoding,
        "elapsed_seconds": round(result.elapsed_seconds, 3),
        "timings": timings,
        "renderer_timings": renderer_timings,
        "download": {
            "mp3": f"/v1/jobs/{job_id}/{result.mp3_path.name}",
            "wav": f"/v1/jobs/{job_id}/{result.wav_path.name}",
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
