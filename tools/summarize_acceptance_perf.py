# /**
# * File name: summarize_acceptance_perf.py
# * Brief: 验收结果性能聚合工具
# * Function:
# *     从 run_remote_acceptance.py 生成的 summary.json 中聚合耗时和音量结果
# * Author: 软件工程架构组
# *     MGSC AI Software Architecture group
# * Version: V2.5.10
# * Date: 2026/05/18
# */
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RenderCase:
    zip_name: str
    style_id: str
    seconds: float
    duration_seconds: float | None
    mean_volume_db: float | None
    max_volume_db: float | None
    ok: bool


def style_family(style_id: str) -> str:
    if style_id.startswith("keyzone"):
        return "Keyzone Classic"
    if style_id.startswith("kong"):
        return "Kong Qin_RV"
    if style_id.startswith("sonatina"):
        return "Sonatina Orchestra"
    if style_id.startswith("dsk"):
        return "DSK Saxophones"
    if style_id.startswith("sf2"):
        return "Musyng Kite SF2"
    if style_id == "manual_track_mix":
        return "Manual multi-track"
    return "Other"


def as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_cases(summary_path: Path) -> list[RenderCase]:
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    cases: list[RenderCase] = []
    for item in data.get("results", []):
        seconds = as_float(item.get("seconds"))
        if seconds is None:
            continue
        cases.append(
            RenderCase(
                zip_name=str(item.get("zip_name") or ""),
                style_id=str(item.get("style_id") or ""),
                seconds=seconds,
                duration_seconds=as_float(item.get("duration_seconds")),
                mean_volume_db=as_float(item.get("mean_volume_db")),
                max_volume_db=as_float(item.get("max_volume_db")),
                ok=bool(item.get("ok")),
            )
        )
    return cases


def fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.3f}"


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, round((len(values) - 1) * fraction)))
    return sorted(values)[index]


def build_markdown(summary_path: Path, cases: list[RenderCase], top: int) -> str:
    passed = sum(1 for item in cases if item.ok)
    lines = [
        f"# Acceptance Performance Summary",
        "",
        f"- Source: `{summary_path}`",
        f"- Cases: {len(cases)}",
        f"- Passed: {passed}",
        f"- Failed: {len(cases) - passed}",
        "",
        "## By Family",
        "",
        "| family | count | avg(s) | median(s) | p90(s) | min(s) | max(s) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    groups: dict[str, list[RenderCase]] = defaultdict(list)
    for item in cases:
        groups[style_family(item.style_id)].append(item)

    family_rows = []
    for family, items in groups.items():
        seconds = sorted(item.seconds for item in items)
        family_rows.append(
            (
                statistics.mean(seconds),
                family,
                len(items),
                statistics.median(seconds),
                percentile(seconds, 0.9),
                seconds[0],
                seconds[-1],
            )
        )
    for avg, family, count, median, p90, min_value, max_value in sorted(
        family_rows, reverse=True
    ):
        lines.append(
            f"| {family} | {count} | {avg:.3f} | {median:.3f} | "
            f"{p90:.3f} | {min_value:.3f} | {max_value:.3f} |"
        )

    lines.extend(
        [
            "",
            f"## Top {top} Slow Cases",
            "",
            "| zip | seconds | duration | style | mean dB | max dB | ok |",
            "|---|---:|---:|---|---:|---:|---:|",
        ]
    )
    for item in sorted(cases, key=lambda case: case.seconds, reverse=True)[:top]:
        lines.append(
            f"| `{item.zip_name}` | {item.seconds:.3f} | {fmt(item.duration_seconds)} | "
            f"`{item.style_id}` | {fmt(item.mean_volume_db)} | "
            f"{fmt(item.max_volume_db)} | {item.ok} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize render acceptance performance.")
    parser.add_argument("summary_json", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args()

    cases = load_cases(args.summary_json)
    markdown = build_markdown(args.summary_json, cases, max(1, args.top))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8")
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
