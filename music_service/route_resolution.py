from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from fastapi import HTTPException

from .auto_routes import route_plugin
from .config import MidiPolicy, PluginProfile, ServiceConfig, StyleProfile
from .instrument_mapping import InstrumentMappingError, style_for_programs_from_mapping
from .request_config import first_present, optional_int, optional_string


def resolve_plugin_and_style(
    config: ServiceConfig,
    plugin_id: str | None,
    style_id: str | None,
) -> tuple[PluginProfile, StyleProfile | None]:
    if style_id:
        style = config.get_style(style_id)
        if style is None:
            raise HTTPException(status_code=404, detail=f"Unknown style: {style_id}")
        if not style.enabled:
            raise HTTPException(status_code=400, detail=f"Style is disabled: {style_id}")
        plugin = config.get_plugin(style.plugin_id)
        if plugin is None:
            raise HTTPException(status_code=500, detail=f"Style references missing plugin: {style.plugin_id}")
        if plugin_id and plugin_id != plugin.id:
            raise HTTPException(
                status_code=400,
                detail=f"Style {style_id} uses plugin {plugin.id}, not {plugin_id}",
            )
        return plugin, style

    if not plugin_id:
        raise HTTPException(status_code=400, detail="Either plugin_id or style_id is required")

    plugin = config.get_plugin(plugin_id)
    if plugin is None:
        raise HTTPException(status_code=404, detail=f"Unknown plugin: {plugin_id}")
    return plugin, None


def validate_midi_channel(value: int | None, label: str) -> int | None:
    if value is None:
        return None
    if value < 1 or value > 16:
        raise HTTPException(status_code=400, detail=f"{label} must be a MIDI channel from 1 to 16")
    return value


def build_effective_midi_policy(
    style: StyleProfile | None,
    apply_midi_policy: bool | None,
    midi_source_channel: int | None,
    midi_target_channel: int | None,
) -> MidiPolicy | None:
    source_channel = validate_midi_channel(midi_source_channel, "midi_source_channel")
    target_channel = validate_midi_channel(midi_target_channel, "midi_target_channel")
    base_policy = style.midi_policy if style else MidiPolicy()
    enabled = base_policy.enabled if apply_midi_policy is None else apply_midi_policy
    if not enabled:
        return None
    return replace(
        base_policy,
        enabled=True,
        source_channel=source_channel if source_channel is not None else base_policy.source_channel,
        target_channel=target_channel if target_channel is not None else base_policy.target_channel,
    )


def normalized_lookup_text(value: object) -> str:
    return re.sub(r"[^0-9a-z]+", "", str(value or "").casefold())


def optional_route_int(value: object) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def looks_like_drum_route(item: dict[str, Any]) -> bool:
    route_text = " ".join(
        str(item.get(key) or "")
        for key in ("track_name", "sf2_path", "vst_path", "patch", "patch_name", "param_key_name")
    )
    normalized_tokens = {
        token
        for token in re.split(r"[^0-9a-z]+", route_text.casefold())
        if token
    }
    compact_text = normalized_lookup_text(route_text)
    return (
        "drum" in compact_text
        or "drumkit" in compact_text
        or bool(normalized_tokens & {"kit", "rock"})
    )


def style_from_web_bank_patch(
    config: ServiceConfig,
    item: dict[str, Any],
) -> tuple[StyleProfile | None, dict[str, object] | None]:
    raw_bank = item.get("bank")
    raw_patch = first_present(item.get("patch"), item.get("program"), item.get("patch_name"))
    bank = optional_route_int(raw_bank)
    program = optional_route_int(raw_patch)
    if program is None and item.get("patch") not in (None, ""):
        program = optional_route_int(item.get("patch_name"))
    if program is None:
        return None, None

    bank_candidates: list[int] = []
    if looks_like_drum_route(item):
        bank_candidates.append(128)
    if bank is not None:
        bank_candidates.append(bank)
    bank_candidates.append(0)

    for bank_candidate in dict.fromkeys(bank_candidates):
        try:
            style, match = style_for_programs_from_mapping(
                config,
                [program],
                channel=10 if bank_candidate == 128 else None,
                bank_programs=[
                    {
                        "bank": bank_candidate,
                        "bank_candidates": [bank_candidate],
                        "program": program + 1,
                        "gm_program": program,
                    }
                ],
            )
        except InstrumentMappingError:
            continue
        if match.get("fallback"):
            continue
        return style, {
            **match,
            "source": "web_bank_patch",
            "web_bank": bank_candidate,
            "web_program": program,
        }
    return None, None


def style_from_legacy_vst_fields(
    config: ServiceConfig,
    *,
    vst_path: str | None,
    param_key_name: str | None,
) -> StyleProfile | None:
    normalized_vst_path = normalized_lookup_text(vst_path)
    normalized_param = normalized_lookup_text(param_key_name)
    if not normalized_vst_path and not normalized_param:
        return None

    best_match: tuple[int, StyleProfile] | None = None
    for style in config.styles:
        search_text = normalized_lookup_text(
            " ".join(
                [
                    style.id,
                    style.name,
                    style.instrument,
                    style.articulation,
                    style.vst2_preset,
                ]
            )
        )
        plugin = config.get_plugin(style.plugin_id)
        plugin_text = normalized_lookup_text(
            " ".join([plugin.id, plugin.name, str(plugin.path)]) if plugin else style.plugin_id
        )
        score = 0
        if normalized_param and normalized_param in search_text:
            score += 10
        if normalized_vst_path and (
            normalized_vst_path in search_text
            or normalized_vst_path in plugin_text
            or plugin_text in normalized_vst_path
        ):
            score += 5
        if score and (best_match is None or score > best_match[0]):
            best_match = (score, style)
    return best_match[1] if best_match else None


def style_from_legacy_sf2_fields(
    config: ServiceConfig,
    *,
    sf2_path: str | None,
    bank: object,
    patch: object,
) -> StyleProfile | None:
    normalized_sf2_path = normalized_lookup_text(sf2_path)
    for style in config.styles:
        plugin = config.get_plugin(style.plugin_id)
        if plugin is None or plugin.type != "sf2":
            continue
        style_text = normalized_lookup_text(" ".join([style.id, style.name, str(plugin.path)]))
        if normalized_sf2_path and normalized_sf2_path not in style_text:
            continue
        return style

    if not normalized_sf2_path and patch not in (None, ""):
        try:
            program = int(patch) + 1
            bank_value = int(bank) if bank not in (None, "") else 0
            style, _match = style_for_programs_from_mapping(
                config,
                [program],
                bank_programs=[{"bank": bank_value, "program": program}],
            )
            return style
        except (TypeError, ValueError, InstrumentMappingError):
            return None
    return None


def manual_track_key(item: dict[str, Any]) -> tuple[str, object] | None:
    track_id = optional_route_int(item.get("id"))
    if track_id is not None:
        return ("id", track_id)
    track_name = str(item.get("track_name") or "").strip()
    if track_name:
        return ("track_name", normalized_lookup_text(track_name))
    return None


def manual_track_priority(item: dict[str, Any]) -> tuple[int, int]:
    source = str(item.get("_manual_source") or "")
    source_rank = {"tracks": 3, "vst": 2, "sf2": 1}.get(source, 0)
    if item.get("style_id") not in (None, ""):
        return (100, source_rank)
    if item.get("plugin_id") not in (None, ""):
        return (90, source_rank)
    if optional_route_int(first_present(item.get("patch"), item.get("program"), item.get("patch_name"))) is not None:
        return (80, source_rank)
    if item.get("patch") not in (None, "") and optional_route_int(item.get("patch_name")) is not None:
        return (80, source_rank)
    if item.get("param_key_name") not in (None, "") or item.get("InstrumentList") not in (None, ""):
        return (60, source_rank)
    if item.get("vst_path") not in (None, ""):
        return (50, source_rank)
    if item.get("sf2_path") not in (None, ""):
        return (40, source_rank)
    return (0, source_rank)


def manual_track_items(config: dict[str, Any]) -> list[dict[str, Any]]:
    tracks: list[dict[str, Any]] = []
    for candidate in ("tracks", "vst", "sf2"):
        if candidate in config:
            raw_tracks = config.get(candidate)
            if raw_tracks is None:
                continue
            if not isinstance(raw_tracks, list):
                raise HTTPException(status_code=400, detail=f"conf.json {candidate} must be an array")
            for index, item in enumerate(raw_tracks):
                if not isinstance(item, dict):
                    raise HTTPException(status_code=400, detail=f"conf.json {candidate}[{index}] must be an object")
                track_item = dict(item)
                track_item["_manual_source"] = candidate
                track_item["_manual_index"] = len(tracks)
                tracks.append(track_item)

    selected_by_key: dict[tuple[str, object], dict[str, Any]] = {}
    result: list[dict[str, Any]] = []
    for item in tracks:
        key = manual_track_key(item)
        if key is None:
            result.append(item)
            continue
        current = selected_by_key.get(key)
        if current is None:
            selected_by_key[key] = item
            result.append(item)
            continue
        current_priority = manual_track_priority(current)
        item_priority = manual_track_priority(item)
        current_sources = list(current.get("_manual_duplicate_sources") or [current.get("_manual_source")])
        current_sources.append(item.get("_manual_source"))
        if item_priority > current_priority:
            item["_manual_duplicate_sources"] = current_sources
            selected_by_key[key] = item
            result[result.index(current)] = item
        else:
            current["_manual_duplicate_sources"] = current_sources
    return result


def build_manual_track_routes(
    config: ServiceConfig,
    bundle_config: dict[str, Any],
) -> list[dict[str, object]]:
    routes: list[dict[str, object]] = []
    for index, item in enumerate(manual_track_items(bundle_config)):
        manual_source = str(item.get("_manual_source") or "tracks")
        track_id = optional_int(item.get("id"), f"conf.json tracks[{index}].id")
        track_name = optional_string(item.get("track_name"), f"conf.json tracks[{index}].track_name")
        style_id = optional_string(item.get("style_id"), f"conf.json tracks[{index}].style_id")
        plugin_id = optional_string(item.get("plugin_id"), f"conf.json tracks[{index}].plugin_id")
        midi_source_channel = optional_int(
            first_present(item.get("midi_source_channel"), item.get("source_channel")),
            f"conf.json tracks[{index}].midi_source_channel",
        )
        midi_target_channel = optional_int(
            first_present(item.get("midi_target_channel"), item.get("target_channel")),
            f"conf.json tracks[{index}].midi_target_channel",
        )

        if style_id:
            style = config.get_style(style_id)
            if style is None:
                raise HTTPException(status_code=404, detail=f"Unknown style in tracks[{index}]: {style_id}")
            match_info: dict[str, object] = {"source": f"conf.json {manual_source}", "direct_style_id": style_id}
        else:
            style, match_info_or_none = style_from_web_bank_patch(config, item)
            match_info = match_info_or_none or {"source": f"conf.json {manual_source}"}
            if style is None:
                style = style_from_legacy_vst_fields(
                    config,
                    vst_path=optional_string(item.get("vst_path"), f"conf.json tracks[{index}].vst_path"),
                    param_key_name=optional_string(
                        first_present(item.get("param_key_name"), item.get("InstrumentList")),
                        f"conf.json tracks[{index}].param_key_name",
                    ),
                )
                if style is not None:
                    match_info["source"] = "legacy_vst_fields"
            if style is None and manual_source == "sf2":
                style = style_from_legacy_sf2_fields(
                    config,
                    sf2_path=optional_string(item.get("sf2_path"), f"conf.json tracks[{index}].sf2_path"),
                    bank=item.get("bank"),
                    patch=item.get("patch"),
                )
                if style is not None:
                    match_info["source"] = "legacy_sf2_fields"
            if style is None and plugin_id is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"conf.json {manual_source}[{index}] requires style_id, plugin_id, "
                        "web bank/patch, or recognizable legacy vst/sf2 fields"
                    ),
                )

        plugin, resolved_style = resolve_plugin_and_style(
            config,
            plugin_id=plugin_id,
            style_id=style.id if style else None,
        )
        if not plugin.enabled:
            raise HTTPException(status_code=400, detail=f"Plugin is disabled: {plugin.id}")
        if resolved_style is not None and not resolved_style.enabled:
            raise HTTPException(status_code=400, detail=f"Style is disabled: {resolved_style.id}")

        policy = build_effective_midi_policy(
            style=resolved_style,
            apply_midi_policy=True,
            midi_source_channel=midi_source_channel,
            midi_target_channel=midi_target_channel,
        )
        if policy is None:
            policy = MidiPolicy(enabled=True, source_channel=midi_source_channel, target_channel=midi_target_channel)
        routes.append(
            {
                "mode": "manual_track",
                "track_id": track_id,
                "track_name": track_name,
                "style": resolved_style,
                "plugin": plugin,
                "policy": policy,
                "match": {
                    **match_info,
                    "route_file": f"conf.json {manual_source}",
                    "route_sources": item.get("_manual_duplicate_sources") or [manual_source],
                    "legacy_vst_path": item.get("vst_path"),
                    "legacy_sf2_path": item.get("sf2_path"),
                    "legacy_param_key_name": item.get("param_key_name"),
                    "legacy_param_value_name": item.get("param_value_name"),
                    "legacy_bank": item.get("bank"),
                    "legacy_patch": item.get("patch"),
                    "legacy_patch_name": item.get("patch_name"),
                },
                "note_on_count": None,
                "note_tick_duration": None,
                "bank_programs": [],
                "track_names": [track_name] if track_name else [],
            }
        )
    return routes


def manual_route_log_summary(routes: list[dict[str, object]]) -> list[dict[str, object]]:
    def first_present(*values: object) -> object:
        for value in values:
            if value is not None:
                return value
        return None

    summary: list[dict[str, object]] = []
    for index, route in enumerate(routes, start=1):
        style = route.get("style")
        plugin = route_plugin(route)
        match = route.get("match")
        match_info = match if isinstance(match, dict) else {}
        item = {
            "index": index,
            "track_id": route.get("track_id"),
            "track_name": route.get("track_name"),
            "plugin_id": plugin.id,
            "style_id": style.id if isinstance(style, StyleProfile) else None,
            "bank": first_present(match_info.get("matched_bank"), match_info.get("web_bank")),
            "program": first_present(match_info.get("matched_gm_program"), match_info.get("web_program")),
            "mapping_id": match_info.get("matched_mapping_id"),
        }
        if match_info.get("fallback"):
            item["fallback"] = True
        channel = route.get("channel")
        if channel is not None:
            item["channel"] = channel
        summary.append({key: value for key, value in item.items() if value is not None})
    return summary
