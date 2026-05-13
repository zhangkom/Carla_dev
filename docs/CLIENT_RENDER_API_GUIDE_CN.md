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

正式调用只需要上传 `data=@xxx.zip`。同步和异步使用同一个接口。`debug` 不作为 multipart 字段使用，需要调试时写在 `conf.json` 顶层或 `render.debug`；不写时程序默认 `false`。

## ZIP 包结构和输入 JSON

### 单轨渲染

单轨渲染表示一个 MIDI 按一个云端风格整体渲染，最后返回一个 MP3。适合调用方已经明确要使用哪个云端 `style_id` 的场景。

```text
render.zip
├── song.mid
└── conf.json
```

`conf.json` 示例：

```json
{
  "style_id": "sf2_musyng_kite_gm",
  "render": {
    "format": "mp3",
    "bitrate": 320,
    "mp3_mode": "cbr",
    "mp3_quality": 2,
    "mp3_compression_level": 7
  }
}
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `style_id` | 是 | 云端风格 ID，例如 `sf2_musyng_kite_gm` |
| `render.format` | 否 | 当前只支持 `mp3`，不写时按服务端默认 |
| `render.bitrate` | 否 | MP3 码率，默认 320 |
| `render.mp3_mode` | 否 | `cbr` 或 `vbr`，默认 `cbr` |
| `render.mp3_quality` | 否 | VBR 质量参数，0 最高、9 最低；CBR 下保留但不是主控参数 |
| `render.mp3_compression_level` | 否 | libmp3lame 编码速度/质量参数，0 最慢、9 最快；当前默认 7 |
| `debug` | 否 | 不写时默认 `false`；调试时才写 `true` |

调试时可以临时增加：

```json
{
  "debug": true,
  "style_id": "sf2_musyng_kite_gm"
}
```

### 多轨渲染

多轨渲染表示一个 MIDI 中有多个轨道，每个轨道可指定不同音源。正式推荐方案是：客户端按 Web 端 A320U 音源语义传 `bank + patch`，服务端根据映射表选择云端 Carla 风格。云端实际使用的是 SF2、Kong、Keyzone、Sonatina、DSK 等插件细节，客户端不用关心。

```text
render.zip
├── song.mid
├── conf.json
└── sf2.json
```

`conf.json` 示例：

```json
{
  "render": {
    "format": "mp3",
    "bitrate": 320,
    "mp3_mode": "cbr",
    "mp3_quality": 2,
    "mp3_compression_level": 7
  },
  "sf2Conf": "sf2.json"
}
```

`sf2.json` 示例：

```json
{
  "sf2": [
    {
      "id": 0,
      "track_name": "chord",
      "bank": 0,
      "patch": 0
    },
    {
      "id": 1,
      "track_name": "main_melody",
      "bank": 0,
      "patch": 40
    },
    {
      "id": 4,
      "track_name": "drum",
      "bank": 128,
      "patch": 8
    }
  ]
}
```

说明：

- `id` 是主要匹配字段，对应 MIDI 中的 track 顺序/track_id，建议必填。
- `track_name` 只用于辅助校验、日志和调试，不作为主要匹配依据。
- `bank` + `patch` 表示 Web 端 A320U 音源编号，服务端映射到云端音源。
- 普通 GM 音色使用 `bank=0`，鼓组使用 `bank=128`。
- `patch` 使用 0-based 编号，和需求文档映射表一致。
- 多轨正式调用不建议传 `sf2_path`、`vst_path`、`param_key_name`、`param_value_name`、`patch_name`。

老 LMMS 的 `sf2_path` / `vst_path` / `param_key_name` / `param_value_name` 仍可作为迁移兼容输入，但它们属于旧工程实现细节，不作为新客户端正式协议。

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
  "http_code": 200,
  "status": "success",
  "error": null,
  "job_id": "a48d9f7130134705a76da5d9b946f581",
  "plugin_id": "kong_qin_rv",
  "style_id": "kong_gaohu_sus_leg_mw",
  "output_basename": "song_Kong_GaoHu_Sus_Leg_MW_202605100907",
  "elapsed_seconds": 11.868,
  "mp3_file": {
    "base64": "<mp3 base64 string>"
  }
}
```

客户端应优先读取：

```text
mp3_file.base64
output_basename
job_id
```

`debug=false` 默认只返回 `http_code`、`status`、`error`、`job_id`、`plugin_id`、
`style_id`、`output_basename`、`elapsed_seconds`、`mp3_file.base64`。

`download.mp3`、`download.wav`、`timing_summary`、`renderer_timings` 等字段只在
`conf.json` 中设置 `debug=true` 时返回，用于服务端调试或性能定位。

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
  "http_code": 200,
  "job_id": "64ee09df901344c6a379a8aa28162fd3",
  "status": "accepted",
  "error": null,
  "async": true,
  "callbackurl": "http://<client-host>:9000/callback",
  "status_url": "/mgsc_daw_service/v1/jobs/64ee09df901344c6a379a8aa28162fd3/status",
  "accepted_at": "2026-05-10T09:07:30"
}
```

渲染完成后，服务端会向 `callbackurl` 发送 `POST application/json`。`debug=false`
时成功回调结构与同步成功响应一致：

```json
{
  "http_code": 200,
  "status": "success",
  "error": null,
  "job_id": "64ee09df901344c6a379a8aa28162fd3",
  "plugin_id": "kong_qin_rv",
  "style_id": "kong_gaohu_sus_leg_mw",
  "output_basename": "song_Kong_GaoHu_Sus_Leg_MW_202605100907",
  "elapsed_seconds": 11.868,
  "mp3_file": {
    "base64": "<mp3 base64 string>"
  }
}
```

`status`、`async`、`completed_at` 等异步完成诊断字段只在 `debug=true` 的成功回调中返回；
任务状态仍可通过 `status_url` 查询。

如果任务失败，回调中会包含：

```json
{
  "http_code": 500,
  "job_id": "...",
  "status": "failed",
  "async": true,
  "error": {
    "code": "RenderError",
    "message": "failure reason",
    "detail": "failure reason"
  }
}
```

## 完整例子

目标：用 Musyng Kite GM 风格渲染 `song.mid`，同步返回 MP3 base64。

1. 准备目录：

```text
example_single/
├── song.mid
└── conf.json
```

2. 写入 `conf.json`：

```json
{
  "style_id": "sf2_musyng_kite_gm",
  "render": {
    "format": "mp3",
    "bitrate": 320,
    "mp3_mode": "cbr",
    "mp3_quality": 2,
    "mp3_compression_level": 7
  }
}
```

3. 打包：

Linux/macOS:

```bash
cd example_single
zip -r ../example_single.zip song.mid conf.json
```

Windows PowerShell:

```powershell
Compress-Archive -Path .\song.mid,.\conf.json -DestinationPath ..\example_single.zip -Force
```

4. 调用接口：

```bash
curl -sS -X POST "http://<server-ip>:18001/mgsc_daw_service/v1/render" \
  -F "data=@example_single.zip" \
  -o response.json
```

5. 客户端解析 `response.json`：

```python
import base64
import json

with open("response.json", "r", encoding="utf-8") as f:
    payload = json.load(f)

raw = base64.b64decode(payload["mp3_file"]["base64"])
filename = payload.get("output_basename", "render") + ".mp3"

with open(filename, "wb") as f:
    f.write(raw)

print("saved", filename, "job_id", payload["job_id"])
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
