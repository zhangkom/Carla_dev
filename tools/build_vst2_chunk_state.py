# /**
# * File name: build_vst2_chunk_state.py
# * Brief: VST2 预设状态文件生成工具
# * Function:
# *     将插件导出的 base64 chunk 预设封装为 Carla 可加载的 .carxs 状态文件
# * Author: 软件工程架构组
# *     MGSC AI Software Architecture group
# * Version: V2.5.10
# * Date: 2026/04/30
# */
import argparse
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="把 VST2 插件的 base64 chunk 预设封装成 Carla .carxs 状态文件。"
    )
    parser.add_argument("--preset-txt", required=True, help="插件预设 txt 文件路径")
    parser.add_argument("--output", required=True, help="输出 .carxs 状态文件路径")
    parser.add_argument("--plugin-name", required=True, help="Carla 状态中的插件名称")
    parser.add_argument(
        "--binary",
        required=True,
        help="Carla 状态中的插件运行时路径，建议使用容器内最终路径",
    )
    parser.add_argument("--unique-id", type=int, default=0, help="插件 UniqueID，默认 0")
    parser.add_argument("--volume", default="1.0", help="状态文件中的音量，默认 1.0")
    parser.add_argument(
        "--control-channel",
        default="-1",
        help="Carla ControlChannel，默认 -1 表示不限制通道",
    )
    parser.add_argument("--options", default="0x3fb", help="Carla Options 字段")
    parser.add_argument("--force", action="store_true", help="允许覆盖已存在输出文件")
    return parser


def read_chunk(path):
    text = Path(path).read_text(encoding="utf-8", errors="ignore").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    chunk = "".join(lines)
    if not chunk:
        raise ValueError("preset chunk is empty: {0}".format(path))
    if not re.fullmatch(r"[A-Za-z0-9+/=]+", chunk):
        raise ValueError("preset chunk is not plain base64 text: {0}".format(path))
    return chunk


def build_state_xml(args, chunk):
    return """<?xml version='1.0' encoding='UTF-8'?>
<!DOCTYPE CARLA-PRESET>
<CARLA-PRESET VERSION='2.0'>
  <Info>
   <Type>VST2</Type>
   <Name>{plugin_name}</Name>
   <Binary>{binary}</Binary>
   <UniqueID>{unique_id}</UniqueID>
  </Info>

  <Data>
   <Active>Yes</Active>
   <Volume>{volume}</Volume>
   <ControlChannel>{control_channel}</ControlChannel>
   <Options>{options}</Options>

   <Chunk>
{chunk}
   </Chunk>
  </Data>
</CARLA-PRESET>
""".format(
        plugin_name=escape(args.plugin_name),
        binary=escape(args.binary),
        unique_id=args.unique_id,
        volume=escape(str(args.volume)),
        control_channel=escape(str(args.control_channel)),
        options=escape(str(args.options)),
        chunk=chunk,
    )


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    preset_path = Path(args.preset_txt)
    if not preset_path.is_file():
        print("ERROR: preset txt not found: {0}".format(preset_path), file=sys.stderr)
        return 1

    output_path = Path(args.output)
    if output_path.exists() and not args.force:
        print("ERROR: output already exists, use --force: {0}".format(output_path), file=sys.stderr)
        return 1

    try:
        chunk = read_chunk(preset_path)
        xml = build_state_xml(args, chunk)
    except Exception as exc:
        print("ERROR: {0}".format(exc), file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(xml, encoding="utf-8")
    print("wrote: {0}".format(output_path))
    print("chunk_bytes: {0}".format(len(chunk)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
