# Wine and Docker Migration Notes

## Target shape

The production image should run a Linux container on Ubuntu, with Wine providing the Windows runtime needed by Windows VST2/VST3 plugins. The API should stay the same as the Windows debug API.

## Migration stages

1. Prove each plugin in Windows GUI.
2. Prove each plugin through `render_midi_to_mp3.py` on Windows.
3. Build a Linux Docker image with Wine, Python, ffmpeg, Carla runtime files, and plugin assets mounted or copied from a private artifact store.
4. Install Kong Audio inside the Wine prefix from the official local installer directory, then snapshot or rebuild the prefix reproducibly.
5. Run the same `/v1/render` request in the container and compare output existence, duration, and audible result.
6. Deploy the working image to Ubuntu.

## Docker design constraints

Do not depend on a physical audio device. The renderer should write audio through Carla's Audio Recorder path and use a driver that works in the container. If DirectSound does not work under Wine, test Wine-compatible alternatives with a virtual audio backend before changing API code.

Keep plugin assets out of Git. Large installers, ISO files, sample libraries, and VST DLL/VST3 binaries should be supplied through a private artifact flow or mounted volume.

Keep one render per subprocess. VST plugins are not always stable under long-running server lifecycles, especially under Wine. Process isolation is slower but safer for the first production version.

## Config split

Use separate configs:

```text
config/plugins.windows.example.json
config/plugins.local.json
config/plugins.wine.example.json
```

Only example configs should be committed. Local configs can contain machine-specific install paths and should remain ignored.

