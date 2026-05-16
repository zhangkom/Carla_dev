# /**
# * File name: main.py
# * Brief: MGSC DAW 渲染服务模块
# * Function:
# *     提供 FastAPI 渲染接口、音源配置、MIDI 策略和渲染调度能力
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
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from .async_jobs import (
    get_async_executor,
    normalize_callback_url,
    read_async_status,
    run_async_render_and_callback,
    timestamp_now,
    write_async_status,
)
from .artifact_archive import (
    archive_bytes as _archive_bytes,
    archive_file as _archive_file,
    archive_response as _archive_response,
    artifact_archive_dir as _artifact_archive_dir,
    artifact_safe_name as _artifact_safe_name,
)
from .auto_routes import (
    build_auto_render_routes,
    is_auto_style_request,
    resolve_auto_style,
    route_plugin,
    route_policy,
)
from .config import (
    ConfigError,
    ParameterOverride,
    PluginProfile,
    ServiceConfig,
    StyleProfile,
    load_config,
    plugin_path_exists,
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
from .request_config import (
    apply_conf_defaults as _apply_conf_defaults,
    apply_conf_render_options as _apply_conf_render_options,
    conf_debug_enabled as _conf_debug_enabled,
    public_render_response as _public_render_response,
    route_config_summary as _route_config_summary,
)
from .renderer import RenderError, RenderResult, run_render
from .route_resolution import (
    build_effective_midi_policy as _build_effective_midi_policy,
    build_manual_track_routes as _build_manual_track_routes,
    manual_route_log_summary as _manual_route_log_summary,
    resolve_plugin_and_style as _resolve_plugin_and_style,
)
from .upload_bundle import clone_render_uploads as _clone_render_uploads
from .upload_bundle import load_zip_bundle as _load_zip_bundle
from .upload_bundle import read_upload_bytes as _read_upload_bytes


app = FastAPI(title="Carla Music Service", version="0.1.0")
_CONFIG: ServiceConfig | None = None
_LOGGER = logging.getLogger("music_service")
_LOGGER_DATE: str | None = None


def _error_response_payload(status_code: int, detail: object, *, code: str | None = None) -> dict[str, object]:
    if isinstance(detail, str):
        message = detail
    else:
        message = json.dumps(detail, ensure_ascii=False, default=str)
    return {
        "http_code": status_code,
        "status": "failed",
        "error": {
            "code": code or f"HTTP_{status_code}",
            "message": message,
        },
    }


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder(_error_response_payload(exc.status_code, exc.detail)),
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=jsonable_encoder(_error_response_payload(422, exc.errors(), code="VALIDATION_ERROR")),
    )


def _normalize_path_text(value: str) -> str:
    return str(Path(value).expanduser()).replace("/", "\\").lower()


def _path_stem_text(value: str | Path) -> str:
    filename = re.split(r"[\\/]", str(value).strip())[-1]
    return filename.rsplit(".", 1)[0].lower()


def _log_service_event(logger: logging.Logger, message: str, **fields: object) -> None:
    logger.info("%s %s", message, json.dumps(fields, ensure_ascii=False, sort_keys=True, default=str))


def _upload_filename(upload: UploadFile | None) -> str | None:
    return upload.filename if upload is not None else None


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


def _env_enabled(name: str) -> bool:
    value = os.environ.get(name, "").strip().lower()
    return bool(value) and value not in {"0", "false", "off", "no"}


def _parallel_route_workers(route_count: int) -> int:
    if route_count <= 1 or not _env_enabled("MUSIC_SERVICE_PARALLEL_ROUTES"):
        return 1
    raw_value = os.environ.get("MUSIC_SERVICE_PARALLEL_ROUTE_WORKERS", "2").strip()
    try:
        requested_workers = int(raw_value)
    except ValueError:
        requested_workers = 2
    return max(1, min(route_count, requested_workers))


@dataclass(frozen=True)
class _PreparedRenderInput:
    input_mode: str
    midi_filename: str
    midi_path: Path
    original_midi_stem: str
    bundle_config: dict[str, Any]
    bundle_conf_name: str | None
    debug_enabled: bool
    archived_files: dict[str, Path | None]


async def _prepare_render_input(
    *,
    logger: logging.Logger,
    job_id: str,
    job_dir: Path,
    archive_dir: Path | None,
    midi: UploadFile | None,
    data: UploadFile | None,
    bundle: UploadFile | None,
) -> _PreparedRenderInput:
    if data is not None and bundle is not None:
        raise HTTPException(status_code=400, detail="Use either data or bundle for zip upload, not both")
    bundle_upload = data or bundle
    if midi is not None and bundle_upload is not None:
        raise HTTPException(status_code=400, detail="Use either midi upload or zip bundle upload, not both")
    if midi is None and bundle_upload is None:
        raise HTTPException(status_code=400, detail="Upload a zip bundle in data/bundle or a MIDI file in midi")

    archived_files: dict[str, Path | None] = {}
    _log_service_event(
        logger,
        "start to process render job",
        job_id=job_id,
        input_mode="zip" if bundle_upload is not None else "midi",
        midi_upload=_upload_filename(midi),
        bundle_upload=_upload_filename(bundle_upload),
        work_dir=str(job_dir),
        artifact_archive_dir=str(archive_dir) if archive_dir else None,
    )

    bundle_config: dict[str, Any] = {}
    bundle_conf_name: str | None = None
    input_mode = "midi"
    if bundle_upload is not None:
        input_mode = "zip"
        zip_bundle = await _load_zip_bundle(bundle_upload)
        midi_filename = zip_bundle.midi_filename
        midi_bytes = zip_bundle.midi_bytes
        bundle_config = zip_bundle.config
        bundle_conf_name = zip_bundle.conf_filename
        _log_service_event(
            logger,
            "input zip loaded",
            job_id=job_id,
            zip_filename=bundle_upload.filename,
            zip_bytes=len(zip_bundle.raw_zip),
            midi_filename=midi_filename,
            midi_bytes=len(midi_bytes),
            conf_filename=bundle_conf_name,
            conf_summary=_route_config_summary(bundle_config),
        )
        archived_files["input_zip"] = _archive_bytes(
            archive_dir,
            _artifact_safe_name("input", bundle_upload.filename, ".zip"),
            zip_bundle.raw_zip,
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

    debug_enabled = _conf_debug_enabled(bundle_config) if bundle_config else False
    _log_service_event(
        logger,
        "input saved",
        job_id=job_id,
        input_mode=input_mode,
        midi_filename=midi_filename,
        midi_path=str(midi_path),
        midi_bytes=midi_path.stat().st_size if midi_path.is_file() else None,
        conf_filename=bundle_conf_name,
        debug=debug_enabled,
    )
    return _PreparedRenderInput(
        input_mode=input_mode,
        midi_filename=midi_filename,
        midi_path=midi_path,
        original_midi_stem=original_midi_stem,
        bundle_config=bundle_config,
        bundle_conf_name=bundle_conf_name,
        debug_enabled=debug_enabled,
        archived_files=archived_files,
    )


_RouteRenderResult = tuple[int, Path, dict[str, Any], dict[str, object], float]


def _run_route_render_tasks(
    routes: list[dict[str, object]],
    workers: int,
    render_one_route: Callable[[int, dict[str, object]], _RouteRenderResult],
) -> list[_RouteRenderResult]:
    indexed_routes = list(enumerate(routes, start=1))
    if workers <= 1:
        return [render_one_route(route_index, route) for route_index, route in indexed_routes]

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="route-render") as executor:
        futures = [
            executor.submit(render_one_route, route_index, route)
            for route_index, route in indexed_routes
        ]
        return [future.result() for future in futures]


def _build_render_payload(
    *,
    job_id: str,
    plugin_id: str,
    style_id: str | None,
    input_mode: str,
    midi_filename: str | None,
    conf_filename: str | None,
    parameters_applied: int,
    render_options: dict[str, object],
    midi_policy_applied: bool,
    midi_policy: dict[str, object] | None,
    auto_route: dict[str, object] | None,
    final_mp3_path: Path,
    final_wav_path: Path,
    output_basename: str,
    mp3_file: dict[str, object],
    encoding: dict[str, object],
    elapsed_seconds: float,
    renderer_elapsed_seconds: float | None,
    timings: dict[str, float],
    renderer_timings: dict[str, Any],
    timing_summary: dict[str, object],
    renderer_stage_seconds: dict[str, float],
    record_audio_breakdown: dict[str, object],
    artifact_archive: dict[str, object] | None,
) -> dict[str, object]:
    return {
        "job_id": job_id,
        "plugin_id": plugin_id,
        "style_id": style_id,
        "input": {
            "mode": input_mode,
            "midi_filename": midi_filename,
            "conf_filename": conf_filename,
        },
        "parameters_applied": parameters_applied,
        "render_options": render_options,
        "midi_policy_applied": midi_policy_applied,
        "midi_policy": midi_policy,
        "auto_route": auto_route,
        "mp3_path": str(final_mp3_path),
        "wav_path": str(final_wav_path),
        "output_basename": output_basename,
        "mp3_file": mp3_file,
        "encoding": encoding,
        "elapsed_seconds": elapsed_seconds,
        "renderer_elapsed_seconds": renderer_elapsed_seconds,
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


def _finalize_render_artifacts(
    *,
    logger: logging.Logger,
    job_id: str,
    archive_dir: Path | None,
    archived_files: dict[str, Path | None],
    final_mp3_path: Path,
    final_wav_path: Path,
    timings: dict[str, float],
    renderer_timings: dict[str, Any],
) -> tuple[dict[str, object], dict[str, float], dict[str, object], dict[str, object] | None]:
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
    _log_service_event(logger, "artifact archive complete", job_id=job_id, artifact_archive=artifact_archive)
    return timing_summary, renderer_stage_seconds, record_audio_breakdown, artifact_archive


def _load_response_mp3_file(
    *,
    logger: logging.Logger,
    job_id: str,
    final_mp3_path: Path,
    timings: dict[str, float],
) -> dict[str, object]:
    stage_started = time.monotonic()
    _log_service_event(logger, "base64 mp3 start", job_id=job_id, mp3_path=str(final_mp3_path))
    mp3_file = _base64_mp3_payload(final_mp3_path)
    _log_service_event(
        logger,
        "base64 mp3 complete",
        job_id=job_id,
        filename=mp3_file.get("filename"),
        size_bytes=mp3_file.get("size_bytes"),
        base64_chars=len(str(mp3_file.get("base64", ""))),
    )
    record_timing(timings, "mp3_base64_seconds", stage_started)
    return mp3_file


def _finalize_single_render_files(
    *,
    logger: logging.Logger,
    job_id: str,
    config: ServiceConfig,
    result: RenderResult,
    output_basename: str,
    recorder_output_basename: str,
    timings: dict[str, float],
) -> tuple[Path, Path]:
    stage_started = time.monotonic()
    final_mp3_path = config.output_dir / f"{output_basename}.mp3"
    final_wav_path = config.output_dir / f"{output_basename}.wav"
    _log_service_event(
        logger,
        "output finalize start",
        job_id=job_id,
        source_mp3=str(result.mp3_path),
        source_wav=str(result.wav_path),
        final_mp3=str(final_mp3_path),
        final_wav=str(final_wav_path),
    )
    if recorder_output_basename != output_basename:
        result.mp3_path.replace(final_mp3_path)
        result.wav_path.replace(final_wav_path)
    else:
        final_mp3_path = result.mp3_path
        final_wav_path = result.wav_path
    record_timing(timings, "output_finalize_seconds", stage_started)
    _log_service_event(
        logger,
        "output finalize complete",
        job_id=job_id,
        mp3_path=str(final_mp3_path),
        wav_path=str(final_wav_path),
        mp3_bytes=final_mp3_path.stat().st_size if final_mp3_path.is_file() else None,
        wav_bytes=final_wav_path.stat().st_size if final_wav_path.is_file() else None,
    )
    return final_mp3_path, final_wav_path


def _run_single_renderer(
    *,
    logger: logging.Logger,
    job_id: str,
    effective_config: ServiceConfig,
    plugin: PluginProfile,
    style: StyleProfile | None,
    selected_style_name: str | None,
    render_midi_path: Path,
    recorder_output_basename: str,
    max_seconds: float | None,
    selected_state: Path | None,
    parameter_overrides: list[ParameterOverride],
    debug_enabled: bool,
    timings: dict[str, float],
) -> RenderResult:
    stage_started = time.monotonic()
    _log_service_event(
        logger,
        "renderer start",
        job_id=job_id,
        plugin_id=plugin.id,
        plugin_name=plugin.name,
        style_id=style.id if style else None,
        style_name=selected_style_name,
        midi_path=str(render_midi_path),
        output_basename=recorder_output_basename,
        max_seconds=max_seconds,
        parameter_count=len(parameter_overrides),
        plugin_state=str(selected_state) if selected_state else None,
    )
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
            debug=debug_enabled,
        )
    except RenderError as exc:
        logger.exception("render failed job_id=%s error=%s", job_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    record_timing(timings, "renderer_subprocess_seconds", stage_started)
    _log_service_event(
        logger,
        "renderer complete",
        job_id=job_id,
        plugin_id=plugin.id,
        style_id=style.id if style else None,
        wav_path=str(result.wav_path),
        mp3_path=str(result.mp3_path),
        elapsed_seconds=result.elapsed_seconds,
        timings={
            "total_seconds": result.timings.get("total_seconds"),
            "record_audio_seconds": result.timings.get("record_audio_seconds"),
            "ffmpeg_mp3_seconds": result.timings.get("ffmpeg_mp3_seconds"),
            "wav_bytes": result.timings.get("wav_bytes"),
            "mp3_bytes": result.timings.get("mp3_bytes"),
        },
    )
    return result


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
                "path_exists": plugin_path_exists(plugin.type, plugin.path),
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
    config = get_config()
    logger = get_logger(config)
    _log_service_event(
        logger,
        "start to process render request",
        async_mode=normalized_callback_url is not None,
        plugin_id=plugin_id,
        style_id=style_id,
        style_name=style_name,
        max_seconds=max_seconds,
        apply_midi_policy=apply_midi_policy,
        midi_source_channel=midi_source_channel,
        midi_target_channel=midi_target_channel,
        midi_filename=_upload_filename(midi),
        data_filename=_upload_filename(data),
        bundle_filename=_upload_filename(bundle),
        callbackurl=normalized_callback_url,
    )
    if normalized_callback_url is None:
        payload = await _render_midi_from_uploads(
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
        _log_service_event(
            logger,
            "return sync render response",
            job_id=payload.get("job_id"),
            plugin_id=payload.get("plugin_id"),
            style_id=payload.get("style_id"),
            mp3_filename=(payload.get("mp3_file") or {}).get("filename")
            if isinstance(payload.get("mp3_file"), dict)
            else None,
            elapsed_seconds=payload.get("elapsed_seconds"),
            artifact_archive=payload.get("artifact_archive"),
        )
        return payload

    job_id = uuid.uuid4().hex
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
        "http_code": 200,
        "job_id": job_id,
        "status": "accepted",
        "error": None,
        "callbackurl": normalized_callback_url,
    }
    status_payload = {
        **accepted_payload,
        "status_url": f"/mgsc_daw_service/v1/jobs/{job_id}/status",
        "accepted_at": timestamp_now(),
    }
    status_path = write_async_status(config.work_dir, job_id, status_payload)
    _log_service_event(
        logger,
        "return async accepted response",
        job_id=job_id,
        callbackurl=normalized_callback_url,
        status_url=status_payload["status_url"],
        status_path=str(status_path),
    )

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

    job_id = job_id_override or uuid.uuid4().hex
    job_dir = config.work_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    archive_dir = _artifact_archive_dir(config, job_id)

    stage_started = time.monotonic()
    prepared_input = await _prepare_render_input(
        logger=logger,
        job_id=job_id,
        job_dir=job_dir,
        archive_dir=archive_dir,
        midi=midi,
        data=data,
        bundle=bundle,
    )
    input_mode = prepared_input.input_mode
    midi_filename = prepared_input.midi_filename
    midi_path = prepared_input.midi_path
    original_midi_stem = prepared_input.original_midi_stem
    bundle_config = prepared_input.bundle_config
    bundle_conf_name = prepared_input.bundle_conf_name
    debug_enabled = prepared_input.debug_enabled
    archived_files = prepared_input.archived_files
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
    render_options["debug"] = debug_enabled
    _log_service_event(
        logger,
        "render conf resolved",
        job_id=job_id,
        plugin_id=plugin_id,
        style_id=style_id,
        style_name=style_name,
        max_seconds=max_seconds,
        apply_midi_policy=apply_midi_policy,
        midi_source_channel=midi_source_channel,
        midi_target_channel=midi_target_channel,
        render_options=render_options,
        debug=debug_enabled,
        conf_summary=_route_config_summary(bundle_config) if bundle_config else {},
    )

    midi_channel_analysis: dict[str, object] | None = None
    auto_route_info: dict[str, object] | None = None
    manual_render_routes = _build_manual_track_routes(config, bundle_config)
    if manual_render_routes and is_auto_style_request(style_id):
        raise HTTPException(status_code=400, detail="Use either conf.json tracks/vst/sf2 or style_id=auto, not both")

    if not manual_render_routes and is_auto_style_request(style_id):
        stage_started = time.monotonic()
        _log_service_event(logger, "auto route analysis start", job_id=job_id, midi_path=str(midi_path))
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
        _log_service_event(
            logger,
            "auto route analysis complete",
            job_id=job_id,
            style_id=style_id,
            selected_source_channel=selected_source_channel,
            route=auto_route_info,
        )
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

    if (
        not manual_render_routes
        and auto_route_info is None
        and midi_source_channel is None
        and style is not None
        and style.midi_policy.enabled
        and _plugin_category(plugin) == "kong_audio"
    ):
        stage_started = time.monotonic()
        _log_service_event(logger, "midi source auto selection start", job_id=job_id, midi_path=str(midi_path))
        try:
            midi_channel_analysis = analyze_midi_channels(midi_path)
        except MidiPolicyError as exc:
            logger.exception("render midi source analysis failed job_id=%s error=%s", job_id, exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        selected_source_channel = midi_channel_analysis.get("selected_source_channel")
        if isinstance(selected_source_channel, int):
            midi_source_channel = selected_source_channel
        record_timing(timings, "midi_channel_analysis_seconds", stage_started)
        _log_service_event(
            logger,
            "midi source auto selection complete",
            job_id=job_id,
            selected_source_channel=selected_source_channel,
            selection_reason=midi_channel_analysis.get("selection_reason"),
        )

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
        _log_service_event(
            logger,
            "manual track routes selected",
            job_id=job_id,
            route_count=len(manual_render_routes),
            routes=_manual_route_log_summary(manual_render_routes),
        )

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
        _log_service_event(
            logger,
            "multi route render start",
            job_id=job_id,
            route_kind=route_mix_kind,
            route_count=len(auto_render_routes),
            output_basename=output_basename,
            final_wav_path=str(final_wav_path),
            final_mp3_path=str(final_mp3_path),
        )

        def render_one_route(route_index: int, route: dict[str, object]) -> tuple[int, Path, dict[str, Any], dict[str, object], float]:
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
            _log_service_event(
                logger,
                "route midi policy start",
                job_id=job_id,
                route_index=route_index,
                route_count=len(auto_render_routes),
                route_kind=route_mix_kind,
                plugin_id=current_route_plugin.id,
                style_id=current_route_style.id if current_route_style else None,
                track_id=route_track_id,
                track_name=route_track_name,
                channel=route_channel,
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
            midi_policy_seconds = time.monotonic() - stage_started
            _log_service_event(
                logger,
                "route midi policy complete",
                job_id=job_id,
                route_index=route_index,
                output_path=str(route_midi_path),
                output_bytes=route_stats.get("output_bytes") if isinstance(route_stats, dict) else None,
                notes_kept=route_stats.get("notes_kept") if isinstance(route_stats, dict) else None,
                selected_mtrk_index=route_stats.get("selected_mtrk_index")
                if isinstance(route_stats, dict)
                else None,
            )

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

            _log_service_event(
                logger,
                "route renderer start",
                job_id=job_id,
                route_index=route_index,
                plugin_id=current_route_plugin.id,
                plugin_name=current_route_plugin.name,
                style_id=route_style_id,
                style_name=route_style_name,
                midi_path=str(route_midi_path),
                output_basename=route_output_basename,
                parameter_count=len(route_parameters),
                plugin_state=str(route_state) if route_state else None,
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
                debug=debug_enabled,
            )
            _log_service_event(
                logger,
                "route renderer complete",
                job_id=job_id,
                route_index=route_index,
                plugin_id=current_route_plugin.id,
                style_id=route_style_id,
                wav_path=str(route_result.wav_path),
                mp3_path=str(route_result.mp3_path),
                elapsed_seconds=route_result.elapsed_seconds,
                timings={
                    "total_seconds": route_result.timings.get("total_seconds"),
                    "record_audio_seconds": route_result.timings.get("record_audio_seconds"),
                    "ffmpeg_mp3_seconds": route_result.timings.get("ffmpeg_mp3_seconds"),
                    "wav_bytes": route_result.timings.get("wav_bytes"),
                    "mp3_bytes": route_result.timings.get("mp3_bytes"),
                },
            )
            route_detail = {
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
            return route_index, route_result.wav_path, route_result.timings, route_detail, midi_policy_seconds

        route_workers = _parallel_route_workers(len(auto_render_routes))
        _log_service_event(
            logger,
            "route render scheduling",
            job_id=job_id,
            route_kind=route_mix_kind,
            route_count=len(auto_render_routes),
            workers=route_workers,
            parallel=route_workers > 1,
        )
        try:
            route_results = _run_route_render_tasks(auto_render_routes, route_workers, render_one_route)
            for _, wav_path, renderer_timings, route_detail, midi_seconds in sorted(route_results, key=lambda item: item[0]):
                route_midi_policy_seconds += midi_seconds
                route_wav_paths.append(wav_path)
                route_result_timings.append(renderer_timings)
                route_details.append(route_detail)
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
            _log_service_event(
                logger,
                "mix wav start",
                job_id=job_id,
                input_count=len(route_wav_paths),
                output_path=str(final_wav_path),
            )
            mix_stats = _mix_wav_files(effective_config, route_wav_paths, final_wav_path)
            _log_service_event(logger, "mix wav complete", job_id=job_id, stats=mix_stats)
            _log_service_event(
                logger,
                "encode mp3 start",
                job_id=job_id,
                wav_path=str(final_wav_path),
                mp3_path=str(final_mp3_path),
            )
            encode_stats = _encode_mp3_file(effective_config, final_wav_path, final_mp3_path)
            _log_service_event(logger, "encode mp3 complete", job_id=job_id, stats=encode_stats)
        except (OSError, subprocess.CalledProcessError, RenderError) as exc:
            logger.exception("auto route output finalize failed job_id=%s error=%s", job_id, exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        record_timing(timings, "output_finalize_seconds", stage_started)

        mp3_file = _load_response_mp3_file(
            logger=logger,
            job_id=job_id,
            final_mp3_path=final_mp3_path,
            timings=timings,
        )
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
            "mp3_mode": effective_config.encoding.mp3_mode,
            "mp3_quality": effective_config.encoding.mp3_quality,
            "mp3_compression_level": effective_config.encoding.mp3_compression_level,
            "mp3_id3v2_version": effective_config.encoding.mp3_id3v2_version,
        }
        timing_summary, renderer_stage_seconds, record_audio_breakdown, artifact_archive = (
            _finalize_render_artifacts(
                logger=logger,
                job_id=job_id,
                archive_dir=archive_dir,
                archived_files=archived_files,
                final_mp3_path=final_mp3_path,
                final_wav_path=final_wav_path,
                timings=timings,
                renderer_timings=renderer_timings,
            )
        )
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
        _log_service_event(
            logger,
            "render payload ready",
            job_id=job_id,
            mode=route_mix_mode,
            route_count=len(auto_render_routes),
            mp3_filename=mp3_file.get("filename"),
            mp3_bytes=mp3_file.get("size_bytes"),
            wav_path=str(final_wav_path),
            elapsed_seconds=timings["request_total_seconds"],
            artifact_archive=artifact_archive,
        )
        payload = _build_render_payload(
            job_id=job_id,
            plugin_id="manual_track_mix" if manual_render_routes else "auto_mix",
            style_id="manual_track_mix" if manual_render_routes else "auto_mix",
            input_mode=input_mode,
            midi_filename=midi_filename,
            conf_filename=bundle_conf_name,
            parameters_applied=sum(int(route_detail["parameters_applied"]) for route_detail in route_details),
            render_options=render_options,
            midi_policy_applied=True,
            midi_policy=midi_policy_stats,
            auto_route=auto_route_response,
            final_mp3_path=final_mp3_path,
            final_wav_path=final_wav_path,
            output_basename=output_basename,
            mp3_file=mp3_file,
            encoding=encoding,
            elapsed_seconds=timings["request_total_seconds"],
            renderer_elapsed_seconds=_float_timing(timing_summary.get("renderer_total_seconds")),
            timings=timings,
            renderer_timings=renderer_timings,
            timing_summary=timing_summary,
            renderer_stage_seconds=renderer_stage_seconds,
            record_audio_breakdown=record_audio_breakdown,
            artifact_archive=artifact_archive,
        )
        return _public_render_response(payload, debug_enabled=debug_enabled)

    timings.setdefault("midi_channel_analysis_seconds", 0.0)

    if effective_midi_policy is not None:
        stage_started = time.monotonic()
        render_midi_path = job_dir / "input.policy.mid"
        _log_service_event(
            logger,
            "midi policy start",
            job_id=job_id,
            input_path=str(midi_path),
            output_path=str(render_midi_path),
            source_channel=effective_midi_policy.source_channel,
            target_channel=effective_midi_policy.target_channel,
            remove_program_changes=effective_midi_policy.remove_program_changes,
            remove_bank_select=effective_midi_policy.remove_bank_select,
        )
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
        _log_service_event(
            logger,
            "midi policy complete",
            job_id=job_id,
            output_path=str(render_midi_path),
            output_bytes=midi_policy_stats.get("output_bytes") if midi_policy_stats else None,
            notes_kept=midi_policy_stats.get("notes_kept") if midi_policy_stats else None,
            channel_events_kept=midi_policy_stats.get("channel_events_kept") if midi_policy_stats else None,
        )
    else:
        timings["midi_policy_seconds"] = 0.0

    result = _run_single_renderer(
        logger=logger,
        job_id=job_id,
        effective_config=effective_config,
        plugin=plugin,
        style=style,
        selected_style_name=selected_style_name,
        render_midi_path=render_midi_path,
        recorder_output_basename=recorder_output_basename,
        max_seconds=max_seconds,
        selected_state=selected_state,
        parameter_overrides=parameter_overrides,
        debug_enabled=debug_enabled,
        timings=timings,
    )

    final_mp3_path, final_wav_path = _finalize_single_render_files(
        logger=logger,
        job_id=job_id,
        config=config,
        result=result,
        output_basename=output_basename,
        recorder_output_basename=recorder_output_basename,
        timings=timings,
    )

    mp3_file = _load_response_mp3_file(
        logger=logger,
        job_id=job_id,
        final_mp3_path=final_mp3_path,
        timings=timings,
    )
    timings["request_total_seconds"] = round(time.monotonic() - request_started, 3)

    renderer_timings = result.timings
    timing_summary, renderer_stage_seconds, record_audio_breakdown, artifact_archive = (
        _finalize_render_artifacts(
            logger=logger,
            job_id=job_id,
            archive_dir=archive_dir,
            archived_files=archived_files,
            final_mp3_path=final_mp3_path,
            final_wav_path=final_wav_path,
            timings=timings,
            renderer_timings=renderer_timings,
        )
    )
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
    _log_service_event(
        logger,
        "render payload ready",
        job_id=job_id,
        mode="single",
        plugin_id=plugin.id,
        style_id=style.id if style else None,
        mp3_filename=mp3_file.get("filename"),
        mp3_bytes=mp3_file.get("size_bytes"),
        wav_path=str(final_wav_path),
        elapsed_seconds=timings["request_total_seconds"],
        artifact_archive=artifact_archive,
    )

    payload = _build_render_payload(
        job_id=job_id,
        plugin_id=plugin.id,
        style_id=style.id if style else None,
        input_mode=input_mode,
        midi_filename=midi_filename,
        conf_filename=bundle_conf_name,
        parameters_applied=len(parameter_overrides),
        render_options=render_options,
        midi_policy_applied=midi_policy_stats is not None,
        midi_policy=midi_policy_stats,
        auto_route=auto_route_info,
        final_mp3_path=final_mp3_path,
        final_wav_path=final_wav_path,
        output_basename=output_basename,
        mp3_file=mp3_file,
        encoding=result.encoding,
        elapsed_seconds=timings["request_total_seconds"],
        renderer_elapsed_seconds=round(result.elapsed_seconds, 3),
        timings=timings,
        renderer_timings=renderer_timings,
        timing_summary=timing_summary,
        renderer_stage_seconds=renderer_stage_seconds,
        record_audio_breakdown=record_audio_breakdown,
        artifact_archive=artifact_archive,
    )
    return _public_render_response(payload, debug_enabled=debug_enabled)


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
