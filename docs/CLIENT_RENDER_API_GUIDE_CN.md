# MGSC 云端 DAW 渲染接口调用说明

本文档面向客户端调用方，说明如何组织输入 ZIP、如何调用服务端同步/异步渲染接口，以及如何解析服务端返回的 MP3。

## 服务地址

生产部署默认端口为 `18001`。如果经过网关或反向代理，请以实际外网地址为准。

```text
http://<server-ip>:18001
```

健康检查：

```http
GET /mgsc_daw_service/health
```

渲染接口：

```http
POST /mgsc_daw_service/v1/render
Content-Type: multipart/form-data
```

旧接口 `/v1/render` 不再使用。

## 调用模式

接口通过 `callbackurl` 判断同步或异步：

| `callbackurl` | 模式 | 返回方式 |
| --- | --- | --- |
| 不传或为空 | 同步 | 本次 HTTP 响应直接返回 `mp3_file.base64` |
| 非空 URL | 异步 | 本次 HTTP 响应返回 accepted；任务完成后服务端 POST JSON 到 `callbackurl` |

`callbackurl` 只使用这一个字段名，不再兼容 `callback_url` 或 `callback-url`。

## multipart 字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `data` | 是 | 上传 ZIP 文件，推荐字段名 |
| `bundle` | 否 | 与 `data` 等价，兼容字段 |
| `callbackurl` | 否 | 异步回调地址；为空则同步 |
| `style_id` | 否 | 调试覆盖字段，正式调用推荐写在 `conf.json` |
| `max_seconds` | 否 | 调试用截断时长，正式调用不建议使用 |

正式调用只需要上传 `data=@xxx.zip`。同步和异步使用同一个接口。

## ZIP 包结构

### 单风格渲染

适合明确指定一个云端风格，例如 Kong GaoHu、Musyng Kite GM。

```text
render.zip
├── song.mid
└── conf.json
```

`conf.json` 示例：

```json
{
  "style_id": "kong_gaohu_sus_leg_mw",
  "render": {
    "format": "mp3",
    "bit_depth": 16,
    "bitrate": 320,
    "samplerate": 44100
  }
}
```

### 自动映射渲染

适合 MIDI 内已经包含 Bank/Program，服务端自动按需求文档中的 A320U Bank/Program 映射到云端音源。

```json
{
  "style_id": "auto",
  "render": {
    "format": "mp3",
    "bit_depth": 16,
    "bitrate": 320,
    "samplerate": 44100
  }
}
```

当前自动映射覆盖：

```text
Bank 0: GM 128 音色
Bank 128: 9 个鼓组
云端音源: Musyng Kite、Kong、Keyzone Classic、Sonatina Orchestra、DSK Saxophones
```

### 多轨指定音源渲染

适合客户端像老 LMMS 接口一样按 `track_id` 指定不同轨道的 VST/SF2。ZIP 包可以包含 4 个文件：

```text
render.zip
├── song.mid
├── conf.json
├── vst.json
└── sf2.json
```

`conf.json` 示例：

```json
{
  "render": {
    "format": "mp3",
    "bit_depth": 16,
    "bitrate": 320,
    "samplerate": 44100
  },
  "import": "song.mid",
  "vstConf": "vst.json",
  "sf2Conf": "sf2.json"
}
```

`vst.json` 示例：

```json
{
  "vst": [
    {
      "id": 0,
      "track_name": "chord",
      "vst_path": "dsk_saxophones/DSK Saxophones.dll",
      "param_key_name": "Soprano Sax",
      "param_value_name": ""
    },
    {
      "id": 1,
      "track_name": "main_melody",
      "vst_path": "dsk_saxophones/DSK Saxophones.dll",
      "param_key_name": "Tenor Sax",
      "param_value_name": ""
    }
  ]
}
```

`sf2.json` 示例：

```json
{
  "sf2": [
    {
      "id": 2,
      "track_name": "assist_melody",
      "sf2_path": "Arachno SoundFont - Version 1.0.sf2",
      "bank": 0,
      "patch": "12",
      "patch_name": "marimba"
    }
  ]
}
```

说明：

- `id` 是主要匹配字段，对应 MIDI 中的 track 顺序/track_id。
- `track_name` 只用于辅助校验、日志和调试，不作为主要匹配依据。
- `param_key_name` 表示 VST 预设名，例如 `Steinway Piano`、`Soprano Sax`。
- `param_value_name` 当前可留空。
- `bank`、`patch`、`patch_name` 用于 SF2 音色选择或映射。

## 同步调用

Linux/macOS:

```bash
curl -sS -X POST "http://<server-ip>:18001/mgsc_daw_service/v1/render" \
  -F "data=@render.zip" \
  -o response.json
```

Windows PowerShell:

```powershell
curl.exe -sS -X POST "http://<server-ip>:18001/mgsc_daw_service/v1/render" `
  -F "data=@C:\path\to\render.zip" `
  -o response.json
```

同步成功时，响应 JSON 中包含：

```json
{
  "job_id": "a48d9f7130134705a76da5d9b946f581",
  "plugin_id": "kong_qin_rv",
  "style_id": "kong_gaohu_sus_leg_mw",
  "input": {
    "mode": "zip",
    "midi_filename": "song.mid",
    "conf_filename": "conf.json"
  },
  "mp3_file": {
    "filename": "song_Kong_GaoHu_Sus_Leg_MW_202605100907.mp3",
    "mime_type": "audio/mpeg",
    "encoding": "base64",
    "size_bytes": 7377023,
    "base64": "<mp3 base64 string>"
  },
  "download": {
    "mp3": "/mgsc_daw_service/v1/jobs/a48d9f7130134705a76da5d9b946f581/song_Kong_GaoHu_Sus_Leg_MW_202605100907.mp3",
    "wav": "/mgsc_daw_service/v1/jobs/a48d9f7130134705a76da5d9b946f581/song_Kong_GaoHu_Sus_Leg_MW_202605100907.wav"
  },
  "elapsed_seconds": 11.868,
  "timing_summary": {
    "record_audio_seconds": 2.998,
    "ffmpeg_mp3_seconds": 2.1
  }
}
```

客户端应优先读取：

```text
mp3_file.base64
mp3_file.filename
job_id
```

`download.mp3` 和 `download.wav` 主要用于服务端调试或内部下载。

## 异步调用

客户端提供一个可被服务端访问的 HTTP 回调地址：

```bash
curl -sS -X POST "http://<server-ip>:18001/mgsc_daw_service/v1/render" \
  -F "data=@render.zip" \
  -F "callbackurl=http://<client-host>:9000/callback" \
  -o accepted.json
```

立即返回：

```json
{
  "job_id": "64ee09df901344c6a379a8aa28162fd3",
  "status": "accepted",
  "async": true,
  "callbackurl": "http://<client-host>:9000/callback",
  "status_url": "/mgsc_daw_service/v1/jobs/64ee09df901344c6a379a8aa28162fd3/status",
  "accepted_at": "2026-05-10T09:07:30"
}
```

渲染完成后，服务端会向 `callbackurl` 发送 `POST application/json`。成功回调结构与同步成功响应基本一致，并额外包含：

```json
{
  "job_id": "64ee09df901344c6a379a8aa28162fd3",
  "status": "completed",
  "async": true,
  "completed_at": "2026-05-10T09:07:34",
  "mp3_file": {
    "filename": "song.mp3",
    "mime_type": "audio/mpeg",
    "encoding": "base64",
    "size_bytes": 803570,
    "base64": "<mp3 base64 string>"
  }
}
```

如果任务失败，回调中会包含：

```json
{
  "job_id": "...",
  "status": "failed",
  "async": true,
  "error": {
    "message": "failure reason"
  }
}
```

## 完整例子

目标：用 Kong GaoHu 的 `Sus_Leg_MW` 风格渲染 `song.mid`，同步返回 MP3 base64。

1. 准备目录：

```text
example_kong/
├── song.mid
└── conf.json
```

2. 写入 `conf.json`：

```json
{
  "style_id": "kong_gaohu_sus_leg_mw",
  "render": {
    "format": "mp3",
    "bit_depth": 16,
    "bitrate": 320,
    "samplerate": 44100
  }
}
```

3. 打包：

Linux/macOS:

```bash
cd example_kong
zip -r ../example_kong.zip song.mid conf.json
```

Windows PowerShell:

```powershell
Compress-Archive -Path .\song.mid,.\conf.json -DestinationPath ..\example_kong.zip -Force
```

4. 调用接口：

```bash
curl -sS -X POST "http://<server-ip>:18001/mgsc_daw_service/v1/render" \
  -F "data=@example_kong.zip" \
  -o response.json
```

5. 客户端解析 `response.json`：

```python
import base64
import json

with open("response.json", "r", encoding="utf-8") as f:
    payload = json.load(f)

mp3 = payload["mp3_file"]
raw = base64.b64decode(mp3["base64"])

with open(mp3["filename"], "wb") as f:
    f.write(raw)

print("saved", mp3["filename"], "job_id", payload["job_id"])
```

## 常见错误

| HTTP 状态 | 原因 | 处理方式 |
| --- | --- | --- |
| 400 | ZIP 中缺少 `conf.json` | 检查 ZIP 根目录或引用路径 |
| 400 | ZIP 中没有 MIDI 文件 | 确认包含 `.mid` 或 `.midi` |
| 400 | 未知 `style_id` 或插件未启用 | 使用服务端已配置的风格 ID |
| 404 | 调用了旧 `/v1/render` | 改为 `/mgsc_daw_service/v1/render` |
| 500 | 服务端渲染失败 | 记录 `job_id`，查看服务端日志 |

## 当前可用测试 ZIP

交付包中包含以下测试文件，可用于客户端联调：

```text
test_zips/kong_gaohu_sus_leg_mw.zip
test_zips/kong_gaohu_stac_1.zip
test_zips/kong_gaohu_tremolo_vel_1.zip
test_zips/kong_gaohu_trill_vel_1.zip
test_zips/sf2_musyng_kite_daojian_20s.zip
test_zips/lmms_vst_keyzone_single.zip
test_zips/lmms_vst_trackname_multi.zip
test_zips/daojianrumeng_style_auto_full_20260510.zip
```
