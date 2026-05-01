# /**
# * File name: auto_routes.py
# * Brief: MGSC DAW 自动路由模块
# * Function:
# *     根据 MIDI Bank/Program 分析结果选择风格并生成多通道路由渲染计划
# * Author: 咪咕数创工程架构组
# *     MGSC AI Software Architecture group
# * Version: V2.5.10
# * Date: 2026/05/01
# */

from __future__ import annotations

from dataclasses import replace
from typing import Any

from fastapi import HTTPException

from .config import MidiPolicy, PluginProfile, ServiceConfig, StyleProfile
from .instrument_mapping import InstrumentMappingError, style_for_programs_from_mapping


def is_auto_style_request(style_id: str | None) -> bool:
    return bool(style_id and style_id.strip().lower() in {"auto", "__auto__"})


def style_for_programs(
    config: ServiceConfig,
    programs: list[int],
    channel: int | None = None,
    bank_programs: list[dict[str, Any]] | None = None,
) -> tuple[StyleProfile, dict[str, object]]:
    try:
        return style_for_programs_from_mapping(
            config,
            programs,
            channel=channel,
            bank_programs=bank_programs,
        )
    except InstrumentMappingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def selected_channel_programs(
    midi_channel_analysis: dict[str, object],
) -> tuple[int | None, list[int], list[dict[str, Any]]]:
    selected_channel = midi_channel_analysis.get("selected_source_channel")
    if not isinstance(selected_channel, int):
        return None, [], []

    for channel_info in midi_channel_analysis.get("channels", []):
        if not isinstance(channel_info, dict):
            continue
        if channel_info.get("channel") != selected_channel:
            continue
        programs = [
            int(program)
            for program in channel_info.get("programs", [])
            if isinstance(program, int)
        ]
        bank_programs = [
            event
            for event in channel_info.get("bank_programs", [])
            if isinstance(event, dict)
        ]
        return selected_channel, programs, bank_programs
    return selected_channel, [], []


def resolve_auto_style(
    config: ServiceConfig,
    midi_channel_analysis: dict[str, object],
) -> tuple[StyleProfile, dict[str, object]]:
    selected_channel, programs, bank_programs = selected_channel_programs(midi_channel_analysis)
    style, match = style_for_programs(
        config,
        programs,
        channel=selected_channel,
        bank_programs=bank_programs,
    )
    return style, {
        "enabled": True,
        "selected_style_id": style.id,
        "selected_plugin_id": style.plugin_id,
        "selected_source_channel": selected_channel,
        **match,
    }


def auto_route_policy(style: StyleProfile, channel: int) -> MidiPolicy:
    if style.id == "sf2_musyng_kite_gm":
        return MidiPolicy(
            enabled=True,
            source_channel=channel,
            target_channel=channel,
            remove_program_changes=False,
            remove_bank_select=False,
            keep_control_changes=tuple(range(128)),
            keep_pitch_bend=True,
            keep_note_aftertouch=True,
            keep_channel_pressure=True,
            keep_sysex=False,
        )
    return replace(
        style.midi_policy,
        enabled=True,
        source_channel=channel,
        target_channel=style.midi_policy.target_channel or 1,
    )


def build_auto_render_routes(
    config: ServiceConfig,
    midi_channel_analysis: dict[str, object],
) -> list[dict[str, object]]:
    routes: list[dict[str, object]] = []
    for channel_info in midi_channel_analysis.get("channels", []):
        if not isinstance(channel_info, dict):
            continue
        try:
            channel = int(channel_info.get("channel"))
            note_on_count = int(channel_info.get("note_on_count") or 0)
        except (TypeError, ValueError):
            continue
        if channel < 1 or channel > 16 or note_on_count <= 0:
            continue

        programs = [
            int(program)
            for program in channel_info.get("programs", [])
            if isinstance(program, int)
        ]
        bank_programs = [
            event
            for event in channel_info.get("bank_programs", [])
            if isinstance(event, dict)
        ]
        style, match = style_for_programs(
            config,
            programs,
            channel=channel,
            bank_programs=bank_programs,
        )
        plugin = config.get_plugin(style.plugin_id)
        if plugin is None:
            raise HTTPException(status_code=500, detail=f"Style references missing plugin: {style.plugin_id}")
        if not plugin.enabled:
            raise HTTPException(status_code=400, detail=f"Plugin is disabled: {plugin.id}")
        routes.append(
            {
                "channel": channel,
                "style": style,
                "plugin": plugin,
                "policy": auto_route_policy(style, channel),
                "match": match,
                "note_on_count": note_on_count,
                "note_tick_duration": channel_info.get("note_tick_duration"),
                "bank_programs": bank_programs,
                "track_names": channel_info.get("track_names", []),
            }
        )

    if not routes:
        raise HTTPException(status_code=400, detail="Auto route did not find any MIDI channels with notes")
    return routes


def route_style(route: dict[str, object]) -> StyleProfile:
    style = route["style"]
    if not isinstance(style, StyleProfile):
        raise TypeError("Auto route style is invalid")
    return style


def route_plugin(route: dict[str, object]) -> PluginProfile:
    plugin = route["plugin"]
    if not isinstance(plugin, PluginProfile):
        raise TypeError("Auto route plugin is invalid")
    return plugin


def route_policy(route: dict[str, object]) -> MidiPolicy:
    policy = route["policy"]
    if not isinstance(policy, MidiPolicy):
        raise TypeError("Auto route MIDI policy is invalid")
    return policy
