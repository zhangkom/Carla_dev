# Codex App 交接记录

日期：2026-05-06  
分支：`6.5.7.0955`  
工程目录：`C:\work\workspace_own\workspace_carla\Carla-2.5.10`

## 2026-05-08 LMMS 四文件输入对齐

当前开发分支：`feature/demand-plugin-expansion`

目标输入继续使用正式接口：

```text
POST /mgsc_daw_service/v1/render
```

推荐 zip 结构：

```text
一个 MIDI
conf.json
vst.json
sf2.json
```

`conf.json` 通过 `vstConf` / `sf2Conf` 引用 zip 内 route JSON；引用值可以是旧 LMMS 风格的 `/data/midi/vst.json`，服务端会按 zip 成员名或 basename 查找。

本次接口对齐规则：

1. `id` 是主匹配字段，按 MIDI 中含音符轨道的 0 基序号定位；`track_name` 仅作 fallback、日志和调试信息。
2. `style_id` 最高优先级，适合 Carla-native 调用。
3. 没有 `style_id` 时，优先用 Web 端 A320U.sf2 语义的 `bank` + `patch` / `patch_name` 查 `config/instrument_mapping.deploy.json`，映射到 Carla 云端 style。
4. `patch` 按需求映射表中的 0 基 Program 解释；如果 `patch` 是 `Rock` 这类名称，则尝试读取数字 `patch_name`。
5. drum/kit/rock 语义的轨道优先尝试 Web Bank `128`，用于 9 个鼓组映射。
6. 旧 LMMS 字段 `vst_path + param_key_name`、`sf2_path` 保留为迁移期 fallback。
7. 如果 `vst.json` 和 `sf2.json` 里同一个 `id` 或 `track_name` 重复，只渲染一条路线；优先级为 `style_id`、Web `bank/patch`、旧 VST 字段、旧 SF2 字段，避免同一 MIDI 轨道重复渲染。
8. `segments`、`output.file_path`、`vstDir`、`sf2Dir` 和绝对 `/data/midi/...` 路径不作为 Carla 渲染控制字段，仅保留兼容读取或元数据意义。

已用本地最新镜像环境验证：

```text
base image: mgsc_daw_service:6.5.7.18001
test zip: C:\work\workspace_own\workspace_carla\runtime_mapping_test\test_zips\input_example_4file_20260508.zip
temp container: mgsc_input_mapping_test
temp port: 18081
```

同步短渲染：HTTP 200，`style_id=manual_track_mix`，`route_count=5`，MP3 43929 bytes。

异步短渲染：accepted 后 callback 返回 `status=completed`，`route_count=5`，MP3 43929 bytes。

`midi/input_example` 的重复 VST/SF2 路由最终解析为：

```text
id=0 chord          -> keyzone_yamaha_grand_piano  web bank/program 0/1
id=1 main_melody    -> sf2_musyng_kite_gm          web bank/program 0/16
id=2 assist_melody  -> sf2_musyng_kite_gm          web bank/program 0/12
id=3 bass           -> keyzone_steinway_piano      web bank/program 0/0
id=4 drum           -> sf2_musyng_kite_gm          web bank/program 128/5
```

代码提交：

```text
71a5dae feat: map LMMS bank patch routes
```

Ubuntu 小补丁包：

```text
C:\work\workspace_own\workspace_carla\docker_images\ubuntu_upload_6.5.7.18001\code_patch_lmms_input_20260508.tar.gz
sha256: 9ffc75277e8b49b509755edd1f487308e6b4b23da3641a60e2afe6bf3f681442
```

如果 Ubuntu 已经有 `mgsc_daw_service:6.5.7.18001` 镜像，可以先把该补丁包解到当前容器 `/home/workspace` 覆盖服务代码，重启验证；验证通过后在服务器上 `docker commit` 成新的镜像版本。

## 2026-05-07 15:20 接口前缀收敛

当前外部正式接口改为只保留服务名前缀路径，不再维护裸 `/v1/...` 路径：

```text
GET  /mgsc_daw_service/health
GET  /mgsc_daw_service/v1/catalog
GET  /mgsc_daw_service/v1/plugins
GET  /mgsc_daw_service/v1/styles
GET  /mgsc_daw_service/v1/instrument-mappings
POST /mgsc_daw_service/v1/render
GET  /mgsc_daw_service/v1/jobs/{job_id}/status
GET  /mgsc_daw_service/v1/jobs/{job_id}/{filename}
```

部署端口统一建议使用宿主机 `18001`，容器内仍是 `8000`：

```bash
HOST_PORT=18001 LOAD_IMAGE=0 ./deploy_mgsc_daw_service.sh
curl http://127.0.0.1:18001/mgsc_daw_service/health
```

Ubuntu 已加载旧镜像时，可以先复制本次小代码补丁进容器验证，无需重新上传 17GB 镜像。复制后重启容器，再用 `docker commit` 在服务器本地保存新的镜像基线。

## 2026-05-07 09:55 基线更新

`6.5.6.2016` 已完成 Windows 本机和同局域网 MacBook 的同步/异步接口验证。当前将该状态固化为：

```text
Git branch: 6.5.7.0955
Docker image: mgsc_daw_service:6.5.7.0955
```

Ubuntu 上传目录：

```text
C:\work\workspace_own\workspace_carla\docker_images\ubuntu_upload_6.5.7.0955
```

该目录只包含小于 2GB 的分片、部署脚本、校验文件、manifest 和测试 zip。不要拷贝完整 tar。

镜像与校验：

```text
image id: sha256:93fbf590c41a9521a6a27a065ab7c25d95cdb6c7e119bcd472589c01c99a5900
full tar sha256: 5efb21b2e5b2fff336ceeb16b653f65587c8de96f1df224db8c2223d4292db3d
part01: 1900000000 bytes
part02: 1900000000 bytes
part03: 659149824 bytes
```

本次额外修复：

1. Windows Git Bash 调用 Docker 时会把容器内路径 `/wineprefix`、`/home/runtime`、`/home/workspace/...` 改写成 `C:/Program Files/Git/...`，部署脚本已通过 `MSYS2_ARG_CONV_EXCL` 排除这些容器路径。
2. `/health` 如果失败，部署脚本现在直接失败退出并打印日志，不再误报 `Container is ready`。
3. 测试 MP3 输出命名改为日期时间，不再带镜像版本号。

## 当前目标

基于 `mgsc_daw_service:v6.4.40` 的声音正确性基线，生成新的日期版本 `6.5.6.2016`：

1. 正式入口收敛为 `/mgsc_daw_service/v1/render`。
2. 不传 `callbackurl` 时同步返回 `mp3_file.base64`。
3. 传 `callbackurl` 时异步 accepted，后台渲染完成后 POST 完整 JSON 到 `callbackurl`。
4. 推荐 zip 结构为 4 文件：一个 MIDI、一个 `conf.json` 全局参数、一个 `vst.json`、一个 `sf2.json`。`conf.json` 通过 `vstConf` / `sf2Conf` 引用 zip 内 route JSON。
5. `vst.json` / `sf2.json` 支持 Carla-native 多轨显式路由：`id`、`track_name`、`style_id`，其中 `id` 优先按 0 基有效音符轨道序号匹配。
6. 迁移期可读取旧 LMMS `vst` / `sf2` 数组中的 `id`、`track_name`、`vst_path`、`sf2_path`、`param_key_name`、`bank`、`patch`，解析成已接入的 Carla style 后分轨渲染混音。
7. 需求方确认：Sonatina Bassoom -> Bassoon；Tensor Trombone -> Tenor Trombone；Bank 128 按表格 9 个鼓组；Tuba Sustain / Solo Horn / Solo Clarinet 等以实际扫描文件名为准。相关 docx 已追加红底确认块。
8. 本地候选资产已作为显式 style 扩展到 `plugins.deploy.json`，包括 A320U、A320U_drums、Vital、DSK Asian DreamZ、DRUM PRO、Tunefish4、MT-PowerDrumKit、ABPL2、AGML2、EZkeys、Sylenth1 等；不改变当前 137 条 auto 映射。
9. 修复 `v6.4.43` Dummy offline 加速导致 Kong Audio 静音的问题。
10. 准备 Ubuntu 部署包，镜像分片小于 2GB。

## 已确认事实

`v6.4.40` 基线重新跑过 5 个非 debug zip：

- `kong_gaohu_stac_1.zip`
- `kong_gaohu_sus_leg_mw.zip`
- `kong_gaohu_tremolo_vel_1.zip`
- `kong_gaohu_trill_vel_1.zip`
- `sf2_musyng_kite_daojian_20s.zip`

结果：5 个 WAV/MP3 都有声音。Kong 包接近实时，单包约 198-209 秒；Musyng Kite 20 秒包约 23.5 秒。

`v6.4.43` 已判定为失败实验：`CARLA_DUMMY_OFFLINE=1` 能把耗时降下来，但 Kong Audio 输出静音，不可交付。

## 新加速策略

新策略是 `CARLA_DUMMY_NOSLEEP`：

- 不启用 `CARLA_DUMMY_OFFLINE`。
- 不调用 `offlineModeChanged(true)`。
- `isOffline()` 继续返回 `false`。
- 只让 Dummy 引擎跳过音频周期 sleep。
- `render_midi_to_mp3.py` 在 nosleep 开启时根据 transport frame 到达目标帧数来结束录音等待。
- `music_service/renderer.py` 只在 `MUSIC_SERVICE_DUMMY_NOSLEEP=1` 时传递该开关。

部署脚本默认：

```bash
MUSIC_SERVICE_DUMMY_NOSLEEP=1
```

如需诊断可回退：

```bash
MUSIC_SERVICE_DUMMY_NOSLEEP=0 ./deploy_mgsc_daw_service.sh
```

## 已跑验证

最终容器：`mgsc_daw_service_6562016`  
端口：`8003`  
镜像：`mgsc_daw_service:6.5.6.2016`

同步回归结果：

| zip | wall | record_audio | 音量 |
| --- | ---: | ---: | --- |
| `kong_gaohu_stac_1.zip` | 14.755s | 3.091s | mean -28.9 dB / max -10.8 dB |
| `kong_gaohu_sus_leg_mw.zip` | 16.345s | 3.060s | mean -27.4 dB / max -9.0 dB |
| `kong_gaohu_tremolo_vel_1.zip` | 17.473s | 2.624s | mean -31.9 dB / max -12.5 dB |
| `kong_gaohu_trill_vel_1.zip` | 15.370s | 2.622s | mean -30.9 dB / max -11.6 dB |
| `sf2_musyng_kite_daojian_20s.zip` | 3.174s | 0.578s | mean -19.5 dB / max -2.1 dB |

异步回调：

- 客户端：`mgsc_daw_async_client.py`
- 字段：`callbackurl`
- accepted 响应包含 `callbackurl`
- callback 响应 `status=completed`、`async=true`，包含 `mp3_file.base64`
- `sf2_musyng_kite_daojian_20s.zip` 异步总等待约 3.76s

测试报告：

```text
C:\work\workspace_own\workspace_carla\output\test_batch_report_6.5.6.2016_final_20260506_204006.json
```

## 镜像与部署包

镜像：

```text
mgsc_daw_service:6.5.6.2016
image id: sha256:3a20c66326bfee3174d69948b5f78718f4cf3d92fed2d4a6022d97570546fd9a
```

部署包目录：

```text
C:\work\workspace_own\workspace_carla\docker_images
```

需要拷贝到 Ubuntu 的文件：

```text
deploy_mgsc_daw_service.sh
mgsc_daw_service_6.5.6.2016.tar.part01
mgsc_daw_service_6.5.6.2016.tar.part02
mgsc_daw_service_6.5.6.2016.tar.part03
SHA256SUMS_6.5.6.2016.txt
SHA256SUMS_6.5.6.2016_parts.txt
SHA256SUMS_test_zips_6.5.6.2016.txt
MANIFEST_6.5.6.2016.txt
test_zips_6.5.6.2016.zip
```

完整 tar：

```text
mgsc_daw_service_6.5.6.2016.tar
size: 4459125760 bytes
sha256: 98977ea61000c34fb87d8c054dd1064e29c436a0fdb5b8c34818e79cecce945c
```

分片大小：

```text
part01: 1900000000 bytes
part02: 1900000000 bytes
part03: 659125760 bytes
```

## 改动文件

```text
deploy_mgsc_daw_service.sh
music_service/renderer.py
render_midi_to_mp3.py
source/backend/engine/CarlaEngineDummy.cpp
tools/package_docker_image.sh
docs/CLOUD_DAW_ENGINE_HANDOFF_CN.md
docs/ENGINE_EVOLUTION_CN.md
docs/CODEX_APP_HANDOFF_CN.md
```

## 下一步

1. 拷贝上述文件到 Ubuntu。
2. 在 Ubuntu 部署目录运行：

```bash
chmod +x deploy_mgsc_daw_service.sh
HOST_PORT=8000 ./deploy_mgsc_daw_service.sh
```

3. 用 `test_zips_6.5.6.2016.zip` 解压出的非 debug 测试包复验同步和异步接口。
