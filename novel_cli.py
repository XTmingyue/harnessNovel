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
      template = """# 参考小说故事情节单元提取（init 流程，建议 flash 模型）
  DATA_BUILDER_MODEL=deepseek-chat
  DATA_BUILDER_BASE_URL=https://api.deepseek.com
  DATA_BUILDER_API_KEY=your-api-key

  # 仿写核心任务：玩法、舞台、情节单元、章纲、正文、去AI味精修（建议 pro 模型）
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

    # Step 1: 提取大纲（切分章节、故事情节单元、卷纲）
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


def _resolve_volume_arg(args):
    """解析新流程卷号。--stage 仅保留为旧命令兼容别名。"""
    volume = getattr(args, "volume", None)
    stage = getattr(args, "stage", None)
    if volume is not None and stage is not None and volume != stage:
        print("错误：当前流程中“舞台”等同于卷号，不支持同时指定不同的 --volume 和 --stage。")
        print("请使用 --volume N；--stage 仅为兼容旧命令保留。")
        return None
    return volume if volume is not None else (stage if stage is not None else 1)


# ── 仿写流程 ──────────────────────────────────────────────

def cmd_novel_outline(args):
    from training.adaptive_builder import gen_novel_outline
    ws = _ws(args.workspace)
    gen_novel_outline(ws, force=args.force, creative_direction=args.direction,
                      direction_file=args.direction_file)


def cmd_world_import(args):
    from training.adaptive_builder import import_target_world_sources
    ws = _ws(args.workspace)
    import_target_world_sources(ws, args.paths, force=args.force)


def cmd_world_build(args):
    from training.adaptive_builder import build_target_world_knowledge
    ws = _ws(args.workspace)
    build_target_world_knowledge(
        ws,
        force=args.force,
        chunk_size=args.chunk_size,
        chapter_batch_size=args.chapter_batch_size,
        max_workers=args.max_workers,
        primary_source=args.primary,
        merge_only=args.merge_only,
    )


def cmd_novel_name_synopsis(args):
    from training.adaptive_builder import gen_novel_name_synopsis
    ws = _ws(args.workspace)
    gen_novel_name_synopsis(ws, force=args.force)


def cmd_story_design(args):
    from training.adaptive_builder import gen_story_design
    ws = _ws(args.workspace)
    gen_story_design(ws, force=args.force, creative_direction=args.direction,
                     direction_file=args.direction_file)


def cmd_stage_insert(args):
    from training.adaptive_builder import insert_stage
    ws = _ws(args.workspace)
    if args.after_stage is not None and args.before_stage is not None:
        print("错误：--after-stage 和 --before-stage 不能同时使用。")
        return
    insert_stage(
        ws,
        creative_direction=args.direction,
        direction_file=args.direction_file,
        after_stage=args.after_stage,
        before_stage=args.before_stage,
    )


def cmd_mechanics_init(args):
    from training.adaptive_builder import init_mechanics
    ws = _ws(args.workspace)
    init_mechanics(
        ws,
        force=args.force,
        creative_direction=args.direction,
        direction_file=args.direction_file,
        mechanics_file=args.file,
        disable=args.none,
    )


def cmd_volume_outline(args):
    from training.adaptive_builder import gen_volume_outline
    ws = _ws(args.workspace)
    gen_volume_outline(ws, volume=args.volume, force=args.force,
                       creative_direction=args.direction)


def cmd_story_arcs(args):
    from training.adaptive_builder import gen_story_arcs
    volume = _resolve_volume_arg(args)
    if volume is None:
        return
    ws = _ws(args.workspace)
    gen_story_arcs(ws, volume=volume, force=args.force)


def cmd_chapter_outlines(args):
    from training.adaptive_builder import gen_serial_chapter_outlines
    volume = _resolve_volume_arg(args)
    if volume is None:
        return
    ws = _ws(args.workspace)
    gen_serial_chapter_outlines(ws, volume=volume, force=args.force)


def cmd_write(args):
    from training.adaptive_builder import gen_serial_chapters
    volume = _resolve_volume_arg(args)
    if volume is None:
        return
    ws = _ws(args.workspace)
    gen_serial_chapters(ws, volume=volume, start_chapter=args.start,
                        max_chapters=args.max,
                        humanize=not args.no_humanize,
                        humanize_existing=args.humanize_existing)


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
    p.add_argument("--batch-size", type=int, default=20, help="每次读取章节数，用于识别故事情节单元（默认20）")

    # novel-outline
    p = sub.add_parser("novel-outline", help="生成核心玩法、长线主线、舞台路线图和角色线")
    p.add_argument("workspace", help="工作区名称")
    p.add_argument("--force", action="store_true")
    p.add_argument("--direction", help="创作方向（字符串）")
    p.add_argument("--direction-file", help="创作方向文件路径")

    # world-import
    p = sub.add_parser("world-import", help="导入目标题材资料")
    p.add_argument("workspace", help="工作区名称")
    p.add_argument("paths", nargs="+", help="资料文件或目录路径，可传多个")
    p.add_argument("--force", action="store_true", help="覆盖已导入的同源文件")

    # world-build
    p = sub.add_parser("world-build", help="结构化梳理目标题材资料")
    p.add_argument("workspace", help="工作区名称")
    p.add_argument("--force", action="store_true", help="强制重新结构化和汇总")
    p.add_argument("--chunk-size", type=int, default=12000, help="资料分片字符数（默认12000）")
    p.add_argument("--chapter-batch-size", type=int, default=20, help="章节资料每批章节数（默认20）")
    p.add_argument("--max-workers", type=int, default=None, help="兼容参数：旧版分栏并行数，当前全栏目汇总模式通常无需设置")
    p.add_argument("--primary", default=None, help="指定主资料，可填文件名、路径或资料ID；不指定时默认最大文件")
    p.add_argument("--merge-only", action="store_true", help="只基于已有 worlds/<资料名>/*.md 重建 worlds/_final 和审计，跳过 cards/canon/source worlds")

    # novel-name-synopsis
    p = sub.add_parser("novel-name-synopsis", help="推荐书名与简介")
    p.add_argument("workspace", help="工作区名称")
    p.add_argument("--force", action="store_true")

    # story-design
    p = sub.add_parser("story-design", help="生成核心玩法、长线主线、舞台路线图和角色成长线")
    p.add_argument("workspace", help="工作区名称")
    p.add_argument("--force", action="store_true")
    p.add_argument("--direction", help="创作方向（字符串）")
    p.add_argument("--direction-file", help="创作方向文件路径")

    # stage-insert
    p = sub.add_parser("stage-insert", help="基于灵感设计新舞台并插入舞台路线图")
    p.add_argument("workspace", help="工作区名称")
    p.add_argument("--direction", help="新舞台灵感（字符串）")
    p.add_argument("--direction-file", help="新舞台灵感文件路径")
    p.add_argument("--after-stage", type=int, default=None, help="优先插入在指定舞台之后")
    p.add_argument("--before-stage", type=int, default=None, help="优先插入在指定舞台之前")

    # mechanics-init
    p = sub.add_parser("mechanics-init", help="初始化可选机制层（系统/面板/数值/轻量状态追踪）")
    p.add_argument("workspace", help="工作区名称")
    p.add_argument("--force", action="store_true", help="覆盖已有机制层")
    p.add_argument("--direction", help="机制设定方向（字符串）")
    p.add_argument("--direction-file", help="机制设定方向文件路径")
    p.add_argument("--file", help="机制设定文件路径，优先级高于 --direction")
    p.add_argument("--none", action="store_true", help="显式关闭机制层")

    # volume-outline
    p = sub.add_parser("volume-outline", help="仿写生成卷纲")
    p.add_argument("workspace", help="工作区名称")
    p.add_argument("--volume", type=int, default=None, help="指定卷号")
    p.add_argument("--force", action="store_true")
    p.add_argument("--direction", help="创作方向")

    # story-arcs
    p = sub.add_parser("story-arcs", help="生成故事情节单元")
    p.add_argument("workspace", help="工作区名称")
    p.add_argument("--volume", type=int, default=None, help="卷号（默认1；新流程中一卷对应一个舞台）")
    p.add_argument("--stage", type=int, default=None, help="兼容旧别名：等同于 --volume，不表示卷内 stage")
    p.add_argument("--force", action="store_true", help="强制重新生成")

    # chapter-outlines
    p = sub.add_parser("chapter-outlines", help="基于故事情节单元串行逐章生成章纲")
    p.add_argument("workspace", help="工作区名称")
    p.add_argument("--volume", type=int, default=None, help="卷号（默认1；新流程中一卷对应一个舞台）")
    p.add_argument("--stage", type=int, default=None, help="兼容旧别名：等同于 --volume，不表示卷内 stage")
    p.add_argument("--force", action="store_true", help="强制重新生成")

    # write
    p = sub.add_parser("write", help="串行生成正文")
    p.add_argument("workspace", help="工作区名称")
    p.add_argument("--volume", type=int, default=None, help="卷号（默认1；新流程中一卷对应一个舞台）")
    p.add_argument("--stage", type=int, default=None, help="兼容旧别名：等同于 --volume，不表示卷内 stage")
    p.add_argument("--start", type=int, default=1, help="起始章节号")
    p.add_argument("--max", type=int, default=None, help="最大章节数")
    p.add_argument("--no-humanize", action="store_true", help="关闭正文生成后的自动去AI味后处理")
    p.add_argument("--humanize-existing", action="store_true", help="对已存在的正文执行去AI味；默认只处理本次新生成章节")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    dispatch = {
        "list": cmd_list,
        "init": cmd_init,
        "world-import": cmd_world_import,
        "world-build": cmd_world_build,
        "novel-outline": cmd_novel_outline,
        "novel-name-synopsis": cmd_novel_name_synopsis,
        "story-design": cmd_story_design,
        "stage-insert": cmd_stage_insert,
        "mechanics-init": cmd_mechanics_init,
        "volume-outline": cmd_volume_outline,
        "story-arcs": cmd_story_arcs,
        "chapter-outlines": cmd_chapter_outlines,
        "write": cmd_write,
        "config": cmd_config
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
