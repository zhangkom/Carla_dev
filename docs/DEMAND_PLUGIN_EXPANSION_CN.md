# 需求文档候选音源扩展记录

日期：2026-05-07
分支：`feature/demand-plugin-expansion`
基线：`v6.5.7.18001`

## 结论

《云端DAW音频工作站引擎.docx》的最终 137 条 Bank/Program 映射表中，云端目标音源只有：

```text
Musyng_Kite
Kong
Keyzone Classic
Sonatina Orchestra
DSK Saxophones
```

因此 `v6.5.7.18001` 基线已经覆盖最终映射表。资产目录中存在的其他插件不等于已经被最终需求表指定为目标音源。

## 2026-05-08 联调 DLL 修补状态

新镜像 `mgsc_daw_service:6.5.8.1155` 已补齐当前 `plugins.deploy.json` 中候选 VST style 需要的 DLL/资产层，用于需求方联调时验证多 VST、多 SF2、LMMS 四文件输入和显式 `style_id` 路由。

本次补齐的候选插件：

| 候选插件 | 镜像/补丁状态 | 正式 137 条映射状态 | 备注 |
| --- | --- | --- | --- |
| Vital | 已补齐并验证有声 | 未进入 137 条 auto 映射 | `lmms_vst_trackname_multi.zip` 已通过 |
| DSK Asian DreamZ | 已补齐 DLL 和 preset state | 未进入 137 条 auto 映射 | 可用显式 style 验证 |
| DSK ElectriK GuitarZ | 已补齐 DLL | 未进入 137 条 auto 映射 | 可用显式 style 验证 |
| DRUM PRO | 已补齐 DLL 和 preset state | 未进入 137 条 auto 映射 | 可用显式 style 验证 |
| MT-PowerDrumKit | 已补齐 DLL | 未进入 137 条 auto 映射 | 可用显式 style 验证 |
| Tunefish4 | 已补齐 DLL 和 preset state | 未进入 137 条 auto 映射 | 可用显式 style 验证 |
| ABPL2 | 已补齐 DLL | 未进入 137 条 auto 映射 | 可用显式 style 验证 |
| AGML2 | 已补齐 DLL | 未进入 137 条 auto 映射 | 可用显式 style 验证 |
| Sylenth1 | 已补齐 DLL | 未进入 137 条 auto 映射 | 可用显式 style 验证 |
| EZkeys | 仅补齐最小 DLL 层 | 未进入 137 条 auto 映射 | 完整 `EZkeys Library` 约 24.5GB，默认联调包未包含 |

重要边界：

1. `instrument_mapping.deploy.json` 的正式 137 条 Bank/Program 自动映射未改动，仍以 Musyng Kite、Kong、Keyzone Classic、Sonatina Orchestra、DSK Saxophones 为主。
2. 上表候选插件已经可以通过 `vst.json` / `sf2.json` 显式 `style_id` 或旧 LMMS 字段迁移路径进入 Carla 渲染，但不代表需求文档最终映射表已改成这些插件。
3. 若需求方要求 EZkeys 作为正式云端目标音源，需要单独确认授权、上传完整大库，并新增明确的 Bank/Program 或 `style_id` 映射。

## 候选音源状态

| 候选音源 | 需求文档位置 | 本地资产状态 | 当前处理 |
| --- | --- | --- | --- |
| GeneralUser GS | 云端音源选型 | 未在 `mgsc_daw_assets` 中发现可部署文件 | 暂不接入，等待资产 |
| FluidR3 GM | 云端音源选型 | 存在 `mgsc_daw_assets/soundfont2/FluidR3_GM/FluidR3_GM.sf2` | 已新增显式 style `sf2_fluidr3_gm`，暂不参与 137 条 auto 映射 |
| Musyng Kite | 云端音源选型和最终映射表 | 存在并已进入镜像 | 已正式接入，111 条映射使用 |
| FluidSynth VST3 | 云端音源选型 | 未发现独立 VST3 插件资产；当前 Carla 可直接加载 SF2 | 暂不新增 VST3 插件，继续使用 Carla/SF2 路径 |
| Smidy VST3 | 云端音源选型 | 未在 `mgsc_daw_assets` 中发现可部署文件 | 暂不接入，等待资产 |
| Roland Sound Canvas VA | 云端音源选型 | 未在 `mgsc_daw_assets` 中发现可部署文件，且涉及商业授权 | 暂不接入，等待授权和资产 |
| A320U.sf2 | Web 端轻量化渲染参考 | 存在 `mgsc_daw_assets/soundfont2/A320U.sf2` | 文档定位为 Web 端参考音源，不作为当前云端目标 |
| A320U_drums.sf2 | Web 端轻量化渲染参考 | 存在 `mgsc_daw_assets/soundfont2/A320U_drums.sf2` | 文档定位为 Web 端参考音源，不作为当前云端目标 |

## 本分支改动

新增部署配置：

```text
plugin_id: sf2_fluidr3_gm
style_id:  sf2_fluidr3_gm
path:      /home/workspace/assets/soundfont2/FluidR3_GM/FluidR3_GM.sf2
```

注意：当前 `mgsc_daw_service:6.5.7.18001` 镜像内尚未包含 `FluidR3_GM.sf2`，后续如果要验证该 style，需要把本地资产复制进镜像或在构建流程中加入该资产。

## 后续建议

1. 先完成 `v6.5.7.18001` 在 Ubuntu 上对 37 个完整时长测试包的验证。
2. 和需求方确认是否要求 FluidR3 GM 替代 Musyng Kite 的某些 Program，还是只作为备用显式 style。
3. 如果需求方要求 GeneralUser GS、Smidy VST3 或 Roland Sound Canvas VA，先提供可部署资产和授权说明，再进入配置接入和 Ubuntu 有声验证。
