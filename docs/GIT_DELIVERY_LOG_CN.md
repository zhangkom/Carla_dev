# Git 阶段性交付记录

本文档用于补充 Git 提交历史中的中文交付说明，避免重写已经推送到远端的历史提交。

## 记录规则

后续提交信息统一采用中文描述，建议格式如下：

```text
当前完成：一句话说明本次完成的可交付内容；下一步：一句话说明后续计划
```

如果一次提交涉及较多内容，可以在提交正文中继续补充：

```text
当前完成：
- 完成内容 1
- 完成内容 2

验证情况：
- 编译或测试结果

下一步：
- 后续计划
```

## 2026-05-14 提交历史中文补充

当前分支：`perf/keyzone-render-speed`

当前阶段版本：

```text
代码版本分支：6.5.13.2019
Docker 镜像：mgsc_daw_service:6.5.13.2019
正式业务接口：POST /mgsc_daw_service/v1/render
```

当前完成：

- 完成正式渲染接口输入输出协议收敛，公开 multipart 字段保留 `data` 和 `callbackurl`。
- 同步返回精简为业务调用需要的字段：`http_code`、`status`、`error`、`job_id`、`plugin_id`、`style_id`、`output_basename`、`elapsed_seconds`、`mp3_file.base64`。
- 异步 accepted 返回精简为：`http_code`、`job_id`、`status`、`error`、`callbackurl`。
- 调试信息统一放入 `debug=true` 场景，默认不返回内部路由、编码和渲染阶段明细。
- MP3 编码支持通过 `conf.json` 控制 `mp3_mode`、`mp3_quality`、`mp3_compression_level`、`bitrate`。
- 修复并验证 Keyzone Classic 在云端容器中的静音问题，保留性能调试能力。
- 完成 `6.5.13.2019` 镜像打包，修复 Windows 环境下 Python 回退导致的分片脚本问题。
- 已将 `main`、`6.5.13.2019`、`perf/keyzone-render-speed` 推送到远端最新提交。

验证情况：

- `python -m compileall music_service mgsc_daw_service.py mgsc_daw_client.py mgsc_daw_async_client.py render_midi_to_mp3.py tools` 已通过。
- `mgsc_daw_service:6.5.13.2019` 健康检查通过。
- `sf2_musyng_kite_daojian_20s.zip` 通过 `/mgsc_daw_service/v1/render` 同步渲染冒烟验证，返回 `status=success` 且包含 MP3 base64。

下一步：

- 在 Ubuntu 侧用正式镜像复核 `18003` 部署和公网转发访问。
- 按 `云端DAW音频工作站引擎_v2.docx` 的映射表继续补齐全量需求用例的测试记录。
- 对 Keyzone 类插件继续做性能对比，确认 Windows 与 Ubuntu 环境差异是否还能进一步收敛。
- 根据需求方反馈继续调整专利交底书和客户端调用说明。

## 近期英文提交对照说明

以下条目不修改原提交哈希，仅补充中文解释。

| 原提交 | 中文补充 |
| --- | --- |
| `3cbdfb4 chore: remove async flag from render responses` | 当前完成：移除对外返回中的 `async` 字段，避免客户端把交付模式当成业务字段处理；下一步：继续精简同步和异步响应结构。 |
| `e5ce8bc chore: slim async and error response fields` | 当前完成：精简异步 accepted 和错误响应字段，去掉 `status_url`、`accepted_at`、`detail` 等非必要字段；下一步：把最终返回结构同步到接口文档。 |
| `5072571 feat: standardize render response envelope` | 当前完成：统一同步、异步和错误场景的响应外层结构，增加 `http_code`、`status`、`error`；下一步：按商业客户端使用场景继续减少默认字段。 |
| `3395eb6 chore: finalize 6.5.13.1428 delivery metadata` | 当前完成：固化 6.5.13.1428 交付元数据和部署包信息；下一步：在新协议确认后继续推进 6.5.13.2019 正式包。 |
| `a686d5e chore: bump deployment version to 6.5.13.1143` | 当前完成：更新部署版本号到 6.5.13.1143；下一步：继续验证 Keyzone 性能与输出字段收敛。 |
| `cac513e feat: trim non-debug render response` | 当前完成：默认响应只保留必要业务字段，内部诊断字段仅在调试场景返回；下一步：补充 debug 开关的文档说明。 |
| `73adff0 feat: add render debug response mode` | 当前完成：新增渲染接口 debug 返回模式，便于排查路由、MIDI 预处理、编码和耗时问题；下一步：把 debug 默认值固定为 false。 |
| `536db28 perf: speed up keyzone render path` | 当前完成：优化 Keyzone 渲染路径，降低云端容器中单次渲染等待时间；下一步：继续用刀剑如梦 MIDI 做需求映射全量回归。 |
| `e8d858c perf: add dummy sleep divisor for keyzone probes` | 当前完成：增加 Keyzone 专用 Dummy sleep divisor 探测能力；下一步：比较 Windows 与 Ubuntu 环境下的输出是否稳定有声。 |
| `5ad3efd perf: add keyzone render diagnostics` | 当前完成：增加 Keyzone 渲染诊断日志，便于定位静音和耗时异常；下一步：根据诊断结果决定回退或加速策略。 |

## 后续提交消息示例

```text
当前完成：补充接口协议中文交付记录；下一步：在 Ubuntu 18003 环境复核正式镜像
```

```text
当前完成：完成需求映射全量 zip 回归并生成测试报告；下一步：继续优化 Keyzone 类插件渲染耗时
```

```text
当前完成：更新专利交底书格式和流程图；下一步：根据需求方反馈补充权利要求保护范围
```
