# 6.5.18.1612 之后的性能优化准备记录

日期：2026-05-18

当前稳定分支：`6.5.18.1612`

后续优化分支：`perf/post-6.5.18-optimization`

## 1. 稳定基线

`6.5.18.1612` 已作为当前稳定基线固定：

- 新镜像冷启动容器验证通过。
- Xvfb 冷启动正常，`Xvfb :99` 有活跃进程。
- Kong 两条需求映射通过，未再出现等长静音 MP3。
- 代表集 8 个通过。
- 需求映射 137 个通过，失败 0。

后续每次保存新镜像必须遵守：

1. 使用新镜像启动全新容器验证，不能复用旧容器结果。
2. 验证通过后再交付镜像包。
3. 临时验证容器确认无用后删除，避免端口、缓存和运行态干扰。
4. 正式交付至少保留镜像 tag、代码 commit、验证容器名、验证输出目录和通过数量。

## 2. 当前耗时画像

数据来源：

`C:\work\workspace_own\workspace_carla\output\demand_137_check_6.5.18.1546_20260518\summary.json`

按插件家族聚合：

| 插件家族 | 数量 | 平均耗时(s) | 最快(s) | 中位数(s) | 最慢(s) |
|---|---:|---:|---:|---:|---:|
| Keyzone Classic | 5 | 16.839 | 16.441 | 16.464 | 18.357 |
| Kong Qin_RV | 2 | 13.902 | 13.109 | 14.696 | 14.696 |
| Sonatina Orchestra | 17 | 9.985 | 9.256 | 9.919 | 11.074 |
| DSK Saxophones | 2 | 9.622 | 9.568 | 9.676 | 9.676 |
| Musyng Kite SF2 | 111 | 5.999 | 4.736 | 5.957 | 7.240 |

最慢前几项：

| ZIP | 耗时(s) | style_id |
|---|---:|---|
| `gm_001_bank000_program001_Keyzone_Classic_Yamaha_Grand_Piano.zip` | 18.357 | `keyzone_yamaha_grand_piano` |
| `gm_005_bank000_program005_Keyzone_Classic_Basic_Electric_Piano.zip` | 16.478 | `keyzone_basic_electric_piano` |
| `gm_004_bank000_program004_Keyzone_Classic_Basic_Electric_Piano.zip` | 16.464 | `keyzone_basic_electric_piano` |
| `gm_002_bank000_program002_Keyzone_Classic_Basic_Electric_Piano.zip` | 16.455 | `keyzone_basic_electric_piano` |
| `gm_000_bank000_program000_Keyzone_Classic_Steinway_Piano.zip` | 16.441 | `keyzone_steinway_piano` |
| `gm_015_bank000_program015_kong_02_Sus_mp.zip` | 14.696 | `kong_yangqin_sus_mp` |
| `gm_107_bank000_program107_kong_03_Sus_Shake_2.zip` | 13.109 | `kong_guzheng_classic_sus_shake_2` |

## 3. 优化优先级

### 优先级 1：Keyzone 专项

目标：在不静音、不牺牲音质的前提下，把 Keyzone 5 条从 16-18 秒进一步压低。

当前策略：

- `MUSIC_SERVICE_DUMMY_SLEEP_DIVISOR_BY_PLUGIN=vst_keyzone_classic=16`
- `MUSIC_SERVICE_RENDER_WARMUP_SECONDS_BY_PLUGIN=vst_keyzone_classic=2`
- `MUSIC_SERVICE_BUFFER_SIZE_BY_PLUGIN=vst_keyzone_classic=512`

候选实验：

1. 比较 Keyzone divisor：`12`、`16`、`20`、`24`、`32`。
2. 比较 warmup：`0`、`1`、`2`、`3` 秒。
3. 比较 buffer：`256`、`512`、`1024`。
4. 每个组合至少跑 5 个 Keyzone 需求包，检查 `max_volume > -80 dB`。
5. 如果出现静音或削波明显变化，立即剔除该组合。

### 优先级 2：多轨 VST/Vital

代表样例：

- `lmms_vst_trackname_multi.zip`

当前代表集耗时约 24.659 秒。之前记录显示 Vital 慢 preset 是主要瓶颈，尤其 `vital_abbysun.zip`。

候选实验：

1. 对 Vital 慢 preset 单独跑 buffer 矩阵：`4096`、`8192`、`16384`。
2. 只在单轨或 Vital 专属 style 上尝试更大 buffer，不直接改全局默认。
3. 比较多轨 workers：`3`、`4`、`5`，以端到端耗时和非静音为准。

### 优先级 3：Sonatina/DSK 小幅优化

Sonatina 和 DSK 当前稳定在 9-11 秒。它们不是当前最大瓶颈，除非 Keyzone 和 Vital 优化完成，否则不优先动默认参数。

## 4. 风险边界

不建议优先做：

- 重新启用 `CARLA_DUMMY_OFFLINE`。历史上该路径会导致 Kong Audio 静音。
- 直接把 `MUSIC_SERVICE_DUMMY_NOSLEEP` 用在 Keyzone。历史上 Ubuntu 下 Keyzone 曾出现静音。
- 把全局 VST buffer 直接改到 8192 或更高。之前多轨测试中并不稳定优于 4096。
- 在没有新镜像新容器验证的情况下交付任何性能改动。

## 5. 下一步执行

1. 在 `perf/post-6.5.18-optimization` 分支新增一个小型性能矩阵脚本，专门跑 Keyzone 参数组合。
2. 先不打新镜像，直接用 `6.5.18.1612` 容器和环境变量覆盖做实验。
3. 选出候选参数后，跑：
   - Keyzone 5 条。
   - Kong 两条。
   - 代表集 8 个。
4. 只有候选参数全部通过，才考虑固化到部署脚本和下一版镜像。

## 6. 2026-05-19 继续优化记录

本次先做不影响渲染结果的轻量优化：

- 在 `ServiceConfig` 中预计算 legacy VST/SF2 路由匹配索引，避免多轨请求中每条轨道重复归一化所有 style 和 plugin 文本。
- 保持原有匹配规则不变：`param_key_name` 优先匹配 style 文本，`vst_path` 匹配 style/plugin 文本，`sf2_path` 匹配 sf2 style/plugin 文本。
- 新增 `tools/run_keyzone_perf_matrix.py`，用于用同一镜像按 divisor、warmup、buffer 组合启动临时新容器并批量跑 Keyzone 测试包。

矩阵工具示例：

```powershell
python tools\run_keyzone_perf_matrix.py `
  --image mgsc_daw_service:6.5.18.1612 `
  --zip-dir C:\work\workspace_own\workspace_carla\midi\demand_mapping_coverage_20260511 `
  --zip-pattern "*Keyzone*.zip" `
  --output-root C:\work\workspace_own\workspace_carla\output\keyzone_matrix_20260519 `
  --host-port-base 18100
```

注意：该工具每个参数组合都会创建一个新容器，跑完后默认删除该临时容器，符合“新镜像/新参数必须用新容器验证”的规则。正式固化参数前仍需要补跑 Kong 两条和代表集 8 条。

## 7. 2026-05-19 Keyzone 小矩阵结果

测试镜像：`mgsc_daw_service:6.5.18.1612`

测试包：`midi\demand_mapping_coverage_20260511` 中 5 个 Keyzone zip。

输出目录：

- `C:\work\workspace_own\workspace_carla\output\keyzone_matrix_divisor_20260519`
- `C:\work\workspace_own\workspace_carla\output\keyzone_matrix_warmup_20260519`

### 7.1 divisor 对照

固定 `warmup=2`、`buffer=512`：

| divisor | 通过 | 平均耗时(s) | 最慢(s) | 最低 max_volume(dB) | 静音数 |
|---:|---:|---:|---:|---:|---:|
| 16 | 5/5 | 9.230 | 10.295 | -10.5 | 0 |
| 20 | 5/5 | 8.974 | 9.132 | -10.5 | 0 |
| 24 | 5/5 | 8.971 | 9.161 | -10.5 | 0 |
| 32 | 5/5 | 9.013 | 9.188 | -10.5 | 0 |

结论：`20`、`24`、`32` 都比当前默认 `16` 更快；`20` 的最慢耗时最低，暂作为候选。

### 7.2 warmup 对照

固定 `divisor=20`、`buffer=512`：

| warmup | 通过 | 平均耗时(s) | 最慢(s) | 最低 max_volume(dB) | 静音数 |
|---:|---:|---:|---:|---:|---:|
| 0 | 0/5 | - | - | - | - |
| 1 | 5/5 | 8.007 | 8.228 | -10.5 | 0 |
| 2 | 5/5 | 8.987 | 9.180 | -10.5 | 0 |
| 3 | 5/5 | 10.001 | 10.237 | -10.5 | 0 |

`warmup=0` 在当前镜像中被服务端校验拒绝，原因是 `MUSIC_SERVICE_RENDER_WARMUP_SECONDS_BY_PLUGIN=vst_keyzone_classic=0.0` 被旧代码当成非法正数。源码已改为 warmup 允许 0，但需要下一版镜像才能复测。

当前候选参数：`MUSIC_SERVICE_DUMMY_SLEEP_DIVISOR_BY_PLUGIN=vst_keyzone_classic=20`，`MUSIC_SERVICE_RENDER_WARMUP_SECONDS_BY_PLUGIN=vst_keyzone_classic=1`，`MUSIC_SERVICE_BUFFER_SIZE_BY_PLUGIN=vst_keyzone_classic=512`。

暂不固化到部署脚本。下一步需要用候选参数补跑 Kong 两条、代表集 8 条、Ubuntu 端 Keyzone 5 条，全部通过后再改默认值并打新镜像。

### 7.3 候选参数代表集回归

候选参数：`divisor=20`、`warmup=1`、`buffer=512`。

输出目录：`C:\work\workspace_own\workspace_carla\output\keyzone_candidate_representative_20260519`

结果：代表集 8/8 通过，静音数 0。

| ZIP | 耗时(s) | max_volume(dB) | style |
|---|---:|---:|---|
| `drum_128_056_bank128_program008_Musyng_Kite_8.zip` | 5.114 | -3.1 | `sf2_musyng_kite_gm` |
| `gm_040_bank000_program040_Sonatina_Orchestra_Solo_Violin.zip` | 8.767 | -3.4 | `sonatina_solo_violin` |
| `gm_064_bank000_program064_DSK_Saxophones_Soprano_Sax.zip` | 8.880 | -0.0 | `dsk_soprano_sax` |
| `gm_107_bank000_program107_kong_03_Sus_Shake_2.zip` | 12.349 | -11.7 | `kong_guzheng_classic_sus_shake_2` |
| `kong_gaohu_tremolo_vel_1.zip` | 9.393 | -12.5 | `kong_gaohu_tremolo_vel_1` |
| `lmms_vst_keyzone_single.zip` | 12.635 | -7.0 | `manual_track_mix` |
| `lmms_vst_trackname_multi.zip` | 24.393 | -0.0 | `manual_track_mix` |
| `sf2_gm_drum_mix_6tracks.zip` | 6.294 | -6.7 | `manual_track_mix` |

结论：候选参数没有破坏 Kong、Sonatina、DSK、Musyng Kite、多轨混音路径。下一步优先在 Ubuntu 端用同样参数补跑 Keyzone 5 条和代表集 8 条；如果仍然通过，再把部署脚本默认从 `vst_keyzone_classic=16 / warmup=2` 调整为 `vst_keyzone_classic=20 / warmup=1`。
