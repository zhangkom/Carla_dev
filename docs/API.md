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

## Catalog

```http
GET /v1/catalog
```

Returns a client-friendly JSON catalog of configured plugins, categories, styles, and output directories.

Important distinction:

```text
configured_plugin_count: plugins available in config
loaded_plugin_count: currently loaded Carla plugins
runtime_model: per_request_subprocess
```

The first production-safe version does not keep VST plugins loaded between requests. Each render starts a Carla subprocess, loads the selected plugin/style, renders, then closes Carla. Therefore `loaded_plugin_count` is normally `0` outside an active render.

Example response shape:

```json
{
  "runtime_model": "per_request_subprocess",
  "loaded_plugin_count": 0,
  "configured_plugin_count": 4,
  "enabled_plugin_count": 4,
  "style_count": 5,
  "categories": {
    "vst3": 2,
    "vst2": 1,
    "kong_audio": 1
  },
  "plugins": [
    {
      "id": "kong_qin_rv",
      "name": "Qin_RV",
      "category": "kong_audio",
      "format": "vst2",
      "enabled": true,
      "path_exists": true,
      "style_count": 4,
      "ready_style_count": 4,
      "styles": [
        {
          "id": "kong_gaohu_sus_leg_mw",
          "instrument": "ChineeGaoHu",
          "articulation": "Sus_Leg_1_MW",
          "ready": true
        }
      ]
    }
  ]
}
```

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

## List Instrument Mappings

```http
GET /v1/instrument-mappings
```

Returns the active 137-entry Bank/Program mapping loaded from
`config/instrument_mapping.deploy.json`, including the resolved style for each
entry. This is mainly a deployment/debug endpoint for checking that the Word
document mapping is available to `style_id=auto`.

Important response fields:

```text
mapping_count: total mapping rows, expected 137
plugin_counts: mapping count by target plugin
bank_counts: mapping count by source MIDI bank
resolved_style_id: style selected by the current runtime config
fallback: true when a mapped target exists but the exact style/state is not ready
fallback_reason: reason for fallback, for example target_style_unavailable
```

## Render MIDI

```http
POST /v1/render
Content-Type: multipart/form-data
```

Fields:

```text
data or bundle: preferred zip upload. The zip must contain exactly one .mid/.midi file and one conf.json.
midi: optional direct .mid/.midi upload for debugging; do not combine with data/bundle.
style_id: optional form override; normally read from conf.json.
plugin_id: optional configured plugin id; required only when rendering without style_id.
style_name: optional output label; normally read from conf.json or style config.
max_seconds: optional render cap for quick tests.
parameters_json: optional debug-only JSON parameter overrides, for example {"7": 0.8}.
apply_midi_policy: optional true/false override; defaults to the selected style policy.
midi_source_channel: optional debug override. Production requests should omit it and use automatic source channel detection.
midi_target_channel: optional debug override. Production requests should omit it and use the selected style policy target channel.
callback_url or callbackurl: optional absolute http(s) URL. Empty or omitted means synchronous response; non-empty means async callback mode.
```

Recommended zip contents:

```text
bundle.zip
├── 刀剑如梦.mid
└── conf.json
```

Minimal `conf.json`:

```json
{
  "style_id": "kong_gaohu_sus_leg_mw"
}
```

For Musyng Kite SoundFont GM rendering:

```json
{
  "style_id": "sf2_musyng_kite_gm"
}
```

`sf2_musyng_kite_gm` preserves the MIDI file's original channels, bank select,
and program changes. It does not apply the Kong GaoHu MIDI channel cleanup
policy.

Example:

```powershell
$tmp = "C:\work\workspace_own\workspace_carla\tmp\kong_render"
New-Item -ItemType Directory -Force $tmp | Out-Null
Copy-Item "C:\work\workspace_own\workspace_carla\midi\刀剑如梦.mid" "$tmp\刀剑如梦.mid"
'{"style_id":"kong_gaohu_sus_leg_mw"}' | Set-Content -Encoding UTF8 "$tmp\conf.json"
Compress-Archive -Path "$tmp\刀剑如梦.mid","$tmp\conf.json" -DestinationPath "$tmp\bundle.zip" -Force

curl.exe -X POST http://127.0.0.1:8000/v1/render `
  -F "data=@$tmp\bundle.zip"
```

The render response includes the generated MP3 as base64 JSON. Remote callers can
decode `mp3_file.base64` and write the decoded bytes directly to an `.mp3` file,
without issuing a second download request.

Example response fields:

```json
{
  "job_id": "4e6f...",
  "style_id": "kong_gaohu_sus_leg_mw",
  "output_basename": "song_Kong_GaoHu_Sus_Leg_MW_202604301430",
  "mp3_file": {
    "filename": "song_Kong_GaoHu_Sus_Leg_MW_202604301430.mp3",
    "mime_type": "audio/mpeg",
    "encoding": "base64",
    "size_bytes": 7340032,
    "base64": "..."
  },
  "download": {
    "mp3": "/v1/jobs/4e6f.../song_Kong_GaoHu_Sus_Leg_MW_202604301430.mp3"
  }
}
```

`download.mp3` remains available as a backward-compatible fallback.

### Async callback mode

If `callback_url`/`callbackurl` is empty or omitted, `/v1/render` is synchronous and returns
the generated MP3 in `mp3_file.base64` as shown above.

If `callback_url`/`callbackurl` is non-empty, `/v1/render` returns immediately after accepting
the upload:

```json
{
  "job_id": "4e6f...",
  "status": "accepted",
  "async": true,
  "callback_url": "http://client-host:9000/callback"
}
```

The service then renders in a background worker and sends one JSON `POST` to the callback URL.
On success, the callback body reuses the synchronous response shape and adds async status fields:

```json
{
  "job_id": "4e6f...",
  "status": "completed",
  "async": true,
  "style_id": "kong_gaohu_sus_leg_mw",
  "mp3_file": {
    "filename": "song_Kong_GaoHu_Sus_Leg_MW_202604301430.mp3",
    "mime_type": "audio/mpeg",
    "encoding": "base64",
    "size_bytes": 7340032,
    "base64": "..."
  }
}
```

On failure, the callback body is:

```json
{
  "job_id": "4e6f...",
  "status": "failed",
  "async": true,
  "error": {
    "status_code": 500,
    "detail": "..."
  }
}
```

Callback delivery uses `POST application/json`, disables proxy lookup, and retries up to 3
times by default. Runtime knobs:

```text
MUSIC_SERVICE_ASYNC_WORKERS=1
MUSIC_SERVICE_CALLBACK_TIMEOUT=30
MUSIC_SERVICE_CALLBACK_RETRIES=3
```

The dedicated async client can run a temporary local callback receiver:

```powershell
python mgsc_daw_async_client.py `
  --server http://127.0.0.1:8000 `
  --zip C:\path\to\bundle.zip `
  --callback-bind-host 0.0.0.0 `
  --callback-public-host host.docker.internal
```

When the render service runs in Docker and the client runs on the host machine, use a callback
host that is reachable from inside the container, such as `host.docker.internal` on Docker
Desktop or the host's LAN IP on Linux deployments.

`mgsc_daw_client.py` remains the synchronous client. `mgsc_daw_async_client.py` is the
async callback client; if you pass `--callback-url`, it submits the async task and returns the
accepted response without starting a local receiver.

Response:

```json
{
  "job_id": "9d5b7b0f079e4f4b8d7c8cb7a4f70e9e",
  "plugin_id": "kong_qin_rv",
  "style_id": "kong_gaohu_sus_leg_mw",
  "input": {
    "mode": "zip",
    "midi_filename": "刀剑如梦.mid",
    "conf_filename": "conf.json"
  },
  "parameters_applied": 0,
  "render_options": {
    "format": "mp3",
    "bitrate": "320k",
    "bit_depth": 16,
    "loop": false,
    "samplerate": 44100
  },
  "midi_policy_applied": true,
  "midi_policy": {
    "source_channel": 7,
    "target_channel": 1,
    "source_channel_auto_selected": true,
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
  "timing_summary": {
    "mp3_generation_seconds": 186.054,
    "renderer_total_seconds": 186.029,
    "record_audio_seconds": 170.0,
    "ffmpeg_mp3_seconds": 0.456,
    "midi_policy_seconds": 0.015,
    "output_finalize_seconds": 0.001,
    "mp3_bytes": 7340032,
    "wav_bytes": 81133568
  },
  "renderer_stage_seconds": {
    "record_audio_seconds": 170.0,
    "load_plugin_state_seconds": 3.456,
    "add_instrument_seconds": 1.234,
    "ffmpeg_mp3_seconds": 0.456,
    "engine_init_seconds": 0.213
  },
  "record_audio_breakdown": {
    "record_audio_seconds": 170.0,
    "transport_relocate_seconds": 0.001,
    "transport_play_seconds": 0.001,
    "record_idle_wall_seconds": 169.8,
    "record_idle_engine_idle_seconds": 0.050,
    "record_idle_sleep_seconds": 169.6,
    "record_idle_loop_overhead_seconds": 0.150,
    "record_idle_iterations": 8500,
    "transport_pause_seconds": 0.001,
    "post_pause_idle_seconds": 0.2
  },
  "download": {
    "mp3": "/v1/jobs/9d5b7b0f079e4f4b8d7c8cb7a4f70e9e/input_test.mp3",
    "wav": "/v1/jobs/9d5b7b0f079e4f4b8d7c8cb7a4f70e9e/input_test.wav"
  }
}
```

`timing_summary.mp3_generation_seconds` is the main per-output timing to watch. It includes upload handling, MIDI preprocessing, Carla subprocess rendering, MP3 encoding, and final output rename/move. `renderer_stage_seconds` sorts renderer subprocess stages by cost, so the first key is the current bottleneck. For full-length Kong renders, `record_audio_seconds` is usually close to the musical duration plus tail time, while `ffmpeg_mp3_seconds` isolates MP3 encoding cost.

`record_audio_breakdown` drills into the transport recording block. In the current realtime Carla path, `transport_play_seconds` should be near zero; the long duration is expected to appear under `record_idle_wall_seconds`, with the loop spending most wall time sleeping while Carla's audio engine plays and the Audio Recorder writes WAV.

For batch/manual timing tests, run:

```powershell
python tools\call_render_zip.py `
  C:\work\workspace_own\workspace_carla\midi\zip_kong_4styles_full_new_20260427200913\kong_gaohu_sus_leg_mw.zip `
  C:\work\workspace_own\workspace_carla\midi\zip_kong_4styles_full_new_20260427200913\kong_gaohu_stac_1.zip
```

Each completed render prints one line with `client_elapsed`, `mp3_generation`, `renderer`, `top_stage`, `record_audio`, `ffmpeg_mp3`, and the final `mp3` path.

## Download Output

```http
GET /v1/jobs/{job_id}/{filename}
```

Use the `download.mp3` or `download.wav` value from the render response.

The service also writes request logs to the console and to daily files under:

```text
logs\YYYY-MM-DD.log
```

Each successful render also writes a concise timing line:

```text
mp3 timing job_id=... style_id=... output=... mp3_generation=186.054s renderer=186.029s record_audio=170.000s ffmpeg_mp3=0.456s midi_policy=0.015s output_finalize=0.001s mp3_bytes=7340032 wav_bytes=81133568
```

The renderer subprocess also emits live progress events to the service log during long renders:

```text
renderer event stream=stderr RENDER_EVENT {"event": "record_audio_progress", "elapsed_seconds": 90.0, "percent": 52.9, "target_seconds": 170.0}
renderer timing detail job_id=... top_stage=record_audio_seconds top_seconds=170.000s midi_length=168.000 record_target=170.000 stages={"record_audio_seconds": 170.0, "load_plugin_state_seconds": 3.456, "add_instrument_seconds": 1.234}
record audio breakdown job_id=... style_id=... breakdown={"record_idle_sleep_seconds": 169.6, "record_idle_wall_seconds": 169.8, "transport_play_seconds": 0.001}
```
