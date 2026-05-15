# 多轨并行与 Kong 静音补充验证

日期：2026-05-15

分支：`perf/keyzone-render-speed`

镜像：`mgsc_daw_service:6.5.13.2019` 加当前工作区代码

## 1. 老 LMMS 兼容输入对比

测试目录：

```text
C:\work\workspace_own\workspace_carla\midi\daojianrumeng_0508
```

输出目录：

```text
C:\work\workspace_own\workspace_carla\output\local_lmms_acceptance_perf_branch_20260515
C:\work\workspace_own\workspace_carla\output\local_lmms_acceptance_perf_branch_serial_20260515
```

| ZIP | 串行耗时 | 并行 workers=4 耗时 | 音量结果 |
| --- | ---: | ---: | --- |
| `lmms_sf2_trackname_a.zip` | 44.810s | 20.262s | 非静音 |
| `lmms_sf2_trackname_b.zip` | 34.793s | 18.051s | 非静音 |
| `lmms_sf2_vst_trackname_a.zip` | 12.406s | 12.374s | 非静音 |
| `lmms_sf2_vst_trackname_b.zip` | 12.351s | 12.334s | 非静音 |
| `lmms_vst_keyzone_single.zip` | 17.060s | 16.999s | 非静音 |
| `lmms_vst_trackname_multi.zip` | 79.038s | 24.365s | 非静音 |

结论：多轨并行对 SF2 多轨和 VST 多轨收益明显；单轨 Keyzone 基本不受影响，仍维持 17s 左右并保持有声。

## 2. Kong 显式 Style 静音原因

在旧调试容器中，Kong 代表样例出现 `mean_volume=-91.0 dB` 的静音结果。重新创建干净容器后，用同一镜像和同一代码验证：

- Qin_RV 插件和 Kong library 本身可以发声。
- `kong_gaohu_stac_1.zip` 这类老显式 style 输入没有指定 `midi_source_channel`。
- 原始 MIDI 的旋律轨道由 `analyze_midi_channels` 识别为 channel 7，原因是 `track_name_melody`。
- 如果不选源通道，服务会把鼓、贝司、和弦、旋律等所有轨道重写到一个 Kong 单音色插件，容易导致静音。

因此修复为：仅在“显式 Kong 单风格 + 未指定 `midi_source_channel` + style MIDI policy 启用”时，自动分析 MIDI 并选择旋律源通道。用户显式传入 `midi_source_channel` 时不覆盖。

## 3. 干净容器验证结果

输出目录：

```text
C:\work\workspace_own\workspace_carla\output\perf_representative_styles_20260515
```

| ZIP | style_id | 耗时 | mean dB | max dB |
| --- | --- | ---: | ---: | ---: |
| `kong_gaohu_stac_1.zip` | `kong_gaohu_stac_1` | 10.611s | -28.9 | -10.8 |
| `kong_gaohu_sus_leg_mw.zip` | `kong_gaohu_sus_leg_mw` | 10.102s | -27.4 | -9.1 |
| `kong_gaohu_tremolo_vel_1.zip` | `kong_gaohu_tremolo_vel_1` | 10.171s | -31.9 | -12.5 |
| `kong_gaohu_trill_vel_1.zip` | `kong_gaohu_trill_vel_1` | 10.168s | -30.9 | -11.6 |
| `gm_015_bank000_program015_kong_02_Sus_mp.zip` | `kong_yangqin_sus_mp` | 15.474s | -38.0 | -11.7 |
| `gm_107_bank000_program107_kong_03_Sus_Shake_2.zip` | `kong_guzheng_classic_sus_shake_2` | 13.059s | -39.4 | -14.1 |

## 4. 后续建议

- 正式回归前优先使用干净容器启动服务。
- 长期运行的调试容器中可能堆积 `carla-bridge`、`wineserver` defunct 进程，影响 Kong/Wine bridge 判断。
- 多轨并行仍建议保持为环境变量开关；下一步继续扩大 VST/Kong/Sonatina/DSK 的组合回归后，再决定是否默认打开。
