from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .config import ConfigError, ServiceConfig, load_config
from .renderer import RenderError, run_render


app = FastAPI(title="Carla Music Service", version="0.1.0")
_CONFIG: ServiceConfig | None = None


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


@app.post("/v1/render")
async def render_midi(
    plugin_id: str = Form(...),
    midi: UploadFile = File(...),
    style_name: str | None = Form(None),
    max_seconds: float | None = Form(None),
) -> dict[str, object]:
    config = get_config()
    plugin = config.get_plugin(plugin_id)
    if plugin is None:
        raise HTTPException(status_code=404, detail=f"Unknown plugin: {plugin_id}")
    if not plugin.enabled:
        raise HTTPException(status_code=400, detail=f"Plugin is disabled: {plugin_id}")

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

    try:
        result = run_render(
            config=config,
            plugin=plugin,
            midi_path=midi_path,
            output_dir=job_dir,
            style_name=style_name,
            max_seconds=max_seconds,
        )
    except RenderError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "job_id": job_id,
        "plugin_id": plugin.id,
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

