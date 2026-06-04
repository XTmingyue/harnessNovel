#!/usr/bin/env python3
"""harness-novel 统一 CLI 入口"""

import sys
import os
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

def cmd_config(args):
      """初始化全局配置文件 ~/.harnessNovel/.env"""
      import os
      config_dir = os.path.join(os.path.expanduser("~"), ".harnessNovel")
      env_path = os.path.join(config_dir, ".env")
      if os.path.exists(env_path) and not args.force:
          print(f"配置文件已存在：{env_path}")
          print("使用 --force 覆盖")
          return
      os.makedirs(config_dir, exist_ok=True)
      template = """# 参考小说批次摘要提取（init 流程，建议 flash 模型）
  DATA_BUILDER_MODEL=deepseek-chat
  DATA_BUILDER_BASE_URL=https://api.deepseek.com
  DATA_BUILDER_API_KEY=your-api-key

  # 仿写核心任务：大纲、卷纲、章纲、正文（建议 pro 模型）
  ADAPTIVE_BUILDER_MODEL=deepseek-chat
  ADAPTIVE_BUILDER_BASE_URL=https://api.deepseek.com
  ADAPTIVE_BUILDER_API_KEY=your-api-key

  # 仿写辅助任务：世界观提取（建议 flash 模型）
  ADAPTIVE_BUILDER_LITE_MODEL=deepseek-chat
  ADAPTIVE_BUILDER_LITE_BASE_URL=https://api.deepseek.com
  ADAPTIVE_BUILDER_LITE_API_KEY=your-api-key
  """
      with open(env_path, "w", encoding="utf-8") as f:
          f.write(template)
      print(f"配置文件已创建：{env_path}")
      print("请编辑该文件，填入你的 API Key")

def cmd_list(args):
    from core.workspace import list_novels
    novels = list_novels()
    if novels:
        print("已有工作区：")
        for name in novels:
            print(f"  - {name}")
    else:
        print("暂无工作区。")


def cmd_init(args):
    """创建工作空间。novel init <name> --txt <path>"""
    import shutil
    import re
    from core.workspace import init_workspace

    ws = init_workspace(args.workspace)

    txt_path = args.txt

    if not txt_path:
        print(f"工作空间「{args.workspace}」已创建：{ws.root}")
        print("提示：使用 --txt 添加参考小说文件，例如：novel init <name> --txt 小说.txt")
        return

    if not os.path.exists(txt_path):
        print(f"错误：文件不存在：{txt_path}")
        return

    dest = ws.reference_sample
    shutil.copy2(txt_path, dest)
    name = os.path.splitext(os.path.basename(txt_path))[0]
    print(f"工作空间「{args.workspace}」已创建")
    print(f"  参考小说：{name}")
    print(f"  文件位置：{dest}")

    # Step 0: 拆分参考小说章节到独立文件
    print()
    from training.outline_builder import split_chapters_to_files
    split_chapters_to_files(ws)

    # Step 1: 提取大纲（切分章节、批次摘要、卷纲）
    print()
    from training.outline_builder import run_outline_build
    run_outline_build(txt_path=dest, output_dir=ws.reference,
                      batch_size=args.batch_size)

    # Step 2: 判断是否需要智能分卷
    outlines_dir = os.path.join(ws.reference, "outlines")
    if os.path.isdir(outlines_dir):
        vol_dirs = []
        for fname in sorted(os.listdir(outlines_dir)):
            if re.match(r'^vol_\d+_.+$', fname) and os.path.isdir(os.path.join(outlines_dir, fname)):
                vol_dirs.append(fname)

        if len(vol_dirs) <= 1:
            print("\n检测到仅有一个分卷，执行智能分卷...")
            from training.outline_builder import resegment
            resegment(outlines_dir)
        else:
            print(f"\n检测到 {len(vol_dirs)} 个分卷，跳过智能分卷。")

    # Step 3: 提取世界观
    print()
    from training.adaptive_builder import gen_worldview
    gen_worldview(ws)

    print(f"\n工作空间目录：{ws.root}")


def _ws(name):
    from core.workspace import init_workspace
    return init_workspace(name)


# ── 仿写流程 ──────────────────────────────────────────────

def cmd_novel_outline(args):
    from training.adaptive_builder import gen_novel_outline
    ws = _ws(args.workspace)
    gen_novel_outline(ws, force=args.force, creative_direction=args.direction,
                      direction_file=args.direction_file)


def cmd_novel_name_synopsis(args):
    from training.adaptive_builder import gen_novel_name_synopsis
    ws = _ws(args.workspace)
    gen_novel_name_synopsis(ws, force=args.force)


def cmd_volume_outline(args):
    from training.adaptive_builder import gen_volume_outline
    ws = _ws(args.workspace)
    gen_volume_outline(ws, volume=args.volume, force=args.force,
                       creative_direction=args.direction)


def cmd_chapter_outlines(args):
    from training.adaptive_builder import gen_serial_chapter_outlines
    ws = _ws(args.workspace)
    gen_serial_chapter_outlines(ws, volume=args.volume, force=args.force)


def cmd_write(args):
    from training.adaptive_builder import gen_serial_chapters
    ws = _ws(args.workspace)
    gen_serial_chapters(ws, volume=args.volume, start_chapter=args.start,
                        max_chapters=args.max)


# ── 主入口 ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="novel",
        description="harness-novel 统一 CLI",
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    # config
    p = sub.add_parser("config", help="初始化全局配置文件")
    p.add_argument("--force", action="store_true", help="覆盖已有配置")

    # list
    sub.add_parser("list", help="列出所有工作区")

    # init
    p = sub.add_parser("init", help="创建工作空间")
    p.add_argument("workspace", help="工作区名称")
    p.add_argument("--txt", help="参考小说文件路径")
    p.add_argument("--batch-size", type=int, default=20, help="每批处理章节数（默认20）")

    # novel-outline
    p = sub.add_parser("novel-outline", help="仿写生成新小说大纲")
    p.add_argument("workspace", help="工作区名称")
    p.add_argument("--force", action="store_true")
    p.add_argument("--direction", help="创作方向（字符串）")
    p.add_argument("--direction-file", help="创作方向文件路径")

    # novel-name-synopsis
    p = sub.add_parser("novel-name-synopsis", help="推荐书名与简介")
    p.add_argument("workspace", help="工作区名称")
    p.add_argument("--force", action="store_true")

    # volume-outline
    p = sub.add_parser("volume-outline", help="仿写生成卷纲")
    p.add_argument("workspace", help="工作区名称")
    p.add_argument("--volume", type=int, default=None, help="指定卷号")
    p.add_argument("--force", action="store_true")
    p.add_argument("--direction", help="创作方向")

    # chapter-outlines
    p = sub.add_parser("chapter-outlines", help="串行逐章生成章纲")
    p.add_argument("workspace", help="工作区名称")
    p.add_argument("--volume", type=int, default=1, help="卷号（默认1）")
    p.add_argument("--force", action="store_true", help="强制重新生成")

    # write
    p = sub.add_parser("write", help="串行生成正文")
    p.add_argument("workspace", help="工作区名称")
    p.add_argument("--volume", type=int, default=1, help="卷号（默认1）")
    p.add_argument("--start", type=int, default=1, help="起始章节号")
    p.add_argument("--max", type=int, default=None, help="最大章节数")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    dispatch = {
        "list": cmd_list,
        "init": cmd_init,
        "novel-outline": cmd_novel_outline,
        "novel-name-synopsis": cmd_novel_name_synopsis,
        "volume-outline": cmd_volume_outline,
        "chapter-outlines": cmd_chapter_outlines,
        "write": cmd_write,
        "config": cmd_config
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
