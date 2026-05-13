<!--
/**
* File name: WINE_DOCKER.md
* Brief: MGSC DAW 项目文档
* Function:
*     记录云端 DAW 服务接口、部署、状态或开发规范
* Author: 软件工程架构组
*     MGSC AI Software Architecture group
* Version: V2.5.10
* Date: 2026/04/30
*/
-->

# Wine and Docker Migration Notes

## Target shape

The production image should run a Linux container on Ubuntu, with Wine providing the Windows runtime needed by Windows VST2/VST3 plugins. The API should stay the same as the Windows debug API.

Current prototype files:

```text
docker/wine/Dockerfile
docker/wine/compose.windows.yml
docker/wine/mgsc-daw-entrypoint.sh
docker/wine/wine-python
docker/wine/README_CN.md
config/plugins.wine.example.json
```

The first Wine prototype keeps FastAPI on Linux Python and runs only the Carla renderer through Wine + Windows embeddable Python. This is intentional: MIDI policy, zip handling, logs, and API stay native Linux, while Windows Carla DLL and Windows VST plugins run in Wine.

## Migration stages

1. Prove each plugin in Windows GUI.
2. Prove each plugin through `render_midi_to_mp3.py` on Windows.
3. Build a Linux Docker image with Wine, Linux Python for FastAPI, Windows embeddable Python for the renderer, Windows ffmpeg, Carla runtime files, and plugin assets mounted from local/private storage.
4. Mount Kong Audio into the Wine prefix and expose the Kong library as Wine drive `E:`.
5. Run the same `/mgsc_daw_service/v1/render` request in the container and compare output existence, duration, logs, and audible result.
6. Deploy the same image to Ubuntu and repeat the validation.

## Docker design constraints

Do not depend on a physical audio device. The renderer should write audio through Carla's Audio Recorder path and use a driver that works in the container. If DirectSound does not work under Wine, test Wine-compatible alternatives with a virtual audio backend before changing API code.

Keep plugin assets out of Git. Large installers, ISO files, sample libraries, and VST DLL/VST3 binaries should be supplied through a private artifact flow or mounted volume.

Keep one render per subprocess. VST plugins are not always stable under long-running server lifecycles, especially under Wine. Process isolation is slower but safer for the first production version.

## Wine path mode

Wine config uses:

```json
{
  "renderer_path_mode": "wine",
  "python": "/usr/local/bin/wine-python"
}
```

When `renderer_path_mode` is `wine`, the service converts Linux paths such as `/home/runtime/service_work/...` to Wine paths such as `Z:\home\runtime\service_work\...` before invoking `render_midi_to_mp3.py`. Renderer result paths are converted back to Linux paths so API download and file validation still work.

Plugin config uses two paths:

```json
{
  "path": "/wineprefix/drive_c/VSTPlugins/KongAudio/Qin_RV_x64.DLL",
  "runtime_path": "C:\\VSTPlugins\\KongAudio\\Qin_RV_x64.DLL"
}
```

`path` is the Linux path used by the service for existence checks. `runtime_path` is the Windows path passed to Carla inside Wine.

## Config split

Use separate configs:

```text
config/plugins.windows.example.json
config/plugins.local.json
config/plugins.wine.example.json
```

Only example configs should be committed. Local configs can contain machine-specific install paths and should remain ignored.
