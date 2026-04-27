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

## Render MIDI

```http
POST /v1/render
Content-Type: multipart/form-data
```

Fields:

```text
plugin_id: configured plugin id, for example surge_xt
midi: .mid or .midi upload
style_name: optional output label
max_seconds: optional render cap for quick tests
```

Example:

```powershell
curl.exe -X POST http://127.0.0.1:8000/v1/render `
  -F "plugin_id=surge_xt" `
  -F "style_name=test" `
  -F "max_seconds=10" `
  -F "midi=@C:\path\to\example.mid"
```

Response:

```json
{
  "job_id": "9d5b7b0f079e4f4b8d7c8cb7a4f70e9e",
  "plugin_id": "surge_xt",
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

