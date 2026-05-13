# /**
# * File name: async_jobs.py
# * Brief: MGSC DAW 异步任务管理模块
# * Function:
# *     管理异步渲染线程、任务状态落盘以及 callbackurl 回调投递
# * Author: 软件工程架构组
# *     MGSC AI Software Architecture group
# * Version: V2.5.10
# * Date: 2026/05/01
# */

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Awaitable, Callable
from urllib import error as url_error
from urllib import parse as url_parse
from urllib import request as url_request


_ASYNC_EXECUTOR: ThreadPoolExecutor | None = None
_ASYNC_EXECUTOR_LOCK = Lock()
_STATUS_DIR_NAME = "_async_status"


AsyncRenderCallable = Callable[..., Awaitable[dict[str, object]]]


def timestamp_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _log_async_event(
    logger: logging.Logger,
    message: str,
    *,
    level: int = logging.INFO,
    **fields: object,
) -> None:
    logger.log(level, "%s %s", message, json.dumps(fields, ensure_ascii=False, sort_keys=True, default=str))


def _upload_summary(value: object) -> object:
    filename = getattr(value, "filename", None)
    if filename:
        return filename
    return None


def _render_kwargs_summary(render_kwargs: dict[str, object]) -> dict[str, object]:
    keys = (
        "plugin_id",
        "style_id",
        "style_name",
        "max_seconds",
        "apply_midi_policy",
        "midi_source_channel",
        "midi_target_channel",
    )
    summary = {key: render_kwargs.get(key) for key in keys if key in render_kwargs}
    summary["midi_upload"] = _upload_summary(render_kwargs.get("midi"))
    summary["data_upload"] = _upload_summary(render_kwargs.get("data"))
    summary["bundle_upload"] = _upload_summary(render_kwargs.get("bundle"))
    return summary


def _payload_log_summary(payload: dict[str, object]) -> dict[str, object]:
    summary: dict[str, object] = {
        "job_id": payload.get("job_id"),
        "status": payload.get("status"),
        "async": payload.get("async"),
        "plugin_id": payload.get("plugin_id"),
        "style_id": payload.get("style_id"),
        "style_name": payload.get("style_name"),
        "mode": payload.get("mode"),
        "elapsed_seconds": payload.get("elapsed_seconds"),
    }
    mp3_file = payload.get("mp3_file")
    if isinstance(mp3_file, dict):
        summary["mp3_file"] = {
            "filename": mp3_file.get("filename"),
            "size_bytes": mp3_file.get("size_bytes"),
            "base64_chars": len(mp3_file.get("base64", "")) if isinstance(mp3_file.get("base64"), str) else None,
        }
    error = payload.get("error")
    if isinstance(error, dict):
        summary["error"] = error
    auto_route = payload.get("auto_route")
    if isinstance(auto_route, dict):
        routes = auto_route.get("routes")
        summary["auto_route"] = {
            "mode": auto_route.get("mode"),
            "route_count": len(routes) if isinstance(routes, list) else auto_route.get("route_count"),
        }
    return summary


def get_async_executor() -> ThreadPoolExecutor:
    global _ASYNC_EXECUTOR
    with _ASYNC_EXECUTOR_LOCK:
        if _ASYNC_EXECUTOR is None:
            raw_workers = os.environ.get("MUSIC_SERVICE_ASYNC_WORKERS", "1")
            try:
                max_workers = max(1, int(raw_workers))
            except ValueError:
                max_workers = 1
            _ASYNC_EXECUTOR = ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix="music-render-callback",
            )
        return _ASYNC_EXECUTOR


def normalize_callback_url(callbackurl: str | None) -> str | None:
    callback = callbackurl.strip() if callbackurl and callbackurl.strip() else None
    if callback is None:
        return None
    parsed = url_parse.urlparse(callback)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("callbackurl must be an absolute http(s) URL")
    return callback


def async_status_path(work_dir: Path, job_id: str) -> Path:
    return work_dir / _STATUS_DIR_NAME / f"{job_id}.json"


def _redact_status_payload(payload: dict[str, object]) -> dict[str, object]:
    redacted = copy.deepcopy(payload)
    mp3_file = redacted.get("mp3_file")
    if isinstance(mp3_file, dict):
        encoded = mp3_file.get("base64")
        if isinstance(encoded, str):
            mp3_file["base64"] = f"<omitted {len(encoded)} base64 chars>"
    return redacted


def write_async_status(work_dir: Path, job_id: str, payload: dict[str, object]) -> Path:
    status_path = async_status_path(work_dir, job_id)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_payload = _redact_status_payload(payload)
    status_payload["updated_at"] = timestamp_now()
    tmp_path = status_path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(status_payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(status_path)
    return status_path


def read_async_status(work_dir: Path, job_id: str) -> dict[str, object] | None:
    status_path = async_status_path(work_dir, job_id)
    try:
        decoded = json.loads(status_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        return {
            "job_id": job_id,
            "status": "unknown",
            "async": True,
            "error": {
                "type": "StatusReadError",
                "detail": f"Could not read async status file: {status_path}",
            },
        }
    if isinstance(decoded, dict):
        return decoded
    return {
        "job_id": job_id,
        "status": "unknown",
        "async": True,
        "error": {
            "type": "StatusFormatError",
            "detail": f"Async status file is not a JSON object: {status_path}",
        },
    }


def callback_error_payload(job_id: str, exc: BaseException) -> dict[str, object]:
    status_code = getattr(exc, "status_code", None)
    detail = getattr(exc, "detail", None)
    if isinstance(status_code, int):
        return {
            "http_code": status_code,
            "job_id": job_id,
            "status": "failed",
            "async": True,
            "failed_at": timestamp_now(),
            "error": {
                "code": f"HTTP_{status_code}",
                "message": str(detail),
                "detail": detail,
            },
        }
    return {
        "http_code": 500,
        "job_id": job_id,
        "status": "failed",
        "async": True,
        "failed_at": timestamp_now(),
        "error": {
            "code": type(exc).__name__,
            "message": str(exc),
            "detail": str(exc),
        },
    }


def _callback_attempt_error(exc: BaseException) -> dict[str, object]:
    detail: dict[str, object] = {
        "type": type(exc).__name__,
        "detail": str(exc),
    }
    if isinstance(exc, url_error.HTTPError):
        detail["status_code"] = exc.code
    return detail


def post_callback_payload(
    callback_url: str,
    payload: dict[str, object],
    logger: logging.Logger,
) -> dict[str, object]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        timeout = max(1.0, float(os.environ.get("MUSIC_SERVICE_CALLBACK_TIMEOUT", "30")))
    except ValueError:
        timeout = 30.0
    try:
        retries = max(1, int(os.environ.get("MUSIC_SERVICE_CALLBACK_RETRIES", "3")))
    except ValueError:
        retries = 3
    opener = url_request.build_opener(url_request.ProxyHandler({}))
    _log_async_event(
        logger,
        "async callback payload prepared",
        job_id=payload.get("job_id"),
        callbackurl=callback_url,
        body_bytes=len(body),
        timeout_seconds=timeout,
        retries=retries,
        payload=_payload_log_summary(payload),
    )

    last_error: BaseException | None = None
    for attempt in range(1, retries + 1):
        request = url_request.Request(
            callback_url,
            data=body,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Content-Length": str(len(body)),
            },
            method="POST",
        )
        try:
            _log_async_event(
                logger,
                "async callback post start",
                job_id=payload.get("job_id"),
                callbackurl=callback_url,
                attempt=attempt,
                retries=retries,
                body_bytes=len(body),
                timeout_seconds=timeout,
            )
            with opener.open(request, timeout=timeout) as response:
                response.read()
                status_code = getattr(response, "status", response.getcode())
            _log_async_event(
                logger,
                "async callback post complete",
                job_id=payload.get("job_id"),
                callbackurl=callback_url,
                attempt=attempt,
                http_status=status_code,
            )
            return {
                "delivered": True,
                "attempts": attempt,
                "http_status": status_code,
                "callbackurl": callback_url,
                "delivered_at": timestamp_now(),
            }
        except (OSError, url_error.URLError, url_error.HTTPError) as exc:
            last_error = exc
            _log_async_event(
                logger,
                "async callback post failed",
                level=logging.WARNING,
                job_id=payload.get("job_id"),
                callbackurl=callback_url,
                attempt=attempt,
                retries=retries,
                error=_callback_attempt_error(exc),
            )
            if attempt < retries:
                time.sleep(min(2.0 * attempt, 10.0))

    _log_async_event(
        logger,
        "async callback post abandoned",
        level=logging.ERROR,
        job_id=payload.get("job_id"),
        callbackurl=callback_url,
        retries=retries,
        error=_callback_attempt_error(last_error) if last_error is not None else None,
    )
    delivery: dict[str, object] = {
        "delivered": False,
        "attempts": retries,
        "callbackurl": callback_url,
        "abandoned_at": timestamp_now(),
    }
    if last_error is not None:
        delivery["last_error"] = _callback_attempt_error(last_error)
    return delivery


def run_async_render_and_callback(
    *,
    callbackurl: str,
    job_id: str,
    render_kwargs: dict[str, object],
    render_callable: AsyncRenderCallable,
    work_dir: Path,
    logger: logging.Logger,
) -> None:
    _log_async_event(
        logger,
        "async worker start",
        job_id=job_id,
        callbackurl=callbackurl,
        render_request=_render_kwargs_summary(render_kwargs),
    )
    status_path = write_async_status(
        work_dir,
        job_id,
        {
            "job_id": job_id,
            "status": "running",
            "async": True,
            "callbackurl": callbackurl,
            "started_at": timestamp_now(),
        },
    )
    _log_async_event(logger, "async status written", job_id=job_id, status="running", status_path=str(status_path))
    try:
        _log_async_event(logger, "async render callable start", job_id=job_id)
        payload = asyncio.run(
            render_callable(
                **render_kwargs,
                job_id_override=job_id,
            )
        )
        completed_at = timestamp_now()
        debug_enabled = payload.get("debug") is True
        callback_payload = dict(payload)
        if debug_enabled:
            callback_payload["status"] = "completed"
            callback_payload["async"] = True
            callback_payload["completed_at"] = completed_at
        status_payload = {
            **payload,
            "status": "completed",
            "async": True,
            "completed_at": completed_at,
        }
        _log_async_event(
            logger,
            "async render callable complete",
            job_id=job_id,
            payload=_payload_log_summary(status_payload),
        )
    except Exception as exc:
        logger.exception("async render failed job_id=%s callbackurl=%s error=%s", job_id, callbackurl, exc)
        callback_payload = callback_error_payload(job_id, exc)
        status_payload = dict(callback_payload)
        _log_async_event(
            logger,
            "async render callable failed",
            level=logging.ERROR,
            job_id=job_id,
            error={"type": type(exc).__name__, "detail": str(exc)},
        )

    pending_status_payload = {
        **status_payload,
        "callbackurl": callbackurl,
        "callback_status": "pending",
    }
    status_path = write_async_status(work_dir, job_id, pending_status_payload)
    _log_async_event(
        logger,
        "async status written",
        job_id=job_id,
        status=status_payload.get("status"),
        callback_status="pending",
        status_path=str(status_path),
        payload=_payload_log_summary(status_payload),
    )

    _log_async_event(logger, "async callback delivery start", job_id=job_id, callbackurl=callbackurl)
    delivery = post_callback_payload(callbackurl, callback_payload, logger)
    final_status_payload = {
        **status_payload,
        "callback_delivery": delivery,
        "callbackurl": callbackurl,
    }
    status_path = write_async_status(work_dir, job_id, final_status_payload)
    _log_async_event(
        logger,
        "async callback delivery complete",
        job_id=job_id,
        callbackurl=callbackurl,
        delivery=delivery,
    )
    _log_async_event(
        logger,
        "async status written",
        job_id=job_id,
        status=status_payload.get("status"),
        callback_delivery=delivery,
        status_path=str(status_path),
    )
