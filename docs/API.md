# Music Service API

Base URL for local Windows debugging:

```text
http://127.0.0.1:8000
```

## Health

```http
GET /health
```

Response:

```json
{
  "status": "ok",
  "config": "C:\\...\\config\\plugins.windows.example.json"
}
```

## List Plugins

```http
GET /v1/plugins
```

Returns configured plugin profiles. Disabled profiles are visible but cannot render until enabled in config.

## Encoding

Default output encoding is tuned for broad player compatibility:

```text
MP3: libmp3lame CBR 320k, 44.1 kHz, stereo, ID3v2.3
WAV: 16-bit PCM from Carla Audio Recorder at the configured audio sample rate
```

MP3 does not store audio with a PCM bit depth like WAV does. The 16-bit setting applies to the intermediate WAV/PCM render, while MP3 quality is primarily controlled by bitrate, sample rate, channel count, and encoder settings.

Rendered MP3/WAV files are written to:

```text
C:\work\workspace_own\workspace_carla\Carla-2.5.10\output
```

The filename format is:

```text
<original_midi_name>_<style_name>_<YYYYMMDDHHMM>.mp3
<original_midi_name>_<style_name>_<YYYYMMDDHHMM>.wav
```

## List Styles

```http
GET /v1/styles
```

Returns GUI-authored render styles. A style usually maps to one plugin plus one `.carxs` state file saved from Carla GUI.

Important response fields:

```text
ready: true when the style is enabled, its plugin is enabled, and its state file exists if configured
state_exists: true when the configured .carxs file is present locally
state_binary_matches_plugin: true when the .carxs was saved from the same DLL path configured for the plugin
instrument: source instrument name, for example ChineeGaoHu
articulation: playable technique/preset name, for example Stac_1 or Trill_Vel_1
parameter_count: number of default Carla parameter overrides configured for this style
midi_policy: MIDI cleanup/remapping policy applied by default for the style
```

## Render MIDI

```http
POST /v1/render
Content-Type: multipart/form-data
```

Fields:

```text
style_id: preferred configured style id, for example kong_gaohu_sus_leg_mw
plugin_id: optional configured plugin id; required only when rendering without style_id
midi: .mid or .midi upload
style_name: optional output label
max_seconds: optional render cap for quick tests
parameters_json: optional debug-only JSON parameter overrides, for example {"7": 0.8}
apply_midi_policy: optional true/false override; defaults to the selected style policy
midi_source_channel: optional source MIDI channel to keep, for example 7 for the current 刀剑如梦 melody
midi_target_channel: optional target MIDI channel, defaults to the style policy
```

Example:

```powershell
curl.exe -X POST http://127.0.0.1:8000/v1/render `
  -F "style_id=kong_gaohu_sus_leg_mw" `
  -F "midi_source_channel=7" `
  -F "max_seconds=10" `
  -F "midi=@C:\work\workspace_own\workspace_carla\midi\刀剑如梦.mid"
```

Response:

```json
{
  "job_id": "9d5b7b0f079e4f4b8d7c8cb7a4f70e9e",
  "plugin_id": "kong_qin_rv",
  "style_id": "kong_gaohu_sus_leg_mw",
  "parameters_applied": 0,
  "midi_policy_applied": true,
  "midi_policy": {
    "source_channel": 7,
    "target_channel": 1,
    "program_changes_removed": 1,
    "bank_select_removed": 2
  },
  "mp3_path": "C:\\...\\output\\刀剑如梦_Kong_GaoHu_Sus_Leg_MW_202604271741.mp3",
  "wav_path": "C:\\...\\output\\刀剑如梦_Kong_GaoHu_Sus_Leg_MW_202604271741.wav",
  "output_basename": "刀剑如梦_Kong_GaoHu_Sus_Leg_MW_202604271741",
  "encoding": {
    "mp3_codec": "libmp3lame",
    "mp3_bitrate": "320k",
    "mp3_sample_rate": 44100,
    "mp3_channels": 2,
    "mp3_mode": "cbr",
    "mp3_id3v2_version": 3,
    "wav_sample_rate": 44100,
    "wav_bit_depth": 16,
    "wav_channels": 2
  },
  "elapsed_seconds": 12.34,
  "timings": {
    "resolve_request_seconds": 0.001,
    "upload_save_seconds": 0.002,
    "prepare_render_seconds": 0.0,
    "midi_policy_seconds": 0.015,
    "renderer_subprocess_seconds": 186.029,
    "request_total_seconds": 186.054
  },
  "renderer_timings": {
    "prepare_seconds": 0.002,
    "engine_init_seconds": 0.213,
    "add_instrument_seconds": 1.234,
    "load_plugin_state_seconds": 3.456,
    "record_audio_seconds": 170.0,
    "ffmpeg_mp3_seconds": 0.456,
    "total_seconds": 186.029
  },
  "download": {
    "mp3": "/v1/jobs/9d5b7b0f079e4f4b8d7c8cb7a4f70e9e/input_test.mp3",
    "wav": "/v1/jobs/9d5b7b0f079e4f4b8d7c8cb7a4f70e9e/input_test.wav"
  }
}
```

## Download Output

```http
GET /v1/jobs/{job_id}/{filename}
```

Use the `download.mp3` or `download.wav` value from the render response.

The service also writes request logs to the console and to daily files under:

```text
logs\YYYY-MM-DD.log
```
