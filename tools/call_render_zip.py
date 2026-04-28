from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any


def build_multipart(field_name: str, file_path: Path) -> tuple[bytes, str]:
    boundary = f"----carla-render-{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        (
            f'Content-Disposition: form-data; name="{field_name}"; '
            f'filename="{file_path.name}"\r\n'
        ).encode("utf-8")
    )
    body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
    body.extend(file_path.read_bytes())
    body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def post_bundle(url: str, field_name: str, bundle_path: Path, timeout: float) -> dict[str, Any]:
    body, content_type = build_multipart(field_name, bundle_path)
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    decoded = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise RuntimeError("Render API returned non-object JSON")
    return decoded


def seconds(value: object) -> str:
    if isinstance(value, bool) or value is None:
        return "-"
    try:
        return f"{float(value):.3f}s"
    except (TypeError, ValueError):
        return "-"


def render_one(index: int, total: int, args: argparse.Namespace, bundle_path: Path) -> bool:
    started = time.monotonic()
    try:
        result = post_bundle(args.url, args.field_name, bundle_path, args.timeout)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"[{index}/{total}] FAIL {bundle_path} http={exc.code} elapsed={seconds(time.monotonic() - started)} detail={detail}")
        return False
    except Exception as exc:
        print(f"[{index}/{total}] FAIL {bundle_path} elapsed={seconds(time.monotonic() - started)} error={exc}")
        return False

    client_elapsed = round(time.monotonic() - started, 3)
    timing_summary = result.get("timing_summary")
    if not isinstance(timing_summary, dict):
        timing_summary = {}
    renderer_timings = result.get("renderer_timings")
    if not isinstance(renderer_timings, dict):
        renderer_timings = {}
    renderer_stage_seconds = result.get("renderer_stage_seconds")
    if not isinstance(renderer_stage_seconds, dict):
        renderer_stage_seconds = {}
    top_stage = next(iter(renderer_stage_seconds.items()), None)

    print(
        " ".join(
            [
                f"[{index}/{total}] OK",
                f"zip={bundle_path.name}",
                f"job_id={result.get('job_id')}",
                f"style_id={result.get('style_id')}",
                f"client_elapsed={seconds(client_elapsed)}",
                f"mp3_generation={seconds(timing_summary.get('mp3_generation_seconds'))}",
                f"renderer={seconds(timing_summary.get('renderer_total_seconds'))}",
                f"top_stage={top_stage[0] if top_stage else '-'}:{seconds(top_stage[1] if top_stage else None)}",
                f"record_audio={seconds(timing_summary.get('record_audio_seconds') or renderer_timings.get('record_audio_seconds'))}",
                f"ffmpeg_mp3={seconds(timing_summary.get('ffmpeg_mp3_seconds') or renderer_timings.get('ffmpeg_mp3_seconds'))}",
                f"mp3={result.get('mp3_path')}",
            ]
        )
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return True


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Call the Carla render API with one or more zip bundles and print per-MP3 timing."
    )
    parser.add_argument("bundles", nargs="+", help="Zip bundle path(s). Each zip must contain one MIDI and conf.json.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/v1/render", help="Render API URL.")
    parser.add_argument("--field-name", default="data", choices=("data", "bundle"), help="Multipart field name for the zip.")
    parser.add_argument("--timeout", type=float, default=3600.0, help="HTTP timeout in seconds.")
    parser.add_argument("--json", action="store_true", help="Print the full JSON response after the timing line.")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    bundle_paths = [Path(value).expanduser().resolve() for value in args.bundles]
    missing = [path for path in bundle_paths if not path.is_file()]
    if missing:
        for path in missing:
            print(f"Missing zip bundle: {path}", file=sys.stderr)
        return 2

    successes = 0
    for index, bundle_path in enumerate(bundle_paths, start=1):
        if render_one(index, len(bundle_paths), args, bundle_path):
            successes += 1

    print(f"summary total={len(bundle_paths)} success={successes} failed={len(bundle_paths) - successes}")
    return 0 if successes == len(bundle_paths) else 1


if __name__ == "__main__":
    raise SystemExit(main())
