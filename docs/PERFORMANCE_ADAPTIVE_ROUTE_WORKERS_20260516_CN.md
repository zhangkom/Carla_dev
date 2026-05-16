# 自适应多轨 worker 性能验证

日期：2026-05-16

分支：`perf/keyzone-render-speed`

镜像：`mgsc_daw_service:6.5.13.2019` 加当前工作区代码

## 1. 验证目标

此前部署默认使用：

```text
MUSIC_SERVICE_PARALLEL_ROUTES=1
MUSIC_SERVICE_PARALLEL_ROUTE_WORKERS=4
```

代表性回归显示，6 轨 SF2 混音仍会因为 4 个 worker 分两批执行而多耗时；但 VST/混合多轨的瓶颈通常是单个插件 route 自身耗时，盲目把 worker 全局升到 6 没有稳定收益。

本次验证目标是把默认策略改为自适应：

- 全部 route 都是 SF2 时，默认使用 6 个 worker。
- VST 或混合 route 时，默认使用 4 个 worker。
- 如果部署显式设置 `MUSIC_SERVICE_PARALLEL_ROUTE_WORKERS`，继续按显式值覆盖。

## 2. 输出目录

```text
C:\work\workspace_own\workspace_carla\output\perf_refactor_representative_20260516
C:\work\workspace_own\workspace_carla\output\perf_workers6_subset_20260516
C:\work\workspace_own\workspace_carla\output\perf_adaptive_workers_subset_20260516
C:\work\workspace_own\workspace_carla\output\perf_adaptive_representative_20260516
```

## 3. 关键对比

| 场景 | workers=4 | workers=6 | 自适应默认 | 音量 |
| --- | ---: | ---: | ---: | --- |
| `lmms_vst_trackname_multi.zip` | 22.845s | 23.323s | 22.844s | 非静音 |
| `sf2_gm_drum_mix_6tracks.zip` | 9.064s | 6.723s | 7.459s | 非静音 |

自适应容器日志确认：

```text
lmms_vst_trackname_multi.zip route_count=5 workers=4
sf2_gm_drum_mix_6tracks.zip route_count=6 workers=6
```

## 4. 完整代表性回归

自适应默认策略下，8 个代表性 zip 全部通过：

| ZIP | 耗时 | style_id | mean dB | max dB |
| --- | ---: | --- | ---: | ---: |
| `drum_128_056_bank128_program008_Musyng_Kite_8.zip` | 4.608s | `sf2_musyng_kite_gm` | -27.7 | -3.1 |
| `gm_040_bank000_program040_Sonatina_Orchestra_Solo_Violin.zip` | 10.108s | `sonatina_solo_violin` | -24.1 | -3.4 |
| `gm_064_bank000_program064_DSK_Saxophones_Soprano_Sax.zip` | 9.865s | `dsk_soprano_sax` | -15.6 | -0.0 |
| `gm_107_bank000_program107_kong_03_Sus_Shake_2.zip` | 13.376s | `kong_guzheng_classic_sus_shake_2` | -39.4 | -14.1 |
| `kong_gaohu_tremolo_vel_1.zip` | 10.141s | `kong_gaohu_tremolo_vel_1` | -31.9 | -12.5 |
| `lmms_vst_keyzone_single.zip` | 14.101s | `manual_track_mix` | -27.3 | -7.0 |
| `lmms_vst_trackname_multi.zip` | 22.844s | `manual_track_mix` | -15.4 | 0.0 |
| `sf2_gm_drum_mix_6tracks.zip` | 7.459s | `manual_track_mix` | -25.9 | -6.9 |

## 5. 代码调整

- `music_service.main._parallel_route_workers` 支持接收 route 列表并计算自适应默认 worker 数。
- `deploy_mgsc_daw_service.sh` 不再强行写入默认 `MUSIC_SERVICE_PARALLEL_ROUTE_WORKERS=4`，让服务端自适应策略生效。
- 服务器资源较小时，仍可在部署前显式设置 `MUSIC_SERVICE_PARALLEL_ROUTE_WORKERS=2` 或 `4` 回退。
