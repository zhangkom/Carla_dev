from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

from .config import ServiceConfig
from .render_outputs import sanitize_filename_component


def artifact_archive_dir(config: ServiceConfig, job_id: str) -> Path | None:
    root = artifact_archive_root(config)
    if root is None:
        return None
    return root / datetime.now().strftime("%Y%m%d") / job_id


def artifact_archive_root(config: ServiceConfig) -> Path | None:
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


def artifact_safe_name(prefix: str, filename: str | None, fallback_suffix: str) -> str:
    candidate = Path(filename or "").name
    suffix = Path(candidate).suffix or fallback_suffix
    stem = sanitize_filename_component(Path(candidate).stem) or "upload"
    return f"{prefix}_{stem}{suffix}"


def archive_bytes(
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


def archive_file(
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


def archive_response(archive_dir: Path | None, files: dict[str, Path | None]) -> dict[str, object] | None:
    if archive_dir is None:
        return None
    payload: dict[str, object] = {"dir": str(archive_dir)}
    archived_files = {key: str(value) for key, value in files.items() if value is not None}
    if archived_files:
        payload["files"] = archived_files
    return payload
