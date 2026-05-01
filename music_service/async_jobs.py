# /**
# * File name: async_jobs.py
# * Brief: MGSC DAW 异步任务管理模块
# * Function:
# *     管理异步渲染线程、任务状态落盘以及 callback_url 回调投递
# * Author: 咪咕数创工程架构组
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


def normalize_callback_url(
    callback_url: str | None,
    callbackurl: str | None,
) -> str | None:
    normalized = [value.strip() for value in (callback_url, callbackurl) if value and value.strip()]
    if not normalized:
        return None
    if len(set(normalized)) > 1:
        raise ValueError("callback_url and callbackurl must match when both are set")

    callback = normalized[0]
    parsed = url_parse.urlparse(callback)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("callback_url must be an absolute http(s) URL")
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
            "job_id": job_id,
            "status": "failed",
            "async": True,
            "failed_at": timestamp_now(),
            "error": {
                "status_code": status_code,
                "detail": detail,
            },
        }
    return {
        "job_id": job_id,
        "status": "failed",
        "async": True,
        "failed_at": timestamp_now(),
        "error": {
            "type": type(exc).__name__,
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
            with opener.open(request, timeout=timeout) as response:
                response.read()
                status_code = getattr(response, "status", response.getcode())
            logger.info(
                "async render callback delivered job_id=%s url=%s attempt=%s",
                payload.get("job_id"),
                callback_url,
                attempt,
            )
            return {
                "delivered": True,
                "attempts": attempt,
                "http_status": status_code,
                "callback_url": callback_url,
                "delivered_at": timestamp_now(),
            }
        except (OSError, url_error.URLError, url_error.HTTPError) as exc:
            last_error = exc
            logger.warning(
                "async render callback failed job_id=%s url=%s attempt=%s/%s error=%s",
                payload.get("job_id"),
                callback_url,
                attempt,
                retries,
                exc,
            )
            if attempt < retries:
                time.sleep(min(2.0 * attempt, 10.0))

    logger.error(
        "async render callback abandoned job_id=%s url=%s error=%s",
        payload.get("job_id"),
        callback_url,
        last_error,
    )
    delivery: dict[str, object] = {
        "delivered": False,
        "attempts": retries,
        "callback_url": callback_url,
        "abandoned_at": timestamp_now(),
    }
    if last_error is not None:
        delivery["last_error"] = _callback_attempt_error(last_error)
    return delivery


def run_async_render_and_callback(
    *,
    callback_url: str,
    job_id: str,
    render_kwargs: dict[str, object],
    render_callable: AsyncRenderCallable,
    work_dir: Path,
    logger: logging.Logger,
) -> None:
    write_async_status(
        work_dir,
        job_id,
        {
            "job_id": job_id,
            "status": "running",
            "async": True,
            "callback_url": callback_url,
            "started_at": timestamp_now(),
        },
    )
    try:
        payload = asyncio.run(
            render_callable(
                **render_kwargs,
                job_id_override=job_id,
            )
        )
        payload["status"] = "completed"
        payload["async"] = True
        payload["completed_at"] = timestamp_now()
    except Exception as exc:
        logger.exception("async render failed job_id=%s callback_url=%s error=%s", job_id, callback_url, exc)
        payload = callback_error_payload(job_id, exc)

    status_payload = {
        **payload,
        "callback_url": callback_url,
        "callback_status": "pending",
    }
    write_async_status(work_dir, job_id, status_payload)

    delivery = post_callback_payload(callback_url, payload, logger)
    payload["callback_delivery"] = delivery
    payload["callback_url"] = callback_url
    write_async_status(work_dir, job_id, payload)
