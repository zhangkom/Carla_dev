# /**
# * File name: instrument_mapping.py
# * Brief: MGSC DAW 渲染服务模块
# * Function:
# *     提供 FastAPI 渲染接口、音源配置、MIDI 策略和渲染调度能力
# * Author: 咪咕数创工程架构组
# *     MGSC AI Software Architecture group
# * Version: V2.5.10
# * Date: 2026/04/30
# */

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ServiceConfig, StyleProfile


class InstrumentMappingError(RuntimeError):
    pass


@dataclass(frozen=True)
class InstrumentMappingEntry:
    id: str
    bank: int
    program: int
    plugin_id: str
    plugin_name: str
    plugin_type: str
    target_bank: str
    target_program: str
    preset_relpaths: tuple[str, ...]
    implementation: str
    needs_confirmation: tuple[str, ...]
    notes: tuple[str, ...]


_MAPPING_CACHE: dict[Path, tuple[int, float, tuple[InstrumentMappingEntry, ...]]] = {}


def _candidate_mapping_paths(config: ServiceConfig) -> list[Path]:
    paths: list[Path] = []
    env_path = os.environ.get("MUSIC_SERVICE_INSTRUMENT_MAPPING")
    if env_path:
        paths.append(Path(env_path))
    paths.append(config.config_path.parent / "instrument_mapping.deploy.json")
    paths.append(config.carla_root / "config" / "instrument_mapping.deploy.json")
    return paths


def instrument_mapping_path(config: ServiceConfig) -> Path:
    for raw_path in _candidate_mapping_paths(config):
        path = raw_path.expanduser()
        if path.is_file():
            return path.resolve()
    checked = ", ".join(str(path) for path in _candidate_mapping_paths(config))
    raise InstrumentMappingError(f"Instrument mapping config not found; checked: {checked}")


def load_instrument_mappings(config: ServiceConfig) -> tuple[InstrumentMappingEntry, ...]:
    path = instrument_mapping_path(config)
    stat = path.stat()
    cached = _MAPPING_CACHE.get(path)
    if cached and cached[0] == stat.st_size and cached[1] == stat.st_mtime:
        return cached[2]

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InstrumentMappingError(f"Failed to read instrument mapping config: {path}") from exc

    raw_mappings = data.get("mappings", [])
    if not isinstance(raw_mappings, list):
        raise InstrumentMappingError("instrument mapping config field mappings must be an array")

    mappings: list[InstrumentMappingEntry] = []
    for index, item in enumerate(raw_mappings):
        if not isinstance(item, dict):
            raise InstrumentMappingError(f"mappings[{index}] must be an object")
        source_doc = _mapping_dict(item.get("source_doc", {}), f"mappings[{index}].source_doc")
        midi = _mapping_dict(item.get("midi"), f"mappings[{index}].midi")
        target = _mapping_dict(item.get("target"), f"mappings[{index}].target")
        status = _mapping_dict(item.get("status", {}), f"mappings[{index}].status")

        mappings.append(
            InstrumentMappingEntry(
                id=str(item.get("id") or f"mapping_{index:03d}"),
                bank=_mapping_int(midi.get("bank"), f"mappings[{index}].midi.bank"),
                program=_mapping_int(
                    midi.get("program"),
                    f"mappings[{index}].midi.program",
                    fallback_values=(source_doc.get("midi_id"), target.get("program")),
                ),
                plugin_id=str(target.get("plugin_id", "")).strip(),
                plugin_name=str(target.get("plugin_name", "")).strip(),
                plugin_type=str(target.get("plugin_type", "")).strip().lower(),
                target_bank=str(target.get("bank", "")).strip(),
                target_program=str(target.get("program", "")).strip(),
                preset_relpaths=_preset_relpaths(target.get("preset_candidates")),
                implementation=str(status.get("implementation", "")).strip(),
                needs_confirmation=_string_tuple(status.get("needs_confirmation")),
                notes=_string_tuple(status.get("notes")),
            )
        )

    _MAPPING_CACHE[path] = (stat.st_size, stat.st_mtime, tuple(mappings))
    return tuple(mappings)


def style_for_programs_from_mapping(
    config: ServiceConfig,
    programs: list[int],
    channel: int | None = None,
    bank_programs: list[dict[str, Any]] | None = None,
) -> tuple[StyleProfile, dict[str, object]]:
    mappings = load_instrument_mappings(config)
    entries = {(item.bank, item.program): item for item in mappings}

    for bank, program, match_mode in _candidate_keys(programs, channel, bank_programs):
        entry = entries.get((bank, program))
        if entry is None:
            continue
        style = _style_for_entry(config, entry)
        if style is not None:
            return style, _match_info(
                entry=entry,
                programs=programs,
                bank=bank,
                program=program,
                match_mode=match_mode,
                fallback=False,
            )

        fallback_style = _fallback_style(config)
        return fallback_style, _match_info(
            entry=entry,
            programs=programs,
            bank=bank,
            program=program,
            match_mode=f"{match_mode}_target_style_unavailable",
            fallback=True,
            fallback_reason="target_style_unavailable",
            fallback_style=fallback_style,
        )

    fallback_style = _fallback_style(config)
    return fallback_style, {
        "channel_programs": programs,
        "matched_bank": None,
        "matched_gm_program": None,
        "match_mode": "fallback_sf2_musyng_kite_gm",
        "fallback": True,
        "fallback_reason": "mapping_missing",
        "selected_style_id": fallback_style.id,
        "selected_plugin_id": fallback_style.plugin_id,
        "mapping_source": str(instrument_mapping_path(config)),
    }


def _mapping_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InstrumentMappingError(f"{label} must be an object")
    return value


def _mapping_int(value: Any, label: str, fallback_values: tuple[Any, ...] = ()) -> int:
    values = (value, *fallback_values)
    for candidate in values:
        if candidate in (None, ""):
            continue
        try:
            return int(candidate)
        except (TypeError, ValueError):
            continue
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise InstrumentMappingError(f"{label} must be an integer") from exc


def _preset_relpaths(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    relpaths: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        relpath = str(item.get("relpath", "")).strip()
        if relpath:
            relpaths.append(relpath)
    return tuple(relpaths)


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


def _candidate_programs(programs: list[int]) -> list[tuple[int, str]]:
    candidates: list[tuple[int, str]] = []
    for program in programs:
        if 1 <= program <= 128:
            candidates.append((program - 1, "midi_payload_plus_one"))
        if 0 <= program <= 127:
            candidates.append((program, "direct"))
    return candidates


def _candidate_keys(
    programs: list[int],
    channel: int | None,
    bank_programs: list[dict[str, Any]] | None = None,
) -> list[tuple[int, int, str]]:
    keys: list[tuple[int, int, str]] = []
    if bank_programs:
        keys.extend(_candidate_bank_program_keys(bank_programs, channel))
    banks = (128, 0) if channel == 10 else (0,)
    for program, match_mode in _candidate_programs(programs):
        for bank in banks:
            keys.append((bank, program, match_mode))
    if channel == 10 and not programs:
        keys.append((128, 0, "channel_10_default_drum"))
    return _dedupe_keys(keys)


def _candidate_bank_program_keys(
    bank_programs: list[dict[str, Any]],
    channel: int | None,
) -> list[tuple[int, int, str]]:
    keys: list[tuple[int, int, str]] = []
    for event in bank_programs:
        if not isinstance(event, dict):
            continue
        try:
            gm_program = int(event.get("gm_program"))
        except (TypeError, ValueError):
            raw_program = event.get("program")
            try:
                gm_program = int(raw_program) - 1
            except (TypeError, ValueError):
                continue
        if gm_program < 0 or gm_program > 127:
            continue

        raw_banks = event.get("bank_candidates")
        if isinstance(raw_banks, list):
            bank_values = raw_banks
        else:
            bank_values = [event.get("bank")]

        banks: list[int] = []
        for raw_bank in bank_values:
            try:
                bank = int(raw_bank)
            except (TypeError, ValueError):
                continue
            if bank not in banks:
                banks.append(bank)
        if channel == 10:
            for drum_bank in (128, 0):
                if drum_bank not in banks:
                    banks.append(drum_bank)
        if not banks:
            banks.append(0)

        for bank in banks:
            keys.append((bank, gm_program, "bank_program_change"))
    return keys


def _dedupe_keys(keys: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    result: list[tuple[int, int, str]] = []
    seen: set[tuple[int, int]] = set()
    for bank, program, match_mode in keys:
        key = (bank, program)
        if key in seen:
            continue
        seen.add(key)
        result.append((bank, program, match_mode))
    return result


def _style_for_entry(config: ServiceConfig, entry: InstrumentMappingEntry) -> StyleProfile | None:
    if entry.plugin_id == "sf2_musyng_kite":
        return _enabled_style(config, "sf2_musyng_kite_gm")

    styles = [style for style in config.styles if style.enabled and style.plugin_id == entry.plugin_id]
    for style in styles:
        if _style_matches_preset(style, entry):
            return style
    for style in styles:
        if _style_matches_instrument(style, entry):
            return style
    return None


def _enabled_style(config: ServiceConfig, style_id: str) -> StyleProfile | None:
    style = config.get_style(style_id)
    if style is None or not style.enabled:
        return None
    return style


def _fallback_style(config: ServiceConfig) -> StyleProfile:
    style = _enabled_style(config, "sf2_musyng_kite_gm")
    if style is None:
        raise InstrumentMappingError("sf2_musyng_kite_gm fallback style is not available")
    return style


def _normalize_path(value: str) -> str:
    return value.strip().replace("\\", "/").lower()


def _style_matches_preset(style: StyleProfile, entry: InstrumentMappingEntry) -> bool:
    style_preset = _normalize_path(style.vst2_preset)
    if not style_preset:
        return False
    for preset in entry.preset_relpaths:
        mapping_preset = _normalize_path(preset)
        if mapping_preset.endswith(style_preset) or style_preset.endswith(mapping_preset):
            return True
    return False


def _normalize_label(value: str) -> str:
    return " ".join(value.replace("_", " ").split()).lower()


def _style_matches_instrument(style: StyleProfile, entry: InstrumentMappingEntry) -> bool:
    target_bank = _normalize_label(entry.target_bank)
    target_program = _normalize_label(entry.target_program)
    if target_bank and _normalize_label(style.instrument) != target_bank:
        return False
    if target_program and _normalize_label(style.articulation) == target_program:
        return True
    return False


def _match_info(
    *,
    entry: InstrumentMappingEntry,
    programs: list[int],
    bank: int,
    program: int,
    match_mode: str,
    fallback: bool,
    fallback_reason: str | None = None,
    fallback_style: StyleProfile | None = None,
) -> dict[str, object]:
    info: dict[str, object] = {
        "channel_programs": programs,
        "matched_bank": bank,
        "matched_gm_program": program,
        "matched_mapping_id": entry.id,
        "mapped_plugin_id": entry.plugin_id,
        "mapped_plugin_name": entry.plugin_name,
        "mapped_plugin_type": entry.plugin_type,
        "mapped_target_bank": entry.target_bank,
        "mapped_target_program": entry.target_program,
        "mapped_implementation": entry.implementation,
        "needs_confirmation": list(entry.needs_confirmation),
        "mapping_notes": list(entry.notes),
        "match_mode": match_mode,
        "fallback": fallback,
    }
    if fallback_reason:
        info["fallback_reason"] = fallback_reason
    if fallback_style is not None:
        info["selected_style_id"] = fallback_style.id
        info["selected_plugin_id"] = fallback_style.plugin_id
    return info
