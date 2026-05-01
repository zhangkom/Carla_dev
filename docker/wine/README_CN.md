<!--
/**
* File name: README_CN.md
* Brief: MGSC DAW 项目文档
* Function:
*     记录云端 DAW 服务接口、部署、状态或开发规范
* Author: 咪咕数创工程架构组
*     MGSC AI Software Architecture group
* Version: V2.5.10
* Date: 2026/04/30
*/
-->

# Ubuntu + Wine Docker 原型

这个目录用于验证 Windows 本机已经跑通的 Carla + Kong Audio 渲染链路能否迁移到 Ubuntu 容器中。

## 当前结论

已验证可行的方案是：

- Linux Python 运行 FastAPI 服务、zip 解包、MIDI policy、日志和 MP3 转码。
- Linux 原生 `libcarla_standalone2.so` 运行 Carla engine。
- Carla 官方 Wine bridge 加载 Windows VST 插件。
- Kong Audio 当前使用 32 位 `Qin_RV.DLL`，不要在容器渲染链路里使用 `Qin_RV_x64.DLL`。

不采用的方案：

- Wine 内运行 Windows Python + Windows `libcarla_standalone2.dll`。这个方案在 Wine 加载 Carla DLL 时会崩溃或卡死，不适合作为服务器方案。
- Kong `Qin_RV_x64.DLL`。它在当前环境下可以被加载，但实测无声；当前用 direct 32 位 `Qin_RV.DLL` 出声。

对应服务配置为：

```json
{
  "renderer_path_mode": "native_bridge",
  "plugin_load_mode": "load_file",
  "carla_backend": "/opt/carla-service/bin/libcarla_standalone2.so",
  "carla_bin_dir": "/opt/carla-service/bin",
  "carla_resources_dir": "/opt/carla-service/bin/resources",
  "carla_frontend_dir": "/opt/carla-service/source/frontend"
}
```

## 本机挂载约定

Docker Compose 示例默认使用以下 Windows 本机路径：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\kong_audio\qin_rv_v2_2\installer
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\kong_audio\qin_rv_v2_2\library
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\kong_audio\qin_rv_v2_2\vst2
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\soundfont2
```

其中：

- `installer` 映射到 Wine 的 `D:`，用于在容器桌面中手动运行 `Qin_RV_Setup_v2.2.exe`。
- `library` 是从 `E:\Kong Audio Library` 复制出来的普通目录。Docker Desktop 不能稳定挂载 mounted ISO/光驱盘符，所以不要直接挂载 `E:`。
- `vst2` 是 Windows 本机 `C:\VSTPlugins\KongAudio` 的备份副本，用于保留已安装插件文件。
- `soundfont2` 映射到容器的 `/app/assets/soundfont2`，用于 `Musyng_Kite.sf2` 的 SoundFont 渲染。
- Kong 安装目标使用 Wine prefix 内部的 `C:\VSTPlugins\KongAudio`，保存在 compose 的 `wineprefix` 命名卷中。
- 当前已验证 Kong 需要真实目录 `E:\Kong Audio Library\ChineeGaoHu`。只把 `E:` 指向 Linux symlink 时，插件会报找不到音色文件。

Compose 会通过以下环境变量把音色库复制到 Wine prefix 内部的真实目录：

```yaml
KONG_LIBRARY_MATERIALIZE: "true"
KONG_LIBRARY_FOLDERS: ChineeGaoHu
KONG_REGISTER_INSTRUMENTS: ChineeGaoHu
KONG_INSTRUMENT_VERSION: v2.1.2.0
```

这些资产不进入 Git。

## 构建镜像

Compose 默认使用清华 Ubuntu 源：

```yaml
APT_MIRROR: https://mirrors.tuna.tsinghua.edu.cn/ubuntu
PIP_INDEX_URL: https://pypi.tuna.tsinghua.edu.cn/simple
```

当前 native bridge 方案不需要 Windows embeddable Python，`INSTALL_WINPYTHON` 默认关闭，减少构建时对 `python.org` 的依赖。

在仓库根目录执行：

```powershell
docker compose -f docker\wine\compose.windows.yml build
```

当前镜像会构建 Carla win32 Wine bridge：

```text
/opt/carla-service/bin/carla-bridge-win32.exe
/opt/carla-service/bin/carla-discovery-win32.exe
/opt/carla-service/bin/jackbridge-wine32.dll
```

## 启动服务

```powershell
docker compose -f docker\wine\compose.windows.yml up -d
```

服务启动后验证：

```powershell
curl.exe --noproxy "*" http://127.0.0.1:8000/health
curl.exe --noproxy "*" http://127.0.0.1:8000/v1/catalog
```

`/v1/catalog` 里应看到 `kong_qin_rv` 的 `path_exists=true`，4 个 `ChineeGaoHu` 风格 `ready=true`。

## VNC 桌面安装 Kong

当前 compose 会启动一个只绑定本机的 VNC 端口：

```text
127.0.0.1:5901
```

默认密码：

```text
carla
```

连接后会自动打开 Wine 文件管理器。手动安装流程：

1. 打开 `D:\Qin_RV_Setup_v2.2.exe`。
2. 安装目录选择 `C:\VSTPlugins\KongAudio`。
3. 如果需要手动定位音色库，运行 `E:\Kong Audio Library\Locate_Library_Here.exe`。
4. 安装完成后访问 `/v1/catalog`，确认 `kong_qin_rv` 的 `path_exists=true`，4 个风格 `ready=true`。

注意：`wineprefix` 是 Docker 命名卷。执行 `docker compose -f docker\wine\compose.windows.yml down -v` 会删除容器内安装好的 Kong，需要重新安装。

## 快速渲染验证

短 MIDI 验证可以避免每次等待完整曲目：

```powershell
curl.exe --noproxy "*" -X POST http://127.0.0.1:8000/v1/render `
  -F "style_id=kong_gaohu_sus_leg_mw" `
  -F "max_seconds=8" `
  -F "midi=@C:\work\workspace_own\workspace_carla\midi\debug_ch1_note_only_10s.mid"
```

完整 4 风格验证使用：

```powershell
python tools\call_render_zip.py `
  C:\work\workspace_own\workspace_carla\midi\zip_kong_4styles_full_new_20260427200913\kong_gaohu_sus_leg_mw.zip `
  C:\work\workspace_own\workspace_carla\midi\zip_kong_4styles_full_new_20260427200913\kong_gaohu_stac_1.zip `
  C:\work\workspace_own\workspace_carla\midi\zip_kong_4styles_full_new_20260427200913\kong_gaohu_trill_vel_1.zip `
  C:\work\workspace_own\workspace_carla\midi\zip_kong_4styles_full_new_20260427200913\kong_gaohu_tremolo_vel_1.zip `
  --url http://127.0.0.1:8000/v1/render `
  --timeout 3600
```

## 已验证结果

当前容器内已验证：

- `/v1/catalog` 返回 1 个插件、4 个风格，且 4 个风格均 `ready=true`。
- 短 MIDI 通过 API 渲染成功，输出 320k MP3 和 16-bit WAV。
- 生成 WAV 为 `44100Hz`、双声道、16-bit，且 RMS/峰值非零。
- 日志会写入 `/app/logs/YYYY-MM-DD.log`，包含 `record_audio_seconds`、`record_idle_wall_seconds`、`add_instrument_seconds`、`ffmpeg_mp3_seconds` 等细分耗时。

当前服务仍是单进程阻塞式渲染。并发请求会排队或互相等待，生产环境需要增加任务队列、并发控制和 worker 池。

## 预期风险

- Docker Desktop/WSL2 跑通不等于真实 Ubuntu 服务器完全等价，最终仍需在目标 Ubuntu 服务器上验收。
- 当前只验证了 `ChineeGaoHu` 的 4 个风格，其他 Kong 乐器需要逐个按同样方式保存状态、复制音色库、跑短 MIDI 和完整 MIDI。
- 如果未来切换到其他插件，优先确认插件位数、Wine bridge 位数、音色库路径和 `.carxs` 状态是否一致。
