from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any

from fastapi import HTTPException

from .config import ServiceConfig


def first_present(*values: object) -> object | None:
    for value in values:
        if value is not None:
            return value
    return None


def optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{label} must be a string")
    stripped = value.strip()
    return stripped or None


def optional_bool(value: object, label: str) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
    raise HTTPException(status_code=400, detail=f"{label} must be a boolean")


def optional_int(value: object, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"{label} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{label} must be an integer") from exc


def optional_float(value: object, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"{label} must be a number")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{label} must be a number") from exc


def read_conf_json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        decoded = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(decoded, dict):
        raise HTTPException(status_code=400, detail=f"{label} must be a JSON object")
    return decoded


def mapping_section(config: dict[str, Any], key: str) -> dict[str, Any]:
    value = config.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail=f"conf.json field {key} must be an object")
    return value


def optional_mp3_bitrate(value: object, label: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"{label} must be a bitrate number or string")
    if isinstance(value, (int, float)):
        if value <= 0:
            raise HTTPException(status_code=400, detail=f"{label} must be greater than 0")
        return f"{int(value)}k"
    if isinstance(value, str):
        stripped = value.strip().lower()
        if not re.fullmatch(r"\d+[km]?", stripped):
            raise HTTPException(status_code=400, detail=f"{label} must be like 320 or 320k")
        return stripped if stripped[-1] in {"k", "m"} else f"{stripped}k"
    raise HTTPException(status_code=400, detail=f"{label} must be a bitrate number or string")


def optional_mp3_mode(value: object, label: str) -> str | None:
    if value is None:
        return None
    mode = optional_string(value, label)
    if mode is None:
        return None
    normalized = mode.strip().lower()
    if normalized not in {"cbr", "vbr"}:
        raise HTTPException(status_code=400, detail=f"{label} must be cbr or vbr")
    return normalized


def optional_int_range(value: object, label: str, minimum: int, maximum: int) -> int | None:
    parsed = optional_int(value, label)
    if parsed is None:
        return None
    if parsed < minimum or parsed > maximum:
        raise HTTPException(status_code=400, detail=f"{label} must be between {minimum} and {maximum}")
    return parsed


def apply_conf_render_options(
    config: ServiceConfig,
    request_config: dict[str, Any],
) -> tuple[ServiceConfig, dict[str, object]]:
    render_config = mapping_section(request_config, "render")
    output_config = mapping_section(request_config, "output")

    output_format = (optional_string(render_config.get("format"), "conf.json render.format") or "mp3").lower()
    if output_format != "mp3":
        raise HTTPException(status_code=400, detail="conf.json render.format currently only supports mp3")

    bitrate = optional_mp3_bitrate(render_config.get("bitrate"), "conf.json render.bitrate")
    mp3_mode = optional_mp3_mode(
        first_present(render_config.get("mp3_mode"), render_config.get("bitrate_mode")),
        "conf.json render.mp3_mode",
    )
    mp3_quality = optional_int_range(
        first_present(render_config.get("mp3_quality"), render_config.get("quality")),
        "conf.json render.mp3_quality",
        0,
        9,
    )
    mp3_compression_level = optional_int_range(
        first_present(render_config.get("mp3_compression_level"), render_config.get("compression_level")),
        "conf.json render.mp3_compression_level",
        0,
        9,
    )
    bit_depth = optional_int(render_config.get("bit_depth"), "conf.json render.bit_depth")
    if bit_depth is not None and bit_depth != 16:
        raise HTTPException(status_code=400, detail="conf.json render.bit_depth currently only supports 16")

    loop = optional_bool(render_config.get("loop"), "conf.json render.loop")
    samplerate = optional_int(
        first_present(output_config.get("samplerate"), output_config.get("sample_rate")),
        "conf.json output.samplerate",
    )
    if samplerate is not None and samplerate <= 0:
        raise HTTPException(status_code=400, detail="conf.json output.samplerate must be greater than 0")

    effective_audio = config.audio
    effective_encoding = config.encoding
    if samplerate is not None:
        effective_audio = replace(effective_audio, sample_rate=samplerate)
        effective_encoding = replace(effective_encoding, mp3_sample_rate=samplerate)
    if bitrate is not None:
        effective_encoding = replace(effective_encoding, mp3_bitrate=bitrate)
    if mp3_mode is not None:
        effective_encoding = replace(effective_encoding, mp3_mode=mp3_mode)
    if mp3_quality is not None:
        effective_encoding = replace(effective_encoding, mp3_quality=mp3_quality)
    if mp3_compression_level is not None:
        effective_encoding = replace(effective_encoding, mp3_compression_level=mp3_compression_level)

    effective_config = replace(config, audio=effective_audio, encoding=effective_encoding)
    return effective_config, {
        "format": output_format,
        "bitrate": bitrate or effective_config.encoding.mp3_bitrate,
        "mp3_mode": effective_config.encoding.mp3_mode,
        "mp3_quality": effective_config.encoding.mp3_quality,
        "mp3_compression_level": effective_config.encoding.mp3_compression_level,
        "bit_depth": bit_depth or 16,
        "loop": False if loop is None else loop,
        "samplerate": samplerate or effective_config.audio.sample_rate,
    }


def conf_debug_enabled(config: dict[str, Any]) -> bool:
    render_config = mapping_section(config, "render")
    diagnostics_config = mapping_section(config, "diagnostics")
    raw_value = first_present(
        config.get("debug"),
        render_config.get("debug"),
        diagnostics_config.get("debug"),
        diagnostics_config.get("enabled"),
    )
    return bool(optional_bool(raw_value, "conf.json debug"))


def public_render_response(payload: dict[str, object], *, debug_enabled: bool) -> dict[str, object]:
    payload.setdefault("http_code", 200)
    payload.setdefault("status", "success")
    payload.setdefault("error", None)
    payload["debug"] = debug_enabled
    if debug_enabled:
        return payload

    public_payload = {
        key: payload[key]
        for key in (
            "http_code",
            "status",
            "error",
            "job_id",
            "plugin_id",
            "style_id",
            "output_basename",
            "elapsed_seconds",
        )
        if key in payload
    }
    mp3_file = payload.get("mp3_file")
    if isinstance(mp3_file, dict) and isinstance(mp3_file.get("base64"), str):
        public_payload["mp3_file"] = {"base64": mp3_file["base64"]}
    return public_payload


def route_config_summary(config: dict[str, Any]) -> dict[str, object]:
    render_config = config.get("render") if isinstance(config.get("render"), dict) else {}
    midi_config = config.get("midi") if isinstance(config.get("midi"), dict) else {}
    summary: dict[str, object] = {
        "top_level_keys": sorted(str(key) for key in config.keys()),
        "plugin_id": config.get("plugin_id"),
        "style_id": config.get("style_id"),
        "style_name": config.get("style_name"),
        "debug": config.get("debug"),
        "tracks_count": len(config.get("tracks") or []) if isinstance(config.get("tracks"), list) else 0,
        "vst_count": len(config.get("vst") or []) if isinstance(config.get("vst"), list) else 0,
        "sf2_count": len(config.get("sf2") or []) if isinstance(config.get("sf2"), list) else 0,
        "vst_conf": first_present(config.get("vstConf"), config.get("vst_conf"), config.get("vst_json")),
        "sf2_conf": first_present(config.get("sf2Conf"), config.get("sf2_conf"), config.get("sf2_json")),
    }
    if render_config:
        summary["render"] = {
            key: render_config.get(key)
            for key in (
                "format",
                "bitrate",
                "mp3_mode",
                "bitrate_mode",
                "mp3_quality",
                "quality",
                "mp3_compression_level",
                "compression_level",
                "bit_depth",
                "samplerate",
                "sample_rate",
                "loop",
                "max_seconds",
                "debug",
            )
            if key in render_config
        }
    if midi_config:
        summary["midi"] = {
            key: midi_config.get(key)
            for key in ("apply_policy", "source_channel", "target_channel")
            if key in midi_config
        }
    return summary


def apply_conf_defaults(
    config: dict[str, Any],
    *,
    plugin_id: str | None,
    style_id: str | None,
    style_name: str | None,
    max_seconds: float | None,
    apply_midi_policy: bool | None,
    midi_source_channel: int | None,
    midi_target_channel: int | None,
) -> tuple[str | None, str | None, str | None, float | None, bool | None, int | None, int | None]:
    midi_config = mapping_section(config, "midi")
    render_config = mapping_section(config, "render")

    plugin_id = plugin_id or optional_string(config.get("plugin_id"), "conf.json plugin_id")
    style_id = style_id or optional_string(config.get("style_id"), "conf.json style_id")
    style_name = style_name or optional_string(config.get("style_name"), "conf.json style_name")
    max_seconds = max_seconds if max_seconds is not None else optional_float(
        first_present(config.get("max_seconds"), render_config.get("max_seconds")),
        "conf.json max_seconds",
    )
    apply_midi_policy = apply_midi_policy if apply_midi_policy is not None else optional_bool(
        first_present(config.get("apply_midi_policy"), midi_config.get("apply_midi_policy"), midi_config.get("apply_policy")),
        "conf.json apply_midi_policy",
    )
    midi_source_channel = midi_source_channel if midi_source_channel is not None else optional_int(
        first_present(config.get("midi_source_channel"), midi_config.get("source_channel")),
        "conf.json midi_source_channel",
    )
    midi_target_channel = midi_target_channel if midi_target_channel is not None else optional_int(
        first_present(config.get("midi_target_channel"), midi_config.get("target_channel")),
        "conf.json midi_target_channel",
    )
    return (
        plugin_id,
        style_id,
        style_name,
        max_seconds,
        apply_midi_policy,
        midi_source_channel,
        midi_target_channel,
    )
