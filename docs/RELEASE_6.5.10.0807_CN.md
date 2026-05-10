# 6.5.10.0807 阶段验证记录

## 版本定位

`6.5.10.0807` 是 2026-05-10 Windows 本机回归通过的阶段性版本，用于替换 Ubuntu 商用环境中原始 `6.5.9.1821` 镜像。

本版本保留 `6.5.9.1821` 已完成的接口、日志、归档、LMMS 输入兼容和业务映射能力，并额外修复 Kong Audio 在 Wine 中的音源库盘符映射问题。

## 关键修复

1. `docker/wine/mgsc-daw-entrypoint.sh` 优先保留内置 `/wineprefix/kong-library-drive`，避免把 Wine `E:` 指到空的 `/kong-library`。
2. `deploy_mgsc_daw_service.sh` 兼容旧 Bash，避免 Ubuntu 上因为空数组或启动命令处理失败。
3. `mgsc_daw_client.py` 兼容没有 `http.server.ThreadingHTTPServer` 的旧 Python。
4. 单显式 `style_id` 渲染恢复全通道输入行为；`style_id=auto` 和多轨手动路由仍按各自路由拆分。

## Windows 本机验证环境

```text
image: mgsc_daw_service:6.5.10.0807
container: mgsc_daw_service_winverify_65100807
port: 18110 -> 8000
MUSIC_SERVICE_DUMMY_NOSLEEP=1
Kong Wine E: /wineprefix/kong-library-drive
```

## 回归结果

| 测试项 | 结果 |
| --- | --- |
| `/mgsc_daw_service/health` | 通过 |
| 旧 `/v1/render` | 返回 404，符合只保留前缀接口的要求 |
| 同步接口 | 通过，返回 `mp3_file.base64` |
| 异步 `callbackurl` | 通过，先返回 accepted，完成后 callback 返回 MP3 base64 |
| SF2 Musyng Kite 20 秒包 | 非静音，RMS 约 -19.5 dB |
| Kong GaoHu Sus Leg MW | 非静音，`record_audio_seconds` 约 3 秒 |
| Kong GaoHu Stac/Tremolo/Trill | 均非静音，`record_audio_seconds` 约 2.8 到 3.0 秒 |
| LMMS 单 VST Keyzone 输入 | 非静音 |
| LMMS SF2/VST 多 track 输入 | 非静音，按 `id` 路由 |
| `style_id=auto` 完整 MIDI | 通过，9 路自动混音，匹配 Keyzone、Musyng Kite、Sonatina、Kong 和 Bank 128 鼓组 |
| 日志和归档 | 通过，按日期/job_id 保存输入 zip、MP3、WAV |

## 与 6.5.9.1821 的关键差异

同样使用 `MUSIC_SERVICE_DUMMY_NOSLEEP=1` 测试 `kong_gaohu_sus_leg_mw.zip`：

```text
6.5.9.1821:
  Kong E: /kong-library
  /kong-library 文件数: 0
  record_audio_seconds: 2.564s
  MP3: 静音，Peak=-inf, RMS=-inf

6.5.10.0807:
  Kong E: /wineprefix/kong-library-drive
  record_audio_seconds: 约 3s
  MP3: 非静音
```

因此 Ubuntu 商用环境不建议继续使用原始 `6.5.9.1821` 作为最终基线，应升级到 `6.5.10.0807` 或至少同步 Kong Wine 音源库映射修复后重新保存镜像。

## 业务需求覆盖

根据 `C:\work\workspace_own\workspace_carla\doc\云端DAW音频工作站引擎_v2.docx`：

- 支持云端 Carla 服务化渲染。
- 支持 zip 输入，包含 MIDI 与 `conf.json`，并兼容 `vst.json`、`sf2.json` 多轨输入。
- 支持同步和异步 `callbackurl` 两种调用方式。
- 支持 MP3 base64 返回。
- 支持 137 条 Bank/Program 映射：Bank 0 的 GM 128 音色与 Bank 128 的 9 个鼓组。
- 正式映射音源覆盖 Musyng Kite、Kong、Keyzone Classic、Sonatina Orchestra、DSK Saxophones。

`FluidR3_GM`、A320U、Vital、DSK Asian DreamZ 等目前属于显式候选或扩展风格，不属于当前 137 条正式自动映射的替换底座。
