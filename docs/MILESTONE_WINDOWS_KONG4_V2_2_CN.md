# 阶段性成果：Windows 本机 Kong Audio 4 风格验证通过

日期：2026-04-28

## 阶段目标

本阶段目标是先在 Windows 本机环境中跑通 Carla 音乐服务的最小可用闭环，验证以下内容：

- Carla 可以加载 Kong Audio `Qin_RV_x64.DLL`。
- Carla GUI 保存的 `.carxs` 状态可以在无 GUI 渲染脚本中复用。
- FastAPI 服务可以接收 zip 输入。
- zip 内 `conf.json` 严格符合 v2.2 文档第 5.2 节定义。
- 服务可以自动处理 MIDI 通道和 MIDI policy。
- 服务可以输出 320 kbps MP3 和 16-bit WAV。
- 服务日志可以记录每个渲染阶段耗时。

## 已验证输入格式

zip 输入目录：

```text
C:\work\workspace_own\workspace_carla\midi\zip_kong_4styles_full_new_20260427200913
```

zip 内文件结构：

```text
song.mid
conf.json
```

`conf.json` 格式：

```json
{
  "style_id": "kong_gaohu_stac_1",
  "render": {
    "format": "mp3",
    "bitrate": 320,
    "bit_depth": 16,
    "loop": false
  },
  "output": {
    "samplerate": 44100
  }
}
```

正式客户端不再传入以下字段：

- `apply_midi_policy`
- `midi_source_channel`
- `midi_target_channel`
- `max_seconds`
- `conf.import`
- `vstDir`
- `vstConf`
- `sf2Dir`
- `sf2Conf`

## 已验证风格

| style_id | 插件 | 乐器 | 演奏法 | 状态文件 |
|---|---|---|---|---|
| `kong_gaohu_sus_leg_mw` | `kong_qin_rv` | ChineeGaoHu | Sus_Leg_1_MW | `states\kong_gaohu_sus_leg_mw.carxs` |
| `kong_gaohu_stac_1` | `kong_qin_rv` | ChineeGaoHu | Stac_1 | `states\kong_gaohu_stac_1.carxs` |
| `kong_gaohu_trill_vel_1` | `kong_qin_rv` | ChineeGaoHu | Trill_Vel_1 | `states\kong_gaohu_trill.carxs` |
| `kong_gaohu_tremolo_vel_1` | `kong_qin_rv` | ChineeGaoHu | Tremolo_Vel_1 | `states\kong_gaohu_tremolo.carxs` |

## 最近一次验证结果

调用方式：

```powershell
python tools\call_render_zip.py `
  C:\work\workspace_own\workspace_carla\midi\zip_kong_4styles_full_new_20260427200913\kong_gaohu_sus_leg_mw.zip `
  C:\work\workspace_own\workspace_carla\midi\zip_kong_4styles_full_new_20260427200913\kong_gaohu_stac_1.zip `
  C:\work\workspace_own\workspace_carla\midi\zip_kong_4styles_full_new_20260427200913\kong_gaohu_trill_vel_1.zip `
  C:\work\workspace_own\workspace_carla\midi\zip_kong_4styles_full_new_20260427200913\kong_gaohu_tremolo_vel_1.zip `
  --url http://127.0.0.1:8000/v1/render `
  --timeout 3600
```

输出文件：

```text
C:\work\workspace_own\workspace_carla\Carla-2.5.10\output\song_Kong_GaoHu_Sus_Leg_MW_202604281444.mp3
C:\work\workspace_own\workspace_carla\Carla-2.5.10\output\song_Kong_GaoHu_Stac_1_202604281447.mp3
C:\work\workspace_own\workspace_carla\Carla-2.5.10\output\song_Kong_GaoHu_Trill_Vel_1_202604281451.mp3
C:\work\workspace_own\workspace_carla\Carla-2.5.10\output\song_Kong_GaoHu_Tremolo_Vel_1_202604281454.mp3
```

日志文件：

```text
C:\work\workspace_own\workspace_carla\Carla-2.5.10\logs\2026-04-28.log
```

日志确认每个请求都应用了 v2.2 渲染参数：

```text
render_options={"bit_depth": 16, "bitrate": "320k", "format": "mp3", "loop": false, "samplerate": 44100}
```

编码结果：

```text
mp3_bitrate=320k
mp3_sample_rate=44100
mp3_channels=2
wav_bit_depth=16
wav_sample_rate=44100
wav_channels=2
```

## 当前性能结论

4 个风格单次渲染耗时约 188 到 189 秒。

主要耗时不是插件加载，也不是 MP3 转码，而是实时录制：

```text
record_audio_seconds ~= 184.5s
record_idle_wall_seconds ~= 184.3s
record_idle_sleep_seconds ~= 184.2s
transport_play_seconds ~= 0.000s
```

结论：

- `transport_play()` 本身不阻塞。
- 当前 Carla 渲染路径是按 MIDI 实际时长实时播放并录 WAV。
- 如果后续要优化 180 秒耗时，重点不是 Python 调用层，而是研究 Carla 是否支持离线/非实时渲染路径。

## 当前技术基线

Windows 本机基线已经成立：

```text
FastAPI -> zip/conf.json -> MIDI policy -> Carla Windows runtime -> Kong Qin_RV_x64 -> Audio Recorder -> WAV -> ffmpeg MP3
```

下一阶段迁移验证目标：

```text
FastAPI/Linux Python -> Wine -> Windows Python/Carla runtime -> Kong Qin_RV_x64 -> Audio Recorder -> WAV -> ffmpeg MP3
```

## 下一步计划

下一步不建议继续等全部风格做完再迁移。应该先把已经验证通过的 4 个 Kong 风格迁移到 Ubuntu + Wine Docker 原型镜像中。

迁移顺序：

1. 创建 Ubuntu + Wine Docker 原型镜像。
2. 在镜像中准备 64 位 Wine prefix。
3. 放入或挂载 Windows Carla 运行时。
4. 放入或挂载 Kong Audio `Qin_RV_x64.DLL`。
5. 放入或挂载 Kong Audio Library。
6. 在 Wine 中准备可运行的 Windows Python 环境。
7. 先用 10 秒 debug MIDI 做快速验证。
8. 再用当前 4 个 v2.2 zip 做完整验证。
9. 如果 Docker Desktop/WSL2 下验证通过，再把同一镜像部署到真实 Ubuntu 服务器做最终验收。

注意事项：

- Wine 支持 64 位 Windows 程序，不是只能跑 32 位。
- 当前优先路线是 64 位 Wine + 64 位 Carla Windows 运行时 + `Qin_RV_x64.DLL`。
- 不建议现在切换到 32 位 Qin 插件，除非后续遇到某个插件只有 32 位版本。
- 插件二进制、采样库、授权文件和生成音频不进入 Git，应通过挂载或私有制品方式进入运行环境。
