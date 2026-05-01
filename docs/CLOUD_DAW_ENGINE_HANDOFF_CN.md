<!--
/**
* File name: CLOUD_DAW_ENGINE_HANDOFF_CN.md
* Brief: MGSC DAW 项目文档
* Function:
*     记录云端 DAW 服务接口、部署、状态或开发规范
* Author: 咪咕数创工程架构组
*     MGSC AI Software Architecture group
* Version: V2.5.10
* Date: 2026/04/30
*/
-->

# 云端 DAW 音频工作站引擎实现交接记录

版本：V2.5.10  
日期：2026/04/30-2026/05/01  
依据文档：`C:\work\workspace_own\workspace_carla\doc\云端DAW音频工作站引擎.docx`  
工程目录：`C:\work\workspace_own\workspace_carla\Carla-2.5.10`  
资产目录：`C:\work\workspace_own\workspace_carla\mgsc_daw_assets`

## 0. 2026/05/01 08:54 Codex App v6.4.40 独立异步客户端发布检查点

本次在保持 `/v1/render` 同步接口兼容的前提下，新增 callback URL 异步模式：

1. `/v1/render` 新增可选表单字段 `callback_url`，同时兼容 `callbackurl`。
2. `callback_url`/`callbackurl` 为空或不传时，仍走原同步路径，直接返回当前完整 JSON，包含 `mp3_file.base64`。
3. `callback_url`/`callbackurl` 非空时，服务端读取并复制上传内容后立即返回：

```json
{
  "job_id": "...",
  "status": "accepted",
  "async": true,
  "callback_url": "http://client-host:9000/callback"
}
```

4. 后台渲染完成后，服务端向 callback URL 发送 `POST application/json`。成功时复用同步响应结构，并额外包含 `status: "completed"`、`async: true`；失败时回调 `status: "failed"` 和错误详情。
5. 异步渲染默认单 worker，避免多个 Carla/Wine 渲染任务抢占资源。可通过环境变量调整：
   - `MUSIC_SERVICE_ASYNC_WORKERS=1`
   - `MUSIC_SERVICE_CALLBACK_TIMEOUT=30`
   - `MUSIC_SERVICE_CALLBACK_RETRIES=3`
6. 新增独立异步客户端 `mgsc_daw_async_client.py`，默认启动本地临时 HTTP callback receiver，收到回调后按原逻辑保存 `mp3_file.base64`。
7. `mgsc_daw_client.py` 保持同步客户端定位，同时保留调试用异步参数：
   - `--callback-url`：只提交异步任务并返回 accepted 响应；
   - `--async-callback`：启动本地临时 HTTP callback receiver；
   - `--callback-bind-host`、`--callback-public-host`、`--callback-port`、`--callback-path`。

已用 fake renderer 做本机单元级验证：异步请求可立即返回 accepted，后台渲染结束后 callback 收到完整 `mp3_file.base64`；同步请求仍直接返回 `mp3_file.base64`。

本次新增独立客户端文件：

```text
mgsc_daw_async_client.py
```

默认用法：

```powershell
python mgsc_daw_async_client.py `
  --server http://127.0.0.1:8000 `
  --zip C:\path\to\bundle.zip `
  --output output.mp3 `
  --callback-bind-host 0.0.0.0 `
  --callback-public-host host.docker.internal
```

`mgsc_daw_client.py` 继续作为同步客户端保留；部署脚本现在会同时从容器中拷出 `mgsc_daw_client.py` 和 `mgsc_daw_async_client.py`。

已固化并验证干净交付镜像：

```text
mgsc_daw_service:v6.4.40
image id: sha256:953fdbdc7a8c01cdfaa16766f12069fa446811f6f35d4400c61cf480a4010c2d
image size: 4456127571 bytes
```

镜像导出目录：

```text
C:\work\workspace_own\workspace_carla\docker_images
```

需要拷贝到 Ubuntu 的文件：

```text
deploy_mgsc_daw_service.sh
mgsc_daw_service_v6.4.40.tar.part01
mgsc_daw_service_v6.4.40.tar.part02
mgsc_daw_service_v6.4.40.tar.part03
SHA256SUMS_v6.4.40.txt
SHA256SUMS_v6.4.40_parts.txt
MANIFEST_v6.4.40.txt
test_zips_v6.4.40.zip
```

完整 tar：

```text
mgsc_daw_service_v6.4.40.tar
size: 4456169472 bytes
sha256: 376D63FE4521CA8457DB2336F5C579F5399A289B38AF18BE1DE083836945C4EA
```

分片大小：

```text
part01: 1900000000 bytes
part02: 1900000000 bytes
part03: 656169472 bytes
```

已用流式 SHA256 校验确认：三个分片按顺序拼接后的 SHA256 与完整 tar 一致。

v6.4.40 最终镜像验证结果：

| 测试 | 结果 |
| --- | --- |
| 新容器启动 `/health` | 通过 |
| `mgsc_daw_async_client.py` + `host.docker.internal` | 通过；服务端先返回 `accepted`，渲染完成后 callback 一次送达 |
| `auto_sonatina_violin_program40_probe.zip` 异步渲染 | `status=completed`，`style_id=sonatina_solo_violin`，MP3 从 callback `mp3_file.base64` 保存，大小 172452 bytes |
| 同步 `/v1/render` 兼容回归 | 通过；仍直接返回 `mp3_file.base64` |

注意：如果渲染服务运行在 Docker 容器内，而客户端 callback receiver 运行在宿主机，`callback_url` 不能写成容器内的 `127.0.0.1`，需要使用容器可访问的宿主机地址，例如 Docker Desktop 的 `host.docker.internal` 或 Linux 部署中的宿主机 LAN IP。

## 0.1 2026/05/01 01:21 Codex App v6.4.38 发布检查点

当前功能实现提交：

```text
d4fb585 标记137条音源映射全部实现
```

当前干净交付镜像：

```text
mgsc_daw_service:v6.4.38
image id: sha256:b7d9f698330bcb655fa7810bb17db22cf9c0c96620e5f7e569bb0333f7c3405c
image size: 4456041365 bytes
```

v6.4.38 要点：

1. `config/instrument_mapping.deploy.json` 的 137 条 MIDI Bank/Program 映射均标记为 `implemented`。
2. `/v1/instrument-mappings` 在部署配置下返回 `mapping_count=137`，`implemented=137`。
3. `style_id=auto` 保持走完整文档映射，关键映射无 fallback：
   - `gm_040` -> `sonatina_solo_violin`
   - `gm_015` -> `kong_yangqin_sus_mp`
   - `gm_107` -> `kong_guzheng_classic_sus_shake_2`
4. `/v1/render` 接口保持不变：zip 输入不变，响应里的 `mp3_file.base64` 不变。
5. `C:\work\workspace_own\workspace_carla\docker_images\deploy_mgsc_daw_service.sh` 默认镜像和 tar 已切到 v6.4.38。

镜像导出目录：

```text
C:\work\workspace_own\workspace_carla\docker_images
```

需要拷贝到 Ubuntu 的文件：

```text
deploy_mgsc_daw_service.sh
mgsc_daw_service_v6.4.38.tar.part01
mgsc_daw_service_v6.4.38.tar.part02
mgsc_daw_service_v6.4.38.tar.part03
SHA256SUMS_v6.4.38.txt
SHA256SUMS_v6.4.38_parts.txt
MANIFEST_v6.4.38.txt
test_zips_v6.4.38.zip
```

完整 tar：

```text
mgsc_daw_service_v6.4.38.tar
size: 4456081920 bytes
sha256: 63E652908E8A61BC863C2CAA5A6F6DDFFE88B689A5FC7C7F253A860DE2EC628C
```

分片大小：

```text
part01: 1900000000 bytes
part02: 1900000000 bytes
part03: 656081920 bytes
```

已用流式 SHA256 校验确认：三个分片按顺序拼接后的 SHA256 与完整 tar 一致。

v6.4.38 最终镜像验证结果：

| 测试 | 路由 style | 结果 | WAV RMS | WAV peak |
| --- | --- | --- | ---: | ---: |
| `auto_sonatina_violin_program40_probe.zip` | `sonatina_solo_violin` | 通过，有声 | 1653 | 7089 |
| `auto_kong_yangqin_program15_probe.zip` | `kong_yangqin_sus_mp` | 通过，有声 | 1569 | 13720 |
| `auto_kong_guzheng_program107_probe.zip` | `kong_guzheng_classic_sus_shake_2` | 通过，有声 | 1244 | 10940 |
| `kong_gaohu_sus_leg_mw_debug_10s.zip` | `kong_gaohu_sus_leg_mw` | 通过，有声 | 1348 | 7371 |

构建说明：最终镜像提交前已删除 `/wineprefix`、`/home/runtime/output`、`/home/runtime/logs`、`/home/runtime/service_work` 和 Python cache，只保留 `/home/runtime/wineprefix_seed`。部署后第一次启动服务会从 seed 初始化 `/wineprefix`，seed 中已包含 `ChineeGaoHu`、`ChineeYangQin`、`ChineeGuZheng_Classic`。

## 0.2 2026/04/30 23:55 Codex App 检查点

本次已补齐文档映射中的 Kong 扬琴和古筝：

1. 新增 `config/plugins.deploy.json` styles：
   - `kong_yangqin_sus_mp` -> `ChineeYangQin / 02 Sus_mp`
   - `kong_guzheng_classic_sus_shake_2` -> `ChineeGuZheng_Classic / 03 Sus_Shake_2`
2. 已通过 Carla GUI 在临时 Xvfb 容器中加载 Kong Qin_RV，选择目标乐器和 preset，并保存验证有声的本地状态文件：
   - `states/kong_yangqin_sus_mp.carxs`
   - `states/kong_guzheng_classic_sus_shake_2.carxs`
3. `mgsc_daw_service.py` 新增 Kong Qin_RV library materialize 逻辑：如果部署镜像或挂载目录中存在 `/home/workspace/assets/kong_audio/qin_rv_v2_2/library`，启动时会把 `ChineeGaoHu`、`ChineeYangQin`、`ChineeGuZheng_Classic` 复制到 Wine 的 `Kong Audio Library`。
4. `config/instrument_mapping.deploy.json` 中 `gm_015`、`gm_107` 的状态已从 `partial` 改为 `implemented`，`/v1/instrument-mappings` 当前解析为：
   - `gm_015` -> `kong_yangqin_sus_mp`，`fallback=false`
   - `gm_107` -> `kong_guzheng_classic_sus_shake_2`，`fallback=false`

已在临时容器 `mgsc_daw_service_kong_probe` 用实际部署配置验证：

| 测试 | 结果 | WAV RMS | WAV peak |
| --- | --- | ---: | ---: |
| `auto_kong_yangqin_program15_probe.zip` | 自动路由到 `kong_yangqin_sus_mp`，有声 | 1569 | 13720 |
| `auto_kong_guzheng_program107_probe.zip` | 自动路由到 `kong_guzheng_classic_sus_shake_2`，有声 | 1244 | 10940 |
| GaoHu `Sus_Leg_MW` 回归 | 通过 | 1378 | 11566 |
| GaoHu `Stac_1` 回归 | 通过 | 1155 | 9482 |
| GaoHu `Trill_Vel_1` 回归 | 通过 | 918 | 8586 |
| GaoHu `Tremolo_Vel_1` 回归 | 通过 | 815 | 7795 |

注意：`states/*.carxs` 按项目约定仍被 `.gitignore` 忽略，但本地工作区已经生成并保存上述两个新增状态文件；构建或提交部署镜像前必须确保这两个状态文件和对应 Kong library 已进入镜像或部署挂载目录。

## 0.3 2026/04/30 22:15 Codex App 检查点

本次继续加固了 `style_id: "auto"` 的文档映射实现：MIDI 分析现在会读取 Bank Select MSB/LSB 和 Program Change，路由时优先按运行时解析出的 Bank/Program 匹配 `config/instrument_mapping.deploy.json`，再回退到旧的 Program-only 兼容逻辑。这样可覆盖 Word 文档中的 Bank 0 普通 GM 映射和 Bank 128 鼓组映射。

同时新增部署/调试接口：

```http
GET /v1/instrument-mappings
```

该接口返回当前加载的 137 条映射、按插件/Bank 的统计，以及每条映射在当前 `plugins.deploy.json` 下会解析到的 style/fallback 状态。`/v1/styles` 和 `/v1/catalog` 的 style 条目也补充返回 `vst2_preset`，便于核对 VST2 预设映射。

已验证：

| 验证项 | 结果 |
| --- | --- |
| Python 编译检查 | 通过 |
| `auto_route_two_channel_debug_5s.zip` MIDI 解析 | channel 1 Bank 0/Program 0 匹配 `gm_000` -> `keyzone_steinway_piano`；channel 2 Bank 0/Program 64 匹配 `gm_064` -> `dsk_soprano_sax` |
| `/v1/instrument-mappings` TestClient | 200；`mapping_count=137`；Bank 0 为 128 条，Bank 128 为 9 条 |

## 0.4 2026/04/30 21:50 Codex App 接管后状态

本次已经把 `style_id: "auto"` 的路由依据从 `plugins.deploy.json` 中各 style 的小范围 `gm_programs`，切换为 `config/instrument_mapping.deploy.json` 中由 Word 表格抽取出的完整 137 条 Bank/Program 映射。接口保持不变：仍是当前 `/v1/render`，zip 输入不变，响应里的 `mp3_file.base64` 不变。

代码变化要点：

1. 新增 `music_service/instrument_mapping.py`，负责读取 `config/instrument_mapping.deploy.json`，按 MIDI channel、Bank、Program 找到文档映射，再匹配已有 style。
2. `music_service/main.py` 的 `auto` 单路由和多通道路由都改为调用完整映射；显式指定 `style_id` 的 Kong GaoHu 路径不变。
3. `music_service/config.py` 的 `StyleProfile` 新增 `vst2_preset` 字段，用于把文档中的 VST2 预设路径映射到已生成的 Keyzone、DSK、Sonatina style。
4. `tools/build_instrument_mapping_from_docx.py` 增加兼容：普通 GM 行如果 Word 表格里的 Web Program 为空，则按 MIDI id 回填。当前已修正 `gm_111` 唢呐，使其从 `null` 变为 `111`。

当前验证结果：

| 验证项 | 结果 |
| --- | --- |
| Python 编译检查 | `music_service`、构建脚本、服务入口编译通过 |
| 137 条映射解析 | 111 条 Musyng、17 条 Sonatina、5 条 Keyzone、2 条 DSK 正常落到已实现 style |
| Kong 文档映射 | MIDI 15 扬琴、MIDI 107 筝已被识别为 Kong 目标，但因未有已验证 `.carxs` 状态，当前自动回退到 `sf2_musyng_kite_gm`，并在路由元数据中标记 `fallback_reason: "target_style_unavailable"` |
| `auto_route_two_channel_debug_5s.zip` 容器 API 测试 | 通过；channel 1 路由到 `keyzone_steinway_piano`，channel 2 路由到 `dsk_soprano_sax`，返回 MP3 base64 |
| `kong_gaohu_sus_leg_mw_debug_10s.zip` 容器 API 回归 | 通过；显式 Kong GaoHu 路径未受影响 |

Kong YangQin / GuZheng 的当前判断：

1. 本地资产里已确认存在 `ChineeYangQin`，且 SoundBank 中有 `YangQin_z2_mp.KAS`，与文档 `02 Sus_mp` 对应关系最接近。
2. 本地资产里同时存在 `ChineeGuZheng_Classic` 和 `ChineeGuZheng_II`。文档目标是 `03 Sus_Shake_2`，从文件名看 `ChineeGuZheng_Classic\SoundBank\GuZheng_Shake_2.KAS` 更接近。
3. 已只读拆解现有 4 个 GaoHu `.carxs`：状态二进制块不只是最后的 preset 名，GaoHu 的不同奏法之间已有几十到数百字节差异。因此不要通过简单替换 `CGH2`/preset 字符串来伪造可交付的 YangQin 或 GuZheng 状态。
4. 正确下一步仍是按 `docs/STYLE_AUTHORING.md` 用 Carla GUI 加载 `Qin_RV`，手动选择目标乐器和奏法，确认有声后保存新的 `.carxs`。

下一步从这里继续：

1. 用 Carla GUI 建立并验证 `ChineeYangQin / 02 Sus_mp` 状态，建议文件名 `states/kong_yangqin_sus_mp.carxs`。
2. 用 Carla GUI 建立并验证 `ChineeGuZheng_Classic / 03 Sus_Shake_2` 状态，建议文件名 `states/kong_guzheng_classic_sus_shake_2.carxs`。
3. 状态文件确认有声后，再在 `config/plugins.deploy.json` 增加对应 enabled style。`music_service/instrument_mapping.py` 已经能按 `instrument` + `articulation` 自动匹配这些未来 style。
4. 接入后必须再跑 `auto` MIDI 15、`auto` MIDI 107、以及 Kong GaoHu 4 风格回归。

## 0.5 2026/04/30 20:44 终端交接时状态

本次已经把 `style_id: "auto"` 从“只选择一个主旋律 style”扩展为“多 MIDI channel 分别路由、分别渲染 WAV、最后混音输出一个 MP3”的第一版底层能力。显式指定 Kong Audio GaoHu 风格的请求仍走原来的单 style 渲染路径。

注意：这里的 `auto_route_two_channel_debug_5s.zip` 只是内部最小验证用例，不是最终产品方案。它故意做成两个 MIDI channel，是为了快速证明“一首 MIDI 内的不同 channel 可以路由到不同插件并混音”这件事已经跑通。最终业务目标仍以 `云端DAW音频工作站引擎.docx` 为准，路由依据应切换到 `config/instrument_mapping.deploy.json` 中从 Word 表格抽取出的 137 条映射，接口保持当前 `/v1/render`、zip 输入和 `mp3_file.base64` 返回不变。

最新干净交付镜像：

```text
mgsc_daw_service:v6.4.37
image id: sha256:ca4c6a1e2b72125db7dc3c32194f2e8ac07fc0e495a8f51b89ff8b50d7028ded
```

镜像导出目录：

```text
C:\work\workspace_own\workspace_carla\docker_images
```

需要拷贝到 Ubuntu 的文件：

```text
deploy_mgsc_daw_service.sh
mgsc_daw_service_v6.4.37.tar.part01
mgsc_daw_service_v6.4.37.tar.part02
mgsc_daw_service_v6.4.37.tar.part03
SHA256SUMS_v6.4.37.txt
SHA256SUMS_v6.4.37_parts.txt
MANIFEST_v6.4.37.txt
test_zips_v6.4.37.zip
```

完整 tar：

```text
mgsc_daw_service_v6.4.37.tar
size: 4140712448 bytes
sha256: 0915672C17A9C7B42FEC9241C4175B5954A2ADC3A2850E951986827DCBA2A0AC
```

分片大小：

```text
part01: 1900000000 bytes
part02: 1900000000 bytes
part03: 340712448 bytes
```

已验证把三个分片按顺序拼接后的 SHA256 与完整 tar 一致。

重要构建说明：v6.4.37 是从 v6.4.36 基础镜像重新开干净 staging 容器后只复制代码和脚本提交的；提交前已清理 `/wineprefix`、`/home/runtime/output`、`/home/runtime/logs`、`/home/runtime/service_work`，避免把运行态 Wine 前缀和历史音频输出固化进镜像。部署后第一次启动服务会重新从 `/home/runtime/wineprefix_seed` 初始化 `/wineprefix`。

v6.4.37 干净容器验证结果：

| 测试 | 结果 | MP3大小 | WAV RMS | WAV peak |
| --- | --- | ---: | ---: | ---: |
| `kong_gaohu_sus_leg_mw_debug_10s.zip` | 显式 Kong 路径通过 | 334411 | 1350 | 7371 |
| `auto_route_two_channel_debug_5s.zip` | 内部最小多路由验证通过 | 126476 | 2213 | 12329 |

`auto_route_two_channel_debug_5s.zip` 的自动路由结果：

| MIDI channel | GM Program | 路由 style | 插件 |
| ---: | ---: | --- | --- |
| 1 | 0 | `keyzone_steinway_piano` | `vst_keyzone_classic` |
| 2 | 64 | `dsk_soprano_sax` | `vst_dsk_saxophones` |

下一步从这里继续：

1. 把当前 `style_id: "auto"` 的多通道路由从 `plugins.deploy.json` 中的 `style.gm_programs` 扩展到 `config/instrument_mapping.deploy.json` 的完整 137 条文档映射。
2. 等用户确认第 5 节中的文档表格问题后，修正或兼容映射。
3. 建立 Kong YangQin、GuZheng 状态文件，再接入文档中的 MIDI 15、107。
4. 每次扩展后继续做 Kong GaoHu 4 风格回归，不能影响当前已跑通方案。

## 1. 最终目标

按照 `云端DAW音频工作站引擎.docx` 实现云端 DAW 音频工作站引擎。

目标能力如下：

1. 在 Ubuntu 服务器上通过 Docker 镜像部署 FastAPI 服务。
2. 部署时只需要拷贝镜像和部署脚本，脚本创建容器 `mgsc_daw_service_kom`。
3. 进入容器后执行 `python mgsc_daw_service.py` 启动服务。
4. 客户端执行 `python mgsc_daw_client.py`，把指定 zip 发送给服务端。
5. 服务端渲染 MIDI，返回 MP3 的 base64 数据。
6. 客户端收到返回后直接保存 MP3 文件。
7. 后续最终要按文档中的 MIDI Bank、Program、云端音源映射，实现多插件音源路由和混音。

输出文件命名规则固定为：

```text
<MIDI文件名>_<插件或风格名>_<yyyyMMddHHmm>.mp3
```

示例：

```text
刀剑如梦_Kong_GaoHu_Tremolo_Vel_1_202604271839.mp3
```

## 2. 当前已经完成的状态

当前代码主线最近关键提交：

```text
13a834f 预留Steinberg插件物化逻辑
054c6ce 补充x64插件预研结果
fc5c17d 验证Keyzone插件接入路径
b2eed1c 生成云端DAW音源映射配置
c1dc726 固化输出命名和中文文件名兼容
```

当前已完成能力：

1. FastAPI 服务 `/v1/render` 可接收 zip 并渲染音频。
2. 服务端返回中包含 `mp3_file.base64`。
3. `mgsc_daw_client.py` 可从 base64 保存 MP3。
4. `mgsc_daw_client.py` 已兼容 Python 3.6。
5. 部署脚本支持外部端口映射到容器内部服务端口。
6. 输出 MP3/WAV 文件名已使用 MIDI 原始文件名、插件或风格名、当前时间。
7. zip 内中文 MIDI 文件名已做常见编码恢复，能保留中文名。
8. `Musyng_Kite.sf2` 已接入为 `sf2_musyng_kite`。
9. Kong Audio 当前 4 个高胡风格已验证通过，音效正确。
10. v6.4.36 镜像已补充 x64 Wine bridge，可加载 Keyzone Classic、DSK Saxophones、Sonatina Orchestra。
11. Keyzone、DSK、Sonatina 已按文档中本地存在的 VST2 预设接入 20 个 style，用于后续自动路由。
12. 已新增显式可选的 `style_id: "auto"` 自动路由第一阶段，按主旋律 channel 的 GM Program 选择 style。
13. v6.4.37 已新增 `style_id: "auto"` 多通道路由第一版：每个有音符的 MIDI channel 单独匹配 style，分别生成临时 MIDI/WAV，再用 ffmpeg 混成最终 MP3，API 返回仍包含 `mp3_file.base64`。

当前服务配置中已正式接入：

```text
插件：kong_qin_rv
风格：
  kong_gaohu_sus_leg_mw
  kong_gaohu_stac_1
  kong_gaohu_trill_vel_1
  kong_gaohu_tremolo_vel_1

插件：sf2_musyng_kite
风格：
  sf2_musyng_kite_gm

插件：vst_keyzone_classic
风格：
  keyzone_steinway_piano

插件：vst_dsk_saxophones
风格：
  dsk_soprano_sax

插件：vst_sonatina_orchestra
风格：
  sonatina_solo_violin
```

## 3. 当前可部署镜像状态

当前可部署镜像版本：

```text
mgsc_daw_service:v6.4.37
```

镜像导出目录：

```text
C:\work\workspace_own\workspace_carla\docker_images
```

主要交付文件：

```text
deploy_mgsc_daw_service.sh
mgsc_daw_service_v6.4.37.tar.part01
mgsc_daw_service_v6.4.37.tar.part02
mgsc_daw_service_v6.4.37.tar.part03
SHA256SUMS_v6.4.37.txt
SHA256SUMS_v6.4.37_parts.txt
MANIFEST_v6.4.37.txt
test_zips_v6.4.37.zip
```

Ubuntu 合并镜像：

```bash
cat mgsc_daw_service_v6.4.37.tar.part* > mgsc_daw_service_v6.4.37.tar
sha256sum mgsc_daw_service_v6.4.37.tar
```

期望 SHA256：

```text
0915672C17A9C7B42FEC9241C4175B5954A2ADC3A2850E951986827DCBA2A0AC
```

部署示例：

```bash
chmod +x deploy_mgsc_daw_service.sh
HOST_PORT=8000 ./deploy_mgsc_daw_service.sh
docker exec -it mgsc_daw_service_kom bash
cd /home/workspace
python mgsc_daw_service.py
```

## 4. 文档中的最终插件和音源映射目标

`云端DAW音频工作站引擎.docx` 的核心表格定义了 137 条映射：

1. 128 个 GM 普通音色，Bank 0，Program 0-127。
2. 9 个鼓组音色，Bank 128。

云端目标音源分布：

| 云端音源 | 数量 | 本地资产状态 | 当前服务状态 |
| --- | ---: | --- | --- |
| Musyng_Kite | 111 | 已有 `Musyng_Kite.sf2` | 已接入并验证 |
| Sonatina Orchestra | 17 | 已有 DLL、MSE、预设 txt | 已接入 15 个唯一 style |
| Keyzone Classic | 5 | 已有 DLL、MSE、预设 txt | 已接入 3 个唯一 style |
| Kong | 2 | 已有扬琴、古筝库 | 当前只正式接入高胡 4 风格，扬琴和筝待建状态 |
| DSK Saxophones | 2 | 已有 DLL、MSE、预设 txt | 已接入 2 个唯一 style |

本地资产主要路径：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\soundfont2\Musyng_Kite.sf2
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\Keyzone Classic
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\Sonatina Orchestra
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\DSK Saxophones
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\kong_audio\qin_rv_v2_2
```

当前已经把 Word 文档中的映射表抽取成结构化配置：

```text
config\instrument_mapping.deploy.json
```

配置生成工具：

```text
tools\build_instrument_mapping_from_docx.py
```

重新生成命令：

```powershell
python tools\build_instrument_mapping_from_docx.py
```

当前生成结果：

```text
mapping_count: 137
normal_gm_count: 128
drum_bank_count: 9
needs_confirmation_count: 15
plugin_counts:
  DSK Saxophones: 2
  Keyzone Classic: 5
  Musyng_Kite: 111
  Sonatina Orchestra: 17
  kong: 2
```

说明：该配置目前只作为后续开发依据，当前 FastAPI 服务不会自动加载它，因此不会影响已经跑通的 Kong GaoHu 4 风格。

## 5. 需要确认或兼容的表格问题

这些问题已反馈给用户，用户正在确认。后续实现时需要按确认结果修正文档或在配置中做兼容映射。

### 5.1 Sonatina Orchestra

1. MIDI 40，小提琴

文档写法：

```text
Sonatina violin / Solo Violin
```

本地实际路径：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\Sonatina Orchestra\Sonatina Orchestra\Sonatina Violin\Solo Violin.txt
```

问题：`violin` 大小写不一致，Linux 容器路径可能区分大小写，建议统一为 `Sonatina Violin`。

2. MIDI 46，竖琴

文档写法：

```text
Sonatina Harp / default group
```

本地实际路径：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\Sonatina Orchestra\Sonatina Orchestra\Sonatina Harp\Default Group.txt
```

问题：`default group` 大小写不一致，建议统一为 `Default Group`。

3. MIDI 57，长号

文档写法：

```text
Sonatina Trombone / Tensor Trombone
```

本地实际路径：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\Sonatina Orchestra\Sonatina Orchestra\Sonatina Trombone\Tenor Trombone.txt
```

问题：`Tensor Trombone` 应该是 `Tenor Trombone`。

4. MIDI 58，大号

文档写法：

```text
Sonatina Tuba / Tuba  / Sustain
```

本地实际路径：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\Sonatina Orchestra\Sonatina Orchestra\Sonatina Tuba\Tuba Sustain.txt
```

问题：文档里多了 `/` 和多余空格，应兼容或修正为 `Tuba Sustain`。

5. MIDI 60，圆号

文档写法：

```text
Sonatina Horn / Solo  / Horn
```

本地实际路径：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\Sonatina Orchestra\Sonatina Orchestra\Sonatina Horn\Solo Horn.txt
```

问题：文档里多了 `/` 和多余空格，应兼容或修正为 `Solo Horn`。

6. MIDI 70，大管

文档写法：

```text
Sonatina Bassoom / Solo Bassoon
```

本地实际路径：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\Sonatina Orchestra\Sonatina Orchestra\Sonatina Bassoon\Solo Bassoon.txt
```

问题：`Bassoom` 应该是 `Bassoon`。

7. MIDI 71，单簧管

文档写法：

```text
Sonatina Clarinet / Solo / Clarinet
```

本地实际路径：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\Sonatina Orchestra\Sonatina Orchestra\Sonatina Clarinet\Solo Clarinet.txt
```

问题：文档里多了 `/`，应兼容或修正为 `Solo Clarinet`。

### 5.2 DSK Saxophones

1. MIDI 64，高音萨克斯

文档写法：

```text
DSK Saxophones / ？ / Soprano /  Sax
```

本地实际路径：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\DSK Saxophones\DSK Saxophones\Soprano Sax.txt
```

问题：Bank 写为 `？`，Program 里多了 `/` 和多余空格，应兼容或修正为 `Soprano Sax`。

2. MIDI 66，次中音萨克斯

文档写法：

```text
DSK Saxophones / ？ / Tenor Sax
```

本地实际路径：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\DSK Saxophones\DSK Saxophones\Tenor Sax.txt
```

问题：Bank 写为 `？`，后续配置中不能直接保留 `？`，需要表达为无 Bank 或插件预设名。

### 5.3 Keyzone Classic

以下 5 条文档中 Bank 都写为 `？`，本地实际是插件预设文件，不是 SF2 Bank/Program。

本地目录：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\Keyzone Classic\Keyzone Classic
```

本地已有预设：

```text
Basic Electric Piano.txt
Keyzone Piano.txt
Rhodes Piano.txt
Steinway Piano.txt
Yamaha Grand Piano.txt
```

涉及条目：

| MIDI | 用户音源名 | 文档 Program | 本地文件 |
| ---: | --- | --- | --- |
| 0 | 大钢琴 Acoustic Grand Piano | Steinway Piano | Steinway Piano.txt |
| 1 | 立式钢琴 | Yamaha Grand Piano | Yamaha Grand Piano.txt |
| 2 | 电钢琴 | Basic Electric Piano | Basic Electric Piano.txt |
| 4 | 电钢琴1 | Basic Electric Piano | Basic Electric Piano.txt |
| 5 | 电钢琴2 | Basic Electric Piano | Basic Electric Piano.txt |

问题：Bank 为 `？`，后续配置中要表达为插件预设，不是 SF2 Bank。

### 5.4 Kong

1. MIDI 15，扬琴

文档写法：

```text
kong / yangqin / 02 Sus_mp
```

本地实际目录：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\kong_audio\qin_rv_v2_2\library\ChineeYangQin
```

问题：

1. `yangqin` 是逻辑名，不是本地真实目录名。
2. 当前服务只验证了 Kong GaoHu 4 个状态，尚未建立 YangQin 状态文件。

2. MIDI 107，筝

文档写法：

```text
kong / chineseGuZheng / 03 Sus_Shake_2
```

本地可能目录：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\kong_audio\qin_rv_v2_2\library\ChineeGuZheng_Classic
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\kong_audio\qin_rv_v2_2\library\ChineeGuZheng_II
```

问题：

1. `chineseGuZheng` 是逻辑名，不是本地真实目录名。
2. 需要确认最终用 `ChineeGuZheng_Classic` 还是 `ChineeGuZheng_II`。
3. 从文件名看，`ChineeGuZheng_Classic` 中有 `GuZheng_Shake_2.KAS`，更接近文档中的 `03 Sus_Shake_2`。
4. 当前服务尚未建立 GuZheng 状态文件。

### 5.5 其他文档一致性问题

1. 正文说 Bank 128 有 10 个鼓组 preset，但表格实际只有 9 行。
2. MIDI 65，中音萨克斯，文档中 MIDI id 是 `65`，云端 Program 是 `65`，但 Web Program 写成 `63`。需要确认 Web Program 是否应改为 `65`。

## 6. 当前技术缺口

当前服务模式：

```text
一次请求选择一个 plugin_id 或 style_id，然后用这个插件或风格渲染整首 MIDI。
```

最终文档目标要求：

```text
按 MIDI Bank、Program、Channel 自动路由到不同云端音源插件，再把多个渲染结果混音为一个 MP3。
```

因此后续主要工作不是继续找资产，而是实现：

1. 结构化音源映射配置。
2. MIDI 解析和轨道/通道/Program 识别。
3. 按映射选择插件和预设。
4. 对不同插件分轨渲染。
5. 多轨 WAV 混音。
6. 最终 MP3 输出。
7. 保持当前 Kong GaoHu 4 风格方案不受影响。

## 6.1 2026/04/30 x64 VST2 插件预研结果

已先在临时容器 `mgsc_win64_bridge_probe` 中验证 Keyzone Classic、DSK Saxophones、Sonatina Orchestra，后续已固化到 v6.4.36 镜像。

结论：

1. `Keyzone Classic.dll`、`DSK Saxophones.dll`、`Sonatina Orchestra.dll` 都是 x64 DLL。
2. `mgsc_daw_service:v6.4.36` 已在 v6.4.33 基础上补充 `carla-bridge-win64.exe` 和 `jackbridge-wine64.dll`，同时保留 win32 bridge，避免影响 Kong GaoHu。
3. Keyzone Classic、DSK Saxophones、Sonatina Orchestra 已在 v6.4.36 测试容器中由 FastAPI 调用验证。
4. Keyzone 不能直接从 `/plugin_assets/keyzone` 这类挂载路径稳定加载；复制到 Wine C 盘路径后可以正常加载。DSK 和 Sonatina 也按同样方式验证通过：

```text
/wineprefix/drive_c/VSTPlugins/Keyzone Classic/Keyzone Classic.dll
/wineprefix/drive_c/VSTPlugins/DSK Saxophones/DSK Saxophones.dll
/wineprefix/drive_c/VSTPlugins/Sonatina Orchestra/Sonatina Orchestra.dll
```

5. Keyzone、DSK、Sonatina 的 `.txt` 预设可以封装成 `.carxs` 后通过 `--plugin-state` 加载。
6. 5 秒单音渲染已产生非静音 WAV：

| 插件 | 预设 | RMS | peak |
| --- | --- | ---: | ---: |
| Keyzone Classic | Steinway Piano | 约 2332 | 约 13536 |
| DSK Saxophones | Soprano Sax | 约 2821 | 约 13941 |
| Sonatina Orchestra | Solo Violin | 约 1530 | 约 6099 |

新增工具：

```text
tools\build_vst2_chunk_state.py
```

用途：把 Keyzone、DSK、Sonatina 这类插件的 base64 chunk `.txt` 预设封装为 Carla `.carxs` 状态文件。

示例：

```powershell
python tools\build_vst2_chunk_state.py `
  --preset-txt "C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\Keyzone Classic\Keyzone Classic\Steinway Piano.txt" `
  --output output\keyzone_win64_probe\keyzone_steinway_tool.carxs `
  --plugin-name "Keyzone Classic" `
  --binary "/wineprefix/drive_c/VSTPlugins/Keyzone Classic/Keyzone Classic.dll" `
  --force
```

已修复工具：

```text
tools\dump_plugin_parameters.py
```

修复内容：

1. 适配 `render_midi_to_mp3.py` 当前的 `resolve_script_paths(args)` 签名。
2. 增加 `--plugin-load-mode load_file`，支持 Linux 容器通过 Carla Wine bridge 加载 Windows VST。

v6.4.36 FastAPI 抽测结果：

| 风格 | MP3大小 | WAV RMS | WAV peak |
| --- | ---: | ---: | ---: |
| keyzone_steinway_piano | 206933 | 2335 | 13536 |
| dsk_soprano_sax | 209023 | 2829 | 13941 |
| sonatina_solo_violin | 209023 | 1529 | 6099 |
| keyzone_yamaha_grand_piano | 207978 | 2318 | 11766 |
| dsk_tenor_sax | 210068 | 4369 | 20513 |
| sonatina_flute | 210068 | 3595 | 11352 |
| sonatina_solo_horn | 209023 | 2655 | 10615 |
| auto_program0 -> keyzone_steinway_piano | 167227 | 1243 | 11380 |

v6.4.36 Kong GaoHu 回归结果：

| 风格 | 截断时长 | MP3大小 | WAV RMS | WAV peak |
| --- | ---: | ---: | ---: | ---: |
| kong_gaohu_sus_leg_mw | 45 秒 | 1867276 | 916 | 6486 |
| kong_gaohu_stac_1 | 45 秒 | 1867276 | 841 | 8514 |
| kong_gaohu_tremolo_vel_1 | 45 秒 | 1867276 | 704 | 6861 |
| kong_gaohu_trill_vel_1 | 45 秒 | 1866231 | 875 | 5684 |
| kong_gaohu_sus_leg_mw | 5 秒 | 210068 | 1569 | 7371 |

## 7. 下一步任务计划

建议下一步按以下顺序推进。

### 7.1 等待用户确认文档问题

需要确认第 5 节中的问题，尤其是：

1. `Tensor Trombone` 是否修正为 `Tenor Trombone`。
2. `Sonatina Bassoom` 是否修正为 `Sonatina Bassoon`。
3. `default group` 是否修正为 `Default Group`。
4. `Tuba  / Sustain` 是否修正为 `Tuba Sustain`。
5. `Solo  / Horn` 是否修正为 `Solo Horn`。
6. `Solo / Clarinet` 是否修正为 `Solo Clarinet`。
7. `Soprano /  Sax` 是否修正为 `Soprano Sax`。
8. `chineseGuZheng` 最终使用 `ChineeGuZheng_Classic` 还是 `ChineeGuZheng_II`。
9. Bank 128 鼓组到底是 9 个还是 10 个。
10. MIDI 65 中音萨克斯的 Web Program 是否应为 `65`。

### 7.2 建立结构化映射配置

建议新增配置，例如：

```text
config/instrument_mapping.deploy.json
```

内容从 Word 文档表格转换而来，并把第 5 节问题做成明确兼容映射。

### 7.3 扩展非 Kong 的 VST2 预设覆盖

v6.4.36 已完成的覆盖：

1. `Keyzone Classic`：3 个 style。
2. `DSK Saxophones`：2 个 style。
3. `Sonatina Orchestra`：15 个 style。

当前已经把文档中属于这三个插件且本地预设文件存在的条目接入为 20 个唯一 style，目的是验证 x64 bridge、Wine C 盘路径、`.txt` 预设封装 `.carxs`、FastAPI base64 返回链路全部可用。

已完成自动路由第一阶段：只有请求或 `conf.json` 显式传入 `style_id: "auto"` 时启用，根据主旋律 channel 的 MIDI Program Change 匹配 `style.gm_programs`，Program 0 测试包已自动路由到 `keyzone_steinway_piano`。不传 `auto` 时仍走原来的显式 `style_id` 逻辑。

下一步需要把自动路由从单 style 扩展为多插件分轨渲染和混音。每新增一组预设或路由规则后都要做：

1. 单音 MIDI 渲染测试。
2. FastAPI zip 调用测试。
3. 输出 MP3/WAV 文件名检查。
4. Kong GaoHu 4 个 zip 回归测试，确认原方案不受影响。

当前已经完成：

1. 在正式镜像构建流程中保留现有 win32 bridge。
2. 增加 win64 bridge：

```text
carla-bridge-win64.exe
jackbridge-wine64.dll
carla-discovery-win64.exe
```

3. 将 x64 插件复制到 Wine C 盘路径，例如：

```text
/wineprefix/drive_c/VSTPlugins/Keyzone Classic
/wineprefix/drive_c/VSTPlugins/DSK Saxophones
/wineprefix/drive_c/VSTPlugins/Sonatina Orchestra
```

`mgsc_daw_service.py` 已增加可选的 Steinberg VST 复制逻辑：如果启动时存在 `/home/workspace/assets/Steinberg/VstPlugins`，会把 `Keyzone Classic`、`DSK Saxophones`、`Sonatina Orchestra` 复制到 `/wineprefix/drive_c/VSTPlugins`。如果该目录不存在，会直接跳过，不影响当前 Kong GaoHu。

4. 启动服务时自动根据 `plugins.deploy.json` 的 `vst2_preset` 字段生成 `.carxs` 状态文件。

### 7.4 再接入 Kong 的扬琴和筝

原因：Kong 当前已经验证的是 GaoHu，扬琴和筝需要新建 Carla 状态文件，风险高于普通 preset 文件映射。

需要做：

1. 建立 `ChineeYangQin` 状态。
2. 建立 `ChineeGuZheng_Classic` 或 `ChineeGuZheng_II` 状态。
3. 确认文档中的 `02 Sus_mp`、`03 Sus_Shake_2` 在插件状态中正确选中。
4. 单独做 MIDI 渲染和 API 测试。
5. 再次回归 Kong GaoHu 4 风格。

### 7.5 实现多插件路由和混音

初步实现策略：

1. 解析 MIDI 的每个 channel 和 program change。
2. 根据 `instrument_mapping.deploy.json` 决定目标音源。
3. 将 MIDI 按目标音源拆分成多个临时 MIDI。
4. 分别调用现有渲染管线生成 WAV。
5. 使用 ffmpeg 或 Python 音频处理把 WAV 混音。
6. 统一导出最终 MP3。
7. API 返回仍保持 `mp3_file.base64`。

## 8. 重启后恢复工作入口

如果重启电脑或上下文丢失，按下面顺序恢复：

1. 打开工程：

```powershell
cd C:\work\workspace_own\workspace_carla\Carla-2.5.10
git status -sb
git log --oneline -5
```

2. 阅读本交接文档：

```text
docs\CLOUD_DAW_ENGINE_HANDOFF_CN.md
```

3. 阅读最终需求文档：

```text
C:\work\workspace_own\workspace_carla\doc\云端DAW音频工作站引擎.docx
```

4. 确认当前部署镜像：

```powershell
docker images mgsc_daw_service
```

5. 确认资产目录：

```powershell
Get-ChildItem C:\work\workspace_own\workspace_carla\mgsc_daw_assets
```

6. 如果继续开发插件映射，先不要修改当前 Kong GaoHu 4 风格的配置和状态文件。新增能力应通过新配置、新 style、新测试逐步接入。

## 9. 当前保护原则

1. 不影响当前已经跑通的 Kong Audio GaoHu 4 风格。
2. 不破坏 `mgsc_daw_service:v6.4.33` 作为上一版稳定版本；v6.4.36 是当前包含 x64 VST2 预设覆盖和自动路由第一阶段的交付版本。
3. 每次新增插件或路由能力，都必须先做单插件测试，再做 Kong 回归。
4. 文档中的逻辑音源名和本地真实目录名要分开记录，不能直接把 `？` 或逻辑名写进运行时路径。
5. 最终以 `云端DAW音频工作站引擎.docx` 为需求依据，但实现配置应使用经过确认和兼容后的结构化数据。
