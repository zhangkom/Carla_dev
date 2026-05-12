# Ubuntu 18003 远程验收与性能报告（6.5.12.1508）

生成时间：2026-05-12 21:49:57

## 测试对象

- 服务地址：`http://221.178.78.110:29001/mgsc_daw_service_18003/v1/render`
- 镜像版本：`mgsc_daw_service:6.5.12.1508`
- 客户端：Windows 本机调用 Ubuntu 18003 外部转发地址
- 判定：HTTP 2xx、响应含 `mp3_file.base64`、MP3 可解码、`max_volume > -80 dB` 判定非静音。

## 需求映射 137 项覆盖

- 首轮输出目录：`C:\work\workspace_own\workspace_carla\output\demand_mapping_daojian_ubuntu_6.5.12.1508_20260512_202307`
- 重试输出目录：`C:\work\workspace_own\workspace_carla\output\demand_mapping_daojian_ubuntu_6.5.12.1508_retry_20260512_211452`
- 首轮结果：通过 136，失败 1，跳过 0。失败项为 `gm_055_bank000_program055_Musyng_Kite_55.zip`，错误是 Windows 客户端连接超时。
- 单项重试：`gm_055_bank000_program055_Musyng_Kite_55.zip` 通过，耗时 15.838 秒，非静音。
- 有效结论：通过 137，失败 0，跳过 0。
- 客户端总耗时统计：count=137, min=9.098s, avg=21.313s, median=14.412s, max=199.164s
- 服务端请求总耗时统计：count=137, min=6.568s, avg=18.051s, median=11.333s, max=195.693s
- 渲染器总耗时统计：count=137, min=3.765s, avg=14.555s, median=8.547s, max=188.041s
- 录音阶段耗时统计：count=137, min=2.123s, avg=12.78s, median=6.779s, max=184.523s
- MP3 编码耗时统计：count=137, min=2.039s, avg=2.455s, median=2.435s, max=2.775s

### 最慢样例

| zip | seconds | style | routes | mean_db | max_db |
| --- | --- | --- | --- | --- | --- |
| gm_005_bank000_program005_Keyzone_Classic_Basic_Electric_Piano.zip | 199.164 | keyzone_basic_electric_piano | 1 | -11.4 | 0.0 |
| gm_000_bank000_program000_Keyzone_Classic_Steinway_Piano.zip | 198.725 | keyzone_steinway_piano | 1 | -15.2 | 0.0 |
| gm_002_bank000_program002_Keyzone_Classic_Basic_Electric_Piano.zip | 198.605 | keyzone_basic_electric_piano | 1 | -11.4 | 0.0 |
| gm_004_bank000_program004_Keyzone_Classic_Basic_Electric_Piano.zip | 198.513 | keyzone_basic_electric_piano | 1 | -11.4 | 0.0 |
| gm_001_bank000_program001_Keyzone_Classic_Yamaha_Grand_Piano.zip | 198.468 | keyzone_yamaha_grand_piano | 1 | -14.3 | 0.0 |
| gm_056_bank000_program056_Sonatina_Orchestra_Solo_Trumpet.zip | 42.396 | sonatina_solo_trumpet | 1 | -24.6 | -4.6 |
| gm_009_bank000_program009_Musyng_Kite_9.zip | 27.827 | sf2_musyng_kite_gm | 1 | -29.4 | -6.7 |
| gm_015_bank000_program015_kong_02_Sus_mp.zip | 26.192 | kong_yangqin_sus_mp | 1 | -38.0 | -11.7 |
| drum_128_000_bank128_program000_Musyng_Kite_0.zip | 23.91 | sf2_musyng_kite_gm | 1 | -28.3 | -7.7 |
| gm_107_bank000_program107_kong_03_Sus_Shake_2.zip | 23.862 | kong_guzheng_classic_sus_shake_2 | 1 | -39.4 | -14.1 |
| gm_057_bank000_program057_Sonatina_Orchestra_Tenor_Trombone.zip | 23.379 | sonatina_tenor_trombone | 1 | -20.4 | -1.5 |
| gm_010_bank000_program010_Musyng_Kite_10.zip | 22.298 | sf2_musyng_kite_gm | 1 | -33.5 | -11.2 |

## 历史 ZIP 回归

| set | pass | fail | skip | seconds | request_total | output |
| --- | --- | --- | --- | --- | --- | --- |
| docker_images_test_zips | 5 | 0 | 0 | count=5, min=3.724s, avg=14.331s, median=16.975s, max=17.382s | count=5, min=3.07s, avg=12.039s, median=14.094s, max=14.608s | C:\work\workspace_own\workspace_carla\output\historical_zips_ubuntu_6.5.12.1508_20260512_211600\docker_images_test_zips |
| daojianrumeng_0508 | 6 | 0 | 1 | count=6, min=18.737s, avg=162.743s, median=152.311s, max=411.793s | count=6, min=16.436s, avg=159.973s, median=149.503s, max=408.691s | C:\work\workspace_own\workspace_carla\output\historical_zips_ubuntu_6.5.12.1508_20260512_211600\daojianrumeng_0508 |
| release_input | 4 | 0 | 1 | count=4, min=10.317s, avg=18.887s, median=13.661s, max=37.911s | count=4, min=8.064s, avg=16.161s, median=10.655s, max=35.271s | C:\work\workspace_own\workspace_carla\output\historical_zips_ubuntu_6.5.12.1508_20260512_211600\release_input |
| release_input18003 | 4 | 0 | 1 | count=4, min=10.061s, avg=18.654s, median=13.592s, max=37.369s | count=4, min=7.749s, avg=16.069s, median=10.78s, max=34.967s | C:\work\workspace_own\workspace_carla\output\historical_zips_ubuntu_6.5.12.1508_20260512_211600\release_input18003 |

说明：`docker_images/test_zips` 按既定要求跳过带 debug 的 zip；`mgsc_daw_example.zip` 和 `daojianrumeng_0508_test_zips.zip` 是集合包，不是单个渲染 bundle，因此脚本按规则跳过。

## 异步接口冒烟

- 异步请求已成功返回 `accepted job_id`，说明 `/mgsc_daw_service_18003/v1/render` 的 `callbackurl` 异步入口可用。
- 本次 Windows 客户端自动生成的 callback 地址是内网地址 `192.168.201.72`，Ubuntu 服务端无法反连该地址，所以等待 300 秒后客户端超时。
- 外部转发目前只对 render 路径生效；访问 `/v1/jobs/{job_id}/status` 被 nginx 返回图片内容，无法通过公网转发读取状态。
- 结论：服务端异步提交路径正常；端到端 callback 验证需要提供 Ubuntu 可达的 `callbackurl`，例如同网段可访问的回调服务或公网 HTTPS 回调地址。

```text
accepted job_id: 1b8e3e14fb3a4f7080df72ee6339e2b5
callbackurl: http://192.168.201.72:2435/callback
accepted_client_seconds: 0.313
TimeoutError: timed out waiting for callback after 300.0 seconds
```

## 性能观察

- Kong GaoHu 历史 4 个风格本次为 16-17 秒，未复现早期 184 秒问题。
- Keyzone 在 Ubuntu 上为保证非静音，仍走实时回退，需求映射中 Keyzone 条目约 198-199 秒。
- 多轨 LMMS 对齐包耗时与轨道数明显相关，`lmms_sf2_trackname_a.zip` 为 5 轨混音，耗时 411.793 秒。
- 单轨 Musyng Kite / 多数 GM 映射通常在 9-19 秒区间。

## 后续优化方向

1. 新建 Keyzone 性能优化分支，增加 Keyzone nosleep 对照日志：插件加载、transport、record buffer、WAV 峰值/均值。
2. 做 Keyzone 短 MIDI A/B：nosleep 开/关、Windows/Ubuntu、同一 preset 输出峰值对比，定位静音发生在哪个阶段。
3. 多轨包单独评估是否可以并行分轨或复用 Carla/Wine 初始化，避免每轨都付完整初始化成本。
