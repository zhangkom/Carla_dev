# Codex App 交接记录

日期：2026-05-06  
分支：`6.5.7.0955`  
工程目录：`C:\work\workspace_own\workspace_carla\Carla-2.5.10`

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

1. 保留 `/v1/render` 唯一入口。
2. 不传 `callbackurl` 时同步返回 `mp3_file.base64`。
3. 传 `callbackurl` 时异步 accepted，后台渲染完成后 POST 完整 JSON 到 `callbackurl`。
4. 修复 `v6.4.43` Dummy offline 加速导致 Kong Audio 静音的问题。
5. 准备 Ubuntu 部署包，镜像分片小于 2GB。

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
