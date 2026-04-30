# 云端 DAW 音频工作站引擎实现交接记录

版本：V2.5.10  
日期：2026/04/30  
依据文档：`C:\work\workspace_own\workspace_carla\doc\云端DAW音频工作站引擎.docx`  
工程目录：`C:\work\workspace_own\workspace_carla\Carla-2.5.10`  
资产目录：`C:\work\workspace_own\workspace_carla\mgsc_daw_assets`

## 1. 最终目标

按照 `云端DAW音频工作站引擎.docx` 实现云端 DAW 音频工作站引擎。

目标能力如下：

1. 在 Ubuntu 服务器上通过 Docker 镜像部署 FastAPI 服务。
2. 部署时只需要拷贝镜像和部署脚本，脚本创建容器 `mgsc_daw_service_kom`。
3. 进入容器后执行 `python mgsc_daw_service.py` 启动服务。
4. 客户端执行 `python mgsc_daw_client.py`，把指定 zip 发送给服务端。
5. 服务端渲染 MIDI，返回 MP3 的 base64 数据。
6. 客户端收到返回后直接保存 MP3 文件。
7. 后续最终要按文档中的 MIDI Bank、Program、云端音源映射，实现多插件音源路由和混音。

输出文件命名规则固定为：

```text
<MIDI文件名>_<插件或风格名>_<yyyyMMddHHmm>.mp3
```

示例：

```text
刀剑如梦_Kong_GaoHu_Tremolo_Vel_1_202604271839.mp3
```

## 2. 当前已经完成的状态

当前代码主线最近关键提交：

```text
c1dc726 固化输出命名和中文文件名兼容
2eb8f66 接入Musyng Kite SoundFont渲染
60e25f9 支持外部端口和MP3 Base64返回
```

当前已完成能力：

1. FastAPI 服务 `/v1/render` 可接收 zip 并渲染音频。
2. 服务端返回中包含 `mp3_file.base64`。
3. `mgsc_daw_client.py` 可从 base64 保存 MP3。
4. `mgsc_daw_client.py` 已兼容 Python 3.6。
5. 部署脚本支持外部端口映射到容器内部服务端口。
6. 输出 MP3/WAV 文件名已使用 MIDI 原始文件名、插件或风格名、当前时间。
7. zip 内中文 MIDI 文件名已做常见编码恢复，能保留中文名。
8. `Musyng_Kite.sf2` 已接入为 `sf2_musyng_kite`。
9. Kong Audio 当前 4 个高胡风格已验证通过，音效正确。

当前服务配置中已正式接入：

```text
插件：kong_qin_rv
风格：
  kong_gaohu_sus_leg_mw
  kong_gaohu_stac_1
  kong_gaohu_trill_vel_1
  kong_gaohu_tremolo_vel_1

插件：sf2_musyng_kite
风格：
  sf2_musyng_kite_gm
```

## 3. 当前可部署镜像状态

当前可部署镜像版本：

```text
mgsc_daw_service:v6.4.33
```

镜像导出目录：

```text
C:\work\workspace_own\workspace_carla\docker_images
```

主要交付文件：

```text
deploy_mgsc_daw_service.sh
mgsc_daw_service_v6.4.33.tar.part01
mgsc_daw_service_v6.4.33.tar.part02
mgsc_daw_service_v6.4.33.tar.part03
SHA256SUMS_v6.4.33.txt
SHA256SUMS_v6.4.33_parts.txt
test_zips_v6.4.33.zip
```

Ubuntu 合并镜像：

```bash
cat mgsc_daw_service_v6.4.33.tar.part01 mgsc_daw_service_v6.4.33.tar.part02 mgsc_daw_service_v6.4.33.tar.part03 > mgsc_daw_service_v6.4.33.tar
sha256sum mgsc_daw_service_v6.4.33.tar
```

期望 SHA256：

```text
B4C1CC81FC01A52EDA46BF6ED225C5BD8B17390EBA48821DE9FF4017E16FADF6
```

部署示例：

```bash
chmod +x deploy_mgsc_daw_service.sh
HOST_PORT=8000 ./deploy_mgsc_daw_service.sh
docker exec -it mgsc_daw_service_kom bash
cd /home/workspace
python mgsc_daw_service.py
```

## 4. 文档中的最终插件和音源映射目标

`云端DAW音频工作站引擎.docx` 的核心表格定义了 137 条映射：

1. 128 个 GM 普通音色，Bank 0，Program 0-127。
2. 9 个鼓组音色，Bank 128。

云端目标音源分布：

| 云端音源 | 数量 | 本地资产状态 | 当前服务状态 |
| --- | ---: | --- | --- |
| Musyng_Kite | 111 | 已有 `Musyng_Kite.sf2` | 已接入并验证 |
| Sonatina Orchestra | 17 | 已有 DLL、MSE、预设 txt | 未接入服务 |
| Keyzone Classic | 5 | 已有 DLL、MSE、预设 txt | 未接入服务 |
| Kong | 2 | 已有扬琴、古筝库 | 当前只接入高胡 4 风格 |
| DSK Saxophones | 2 | 已有 DLL、MSE、预设 txt | 未接入服务 |

本地资产主要路径：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\soundfont2\Musyng_Kite.sf2
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\Keyzone Classic
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\Sonatina Orchestra
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\DSK Saxophones
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\kong_audio\qin_rv_v2_2
```

当前已经把 Word 文档中的映射表抽取成结构化配置：

```text
config\instrument_mapping.deploy.json
```

配置生成工具：

```text
tools\build_instrument_mapping_from_docx.py
```

重新生成命令：

```powershell
python tools\build_instrument_mapping_from_docx.py
```

当前生成结果：

```text
mapping_count: 137
normal_gm_count: 128
drum_bank_count: 9
needs_confirmation_count: 15
plugin_counts:
  DSK Saxophones: 2
  Keyzone Classic: 5
  Musyng_Kite: 111
  Sonatina Orchestra: 17
  kong: 2
```

说明：该配置目前只作为后续开发依据，当前 FastAPI 服务不会自动加载它，因此不会影响已经跑通的 Kong GaoHu 4 风格。

## 5. 需要确认或兼容的表格问题

这些问题已反馈给用户，用户正在确认。后续实现时需要按确认结果修正文档或在配置中做兼容映射。

### 5.1 Sonatina Orchestra

1. MIDI 40，小提琴

文档写法：

```text
Sonatina violin / Solo Violin
```

本地实际路径：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\Sonatina Orchestra\Sonatina Orchestra\Sonatina Violin\Solo Violin.txt
```

问题：`violin` 大小写不一致，Linux 容器路径可能区分大小写，建议统一为 `Sonatina Violin`。

2. MIDI 46，竖琴

文档写法：

```text
Sonatina Harp / default group
```

本地实际路径：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\Sonatina Orchestra\Sonatina Orchestra\Sonatina Harp\Default Group.txt
```

问题：`default group` 大小写不一致，建议统一为 `Default Group`。

3. MIDI 57，长号

文档写法：

```text
Sonatina Trombone / Tensor Trombone
```

本地实际路径：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\Sonatina Orchestra\Sonatina Orchestra\Sonatina Trombone\Tenor Trombone.txt
```

问题：`Tensor Trombone` 应该是 `Tenor Trombone`。

4. MIDI 58，大号

文档写法：

```text
Sonatina Tuba / Tuba  / Sustain
```

本地实际路径：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\Sonatina Orchestra\Sonatina Orchestra\Sonatina Tuba\Tuba Sustain.txt
```

问题：文档里多了 `/` 和多余空格，应兼容或修正为 `Tuba Sustain`。

5. MIDI 60，圆号

文档写法：

```text
Sonatina Horn / Solo  / Horn
```

本地实际路径：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\Sonatina Orchestra\Sonatina Orchestra\Sonatina Horn\Solo Horn.txt
```

问题：文档里多了 `/` 和多余空格，应兼容或修正为 `Solo Horn`。

6. MIDI 70，大管

文档写法：

```text
Sonatina Bassoom / Solo Bassoon
```

本地实际路径：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\Sonatina Orchestra\Sonatina Orchestra\Sonatina Bassoon\Solo Bassoon.txt
```

问题：`Bassoom` 应该是 `Bassoon`。

7. MIDI 71，单簧管

文档写法：

```text
Sonatina Clarinet / Solo / Clarinet
```

本地实际路径：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\Sonatina Orchestra\Sonatina Orchestra\Sonatina Clarinet\Solo Clarinet.txt
```

问题：文档里多了 `/`，应兼容或修正为 `Solo Clarinet`。

### 5.2 DSK Saxophones

1. MIDI 64，高音萨克斯

文档写法：

```text
DSK Saxophones / ？ / Soprano /  Sax
```

本地实际路径：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\DSK Saxophones\DSK Saxophones\Soprano Sax.txt
```

问题：Bank 写为 `？`，Program 里多了 `/` 和多余空格，应兼容或修正为 `Soprano Sax`。

2. MIDI 66，次中音萨克斯

文档写法：

```text
DSK Saxophones / ？ / Tenor Sax
```

本地实际路径：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\DSK Saxophones\DSK Saxophones\Tenor Sax.txt
```

问题：Bank 写为 `？`，后续配置中不能直接保留 `？`，需要表达为无 Bank 或插件预设名。

### 5.3 Keyzone Classic

以下 5 条文档中 Bank 都写为 `？`，本地实际是插件预设文件，不是 SF2 Bank/Program。

本地目录：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\Steinberg\VstPlugins\Keyzone Classic\Keyzone Classic
```

本地已有预设：

```text
Basic Electric Piano.txt
Keyzone Piano.txt
Rhodes Piano.txt
Steinway Piano.txt
Yamaha Grand Piano.txt
```

涉及条目：

| MIDI | 用户音源名 | 文档 Program | 本地文件 |
| ---: | --- | --- | --- |
| 0 | 大钢琴 Acoustic Grand Piano | Steinway Piano | Steinway Piano.txt |
| 1 | 立式钢琴 | Yamaha Grand Piano | Yamaha Grand Piano.txt |
| 2 | 电钢琴 | Basic Electric Piano | Basic Electric Piano.txt |
| 4 | 电钢琴1 | Basic Electric Piano | Basic Electric Piano.txt |
| 5 | 电钢琴2 | Basic Electric Piano | Basic Electric Piano.txt |

问题：Bank 为 `？`，后续配置中要表达为插件预设，不是 SF2 Bank。

### 5.4 Kong

1. MIDI 15，扬琴

文档写法：

```text
kong / yangqin / 02 Sus_mp
```

本地实际目录：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\kong_audio\qin_rv_v2_2\library\ChineeYangQin
```

问题：

1. `yangqin` 是逻辑名，不是本地真实目录名。
2. 当前服务只验证了 Kong GaoHu 4 个状态，尚未建立 YangQin 状态文件。

2. MIDI 107，筝

文档写法：

```text
kong / chineseGuZheng / 03 Sus_Shake_2
```

本地可能目录：

```text
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\kong_audio\qin_rv_v2_2\library\ChineeGuZheng_Classic
C:\work\workspace_own\workspace_carla\mgsc_daw_assets\kong_audio\qin_rv_v2_2\library\ChineeGuZheng_II
```

问题：

1. `chineseGuZheng` 是逻辑名，不是本地真实目录名。
2. 需要确认最终用 `ChineeGuZheng_Classic` 还是 `ChineeGuZheng_II`。
3. 从文件名看，`ChineeGuZheng_Classic` 中有 `GuZheng_Shake_2.KAS`，更接近文档中的 `03 Sus_Shake_2`。
4. 当前服务尚未建立 GuZheng 状态文件。

### 5.5 其他文档一致性问题

1. 正文说 Bank 128 有 10 个鼓组 preset，但表格实际只有 9 行。
2. MIDI 65，中音萨克斯，文档中 MIDI id 是 `65`，云端 Program 是 `65`，但 Web Program 写成 `63`。需要确认 Web Program 是否应改为 `65`。

## 6. 当前技术缺口

当前服务模式：

```text
一次请求选择一个 plugin_id 或 style_id，然后用这个插件或风格渲染整首 MIDI。
```

最终文档目标要求：

```text
按 MIDI Bank、Program、Channel 自动路由到不同云端音源插件，再把多个渲染结果混音为一个 MP3。
```

因此后续主要工作不是继续找资产，而是实现：

1. 结构化音源映射配置。
2. MIDI 解析和轨道/通道/Program 识别。
3. 按映射选择插件和预设。
4. 对不同插件分轨渲染。
5. 多轨 WAV 混音。
6. 最终 MP3 输出。
7. 保持当前 Kong GaoHu 4 风格方案不受影响。

## 7. 下一步任务计划

建议下一步按以下顺序推进。

### 7.1 等待用户确认文档问题

需要确认第 5 节中的问题，尤其是：

1. `Tensor Trombone` 是否修正为 `Tenor Trombone`。
2. `Sonatina Bassoom` 是否修正为 `Sonatina Bassoon`。
3. `default group` 是否修正为 `Default Group`。
4. `Tuba  / Sustain` 是否修正为 `Tuba Sustain`。
5. `Solo  / Horn` 是否修正为 `Solo Horn`。
6. `Solo / Clarinet` 是否修正为 `Solo Clarinet`。
7. `Soprano /  Sax` 是否修正为 `Soprano Sax`。
8. `chineseGuZheng` 最终使用 `ChineeGuZheng_Classic` 还是 `ChineeGuZheng_II`。
9. Bank 128 鼓组到底是 9 个还是 10 个。
10. MIDI 65 中音萨克斯的 Web Program 是否应为 `65`。

### 7.2 建立结构化映射配置

建议新增配置，例如：

```text
config/instrument_mapping.deploy.json
```

内容从 Word 文档表格转换而来，并把第 5 节问题做成明确兼容映射。

### 7.3 先接入并验证非 Kong 的 VST2 插件

优先顺序：

1. `Keyzone Classic`
2. `DSK Saxophones`
3. `Sonatina Orchestra`

原因：这些插件的 preset 文件和采样文件结构清晰，适合先验证 Carla/Wine 无界面加载。

每接入一个插件后都要做：

1. 单音 MIDI 渲染测试。
2. FastAPI zip 调用测试。
3. 输出 MP3/WAV 文件名检查。
4. Kong GaoHu 4 个 zip 回归测试，确认原方案不受影响。

### 7.4 再接入 Kong 的扬琴和筝

原因：Kong 当前已经验证的是 GaoHu，扬琴和筝需要新建 Carla 状态文件，风险高于普通 preset 文件映射。

需要做：

1. 建立 `ChineeYangQin` 状态。
2. 建立 `ChineeGuZheng_Classic` 或 `ChineeGuZheng_II` 状态。
3. 确认文档中的 `02 Sus_mp`、`03 Sus_Shake_2` 在插件状态中正确选中。
4. 单独做 MIDI 渲染和 API 测试。
5. 再次回归 Kong GaoHu 4 风格。

### 7.5 实现多插件路由和混音

初步实现策略：

1. 解析 MIDI 的每个 channel 和 program change。
2. 根据 `instrument_mapping.deploy.json` 决定目标音源。
3. 将 MIDI 按目标音源拆分成多个临时 MIDI。
4. 分别调用现有渲染管线生成 WAV。
5. 使用 ffmpeg 或 Python 音频处理把 WAV 混音。
6. 统一导出最终 MP3。
7. API 返回仍保持 `mp3_file.base64`。

## 8. 重启后恢复工作入口

如果重启电脑或上下文丢失，按下面顺序恢复：

1. 打开工程：

```powershell
cd C:\work\workspace_own\workspace_carla\Carla-2.5.10
git status -sb
git log --oneline -5
```

2. 阅读本交接文档：

```text
docs\CLOUD_DAW_ENGINE_HANDOFF_CN.md
```

3. 阅读最终需求文档：

```text
C:\work\workspace_own\workspace_carla\doc\云端DAW音频工作站引擎.docx
```

4. 确认当前部署镜像：

```powershell
docker images mgsc_daw_service
```

5. 确认资产目录：

```powershell
Get-ChildItem C:\work\workspace_own\workspace_carla\mgsc_daw_assets
```

6. 如果继续开发插件映射，先不要修改当前 Kong GaoHu 4 风格的配置和状态文件。新增能力应通过新配置、新 style、新测试逐步接入。

## 9. 当前保护原则

1. 不影响当前已经跑通的 Kong Audio GaoHu 4 风格。
2. 不破坏 `mgsc_daw_service:v6.4.33` 作为当前可部署版本。
3. 每次新增插件或路由能力，都必须先做单插件测试，再做 Kong 回归。
4. 文档中的逻辑音源名和本地真实目录名要分开记录，不能直接把 `？` 或逻辑名写进运行时路径。
5. 最终以 `云端DAW音频工作站引擎.docx` 为需求依据，但实现配置应使用经过确认和兼容后的结构化数据。
