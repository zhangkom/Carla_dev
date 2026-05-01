# /**
# * File name: run_music_service_regression.py
# * Brief: MGSC DAW 服务回归验证脚本
# * Function:
# *     检查基础查询接口，并可选执行同步/异步 ZIP 渲染与异步状态查询
# * Author: 咪咕数创工程架构组
# *     MGSC AI Software Architecture group
# * Version: V2.5.10
# * Date: 2026/05/01
# */

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib import error


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mgsc_daw_client import DEFAULT_SERVER, OPENER, printable_payload, render  # noqa: E402


def get_json(server: str, path: str, timeout: float) -> dict[str, object]:
    url = server.rstrip("/") + path
    try:
        with OPENER.open(url, timeout=timeout) as response:
            raw = response.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {path} failed HTTP {exc.code}: {detail}") from exc
    decoded = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise RuntimeError(f"GET {path} returned a non-object JSON payload")
    return decoded


def check_query_endpoints(
    server: str,
    timeout: float,
    *,
    skip_instrument_mappings: bool,
) -> dict[str, object]:
    checks: dict[str, object] = {}
    endpoints = [
        ("health", "/health"),
        ("catalog", "/v1/catalog"),
        ("styles", "/v1/styles"),
        ("instrument_mappings", "/v1/instrument-mappings"),
    ]
    if skip_instrument_mappings:
        endpoints = [
            (name, path)
            for name, path in endpoints
            if name != "instrument_mappings"
        ]

    for name, path in endpoints:
        payload = get_json(server, path, timeout)
        checks[name] = {
            "ok": True,
            "path": path,
            "keys": sorted(payload.keys()),
        }
    return checks


def render_args(args: argparse.Namespace, *, async_callback: bool, output_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        server=args.server,
        zip=str(args.zip),
        output=str(output_path),
        field=args.field,
        style_id=args.style_id,
        max_seconds=args.max_seconds,
        timeout=args.render_timeout,
        callback_url=None,
        async_callback=async_callback,
        async_timeout=args.async_timeout,
        callback_bind_host=args.callback_bind_host,
        callback_public_host=args.callback_public_host,
        callback_port=args.callback_port,
        callback_path=args.callback_path,
    )


def run_sync_render(args: argparse.Namespace, output_dir: Path) -> dict[str, object]:
    payload = render(render_args(args, async_callback=False, output_path=output_dir / "sync.mp3"))
    return printable_payload(payload)


def run_async_render(args: argparse.Namespace, output_dir: Path) -> dict[str, object]:
    payload = render(render_args(args, async_callback=True, output_path=output_dir / "async.mp3"))
    printable = printable_payload(payload)
    accepted = payload.get("accepted_response")
    if isinstance(accepted, dict):
        status_url = accepted.get("status_url")
        if isinstance(status_url, str) and status_url:
            printable["status_check"] = get_json(args.server, status_url, args.timeout)
    return printable


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run MGSC DAW service regression checks.")
    parser.add_argument("--server", default=os.environ.get("DAW_SERVER", DEFAULT_SERVER))
    parser.add_argument("--timeout", type=float, default=30.0, help="Seconds for query/status checks.")
    parser.add_argument("--zip", type=Path, help="Optional render bundle zip for sync/async render checks.")
    parser.add_argument("--mode", choices=("query", "sync", "async", "both"), default="query")
    parser.add_argument(
        "--skip-instrument-mappings",
        action="store_true",
        help="Skip /v1/instrument-mappings for older containers that do not expose it.",
    )
    parser.add_argument("--output-dir", type=Path, help="Directory for rendered regression MP3 files.")
    parser.add_argument("--field", default="data", choices=("data", "bundle"))
    parser.add_argument("--style-id", help="Optional debug style override.")
    parser.add_argument("--max-seconds", type=float, help="Optional render cap for quick smoke tests.")
    parser.add_argument("--render-timeout", type=float, default=3600.0)
    parser.add_argument("--async-timeout", type=float, default=3600.0)
    parser.add_argument("--callback-bind-host", default="0.0.0.0")
    parser.add_argument("--callback-public-host", default=os.environ.get("DAW_CALLBACK_PUBLIC_HOST"))
    parser.add_argument("--callback-port", type=int, default=0)
    parser.add_argument("--callback-path", default="/callback")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.mode != "query" and args.zip is None:
        parser.error("--zip is required when --mode is sync, async, or both")
    if args.zip is not None:
        args.zip = args.zip.expanduser().resolve()
        if not args.zip.is_file():
            raise FileNotFoundError(f"zip file not found: {args.zip}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = (args.output_dir or ROOT / "output" / f"regression_{timestamp}").expanduser().resolve()
    report: dict[str, object] = {
        "server": args.server,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "query_checks": check_query_endpoints(
            args.server,
            args.timeout,
            skip_instrument_mappings=args.skip_instrument_mappings,
        ),
    }

    if args.mode in {"sync", "both"}:
        output_dir.mkdir(parents=True, exist_ok=True)
        report["sync_render"] = run_sync_render(args, output_dir)
    if args.mode in {"async", "both"}:
        output_dir.mkdir(parents=True, exist_ok=True)
        report["async_render"] = run_async_render(args, output_dir)

    report["completed_at"] = datetime.now().isoformat(timespec="seconds")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
