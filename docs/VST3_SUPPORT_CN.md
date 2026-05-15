# VST3 支持现状记录

日期：2026-05-15

## 当前结论

Carla 渲染链路已经具备 VST3 基础支持：

- `render_midi_to_mp3.py` 支持 `--plugin-type vst3`，并映射到 Carla 的 `PLUGIN_VST3`。
- `music_service` 配置加载允许插件类型为 `vst3`。
- 当前改动后，VST3 插件路径支持两种形态：
  - 单文件形式，例如 `Tunefish4.vst3`。
  - 标准目录包形式，例如 `PluginName.vst3/`。

但当前正式需求映射仍未把 VST3 作为生产风格启用。原因是 VST3 格式加载成功不等于具体插件已经稳定发声；每个 VST3 插件仍需要独立做有声验证、状态保存和回归测试。

## 本地容器验证

验证容器：

- 镜像：`mgsc_daw_service:6.5.13.2019`
- 容器：`mgsc_daw_service_perf_debug`
- 端口：`18013 -> 8000`

验证插件：

- VST2：`/wineprefix/drive_c/VSTPlugins/Tunefish4/Tunefish4.dll`
- VST3：`/wineprefix/drive_c/VSTPlugins/Tunefish4/Tunefish4.vst3`

验证结果：

| 场景 | 结果 | 音量检测 |
|---|---|---|
| Tunefish4 VST2 裸加载 | 成功发声 | `mean_volume: -12.1 dB`, `max_volume: 0.0 dB` |
| Tunefish4 VST3 `load_file` 裸加载 | 能加载并完成渲染，但接近静音 | `mean_volume: -91.0 dB`, `max_volume: -91.0 dB` |
| Tunefish4 VST3 复用 VST2 `.carxs` state | 能加载并完成渲染，但仍接近静音 | `mean_volume: -91.0 dB`, `max_volume: -91.0 dB` |
| Tunefish4 VST3 `add_plugin` | 加载失败 | `Failed to get plugin description` |

因此，当前可以确认的是：VST3 bridge 能启动，`load_file` 链路能跑通；但 Tunefish4 VST3 还不能作为已验证风格交付。

## 后续接入标准

某个 VST3 插件要进入正式 `plugins.deploy.json` 和需求映射，建议满足以下条件：

1. 插件文件或 `.vst3` 目录包已经进入镜像或部署挂载目录。
2. 使用 Carla/Wine 在 Ubuntu 容器内完成渲染，生成 MP3 非静音。
3. 保存专用 VST3 `.carxs` state，不复用 VST2 state。
4. 使用需求 MIDI 或刀剑如梦 MIDI 完成同步接口回归。
5. 记录音量检测结果、服务耗时、渲染内部耗时。

## 当前建议

短期内继续以已验证的 VST2/SF2/Kong/Sonatina/Keyzone 路径满足需求文档。VST3 作为候选扩展能力保留，等拿到明确需要 VST3 的插件时，再按“插件级验证”方式接入。
