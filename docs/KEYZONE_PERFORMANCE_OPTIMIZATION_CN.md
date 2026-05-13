# Keyzone Classic 性能优化记录

日期：2026-05-13

## 当前问题

`vst_keyzone_classic` 在 Ubuntu 18003 上曾为了避免静音，默认通过
`MUSIC_SERVICE_DUMMY_NOSLEEP_DISABLE_PLUGINS=vst_keyzone_classic` 回退实时渲染。

已验证结果：

- Keyzone 单轨非静音，但完整《刀剑如梦》MIDI 耗时约 198-201 秒。
- 开启完全 `CARLA_DUMMY_NOSLEEP=1` 时可高速完成，但 Ubuntu 上 Keyzone 输出接近静音。
- Kong GaoHu、Musyng Kite、Sonatina、DSK 等路径仍可使用 nosleep 加速。

## 本轮优化思路

原先只有两档：

1. 实时模式：每个 Dummy 音频周期睡满剩余时间，声音稳定但耗时等于 MIDI 时长。
2. nosleep 模式：完全跳过周期 sleep，速度最快，但 Keyzone 在 Ubuntu 上静音。

新增中间档：

- `CARLA_DUMMY_SLEEP_DIVISOR=N`
- `N=1` 表示实时。
- `N=2` 表示睡 1/2 周期，理论约 2 倍速。
- `N=4` 表示睡 1/4 周期，理论约 4 倍速。
- `N=8` 表示睡 1/8 周期，理论约 8 倍速。

目标是在 Keyzone 上找到“最快且不静音”的睡眠除数。2026-05-13 实测后，默认采用
`MUSIC_SERVICE_DUMMY_SLEEP_DIVISOR_BY_PLUGIN=vst_keyzone_classic=16`，并给 Keyzone 增加
2 秒预热。该配置会优先于禁用列表，保留禁用列表只是作为清空 divisor 后的稳定回退。

## 新增开关

部署脚本已透传：

```bash
MUSIC_SERVICE_DUMMY_SLEEP_DIVISOR_BY_PLUGIN=vst_keyzone_classic=16
MUSIC_SERVICE_RENDER_WARMUP_SECONDS_BY_PLUGIN=vst_keyzone_classic=2
MUSIC_SERVICE_RENDER_WAV_STATS=1
```

含义：

- `MUSIC_SERVICE_DUMMY_SLEEP_DIVISOR_BY_PLUGIN`：按插件设置 Dummy 周期睡眠除数。设置后优先于 `MUSIC_SERVICE_DUMMY_NOSLEEP_DISABLE_PLUGINS`。
- `MUSIC_SERVICE_RENDER_WARMUP_SECONDS_BY_PLUGIN`：按插件设置播放前预热时间，用于验证 Keyzone 是否因为采样/状态初始化太短而静音。
- `MUSIC_SERVICE_RENDER_WAV_STATS=1`：渲染子进程输出 `wav_render_stats`，包含 WAV 峰值、帧数、时长、采样宽度等。

## 建议测试矩阵

使用同一个 Keyzone 测试包：

```text
C:\work\workspace_own\workspace_carla\midi\demand_mapping_daojianrumeng_20260511\gm_000_bank000_program000_Keyzone_Classic_Steinway_Piano.zip
```

依次测试：

| 档位 | 环境变量 | 目标 |
| --- | --- | --- |
| 基线 | 不设置 `MUSIC_SERVICE_DUMMY_SLEEP_DIVISOR_BY_PLUGIN` | 确认实时非静音，约 198 秒 |
| 2 倍 | `vst_keyzone_classic=2` | 优先确认音色是否稳定 |
| 4 倍 | `vst_keyzone_classic=4` | 如果非静音，耗时应降到约 50 秒 |
| 8 倍 | `vst_keyzone_classic=8` | 如果非静音，耗时应降到约 25 秒 |
| 16 倍 | `vst_keyzone_classic=16` | 探索上限，实测通过，作为默认优化档 |

## 2026-05-13 实测结果

测试镜像基线：`mgsc_daw_service:6.5.12.1508` 加当前性能分支补丁。

测试输出目录：

```text
C:\work\workspace_own\workspace_carla\output\keyzone_perf_probe_20260513
```

单包矩阵：

| 配置 | 同步接口总耗时 | 录音阶段 | realtime ratio | 音量判定 |
| --- | ---: | ---: | ---: | --- |
| 实时回退 | 约 199 秒 | 约 184 秒 | 约 1x | 有声 |
| divisor=8 | 34.569 秒 | 23.498 秒 | 7.912x | 有声，max 0.0 dB |
| divisor=16 | 17.098 秒 | 6.028 秒 | 31.630x | 有声，max 0.0 dB |
| divisor=32 | 17.085 秒 | 6.056 秒 | 31.477x | 有声，max 0.0 dB |
| full nosleep + 2 秒预热 | 17.050 秒 | 6.040 秒 | 31.562x | 有声，max 0.0 dB |

divisor=16 之后不再继续加速，原因是 512/44100 的 Dummy 周期约 11.6ms，除以 16 后低于
Carla 当前毫秒级 sleep 阈值，实际效果接近 nosleep。选择 divisor=16 而不是直接清空禁用列表，
是为了部署参数上保留“可解释的 Keyzone 专属优化档”，需要回退时只要清空该变量即可。

Keyzone 覆盖包结果：

| 测试包 | 同步接口总耗时 | 录音阶段 | mean/max volume |
| --- | ---: | ---: | --- |
| `gm_000_bank000_program000_Keyzone_Classic_Steinway_Piano.zip` | 17.571s | 6.007s | -15.0 / 0.0 dB |
| `gm_001_bank000_program001_Keyzone_Classic_Yamaha_Grand_Piano.zip` | 18.067s | 7.954s | -14.1 / 0.0 dB |
| `gm_002_bank000_program002_Keyzone_Classic_Basic_Electric_Piano.zip` | 16.303s | 6.177s | -11.2 / 0.0 dB |
| `gm_004_bank000_program004_Keyzone_Classic_Basic_Electric_Piano.zip` | 16.109s | 5.975s | -11.2 / 0.0 dB |
| `gm_005_bank000_program005_Keyzone_Classic_Basic_Electric_Piano.zip` | 16.386s | 6.226s | -11.2 / 0.0 dB |
| `lmms_vst_keyzone_single.zip` | 15.077s | 多轨混音 | -27.3 / -7.0 dB |

判定：

- `max_volume > -80 dB` 只是机器判定非静音。
- 还需要人工听感对比，避免音头丢失、音色异常、断续。
- 如果 4 倍或 8 倍通过，再跑 5 个 Keyzone 映射包和 `lmms_vst_keyzone_single.zip`。

## 注意

`CARLA_DUMMY_SLEEP_DIVISOR` 是 Carla C++ Dummy 引擎新增能力，需要重新构建包含新 `CarlaEngineDummy.cpp` 的镜像后才生效。
同时必须包含 `render_midi_to_mp3.py` 中对 `CARLA_DUMMY_SLEEP_DIVISOR` 的 transport-frame 等待逻辑；
只改 C++ 或只覆盖 Python 都不能完整生效。

## Debug 对比方式

请求 ZIP 的 `conf.json` 支持调试开关：

```json
{
  "render": {
    "format": "mp3",
    "bitrate": 320,
    "samplerate": 44100,
    "debug": true
  }
}
```

默认 `debug=false` 时，同步和异步完成响应只保留 `job_id`、`plugin_id`、
`style_id`、`output_basename`、`elapsed_seconds`、`mp3_file.base64`，避免把大量内部路径、
耗时拆解和 renderer 事件发给商业客户端。

`debug=true` 时，响应会额外包含：

- `timings`
- `renderer_timings`
- `renderer_timings.renderer_events`
- `renderer_stage_seconds`
- `record_audio_breakdown`
- `mp3_path` / `wav_path`
- `artifact_archive`

其中 `renderer_events` 包含 `debug_environment`、`debug_engine_initialized`、
`debug_instrument_added`、`debug_plugin_state_loaded`、`debug_warmup_complete`、
`record_audio_start`、`record_audio_progress`、`record_audio_complete`、`wav_render_stats`
等结构化事件。Windows 和 Ubuntu 只需要用同一个 ZIP、同一个 `debug=true` 配置各跑一次，
对比以下字段即可定位差异：

- `CARLA_DUMMY_NOSLEEP` / `CARLA_DUMMY_SLEEP_DIVISOR`
- `WINEPREFIX` / `DISPLAY`
- `plugin_path` / `plugin_state`
- `midi_length_seconds` / `record_target_seconds`
- `record_realtime_ratio`
- `wav_peak_dbfs` / `wav_peak_ratio`
