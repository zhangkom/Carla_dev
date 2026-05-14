# 渲染性能与 GPU 加速可行性评估

日期：2026-05-14

## 1. 当前结论

当前 Carla 云端 DAW 服务的主要链路是：

```text
MIDI -> Carla/Wine -> VST 或 SF2 插件 -> WAV -> libmp3lame MP3 -> base64 JSON
```

基于现有代码、全量测试数据和官方资料，当前版本不适合把“生成 MP3”或“VST/SF2 渲染”直接迁移到 NVIDIA GPU：

- NVIDIA Video Codec SDK 的 NVENC/NVDEC 主要覆盖视频编解码，例如 H.264、HEVC、AV1，不覆盖 MP3 音频编码。
- FFmpeg 当前使用的 `libmp3lame` 是 MP3 音频编码器，`compression_level` 是 CPU 编码算法复杂度参数。
- 当前接入的 Keyzone Classic、Kong Qin_RV、Sonatina Orchestra、DSK Saxophones、Musyng Kite SF2 没有暴露可由服务端统一调用的 CUDA/GPU 渲染能力。

因此，GPU 对当前正式需求中的 128 组普通音色和 9 组鼓组音色帮助有限。继续优化时应优先处理 CPU/Wine/插件加载、Dummy 渲染推进、MP3 编码参数和多轨并行调度。

## 2. 已有性能基线

最近一次 137 条需求映射全量测试：

```text
测试目录：C:\work\workspace_own\workspace_carla\output\candidate_acceptance_daojian_full_137_6.5.13_20260513_112834
服务地址：http://127.0.0.1:18013/mgsc_daw_service/v1/render
结果：通过 137，失败 0，跳过 0
```

按插件家族聚合的端到端耗时如下：

| 插件家族 | 数量 | 平均耗时 | 中位数 | 最快 | 最慢 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Keyzone Classic | 5 | 16.44s | 16.06s | 16.02s | 17.91s |
| Kong Qin_RV | 2 | 15.38s | 15.38s | 14.32s | 16.45s |
| Sonatina Orchestra | 17 | 10.84s | 10.82s | 10.05s | 12.06s |
| DSK Saxophones | 2 | 10.43s | 10.43s | 10.39s | 10.47s |
| Musyng Kite SF2 | 111 | 4.50s | 4.52s | 3.02s | 5.79s |

整体平均约 5.97s，最慢约 17.91s。当前已经不存在早期 Kong Audio 单个完整 MIDI 接近 184s 的问题。

## 3. 已完成的有效优化

### 3.1 Dummy nosleep 加速

早期瓶颈是 Carla Dummy 驱动按真实音频周期 sleep，导致完整 MIDI 渲染耗时接近 MIDI 时长。当前已通过 `CARLA_DUMMY_NOSLEEP` 跳过 Dummy 周期 sleep，把大部分 SF2/Kong 路径降到秒级或十几秒级。

### 3.2 Keyzone 专用中间档

Keyzone 在 Ubuntu 上直接 nosleep 曾出现静音，因此新增了按插件设置的中间档：

```bash
MUSIC_SERVICE_DUMMY_SLEEP_DIVISOR_BY_PLUGIN=vst_keyzone_classic=16
MUSIC_SERVICE_RENDER_WARMUP_SECONDS_BY_PLUGIN=vst_keyzone_classic=2
```

该策略把原先约 198s 的 Keyzone 完整 MIDI 渲染降低到 16-18s，并保持有声。

### 3.3 MP3 编码参数收敛

当前默认：

```json
{
  "mp3_mode": "cbr",
  "mp3_bitrate": "320k",
  "mp3_compression_level": 7
}
```

该参数优先保证音质和商业交付稳定性。若后续对耗时更敏感，可单独评估 `mp3_compression_level=8` 或 `9`，但需要重新做听感和音量回归，不建议直接改默认值。

## 4. GPU 加速判断

### 4.1 MP3 编码

当前 MP3 使用 FFmpeg `libmp3lame`。FFmpeg 官方文档将 `libmp3lame`列在音频编码器中，并说明 `compression_level` 取值 0-9，0 质量最高但最慢，9 最快但质量最差。

NVIDIA 官方 FFmpeg GPU 加速文档说明 NVENC/NVDEC 面向视频编解码，NVENC 支持的 FFmpeg 编码器是 `h264_nvenc`、`hevc_nvenc`、`av1_nvenc`。这些不适用于 MP3。

2026-05-14 复查本机 FFmpeg 8.0 encoder 列表：

```text
V....D av1_nvenc   NVIDIA NVENC av1 encoder
V....D h264_nvenc  NVIDIA NVENC H.264 encoder
V....D hevc_nvenc  NVIDIA NVENC hevc encoder
A....D libmp3lame  libmp3lame MP3 encoder
A....D mp3_mf      MP3 via MediaFoundation
```

其中 `V` 表示视频编码器，`A` 表示音频编码器。`mp3_mf` 是 Windows MediaFoundation 路径，不是 NVIDIA GPU 路径，也不适用于 Ubuntu 容器部署。

结论：MP3 编码不能通过当前 NVIDIA P40 或 RTX4090 的 NVENC 直接加速，也没有可在 Ubuntu 容器中替换 `libmp3lame` 的 NVIDIA MP3 编码器。

### 4.2 VST/SF2 渲染

VST/SF2 音频渲染是否能使用 GPU，取决于插件自身是否实现并暴露 GPU 计算路径。当前正式接入的插件没有这种可配置能力，Carla 也只是宿主和音频图调度层，不能替插件自动把 DSP 计算迁移到 GPU。

结论：当前插件渲染不具备通用 GPU 加速入口。

### 4.3 什么时候 GPU 才可能有价值

只有以下场景才值得继续考虑 GPU：

- 未来输出从 MP3 音频扩展到视频封装或音画合成，且视频编码使用 H.264/HEVC/AV1。
- 未来换用明确支持 GPU/CUDA 的音频插件或推理模型，例如 AI 音色生成、神经网络混音、音频修复等。
- 未来增加音频 AI 后处理模型，并且该模型本身支持 GPU 推理。

## 5. 后续优化建议

### 优先级 1：保持当前稳定加速配置

继续保留：

```bash
MUSIC_SERVICE_DUMMY_NOSLEEP=1
MUSIC_SERVICE_DUMMY_NOSLEEP_DISABLE_PLUGINS=vst_keyzone_classic
MUSIC_SERVICE_DUMMY_SLEEP_DIVISOR_BY_PLUGIN=vst_keyzone_classic=16
MUSIC_SERVICE_RENDER_WARMUP_SECONDS_BY_PLUGIN=vst_keyzone_classic=2
```

这是目前音质和耗时之间最稳的组合。

### 优先级 2：按插件做性能回归矩阵

对 Keyzone、Kong、Sonatina、DSK、Musyng Kite 分别保留一组固定测试包，记录：

- 客户端总耗时
- 服务端 `elapsed_seconds`
- `renderer_timings.record_audio_seconds`
- `renderer_timings.ffmpeg_mp3_seconds`
- MP3 `mean_volume` 和 `max_volume`

每次改 Dummy、MP3 编码或 Wine 入口后都跑这组矩阵。

### 优先级 3：多轨并行渲染预研

当前多轨混音路径是逐轨渲染 WAV 后再混音。对 5-6 轨以上的请求，理论上可以并行启动多个 Carla 子进程缩短墙钟时间。

2026-05-14 已先把服务端实现为默认关闭的安全开关：

```bash
MUSIC_SERVICE_PARALLEL_ROUTES=1
MUSIC_SERVICE_PARALLEL_ROUTE_WORKERS=2
```

不开 `MUSIC_SERVICE_PARALLEL_ROUTES` 时仍保持原串行行为。打开后仅影响多轨手工路由或 auto 多通道路由，单轨请求不变。该方案还需要单独验证：

- 同一个 Wine prefix 下并行加载多个 VST 是否稳定。
- Kong、Keyzone、Sonatina 是否存在资源锁或授权文件冲突。
- 并行数对内存占用和 CPU 抢占的影响。

验证通过后才能在部署脚本里默认打开；在此之前只作为性能实验开关。

2026-05-14 使用本地 `mgsc_daw_service:6.5.13.2019` 镜像加当前工作区代码，在 6 轨 SF2 混合包上做了第一轮对照：

| 模式 | workers | 客户端耗时 | route_count | mean dB | max dB | 结论 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 串行 | 1 | 32.720s | 6 | -25.8 | -6.7 | 基线正常 |
| 并行 | 2 | 17.833s | 6 | -25.8 | -6.7 | 明显加速 |
| 并行 | 3 | 13.507s | 6 | -25.8 | -6.7 | 继续加速 |
| 并行 | 4 | 12.957s | 6 | -25.8 | -6.7 | 收益开始收敛 |

当前只证明 SF2 多轨场景有效。VST 混合、Kong、Keyzone、Sonatina 并发稳定性还需要继续验证，所以正式部署默认仍为关闭。

### 优先级 4：验收输出减重

已优化 `tools/run_remote_acceptance.py`：默认不再把完整 `mp3_file.base64` 写入 `responses/*.json`，而是在解出 MP3 后保存脱敏响应。需要保留完整响应时可加：

```bash
--keep-response-base64
```

这会显著减少全量 137 包验收输出目录体积。

## 6. 参考资料

- NVIDIA FFmpeg GPU 加速官方文档：<https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/ffmpeg-with-nvidia-gpu/index.html>
- NVIDIA Video Codec SDK 官方说明：<https://developer.nvidia.com/video-codec-sdk>
- FFmpeg Codecs 官方文档，libmp3lame：<https://ffmpeg.org/ffmpeg-codecs.html#libmp3lame>
