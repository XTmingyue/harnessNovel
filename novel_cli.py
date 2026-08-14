#!/usr/bin/env python3
"""harness-novel 统一 CLI 入口"""

import sys
import os
import argparse
import re

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
  DATA_BUILDER_MODEL=deepseek-v4-flash
  DATA_BUILDER_BASE_URL=https://api.deepseek.com
  DATA_BUILDER_API_KEY=your-api-key

  # 全书设计与舞台设计（建议 pro 模型）
  ADAPTIVE_BUILDER_MODEL=deepseek-v4-pro
  ADAPTIVE_BUILDER_BASE_URL=https://api.deepseek.com
  ADAPTIVE_BUILDER_API_KEY=your-api-key

  # 故事情节、逐章章纲、正文及轻量辅助任务（建议 flash 模型）
  ADAPTIVE_BUILDER_LITE_MODEL=deepseek-v4-flash
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


def _reference_state_path(ws):
    return os.path.join(ws.reference, "import_state.json")


def _uploaded_source_name(path):
    """移除 Web 临时上传文件的随机前缀，保留用户看到的原始文件名。"""
    return re.sub(r"^[0-9a-f]{16}_", "", os.path.basename(path), flags=re.IGNORECASE)


def _load_reference_state(ws):
    import json

    path = _reference_state_path(ws)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_reference_state(ws, state):
    import json

    with open(_reference_state_path(ws), "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _saved_reference_story_arc_end(ws):
    """返回已落盘故事片段覆盖的总章数，用于可恢复的参考拆解。"""
    import json
    import re

    outlines_dir = os.path.join(ws.reference, "outlines")
    if not os.path.isdir(outlines_dir):
        return 0

    pattern = re.compile(r"^arc_\d+_ch\d+_(\d+)\.md$", re.IGNORECASE)
    local_coverage = 0
    global_endpoints = []
    for dirname in sorted(os.listdir(outlines_dir)):
        vol_dir = os.path.join(outlines_dir, dirname)
        arc_dir = os.path.join(vol_dir, "story_arcs")
        if not os.path.isdir(arc_dir):
            continue
        volume_end = 0
        for filename in os.listdir(arc_dir):
            matched = pattern.match(filename)
            if matched:
                volume_end = max(volume_end, int(matched.group(1)))
        if not volume_end:
            continue
        local_coverage += volume_end
        meta_path = os.path.join(vol_dir, "meta.json")
        try:
            with open(meta_path, "r", encoding="utf-8") as handle:
                meta_end = int(json.load(handle).get("end_ch") or 0)
        except (OSError, ValueError, json.JSONDecodeError):
            meta_end = 0
        if meta_end:
            global_endpoints.append(meta_end)
    return max(global_endpoints) if global_endpoints else local_coverage


def _reference_card_complete_count(ws):
    """读取 analysis_state 中已完成的单章事实卡数量，作为真实拆解进度的可靠下界。

    单章事实卡是拆解的事实底座：没有卡的章节不可能已被拆解。比 story-arc 的分卷 meta.json
    更可靠——后者在换源/部分拆解后可能残留旧值。
    """
    import json

    path = os.path.join(ws.reference, "analysis_state.json")
    if not os.path.isfile(path):
        return 0
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return 0
    cards = data.get("chapter_cards") if isinstance(data, dict) else None
    if not isinstance(cards, dict):
        return 0
    try:
        return int(cards.get("complete_count") or 0)
    except (TypeError, ValueError):
        return 0


def _canonical_chapter_digest(chapter):
    """生成与拆解器一致的章节指纹，用于识别新版整本快照的公共前缀。"""
    import hashlib
    import re
    from core.text_utils import normalize_text

    content = normalize_text(str(chapter.get("content") or ""))
    canonical = re.sub(r"\s+", "", content)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _replace_reference_with_latest_snapshot(ws, incoming_path):
    """用作者最新整本快照替换源文件，并复用公共前缀的事实卡。"""
    import hashlib
    import json
    import tempfile
    from core.text_encoding import decode_text_bytes
    from training.outline_builder import split_chapters

    with open(incoming_path, "rb") as handle:
        new_text, source_encoding = decode_text_bytes(handle.read())
    _, old_chapters = split_chapters(ws.reference_sample)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as handle:
        handle.write(new_text)
        temporary_path = handle.name
    try:
        _, new_chapters = split_chapters(temporary_path)
    finally:
        os.unlink(temporary_path)
    if not new_chapters:
        raise ValueError("上传文件中未识别到有效章节。")

    reusable_limit = min(_reference_card_complete_count(ws), len(old_chapters))
    common_prefix = 0
    for old_chapter, new_chapter in zip(old_chapters, new_chapters):
        if _canonical_chapter_digest(old_chapter) != _canonical_chapter_digest(new_chapter):
            break
        common_prefix += 1
    if common_prefix < reusable_limit:
        raise ValueError(
            f"新版小说从第 {common_prefix + 1} 章开始与已拆解内容不一致，"
            f"无法安全复用前 {reusable_limit} 章。若作者修改了旧章节，请使用重新拆解。"
        )
    if len(new_chapters) < reusable_limit:
        raise ValueError(
            f"新版小说仅识别到 {len(new_chapters)} 章，少于已拆解的 {reusable_limit} 章。"
        )

    with open(ws.reference_sample, "w", encoding="utf-8") as handle:
        handle.write(new_text)
    source_digest = hashlib.sha256(new_text.encode("utf-8")).hexdigest()

    cards_dir = os.path.join(ws.reference, "chapter_cards")
    for number in range(1, reusable_limit + 1):
        path = os.path.join(cards_dir, f"chapter_{number:04d}.json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                card = json.load(handle)
            card["source_digest"] = source_digest
            card["content_digest"] = _canonical_chapter_digest(new_chapters[number - 1])
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(card, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        except (OSError, ValueError):
            continue

    analysis_path = os.path.join(ws.reference, "analysis_state.json")
    if os.path.isfile(analysis_path):
        try:
            with open(analysis_path, "r", encoding="utf-8") as handle:
                analysis = json.load(handle)
            analysis["source_digest"] = source_digest
            analysis["total_chapters"] = len(new_chapters)
            analysis["latest_snapshot"] = {
                "common_prefix_chapters": common_prefix,
                "reused_chapter_cards": reusable_limit,
                "new_chapters": max(0, len(new_chapters) - reusable_limit),
                "updated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            }
            with open(analysis_path, "w", encoding="utf-8") as handle:
                json.dump(analysis, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        except (OSError, ValueError):
            pass

    return {
        "encoding": source_encoding,
        "old_chapters": len(old_chapters),
        "total_chapters": len(new_chapters),
        "common_prefix": common_prefix,
        "reused_cards": reusable_limit,
        "new_chapters": max(0, len(new_chapters) - reusable_limit),
    }


def _run_reference_pipeline(ws, batch_size, max_chapters=None, resume=False, source_name=None, source_encoding=None,
                            rebuild_reference=False):
    """执行参考小说拆解；续拆时只处理已有片段覆盖范围之后的章节。"""
    import re
    from datetime import datetime
    from training.outline_builder import run_outline_build, split_chapters, split_chapters_to_files

    _, all_chapters = split_chapters(ws.reference_sample)
    total_chapters = len(all_chapters)
    if not total_chapters:
        print("错误：未识别到有效章节，无法拆解。请检查小说章节标题格式。")
        return False

    target_chapters = min(max_chapters or total_chapters, total_chapters)
    previous_state = _load_reference_state(ws)
    state_progress = int(previous_state.get("processed_chapters") or 0)
    arc_progress = _saved_reference_story_arc_end(ws)
    # 容错：残留旧分卷 meta.json 的 end_ch 会把 arc_progress 顶高（换源 / 部分拆解后未重算）。
    # 单章事实卡是拆解的真实底座，且已拆解数不可能超过源文件总章节数；据此封顶，避免续拆被误拦、提示失真。
    arc_progress = min(arc_progress, total_chapters, _reference_card_complete_count(ws) or total_chapters)
    previous_chapters = max(state_progress, arc_progress)
    if rebuild_reference:
        print("  已请求重新拆解，将清除已有参考拆解资产。")
        previous_chapters = 0
    if resume and target_chapters < previous_chapters:
        print(f"当前已拆解至第 {previous_chapters} 章；目标章节数不能小于当前进度。")
        return False

    if target_chapters < total_chapters:
        print(f"  拆解范围：前 {target_chapters}/{total_chapters} 章（可稍后继续拆解）")
    else:
        print(f"  拆解范围：整本书（共 {total_chapters} 章）")

    if resume and target_chapters == previous_chapters and not rebuild_reference:
        print(f"  将从第 {previous_chapters} 章的已保存结果重试，补齐未完成的派生步骤。")

    # 先落盘进行中状态。即使模型调用或进程中断，Web 端仍能知道总范围并从已有片段续跑。
    _save_reference_state(ws, {
        "source_name": source_name or previous_state.get("source_name") or os.path.basename(ws.reference_sample),
        "source_encoding": source_encoding or previous_state.get("source_encoding") or "UTF-8",
        "total_chapters": total_chapters,
        "processed_chapters": previous_chapters,
        "is_complete": False,
        "status": "in_progress",
        "batch_size": batch_size,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    })

    print()
    split_chapters_to_files(ws, max_chapters=target_chapters, refresh=resume)

    print()
    analysis_result = run_outline_build(
        txt_path=ws.reference_sample,
        output_dir=ws.reference,
        batch_size=batch_size,
        max_chapters=target_chapters,
        resume=resume,
        rebuild_reference=rebuild_reference,
    )
    if not analysis_result:
        raise RuntimeError("参考小说拆解未生成有效结果。")

    outlines_dir = os.path.join(ws.reference, "outlines")
    is_partial = target_chapters < total_chapters
    if not is_partial and os.path.isdir(outlines_dir):
        vol_dirs = [
            name for name in sorted(os.listdir(outlines_dir))
            if re.match(r"^vol_\d+_.+$", name) and os.path.isdir(os.path.join(outlines_dir, name))
        ]
        if len(vol_dirs) <= 1:
            print("\n检测到仅有一个分卷，执行智能分卷...")
            from training.outline_builder import resegment
            from training.reference_analyzer import mark_resegmented
            resegment(outlines_dir)
            resulting_dirs = [
                name for name in os.listdir(outlines_dir)
                if re.match(r"^vol_\d+_.+$", name) and os.path.isdir(os.path.join(outlines_dir, name))
            ]
            if resulting_dirs and not any("全书" in name for name in resulting_dirs):
                mark_resegmented(ws.reference)
            else:
                print("  智能分卷未完成，保留当前拆解状态以便下次重试。")
        else:
            print(f"\n检测到 {len(vol_dirs)} 个分卷，跳过智能分卷。")
    elif is_partial:
        print("\n当前为部分拆解，保留现有情节单元；完成整本拆解后再执行智能分卷。")

    _save_reference_state(ws, {
        "source_name": source_name or previous_state.get("source_name") or os.path.basename(ws.reference_sample),
        "source_encoding": source_encoding or previous_state.get("source_encoding") or "UTF-8",
        "total_chapters": total_chapters,
        "processed_chapters": target_chapters,
        "is_complete": target_chapters >= total_chapters,
        "status": "complete",
        "batch_size": batch_size,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    })
    print(f"\n工作空间目录：{ws.root}")
    return True


def cmd_init(args):
    """创建工作空间。novel init <name> --txt <path>"""
    from core.workspace import init_workspace
    from core.text_encoding import copy_as_utf8

    ws = init_workspace(args.workspace)

    txt_path = args.txt

    if not txt_path:
        print(f"工作空间「{args.workspace}」已创建：{ws.root}")
        print("提示：使用 --txt 添加参考小说文件，例如：novel init <name> --txt 小说.txt")
        return

    if not os.path.exists(txt_path):
        print(f"错误：文件不存在：{txt_path}")
        return
    if args.max_chapters is not None and args.max_chapters < 1:
        print("错误：--max-chapters 必须是正整数。")
        return

    dest = ws.reference_sample
    try:
        source_encoding = copy_as_utf8(txt_path, dest)
    except ValueError as exc:
        print(f"错误：{exc}")
        return
    name = os.path.splitext(os.path.basename(txt_path))[0]
    print(f"工作空间「{args.workspace}」已创建")
    print(f"  参考小说：{name}")
    print(f"  文件位置：{dest}")
    if source_encoding == "UTF-8":
        print("  文件编码：UTF-8")
    else:
        print(f"  文件编码：检测到 {source_encoding}，已转换为 UTF-8")
    if args.no_analyze:
        print("  参考小说已导入。请在参考小说步骤选择拆解整本书或前 N 章后开始拆解。")
        return
    _run_reference_pipeline(
        ws,
        batch_size=args.batch_size,
        max_chapters=args.max_chapters,
        source_name=_uploaded_source_name(txt_path),
        source_encoding=source_encoding,
        rebuild_reference=args.rebuild_reference,
    )


def cmd_reference_resume(args):
    """继续拆解；上传文件视为作者最新的整本小说快照。"""
    from core.workspace import init_workspace

    ws = init_workspace(args.workspace)
    if not os.path.isfile(ws.reference_sample):
        print("错误：当前工作区尚未导入参考小说。请先执行 novel init <工作区> --txt <小说.txt>。")
        return
    if args.max_chapters is not None and args.max_chapters < 1:
        print("错误：--max-chapters 必须是正整数。")
        return
    snapshot_source_name = None
    snapshot_source_encoding = None
    if args.txt:
        if not os.path.isfile(args.txt):
            print(f"错误：新版小说文件不存在：{args.txt}")
            return
        try:
            snapshot = _replace_reference_with_latest_snapshot(ws, args.txt)
        except ValueError as exc:
            print(f"错误：{exc}")
            return
        print(
            f"  已识别新版整本小说（{snapshot['encoding']}）：共 {snapshot['total_chapters']} 章；"
            f"复用前 {snapshot['reused_cards']} 章拆解结果，待拆新增 {snapshot['new_chapters']} 章。"
        )
        snapshot_source_name = _uploaded_source_name(args.txt)
        snapshot_source_encoding = snapshot["encoding"]
    _run_reference_pipeline(
        ws,
        batch_size=args.batch_size,
        max_chapters=args.max_chapters,
        resume=True,
        source_name=snapshot_source_name,
        source_encoding=snapshot_source_encoding,
        rebuild_reference=args.rebuild_reference,
    )


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
    from training.adaptive_builder import (
        build_target_world_knowledge,
        import_target_world_sources,
    )
    ws = _ws(args.workspace)
    import_target_world_sources(ws, args.paths, force=args.force)
    if getattr(args, "build", False):
        result = build_target_world_knowledge(
            ws,
            force=False,
            chunk_size=args.chunk_size,
            chapter_batch_size=args.chapter_batch_size,
            max_workers=args.max_workers,
            primary_source=args.primary,
        )
        if not result:
            raise RuntimeError("目标世界资料已导入，但资料库构建失败，请检查任务日志后重试。")


def cmd_world_build(args):
    from training.adaptive_builder import build_target_world_knowledge
    ws = _ws(args.workspace)
    result = build_target_world_knowledge(
        ws,
        force=args.force,
        chunk_size=args.chunk_size,
        chapter_batch_size=args.chapter_batch_size,
        max_workers=args.max_workers,
        primary_source=args.primary,
        merge_only=args.merge_only,
    )
    if not result:
        raise RuntimeError("目标世界资料库构建失败，请检查任务日志后重试。")


def cmd_novel_name_synopsis(args):
    from training.adaptive_builder import gen_novel_name_synopsis
    ws = _ws(args.workspace)
    gen_novel_name_synopsis(ws, force=args.force)


def cmd_story_design(args):
    from training.adaptive_builder import gen_story_design
    ws = _ws(args.workspace)
    gen_story_design(ws, force=args.force, creative_direction=args.direction,
                     direction_file=args.direction_file)


def cmd_story_design_extend(args):
    from training.adaptive_builder import extend_story_design
    ws = _ws(args.workspace)
    extend_story_design(
        ws,
        use_reference=args.use_reference,
        creative_direction=args.direction,
        direction_file=args.direction_file,
    )


def cmd_design_concept(args):
    from training.adaptive_builder import gen_design_concept
    ws = _ws(args.workspace)
    gen_design_concept(ws, force=args.force, creative_direction=args.direction,
                       direction_file=args.direction_file)


def cmd_stage_design(args):
    from training.adaptive_builder import gen_stage_design
    ws = _ws(args.workspace)
    gen_stage_design(ws, force=args.force, creative_direction=args.direction,
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


def cmd_web(args):
    """启动本地可视化工作台。"""
    try:
        import uvicorn
        from webui.app import create_app
    except ImportError as exc:
        print("错误：Web 工作台依赖未安装。请重新执行 pip install --upgrade harnessNovel。")
        print(f"详情：{exc}")
        return

    app = create_app(workspace_root=args.workspace_root)
    print(f">>> HarnessNovel Web 工作台已启动：http://{args.host}:{args.port} <<<")
    print("按 Ctrl+C 停止服务。")
    uvicorn.run(app, host=args.host, port=args.port)


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
    p.add_argument("--max-chapters", type=int, default=None, help="只拆解前 N 章（默认整本）")
    p.add_argument("--no-analyze", action="store_true", help="仅导入参考小说，不立即开始拆解")
    p.add_argument("--rebuild-reference", action="store_true", help="清除已有参考拆解资产后重新拆解")

    # reference-resume
    p = sub.add_parser("reference-resume", help="继续拆解已导入的参考小说，不重复上传文件")
    p.add_argument("workspace", help="工作区名称")
    p.add_argument("--txt", help="作者更新后重新下载的完整小说 TXT 文件")
    p.add_argument("--batch-size", type=int, default=20, help="每次读取章节数，用于识别故事情节单元（默认20）")
    p.add_argument("--max-chapters", type=int, default=None, help="将拆解范围扩展到前 N 章（默认整本）")
    p.add_argument("--rebuild-reference", action="store_true", help="清除已有参考拆解资产后重新拆解")

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
    p.add_argument("--build", action="store_true", help="导入完成后立即构建目标世界资料库")
    p.add_argument("--chunk-size", type=int, default=36000, help="构建时的资料分片字符数（默认36000）")
    p.add_argument("--chapter-batch-size", type=int, default=20, help="构建时每批最多处理章节数（默认20，同时受分片字符数限制）")
    p.add_argument("--max-workers", type=int, default=4, help="章节批次并行提取数（默认4）")
    p.add_argument("--primary", default=None, help="指定主资料；不指定时默认使用最大文件")

    # world-build
    p = sub.add_parser("world-build", help="结构化梳理目标题材资料")
    p.add_argument("workspace", help="工作区名称")
    p.add_argument("--force", action="store_true", help="强制重新结构化和汇总")
    p.add_argument("--chunk-size", type=int, default=36000, help="资料分片字符数（默认36000）")
    p.add_argument("--chapter-batch-size", type=int, default=20, help="章节资料每批章节数（默认20）")
    p.add_argument("--max-workers", type=int, default=4, help="章节批次并行提取数（默认4）")
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

    # design-concept (第一步：全书设计)
    p = sub.add_parser("design-concept", help="生成粗略大纲与世界观（全书设计第一步）")
    p.add_argument("workspace", help="工作区名称")
    p.add_argument("--force", action="store_true")
    p.add_argument("--direction", help="创作方向（字符串）")
    p.add_argument("--direction-file", help="创作方向文件路径")

    # stage-design (第二步：舞台设计)
    p = sub.add_parser("stage-design", help="基于粗略大纲与世界观生成长线主线与舞台路线图")
    p.add_argument("workspace", help="工作区名称")
    p.add_argument("--force", action="store_true")
    p.add_argument("--direction", help="创作方向（字符串）")
    p.add_argument("--direction-file", help="创作方向文件路径")

    # story-design-extend
    p = sub.add_parser("story-design-extend", help="保留已有设计，追加长线、角色线和后续舞台")
    p.add_argument("workspace", help="工作区名称")
    p.add_argument("--use-reference", action="store_true", help="读取上次全书设计后新增的参考拆解内容")
    p.add_argument("--direction", help="可选的续写方向（字符串）")
    p.add_argument("--direction-file", help="可选的续写方向文件路径")

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

    # web
    p = sub.add_parser("web", help="启动本地可视化工作台")
    p.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1，仅本机访问）")
    p.add_argument("--port", type=int, default=8765, help="监听端口（默认 8765）")
    p.add_argument("--workspace-root", help="工作区根目录；不传时优先使用 ~/Documents/my-novels")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    dispatch = {
        "list": cmd_list,
        "init": cmd_init,
        "reference-resume": cmd_reference_resume,
        "world-import": cmd_world_import,
        "world-build": cmd_world_build,
        "novel-outline": cmd_novel_outline,
        "novel-name-synopsis": cmd_novel_name_synopsis,
        "story-design": cmd_story_design,
        "design-concept": cmd_design_concept,
        "stage-design": cmd_stage_design,
        "story-design-extend": cmd_story_design_extend,
        "stage-insert": cmd_stage_insert,
        "mechanics-init": cmd_mechanics_init,
        "volume-outline": cmd_volume_outline,
        "story-arcs": cmd_story_arcs,
        "chapter-outlines": cmd_chapter_outlines,
        "write": cmd_write,
        "web": cmd_web,
        "config": cmd_config
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
