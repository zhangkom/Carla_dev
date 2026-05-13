<!--
/**
* File name: MUSIC_SERVICE_PLAN.md
* Brief: MGSC DAW 项目文档
* Function:
*     记录云端 DAW 服务接口、部署、状态或开发规范
* Author: 软件工程架构组
*     MGSC AI Software Architecture group
* Version: V2.5.10
* Date: 2026/04/30
*/
-->

# Carla Music Service Plan

## Recommendation

Use this order:

1. Debug on Windows with the Carla GUI and local plugin installs.
2. Move the working chain into the headless Windows renderer/API path.
3. Reproduce the same chain inside a Linux Docker image with Wine.
4. Deploy that Docker image on Ubuntu after the Wine image can render the same MIDI outputs.

Do not start by directly moving development to native Ubuntu. Most target plugins are Windows VST2/VST3 binaries, and Kong Audio also depends on installer side effects such as installed files, registry entries, content paths, and possibly fonts/runtime DLLs. Debugging those variables directly in Ubuntu/Wine would mix plugin installation problems, Wine problems, Carla problems, and API problems in one step.

## Why Windows first

Windows GUI validation gives a known-good baseline: the plugin loads, presets/content paths are correct, MIDI reaches the instrument, and audio renders correctly. Once that is true, the GUI can be removed from the runtime path and the same plugin profile can be loaded by `render_midi_to_mp3.py`.

The existing `run_carla_gui.bat` starts the GUI, and `render_midi_to_mp3.py` now supports generic VST2/VST3 plugin arguments. The FastAPI service wraps the renderer as a subprocess per request, so a plugin crash does not kill the API process.

## GUI-to-API style model

Use the GUI to author stable styles, then expose those styles through the API. A style should contain the plugin id, the `.carxs` state saved from Carla GUI, and only the numeric parameter overrides that are safe to change after loading that state.

For Kong Qin_RV, use the GUI to choose the instrument and preset, confirm sound, and save that configured plugin state. The API should call it by `style_id` instead of trying to drive Kong's browser UI at render time.

MIDI files are preprocessed for style-based rendering. Program Change and Bank Select are removed because the API style already selects the VST instrument/articulation. Performance controls such as velocity, ModWheel, expression, sustain, and Pitch Bend are preserved so the generated MP3 keeps musical phrasing where the target plugin supports it.

## Current Windows flow

Install service dependencies:

```powershell
python -m pip install -r requirements-service.txt
```

Start the API:

```bat
run_music_service_windows.bat
```

List configured plugins:

```powershell
curl http://127.0.0.1:8000/v1/plugins
```

Render a MIDI file:

```powershell
curl.exe -X POST http://127.0.0.1:8000/v1/render `
  -F "style_id=surge_xt_default" `
  -F "midi=@C:\path\to\example.mid"
```

## Plugin asset policy

Do not commit plugin binaries, installers, SoundFonts, sample libraries, generated WAV/MP3 files, or Kong Audio ISO content to Git. Keep them as local runtime assets or mount them into Docker images/containers through a private artifact process.

For Kong Audio, use:

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\kong_audio\qin_rv_v2_2\installer
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\kong_audio\qin_rv_v2_2\library
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\kong_audio\qin_rv_v2_2\vst2
```

Do not use these as the source input for Kong setup:

```text
Any copied installer payload directory outside mgsc_daw_assets\kong_audio\qin_rv_v2_2.
```

Those look like files produced by a previous install or extracted install payloads, not the canonical install source.
