from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import MidiPolicy


class MidiPolicyError(RuntimeError):
    pass


def _read_vlq(data: bytes, position: int) -> tuple[int, int]:
    value = 0
    for _ in range(4):
        if position >= len(data):
            raise MidiPolicyError("Unexpected end of MIDI data while reading variable length value")
        byte = data[position]
        position += 1
        value = (value << 7) | (byte & 0x7F)
        if (byte & 0x80) == 0:
            return value, position
    raise MidiPolicyError("Invalid MIDI variable length value")


def _write_vlq(value: int) -> bytes:
    if value < 0:
        raise MidiPolicyError("MIDI delta time cannot be negative")
    parts = [value & 0x7F]
    value >>= 7
    while value:
        parts.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(parts))


def _channel_payload_size(event_type: int) -> int:
    if event_type in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
        return 2
    if event_type in (0xC0, 0xD0):
        return 1
    raise MidiPolicyError(f"Unsupported MIDI channel event type: 0x{event_type:02x}")


def _new_status(status: int, policy: MidiPolicy) -> int:
    event_type = status & 0xF0
    target_channel = policy.target_channel
    if target_channel is None:
        return status
    return event_type | ((target_channel - 1) & 0x0F)


def _stat(stats: dict[str, Any], key: str, amount: int = 1) -> None:
    stats[key] = int(stats.get(key, 0)) + amount


def _transform_channel_event(
    status: int,
    payload: bytes,
    policy: MidiPolicy,
    stats: dict[str, Any],
) -> bytes | None:
    event_type = status & 0xF0
    channel = (status & 0x0F) + 1
    _stat(stats, "channel_events_seen")

    if policy.source_channel is not None and channel != policy.source_channel:
        _stat(stats, "channel_events_dropped_by_source_channel")
        return None

    if event_type in (0x80, 0x90):
        _stat(stats, "notes_kept")
        return bytes([_new_status(status, policy)]) + payload

    if event_type == 0xA0:
        if policy.keep_note_aftertouch:
            _stat(stats, "note_aftertouch_kept")
            return bytes([_new_status(status, policy)]) + payload
        _stat(stats, "note_aftertouch_removed")
        return None

    if event_type == 0xB0:
        controller = payload[0]
        if policy.remove_bank_select and controller in (0, 32):
            _stat(stats, "bank_select_removed")
            return None
        if controller not in set(policy.keep_control_changes):
            _stat(stats, "control_changes_removed")
            return None
        _stat(stats, "control_changes_kept")
        return bytes([_new_status(status, policy)]) + payload

    if event_type == 0xC0:
        if policy.remove_program_changes:
            _stat(stats, "program_changes_removed")
            return None
        _stat(stats, "program_changes_kept")
        return bytes([_new_status(status, policy)]) + payload

    if event_type == 0xD0:
        if policy.keep_channel_pressure:
            _stat(stats, "channel_pressure_kept")
            return bytes([_new_status(status, policy)]) + payload
        _stat(stats, "channel_pressure_removed")
        return None

    if event_type == 0xE0:
        if policy.keep_pitch_bend:
            _stat(stats, "pitch_bend_kept")
            return bytes([_new_status(status, policy)]) + payload
        _stat(stats, "pitch_bend_removed")
        return None

    _stat(stats, "channel_events_removed_unknown_type")
    return None


def _write_event(track: bytearray, delta: int, raw_event: bytes) -> None:
    track += _write_vlq(delta)
    track += raw_event


def _rewrite_track(track_data: bytes, policy: MidiPolicy, stats: dict[str, Any]) -> bytes:
    position = 0
    running_status: int | None = None
    pending_delta = 0
    output = bytearray()
    wrote_end_of_track = False

    while position < len(track_data):
        delta, position = _read_vlq(track_data, position)
        pending_delta += delta
        if position >= len(track_data):
            raise MidiPolicyError("Unexpected end of MIDI track")

        status = track_data[position]
        if status < 0x80:
            if running_status is None:
                raise MidiPolicyError("MIDI running status used before an explicit status")
        else:
            position += 1
            if status < 0xF0:
                running_status = status

        if status < 0x80:
            status = running_status
        if status is None:
            raise MidiPolicyError("Invalid MIDI status")

        if status == 0xFF:
            if position >= len(track_data):
                raise MidiPolicyError("Unexpected end of MIDI meta event")
            meta_type = track_data[position]
            position += 1
            size, position = _read_vlq(track_data, position)
            payload = track_data[position : position + size]
            position += size
            if len(payload) != size:
                raise MidiPolicyError("Unexpected end of MIDI meta payload")
            raw_event = bytes([0xFF, meta_type]) + _write_vlq(size) + payload
            _write_event(output, pending_delta, raw_event)
            pending_delta = 0
            if meta_type == 0x2F:
                wrote_end_of_track = True
            continue

        if status in (0xF0, 0xF7):
            size, position = _read_vlq(track_data, position)
            payload = track_data[position : position + size]
            position += size
            if len(payload) != size:
                raise MidiPolicyError("Unexpected end of MIDI sysex payload")
            if policy.keep_sysex:
                raw_event = bytes([status]) + _write_vlq(size) + payload
                _write_event(output, pending_delta, raw_event)
                pending_delta = 0
                _stat(stats, "sysex_kept")
            else:
                _stat(stats, "sysex_removed")
            continue

        event_type = status & 0xF0
        payload_size = _channel_payload_size(event_type)
        payload = track_data[position : position + payload_size]
        position += payload_size
        if len(payload) != payload_size:
            raise MidiPolicyError("Unexpected end of MIDI channel event")

        rewritten = _transform_channel_event(status, payload, policy, stats)
        if rewritten is None:
            _stat(stats, "channel_events_removed")
            continue

        _stat(stats, "channel_events_kept")
        _write_event(output, pending_delta, rewritten)
        pending_delta = 0

    if not wrote_end_of_track:
        _write_event(output, pending_delta, b"\xff\x2f\x00")

    return bytes(output)


def preprocess_midi(
    input_path: Path,
    output_path: Path,
    policy: MidiPolicy,
) -> dict[str, Any]:
    data = input_path.read_bytes()
    if len(data) < 14 or data[:4] != b"MThd":
        raise MidiPolicyError(f"Not a standard MIDI file: {input_path}")

    header_length = int.from_bytes(data[4:8], "big")
    if header_length < 6:
        raise MidiPolicyError(f"Invalid MIDI header length: {header_length}")
    header_start = 8
    header_end = header_start + header_length
    if header_end > len(data):
        raise MidiPolicyError("MIDI header is truncated")

    header = data[header_start:header_end]
    track_count = int.from_bytes(header[2:4], "big")
    stats: dict[str, Any] = {
        "enabled": True,
        "source_channel": policy.source_channel,
        "target_channel": policy.target_channel,
        "remove_program_changes": policy.remove_program_changes,
        "remove_bank_select": policy.remove_bank_select,
        "keep_control_changes": list(policy.keep_control_changes),
        "tracks_expected": track_count,
    }

    output = bytearray()
    output += b"MThd" + header_length.to_bytes(4, "big") + header

    position = header_end
    tracks_seen = 0
    while position < len(data):
        if position + 8 > len(data):
            raise MidiPolicyError("Truncated MIDI chunk header")
        chunk_type = data[position : position + 4]
        chunk_length = int.from_bytes(data[position + 4 : position + 8], "big")
        position += 8
        chunk_data = data[position : position + chunk_length]
        position += chunk_length
        if len(chunk_data) != chunk_length:
            raise MidiPolicyError("Truncated MIDI chunk data")

        if chunk_type != b"MTrk":
            output += chunk_type + chunk_length.to_bytes(4, "big") + chunk_data
            continue

        rewritten = _rewrite_track(chunk_data, policy, stats)
        output += b"MTrk" + len(rewritten).to_bytes(4, "big") + rewritten
        tracks_seen += 1

    stats["tracks_seen"] = tracks_seen
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(output)
    stats["output_path"] = str(output_path)
    stats["output_bytes"] = output_path.stat().st_size
    return stats


def _decode_meta_text(payload: bytes) -> str:
    for encoding in ("utf-8", "gbk", "latin1"):
        try:
            return payload.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return ""


def _channel_analysis_entry(channels: dict[int, dict[str, Any]], channel: int) -> dict[str, Any]:
    return channels.setdefault(
        channel,
        {
            "channel": channel,
            "note_on_count": 0,
            "note_event_count": 0,
            "note_tick_duration": 0,
            "programs": [],
            "track_names": [],
        },
    )


def _analyze_track_channels(track_data: bytes, channels: dict[int, dict[str, Any]]) -> None:
    position = 0
    running_status: int | None = None
    tick = 0
    active_notes: dict[tuple[int, int], list[int]] = {}
    track_names: list[str] = []
    track_channels: set[int] = set()

    while position < len(track_data):
        delta, position = _read_vlq(track_data, position)
        tick += delta
        if position >= len(track_data):
            raise MidiPolicyError("Unexpected end of MIDI track")

        status = track_data[position]
        if status < 0x80:
            if running_status is None:
                raise MidiPolicyError("MIDI running status used before an explicit status")
        else:
            position += 1
            if status < 0xF0:
                running_status = status

        if status < 0x80:
            status = running_status
        if status is None:
            raise MidiPolicyError("Invalid MIDI status")

        if status == 0xFF:
            if position >= len(track_data):
                raise MidiPolicyError("Unexpected end of MIDI meta event")
            meta_type = track_data[position]
            position += 1
            size, position = _read_vlq(track_data, position)
            payload = track_data[position : position + size]
            position += size
            if position > len(track_data):
                raise MidiPolicyError("Unexpected end of MIDI meta payload")
            if meta_type in (0x03, 0x04):
                decoded = _decode_meta_text(payload)
                if decoded:
                    track_names.append(decoded)
            continue

        if status in (0xF0, 0xF7):
            size, position = _read_vlq(track_data, position)
            position += size
            if position > len(track_data):
                raise MidiPolicyError("Unexpected end of MIDI sysex payload")
            continue

        event_type = status & 0xF0
        channel = (status & 0x0F) + 1
        payload_size = _channel_payload_size(event_type)
        payload = track_data[position : position + payload_size]
        position += payload_size
        if len(payload) != payload_size:
            raise MidiPolicyError("Unexpected end of MIDI channel event")

        if event_type == 0xC0:
            channel_stats = _channel_analysis_entry(channels, channel)
            program_number = payload[0] + 1
            if program_number not in channel_stats["programs"]:
                channel_stats["programs"].append(program_number)
            track_channels.add(channel)
            continue

        if event_type not in (0x80, 0x90):
            continue

        note = payload[0]
        velocity = payload[1]
        channel_stats = _channel_analysis_entry(channels, channel)
        track_channels.add(channel)
        channel_stats["note_event_count"] += 1

        note_key = (channel, note)
        if event_type == 0x90 and velocity > 0:
            channel_stats["note_on_count"] += 1
            active_notes.setdefault(note_key, []).append(tick)
            continue

        starts = active_notes.get(note_key)
        if starts:
            start_tick = starts.pop()
            channel_stats["note_tick_duration"] += max(0, tick - start_tick)

    for (channel, _note), starts in active_notes.items():
        channel_stats = channels[channel]
        for start_tick in starts:
            channel_stats["note_tick_duration"] += max(0, tick - start_tick)

    for channel in track_channels:
        channel_stats = _channel_analysis_entry(channels, channel)
        for track_name in track_names:
            if track_name and track_name not in channel_stats["track_names"]:
                channel_stats["track_names"].append(track_name)


def _channel_name_text(channel_stats: dict[str, Any]) -> str:
    return " ".join(str(name).lower() for name in channel_stats.get("track_names", []))


def _select_source_channel(channel_list: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
    if not channel_list:
        return None, "no_note_channel_found"

    non_drum = [item for item in channel_list if int(item["channel"]) != 10] or channel_list
    melody_keywords = ("melody", "lead", "main", "theme", "vocal", "主旋律", "旋律")
    melody_candidates = [
        item
        for item in non_drum
        if any(keyword in _channel_name_text(item) for keyword in melody_keywords)
    ]
    if melody_candidates:
        return max(
            melody_candidates,
            key=lambda item: (int(item["note_on_count"]), int(item["note_tick_duration"])),
        ), "track_name_melody"

    avoid_keywords = (
        "chord",
        "bass",
        "drum",
        "kit",
        "back",
        "left",
        "right",
        "intro",
        "grace",
    )
    melodic_candidates = [
        item
        for item in non_drum
        if not any(keyword in _channel_name_text(item) for keyword in avoid_keywords)
    ]
    if melodic_candidates:
        return max(
            melodic_candidates,
            key=lambda item: (int(item["note_on_count"]), int(item["note_tick_duration"])),
        ), "highest_note_count_excluding_accompaniment_names"

    return max(
        non_drum,
        key=lambda item: (int(item["note_tick_duration"]), int(item["note_on_count"])),
    ), "highest_note_duration_excluding_channel_10"


def analyze_midi_channels(input_path: Path) -> dict[str, Any]:
    data = input_path.read_bytes()
    if len(data) < 14 or data[:4] != b"MThd":
        raise MidiPolicyError(f"Not a standard MIDI file: {input_path}")

    header_length = int.from_bytes(data[4:8], "big")
    if header_length < 6:
        raise MidiPolicyError(f"Invalid MIDI header length: {header_length}")
    header_start = 8
    header_end = header_start + header_length
    if header_end > len(data):
        raise MidiPolicyError("MIDI header is truncated")

    header = data[header_start:header_end]
    track_count = int.from_bytes(header[2:4], "big")
    channels: dict[int, dict[str, Any]] = {}

    position = header_end
    tracks_seen = 0
    while position < len(data):
        if position + 8 > len(data):
            raise MidiPolicyError("Truncated MIDI chunk header")
        chunk_type = data[position : position + 4]
        chunk_length = int.from_bytes(data[position + 4 : position + 8], "big")
        position += 8
        chunk_data = data[position : position + chunk_length]
        position += chunk_length
        if len(chunk_data) != chunk_length:
            raise MidiPolicyError("Truncated MIDI chunk data")
        if chunk_type != b"MTrk":
            continue

        _analyze_track_channels(chunk_data, channels)
        tracks_seen += 1

    channel_list = sorted(
        channels.values(),
        key=lambda item: (
            -int(item["note_tick_duration"]),
            -int(item["note_on_count"]),
            int(item["channel"]),
        ),
    )
    selected, selection_reason = _select_source_channel(channel_list)

    return {
        "tracks_expected": track_count,
        "tracks_seen": tracks_seen,
        "channels": channel_list,
        "selected_source_channel": int(selected["channel"]) if selected else None,
        "selection_reason": selection_reason,
    }
