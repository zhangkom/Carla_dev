#!/usr/bin/env python3
# /**
# * File name: generate_mapping_coverage_zips.py
# * Brief: 需求映射覆盖 ZIP 生成工具
# * Function:
# *     根据 config/instrument_mapping.deploy.json 的 137 条 Bank/Program 映射，
# *     为每条映射生成一个 style_id=auto 的测试 ZIP。
# * Author: 咪咕数创工程架构组
# *     MGSC AI Software Architecture group
# * Version: V2.5.10
# * Date: 2026/05/11
# */
from __future__ import annotations

import argparse
import csv
import json
import re
import zipfile
from pathlib import Path
from typing import Any

import mido


def safe_name(value: str) -> str:
    value = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("._")
    return value or "item"


def note_pattern(program: int, is_drum: bool) -> list[int]:
    if is_drum:
        return [36, 38, 42, 46, 45, 48, 42, 49]
    if program < 8:
        return [60, 64, 67, 72, 67, 64, 60, 55]
    if 24 <= program <= 31:
        return [52, 55, 59, 64, 59, 55, 52, 47]
    if 32 <= program <= 39:
        return [40, 43, 47, 52, 47, 43, 40, 35]
    if 40 <= program <= 55:
        return [55, 59, 62, 67, 62, 59, 55, 50]
    if 56 <= program <= 71:
        return [62, 65, 69, 74, 69, 65, 62, 57]
    if 72 <= program <= 79:
        return [72, 76, 79, 84, 79, 76, 72, 67]
    return [60, 62, 65, 67, 69, 67, 65, 62]


def build_midi(path: Path, mapping: dict[str, Any], seconds: float) -> None:
    midi_info = mapping["midi"]
    bank = int(midi_info["bank"])
    program = int(midi_info["program"])
    is_drum = bool(midi_info.get("is_drum_bank"))
    channel = 9 if is_drum else 0
    ticks_per_beat = 480
    tempo = mido.bpm2tempo(96)
    ticks_per_note = int(ticks_per_beat * 0.75)
    phrase = note_pattern(program, is_drum)

    mid = mido.MidiFile(type=1, ticks_per_beat=ticks_per_beat)
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("track_name", name=mapping["id"], time=0))
    meta.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
    mid.tracks.append(meta)

    track = mido.MidiTrack()
    track.append(mido.MetaMessage("track_name", name=mapping["id"], time=0))
    if not is_drum:
        if bank <= 127:
            track.append(mido.Message("control_change", channel=channel, control=0, value=bank, time=0))
        track.append(mido.Message("program_change", channel=channel, program=program, time=0))
    else:
        track.append(mido.Message("program_change", channel=channel, program=program, time=0))

    elapsed_ticks = 0
    target_ticks = int(seconds * ticks_per_beat * 96 / 60)
    first = True
    while elapsed_ticks < target_ticks:
        for note in phrase:
            if elapsed_ticks >= target_ticks:
                break
            track.append(mido.Message("note_on", channel=channel, note=note, velocity=92, time=0 if first else 0))
            track.append(mido.Message("note_off", channel=channel, note=note, velocity=0, time=ticks_per_note))
            elapsed_ticks += ticks_per_note
            first = False
    track.append(mido.MetaMessage("end_of_track", time=0))
    mid.tracks.append(track)
    mid.save(path)


def _source_track_has_channel(track: mido.MidiTrack, channel: int) -> bool:
    return any(getattr(message, "channel", None) == channel for message in track)


def build_midi_from_source(path: Path, mapping: dict[str, Any], source_midi: Path) -> None:
    midi_info = mapping["midi"]
    bank = int(midi_info["bank"])
    program = int(midi_info["program"])
    is_drum = bool(midi_info.get("is_drum_bank"))
    target_channel = 9 if is_drum else 0

    source = mido.MidiFile(source_midi)
    output = mido.MidiFile(type=1, ticks_per_beat=source.ticks_per_beat)

    meta_track = mido.MidiTrack()
    meta_track.append(mido.MetaMessage("track_name", name=f"{mapping['id']} meta", time=0))
    if source.tracks:
        for message in source.tracks[0]:
            if message.is_meta and message.type != "end_of_track":
                meta_track.append(message.copy())
    meta_track.append(mido.MetaMessage("end_of_track", time=0))
    output.tracks.append(meta_track)

    events: list[tuple[int, int, mido.Message]] = []
    sequence = 0

    if not is_drum:
        if 0 <= bank <= 127:
            events.append((0, sequence, mido.Message("control_change", channel=target_channel, control=0, value=bank, time=0)))
            sequence += 1
        events.append((0, sequence, mido.Message("program_change", channel=target_channel, program=program, time=0)))
        sequence += 1
    else:
        events.append((0, sequence, mido.Message("program_change", channel=target_channel, program=program, time=0)))
        sequence += 1

    for track in source.tracks[1:]:
        source_track_is_drum = _source_track_has_channel(track, 9)
        if is_drum != source_track_is_drum:
            continue
        absolute_tick = 0
        for message in track:
            absolute_tick += message.time
            if message.is_meta or not hasattr(message, "channel"):
                continue
            if message.type == "program_change":
                continue
            if message.type == "control_change" and message.control in (0, 32):
                continue
            copied = message.copy(channel=target_channel, time=0)
            events.append((absolute_tick, sequence, copied))
            sequence += 1

    events.sort(key=lambda item: (item[0], item[1]))
    music_track = mido.MidiTrack()
    music_track.append(mido.MetaMessage("track_name", name=mapping["id"], time=0))
    last_tick = 0
    for absolute_tick, _, message in events:
        message.time = max(0, absolute_tick - last_tick)
        music_track.append(message)
        last_tick = absolute_tick
    music_track.append(mido.MetaMessage("end_of_track", time=0))
    output.tracks.append(music_track)
    output.save(path)


def build_conf(mapping: dict[str, Any]) -> dict[str, Any]:
    return {
        "style_id": "auto",
        "render": {
            "format": "mp3",
            "bit_depth": 16,
            "bitrate": 320,
            "samplerate": 44100,
            "loop": False,
        },
        "test_meta": {
            "mapping_id": mapping["id"],
            "web_bank": mapping["midi"]["bank"],
            "web_program": mapping["midi"]["program"],
            "cloud_plugin_name": mapping["target"]["plugin_name"],
            "cloud_plugin_id": mapping["target"]["plugin_id"],
            "cloud_program": mapping["target"]["program"],
            "source_doc": mapping.get("source_doc", {}),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate one render ZIP per demand mapping row.")
    parser.add_argument(
        "--mapping",
        default="config/instrument_mapping.deploy.json",
        help="Path to instrument_mapping.deploy.json",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory for generated coverage zips",
    )
    parser.add_argument("--seconds", type=float, default=12.0, help="Generated MIDI phrase length.")
    parser.add_argument(
        "--source-midi",
        default=None,
        help="Optional source MIDI. When set, preserve its full song content and rewrite Bank/Program per mapping.",
    )
    args = parser.parse_args()

    mapping_path = Path(args.mapping)
    output_dir = Path(args.output_dir)
    midi_dir = output_dir / "_midi"
    output_dir.mkdir(parents=True, exist_ok=True)
    midi_dir.mkdir(parents=True, exist_ok=True)

    data = json.load(open(mapping_path, encoding="utf-8"))
    manifest_rows: list[dict[str, Any]] = []
    for mapping in data["mappings"]:
        midi_info = mapping["midi"]
        target = mapping["target"]
        zip_name = (
            f"{mapping['id']}_bank{midi_info['bank']:03d}_program{midi_info['program']:03d}_"
            f"{safe_name(target['plugin_name'])}_{safe_name(str(target['program']))}.zip"
        )
        midi_path = midi_dir / f"{Path(zip_name).stem}.mid"
        if args.source_midi:
            build_midi_from_source(midi_path, mapping, Path(args.source_midi))
        else:
            build_midi(midi_path, mapping, args.seconds)
        conf = build_conf(mapping)
        conf_bytes = json.dumps(conf, ensure_ascii=False, indent=2).encode("utf-8")
        zip_path = output_dir / zip_name
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.write(midi_path, "input.mid")
            bundle.writestr("conf.json", conf_bytes)
        manifest_rows.append(
            {
                "zip": zip_name,
                "mapping_id": mapping["id"],
                "bank": midi_info["bank"],
                "program": midi_info["program"],
                "is_drum_bank": midi_info.get("is_drum_bank"),
                "cloud_plugin_name": target["plugin_name"],
                "cloud_plugin_id": target["plugin_id"],
                "cloud_program": target["program"],
                "source_category": mapping.get("source_doc", {}).get("category"),
                "source_midi_name": mapping.get("source_doc", {}).get("midi_name"),
            }
        )

    manifest_json = output_dir / "manifest.json"
    manifest_csv = output_dir / "manifest.csv"
    manifest_json.write_text(json.dumps(manifest_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    with manifest_csv.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest_rows[0]))
        writer.writeheader()
        writer.writerows(manifest_rows)

    print(f"generated {len(manifest_rows)} zips")
    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
