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
class PluginProfile:
    id: str
    name: str
    type: str
    path: Path
    enabled: bool = True
    label: str = ""
    state: Path | None = None
    notes: str = ""


@dataclass(frozen=True)
class ServiceConfig:
    config_path: Path
    carla_root: Path
    python_executable: str
    ffmpeg: str | None
    output_dir: Path
    work_dir: Path
    render_timeout_seconds: int
    audio: AudioSettings
    plugins: tuple[PluginProfile, ...]

    def get_plugin(self, plugin_id: str) -> PluginProfile | None:
        for plugin in self.plugins:
            if plugin.id == plugin_id:
                return plugin
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
        if plugin_type not in {"vst2", "vst3"}:
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
                enabled=bool(plugin.get("enabled", True)),
                label=str(plugin.get("label", "")),
                state=state_path,
                notes=str(plugin.get("notes", "")),
            )
        )

    return tuple(plugins)


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

    return ServiceConfig(
        config_path=selected_path,
        carla_root=carla_root,
        python_executable=str(data.get("python", "python")),
        ffmpeg=data.get("ffmpeg"),
        output_dir=output_dir,
        work_dir=work_dir,
        render_timeout_seconds=int(data.get("render_timeout_seconds", 900)),
        audio=_load_audio(data),
        plugins=_load_plugins(data, config_dir),
    )

