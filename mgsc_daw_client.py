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
import argparse
import base64
import binascii
import http.server
import json
import mimetypes
import os
import sys
import threading
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Type
from urllib import error, request


DEFAULT_SERVER = "http://127.0.0.1:8000"
OPENER = request.build_opener(request.ProxyHandler({}))


class CallbackState:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.payload: Optional[Dict[str, object]] = None
        self.error: Optional[str] = None


def make_callback_handler(state: CallbackState, callback_path: str) -> Type[http.server.BaseHTTPRequestHandler]:
    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path.split("?", 1)[0] != callback_path:
                self.send_error(404, "callback path not found")
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            raw = self.rfile.read(length)
            try:
                decoded = json.loads(raw.decode("utf-8"))
                if not isinstance(decoded, dict):
                    raise ValueError("callback payload is not a JSON object")
                state.payload = decoded
                state.error = None
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
            except Exception as exc:
                state.error = str(exc)
                self.send_error(400, state.error)
            finally:
                state.event.set()

        def log_message(self, format: str, *args: object) -> None:
            return

    return CallbackHandler


def start_callback_server(args: argparse.Namespace) -> Tuple[http.server.ThreadingHTTPServer, CallbackState, str]:
    callback_path = args.callback_path
    if not callback_path.startswith("/"):
        callback_path = "/" + callback_path
    if callback_path == "/callback":
        callback_path = f"/callback/{uuid.uuid4().hex}"

    state = CallbackState()
    handler = make_callback_handler(state, callback_path)
    server = http.server.ThreadingHTTPServer((args.callback_bind_host, args.callback_port), handler)
    thread = threading.Thread(target=server.serve_forever, name="mgsc-daw-callback", daemon=True)
    thread.start()

    actual_port = int(server.server_address[1])
    public_host = args.callback_public_host or args.callback_bind_host
    if public_host in {"0.0.0.0", "::"}:
        public_host = "127.0.0.1"
    callback_url = f"http://{public_host}:{actual_port}{callback_path}"
    return server, state, callback_url


def encode_multipart(
    fields: Dict[str, str],
    file_field: str,
    file_path: Path,
) -> Tuple[bytes, str]:
    boundary = "----mgsc-daw-" + uuid.uuid4().hex
    chunks: List[bytes] = []

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


def http_json(url: str, body: bytes, content_type: str, timeout: float) -> Dict[str, object]:
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


def save_base64_mp3(payload: Dict[str, object], output_path: Path) -> bool:
    mp3_file = payload.get("mp3_file")
    if not isinstance(mp3_file, dict):
        return False

    encoded = mp3_file.get("base64")
    if not isinstance(encoded, str) or not encoded:
        return False

    try:
        raw = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError) as exc:
        raise RuntimeError("service response included invalid mp3_file.base64 data") from exc

    expected_size = mp3_file.get("size_bytes")
    if isinstance(expected_size, int) and expected_size >= 0 and len(raw) != expected_size:
        raise RuntimeError(
            "decoded MP3 size mismatch: expected {0}, got {1}".format(
                expected_size,
                len(raw),
            )
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(raw)
    return True


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


def output_path_for(zip_path: Path, payload: Dict[str, object], requested: Optional[str]) -> Path:
    if requested:
        return Path(requested)
    basename = str(payload.get("output_basename") or zip_path.stem)
    return zip_path.with_name(f"{basename}.mp3")


def render(args: argparse.Namespace) -> Dict[str, object]:
    zip_path = Path(args.zip).expanduser().resolve()
    if not zip_path.is_file():
        raise FileNotFoundError(f"zip file not found: {zip_path}")

    callback_server: Optional[http.server.ThreadingHTTPServer] = None
    callback_state: Optional[CallbackState] = None
    callback_url = args.callback_url
    if args.async_callback:
        if callback_url:
            raise RuntimeError("Use either --async-callback or --callback-url, not both")
        callback_server, callback_state, callback_url = start_callback_server(args)

    fields: Dict[str, str] = {}
    if args.style_id:
        fields["style_id"] = args.style_id
    if args.max_seconds is not None:
        fields["max_seconds"] = str(args.max_seconds)
    if callback_url:
        fields["callback_url"] = callback_url

    body, content_type = encode_multipart(fields, args.field, zip_path)
    server = args.server.rstrip("/")
    accepted_payload = http_json(f"{server}/v1/render", body, content_type, args.timeout)

    if callback_state is not None:
        try:
            if not callback_state.event.wait(args.async_timeout):
                raise RuntimeError(f"timed out waiting for async callback after {args.async_timeout} seconds")
            if callback_state.error:
                raise RuntimeError(f"callback receiver failed: {callback_state.error}")
            if not isinstance(callback_state.payload, dict):
                raise RuntimeError("callback receiver did not get a JSON payload")
            payload = callback_state.payload
            payload["accepted_response"] = accepted_payload
        finally:
            if callback_server is not None:
                callback_server.shutdown()
                callback_server.server_close()
    else:
        payload = accepted_payload

    if callback_url and callback_state is None:
        payload["callback_url"] = callback_url
        return payload

    if payload.get("status") == "failed":
        raise RuntimeError("async render failed: {0}".format(json.dumps(payload.get("error"), ensure_ascii=False)))

    output_path = output_path_for(zip_path, payload, args.output).resolve()
    if save_base64_mp3(payload, output_path):
        payload["saved_from"] = "mp3_file.base64"
    else:
        downloads = payload.get("download")
        if not isinstance(downloads, dict) or not downloads.get("mp3"):
            raise RuntimeError("service response did not include mp3_file.base64 or download.mp3")
        download_file(server, str(downloads["mp3"]), output_path, args.timeout)
        payload["saved_from"] = "download.mp3"
    payload["saved_path"] = str(output_path)
    return payload


def printable_payload(payload: Dict[str, object]) -> Dict[str, object]:
    result = dict(payload)
    mp3_file = result.get("mp3_file")
    if isinstance(mp3_file, dict):
        redacted_mp3 = dict(mp3_file)
        encoded = redacted_mp3.get("base64")
        if isinstance(encoded, str):
            redacted_mp3["base64"] = "<omitted {0} base64 chars>".format(len(encoded))
        result["mp3_file"] = redacted_mp3
    return result


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
    parser.add_argument("--callback-url", help="Submit as an async render and let the service POST JSON here.")
    parser.add_argument(
        "--async-callback",
        action="store_true",
        help="Start a temporary local callback server, submit async render, wait for callback, and save MP3.",
    )
    parser.add_argument("--async-timeout", type=float, default=3600.0, help="Seconds to wait for --async-callback.")
    parser.add_argument("--callback-bind-host", default="127.0.0.1", help="Host/IP for the local callback server.")
    parser.add_argument("--callback-public-host", help="Host/IP the render service can use to reach this client.")
    parser.add_argument("--callback-port", type=int, default=0, help="Local callback server port; 0 chooses a free port.")
    parser.add_argument("--callback-path", default="/callback", help="Local callback path.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    payload = render(args)
    print(json.dumps(printable_payload(payload), ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
