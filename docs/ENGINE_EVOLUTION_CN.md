<!--
/**
* File name: ENGINE_EVOLUTION_CN.md
* Brief: 云端 DAW 引擎演进记录
* Function:
*     记录 Carla 云端 DAW 服务从原始版本到当前版本的能力演进、优化方法和效果
* Author: 咪咕数创工程架构组
*     MGSC AI Software Architecture group
* Version: V2.5.10
* Date: 2026/05/06
*/
-->

# 云端 DAW 引擎演进与优化记录

本文档用于说明这个项目从最初原型到当前版本的演进过程，重点回答四个问题：

1. 最开始的原始代码能做什么。
2. 每一阶段新增了什么能力。
3. 每一次优化是怎么做的，为什么这么做。
4. 当前版本相比原始版本，整体架构和性能提升到了什么程度。

相关文档：

- [CLOUD_DAW_ENGINE_HANDOFF_CN.md](/mnt/c/work/workspace_own/workspace_carla/Carla-2.5.10/docs/CLOUD_DAW_ENGINE_HANDOFF_CN.md)
- [API.md](/mnt/c/work/workspace_own/workspace_carla/Carla-2.5.10/docs/API.md)
- [PROJECT_STATUS_CN.md](/mnt/c/work/workspace_own/workspace_carla/Carla-2.5.10/docs/PROJECT_STATUS_CN.md)
- [MILESTONE_WINDOWS_KONG4_V2_2_CN.md](/mnt/c/work/workspace_own/workspace_carla/Carla-2.5.10/docs/MILESTONE_WINDOWS_KONG4_V2_2_CN.md)

## 1. 原始起点

最初的服务形态是一个 Carla 渲染脚本加一层简单的服务封装，核心链路是：

`MIDI -> Carla -> 插件 -> Audio Recorder -> WAV -> ffmpeg -> MP3`

原始版本的特点：

- 可以调用 Carla 渲染单个 MIDI。
- 以显式插件路径和显式状态文件为主。
- 主要面向本地验证，不是完整的云端 API 方案。
- 还没有 zip 输入协议。
- 还没有异步回调。
- 还没有完整的自动路由。
- 还没有成体系的 Docker/Wine 部署交付物。
- 最大性能问题是 Dummy 驱动下本质上按真实时间录音，长 MIDI 渲染耗时接近歌曲时长。

对应最早的基础提交：

- `6c53887 Initial Carla music service`

## 2. 演进总览

按能力演进，可以把项目分成 9 个阶段。

| 阶段 | 代表提交/版本 | 主要目标 |
| --- | --- | --- |
| 0 | `6c53887` | 建立 Carla 渲染服务基础骨架 |
| 1 | `245141d` 到 `0ff9a9f` | 打通 Windows 本机 Kong GaoHu 4 风格 |
| 2 | `0c4cfdf` 到 `38e05c3` | 迁移到 Ubuntu Docker/Wine，形成 v6.4.30/v6.4.31 部署主线 |
| 3 | `60e25f9` 到 `8e256ae` | 增加 MP3 base64、SoundFont、中文文件名、插件扩展 |
| 4 | `cf0b74e` 到 `531f6a1` | 完成 `style_id=auto` 的自动路由、多通道路由和 137 条映射 |
| 5 | `0fe50a4` 到 `29fb568` | 完成统一同步/异步接口和独立异步客户端 |
| 6 | `091e9d6` 到 `ccdfa84` | 把 async、auto route、output 处理模块化重构 |
| 7 | `ade9c78` | 打通 Dummy 离线渲染，解决实时录制性能瓶颈 |
| 8 | `51227f5` | 固化 v6.4.43 交付记录和部署默认版本 |

## 3. 分阶段详细演进

## 3.1 阶段 0：建立 Carla 渲染服务基础骨架

代表提交：

- `6c53887 Initial Carla music service`

新增内容：

- 建立 `music_service` 基本结构。
- 具备 Carla 调用、WAV/MP3 输出的基本能力。
- 渲染链以单插件、单状态、单输出为核心。

局限：

- 主要是开发原型。
- 对业务输入格式支持有限。
- 没有自动选风格。
- 没有容器化交付。

## 3.2 阶段 1：Windows 本机验证 Kong GaoHu 4 风格

代表提交：

- `245141d Enable local Kong Audio plugin profile`
- `7a32833 Add GUI-authored render styles`
- `77caff3 Track style state binary compatibility`
- `d345557 Add MIDI preprocessing policy`
- `fe633a3 Add render timing logs`
- `f2b211a Use high quality MP3 encoding defaults`
- `ab90913 Write renders to dated output files`
- `0ff9a9f 保存Windows本机Kong四风格阶段成果`

这一阶段解决的问题：

- 把 Kong Audio Qin_RV 正式接进 Carla。
- 在 Carla GUI 中保存 4 个已经验证有声的 GaoHu 风格状态。
- 建立 `style_id -> plugin + state` 的风格组织方式。
- 加入 MIDI 预处理策略，避免 Program Change/Bank Select 干扰 Kong 状态。
- 增加基础 timing 统计，开始知道时间花在哪。

新增能力：

- `kong_gaohu_sus_leg_mw`
- `kong_gaohu_stac_1`
- `kong_gaohu_trill_vel_1`
- `kong_gaohu_tremolo_vel_1`

优化方法：

1. 把 GUI 中已经验证过的插件状态导出为 `.carxs`，避免运行时临时调参。
2. 用 MIDI policy 删除会破坏 Kong 状态的事件。
3. 输出命名加时间戳，避免覆盖历史结果。
4. MP3 编码参数提升为高质量默认值。

效果：

- Windows 本机 4 个 Kong GaoHu 风格都能稳定发声。
- 业务风格的概念正式成型。

## 3.3 阶段 2：迁移到 Ubuntu Docker/Wine

代表提交：

- `0c4cfdf 启动Ubuntu Wine镜像迁移原型`
- `2a41b40 修正Wine原型中的ffmpeg挂载路径`
- `8dbe808 固化Ubuntu容器Wine桥接渲染方案`
- `32d8f13 固化自包含 Ubuntu 部署镜像流程`
- `8882d34 固化 Ubuntu 部署的线程兼容参数`
- `f96edab 调整 native bridge 的 MP3 编码位置`
- `38e05c3 发布 v6.4.31 部署版本`

这一阶段解决的问题：

- 把原来依赖 Windows 本机的运行方案迁到 Ubuntu 服务器可部署形态。
- 在 Linux 下用 Carla + Wine bridge 加载 Windows VST。
- 形成镜像、部署脚本、运行目录三件套。

新增能力：

- Docker/Wine 容器部署。
- `deploy_mgsc_daw_service.sh` 部署脚本。
- 容器自包含运行目录：`output`、`logs`、`service_work`。
- Linux 原生 ffmpeg 编码路径。

优化方法：

1. 用 Linux Carla backend 驱动 Wine bridge，而不是在容器里再套一层 Windows Python 服务。
2. 把 MP3 编码尽量放回 Linux 侧，减少 Wine 路径的复杂度。
3. 修复线程和运行参数，保证 Docker 里桥接插件可以稳定启动。

效果：

- 项目从“本机验证工程”升级为“可部署服务”。

## 3.4 阶段 3：完善 API 输入输出与音源扩展

代表提交：

- `60e25f9 支持外部端口和MP3 Base64返回`
- `2eb8f66 接入Musyng Kite SoundFont渲染`
- `c1dc726 固化输出命名和中文文件名兼容`
- `b2eed1c 生成云端DAW音源映射配置`
- `fc5c17d 验证Keyzone插件接入路径`
- `054c6ce 补充x64插件预研结果`
- `13a834f 预留Steinberg插件物化逻辑`
- `8e256ae 固化v6.4.34多插件验证镜像`
- `6365aee 扩展v6.4.35的VST2预设覆盖`

这一阶段解决的问题：

- 服务结果需要直接返回给客户端，而不是只在磁盘落文件。
- 需要接入非 Kong 的音源，覆盖更多文档风格。
- 需要兼容中文文件名和更稳定的输出命名。

新增能力：

- 同步接口返回 `mp3_file.base64`。
- 接入 Musyng Kite SoundFont。
- 接入 Keyzone Classic、DSK Saxophones、Sonatina Orchestra 等非 Kong 路径。
- 准备音源映射配置，为后续 `style_id=auto` 打基础。

优化方法：

1. 把 MP3 直接 base64 返回，减少客户端二次取文件复杂度。
2. 输出文件名做安全清洗和中文兼容。
3. 预留 Steinberg VST 物化逻辑，使容器启动时能自动复制资源到 Wine 环境。

效果：

- 接口结果更接近正式云服务用法。
- 音源覆盖不再局限于 Kong GaoHu。

## 3.5 阶段 4：实现自动路由与文档映射

代表提交：

- `cf0b74e 增加v6.4.36自动路由第一阶段`
- `e82011d 实现v6.4.37自动多路由混音`
- `0beaa42 实现完整映射驱动自动路由`
- `878f194 增强自动路由Bank Program匹配`
- `bd7c80f 接入Kong扬琴和古筝自动路由`
- `95ea154 加固Kong音源库启动检测`
- `d4fb585 标记137条音源映射全部实现`
- `531f6a1 记录v6.4.38镜像交付信息`

这是业务能力提升最大的一段。

最初的 `auto` 只做主旋律 channel 的单路由，后来逐步演进为：

1. 从 Word 文档抽取完整 137 条 Bank/Program 映射。
2. 支持读取 MIDI 中的 Bank Select MSB/LSB + Program Change。
3. 支持多 MIDI channel 分别匹配不同 style。
4. 分轨渲染多个 WAV。
5. 用 ffmpeg 混音为最终一个 MP3。

优化方法：

1. 路由从局部 `gm_programs` 小表切到完整文档映射。
2. 匹配逻辑从 Program-only 扩展到 Bank/Program 联合匹配。
3. 自动路由不再强迫一首 MIDI 只选一个主风格，而是按通道拆开处理。
4. 用 `config/instrument_mapping.deploy.json` 把文档知识结构化，避免把业务规则写死在代码里。

效果：

- `style_id=auto` 从演示能力变成真正可用于生产的路由引擎。
- YangQin、GuZheng、Sonatina、DSK、Keyzone、Musyng Kite 等路径逐步接入。

## 3.6 阶段 5：统一同步/异步接口

代表提交：

- `0fe50a4 实现callback_url异步渲染回调`
- `22cfcf8 新增独立异步回调客户端`
- `29fb568 记录v6.4.40独立异步客户端镜像`

这一阶段解决的问题：

- 客户端不能总是阻塞等待完整渲染。
- 需要兼容 LMMS 老方案“提交任务后回调客户端”的使用方式。

最终收敛结果：

- 只保留 `/v1/render` 作为唯一业务入口。
- `callbackurl` 为空或不传：同步返回，直接带 `mp3_file.base64`。
- `callbackurl` 非空：异步 accepted，后台完成后 `POST application/json` 到回调地址。

优化方法：

1. 不恢复 LMMS 的旧路径，而是只借鉴其回调语义。
2. 同步和异步共用一套渲染主逻辑，不复制业务实现。
3. 增加独立异步客户端 `mgsc_daw_async_client.py`，便于本地回调验证。

效果：

- 服务接口对外变得统一。
- 兼顾同步调用和异步回调两类场景。

## 3.7 阶段 6：模块化重构

代表提交：

- `091e9d6 refactor: extract async render job handling`
- `ad9427e refactor: extract auto route planning`
- `ccdfa84 refactor: finalize async render output handling`

这一阶段不是加新业务，而是压低后续维护成本。

重构内容：

- `music_service/async_jobs.py`：抽出异步任务处理。
- `music_service/auto_routes.py`：抽出自动路由规划。
- `music_service/render_outputs.py`：抽出输出命名、MP3 base64、WAV 混音、MP3 编码、timing 摘要。

优化方法：

1. 把 `main.py` 里混在一起的流程拆成稳定模块。
2. 输出处理逻辑集中化，避免同步/异步、多路由/单路由重复维护。
3. 为后续性能优化创造更清晰的边界。

效果：

- `main.py` 复杂度下降。
- 后续改异步、改路由、改输出时不容易互相干扰。

## 3.8 阶段 7：解决“渲染时长接近歌曲时长”的核心性能问题

代表提交：

- `ade9c78 perf: enable offline dummy rendering`

这是当前最关键的性能优化。

### 3.8.1 原始瓶颈

在原始实现中，即便服务已经跑在 Docker/Wine 中，长 MIDI 渲染仍然很慢。根因不是：

- 不是 FastAPI 慢。
- 不是 Python 调用慢。
- 不是 ffmpeg 编码慢。

真正瓶颈是两层叠加：

1. `render_midi_to_mp3.py` 的录音等待逻辑按墙钟时间循环等待。
2. 更底层的 `CarlaEngineDummy` 自己也按每个音频周期剩余时间 `sleep`，本质上是在做“实时录音式渲染”。

所以 180 秒左右的 MIDI，渲染经常也要 180 秒左右。

### 3.8.2 第一步优化：transport frame 驱动等待

在 `render_midi_to_mp3.py` 中做了第一步替换：

- 不再单纯按 `time.sleep(total_seconds)` 思路等待。
- 改成看 `host.get_current_transport_frame()` 是否推进到目标帧数。
- 加入 `record_realtime_ratio`、`record_target_frames` 等指标。

作用：

- 先去掉上层额外的人工 sleep。
- 把“渲染慢”这个问题从黑盒变成可测问题。

这一步有帮助，但还不够。因为 Carla Dummy 引擎本身还在按真实时间推进。

### 3.8.3 第二步优化：Dummy 离线 freewheel

最终的关键改法在 `source/backend/engine/CarlaEngineDummy.cpp`：

1. 新增 `CARLA_DUMMY_OFFLINE` 开关。
2. Dummy 引擎启动时读取该开关。
3. 如果离线模式开启：
   - `isOffline()` 返回 `true`
   - 调用 `offlineModeChanged(true)`
   - 不再按每个音频周期剩余时间 `carla_msleep(...)`
4. 这样引擎就会尽可能快地推进 transport frame，而不是按真实时间等待。

同时在：

- `render_midi_to_mp3.py`
- `music_service/renderer.py`

里加了默认逻辑：只要 `audio.driver == Dummy`，就自动设置 `CARLA_DUMMY_OFFLINE=1`。

也就是说：

- 命令行直跑会自动启用离线模式。
- FastAPI 服务子进程也会自动启用离线模式。

### 3.8.4 性能效果

实测结果：

| 场景 | 优化前 | 优化后 |
| --- | --- | --- |
| `kong_gaohu_sus_leg_mw.zip` 同步 API 总耗时 | `~197.227s` | `~9.745s` |
| 同场景 `record_audio_seconds` | `~184.522s` | `~2.235s` |
| Kong 45 秒直跑预览 `record_audio_seconds` | `~45.135s` | `~0.442s` |
| `sf2_musyng_kite_daojian_20s.zip` 同步 API 总耗时 | 近实时级别 | `~3.844s` |

优化本质：

- 从“实时录音型渲染”切换为“离线 freewheel 渲染”。

这是当前项目里最重要的一次性能突破。

### 3.8.5 2026/05/06 修正：从 offline 改为 nosleep

复测发现，`CARLA_DUMMY_OFFLINE=1` 对 Musyng Kite/SF2 路径有效，但会让 Kong Audio 的 WAV 输出变成静音。因此 `v6.4.43` 只能作为失败实验记录，不能作为交付基线。

新的 `6.5.6.2016` 策略改成：

1. `CarlaEngineDummy` 增加 `CARLA_DUMMY_NOSLEEP`。
2. `isOffline()` 仍返回 `false`，不向插件广播 `offlineModeChanged(true)`。
3. 只跳过 Dummy 音频线程每个周期末尾的 `carla_msleep(...)`。
4. `render_midi_to_mp3.py` 在该开关开启时用 transport frame 推进量判断录音完成，而不是按墙钟时间等待。
5. `music_service/renderer.py` 只在 `MUSIC_SERVICE_DUMMY_NOSLEEP=1` 时把 `CARLA_DUMMY_NOSLEEP=1` 传给渲染子进程。
6. 2026-05-11 在 Ubuntu 上复现 `lmms_vst_keyzone_single.zip` 静音：开启 nosleep 时 `max_volume=-91.0 dB`，关闭 nosleep 后恢复到 `mean_volume=-26.5 dB`、`max_volume=-7.0 dB`。因此新增 `MUSIC_SERVICE_DUMMY_NOSLEEP_DISABLE_PLUGINS`，默认 `vst_keyzone_classic` 自动回退实时模式，Kong Audio/SF2 仍保留快速路径。

这相当于保留插件的“实时工作语义”，但去掉 Dummy 驱动的人为实时睡眠。Docker Desktop 验证结果：

| 场景 | v6.4.40 基线 | 6.5.6.2016 nosleep |
| --- | ---: | ---: |
| Kong 约 3 分钟 MIDI 同步总耗时 | 约 198-209s | 约 15-16s |
| Kong `record_audio_seconds` | 约 184.5s | 约 2.5-2.7s |
| Musyng Kite 20s 测试包同步总耗时 | 约 23.5s | 约 3.8s |

音量复核：

- Kong GaoHu 四个测试包均有声音，mean/max 音量与 `v6.4.40` 基线接近。
- Musyng Kite 测试包也有声音。

部署安全阀：

- 默认：`MUSIC_SERVICE_DUMMY_NOSLEEP=1`
- 默认禁用 nosleep 的插件：`MUSIC_SERVICE_DUMMY_NOSLEEP_DISABLE_PLUGINS=vst_keyzone_classic`
- 回退实时模式：`MUSIC_SERVICE_DUMMY_NOSLEEP=0`

## 4. 当前版本的整体能力

截至当前版本，项目已经具备：

- 基于 Carla + Docker/Wine 的 Ubuntu 服务器渲染服务
- `/v1/render` 统一同步/异步接口
- zip 输入，包含 MIDI + `conf.json`
- 同步返回 `mp3_file.base64`
- 异步 `callbackurl` 回调
- Kong GaoHu、YangQin、GuZheng
- Musyng Kite SoundFont
- Keyzone Classic、DSK Saxophones、Sonatina Orchestra
- `style_id=auto` 多通道路由、分轨渲染、混音输出
- 137 条文档映射落地
- 小于 2GB 分卷镜像交付
- Dummy nosleep 高速渲染，保留插件实时语义，避免 Kong Audio offline 静音

## 5. 当前仍然值得继续优化的方向

虽然最核心的性能问题已经解决，但还可以继续做：

1. 把镜像版本命名从 `v6.4.xx` 完整切换到日期版。
2. 补一份“函数调用流程图”文档，把接口入口、MIDI 预处理、路由、渲染、输出、异步回调用图画清楚。
3. 继续扩展文档中剩余风格的状态文件和验证样本。
4. 把容器内验证过的离线渲染流程重新在 Ubuntu 目标服务器上完整复验一次。

## 6. 阅读建议

如果是新接手开发，建议按这个顺序读：

1. 本文档：先理解全局演进和关键优化。
2. [API.md](/mnt/c/work/workspace_own/workspace_carla/Carla-2.5.10/docs/API.md)：理解对外协议。
3. [CLOUD_DAW_ENGINE_HANDOFF_CN.md](/mnt/c/work/workspace_own/workspace_carla/Carla-2.5.10/docs/CLOUD_DAW_ENGINE_HANDOFF_CN.md)：看每个检查点的部署和验证细节。
4. `music_service/main.py`、`async_jobs.py`、`auto_routes.py`、`render_outputs.py`：看业务主流程。
5. `render_midi_to_mp3.py` 和 `source/backend/engine/CarlaEngineDummy.cpp`：看当前性能优化的关键实现。

后续每次功能新增或性能优化，都建议继续往这份文档补一节，而不是只改交接记录。
