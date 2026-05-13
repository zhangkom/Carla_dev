# Keyzone Classic 性能优化记录

日期：2026-05-13

## 当前问题

`vst_keyzone_classic` 在 Ubuntu 18003 上为了避免静音，当前默认通过
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

目标是在 Keyzone 上找到“最快且不静音”的睡眠除数。

## 新增开关

部署脚本已透传：

```bash
MUSIC_SERVICE_DUMMY_SLEEP_DIVISOR_BY_PLUGIN=vst_keyzone_classic=4
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
| 16 倍 | `vst_keyzone_classic=16` | 探索上限，可能重新静音或爆音 |

判定：

- `max_volume > -80 dB` 只是机器判定非静音。
- 还需要人工听感对比，避免音头丢失、音色异常、断续。
- 如果 4 倍或 8 倍通过，再跑 5 个 Keyzone 映射包和 `lmms_vst_keyzone_single.zip`。

## 注意

`CARLA_DUMMY_SLEEP_DIVISOR` 是 Carla C++ Dummy 引擎新增能力，需要重新构建包含新 `CarlaEngineDummy.cpp` 的镜像后才生效。只覆盖 Python 服务代码不会让该开关生效。
