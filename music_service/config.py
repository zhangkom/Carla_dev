# /**
# * File name: config.py
# * Brief: MGSC DAW 渲染服务模块
# * Function:
# *     提供 FastAPI 渲染接口、音源配置、MIDI 策略和渲染调度能力
# * Author: 软件工程架构组
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


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class AudioSettings:
    driver: str = "DirectSound"
    device: str = "Primary Sound Driver"
    buffer_size: int = 512
    sample_rate: int = 44100


@dataclass(frozen=True)
class EncodingSettings:
    mp3_mode: str = "cbr"
    mp3_bitrate: str = "320k"
    mp3_sample_rate: int | None = None
    mp3_channels: int = 2
    mp3_quality: int = 2
    mp3_compression_level: int = 7
    mp3_id3v2_version: int = 3


@dataclass(frozen=True)
class PluginProfile:
    id: str
    name: str
    type: str
    path: Path
    runtime_path: str | None = None
    enabled: bool = True
    label: str = ""
    state: Path | None = None
    notes: str = ""


@dataclass(frozen=True)
class ParameterOverride:
    index: int
    value: float
    name: str = ""


@dataclass(frozen=True)
class MidiPolicy:
    enabled: bool = False
    source_channel: int | None = None
    target_channel: int | None = None
    remove_program_changes: bool = True
    remove_bank_select: bool = True
    keep_control_changes: tuple[int, ...] = (1, 7, 10, 11, 64)
    keep_pitch_bend: bool = True
    keep_note_aftertouch: bool = True
    keep_channel_pressure: bool = True
    keep_sysex: bool = False
    notes: str = ""


@dataclass(frozen=True)
class StyleProfile:
    id: str
    plugin_id: str
    name: str
    instrument: str = ""
    articulation: str = ""
    enabled: bool = True
    state: Path | None = None
    vst2_preset: str = ""
    gm_programs: tuple[int, ...] = ()
    parameters: tuple[ParameterOverride, ...] = ()
    midi_policy: MidiPolicy = MidiPolicy()
    notes: str = ""


@dataclass(frozen=True)
class ServiceConfig:
    config_path: Path
    carla_root: Path
    carla_backend: Path | None
    carla_bin_dir: Path | None
    carla_resources_dir: Path | None
    carla_frontend_dir: Path | None
    python_executable: str
    ffmpeg: str | None
    output_dir: Path
    work_dir: Path
    renderer_path_mode: str
    plugin_load_mode: str
    render_timeout_seconds: int
    audio: AudioSettings
    encoding: EncodingSettings
    plugins: tuple[PluginProfile, ...]
    styles: tuple[StyleProfile, ...]

    def get_plugin(self, plugin_id: str) -> PluginProfile | None:
        for plugin in self.plugins:
            if plugin.id == plugin_id:
                return plugin
        return None

    def get_style(self, style_id: str) -> StyleProfile | None:
        for style in self.styles:
            if style.id == style_id:
                return style
        return None


def default_config_path() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / "config" / "plugins.windows.example.json"


def _resolve_path(value: str | None, base_dir: Path) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{label} must be an object")
    return value


def _load_audio(data: dict[str, Any]) -> AudioSettings:
    audio = _require_mapping(data.get("audio", {}), "audio")
    return AudioSettings(
        driver=str(audio.get("driver", "DirectSound")),
        device=str(audio.get("device", "Primary Sound Driver")),
        buffer_size=int(audio.get("buffer_size", 512)),
        sample_rate=int(audio.get("sample_rate", 44100)),
    )


def _load_encoding(data: dict[str, Any]) -> EncodingSettings:
    encoding = _require_mapping(data.get("encoding", {}), "encoding")
    mp3_mode = str(encoding.get("mp3_mode", "cbr")).strip().lower()
    if mp3_mode not in {"cbr", "vbr"}:
        raise ConfigError("encoding.mp3_mode must be cbr or vbr")

    mp3_sample_rate = encoding.get("mp3_sample_rate")
    if mp3_sample_rate in (None, ""):
        parsed_mp3_sample_rate = None
    else:
        parsed_mp3_sample_rate = int(mp3_sample_rate)
        if parsed_mp3_sample_rate <= 0:
            raise ConfigError("encoding.mp3_sample_rate must be greater than 0")

    mp3_channels = int(encoding.get("mp3_channels", 2))
    if mp3_channels not in {1, 2}:
        raise ConfigError("encoding.mp3_channels must be 1 or 2")

    mp3_quality = int(encoding.get("mp3_quality", 2))
    if mp3_quality < 0 or mp3_quality > 9:
        raise ConfigError("encoding.mp3_quality must be between 0 and 9")

    mp3_compression_level = int(encoding.get("mp3_compression_level", 7))
    if mp3_compression_level < 0 or mp3_compression_level > 9:
        raise ConfigError("encoding.mp3_compression_level must be between 0 and 9")

    mp3_id3v2_version = int(encoding.get("mp3_id3v2_version", 3))
    if mp3_id3v2_version not in {3, 4}:
        raise ConfigError("encoding.mp3_id3v2_version must be 3 or 4")

    return EncodingSettings(
        mp3_mode=mp3_mode,
        mp3_bitrate=str(encoding.get("mp3_bitrate", "320k")),
        mp3_sample_rate=parsed_mp3_sample_rate,
        mp3_channels=mp3_channels,
        mp3_quality=mp3_quality,
        mp3_compression_level=mp3_compression_level,
        mp3_id3v2_version=mp3_id3v2_version,
    )


def _load_plugins(data: dict[str, Any], base_dir: Path) -> tuple[PluginProfile, ...]:
    raw_plugins = data.get("plugins", [])
    if not isinstance(raw_plugins, list):
        raise ConfigError("plugins must be an array")

    plugins: list[PluginProfile] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_plugins):
        plugin = _require_mapping(item, f"plugins[{index}]")
        plugin_id = str(plugin.get("id", "")).strip()
        if not plugin_id:
            raise ConfigError(f"plugins[{index}].id is required")
        if plugin_id in seen:
            raise ConfigError(f"Duplicate plugin id: {plugin_id}")
        seen.add(plugin_id)

        plugin_type = str(plugin.get("type", "")).strip().lower()
        if plugin_type not in {"vst2", "vst3", "sf2"}:
            raise ConfigError(f"Plugin {plugin_id} has unsupported type: {plugin_type}")

        plugin_path = _resolve_path(str(plugin.get("path", "")), base_dir)
        if plugin_path is None:
            raise ConfigError(f"Plugin {plugin_id} path is required")

        state_path = _resolve_path(plugin.get("state"), base_dir)
        plugins.append(
            PluginProfile(
                id=plugin_id,
                name=str(plugin.get("name") or plugin_path.stem),
                type=plugin_type,
                path=plugin_path,
                runtime_path=str(plugin.get("runtime_path", "")).strip() or None,
                enabled=bool(plugin.get("enabled", True)),
                label=str(plugin.get("label", "")),
                state=state_path,
                notes=str(plugin.get("notes", "")),
            )
        )

    return tuple(plugins)


def _load_parameter_overrides(value: Any, label: str) -> tuple[ParameterOverride, ...]:
    if value in (None, ""):
        return ()

    parameters: list[ParameterOverride] = []
    if isinstance(value, dict):
        iterable = [
            {"index": raw_index, "value": raw_value}
            for raw_index, raw_value in value.items()
        ]
    elif isinstance(value, list):
        iterable = value
    else:
        raise ConfigError(f"{label} must be an array or object")

    for index, item in enumerate(iterable):
        parameter = _require_mapping(item, f"{label}[{index}]")
        try:
            parameter_index = int(parameter["index"])
            parameter_value = float(parameter["value"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigError(f"{label}[{index}] requires numeric index and value") from exc
        if parameter_index < 0:
            raise ConfigError(f"{label}[{index}].index must be >= 0")
        parameters.append(
            ParameterOverride(
                index=parameter_index,
                value=parameter_value,
                name=str(parameter.get("name", "")),
            )
        )

    return tuple(parameters)


def _load_optional_channel(value: Any, label: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        channel = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{label} must be a MIDI channel from 1 to 16") from exc
    if channel < 1 or channel > 16:
        raise ConfigError(f"{label} must be a MIDI channel from 1 to 16")
    return channel


def _load_cc_list(value: Any, label: str) -> tuple[int, ...]:
    if value in (None, ""):
        return (1, 7, 10, 11, 64)
    if not isinstance(value, list):
        raise ConfigError(f"{label} must be an array")
    controllers: list[int] = []
    for index, item in enumerate(value):
        try:
            controller = int(item)
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{label}[{index}] must be a MIDI CC number") from exc
        if controller < 0 or controller > 127:
            raise ConfigError(f"{label}[{index}] must be between 0 and 127")
        controllers.append(controller)
    return tuple(controllers)


def _load_gm_programs(value: Any, label: str) -> tuple[int, ...]:
    if value in (None, ""):
        return ()
    if not isinstance(value, list):
        raise ConfigError(f"{label} must be an array")
    programs: list[int] = []
    for index, item in enumerate(value):
        try:
            program = int(item)
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{label}[{index}] must be a GM program number") from exc
        if program < 0 or program > 127:
            raise ConfigError(f"{label}[{index}] must be between 0 and 127")
        if program not in programs:
            programs.append(program)
    return tuple(programs)


def _load_midi_policy(value: Any, label: str) -> MidiPolicy:
    if value in (None, ""):
        return MidiPolicy()
    policy = _require_mapping(value, label)
    return MidiPolicy(
        enabled=bool(policy.get("enabled", False)),
        source_channel=_load_optional_channel(policy.get("source_channel"), f"{label}.source_channel"),
        target_channel=_load_optional_channel(policy.get("target_channel"), f"{label}.target_channel"),
        remove_program_changes=bool(policy.get("remove_program_changes", True)),
        remove_bank_select=bool(policy.get("remove_bank_select", True)),
        keep_control_changes=_load_cc_list(policy.get("keep_control_changes"), f"{label}.keep_control_changes"),
        keep_pitch_bend=bool(policy.get("keep_pitch_bend", True)),
        keep_note_aftertouch=bool(policy.get("keep_note_aftertouch", True)),
        keep_channel_pressure=bool(policy.get("keep_channel_pressure", True)),
        keep_sysex=bool(policy.get("keep_sysex", False)),
        notes=str(policy.get("notes", "")),
    )


def _load_styles(
    data: dict[str, Any],
    base_dir: Path,
    plugins: tuple[PluginProfile, ...],
) -> tuple[StyleProfile, ...]:
    raw_styles = data.get("styles", [])
    if not isinstance(raw_styles, list):
        raise ConfigError("styles must be an array")

    plugin_ids = {plugin.id for plugin in plugins}
    styles: list[StyleProfile] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_styles):
        style = _require_mapping(item, f"styles[{index}]")
        style_id = str(style.get("id", "")).strip()
        if not style_id:
            raise ConfigError(f"styles[{index}].id is required")
        if style_id in seen:
            raise ConfigError(f"Duplicate style id: {style_id}")
        seen.add(style_id)

        plugin_id = str(style.get("plugin_id", "")).strip()
        if not plugin_id:
            raise ConfigError(f"styles[{index}].plugin_id is required")
        if plugin_id not in plugin_ids:
            raise ConfigError(f"Style {style_id} references unknown plugin: {plugin_id}")

        state_path = _resolve_path(style.get("state"), base_dir)
        styles.append(
            StyleProfile(
                id=style_id,
                plugin_id=plugin_id,
                name=str(style.get("name") or style_id),
                instrument=str(style.get("instrument", "")),
                articulation=str(style.get("articulation", "")),
                enabled=bool(style.get("enabled", True)),
                state=state_path,
                vst2_preset=str(style.get("vst2_preset", "")).strip(),
                gm_programs=_load_gm_programs(
                    style.get("gm_programs"),
                    f"styles[{index}].gm_programs",
                ),
                parameters=_load_parameter_overrides(
                    style.get("parameters"),
                    f"styles[{index}].parameters",
                ),
                midi_policy=_load_midi_policy(
                    style.get("midi_policy"),
                    f"styles[{index}].midi_policy",
                ),
                notes=str(style.get("notes", "")),
            )
        )

    return tuple(styles)


def load_config(config_path: str | os.PathLike[str] | None = None) -> ServiceConfig:
    selected_path = Path(
        config_path or os.environ.get("MUSIC_SERVICE_CONFIG") or default_config_path()
    ).expanduser()
    selected_path = selected_path.resolve()
    if not selected_path.is_file():
        raise ConfigError(f"Config file not found: {selected_path}")

    with selected_path.open("r", encoding="utf-8") as handle:
        data = _require_mapping(json.load(handle), "config")

    config_dir = selected_path.parent
    carla_root = _resolve_path(str(data.get("carla_root", ".")), config_dir)
    if carla_root is None:
        raise ConfigError("carla_root is required")

    output_dir = _resolve_path(str(data.get("output_dir", "output/service")), carla_root)
    work_dir = _resolve_path(str(data.get("work_dir", "service_work")), carla_root)
    if output_dir is None or work_dir is None:
        raise ConfigError("output_dir and work_dir are required")

    renderer_path_mode = str(data.get("renderer_path_mode", "native")).strip().lower()
    if renderer_path_mode not in {"native", "wine", "native_bridge"}:
        raise ConfigError("renderer_path_mode must be native, wine, or native_bridge")

    plugin_load_mode = str(
        data.get("plugin_load_mode") or ("load_file" if renderer_path_mode == "native_bridge" else "add_plugin")
    ).strip().lower()
    if plugin_load_mode not in {"add_plugin", "load_file"}:
        raise ConfigError("plugin_load_mode must be add_plugin or load_file")

    plugins = _load_plugins(data, config_dir)
    styles = _load_styles(data, carla_root, plugins)

    return ServiceConfig(
        config_path=selected_path,
        carla_root=carla_root,
        carla_backend=_resolve_path(data.get("carla_backend"), carla_root),
        carla_bin_dir=_resolve_path(data.get("carla_bin_dir"), carla_root),
        carla_resources_dir=_resolve_path(data.get("carla_resources_dir"), carla_root),
        carla_frontend_dir=_resolve_path(data.get("carla_frontend_dir"), carla_root),
        python_executable=str(data.get("python", "python")),
        ffmpeg=data.get("ffmpeg"),
        output_dir=output_dir,
        work_dir=work_dir,
        renderer_path_mode=renderer_path_mode,
        plugin_load_mode=plugin_load_mode,
        render_timeout_seconds=int(data.get("render_timeout_seconds", 900)),
        audio=_load_audio(data),
        encoding=_load_encoding(data),
        plugins=plugins,
        styles=styles,
    )
