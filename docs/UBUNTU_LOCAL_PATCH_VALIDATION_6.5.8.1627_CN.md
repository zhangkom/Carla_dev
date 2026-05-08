# 6.5.8.1627 本地实战验证和 Ubuntu 迁移步骤

日期：2026-05-08

## 结论

已在 Windows Docker 本机验证“`mgsc_daw_service:6.5.7.0955` 基础镜像 + 本地最新代码/资产补丁”的启动和渲染流程。

验证容器：

```text
container: mgsc_daw_service_local_patch_6581627
base image: mgsc_daw_service:6.5.7.0955
host port: 18082
health: http://127.0.0.1:18082/mgsc_daw_service/health
result: {"status":"ok","config":"/home/workspace/config/plugins.deploy.json"}
```

代码补丁 `code_patch_mgsc_daw_service_6.5.8.1155.tar.gz` 已和本地 `mgsc_daw_service:6.5.8.1155` 镜像内关键运行文件做 SHA256 对比，关键文件一致，包括：

```text
config/plugins.deploy.json
config/instrument_mapping.deploy.json
music_service/main.py
music_service/async_jobs.py
music_service/auto_routes.py
music_service/render_outputs.py
music_service/midi_policy.py
music_service/renderer.py
music_service/instrument_mapping.py
mgsc_daw_service.py
mgsc_daw_client.py
mgsc_daw_async_client.py
render_midi_to_mp3.py
```

## 本地同步测试结果

测试输入目录：

```text
C:\work\workspace_own\workspace_carla\midi\daojianrumeng_0508
```

输出目录：

```text
C:\work\workspace_own\workspace_carla\output\local_patch_validation_20260508_1819
```

同步接口全部通过，均未使用 `max_seconds` 截断，输出时长约 184 秒：

| zip | route_count | wall seconds | MP3 | mean/max volume | 有声 |
| --- | ---: | ---: | --- | --- | --- |
| `lmms_vst_keyzone_single.zip` | 1 | 31.119 | `lmms_vst_keyzone_single_20260508_182711.mp3` | -28.0 / -7.1 dB | 是 |
| `lmms_sf2_trackname_a.zip` | 5 | 62.227 | `lmms_sf2_trackname_a_20260508_182834.mp3` | -26.6 / -1.2 dB | 是 |
| `lmms_sf2_trackname_b.zip` | 5 | 48.275 | `lmms_sf2_trackname_b_20260508_182936.mp3` | -27.2 / -5.8 dB | 是 |
| `lmms_sf2_vst_trackname_a.zip` | 1 | 19.833 | `lmms_sf2_vst_trackname_a_20260508_183025.mp3` | -20.9 / -3.2 dB | 是 |
| `lmms_sf2_vst_trackname_b.zip` | 1 | 19.791 | `lmms_sf2_vst_trackname_b_20260508_183045.mp3` | -20.9 / -3.2 dB | 是 |
| `lmms_vst_trackname_multi.zip` | 5 | 93.266 | `lmms_vst_trackname_multi_20260508_183104.mp3` | -15.4 / 0.0 dB | 是 |

异步 callback 测试也通过：

```text
zip: lmms_sf2_vst_trackname_a.zip
accepted_status: accepted
final_status: completed
async: true
route_count: 1
output: async_lmms_sf2_vst_trackname_a_20260508_183325.mp3
duration: 184.343 seconds
mean/max volume: -20.9 / -3.2 dB
has_sound: true
```

## Windows 本机启动验证命令

本机使用的补丁目录：

```text
C:\work\workspace_own\workspace_carla\docker_images\ubuntu_reset_6.5.8.1627
```

关键方式：不 commit 新镜像，不改 Wine entrypoint；用旧基础镜像启动时挂载 `/patch`，在容器启动命令里解压代码和资产补丁后运行 `python3 mgsc_daw_service.py`。

## Ubuntu 推荐迁移方式

将整个目录拷贝到 Ubuntu：

```text
C:\work\workspace_own\workspace_carla\docker_images\ubuntu_reset_6.5.8.1627
```

Ubuntu 上执行：

```bash
cd /data/zhangzhihui/zzh/workspace_daw/ubuntu_reset_6.5.8.1627
sed -i 's/\r$//' SHA256SUMS_ubuntu_reset_6.5.8.1627.txt *.sh
sha256sum -c SHA256SUMS_ubuntu_reset_6.5.8.1627.txt
chmod +x run_base_image_with_local_patch_6.5.8.1627.sh
./run_base_image_with_local_patch_6.5.8.1627.sh
```

如果服务器上的基础镜像名称不是 `mgsc_daw_service:6.5.7.0955`，改用：

```bash
BASE_IMAGE=mgsc_daw_service:6.5.7.18001 ./run_base_image_with_local_patch_6.5.8.1627.sh
```

服务端本机验证：

```bash
curl http://127.0.0.1:18001/mgsc_daw_service/health
```

同步 render 验证：

```bash
unzip -o daojianrumeng_0508_test_zips.zip -d test_zips
curl -i --connect-timeout 10 --max-time 7200 \
  -X POST "http://127.0.0.1:18001/mgsc_daw_service/v1/render" \
  -F "data=@test_zips/lmms_vst_keyzone_single.zip"
```

预期：不需要传 `plugin_id` 或 `style_id`，服务端应从 zip 内 `conf.json` + `vst.json` / `sf2.json` 自动解析路线，并返回包含 `mp3_file.base64` 的 JSON。

如果公网转发使用路径前缀，例如 `/mgsc_daw_service_18001`，需要让转发规则把该前缀代理到后端正式前缀 `/mgsc_daw_service`；服务器本机验证始终以 `http://127.0.0.1:18001/mgsc_daw_service/...` 为准。
