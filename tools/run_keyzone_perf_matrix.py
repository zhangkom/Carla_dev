from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def split_csv_numbers(value: str, *, number_type: type = float) -> list[Any]:
    result = []
    for item in value.split(","):
        item = item.strip()
        if item:
            result.append(number_type(item))
    return result


def combo_label(divisor: float, warmup: float, buffer_size: int) -> str:
    divisor_text = str(divisor).replace(".", "p")
    warmup_text = str(warmup).replace(".", "p")
    return f"div{divisor_text}_warm{warmup_text}_buf{buffer_size}"


def run_command(command: list[str], *, cwd: Path, env: dict[str, str], log_path: Path) -> None:
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"\n$ {' '.join(command)}\n")
        log_file.flush()
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {completed.returncode}: {' '.join(command)}")


def remove_container(container_name: str, *, log_path: Path) -> None:
    docker = shutil.which("docker")
    if not docker:
        return
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"\n$ docker rm -f {container_name}\n")
        subprocess.run(
            [docker, "rm", "-f", container_name],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )


def load_summary(summary_path: Path) -> dict[str, Any]:
    if not summary_path.is_file():
        return {}
    try:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def summarize_combo(
    *,
    label: str,
    divisor: float,
    warmup: float,
    buffer_size: int,
    summary: dict[str, Any],
) -> dict[str, Any]:
    results = summary.get("results")
    if not isinstance(results, list):
        results = []
    ok_results = [item for item in results if isinstance(item, dict) and item.get("ok")]
    elapsed_values = [
        float(item["elapsed_seconds"])
        for item in ok_results
        if isinstance(item.get("elapsed_seconds"), (int, float))
    ]
    max_volume_values = [
        float(item["max_volume_db"])
        for item in ok_results
        if isinstance(item.get("max_volume_db"), (int, float))
    ]
    silent_count = sum(
        1
        for item in ok_results
        if isinstance(item.get("max_volume_db"), (int, float)) and float(item["max_volume_db"]) <= -80.0
    )
    return {
        "label": label,
        "divisor": divisor,
        "warmup": warmup,
        "buffer_size": buffer_size,
        "passed": summary.get("passed", 0),
        "failed": summary.get("failed", 0),
        "skipped": summary.get("skipped", 0),
        "avg_elapsed_seconds": average(elapsed_values),
        "max_elapsed_seconds": round(max(elapsed_values), 3) if elapsed_values else None,
        "min_max_volume_db": round(min(max_volume_values), 3) if max_volume_values else None,
        "silent_count": silent_count,
    }


def write_matrix_summary(rows: list[dict[str, Any]], output_root: Path) -> Path:
    path = output_root / "keyzone_perf_matrix_summary.csv"
    fieldnames = [
        "label",
        "divisor",
        "warmup",
        "buffer_size",
        "passed",
        "failed",
        "skipped",
        "avg_elapsed_seconds",
        "max_elapsed_seconds",
        "min_max_volume_db",
        "silent_count",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def prepare_zip_dir(source_dir: Path, output_root: Path, pattern: str) -> Path:
    if not pattern:
        return source_dir
    selected_dir = output_root / "_selected_zips"
    selected_dir.mkdir(parents=True, exist_ok=True)
    selected = sorted(source_dir.glob(pattern))
    if not selected:
        raise RuntimeError(f"No zip files matched pattern {pattern!r} in {source_dir}")
    for source in selected:
        target = selected_dir / source.name
        if not target.exists() or target.stat().st_mtime < source.stat().st_mtime:
            shutil.copy2(source, target)
    return selected_dir


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Keyzone render parameter matrix with one fresh Docker container per combo."
    )
    parser.add_argument("--image", default="mgsc_daw_service:6.5.18.1612")
    parser.add_argument("--deploy-script", default="deploy_mgsc_daw_service.sh")
    parser.add_argument("--zip-dir", required=True)
    parser.add_argument("--zip-pattern", default="*Keyzone*.zip")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--doc-dir", default="docs")
    parser.add_argument("--host-port-base", type=int, default=18100)
    parser.add_argument("--divisors", default="12,16,20,24,32")
    parser.add_argument("--warmups", default="0,1,2,3")
    parser.add_argument("--buffers", default="256,512,1024")
    parser.add_argument("--timeout", type=float, default=1200.0)
    parser.add_argument("--keep-containers", action="store_true")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    deploy_script = (repo_root / args.deploy_script).resolve()
    zip_dir = Path(args.zip_dir).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    doc_dir = Path(args.doc_dir).expanduser()
    if not doc_dir.is_absolute():
        doc_dir = repo_root / doc_dir
    if not deploy_script.is_file():
        print(f"deploy script not found: {deploy_script}", file=sys.stderr)
        return 2
    if not zip_dir.is_dir():
        print(f"zip dir not found: {zip_dir}", file=sys.stderr)
        return 2

    output_root.mkdir(parents=True, exist_ok=True)
    doc_dir.mkdir(parents=True, exist_ok=True)
    zip_dir = prepare_zip_dir(zip_dir, output_root, args.zip_pattern)
    matrix_log = output_root / "keyzone_perf_matrix.log"
    rows: list[dict[str, Any]] = []

    divisors = split_csv_numbers(args.divisors, number_type=float)
    warmups = split_csv_numbers(args.warmups, number_type=float)
    buffers = split_csv_numbers(args.buffers, number_type=int)
    combo_index = 0
    total = len(divisors) * len(warmups) * len(buffers)

    for divisor in divisors:
        for warmup in warmups:
            for buffer_size in buffers:
                combo_index += 1
                label = combo_label(divisor, warmup, buffer_size)
                host_port = args.host_port_base + combo_index
                container_name = f"mgsc_daw_keyzone_matrix_{label}"
                combo_output = output_root / label
                runtime_dir = combo_output / "runtime"
                report_dir = combo_output / "acceptance"
                combo_output.mkdir(parents=True, exist_ok=True)
                print(f"[{combo_index}/{total}] {label} port={host_port}")

                env = os.environ.copy()
                image_name, _, version = args.image.partition(":")
                env.update(
                    {
                        "IMAGE_NAME": args.image,
                        "VERSION": version or "matrix",
                        "LOAD_IMAGE": "0",
                        "CONTAINER_NAME": container_name,
                        "HOST_PORT": str(host_port),
                        "RUNTIME_DIR": str(runtime_dir),
                        "RESTART_POLICY": "no",
                        "MUSIC_SERVICE_DUMMY_SLEEP_DIVISOR_BY_PLUGIN": f"vst_keyzone_classic={divisor}",
                        "MUSIC_SERVICE_RENDER_WARMUP_SECONDS_BY_PLUGIN": f"vst_keyzone_classic={warmup}",
                        "MUSIC_SERVICE_BUFFER_SIZE_BY_PLUGIN": f"vst_keyzone_classic={buffer_size}",
                    }
                )

                try:
                    run_command(["bash", str(deploy_script)], cwd=repo_root, env=env, log_path=matrix_log)
                    run_command(
                        [
                            sys.executable,
                            str(repo_root / "tools" / "run_remote_acceptance.py"),
                            "--url",
                            f"http://127.0.0.1:{host_port}/mgsc_daw_service/v1/render",
                            "--zip-dir",
                            str(zip_dir),
                            "--output-dir",
                            str(report_dir),
                            "--doc-dir",
                            str(doc_dir),
                            "--version",
                            f"keyzone_matrix_{label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                            "--timeout",
                            str(args.timeout),
                        ],
                        cwd=repo_root,
                        env=env,
                        log_path=matrix_log,
                    )
                except Exception as exc:
                    (combo_output / "ERROR.txt").write_text(str(exc), encoding="utf-8")
                    print(f"  FAIL {exc}")
                finally:
                    if not args.keep_containers:
                        remove_container(container_name, log_path=matrix_log)

                rows.append(
                    summarize_combo(
                        label=label,
                        divisor=divisor,
                        warmup=warmup,
                        buffer_size=buffer_size,
                        summary=load_summary(report_dir / "summary.json"),
                    )
                )
                write_matrix_summary(rows, output_root)

    summary_path = write_matrix_summary(rows, output_root)
    print(f"matrix summary: {summary_path}")
    return 0 if all(int(row.get("failed") or 0) == 0 for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
