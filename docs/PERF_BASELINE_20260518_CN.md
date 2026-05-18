# Carla 云端 DAW 性能基线与 Vital 专项测试报告（2026-05-18）

## 1. 测试范围

本次测试基于分支 `perf/keyzone-render-speed`，目标是确认当前代码可以作为一个阶段性稳定基线，并继续定位 Vital 预设耗时问题。

测试服务：

- 本地容器：`mgsc_daw_all_route_wav_only_20260516`
- 镜像：`mgsc_daw_service:6.5.13.2019`
- 接口：`http://127.0.0.1:18020/mgsc_daw_service/v1/render`
- 代码分支：`perf/keyzone-render-speed`

关键运行参数：

- `MUSIC_SERVICE_BUFFER_SIZE_BY_TYPE=vst=4096`
- `MUSIC_SERVICE_BUFFER_SIZE_BY_PLUGIN=vst_keyzone_classic=512`
- `MUSIC_SERVICE_DUMMY_NOSLEEP=1`
- `MUSIC_SERVICE_DUMMY_SLEEP_DIVISOR_BY_PLUGIN=vst_keyzone_classic=16`

## 2. 代表性同步验收

输入目录：

`C:\work\workspace_own\workspace_carla\output\perf_representative_zips_20260515`

输出目录：

`C:\work\workspace_own\workspace_carla\output\stable_baseline_perf_branch_20260518_091331`

结果：8 个代表包全部通过，均生成非静音 MP3。

| ZIP | 结果 | 耗时(s) | 音频时长(s) | mean dB | max dB | style |
|---|---:|---:|---:|---:|---:|---|
| `drum_128_056_bank128_program008_Musyng_Kite_8.zip` | PASS | 5.048 | 179.769 | -27.7 | -2.9 | `sf2_musyng_kite_gm` |
| `gm_040_bank000_program040_Sonatina_Orchestra_Solo_Violin.zip` | PASS | 8.698 | 184.459 | -24.1 | -3.4 | `sonatina_solo_violin` |
| `gm_064_bank000_program064_DSK_Saxophones_Soprano_Sax.zip` | PASS | 8.690 | 184.459 | -15.6 | -0.0 | `dsk_soprano_sax` |
| `gm_107_bank000_program107_kong_03_Sus_Shake_2.zip` | PASS | 12.117 | 184.459 | -39.6 | -11.7 | `kong_guzheng_classic_sus_shake_2` |
| `kong_gaohu_tremolo_vel_1.zip` | PASS | 9.189 | 184.459 | -31.8 | -12.5 | `kong_gaohu_tremolo_vel_1` |
| `lmms_vst_keyzone_single.zip` | PASS | 13.751 | 184.343 | -27.3 | -7.0 | `manual_track_mix` |
| `lmms_vst_trackname_multi.zip` | PASS | 20.108 | 184.459 | -15.4 | 0.0 | `manual_track_mix` |
| `sf2_gm_drum_mix_6tracks.zip` | PASS | 5.563 | 184.424 | -25.8 | -6.7 | `manual_track_mix` |

结论：

- Kong Audio 没有回退到按 MIDI 实时时长渲染，代表风格保持 10 秒级。
- Keyzone 单轨有声音，耗时约 13.8 秒。
- SF2 六轨混合保持 6 秒以内。
- VST 多轨当前约 20 秒，主要受 Vital 预设影响。

## 3. 同步与异步接口回归

测试 ZIP：

`drum_128_056_bank128_program008_Musyng_Kite_8.zip`

输出目录：

`C:\work\workspace_own\workspace_carla\output\stable_baseline_perf_branch_20260518_091331\sync_async_regression`

结果：

| 模式 | 结果 | job_id | style_id | 耗时(s) | 输出 |
|---|---:|---|---|---:|---|
| 同步 | PASS | `7ae63165f7d740cbab1c6163d4f687c8` | `sf2_musyng_kite_gm` | 4.065 | `sync.mp3` |
| 异步 callback | PASS | `6906f25626844c468a9d5c2dd3e3f6b9` | `sf2_musyng_kite_gm` | 3.524 | `async.mp3` |

异步测试使用本地临时 callback server，服务端通过 `callbackurl` POST 回调返回 JSON，客户端从 `mp3_file.base64` 解码并保存 MP3。说明同步和异步交付路径均正常。

## 4. Vital buffer 专项测试

测试对象：

从 `lmms_vst_trackname_multi.zip` 拆出的三个 Vital 单 route 包：

- `vital_a_happy_ending_of_the_world.zip`
- `vital_abbysun.zip`
- `vital_ah_eh_ee_oh.zip`

输出目录：

`C:\work\workspace_own\workspace_carla\output\vital_perf_probe_20260518_091331`

| preset zip | buffer | 耗时(s) | 音频时长(s) | mean dB | max dB |
|---|---:|---:|---:|---:|---:|
| `vital_a_happy_ending_of_the_world.zip` | 512 | 14.043 | 184.343 | -28.1 | -3.8 |
| `vital_a_happy_ending_of_the_world.zip` | 1024 | 13.050 | 184.366 | -28.1 | -3.8 |
| `vital_a_happy_ending_of_the_world.zip` | 2048 | 12.469 | 184.413 | -28.1 | -3.8 |
| `vital_a_happy_ending_of_the_world.zip` | 4096 | 11.637 | 184.459 | -29.5 | -3.6 |
| `vital_a_happy_ending_of_the_world.zip` | 8192 | 10.967 | 184.645 | -30.3 | -4.2 |
| `vital_abbysun.zip` | 512 | 23.276 | 184.343 | -34.3 | -8.2 |
| `vital_abbysun.zip` | 1024 | 22.733 | 184.366 | -34.2 | -9.6 |
| `vital_abbysun.zip` | 2048 | 22.354 | 184.413 | -34.1 | -9.4 |
| `vital_abbysun.zip` | 4096 | 22.181 | 184.459 | -34.3 | -8.4 |
| `vital_abbysun.zip` | 8192 | 22.064 | 184.645 | -34.2 | -9.3 |
| `vital_ah_eh_ee_oh.zip` | 512 | 11.457 | 184.343 | -19.4 | -1.5 |
| `vital_ah_eh_ee_oh.zip` | 1024 | 10.967 | 184.366 | -19.4 | -1.5 |
| `vital_ah_eh_ee_oh.zip` | 2048 | 10.675 | 184.413 | -19.4 | -1.5 |
| `vital_ah_eh_ee_oh.zip` | 4096 | 10.506 | 184.459 | -19.4 | -1.5 |
| `vital_ah_eh_ee_oh.zip` | 8192 | 10.438 | 184.645 | -19.4 | -1.6 |

结论：

- 单 route 下 Vital 的 buffer 越大越快，但收益逐步变小。
- `vital_abbysun.zip` 即使使用 8192 buffer 仍约 22 秒，是当前最明显的慢 preset。
- 之前多轨实测中，workers=3 和 workers=5 都比默认 workers=4 慢；VST 多轨 8192 也曾慢于 4096。
- 因此当前不建议把生产默认从 `vst=4096` 改成 8192。8192 可以作为后续单轨或特定 preset 的候选策略继续观察。

## 5. 当前建议

当前分支可以作为阶段性性能整理基线，建议下一步：

1. 保留生产默认：`MUSIC_SERVICE_BUFFER_SIZE_BY_TYPE=vst=4096`，Keyzone 单独保持 `512`。
2. 不再调整多轨 workers 默认值，继续保持混合/VST 默认 4、SF2 默认 6。
3. 对 Vital 慢 preset 做候选替代策略：
   - 如果业务允许，可将 `vital_abbysun` 对应需求映射替换为更快、听感相近的 Vital 或 DSK/SF2 风格。
   - 如果必须保留 `vital_abbysun`，可只对单轨场景试验 8192 buffer，但多轨场景暂不建议启用。
4. 打镜像前建议再跑一次完整需求映射 137 项验收，确认本次性能整理没有影响需求覆盖。
