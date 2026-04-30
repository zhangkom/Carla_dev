# /**
# * File name: mgsc_daw_client.py
# * Brief: MGSC DAW 服务调用客户端
# * Function:
# *     上传 ZIP 渲染任务并下载 FastAPI 服务生成的 MP3 文件
# * Author: 咪咕数创工程架构组
# *     MGSC AI Software Architecture group
# * Version: V2.5.10
# * Date: 2026/04/30
# */
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import uuid
from pathlib import Path
from urllib import error, request


DEFAULT_SERVER = "http://127.0.0.1:8000"
OPENER = request.build_opener(request.ProxyHandler({}))


def encode_multipart(
    fields: dict[str, str],
    file_field: str,
    file_path: Path,
) -> tuple[bytes, str]:
    boundary = "----mgsc-daw-" + uuid.uuid4().hex
    chunks: list[bytes] = []

    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )

    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{file_path.name}"\r\n'
            ).encode(),
            f"Content-Type: {mime_type}\r\n\r\n".encode(),
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def http_json(url: str, body: bytes, content_type: str, timeout: float) -> dict[str, object]:
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": content_type},
        method="POST",
    )
    try:
        with OPENER.open(req, timeout=timeout) as response:
            raw = response.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    decoded = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise RuntimeError("service returned a non-object JSON payload")
    return decoded


def download_file(server: str, path: str, output_path: Path, timeout: float) -> None:
    url = server.rstrip("/") + path
    try:
        with OPENER.open(url, timeout=timeout) as response:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"download failed HTTP {exc.code}: {detail}") from exc


def output_path_for(zip_path: Path, payload: dict[str, object], requested: str | None) -> Path:
    if requested:
        return Path(requested)
    basename = str(payload.get("output_basename") or zip_path.stem)
    return zip_path.with_name(f"{basename}.mp3")


def render(args: argparse.Namespace) -> dict[str, object]:
    zip_path = Path(args.zip).expanduser().resolve()
    if not zip_path.is_file():
        raise FileNotFoundError(f"zip file not found: {zip_path}")

    fields: dict[str, str] = {}
    if args.style_id:
        fields["style_id"] = args.style_id
    if args.max_seconds is not None:
        fields["max_seconds"] = str(args.max_seconds)

    body, content_type = encode_multipart(fields, args.field, zip_path)
    server = args.server.rstrip("/")
    payload = http_json(f"{server}/v1/render", body, content_type, args.timeout)

    downloads = payload.get("download")
    if not isinstance(downloads, dict) or not downloads.get("mp3"):
        raise RuntimeError("service response did not include download.mp3")

    output_path = output_path_for(zip_path, payload, args.output).resolve()
    download_file(server, str(downloads["mp3"]), output_path, args.timeout)
    payload["saved_path"] = str(output_path)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Upload a DAW zip bundle to mgsc_daw_service and save the rendered MP3."
    )
    parser.add_argument("--server", default=os.environ.get("DAW_SERVER", DEFAULT_SERVER))
    parser.add_argument("--zip", required=True, help="Input zip containing one MIDI file and conf.json.")
    parser.add_argument("--output", help="Local MP3 output path. Defaults to the service output basename.")
    parser.add_argument("--field", default="data", choices=("data", "bundle"))
    parser.add_argument("--style-id", help="Optional debug override; production zips should use conf.json.")
    parser.add_argument("--max-seconds", type=float, help="Optional debug render cap.")
    parser.add_argument("--timeout", type=float, default=3600.0)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    payload = render(args)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
