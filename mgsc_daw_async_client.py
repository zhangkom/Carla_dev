# /**
# * File name: mgsc_daw_async_client.py
# * Brief: MGSC DAW 异步回调客户端
# * Function:
# *     上传 ZIP 异步渲染任务，启动本地 callback 服务等待 MP3 base64 回调并保存文件
# * Author: 咪咕数创工程架构组
# *     MGSC AI Software Architecture group
# * Version: V2.5.10
# * Date: 2026/05/01
# */
import argparse
import json
import os
import sys

from mgsc_daw_client import DEFAULT_SERVER, printable_payload, render


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Upload a DAW zip bundle to mgsc_daw_service in async callback mode "
            "and save the rendered MP3."
        )
    )
    parser.add_argument("--server", default=os.environ.get("DAW_SERVER", DEFAULT_SERVER))
    parser.add_argument("--zip", required=True, help="Input zip containing one MIDI file and conf.json.")
    parser.add_argument("--output", help="Local MP3 output path. Defaults to the service output basename.")
    parser.add_argument("--field", default="data", choices=("data", "bundle"))
    parser.add_argument("--style-id", help="Optional debug override; production zips should use conf.json.")
    parser.add_argument("--max-seconds", type=float, help="Optional debug render cap.")
    parser.add_argument("--timeout", type=float, default=120.0, help="Seconds to wait for request acceptance.")
    parser.add_argument("--async-timeout", type=float, default=3600.0, help="Seconds to wait for callback.")
    parser.add_argument(
        "--callback-url",
        help=(
            "External callback URL. If omitted, this client starts a temporary local "
            "callback server and waits for the result."
        ),
    )
    parser.add_argument("--callback-bind-host", default="0.0.0.0", help="Host/IP for the local callback server.")
    parser.add_argument(
        "--callback-public-host",
        default=os.environ.get("DAW_CALLBACK_PUBLIC_HOST"),
        help=(
            "Host/IP the render service can use to reach this client. For Docker Desktop "
            "host callbacks, use host.docker.internal."
        ),
    )
    parser.add_argument("--callback-port", type=int, default=0, help="Local callback server port; 0 chooses a free port.")
    parser.add_argument("--callback-path", default="/callback", help="Local callback path.")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.async_callback = not bool(args.callback_url)
    payload = render(args)
    print(json.dumps(printable_payload(payload), ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("ERROR: {0}".format(exc), file=sys.stderr)
        raise SystemExit(1)
