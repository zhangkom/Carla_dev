# Ubuntu + Wine Docker 原型

这个目录用于验证 Windows 本机已经跑通的 Carla + Kong Audio 渲染链路能否迁移到 Ubuntu 容器中。

## 当前设计

容器内分两层运行：

- Linux Python 运行 FastAPI 服务、zip 解包、MIDI policy 和日志。
- Windows embeddable Python 通过 Wine 运行 `render_midi_to_mp3.py`，加载 Windows Carla DLL 和 Windows VST2/VST3 插件。

路径模式：

- 服务配置使用 `renderer_path_mode: "wine"`。
- Linux 路径会在调用 renderer 时转换为 Wine 的 `Z:\...` 路径。
- renderer 返回的 `Z:\...` 输出路径会转回 Linux 路径，供 API 下载和文件检查使用。

## 本机挂载约定

Docker Compose 示例默认使用以下 Windows 本机路径：

```text
C:\VSTPlugins\KongAudio
C:\ffmpeg
E:\Kong Audio Library
```

其中：

- `C:\VSTPlugins\KongAudio` 应包含 `Qin_RV_x64.DLL` 和 Kong 的 XML/辅助文件。
- `C:\ffmpeg` 应包含 Windows 版 `bin\ffmpeg.exe`。
- `E:\Kong Audio Library` 是已执行 `Locate_Library_Here.exe` 后定位过的 Kong 音源库。

这些资产不进入 Git。

## 构建镜像

在仓库根目录执行：

```powershell
docker compose -f docker\wine\compose.windows.yml build
```

## 启动服务

```powershell
docker compose -f docker\wine\compose.windows.yml up
```

服务启动后验证：

```powershell
curl.exe --noproxy "*" http://127.0.0.1:8000/health
curl.exe --noproxy "*" http://127.0.0.1:8000/v1/catalog
```

## 快速渲染验证

先用短 MIDI 验证 Wine + Carla + Kong 是否能出声/出文件，避免每次等待完整 180 秒。

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

## 预期风险

- Windows Carla runtime 的 `bin` 目录必须随 `/app` 挂载进入容器。
- Kong `.carxs` 状态中的 DLL 路径应尽量保持为 `C:\VSTPlugins\KongAudio\Qin_RV_x64.DLL`。
- Wine 图形和音频后端可能影响 Carla engine 初始化。
- 如果 DirectSound 在容器中不可用，需要继续验证 Wine 下可用的虚拟音频后端。
- 只有 Docker Desktop/WSL2 跑通还不代表真实 Ubuntu 服务器完全等价，最终仍需在目标 Ubuntu 服务器上验收。
