from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .config import ConfigError, ParameterOverride, PluginProfile, ServiceConfig, StyleProfile, load_config
from .renderer import RenderError, run_render


app = FastAPI(title="Carla Music Service", version="0.1.0")
_CONFIG: ServiceConfig | None = None


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


def get_config() -> ServiceConfig:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = load_config()
        _CONFIG.work_dir.mkdir(parents=True, exist_ok=True)
        _CONFIG.output_dir.mkdir(parents=True, exist_ok=True)
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


@app.post("/v1/render")
async def render_midi(
    plugin_id: str | None = Form(None),
    style_id: str | None = Form(None),
    midi: UploadFile = File(...),
    style_name: str | None = Form(None),
    max_seconds: float | None = Form(None),
    parameters_json: str | None = Form(None),
) -> dict[str, object]:
    config = get_config()
    plugin, style = _resolve_plugin_and_style(config, plugin_id, style_id)
    if not plugin.enabled:
        raise HTTPException(status_code=400, detail=f"Plugin is disabled: {plugin.id}")

    suffix = Path(midi.filename or "input.mid").suffix.lower()
    if suffix not in {".mid", ".midi"}:
        raise HTTPException(status_code=400, detail="Upload must be a .mid or .midi file")

    job_id = uuid.uuid4().hex
    job_dir = config.work_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    midi_path = job_dir / f"input{suffix}"

    with midi_path.open("wb") as handle:
        while True:
            chunk = await midi.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)

    parameter_overrides = list(style.parameters if style else ())
    parameter_overrides.extend(_parse_request_parameters(parameters_json))
    selected_state = style.state if style and style.state else plugin.state
    selected_style_name = style_name or (style.name if style else None)

    try:
        result = run_render(
            config=config,
            plugin=plugin,
            midi_path=midi_path,
            output_dir=job_dir,
            style_name=selected_style_name,
            max_seconds=max_seconds,
            plugin_state=selected_state,
            parameter_overrides=parameter_overrides,
        )
    except RenderError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "job_id": job_id,
        "plugin_id": plugin.id,
        "style_id": style.id if style else None,
        "parameters_applied": len(parameter_overrides),
        "mp3_path": str(result.mp3_path),
        "wav_path": str(result.wav_path),
        "elapsed_seconds": round(result.elapsed_seconds, 3),
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
        raise HTTPException(status_code=404, detail="File not found")

    media_type = "audio/mpeg" if file_path.suffix.lower() == ".mp3" else "audio/wav"
    return FileResponse(file_path, media_type=media_type, filename=file_path.name)
