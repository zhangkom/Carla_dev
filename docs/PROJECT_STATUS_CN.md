<!--
/**
* File name: PROJECT_STATUS_CN.md
* Brief: MGSC DAW 项目文档
* Function:
*     记录云端 DAW 服务接口、部署、状态或开发规范
* Author: 软件工程架构组
*     MGSC AI Software Architecture group
* Version: V2.5.10
* Date: 2026/04/30
*/
-->

# Carla 音乐服务项目状态

更新时间：2026-04-28

## 目标

将原来基于 LMMS 的 MIDI 渲染方案迁移到 Carla，形成一个可服务化部署的音乐渲染系统。

当前总体路线：

- 先在 Windows 本机 GUI 环境验证 VST 插件、音色状态、MIDI 路由和音频输出。
- 再在 Windows 本机无 GUI 服务中通过 FastAPI 提供渲染接口。
- 后续把 Windows 上验证好的 Carla、插件、音色状态和服务封装到 Docker 镜像中。
- 最终在 Ubuntu 服务器上通过 Wine 加载 Windows VST2/VST3 插件，并向客户端提供 API。

客户端目标输入：

- 一个 zip 包。
- zip 包内包含一个 MIDI 文件。
- zip 包内包含一个 `conf.json`。

服务端目标输出：

- 生成 WAV 文件，作为无损中间结果和调试结果。
- 生成 320 kbps MP3 文件，保证常见音乐播放器可播放。
- 输出文件统一写入 `output` 目录。
- 服务日志统一写入 `logs/YYYY-MM-DD.log`。

## 目前已经完成

- 已确认技术路线：先 Windows GUI 调通，再 Windows 本机服务化，最后 Wine/Docker/Ubuntu 迁移。
- 已接入 Kong Audio `Qin_RV_x64.DLL`，插件路径为 `C:\VSTPlugins\KongAudio\Qin_RV_x64.DLL`。
- 已在 Carla GUI 中验证 Kong Audio 可以发声，并保存 4 个高胡风格状态。
- 已支持 `kong_gaohu_sus_leg_mw`，对应 `Kong_GaoHu_Sus_Leg_MW`。
- 已支持 `kong_gaohu_stac_1`，对应 `Kong_GaoHu_Stac_1`。
- 已支持 `kong_gaohu_trill_vel_1`，对应 `Kong_GaoHu_Trill_Vel_1`。
- 已支持 `kong_gaohu_tremolo_vel_1`，对应 `Kong_GaoHu_Tremolo_Vel_1`。
- 已实现 FastAPI 服务接口，包括 `/health`、`/v1/catalog`、`/v1/plugins`、`/v1/styles`、`/v1/render` 和输出文件下载。
- 已实现 zip 上传渲染流程，服务会从 zip 中自动读取 MIDI 文件和 `conf.json`。
- 已明确正式客户端参数不再暴露 `midi_source_channel`、`midi_target_channel`、`apply_midi_policy`、`max_seconds`、`vstConf`、`sf2Conf` 等 LMMS/调试字段。
- 已实现 MIDI 通道自动分析。以《刀剑如梦.mid》为例，服务能自动选择旋律源通道并映射到 Kong 插件需要的目标通道。
- 已实现 MIDI policy：删除 Program Change 和 Bank Select，避免 MIDI 覆盖 GUI 保存的插件音色状态。
- 已保留常用演奏控制事件，例如 ModWheel、Volume、Pan、Expression、Sustain、Pitch Bend、Aftertouch 等。
- 已实现输出命名规则：`midi原名_风格名_生成时间.mp3/.wav`。
- 已将 MP3 输出配置为 libmp3lame、320 kbps CBR、44.1 kHz、stereo、ID3v2.3。
- 已将 WAV 输出保留为 16-bit PCM、44.1 kHz、stereo。
- 已新增调用侧脚本 `tools/call_render_zip.py`，用于批量调用 zip 渲染接口并打印每个 MP3 的耗时。
- 已新增服务端按天日志，渲染请求、阶段耗时、输出路径和错误都会进入 `logs/YYYY-MM-DD.log`。
- 已新增 renderer 子进程实时日志，长时间渲染时会持续打印 `record_audio_progress`。
- 已新增 renderer 阶段排序日志，能直接看到 `top_stage`。
- 已新增 `record_audio_breakdown`，继续拆分 transport 录制阶段。
- 已用 Kong Audio 4 个风格重新跑过完整 zip 请求，全部生成 MP3 和 WAV。
- 已验证当前 180 秒左右耗时的主要来源不是插件加载，也不是 MP3 编码，而是实时录制等待。

当前性能结论：

- `transport_play_seconds` 约为 `0.000s`，说明播放启动函数本身不耗时。
- `record_audio_seconds` 约为 `184.5s`，是当前最大阶段。
- `record_idle_wall_seconds` 约为 `184.3s`。
- `record_idle_sleep_seconds` 约为 `184.2s`。
- `record_idle_engine_idle_seconds` 约为 `0.086s`。
- 因此当前耗时本质是 Carla 按 MIDI 实际时长实时播放并录 WAV，而不是某个 Python 或 Carla 启动函数阻塞。

## 下一步计划

- 固定 Windows 本机服务化版本，继续用 zip 输入和 Kong Audio 风格做回归验证。
- 补齐更多插件和风格，每个风格按“乐器 + 演奏法”保存 Carla `.carxs` 状态。
- 建立插件和风格配置清单，保证 `/v1/catalog` 能准确返回可用插件、类别、风格和 ready 状态。
- 增加批量渲染测试，覆盖多 MIDI、多风格、多插件场景。
- 继续记录每个阶段耗时，为后续性能优化建立基线。
- 研究 Carla 是否支持离线或非实时渲染路径，这是降低 180 秒实时录制耗时的核心方向。
- 验证当前 Kong Audio `.carxs` 中保存的 DLL 路径，迁移 Wine 前尽量统一保存为 `C:\VSTPlugins\KongAudio\Qin_RV_x64.DLL`。
- 开始 Wine 容器验证，把 Carla Windows 运行环境、Kong 插件、Kong Library、ffmpeg 和 Python 服务放进镜像。
- 在 Ubuntu Docker 环境中验证 Wine 是否能稳定加载 Kong Audio 并完成 MIDI 到 WAV/MP3 的渲染。
- 明确插件二进制、采样库、授权文件和输出目录的挂载策略，避免把大文件或授权内容提交到 Git。
- 完成部署文档，形成 Windows 调试、Docker 构建、Ubuntu 部署和 API 调用的完整流程。
