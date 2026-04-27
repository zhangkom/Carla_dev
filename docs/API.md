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
```

Example:

```powershell
curl.exe -X POST http://127.0.0.1:8000/v1/render `
  -F "style_id=surge_xt_default" `
  -F "max_seconds=10" `
  -F "midi=@C:\path\to\example.mid"
```

Response:

```json
{
  "job_id": "9d5b7b0f079e4f4b8d7c8cb7a4f70e9e",
  "plugin_id": "surge_xt",
  "style_id": "surge_xt_default",
  "parameters_applied": 0,
  "mp3_path": "C:\\...\\service_work\\...\\input_test.mp3",
  "wav_path": "C:\\...\\service_work\\...\\input_test.wav",
  "elapsed_seconds": 12.34,
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
