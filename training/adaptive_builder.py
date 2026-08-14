import sys
import os
import re
import json
import hashlib
import math
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.llm_provider import LLMCallCancelled, LLMProvider
from core.prompt_loader import PromptLoader
from core.config import ConfigLoader
from core.text_utils import normalize_text, parse_json_response
from core.workspace import init_workspace
from core.adaptation import (
    append_adaptation_report,
    format_forbidden_terms,
    load_rewrite_map,
    scan_forbidden_terms,
)
from core.world_knowledge import (
    build_world_knowledge,
    import_world_sources,
    load_world_knowledge_context,
    world_knowledge_status,
)
from training.reference_finder import (
    list_reference_volumes,
    list_reference_story_arcs,
    load_reference_novel_outline,
    load_reference_volume_outline,
)

BATCH_SIZE = 20
STORY_ARC_FILE_RE = re.compile(r'^arc_(\d+)_ch(\d+)_(\d+)\.md$')
STORY_ARC_TARGET_CHAPTERS = 5
STAGE_DESIGN_PIPELINE_VERSION = 2
STAGE_HEADING_RE = re.compile(
    r"^#{1,6}\s*(?:舞台|stage)\s*0*(\d+)\b[^\n]*",
    re.IGNORECASE | re.MULTILINE,
)
STAGE_OUTLINE_HEADING_RE = re.compile(
    r"^#{1,6}\s*(?:第\s*)?阶段\s*0*(\d+)\b[^\n]*",
    re.IGNORECASE | re.MULTILINE,
)
# 舞台路线图规整用：识别各种写法的舞台标题行（# / ## / 加粗 / 纯文本，可带前导零），
# 统一改写为一级标题「# 舞台N：名称」。「舞台规则：」「舞台内短线：」等正文行因「舞台」后无数字不会命中。
_STAGE_HEADER_LINE_RE = re.compile(
    r"^\s*(?:#{1,6}\s+|\*\*\s*)?(?:舞台|stage)\s*0*(\d+)[\s:：.．]*([^\n]*?)\s*\**\s*$",
    re.IGNORECASE,
)
# 文档总标题（如「# 舞台路线图」），正是它常把舞台挤到二级标题的元凶，规整时移除。
_STAGE_TITLE_LINE_RE = re.compile(
    r"^\s*#{1,6}\s+(?:舞台路线图|全书舞台路线图|舞台设计|舞台规划|舞台大纲|舞台总览|stage\s*roadmap)\s*$",
    re.IGNORECASE,
)
_STAGE_CODE_FENCE_RE = re.compile(r"^\s*```.*$", re.IGNORECASE)


def _normalize_stage_roadmap(text):
    """把舞台路线图规整为稳定格式：每个舞台写成一级标题「# 舞台N：名称」，并去除文档总标题与代码围栏。

    仅改写「舞台标题行」、移除干扰项；正文（预计章节数、阶段功能等）原样保留。幂等。
    在写盘前与解析前统一调用，避免下游因标题层级/写法差异识别不到舞台。
    """
    if not text:
        return ""
    output_lines = []
    for line in text.splitlines():
        if _STAGE_CODE_FENCE_RE.match(line):
            continue
        header = _STAGE_HEADER_LINE_RE.match(line)
        if header:
            number = int(header.group(1))
            name = header.group(2).strip().strip("*#：:.- ").strip()
            output_lines.append(f"# 舞台{number}：{name}" if name else f"# 舞台{number}：")
            continue
        if _STAGE_TITLE_LINE_RE.match(line):
            continue
        output_lines.append(line)
    return "\n".join(output_lines).strip()


def _get_llm():
    config = ConfigLoader.get_adaptive_builder_config()
    if not config.get("api_key"):
        config["api_key"] = os.getenv("OPENAI_API_KEY")
    if not config.get("api_key"):
        print("错误：未检测到 API Key。")
        return None
    return LLMProvider(**config)


def _get_lite_llm():
    """获取写作生产 LLM（flash）：故事情节、章纲、正文及轻量辅助任务。"""
    config = ConfigLoader.get_adaptive_builder_lite_config()
    if not config:
        config = ConfigLoader.get_adaptive_builder_config()
    if not config.get("api_key"):
        config["api_key"] = os.getenv("OPENAI_API_KEY")
    if not config.get("api_key"):
        print("错误：未检测到 API Key。")
        return None
    return LLMProvider(**config)


def _read_file(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()
    return content if content else None


def _load_outline_rules(ws):
    """加载大纲/卷纲设计规则。"""
    rules = _read_file(os.path.join(ws.file_system, "OUTLINE_RULES.md"))
    return rules or "（无大纲设计规则）"


def _load_world_knowledge_optional(ws, purpose, max_chars=80000, require_ready=False):
    """加载目标世界知识库；不存在时降级为纯参考小说+创作方向流程。"""
    status = world_knowledge_status(ws)
    if (
        require_ready
        and status["enabled"]
        and status["source_count"] > 0
        and not status["ready"]
    ):
        raise RuntimeError(
            "已上传并启用目标世界资料，但资料库尚未完整构建。"
            "请返回“目标世界”步骤重试构建，完成7个栏目后再生成全书设计。"
        )
    world_knowledge = load_world_knowledge_context(ws, max_chars=max_chars)
    if world_knowledge:
        print(f"  -> 已加载目标世界资料库用于{purpose}。")
        return world_knowledge
    print(f"  -> 未检测到目标世界资料库，跳过{purpose}。")
    print("     需要资料库增强时，可先运行 novel world-import / novel world-build。")
    return ""


def _write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content + "\n")


def run_step(*, llm, folder, prompt_vars, output_path, label=None,
             header=None, save=None, write_guard=False, cancel_event=None):
    """核心生成三联：load→generate→normalize→write，可选 header/save 打印。

    label 同时作为 header/save 的派生基础（默认 header=">>> 生成{label} <<<"，
    save="  -> {label}已保存：{output_path}"，冒号为全角）；显式传入 header/save
    则覆盖派生。label=None 且不传 header/save 时静默（无打印）。
    write_guard=True 时仅在 result 非空时写盘与打印 save。
    """
    if label is not None and header is None:
        header = f">>> 生成{label} <<<"
    if label is not None and save is None:
        save = f"  -> {label}已保存：{output_path}"
    if header is not None:
        print(header)
    prompt = PromptLoader.load(folder, **prompt_vars)
    result = normalize_text(_generate_with_cancel(llm, prompt, cancel_event))
    if result or not write_guard:
        _write_file(output_path, result)
    if save is not None and (result or not write_guard):
        print(save)
    return result


def _load_creative_direction(ws, cli_input=None, direction_file=None):
    """加载创作方向：优先 CLI 参数，其次指定文件，最后工作区的 creative_direction.md。"""
    if cli_input:
        return cli_input
    if direction_file:
        content = _read_file(direction_file)
        if content:
            return content
    content = _read_file(ws.creative_direction)
    if content:
        lines = []
        for line in content.split('\n'):
            stripped = line.strip()
            if stripped.startswith('<!--') and stripped.endswith('-->'):
                continue
            lines.append(line)
        cleaned = '\n'.join(lines).strip()
        body = cleaned
        for heading in ['# 创作方向', '## 题材与定位', '## 主角构想', '## 世界观方向',
                        '## 核心冲突', '## 希望保留的参考特质', '## 希望改变的部分', '## 其他补充']:
            body = body.replace(heading, '')
        if body.strip():
            return cleaned
    return ""


def _gen_rewrite_map(ws, llm, force=False):
    """基于参考与新书方案生成全书换皮映射表，供后续阶段硬约束。"""
    adaptation_dir = os.path.join(ws.file_system, "adaptation")
    output_path = os.path.join(adaptation_dir, "rewrite_map.md")
    existing = _read_file(output_path)
    if existing and not force:
        print(f"换皮映射表已存在：{output_path}")
        return existing

    reference_outline = load_reference_novel_outline(ws.reference_outlines)
    novel_outline = _read_file(os.path.join(ws.file_system, "novel_outline.md")) or ""
    new_worldview = _read_file(os.path.join(ws.file_system, "new_novel_worldview.md")) or ""

    if not reference_outline or not novel_outline:
        print("  警告：参考大纲或新小说大纲缺失，暂不生成换皮映射表。")
        return ""

    return run_step(
        llm=llm,
        folder="rewrite_map_extract",
        label="全书换皮映射表",
        save=f"  -> 换皮映射表已保存：{output_path}",
        write_guard=True,
        output_path=output_path,
        prompt_vars=dict(
            reference_outline=reference_outline,
            novel_outline=novel_outline,
            new_novel_worldview=new_worldview or "（未生成新小说世界观）",
        ),
    )


def _ensure_rewrite_map(ws, llm):
    """确保旧工作区在后续阶段也能补齐换皮映射表。"""
    output_path = os.path.join(ws.file_system, "adaptation", "rewrite_map.md")
    if _read_file(output_path):
        return
    _gen_rewrite_map(ws, llm, force=False)


def _story_design_dir(ws):
    return os.path.join(ws.file_system, "story_design")


def _story_design_path(ws, name):
    return os.path.join(_story_design_dir(ws), name)


def _volume_stage_plan_path(ws, vol_idx):
    return os.path.join(_story_design_dir(ws), "stages", f"vol_{vol_idx:02d}_stage.md")


def _rough_outline_path(ws):
    return _story_design_path(ws, "rough_outline.md")


def _worldview_path(ws):
    return _story_design_path(ws, "worldview.md")


def _stage_outline_path(ws):
    return _story_design_path(ws, "stage_outline.md")


def _rough_outline_with_stages(ws):
    """供舞台及后续步骤读取；磁盘上仍保持粗略大纲与阶段粗纲相互独立。"""
    rough = (
        _read_file(_rough_outline_path(ws))
        or _read_file(_story_design_path(ws, "core_gameplay.md"))
        or "（未生成粗略大纲）"
    )
    stages = _read_file(_stage_outline_path(ws))
    return f"{rough}\n\n---\n\n{stages}" if stages else rough


def _design_versions_dir(ws, scope):
    return os.path.join(_story_design_dir(ws), "versions", scope)


def _backup_design_files(ws, scope, files):
    """把当前文件备份到 versions/<scope>/ 下，支持多轮微调回退。"""
    import time
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = _design_versions_dir(ws, scope)
    os.makedirs(out_dir, exist_ok=True)
    for rel, path in files.items():
        content = _read_file(path)
        if not content:
            continue
        _write_file(os.path.join(out_dir, f"{rel}_{stamp}.md"), content)



def _load_story_design_assets(ws):
    # 新流程：核心玩法与角色线并入粗略大纲 rough_outline.md，保持下游 4 个 key 不变。
    rough = _rough_outline_with_stages(ws)
    return {
        "core_gameplay": rough or "（未生成粗略大纲/核心玩法）",
        "long_mainline": _read_file(_story_design_path(ws, "long_mainline.md")) or "（未生成全书长线主线）",
        "stage_roadmap": _read_file(_story_design_path(ws, "stage_roadmap.md")) or "（未生成舞台路线图）",
        "character_arcs": rough or _read_file(_story_design_path(ws, "character_arcs.md")) or "（未生成角色成长线）",
    }


def _story_design_state_path(ws):
    return _story_design_path(ws, "design_state.json")


def _load_story_design_state(ws):
    content = _read_file(_story_design_state_path(ws))
    if not content:
        return {}
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _mark_concept_revision(ws):
    """记录粗略大纲/世界观发生了一次有效更新。"""
    state = _load_story_design_state(ws)
    state["concept_revision"] = int(state.get("concept_revision") or 0) + 1
    state.setdefault("stage_synced_concept_revision", 0)
    state["concept_updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json_file(_story_design_state_path(ws), state)
    return state["concept_revision"]


def _mark_stage_design_synced(ws):
    """记录舞台设计已经吸收当前版本的全书设计。"""
    state = _load_story_design_state(ws)
    revision = int(state.get("concept_revision") or 0)
    state["stage_synced_concept_revision"] = revision
    state["stage_synced_at"] = datetime.now().isoformat(timespec="seconds")
    state["pending_reference_stage_sync"] = False
    state.pop("reference_stage_increment", None)
    _write_json_file(_story_design_state_path(ws), state)
    return revision


def _arc_usage_state_path(ws):
    return _story_design_path(ws, "arc_usage_state.json")


def _chapter_usage_state_path(ws):
    return _story_design_path(ws, "chapter_usage_state.json")


def _load_chapter_usage_state(ws):
    content = _read_file(_chapter_usage_state_path(ws))
    if not content:
        return {}
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _reference_chapter_cards(ws):
    cards_dir = os.path.join(ws.reference, "chapter_cards")
    cards = []
    if not os.path.isdir(cards_dir):
        return cards
    for filename in sorted(os.listdir(cards_dir)):
        if not re.match(r"chapter_\d+\.json$", filename):
            continue
        try:
            card = json.loads(_read_file(os.path.join(cards_dir, filename)) or "{}")
        except json.JSONDecodeError:
            continue
        if isinstance(card, dict) and int(card.get("chapter") or 0) > 0:
            cards.append(card)
    return cards


def _mark_reference_chapters_used(ws, chapter_numbers):
    state = _load_chapter_usage_state(ws)
    now = datetime.now().isoformat(timespec="seconds")
    for number in chapter_numbers:
        state[str(int(number))] = {"used": True, "used_at": now}
    _write_json_file(_chapter_usage_state_path(ws), state)


def _unused_reference_chapter_context(ws, max_chars=30000):
    state = _load_chapter_usage_state(ws)
    legacy_baseline = 0
    if not state:
        legacy_baseline = int(_load_story_design_state(ws).get("reference_processed_chapters") or 0)
    selected = []
    length = 0
    for card in _reference_chapter_cards(ws):
        number = int(card["chapter"])
        record = state.get(str(number), {})
        used = bool(record.get("used")) if isinstance(record, dict) else bool(record)
        used = used or (not state and number <= legacy_baseline)
        if used:
            continue
        text = json.dumps({
            "chapter": number,
            "title": card.get("title"),
            "chapter_outline": card.get("chapter_outline_600"),
            "chapter_rhythm": card.get("chapter_rhythm"),
            "story_line": card.get("story_line"),
            "highlights": card.get("highlights"),
        }, ensure_ascii=False)
        if selected and length + len(text) > max_chars:
            break
        selected.append((number, text))
        length += len(text)
    return selected


def _load_arc_usage_state(ws):
    """加载片段级 used 标记：{arc_rel_path: true}。不存在时返回空 dict。"""
    content = _read_file(_arc_usage_state_path(ws))
    if not content:
        return {}
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _save_arc_usage_state(ws, state):
    _write_json_file(_arc_usage_state_path(ws), state)


def _all_reference_arc_keys(ws):
    """枚举当前参考拆解中所有故事片段的相对路径（相对 reference_outlines）。"""
    keys = []
    base = ws.reference_outlines
    for volume in list_reference_volumes(base):
        for arc in list_reference_story_arcs(base, volume["vol_idx"]):
            try:
                rel = os.path.relpath(arc["path"], base)
            except ValueError:
                rel = arc["path"]
            keys.append(rel)
    return keys


def _init_arc_usage_state(ws):
    """标记当前所有参考片段为已使用（used=True）。

    在初次生成（路由 1）完成后调用，后续续写只消费 used=False 的新增片段。
    """
    keys = _all_reference_arc_keys(ws)
    state = _load_arc_usage_state(ws)
    for key in keys:
        state[key] = True
    _save_arc_usage_state(ws, state)


def _unused_reference_arcs(ws, max_chars=26000):
    """收集 used=False 的参考片段内容，供续写作为输入。"""
    state = _load_arc_usage_state(ws)
    keys = _all_reference_arc_keys(ws)
    base = ws.reference_outlines
    unused = []
    length = 0
    for volume in list_reference_volumes(base):
        for arc in list_reference_story_arcs(base, volume["vol_idx"]):
            try:
                rel = os.path.relpath(arc["path"], base)
            except ValueError:
                rel = arc["path"]
            if state.get(rel, False):
                continue
            content = arc.get("content") or _read_file(arc["path"])
            if not content:
                continue
            if length + len(content) > max_chars:
                break
            unused.append({
                "path": rel,
                "start_ch": arc["start_ch"],
                "end_ch": arc["end_ch"],
                "content": content,
            })
            length += len(content)
    return unused


def _mark_arcs_used(ws, rel_paths, stage_numbers=None):
    """记录片段已被舞台设计实际映射，并保留对应舞台编号。"""
    if not rel_paths:
        return
    state = _load_arc_usage_state(ws)
    now = datetime.now().isoformat(timespec="seconds")
    stages = sorted({int(item) for item in (stage_numbers or []) if str(item).isdigit()})
    for path in rel_paths:
        previous = state.get(path, {})
        previous_stages = previous.get("stage_numbers", []) if isinstance(previous, dict) else []
        state[path] = {
            "used": True,
            "used_at": now,
            "stage_numbers": sorted(set(previous_stages + stages)),
        }
    _save_arc_usage_state(ws, state)


def _direction_history_path(ws):
    return _story_design_path(ws, "direction_history.json")


_DIRECTION_MODE_LABELS = {
    "initial": "初版设计",
    "rebuild": "重新设计",
    "extend": "续写舞台",
    "stage_insert": "插入舞台",
}


def record_creative_direction(ws, direction, mode):
    """记录一次创作方向输入到历史，供工作台回看与复用。"""
    text = (direction or "").strip()
    if not text:
        return
    os.makedirs(_story_design_dir(ws), exist_ok=True)
    history_path = _direction_history_path(ws)
    history = []
    raw = _read_file(history_path)
    if raw:
        try:
            history = json.loads(raw)
        except json.JSONDecodeError:
            history = []
    if not isinstance(history, list):
        history = []
    preview = re.sub(r"\s+", " ", text)[:80]
    history.append({
        "id": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "mode": _DIRECTION_MODE_LABELS.get(mode, mode),
        "preview": preview,
        "text": text,
    })
    _write_file(history_path, json.dumps(history[-20:], ensure_ascii=False, indent=2))


def _reference_design_progress(ws):
    """读取当前参考拆解进度；缺少断点文件时退回已切分章节数。"""
    state_path = os.path.join(ws.reference, "import_state.json")
    state = _read_file(state_path)
    try:
        state = json.loads(state) if state else {}
    except json.JSONDecodeError:
        state = {}

    processed = int(state.get("processed_chapters") or 0) if isinstance(state, dict) else 0
    total = int(state.get("total_chapters") or 0) if isinstance(state, dict) else 0
    if processed:
        return processed, total

    chapters_dir = os.path.join(ws.reference, "chapters")
    if not os.path.isdir(chapters_dir):
        return 0, total
    chapter_count = sum(
        1
        for _, _, files in os.walk(chapters_dir)
        for filename in files
        if filename.endswith((".md", ".txt")) and not filename.startswith("_")
    )
    return chapter_count, total or chapter_count


def _record_story_design_reference_snapshot(ws, reset_extensions=False):
    """保存初版设计对应的参考进度，用于判断后续是否有新增参考内容。"""
    existing = _load_story_design_state(ws)
    if existing and not reset_extensions:
        return existing

    processed, total = _reference_design_progress(ws)
    state = {
        "reference_processed_chapters": processed,
        "reference_total_chapters": total,
        "extension_count": 0,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    _write_json_file(_story_design_state_path(ws), state)
    return state


def _reference_story_arc_delta(ws, baseline_chapter, current_chapter, max_chars=26000):
    """只收集设计快照之后新增的参考故事片段，避免把旧参考再次塞入上下文。"""
    if current_chapter <= baseline_chapter:
        return ""

    items = []
    chapter_offset = 0
    for volume in list_reference_volumes(ws.reference_outlines):
        meta_path = os.path.join(volume["dir_path"], "meta.json")
        meta = {}
        try:
            meta = json.loads(_read_file(meta_path) or "{}")
        except json.JSONDecodeError:
            pass
        is_virtual_volume = isinstance(meta, dict) and int(meta.get("start_ch") or 0) > 0

        for arc in list_reference_story_arcs(ws.reference_outlines, volume["vol_idx"]):
            if is_virtual_volume:
                start_ch = int(arc["start_ch"])
                end_ch = int(arc["end_ch"])
            else:
                start_ch = chapter_offset + int(arc["start_ch"])
                end_ch = chapter_offset + int(arc["end_ch"])
            if end_ch <= baseline_chapter or start_ch > current_chapter:
                continue
            items.append((start_ch, end_ch, arc["content"]))

        chapter_offset += int(volume.get("chapter_count") or 0)

    parts = []
    length = 0
    for start_ch, end_ch, content in sorted(items, key=lambda item: (item[0], item[1])):
        part = f"【参考新增故事片段：第{start_ch}-{end_ch}章】\n{content.strip()}"
        if parts and length + len(part) > max_chars:
            break
        parts.append(part)
        length += len(part)
    return "\n\n---\n\n".join(parts)


def _next_stage_number(stage_roadmap):
    numbers = [int(value) for value in STAGE_HEADING_RE.findall(_normalize_stage_roadmap(stage_roadmap or ""))]
    return max(numbers, default=0) + 1


def _parse_story_design_extension(raw):
    markers = ["LONG_MAINLINE_APPEND", "CHARACTER_ARCS_APPEND", "STAGE_ROADMAP_APPEND"]
    marker_re = re.compile(r"^<<<(" + "|".join(markers) + r")>>>\s*$", re.MULTILINE)
    matches = list(marker_re.finditer(raw or ""))
    sections = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        sections[match.group(1)] = raw[match.end():end].strip()
    missing = [marker for marker in markers if not sections.get(marker)]
    if missing:
        raise ValueError("设计续写结果缺少分段标记：" + "、".join(missing))
    return sections


def _append_story_design_section(path, title, content):
    existing = _read_file(path) or ""
    suffix = f"# {title}\n\n{content.strip()}"
    _write_file(path, f"{existing}\n\n---\n\n{suffix}" if existing else suffix)


def extend_story_design(ws, use_reference=False, creative_direction=None, direction_file=None):
    """在不改动已有设计的前提下，追加长线、角色线和后续舞台。"""
    assets = _load_story_design_assets(ws)
    required_assets = ("core_gameplay", "long_mainline", "stage_roadmap", "character_arcs")
    missing = [name for name in required_assets if assets[name].startswith("（未生成")]
    if missing:
        print("错误：请先完成全书设计，再执行设计续写。")
        return

    state = _load_story_design_state(ws)
    baseline = int(state.get("reference_processed_chapters") or 0)
    current_progress, total_progress = _reference_design_progress(ws)
    if use_reference and current_progress <= baseline:
        print("错误：没有检测到新增参考拆解内容。可不带 --use-reference，直接基于现有舞台扩展。")
        return

    reference_delta = ""
    if use_reference:
        reference_delta = _reference_story_arc_delta(ws, baseline, current_progress)
        if not reference_delta:
            print("警告：未找到新增参考故事片段，将只依据新增章节范围与现有设计继续扩展。")
            reference_delta = "（新增参考章节已完成解析，但未找到可读取的新增故事片段。）"

    direction = _load_creative_direction(ws, creative_direction, direction_file)
    record_creative_direction(ws, direction, "extend")
    llm = _get_llm()
    if not llm:
        return
    world_knowledge = _load_world_knowledge_optional(ws, "全书设计续写")
    next_stage = _next_stage_number(assets["stage_roadmap"])

    source_label = (
        f"参考小说新增第 {baseline + 1}-{current_progress} 章"
        if use_reference else "当前新书已有的玩法、长线、角色线与舞台"
    )
    print(f">>> 续写全书设计：基于{source_label} <<<")
    raw = normalize_text(llm.generate(PromptLoader.load(
        "story_design_extend",
        creative_direction=direction or "（无额外补充方向）",
        use_reference="是" if use_reference else "否",
        reference_range=f"第{baseline + 1}-{current_progress}章" if use_reference else "（本次不读取参考新增章节）",
        reference_delta=reference_delta or "（本次不参考新增拆解内容）",
        core_gameplay=assets["core_gameplay"],
        existing_long_mainline=assets["long_mainline"],
        existing_character_arcs=assets["character_arcs"],
        existing_stage_roadmap=assets["stage_roadmap"],
        next_stage_number=next_stage,
        world_knowledge=world_knowledge or "（未提供目标世界知识库）",
    )))

    try:
        sections = _parse_story_design_extension(raw)
    except ValueError as exc:
        print(f"错误：{exc}，未写入任何设计文件。")
        return
    sections["STAGE_ROADMAP_APPEND"] = _normalize_stage_roadmap(sections["STAGE_ROADMAP_APPEND"])
    if not re.search(rf"^#{{1,6}}\s*舞台\s*{next_stage}\s*[：:]", sections["STAGE_ROADMAP_APPEND"], re.MULTILINE):
        print(f"错误：新增舞台必须从“# 舞台{next_stage}：”开始，未写入任何设计文件。")
        return

    _append_story_design_section(
        _story_design_path(ws, "long_mainline.md"),
        f"长线主线续写（第{int(state.get('extension_count') or 0) + 1}次）",
        sections["LONG_MAINLINE_APPEND"],
    )
    _append_story_design_section(
        _story_design_path(ws, "character_arcs.md"),
        f"角色成长线续写（第{int(state.get('extension_count') or 0) + 1}次）",
        sections["CHARACTER_ARCS_APPEND"],
    )
    stage_path = _story_design_path(ws, "stage_roadmap.md")
    combined_stage_roadmap = _normalize_stage_roadmap(
        f"{assets['stage_roadmap']}\n\n---\n\n{sections['STAGE_ROADMAP_APPEND'].strip()}"
    )
    _write_file(stage_path, combined_stage_roadmap)

    extension_dir = os.path.join(ws.file_system, "adaptation", "story_design_extensions")
    extension_path = os.path.join(extension_dir, f"extension_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md")
    _write_file(extension_path, (
        f"# 全书设计续写记录\n\n"
        f"来源：{source_label}\n\n"
        f"使用新增参考：{'是' if use_reference else '否'}\n\n"
        f"{raw}"
    ))

    state.update({
        "reference_processed_chapters": current_progress if use_reference else baseline,
        "reference_total_chapters": total_progress,
        "extension_count": int(state.get("extension_count") or 0) + 1,
        "last_extension_used_reference": use_reference,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    })
    _write_json_file(_story_design_state_path(ws), state)
    print(f"  -> 长线主线已追加：{_story_design_path(ws, 'long_mainline.md')}")
    print(f"  -> 角色成长线已追加：{_story_design_path(ws, 'character_arcs.md')}")
    print(f"  -> 新增舞台已追加：{stage_path}")
    print(f"  -> 续写记录已保存：{extension_path}")


def _mechanics_dir(ws):
    return os.path.join(ws.file_system, "mechanics")


def _mechanics_path(ws, name):
    return os.path.join(_mechanics_dir(ws), name)


def _write_json_file(path, data):
    _write_file(path, json.dumps(data, ensure_ascii=False, indent=2))


def _read_json_file(path):
    content = _read_file(path)
    if not content:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def _finalized_chapters_path(ws):
    return os.path.join(ws.file_system, "finalized_chapters.json")


def _draft_chapter_path(ws, volume, chapter):
    return os.path.join(
        ws.file_system, "chapters", f"vol_{volume:02d}",
        f"{chapter:03d}_第{chapter}章.md",
    )


def _content_hash(content):
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def _load_finalization_payload(ws):
    payload = _read_json_file(_finalized_chapters_path(ws))
    if not isinstance(payload, dict):
        payload = {}
    drafts = payload.get("drafts") if isinstance(payload.get("drafts"), dict) else {}
    normalized = {"version": 2, "drafts": {}}
    for volume_key, entries in drafts.items():
        records = {}
        if isinstance(entries, list):  # 兼容旧版仅保存章节号的格式。
            entries = {str(chapter): {"finalized": True} for chapter in entries}
        if not isinstance(entries, dict):
            continue
        for chapter_key, record in entries.items():
            try:
                chapter = int(chapter_key)
            except (TypeError, ValueError):
                continue
            if chapter < 1:
                continue
            record = record if isinstance(record, dict) else {}
            if record.get("finalized", True):
                records[str(chapter)] = {
                    "finalized": True,
                    "synced_hash": str(record.get("synced_hash") or ""),
                    "synced_at": str(record.get("synced_at") or ""),
                }
        if records:
            normalized["drafts"][str(volume_key)] = records
    return normalized


def chapter_finalization_status(ws):
    payload = _load_finalization_payload(ws)
    result = {"version": 2, "drafts": {}}
    for volume_key, records in payload["drafts"].items():
        try:
            volume = int(str(volume_key).replace("vol_", ""))
        except ValueError:
            continue
        rendered = {}
        for chapter_key, record in records.items():
            chapter = int(chapter_key)
            content = _read_file(_draft_chapter_path(ws, volume, chapter)) or ""
            current_hash = _content_hash(content) if content else ""
            synced_hash = record.get("synced_hash") or ""
            rendered[str(chapter)] = {
                "finalized": True,
                "status": "synced" if current_hash and synced_hash == current_hash else "pending",
                "current_hash": current_hash,
                "synced_hash": synced_hash,
                "synced_at": record.get("synced_at") or "",
            }
        if rendered:
            result["drafts"][f"vol_{volume:02d}"] = rendered
    return result


def _finalized_chapter_numbers(ws, kind, volume):
    if kind not in {"outlines", "drafts"}:
        return set()
    records = chapter_finalization_status(ws)["drafts"].get(f"vol_{volume:02d}", {})
    if kind == "drafts":
        return {int(chapter) for chapter, record in records.items() if record.get("finalized")}
    return {
        int(chapter) for chapter, record in records.items()
        if record.get("status") == "synced"
    }


def _finalized_chapter_boundary(ws, kind, volume, start_chapter, end_chapter):
    finalized = [
        chapter for chapter in _finalized_chapter_numbers(ws, kind, volume)
        if start_chapter <= chapter <= end_chapter
    ]
    return max(finalized) if finalized else start_chapter - 1


def set_chapter_finalized(ws, kind, volume, chapter, finalized):
    if kind != "drafts":
        raise ValueError("只能将正文标记为最终版；章纲由正文同步后自动锁定。")
    volume, chapter = int(volume), int(chapter)
    if volume < 1 or chapter < 1:
        raise ValueError("卷号和章节号必须是正整数。")
    payload = _load_finalization_payload(ws)
    key = f"vol_{volume:02d}"
    records = payload["drafts"].setdefault(key, {})
    if finalized:
        if not _read_file(_draft_chapter_path(ws, volume, chapter)):
            raise ValueError("正文不存在或为空，无法标记为最终版。")
        previous = records.get(str(chapter), {})
        records[str(chapter)] = {
            "finalized": True,
            "synced_hash": str(previous.get("synced_hash") or ""),
            "synced_at": str(previous.get("synced_at") or ""),
        }
    else:
        records.pop(str(chapter), None)
    if not records:
        payload["drafts"].pop(key, None)
    _write_json_file(_finalized_chapters_path(ws), payload)
    return chapter_finalization_status(ws)


def clear_finalized_chapters(ws, kind, volume, chapters):
    if kind != "drafts":
        return chapter_finalization_status(ws)
    payload = _load_finalization_payload(ws)
    key = f"vol_{int(volume):02d}"
    records = payload["drafts"].get(key, {})
    for chapter in chapters:
        records.pop(str(int(chapter)), None)
    if not records:
        payload["drafts"].pop(key, None)
    _write_json_file(_finalized_chapters_path(ws), payload)
    return chapter_finalization_status(ws)


def _mark_finalized_draft_synced(ws, volume, chapter, expected_hash):
    content = _read_file(_draft_chapter_path(ws, volume, chapter)) or ""
    if not content or _content_hash(content) != expected_hash:
        raise RuntimeError(f"第{chapter}章最终版正文在同步期间发生变化，请重新同步。")
    payload = _load_finalization_payload(ws)
    key = f"vol_{volume:02d}"
    record = payload["drafts"].get(key, {}).get(str(chapter))
    if not record:
        raise RuntimeError(f"第{chapter}章已取消最终版标记，停止同步。")
    record["synced_hash"] = expected_hash
    record["synced_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json_file(_finalized_chapters_path(ws), payload)


def _default_mechanics_disabled(reason):
    return {
        "profile": {
            "mode": "none",
            "enabled": False,
            "visible_panel": False,
            "precision": "none",
            "type": "none",
            "reason": reason,
            "tracked_domains": [],
        },
        "design": reason,
        "rules": {
            "version": 1,
            "mode": "none",
            "event_types": [],
            "display": {
                "panel_enabled": False,
                "panel_name": "",
                "chapter_panel_sections": [],
            },
            "constraints": ["本小说不启用机制层；章纲和正文不得强行加入系统面板。"],
        },
        "state": {
            "version": 1,
            "mode": "none",
            "chapter": 0,
            "values": {},
            "inventory": {},
            "skills": {},
            "tasks": {},
            "relationships": {},
            "flags": {},
        },
    }


def _normalize_mechanics_payload(payload):
    if not isinstance(payload, dict):
        payload = _default_mechanics_disabled("LLM 未返回有效机制层 JSON，默认关闭。")

    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    mode = profile.get("mode") or payload.get("mode") or "none"
    if mode not in {"none", "light_state", "explicit_mechanics"}:
        mode = "none"

    enabled = mode != "none"
    visible_panel = bool(profile.get("visible_panel")) if enabled else False
    precision = profile.get("precision") or ("strict" if mode == "explicit_mechanics" else ("loose" if mode == "light_state" else "none"))
    mechanics_type = profile.get("type") or ("state_tracking" if mode == "light_state" else ("system_panel" if mode == "explicit_mechanics" else "none"))
    tracked_domains = profile.get("tracked_domains")
    if not isinstance(tracked_domains, list):
        tracked_domains = []

    normalized = {
        "profile": {
            "mode": mode,
            "enabled": enabled,
            "visible_panel": visible_panel,
            "precision": precision,
            "type": mechanics_type,
            "reason": profile.get("reason") or payload.get("reason") or "",
            "tracked_domains": tracked_domains,
        },
        "design": payload.get("design") if isinstance(payload.get("design"), str) else "",
        "rules": payload.get("rules") if isinstance(payload.get("rules"), dict) else {},
        "state": payload.get("state") if isinstance(payload.get("state"), dict) else {},
    }
    normalized["rules"].setdefault("version", 1)
    normalized["rules"].setdefault("mode", mode)
    normalized["rules"].setdefault("event_types", [])
    normalized["rules"].setdefault("display", {})
    normalized["rules"]["display"].setdefault("panel_enabled", visible_panel)
    normalized["rules"]["display"].setdefault("panel_name", "")
    normalized["rules"]["display"].setdefault("chapter_panel_sections", [])
    normalized["rules"].setdefault("constraints", [])
    normalized["state"].setdefault("version", 1)
    normalized["state"].setdefault("mode", mode)
    normalized["state"].setdefault("chapter", 0)
    for key in ["values", "inventory", "skills", "tasks", "relationships", "flags"]:
        normalized["state"].setdefault(key, {})
    return normalized


def _write_mechanics_payload(ws, payload):
    os.makedirs(_mechanics_dir(ws), exist_ok=True)
    profile = payload["profile"]
    state = payload["state"]
    panel = {
        "version": 1,
        "selection_mode": "auto",
        "decided": True,
        "enabled": bool(profile.get("enabled")),
        "visible_panel": bool(profile.get("visible_panel")),
        "mode": profile.get("mode") or "none",
        "type": profile.get("type") or "none",
        "reason": profile.get("reason") or payload.get("design") or "",
        "rules": payload["rules"],
        "initial_panel": _legacy_state_to_panel(state),
    }
    _write_json_file(_mechanics_path(ws, "system_panel.json"), panel)


def _load_mechanics_context(ws):
    panel = _read_json_file(_mechanics_path(ws, "system_panel.json"))
    if panel:
        return "【系统面板定义】\n" + json.dumps(panel, ensure_ascii=False, indent=2)
    profile = _read_json_file(_mechanics_path(ws, "profile.json"))
    if not profile or not profile.get("enabled"):
        return "（未启用机制层。章纲和正文不需要系统面板。）"

    design = _read_file(_mechanics_path(ws, "design.md")) or ""
    rules = _read_file(_mechanics_path(ws, "rules.json")) or "{}"
    state = _read_file(_mechanics_path(ws, "state.json")) or "{}"
    return (
        "【机制层 profile】\n"
        + json.dumps(profile, ensure_ascii=False, indent=2)
        + "\n\n【机制层设计】\n"
        + design
        + "\n\n【机制层规则】\n"
        + rules
        + "\n\n【当前机制状态】\n"
        + state
    )


def _system_panel_chapter_dir(ws, volume):
    return os.path.join(ws.file_system, "system_panels", f"vol_{volume:02d}")


def _system_panel_chapter_path(ws, volume, chapter_num):
    return os.path.join(_system_panel_chapter_dir(ws, volume), f"chapter_{chapter_num:03d}.json")


def system_panel_status(ws):
    panel = _read_json_file(_mechanics_path(ws, "system_panel.json")) or {}
    selection_mode = panel.get("selection_mode") or ("auto" if not panel else ("enabled" if panel.get("enabled") else "disabled"))
    return {
        "selection_mode": selection_mode,
        "decided": bool(panel.get("decided", selection_mode != "auto")),
        "enabled": bool(panel.get("enabled")),
        "reason": str(panel.get("reason") or ""),
    }


def configure_system_panel(ws, selection_mode):
    if selection_mode not in {"auto", "enabled", "disabled"}:
        raise ValueError("系统面板模式无效。")
    os.makedirs(_mechanics_dir(ws), exist_ok=True)
    if selection_mode == "auto":
        panel = {
            "version": 1, "selection_mode": "auto", "decided": False,
            "enabled": False, "visible_panel": False, "mode": "pending",
            "reason": "将在首次生成章纲时根据全书设计和故事情节自动判断。",
            "rules": {}, "initial_panel": {},
        }
    else:
        enabled = selection_mode == "enabled"
        panel = {
            "version": 1, "selection_mode": selection_mode, "decided": True,
            "enabled": enabled, "visible_panel": enabled,
            "mode": "explicit_mechanics" if enabled else "none",
            "type": "system_panel" if enabled else "none",
            "reason": "用户手动启用系统面板。" if enabled else "用户明确不使用系统面板。",
            "rules": {
                "constraints": ["只记录章纲中实际发生的主角状态变化，不提前发放奖励或增加剧情。"]
            } if enabled else {},
            "initial_panel": {},
        }
    _write_json_file(_mechanics_path(ws, "system_panel.json"), panel)
    return system_panel_status(ws)


def _ensure_system_panel_decision(ws, cancel_event=None):
    status = system_panel_status(ws)
    if status["selection_mode"] != "auto" or status["decided"]:
        return status
    assets = _load_story_design_assets(ws)
    llm = _get_lite_llm()
    if not llm:
        raise RuntimeError("未配置可用模型，无法自动判断是否需要系统面板。")
    prompt = PromptLoader.load(
        "mechanics_init",
        mechanics_source="（用户选择自动判断）",
        creative_direction="（无额外创作方向）",
        core_gameplay=assets["core_gameplay"],
        long_mainline=assets["long_mainline"],
        stage_roadmap=assets["stage_roadmap"],
        character_arcs=assets["character_arcs"],
    )
    raw = normalize_text(_generate_with_cancel(llm, prompt, cancel_event, temperature=0.2))
    payload = _normalize_mechanics_payload(parse_json_response(raw))
    _write_mechanics_payload(ws, payload)
    panel_path = _mechanics_path(ws, "system_panel.json")
    panel = _read_json_file(panel_path) or {}
    panel.update(selection_mode="auto", decided=True)
    _write_json_file(panel_path, panel)
    return system_panel_status(ws)


def _previous_system_panel(ws, volume, chapter_num):
    if not system_panel_status(ws)["enabled"]:
        return {"enabled": False, "chapter": max(0, chapter_num - 1), "panel": {}}
    previous = _read_json_file(_system_panel_chapter_path(ws, volume, chapter_num - 1))
    if previous:
        return {
            "chapter": previous.get("chapter", max(0, chapter_num - 1)),
            "panel": (
                previous.get("panel")
                if isinstance(previous.get("panel"), dict)
                else _legacy_state_to_panel(previous.get("protagonist_state") or {})
            ),
            "changes": previous.get("changes") if isinstance(previous.get("changes"), list) else [],
        }
    config = _read_json_file(_mechanics_path(ws, "system_panel.json")) or {}
    return {
        "chapter": max(0, chapter_num - 1),
        "panel": (
            config.get("initial_panel")
            if isinstance(config.get("initial_panel"), dict)
            else _legacy_state_to_panel(config.get("protagonist_initial_state") or {})
        ),
        "changes": [],
    }


class SystemPanelValidationError(RuntimeError):
    """模型返回的系统面板未通过 JSON 或基础结构校验。"""


def _legacy_state_to_panel(state):
    """将旧版状态快照迁移为可自由扩展的通用面板。"""
    state = state if isinstance(state, dict) else {}
    labels = {
        "identity": "身份",
        "attributes": "属性",
        "values": "核心数值",
        "resources": "资源",
        "inventory": "物品",
        "equipment": "装备",
        "skills": "技能",
        "tasks": "任务",
        "task_progress": "任务进度",
        "relationships": "关系",
        "injuries_and_status": "当前状态",
        "flags": "状态标记",
    }
    panel = {}
    for key, value in state.items():
        if key in {"version", "mode", "chapter"}:
            continue
        if value not in ({}, [], "", None):
            panel[labels.get(key, key)] = value
    return panel


def _validate_system_panel_response(payload):
    if not isinstance(payload, dict):
        raise ValueError("顶层必须是 JSON 对象")
    unknown = set(payload) - {"panel", "changes"}
    if unknown:
        raise ValueError(f"包含不允许的顶层字段：{', '.join(sorted(unknown))}")
    panel = payload.get("panel")
    changes = payload.get("changes")
    if not isinstance(panel, dict):
        raise ValueError("panel 必须是对象")
    if len(panel) > 40:
        raise ValueError("panel 最多包含 40 个一级栏目")
    if not isinstance(changes, list):
        raise ValueError("changes 必须是数组")
    if len(changes) > 30:
        raise ValueError("changes 最多包含 30 项")
    normalized = []
    for index, change in enumerate(changes, 1):
        if not isinstance(change, dict):
            raise ValueError(f"changes[{index}] 必须是对象")
        field = change.get("field")
        reason = change.get("reason", "")
        if not isinstance(field, str) or not field.strip():
            raise ValueError(f"changes[{index}].field 必须是非空字符串")
        if "before" not in change or "after" not in change:
            raise ValueError(f"changes[{index}] 必须包含 before 和 after")
        if not isinstance(reason, str):
            raise ValueError(f"changes[{index}].reason 必须是字符串")
        normalized.append({
            "field": field.strip(),
            "before": change["before"],
            "after": change["after"],
            "reason": reason.strip(),
        })
    try:
        serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"panel 包含非法 JSON 值：{exc}") from exc
    if len(serialized) > 50000:
        raise ValueError("系统面板内容过长")
    return {"panel": panel, "changes": normalized}


def _generate_chapter_system_panel(llm, ws, volume, chapter_num, chapter_outline,
                                   cancel_event=None):
    if not system_panel_status(ws)["enabled"]:
        return None
    previous = _previous_system_panel(ws, volume, chapter_num)
    definition = _read_json_file(_mechanics_path(ws, "system_panel.json")) or {
        "enabled": True,
        "visible_panel": False,
        "rules": {"constraints": ["以主角状态连续性为主，不虚构章纲未发生的数值变化。"]},
    }
    validation_feedback = "（首次生成，无校验错误）"
    last_error = ""
    for _attempt in range(3):
        prompt = PromptLoader.load(
            "chapter_system_panel",
            chapter_num=chapter_num,
            system_panel_definition=json.dumps(definition, ensure_ascii=False, indent=2),
            previous_system_panel=json.dumps(previous, ensure_ascii=False, indent=2),
            chapter_outline=chapter_outline,
            validation_feedback=validation_feedback,
        )
        raw = normalize_text(_generate_with_cancel(llm, prompt, cancel_event, temperature=0.2))
        try:
            response = _validate_system_panel_response(parse_json_response(raw))
            panel = {
                "chapter": chapter_num,
                "panel": response["panel"],
                "changes": response["changes"],
            }
            break
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            validation_feedback = (
                f"上一次返回未通过校验：{last_error}。"
                "请修正后重新输出完整 JSON，不要解释。"
            )
    else:
        raise SystemPanelValidationError(
            f"系统面板连续 3 次未通过 JSON 校验：{last_error}"
        )
    path = _system_panel_chapter_path(ws, volume, chapter_num)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _write_json_file(path, panel)
    return panel


def _update_chapter_system_panel_with_controls(
    llm, ws, volume, chapter_num, chapter_outline, completed, total,
    progress_callback=None, pause_event=None, stop_event=None, cancel_event=None,
):
    while True:
        try:
            if progress_callback:
                progress_callback(
                    "system_panel", completed, total,
                    f"章纲已保存，正在更新第{chapter_num}章系统面板",
                )
            _generate_chapter_system_panel(
                llm, ws, volume, chapter_num, chapter_outline, cancel_event,
            )
            return True
        except LLMCallCancelled:
            if stop_event is not None and stop_event.is_set():
                return False
            if progress_callback:
                progress_callback(
                    "paused", completed, total,
                    f"第{chapter_num}章系统面板更新已暂停；继续后重新更新",
                )
            if pause_event is not None:
                pause_event.wait()
            if cancel_event is not None:
                cancel_event.clear()


def sync_finalized_drafts_for_outlines(
    llm, ws, volume, through_chapter, progress_callback=None,
    pause_event=None, stop_event=None, cancel_event=None,
):
    """按顺序用最终版正文反向同步对应章纲和章末系统面板。"""
    status = chapter_finalization_status(ws)
    records = status["drafts"].get(f"vol_{volume:02d}", {})
    pending = sorted(
        int(chapter) for chapter, record in records.items()
        if int(chapter) <= through_chapter and record.get("status") != "synced"
    )
    if not pending:
        return []

    outline_dir = os.path.join(ws.file_system, "chapter_outlines", f"vol_{volume:02d}")
    synced = []
    for index, chapter in enumerate(pending):
        if stop_event is not None and stop_event.is_set():
            break
        if pause_event is not None:
            if not pause_event.is_set() and progress_callback:
                progress_callback("paused", index, len(pending), "最终版正文同步已暂停")
            pause_event.wait()
        if stop_event is not None and stop_event.is_set():
            break

        live_status = chapter_finalization_status(ws)
        record = live_status["drafts"].get(f"vol_{volume:02d}", {}).get(str(chapter))
        if not record or record.get("status") == "synced":
            continue
        finalized_draft = _read_file(_draft_chapter_path(ws, volume, chapter))
        if not finalized_draft:
            raise RuntimeError(f"第{chapter}章最终版正文不存在或为空，无法同步。")
        expected_hash = record.get("current_hash") or _content_hash(finalized_draft)
        outline_path = os.path.join(outline_dir, f"chapter_{chapter:03d}.md")
        current_outline = _read_file(outline_path) or "（本章原章纲不存在）"
        previous_panel = _previous_system_panel(ws, volume, chapter)
        if progress_callback:
            progress_callback(
                "syncing_finalized_draft", index, len(pending),
                f"正在用第{chapter}章最终版正文同步章纲",
            )
        prompt = PromptLoader.load(
            "finalized_draft_outline_sync",
            chapter_num=chapter,
            previous_system_panel=json.dumps(previous_panel, ensure_ascii=False, indent=2),
            current_outline=current_outline,
            finalized_draft=finalized_draft,
        )
        while True:
            try:
                synced_outline = normalize_text(
                    _generate_with_cancel(llm, prompt, cancel_event, temperature=0.2)
                )
                break
            except LLMCallCancelled:
                if stop_event is not None and stop_event.is_set():
                    return synced
                if progress_callback:
                    progress_callback(
                        "paused", index, len(pending),
                        f"第{chapter}章正文同步已暂停；继续后重新同步",
                    )
                if pause_event is not None:
                    pause_event.wait()
                if cancel_event is not None:
                    cancel_event.clear()
        if not synced_outline:
            raise RuntimeError(f"第{chapter}章最终版正文未能生成同步章纲。")

        old_panel = _read_json_file(_system_panel_chapter_path(ws, volume, chapter)) or {}
        panel_source = (
            "【最终版正文（本章事实最高优先级）】\n"
            + finalized_draft
            + "\n\n【根据最终版正文同步后的章纲】\n"
            + synced_outline
            + "\n\n【本章旧系统面板（仅供补充栏目；冲突时必须以最终版正文为准）】\n"
            + json.dumps(old_panel, ensure_ascii=False, indent=2)
        )
        if not _update_chapter_system_panel_with_controls(
            llm, ws, volume, chapter, panel_source, index, len(pending),
            progress_callback, pause_event, stop_event, cancel_event,
        ):
            break
        _write_file(outline_path, synced_outline)
        _mark_finalized_draft_synced(ws, volume, chapter, expected_hash)
        synced.append(chapter)
        if progress_callback:
            progress_callback(
                "syncing_finalized_draft", index + 1, len(pending),
                f"第{chapter}章章纲与系统面板已同步",
            )
    return synced


def init_mechanics(ws, force=False, creative_direction=None, direction_file=None,
                   mechanics_file=None, disable=False):
    """初始化可选机制层：none / light_state / explicit_mechanics。"""
    profile_path = _mechanics_path(ws, "system_panel.json")
    if os.path.exists(profile_path) and not force:
        print(f"机制层已存在：{profile_path}")
        print("使用 --force 覆盖。")
        return

    if disable:
        payload = _default_mechanics_disabled("用户显式关闭机制层。")
        _write_mechanics_payload(ws, payload)
        print(f"  -> 已关闭机制层：{profile_path}")
        return

    direction = _load_creative_direction(ws, creative_direction, direction_file)
    mechanics_source = ""
    if mechanics_file:
        mechanics_source = _read_file(mechanics_file) or ""
        if not mechanics_source:
            print(f"错误：机制设定文件不存在或为空：{mechanics_file}")
            return
    elif creative_direction:
        mechanics_source = creative_direction

    assets = _load_story_design_assets(ws)
    llm = _get_llm()
    if not llm:
        return

    print(">>> 初始化机制层 mechanics <<<")
    if mechanics_source:
        print(f"  -> 已加载用户机制设定（{len(mechanics_source)} 字）")
    else:
        print("  -> 未提供用户机制设定，将根据核心玩法自动判断是否启用机制层。")

    prompt = PromptLoader.load(
        "mechanics_init",
        mechanics_source=mechanics_source or "（用户未提供机制设定）",
        creative_direction=direction or "（无额外创作方向）",
        core_gameplay=assets["core_gameplay"],
        long_mainline=assets["long_mainline"],
        stage_roadmap=assets["stage_roadmap"],
        character_arcs=assets["character_arcs"],
    )
    raw = normalize_text(llm.generate(prompt))
    try:
        payload = parse_json_response(raw)
    except Exception as exc:
        print(f"  警告：机制层 JSON 解析失败，默认关闭。原因：{exc}")
        payload = _default_mechanics_disabled("机制层初始化 JSON 解析失败，默认关闭。")
        payload["design"] += "\n\n# 原始返回\n" + raw

    payload = _normalize_mechanics_payload(payload)
    _write_mechanics_payload(ws, payload)
    print(f"  -> 系统面板定义已保存：{_mechanics_path(ws, 'system_panel.json')}")
    print(f"  -> 机制层模式：{payload['profile']['mode']}")


def _gen_core_gameplay(ws, llm, direction, world_knowledge, force=False):
    output_path = _story_design_path(ws, "core_gameplay.md")
    existing = _read_file(output_path)
    if existing and not force:
        print(f"核心玩法文档已存在：{output_path}")
        return existing

    reference_outline = load_reference_novel_outline(ws.reference_outlines)
    return run_step(
        llm=llm,
        folder="core_gameplay_design",
        label="核心玩法文档",
        output_path=output_path,
        prompt_vars=dict(
            creative_direction=direction or "（用户未提供具体方向）",
            reference_outline=reference_outline or "（无参考小说全书大纲）",
            world_knowledge=world_knowledge or "（未提供目标世界知识库）",
            outline_rules=_load_outline_rules(ws),
        ),
    )


def _gen_long_mainline(ws, llm, direction, world_knowledge, force=False):
    output_path = _story_design_path(ws, "long_mainline.md")
    existing = _read_file(output_path)
    if existing and not force:
        print(f"全书长线主线已存在：{output_path}")
        return existing

    reference_outline = load_reference_novel_outline(ws.reference_outlines)
    core_gameplay = _read_file(_story_design_path(ws, "core_gameplay.md")) or "（未生成核心玩法文档）"

    return run_step(
        llm=llm,
        folder="long_mainline_design",
        label="全书长线主线",
        output_path=output_path,
        prompt_vars=dict(
            creative_direction=direction or "（用户未提供具体方向）",
            core_gameplay=core_gameplay,
            reference_outline=reference_outline or "（无参考小说全书大纲）",
            world_knowledge=world_knowledge or "（未提供目标世界知识库）",
        ),
    )


def _gen_stage_roadmap(ws, llm, direction, world_knowledge, force=False):
    output_path = _story_design_path(ws, "stage_roadmap.md")
    existing = _read_file(output_path)
    if existing and not force:
        print(f"舞台路线图已存在：{output_path}")
        return existing

    core_gameplay = _read_file(_story_design_path(ws, "core_gameplay.md")) or "（未生成核心玩法文档）"
    long_mainline = _read_file(_story_design_path(ws, "long_mainline.md")) or "（未生成全书长线主线）"

    result = run_step(
        llm=llm,
        folder="stage_roadmap_design",
        label="全书舞台路线图",
        save=f"  -> 舞台路线图已保存：{output_path}",
        output_path=output_path,
        prompt_vars=dict(
            creative_direction=direction or "（用户未提供具体方向）",
            core_gameplay=core_gameplay,
            long_mainline=long_mainline,
            world_knowledge=world_knowledge or "（未提供目标世界知识库）",
        ),
    )
    # 规整为稳定的舞台标题格式（一级「# 舞台N：名称」），避免后续步骤识别不到舞台。
    result = _normalize_stage_roadmap(result)
    if result:
        _write_file(output_path, result)
    return result


def _gen_character_arcs(ws, llm, direction, world_knowledge, force=False):
    output_path = _story_design_path(ws, "character_arcs.md")
    existing = _read_file(output_path)
    if existing and not force:
        print(f"角色成长线已存在：{output_path}")
        return existing

    core_gameplay = _read_file(_story_design_path(ws, "core_gameplay.md")) or "（未生成核心玩法文档）"
    long_mainline = _read_file(_story_design_path(ws, "long_mainline.md")) or "（未生成全书长线主线）"
    stage_roadmap = _read_file(_story_design_path(ws, "stage_roadmap.md")) or "（未生成舞台路线图）"

    return run_step(
        llm=llm,
        folder="character_arcs_design",
        label="角色成长线",
        output_path=output_path,
        prompt_vars=dict(
            creative_direction=direction or "（用户未提供具体方向）",
            core_gameplay=core_gameplay,
            long_mainline=long_mainline,
            stage_roadmap=stage_roadmap,
            world_knowledge=world_knowledge or "（未提供目标世界知识库）",
        ),
    )


def _load_reference_context(ws):
    return load_reference_novel_outline(ws.reference_outlines) or "（无参考小说全书大纲）"


def _reference_volume_structure_context(ws, per_volume_chars=1800, max_chars=36000):
    """仅提取各卷的卷纲概览与三幕结构，作为新书阶段粗纲的结构参考。

    不拼接人物、伏笔、设定等其他板块，避免长篇参考资料挤占新书世界观和
    粗略大纲的上下文。单卷与总体长度均设上限。
    """
    volumes = list_reference_volumes(ws.reference_outlines)
    # 卷数很多时按卷均分预算，宁可每卷更短，也不能漏掉后半部卷纲。
    volume_budget = max(
        450,
        min(per_volume_chars, max_chars // max(1, len(volumes)) - 120),
    )
    overview_budget = max(180, int(volume_budget * 0.35))
    three_acts_budget = max(250, volume_budget - overview_budget)
    parts = []
    used = 0
    for volume in volumes:
        content = load_reference_volume_outline(ws.reference_outlines, volume["vol_idx"]) or ""
        if not content:
            continue
        sections = {}
        matches = list(re.finditer(r"(?m)^#\s+(.+?)\s*$", content))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
            title = re.sub(
                r"^\s*(?:[一二三四五六七八九十百]+|\d+)\s*[、.．：:]\s*",
                "",
                match.group(1).strip(),
            )
            sections[title] = content[match.start():end].strip()

        selected = []
        overview = sections.get("卷纲概览", "")
        three_acts = sections.get("三幕结构", "")
        if overview:
            selected.append(overview[:overview_budget].rstrip())
        if three_acts:
            selected.append(three_acts[:three_acts_budget].rstrip())
        selected_text = "\n\n".join(part for part in selected if part).strip()
        if len(selected_text) > volume_budget:
            selected_text = selected_text[:volume_budget].rstrip()
        if not selected:
            selected_text = "（该卷未识别到卷纲概览或三幕结构）"

        meta = _read_file(os.path.join(volume["dir_path"], "meta.json"))
        chapter_range = ""
        if meta:
            try:
                meta_data = json.loads(meta)
                start_ch = int(meta_data.get("start_ch") or 0)
                end_ch = int(meta_data.get("end_ch") or 0)
                if start_ch > 0 and end_ch >= start_ch:
                    chapter_range = f"｜第{start_ch}-{end_ch}章"
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        part = (
            f"## 参考卷{volume['vol_idx']}：{volume['title']}{chapter_range}\n\n"
            + selected_text
        )
        parts.append(part)
        used += len(part)
    return "\n\n---\n\n".join(parts) or "（未找到参考小说分卷卷纲）"


def _reference_volume_stage_structure(ws, volume):
    """读取单卷完整的“卷纲概览 + 三幕结构”，供末尾阶段增量同步。"""
    content = load_reference_volume_outline(
        ws.reference_outlines, volume["vol_idx"]
    ) or ""
    sections = {}
    matches = list(re.finditer(r"(?m)^#\s+(.+?)\s*$", content))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        title = re.sub(
            r"^\s*(?:[一二三四五六七八九十百]+|\d+)\s*[、.．：:]\s*",
            "",
            match.group(1).strip(),
        )
        sections[title] = content[match.start():end].strip()
    selected = [sections.get("卷纲概览", ""), sections.get("三幕结构", "")]
    return "\n\n".join(item for item in selected if item).strip() or "（对应参考卷缺少卷纲概览与三幕结构）"


def _design_structure_guidance(ws):
    """新书阶段数与参考卷数一一对应；无参考分卷时使用兜底范围。"""
    volume_count = len(list_reference_volumes(ws.reference_outlines))
    if volume_count == 0:
        stage_min, stage_max = 5, 7
    else:
        stage_min = stage_max = volume_count
    map_min = max(3, math.ceil(stage_min * 0.75))
    map_max = max(map_min + 2, stage_max)
    return {
        "reference_volume_count": volume_count,
        "stage_range": str(stage_min) if stage_min == stage_max else f"{stage_min}-{stage_max}",
        "stage_min": stage_min,
        "stage_max": stage_max,
        "map_range": f"{map_min}-{map_max}",
        "map_min": map_min,
        "map_max": map_max,
    }


def _design_structure_counts(rough, worldview):
    chinese_number = r"[一二三四五六七八九十百]+"
    arabic_or_chinese = rf"(?:\d+|{chinese_number})"
    stage_patterns = (
        # ## 阶段1 / ### 阶段一 / ## 第八阶段
        rf"(?m)^\s*#{{2,6}}\s*(?:第\s*)?(?:阶段\s*{arabic_or_chinese}|{arabic_or_chinese}\s*阶段)\b",
        # 1. 阶段一 / - 第八阶段（模型偶尔不用子标题）
        rf"(?m)^\s*(?:[-*+]|\d+[.、．])\s*(?:第\s*)?(?:阶段\s*{arabic_or_chinese}|{arabic_or_chinese}\s*阶段)\b",
    )
    stage_lines = set()
    for pattern in stage_patterns:
        stage_lines.update(match.group(0).strip() for match in re.finditer(pattern, rough or ""))
    stage_count = len(stage_lines)
    map_text = ""
    worldview_lines = (worldview or "").splitlines()
    for index, line in enumerate(worldview_lines):
        heading = re.match(r"^(#{1,6})\s*(.+?)\s*$", line.strip())
        if not heading:
            continue
        heading_title = re.sub(r"^\s*6\s*[.、．:]?\s*", "", heading.group(2)).strip()
        is_map_heading = (
            "地图" in heading_title
            and any(word in heading_title for word in ("舞台", "区域", "版图"))
            and any(word in heading_title for word in ("层级", "层次", "体系", "结构"))
        )
        if not is_map_heading:
            continue
        heading_level = len(heading.group(1))
        body = []
        for following in worldview_lines[index + 1:]:
            next_heading = re.match(r"^(#{1,6})\s+\S", following.strip())
            if next_heading and len(next_heading.group(1)) <= heading_level:
                break
            body.append(following)
        map_text = "\n".join(body)
        break
    map_count = len(re.findall(r"(?m)^\s*(?:[-*+]|\d+[.、．])\s+\S+", map_text))
    if not map_count:
        map_count = len(re.findall(r"(?m)^##+\s+\S+", map_text))
    if not map_count:
        map_count = len(re.findall(
            rf"(?m)^\s*(?:层级|地图|舞台)\s*{arabic_or_chinese}\s*[：:]|"
            rf"^\s*第\s*{arabic_or_chinese}\s*(?:层|级|区域|舞台)\s*[：:]",
            map_text,
        ))
    if not map_count and map_text:
        # 兼容模型把多个层级写在同一段、用分号分隔的情况。
        labels = re.findall(
            rf"(?:层级|地图|舞台)\s*{arabic_or_chinese}\s*[：:]|"
            rf"第\s*{arabic_or_chinese}\s*(?:层|级|区域|舞台)\s*[：:]",
            map_text,
        )
        map_count = len(labels)
    return stage_count, map_count


def _remove_stage_outline_section(rough):
    """确保 rough_outline.md 不再夹带阶段粗纲；阶段内容由独立文件维护。"""
    lines = (rough or "").splitlines()
    output = []
    skipping = False
    skipped_level = 0
    for line in lines:
        heading = re.match(r"^\s*(#{1,6})\s+(.+?)\s*$", line)
        if heading and "阶段粗纲" in heading.group(2):
            skipping = True
            skipped_level = len(heading.group(1))
            continue
        if skipping:
            if heading and len(heading.group(1)) <= skipped_level:
                skipping = False
            else:
                continue
        output.append(line)
    return "\n".join(output).strip()


def _stage_outline_sections(stage_outline):
    """把独立阶段粗纲拆为 {阶段编号: 完整阶段文本}。"""
    headings = list(STAGE_OUTLINE_HEADING_RE.finditer(stage_outline or ""))
    sections = {}
    for index, heading in enumerate(headings):
        number = int(heading.group(1))
        end = headings[index + 1].start() if index + 1 < len(headings) else len(stage_outline)
        sections[number] = (stage_outline or "")[heading.start():end].strip()
    return sections


def _completed_stage_prefix(stage_roadmap, target_count):
    """只保留从舞台1开始连续存在的前缀，后续舞台必须基于此前缀串行生成。"""
    parts = []
    for number in range(1, target_count + 1):
        content = _extract_stage_from_roadmap(stage_roadmap, number)
        if not content or not _is_volume_style_stage(content):
            break
        parts.append(content)
    return parts


def _is_volume_style_stage(content):
    required = ("卷纲概览", "三幕结构", "人物谱系", "伏笔追踪", "核心爽点")
    return (
        all(name in (content or "") for name in required)
        and bool(re.search(r"预计章节数\s*[：:]\s*\d+", content or ""))
    )


def _reference_volume_chapter_count(volume, volume_outline):
    """返回参考卷的实际章节规模，优先使用分卷边界元数据。"""
    meta = _read_json_file(os.path.join(volume.get("dir_path") or "", "meta.json")) or {}
    try:
        start = int(meta.get("start_ch") or 0)
        end = int(meta.get("end_ch") or 0)
    except (TypeError, ValueError):
        start = end = 0
    if start > 0 and end >= start:
        return end - start + 1

    # 旧工作区没有 meta.json 时，从卷纲三幕章节区间反推。
    ranges = re.findall(
        r"第\s*(\d+)\s*章?\s*(?:至|到|[-—~])\s*第?\s*(\d+)\s*章",
        volume_outline or "",
    )
    if ranges:
        starts = [min(int(left), int(right)) for left, right in ranges]
        ends = [max(int(left), int(right)) for left, right in ranges]
        return max(ends) - min(starts) + 1

    try:
        fallback = int(volume.get("chapter_count") or 0)
    except (TypeError, ValueError):
        fallback = 0
    if fallback > 0:
        return fallback
    raise RuntimeError(
        f"无法从参考卷{volume.get('vol_idx') or ''}的分卷元数据或三幕结构"
        "推导章节数，请先补全参考卷纲。"
    )


def gen_design_concept(
    ws, force=False, creative_direction=None, direction_file=None,
    progress_callback=None,
):
    """串行生成世界观、无阶段粗纲的 rough_outline，以及独立 stage_outline。"""
    print(">>> 全书设计：串行生成世界观、粗略大纲与阶段粗纲 <<<")
    direction = _load_creative_direction(ws, creative_direction, direction_file)
    record_creative_direction(ws, direction, "initial")

    rough_path = _rough_outline_path(ws)
    worldview_path = _worldview_path(ws)
    stage_outline_path = _stage_outline_path(ws)
    existing_rough = _read_file(rough_path)
    existing_worldview = _read_file(worldview_path)
    existing_stage_outline = _read_file(stage_outline_path)

    def report(phase, completed, detail):
        if progress_callback:
            progress_callback(phase, completed, 3, detail)
    structure_guidance = _design_structure_guidance(ws)
    expected_existing_stages = structure_guidance["reference_volume_count"]
    existing_stage_count, _ = _design_structure_counts(existing_stage_outline, "")
    existing_stage_valid = _is_real_design_field(existing_stage_outline) and (
        expected_existing_stages == 0
        or existing_stage_count == expected_existing_stages
    )
    if _is_real_design_field(existing_stage_outline) and not existing_stage_valid:
        print(
            f"  -> 已有阶段粗纲为 {existing_stage_count} 个阶段，"
            f"与参考小说 {expected_existing_stages} 卷不一致，将重新生成阶段粗纲。"
        )
        existing_stage_outline = ""
    if (
        not force
        and _is_real_design_field(existing_rough)
        and _is_real_design_field(existing_worldview)
        and existing_stage_valid
    ):
        print("  -> 世界观、粗略大纲与阶段粗纲已存在，跳过生成（使用 --force 覆盖，或用微调对话调整）。")
        return {
            "worldview": existing_worldview,
            "rough_outline": existing_rough,
            "stage_outline": existing_stage_outline,
        }

    # 全书设计属于核心创作任务，使用用户配置的 ADAPTIVE_BUILDER（pro）模型。
    llm = _get_llm()
    if not llm:
        return {}
    reference_outline = _load_reference_context(ws)

    # 每一步生成后立即落盘。后一步失败时可直接复用前一步，避免重新发送长上下文。
    worldview = existing_worldview if not force else ""
    report("worldview", 0, "正在生成新小说世界观")
    if not _is_real_design_field(worldview):
        # 目标世界资料是世界观生成的事实边界；参考小说只提供结构功能。
        # 控制在 6 万字符内，避免与参考全书大纲叠加后挤占模型上下文。
        world_knowledge = _load_world_knowledge_optional(
            ws, "新小说世界观", max_chars=60000, require_ready=True,
        )
        prompt = PromptLoader.load(
            "design_worldview",
            creative_direction=direction or "（用户未提供具体方向）",
            world_knowledge=world_knowledge or "（未提供目标世界资料库，请创建原创世界。）",
            reference_outline=reference_outline,
        )
        payload = parse_json_response(_call_design_llm(llm, prompt, "新小说世界观"))
        worldview = _normalize_design_field(payload, "worldview_md", "# 世界观")
        if not _is_real_design_field(worldview):
            raise RuntimeError("世界观生成失败：模型未返回有效内容，请重试。")
        _write_file(worldview_path, worldview)
        print(f"  -> 世界观已保存：{worldview_path}")
    else:
        print("  -> 复用已生成的世界观。")
    report("worldview_complete", 1, "世界观已生成，正在生成粗略大纲")

    rough = existing_rough if not force else ""
    if not _is_real_design_field(rough):
        prompt = PromptLoader.load(
            "design_rough_outline",
            creative_direction=direction or "（用户未提供具体方向）",
            worldview=worldview,
            reference_outline=reference_outline,
            outline_rules=_load_outline_rules(ws),
        )
        payload = parse_json_response(_call_design_llm(llm, prompt, "新小说粗略大纲"))
        rough = _normalize_design_field(payload, "rough_outline_md", "# 粗略大纲")
        rough = _remove_stage_outline_section(rough)
        if not _is_real_design_field(rough):
            raise RuntimeError("粗略大纲生成失败：模型未返回有效内容，请重试。")
        _write_file(rough_path, rough)
        print(f"  -> 粗略大纲已保存：{rough_path}")
    else:
        print("  -> 复用已生成的粗略大纲。")
    report("rough_outline_complete", 2, "粗略大纲已生成，正在生成阶段粗纲")

    stage_outline = existing_stage_outline if not force else ""
    if not _is_real_design_field(stage_outline):
        base_prompt = PromptLoader.load(
            "design_stage_outline",
            worldview=worldview,
            rough_outline=rough,
            reference_volume_structures=_reference_volume_structure_context(ws),
            **structure_guidance,
        )
        expected_count = structure_guidance["reference_volume_count"]
        actual_count = 0
        for attempt in range(1, 3):
            prompt = base_prompt
            if attempt > 1:
                prompt += (
                    "\n\n【上次输出未通过数量校验】\n"
                    f"上次生成了 {actual_count} 个阶段，本次必须严格生成 {expected_count} 个阶段。"
                )
            payload = parse_json_response(
                _call_design_llm(llm, prompt, f"新小说阶段粗纲（第{attempt}次）")
            )
            candidate = _normalize_design_field(payload, "stage_outline_md", "# 阶段粗纲")
            if not _is_real_design_field(candidate):
                continue
            actual_count, _ = _design_structure_counts(candidate, "")
            if expected_count == 0 or actual_count == expected_count:
                stage_outline = candidate
                break
            print(
                f"  -> 阶段数量校验未通过：生成 {actual_count} 个，"
                f"应为 {expected_count} 个，自动重试。"
            )
        if not _is_real_design_field(stage_outline) or (
            expected_count > 0 and actual_count != expected_count
        ):
            raise RuntimeError(
                f"阶段粗纲生成失败：应生成 {expected_count} 个阶段，"
                f"模型实际生成 {actual_count} 个；未写入文件，请重试。"
            )
        _write_file(stage_outline_path, stage_outline)
        print(f"  -> 阶段粗纲已保存：{stage_outline_path}")
    else:
        print("  -> 复用已生成的阶段粗纲。")
    report("stage_outline_complete", 3, "世界观、粗略大纲和阶段粗纲已全部生成")

    stage_count, map_count = _design_structure_counts(stage_outline, worldview)
    structure_warning = ""
    expected_stage_count = structure_guidance["reference_volume_count"]
    stage_invalid = (
        stage_count != expected_stage_count
        if expected_stage_count > 0
        else stage_count < structure_guidance["stage_min"]
    )
    if stage_invalid or map_count < structure_guidance["map_min"]:
        structure_warning = (
            "结构覆盖可能不足："
            f"阶段 {stage_count}/{structure_guidance['stage_min']}，"
            f"地图 {map_count}/{structure_guidance['map_min']}。"
        )
        print(f"  警告：{structure_warning}")
    _mark_reference_chapters_used(ws, [card["chapter"] for card in _reference_chapter_cards(ws)])
    _record_story_design_reference_snapshot(ws, reset_extensions=True)
    _mark_concept_revision(ws)
    result = {
        "worldview": worldview,
        "rough_outline": rough,
        "stage_outline": stage_outline,
    }
    if structure_warning:
        result["structure_warning"] = structure_warning
        result["adjustment_note"] = structure_warning
    return result


def gen_stage_design(
    ws, force=False, creative_direction=None, direction_file=None,
    progress_callback=None, cancel_event=None,
):
    """先生成长线主线，再按阶段与对应参考卷纲串行生成舞台路线图。"""
    print(">>> 第二阶段：先生成长线主线，再串行生成舞台路线图 <<<")
    rough = _read_file(_rough_outline_path(ws))
    worldview = _read_file(_worldview_path(ws))
    stage_outline = _read_file(_stage_outline_path(ws))
    stage_sections = _stage_outline_sections(stage_outline)
    reference_volumes = list_reference_volumes(ws.reference_outlines)
    total_stages = len(stage_sections)

    def report(phase, completed, detail):
        if progress_callback:
            progress_callback(phase, completed, max(1, total_stages), detail)

    if not rough or not worldview or not stage_outline:
        print("错误：请先完成全书设计（世界观、粗略大纲与阶段粗纲），再执行舞台设计。")
        return {}
    if len(stage_sections) != len(reference_volumes):
        raise RuntimeError(
            f"阶段粗纲与参考卷数不一致：阶段 {len(stage_sections)} 个，"
            f"参考卷 {len(reference_volumes)} 卷。请先重新生成阶段粗纲。"
        )

    direction = _load_creative_direction(ws, creative_direction, direction_file)
    record_creative_direction(ws, direction, "stage_design")
    long_path = _story_design_path(ws, "long_mainline.md")
    stage_path = _story_design_path(ws, "stage_roadmap.md")
    existing_long = _read_file(long_path)
    existing_stage = _read_file(stage_path)
    design_state = _load_story_design_state(ws)
    if int(design_state.get("stage_pipeline_version") or 0) != STAGE_DESIGN_PIPELINE_VERSION:
        existing_long = ""
        existing_stage = ""
        print("  -> 检测到旧版舞台设计产物，将按新的串行流程重新生成。")

    # 舞台设计属于核心创作任务，使用用户配置的 Pro 模型。
    llm = _get_llm()
    if not llm:
        return {}

    report("long_mainline", 0, "正在生成全书长线主线")
    long_mainline = existing_long if not force else ""
    long_generated = False
    if not _is_real_design_field(long_mainline):
        prompt = PromptLoader.load(
            "long_mainline_serial",
            worldview=worldview,
            rough_outline=rough,
            stage_outline=stage_outline,
        )
        payload = parse_json_response(
            _call_design_llm(llm, prompt, "全书长线主线", cancel_event=cancel_event)
        )
        long_mainline = _normalize_design_field(payload, "long_mainline_md", "# 全书长线主线")
        if not _is_real_design_field(long_mainline):
            raise RuntimeError("长线主线生成失败：模型未返回有效内容，请重试。")
        _write_file(long_path, long_mainline)
        design_state = _load_story_design_state(ws)
        design_state["stage_pipeline_version"] = STAGE_DESIGN_PIPELINE_VERSION
        design_state["stage_pipeline_updated_at"] = datetime.now().isoformat(timespec="seconds")
        _write_json_file(_story_design_state_path(ws), design_state)
        long_generated = True
        print(f"  -> 长线主线已保存：{long_path}")
    else:
        print("  -> 复用已生成的长线主线。")
    report(
        "long_mainline_complete", 0,
        f"长线主线已生成，正在准备舞台1/{total_stages}",
    )

    # 强制重建或长线刚重新生成时，从舞台1开始；服务重启后的普通重试则复用连续前缀。
    completed_parts = [] if (force or long_generated) else _completed_stage_prefix(
        existing_stage, len(stage_sections)
    )
    if completed_parts:
        print(f"  -> 检测到已连续生成 {len(completed_parts)}/{len(stage_sections)} 个舞台，从断点继续。")
        report(
            "stage_resume", len(completed_parts),
            f"已保留 {len(completed_parts)}/{total_stages} 个舞台，正在从断点继续",
        )
    if len(completed_parts) == len(stage_sections):
        stage_roadmap = "\n\n".join(completed_parts)
        print("  -> 舞台路线图已完整生成，跳过。")
    else:
        # 先写回可信的连续前缀，丢弃缺口之后无法保证串行依赖的旧内容。
        if completed_parts:
            _write_file(stage_path, "\n\n".join(completed_parts))
        elif os.path.exists(stage_path):
            _write_file(stage_path, "")

        for number in range(len(completed_parts) + 1, len(stage_sections) + 1):
            report(
                "stage_generating", number - 1,
                f"正在生成舞台{number}/{total_stages}",
            )
            volume = reference_volumes[number - 1]
            reference_volume_outline = load_reference_volume_outline(
                ws.reference_outlines, volume["vol_idx"]
            ) or "（对应参考卷纲缺失）"
            reference_chapter_count = _reference_volume_chapter_count(
                volume, reference_volume_outline,
            )
            previous_stage = completed_parts[-1] if completed_parts else "（这是第一个舞台，无上一舞台）"
            prompt = PromptLoader.load(
                "stage_roadmap_serial",
                stage_number=number,
                total_stages=len(stage_sections),
                long_mainline=long_mainline,
                current_stage_outline=stage_sections[number],
                reference_volume_number=volume["vol_idx"],
                reference_volume_title=volume["title"],
                reference_chapter_count=reference_chapter_count,
                reference_volume_outline=reference_volume_outline,
                previous_stage=previous_stage,
            )
            payload = parse_json_response(
                _call_design_llm(
                    llm, prompt, f"舞台{number}/{len(stage_sections)}",
                    cancel_event=cancel_event,
                )
            )
            stage = _normalize_design_field(payload, "stage_roadmap_md", "")
            stage = _normalize_stage_roadmap(stage)
            numbers = [int(value) for value in STAGE_HEADING_RE.findall(stage)]
            if numbers != [number]:
                raise RuntimeError(
                    f"舞台{number}生成结果编号无效（检测到 {numbers or '无编号'}），"
                    "已保留此前舞台，请重试继续。"
                )
            required_sections = ("卷纲概览", "三幕结构", "人物谱系", "伏笔追踪", "核心爽点")
            missing_sections = [name for name in required_sections if name not in stage]
            if not _is_volume_style_stage(stage):
                raise RuntimeError(
                    f"舞台{number}格式不完整：缺少"
                    + ("、".join(missing_sections) if missing_sections else "预计章节数")
                    + "。已保留此前舞台，请重试继续。"
                )
            completed_parts.append(stage)
            stage_roadmap = "\n\n".join(completed_parts)
            _write_file(stage_path, stage_roadmap)
            mapped_arc_paths = []
            for arc in list_reference_story_arcs(ws.reference_outlines, volume["vol_idx"]):
                try:
                    mapped_arc_paths.append(os.path.relpath(arc["path"], ws.reference_outlines))
                except ValueError:
                    mapped_arc_paths.append(arc["path"])
            if mapped_arc_paths:
                _mark_arcs_used(ws, mapped_arc_paths, [number])
            print(f"  -> 舞台{number}已保存（{number}/{len(stage_sections)}）：{stage_path}")
            report(
                "stage_complete", number,
                (
                    f"舞台{number}/{total_stages}已生成，正在生成舞台{number + 1}/{total_stages}"
                    if number < total_stages else
                    f"全部 {total_stages} 个舞台已生成"
                ),
            )

    stage_roadmap = "\n\n".join(completed_parts) if completed_parts else ""
    if not _is_real_design_field(stage_roadmap):
        raise RuntimeError("舞台路线图生成失败：未生成有效舞台内容。")
    _mark_stage_design_synced(ws)
    report(
        "name_synopsis", total_stages,
        "舞台路线图已生成，正在生成书名与简介",
    )
    name_synopsis = gen_novel_name_synopsis(
        ws, force=True, cancel_event=cancel_event,
    )
    print(f"  -> 舞台路线图已保存：{stage_path}")
    report("completed", total_stages, f"全部 {total_stages} 个舞台已生成")
    return {
        "long_mainline": long_mainline,
        "stage_roadmap": stage_roadmap,
        "name_synopsis": name_synopsis,
    }


def refine_design_concept(ws, instruction, compact_summary="", use_new_reference=False):
    """普通全书设计微调：模型只读取指令和当前三份设计文件。"""
    if use_new_reference:
        return sync_stage_outline_from_new_reference(ws, instruction)
    _ = compact_summary  # 保留调用签名兼容，历史摘要不再进入模型。
    paths = {
        "worldview": _worldview_path(ws),
        "rough_outline": _rough_outline_path(ws),
        "stage_outline": _stage_outline_path(ws),
    }
    current = {key: _read_file(path) for key, path in paths.items()}
    if not all(current.values()):
        raise RuntimeError("请先完成世界观、粗略大纲与阶段粗纲。")
    llm = _get_llm()
    if not llm:
        raise RuntimeError("未配置可用模型。")
    prompt = PromptLoader.load(
        "design_concept_refine",
        instruction=instruction,
        worldview=current["worldview"],
        rough_outline=current["rough_outline"],
        stage_outline=current["stage_outline"],
    )
    payload = parse_json_response(_call_design_llm(llm, prompt, "concept 微调"))
    updated = {
        "worldview": _normalize_design_field(payload, "worldview_md", ""),
        "rough_outline": _remove_stage_outline_section(
            _normalize_design_field(payload, "rough_outline_md", "")
        ),
        "stage_outline": _normalize_design_field(payload, "stage_outline_md", ""),
    }
    if not all(updated.values()):
        raise RuntimeError("全书设计调整未返回完整的三份设计文件。")
    before_count, _ = _design_structure_counts(current["stage_outline"], "")
    after_count, _ = _design_structure_counts(updated["stage_outline"], "")
    if before_count != after_count:
        raise RuntimeError(
            f"普通全书调整不能改变阶段数量：调整前 {before_count} 个，调整后 {after_count} 个。"
        )
    _backup_design_files(ws, "concept", paths)
    for key, path in paths.items():
        _write_file(path, updated[key])
    _mark_concept_revision(ws)
    updated["adjustment_note"] = str(payload.get("adjustment_note") or "").strip()
    return updated


def sync_stage_outline_from_new_reference(ws, instruction=""):
    """仅用新增拆解内容调整末阶段或追加新阶段，不触碰世界观与粗略大纲。"""
    _ = instruction  # 保留对话入口签名；增量生成严格使用固定结构输入。
    new_cards = _unused_reference_chapter_context(ws)
    if not new_cards:
        raise ValueError("没有检测到尚未被阶段粗纲使用的新增拆解章节。")
    stage_path = _stage_outline_path(ws)
    stage_outline = _read_file(stage_path)
    sections = _stage_outline_sections(stage_outline)
    reference_volumes = list_reference_volumes(ws.reference_outlines)
    if not sections:
        raise RuntimeError("当前阶段粗纲为空，请先完成初版全书设计。")
    if not reference_volumes:
        raise RuntimeError("未找到参考小说分卷结构。")
    if len(reference_volumes) < len(sections):
        raise RuntimeError(
            f"参考小说当前只有 {len(reference_volumes)} 卷，但阶段粗纲已有 {len(sections)} 个阶段，"
            "无法安全执行末尾增量同步。"
        )

    llm = _get_llm()
    if not llm:
        raise RuntimeError("未配置可用模型。")
    original_stage_outline = stage_outline
    worldview = _read_file(_worldview_path(ws))
    rough_outline = _read_file(_rough_outline_path(ws))
    if not worldview or not rough_outline:
        raise RuntimeError("请先完成新小说世界观与粗略大纲。")
    old_count = len(sections)
    target_count = len(reference_volumes)
    start_number = old_count if target_count == old_count else old_count + 1
    operation_for_first = "调整最后阶段" if target_count == old_count else "新增阶段"

    for number in range(start_number, target_count + 1):
        sections = _stage_outline_sections(stage_outline)
        operation = operation_for_first if number == start_number else "新增阶段"
        volume = reference_volumes[number - 1]
        reference_structure = _reference_volume_stage_structure(ws, volume)
        if operation == "调整最后阶段":
            stage_context = (
                "【倒数第二个阶段】\n"
                + (sections.get(number - 1) or "（这是第一阶段，无倒数第二阶段）")
                + "\n\n【当前最后一个阶段】\n"
                + sections[number]
            )
        else:
            stage_context = "【当前最后一个阶段】\n" + sections[number - 1]
        prompt = PromptLoader.load(
            "design_stage_outline_incremental",
            operation=operation,
            stage_number=number,
            worldview=worldview,
            rough_outline=rough_outline,
            stage_context=stage_context,
            reference_volume_structure=reference_structure,
        )
        payload = parse_json_response(
            _call_design_llm(llm, prompt, f"增量同步阶段粗纲{number}/{target_count}")
        )
        candidate = _normalize_design_field(payload, "stage_outline_md", "")
        numbers = [int(value) for value in STAGE_OUTLINE_HEADING_RE.findall(candidate)]
        if numbers != [number]:
            raise RuntimeError(
                f"阶段粗纲增量结果编号无效：期望阶段{number}，检测到 {numbers or '无编号'}。"
            )
        if operation == "调整最后阶段":
            heading = list(STAGE_OUTLINE_HEADING_RE.finditer(stage_outline))[-1]
            stage_outline = stage_outline[:heading.start()].rstrip() + "\n\n" + candidate.strip()
        else:
            stage_outline = stage_outline.rstrip() + "\n\n" + candidate.strip()

    _backup_design_files(ws, "concept_stage_increment", {"stage_outline": stage_path})
    _write_file(stage_path, stage_outline)
    _mark_reference_chapters_used(ws, [number for number, _ in new_cards])
    revision = _mark_concept_revision(ws)
    state = _load_story_design_state(ws)
    state["pending_reference_stage_sync"] = True
    state["reference_stage_increment"] = {
        "concept_revision": revision,
        "kind": "adjust_last" if target_count == old_count else "append",
        "previous_stage_count": old_count,
        "current_stage_count": target_count,
        "reference_chapters": [number for number, _ in new_cards],
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    _write_json_file(_story_design_state_path(ws), state)
    operation_note = (
        f"已根据新增拆解章节调整最后一个阶段（阶段{old_count}）。"
        if target_count == old_count else
        f"参考小说由 {old_count} 卷扩展为 {target_count} 卷，已追加阶段{old_count + 1}-{target_count}。"
    )
    return {
        "stage_outline": stage_outline,
        "adjustment_note": operation_note,
        "used_reference_chapters": [number for number, _ in new_cards],
        "previous_stage_outline": original_stage_outline,
    }


def refine_stage_design(
    ws, instruction, compact_summary="", cancel_event=None,
    progress_callback=None, pause_event=None, stop_event=None,
):
    """先路由最早受影响舞台，再保留前缀并串行重生成其余舞台。"""
    _ = compact_summary  # 保留调用签名兼容，历史摘要不再进入模型。
    long_path = _story_design_path(ws, "long_mainline.md")
    stage_path = _story_design_path(ws, "stage_roadmap.md")
    long_mainline = _read_file(long_path)
    original_roadmap = _read_file(stage_path)
    stage_outline = _read_file(_stage_outline_path(ws))
    stage_sections = _stage_outline_sections(stage_outline)
    reference_volumes = list_reference_volumes(ws.reference_outlines)
    total_stages = len(stage_sections)
    if not long_mainline or not original_roadmap or not stage_sections:
        raise RuntimeError("请先生成长线主线、阶段粗纲与舞台路线图。")
    if total_stages != len(reference_volumes):
        raise RuntimeError(
            f"阶段粗纲与参考卷数不一致：阶段 {total_stages} 个，"
            f"参考卷 {len(reference_volumes)} 卷。请先同步阶段粗纲。"
        )
    original_parts = [
        _extract_stage_from_roadmap(original_roadmap, number)
        for number in range(1, total_stages + 1)
    ]
    if not all(original_parts):
        raise RuntimeError("当前舞台路线图结构不完整，请先继续生成缺失舞台。")
    llm = _get_llm()
    if not llm:
        raise RuntimeError("未配置可用模型。")

    def report(phase, completed, detail):
        if progress_callback:
            progress_callback(phase, completed, max(1, total_stages), detail)

    def stopped_result(completed_parts):
        return {
            "long_mainline": _read_file(long_path) or long_mainline,
            "stage_roadmap": _read_file(stage_path) or original_roadmap,
            "adjustment_note": "已结束本轮舞台调整，已完成内容均已保留。",
            "stopped": True,
        }

    def controlled_call(prompt, label, completed, paused_message):
        while True:
            if stop_event is not None and stop_event.is_set():
                return None
            if pause_event is not None and not pause_event.is_set():
                report("paused", completed, paused_message)
                pause_event.wait()
                if stop_event is not None and stop_event.is_set():
                    return None
                if cancel_event is not None:
                    cancel_event.clear()
            try:
                return _call_design_llm(
                    llm, prompt, label, cancel_event=cancel_event,
                )
            except LLMCallCancelled:
                if stop_event is not None and stop_event.is_set():
                    return None
                report("paused", completed, paused_message)
                if pause_event is not None:
                    pause_event.wait()
                if stop_event is not None and stop_event.is_set():
                    return None
                if cancel_event is not None:
                    cancel_event.clear()

    report("routing", 0, "正在判断最早受影响的舞台")
    route_prompt = PromptLoader.load(
        "stage_design_refine_route",
        instruction=instruction,
        long_mainline=long_mainline,
        stage_roadmap=original_roadmap,
    )
    route_raw = controlled_call(
        route_prompt, "舞台调整范围路由", 0,
        "范围分析已暂停；点击继续后重新分析",
    )
    if route_raw is None:
        return stopped_result(original_parts)
    routed = parse_json_response(route_raw)
    if not isinstance(routed, dict):
        routed = {}
    try:
        start_stage = int(routed.get("start_stage") or 1)
    except (TypeError, ValueError):
        start_stage = 1
    explicit_stages = [
        int(value) for value in re.findall(r"舞台\s*0*(\d+)", instruction or "")
        if 1 <= int(value) <= total_stages
    ]
    if explicit_stages:
        start_stage = min(explicit_stages)
    start_stage = min(total_stages, max(1, start_stage))
    mode = str(routed.get("mode") or "").strip().lower()
    if mode not in {"regenerate", "revise"}:
        mode = (
            "regenerate"
            if re.search(r"重新生成|完全重写|推倒重来|全部重写", instruction or "")
            else "revise"
        )
    update_long_mainline = routed.get("update_long_mainline") is True
    reason = str(routed.get("reason") or "按用户指令定位最早受影响舞台。")

    _backup_design_files(ws, "stage", {
        "long_mainline": long_path,
        "stage_roadmap": stage_path,
    })
    if update_long_mainline:
        report("long_mainline_refine", start_stage - 1, "正在调整全书长线主线")
        long_prompt = PromptLoader.load(
            "stage_long_mainline_refine",
            instruction=instruction,
            long_mainline=long_mainline,
        )
        long_raw = controlled_call(
            long_prompt, "长线主线调整", start_stage - 1,
            "长线主线调整已暂停；点击继续后重新生成",
        )
        if long_raw is None:
            return stopped_result(original_parts)
        long_payload = parse_json_response(long_raw)
        updated_long = _normalize_design_field(long_payload, "long_mainline_md", "")
        if not updated_long:
            raise RuntimeError("长线主线调整未返回有效内容，本轮舞台尚未改写。")
        long_mainline = updated_long
        _write_file(long_path, long_mainline)

    completed_parts = original_parts[:start_stage - 1]

    for number in range(start_stage, total_stages + 1):
        if stop_event is not None and stop_event.is_set():
            return stopped_result(completed_parts)
        report(
            "stage_refining", number - 1,
            f"正在调整舞台{number}/{total_stages}",
        )
        volume = reference_volumes[number - 1]
        reference_volume_outline = load_reference_volume_outline(
            ws.reference_outlines, volume["vol_idx"]
        ) or "（对应参考卷纲缺失）"
        reference_chapter_count = _reference_volume_chapter_count(
            volume, reference_volume_outline,
        )
        previous_stage = completed_parts[-1] if completed_parts else "（这是第一个舞台，无上一舞台）"
        current_stage = (
            original_parts[number - 1]
            if mode == "revise" else
            "（完全重新生成：不得参考当前舞台旧内容）"
        )
        prompt = PromptLoader.load(
            "stage_roadmap_serial_refine",
            instruction=instruction,
            stage_number=number,
            total_stages=total_stages,
            long_mainline=long_mainline,
            current_stage_outline=stage_sections[number],
            reference_volume_number=volume["vol_idx"],
            reference_volume_title=volume["title"],
            reference_chapter_count=reference_chapter_count,
            reference_volume_outline=reference_volume_outline,
            previous_stage=previous_stage,
            current_stage=current_stage,
        )
        stage_raw = controlled_call(
            prompt, f"串行调整舞台{number}/{total_stages}", number - 1,
            f"舞台{number}调整已暂停；点击继续后重新生成当前舞台",
        )
        if stage_raw is None:
            return stopped_result(completed_parts)
        payload = parse_json_response(stage_raw)
        stage = _normalize_stage_roadmap(
            _normalize_design_field(payload, "stage_roadmap_md", "")
        )
        numbers = [int(value) for value in STAGE_HEADING_RE.findall(stage)]
        if numbers != [number] or not _is_volume_style_stage(stage):
            raise RuntimeError(
                f"舞台{number}调整结果格式或编号不完整；已保留此前成功写入的舞台。"
            )
        completed_parts.append(stage)
        # 尚未处理的旧舞台先保留在文件中；只有新结果成功返回后才逐个替换，
        # 这样暂停或结束不会提前删除仍可使用的原内容。
        pending_original_parts = original_parts[number:]
        _write_file(
            stage_path,
            "\n\n".join(completed_parts + pending_original_parts),
        )
        report(
            "stage_refine_complete", number,
            f"舞台{number}/{total_stages}已调整完成",
        )

    return {
        "long_mainline": long_mainline,
        "stage_roadmap": "\n\n".join(completed_parts),
        "adjustment_note": (
            f"已按指令从舞台{start_stage}开始串行处理 "
            f"{total_stages - start_stage + 1} 个舞台。"
            f"处理方式：{'完全重新生成' if mode == 'regenerate' else '基于当前内容调整'}。"
            f"路由原因：{reason}"
        ),
        "start_stage": start_stage,
        "mode": mode,
    }


def _sync_later_stages_serial(ws, instruction, cancel_event=None):
    """阶段数不变时重做末舞台；阶段增加时保留已有舞台并串行追加。"""
    design_state = _load_story_design_state(ws)
    if not design_state.get("pending_reference_stage_sync"):
        raise ValueError("当前没有由新增拆解章节触发的阶段粗纲变化，无需增量同步舞台。")
    long_mainline = _read_file(_story_design_path(ws, "long_mainline.md"))
    stage_outline = _read_file(_stage_outline_path(ws))
    stage_path = _story_design_path(ws, "stage_roadmap.md")
    stage_roadmap = _read_file(stage_path)
    stage_sections = _stage_outline_sections(stage_outline)
    reference_volumes = list_reference_volumes(ws.reference_outlines)
    if not long_mainline or not stage_roadmap or not stage_sections:
        raise RuntimeError("请先完成长线主线、阶段粗纲与已有舞台设计。")
    if len(stage_sections) != len(reference_volumes):
        raise RuntimeError(
            f"阶段粗纲与参考卷数不一致：阶段 {len(stage_sections)} 个，"
            f"参考卷 {len(reference_volumes)} 卷。请先重新生成阶段粗纲。"
        )

    completed_parts = _completed_stage_prefix(stage_roadmap, len(stage_sections))
    if not completed_parts:
        raise RuntimeError("当前舞台路线图没有可识别的连续舞台，无法执行末尾增量同步。")
    # 阶段数没有增加，说明新增参考内容补充了最后一卷：只重做最后一个舞台。
    adjust_last = len(completed_parts) == len(stage_sections)
    if adjust_last:
        completed_parts = completed_parts[:-1]
    next_stage = len(completed_parts) + 1

    _backup_design_files(ws, "stage_increment", {"stage_roadmap": stage_path})

    llm = _get_llm()
    if not llm:
        raise RuntimeError("未配置可用模型。")
    for number in range(next_stage, len(stage_sections) + 1):
        volume = reference_volumes[number - 1]
        reference_volume_outline = load_reference_volume_outline(
            ws.reference_outlines, volume["vol_idx"]
        ) or "（对应参考卷纲缺失）"
        reference_chapter_count = _reference_volume_chapter_count(
            volume, reference_volume_outline,
        )
        previous_stage = completed_parts[-1] if completed_parts else "（这是第一个舞台，无上一舞台）"
        prompt = PromptLoader.load(
            "stage_roadmap_serial",
            stage_number=number,
            total_stages=len(stage_sections),
            long_mainline=long_mainline,
            current_stage_outline=stage_sections[number],
            reference_volume_number=volume["vol_idx"],
            reference_volume_title=volume["title"],
            reference_chapter_count=reference_chapter_count,
            reference_volume_outline=reference_volume_outline,
            previous_stage=previous_stage,
        )
        payload = parse_json_response(
            _call_design_llm(
                llm, prompt, f"同步新增舞台{number}/{len(stage_sections)}",
                cancel_event=cancel_event,
            )
        )
        stage = _normalize_stage_roadmap(
            _normalize_design_field(payload, "stage_roadmap_md", "")
        )
        numbers = [int(value) for value in STAGE_HEADING_RE.findall(stage)]
        if numbers != [number] or not _is_volume_style_stage(stage):
            raise RuntimeError(
                f"同步新增的舞台{number}格式或编号不完整，已保留此前成功生成的舞台。"
            )
        completed_parts.append(stage)
        _write_file(stage_path, "\n\n".join(completed_parts))
        mapped_paths = []
        for arc in list_reference_story_arcs(ws.reference_outlines, volume["vol_idx"]):
            try:
                mapped_paths.append(os.path.relpath(arc["path"], ws.reference_outlines))
            except ValueError:
                mapped_paths.append(arc["path"])
        _mark_arcs_used(ws, mapped_paths, [number])

    _mark_stage_design_synced(ws)
    return {
        "long_mainline": long_mainline,
        "stage_roadmap": "\n\n".join(completed_parts),
        "adjustment_note": (
            f"阶段数未增加，已仅重新生成最后一个舞台（舞台{next_stage}）。"
            if adjust_last else
            f"已保留已有舞台，并从舞台{next_stage}开始串行补齐后续舞台。"
        ),
    }


def extend_stage_design(ws, instruction, sync_updated_design=False, cancel_event=None):
    """路由 3：续写/新增舞台。

    只读取 used=False 的参考片段作为输入，只输出新增舞台内容，
    程序化追加到 stage_roadmap 末尾，不改动已有舞台。
    """
    print(">>> 续写舞台路线图 <<<")
    if sync_updated_design:
        return _sync_later_stages_serial(ws, instruction, cancel_event=cancel_event)
    rough = _rough_outline_with_stages(ws)
    worldview = _read_file(_worldview_path(ws)) or "（未生成世界观）"
    long_mainline = _read_file(_story_design_path(ws, "long_mainline.md"))
    stage_roadmap = _read_file(_story_design_path(ws, "stage_roadmap.md"))
    if not long_mainline or not stage_roadmap:
        print("错误：请先完成舞台路线图设计，再续写。")
        return {}

    llm = _get_llm()
    if not llm:
        return {}

    unused_arcs = _unused_reference_arcs(ws)
    if unused_arcs:
        ref_parts = []
        for arc in unused_arcs:
            ref_parts.append(
                f"--- 片段ID：{arc['path']}｜参考第 {arc['start_ch']}-{arc['end_ch']} 章 ---\n{arc['content']}"
            )
        reference_text = "\n\n".join(ref_parts)
        print(f"  -> 发现 {len(unused_arcs)} 个未使用的参考片段。")
    else:
        reference_text = "（无新增参考片段）"

    next_stage = _next_stage_number(stage_roadmap)
    world_knowledge = _load_world_knowledge_optional(ws, "续写舞台")
    prompt = PromptLoader.load(
        "stage_design_extend",
        instruction=instruction,
        rough_outline=rough,
        worldview=worldview,
        long_mainline=long_mainline,
        stage_roadmap=stage_roadmap,
        reference_arcs=reference_text,
        world_knowledge=world_knowledge or "（未提供目标世界知识库）",
        next_stage_number=next_stage,
    )
    payload = parse_json_response(
        _call_design_llm(llm, prompt, "续写舞台", cancel_event=cancel_event)
    )
    append_content = _normalize_design_field(payload, "stage_roadmap_append", "")
    if not append_content:
        print("错误：模型未返回新增舞台内容。")
        return {}
    generated_numbers = [int(item) for item in STAGE_HEADING_RE.findall(append_content)]
    if not generated_numbers or generated_numbers[0] != next_stage or any(
        number < next_stage for number in generated_numbers
    ):
        raise RuntimeError(
            f"新增舞台编号无效：必须从舞台{next_stage}开始，且不能包含已有舞台。"
        )
    append_content = _normalize_stage_roadmap(append_content)
    note = str(payload.get("adjustment_note") or "").strip() or "已追加后续舞台。"
    long_mainline_append = ""
    referenced_paths = payload.get("referenced_arc_paths") if isinstance(payload, dict) else []

    # 程序化追加：已有内容不动，只在末尾追加
    stage_path = _story_design_path(ws, "stage_roadmap.md")
    _append_story_design_section(stage_path, f"续写舞台（第{next_stage}舞台起）", append_content)
    print(f"  -> 新增舞台已追加：{stage_path}")

    # 标记本次消费的片段为 used
    allowed_paths = {arc["path"] for arc in unused_arcs}
    consumed = [str(path) for path in (referenced_paths or []) if str(path) in allowed_paths]
    if consumed:
        _mark_arcs_used(ws, consumed, generated_numbers)
        print(f"  -> 已标记 {len(consumed)} 个参考片段为已使用。")
    if long_mainline_append:
        _append_story_design_section(
            _story_design_path(ws, "long_mainline.md"),
            "基于新版全书设计的长线补充",
            long_mainline_append,
        )
    return {
        "stage_roadmap_append": append_content,
        "long_mainline": _read_file(_story_design_path(ws, "long_mainline.md")),
        "stage_roadmap": _read_file(stage_path),
        "adjustment_note": note,
    }


def _refine_design(ws, scope, instruction, compact_summary, prompt_folder, fields, prompt_field_map, output_keys, extra_vars=None):
    rough = _rough_outline_with_stages(ws)
    worldview = _read_file(_worldview_path(ws)) or "（未生成世界观）"
    llm = _get_llm()
    if not llm:
        raise RuntimeError("未配置可用模型。")
    prompt_vars = {
        "creative_direction": _read_file(ws.creative_direction) or "（未提供）",
        "reference_outline": load_reference_novel_outline(ws.reference_outlines) or "（无参考小说全书大纲）",
        "compact_summary": compact_summary or "（无）",
        "rough_outline": rough,
        "worldview": worldview,
    }
    for rel, path in fields.items():
        prompt_vars[prompt_field_map[rel]] = _read_file(path) or f"（未生成{rel}）"
    if extra_vars:
        prompt_vars.update(extra_vars)
    prompt = PromptLoader.load(prompt_folder, **prompt_vars)
    prompt_with_instruction = prompt + "\n\n【本轮指令】\n" + instruction
    payload = parse_json_response(_call_design_llm(llm, prompt_with_instruction, f"{scope} 微调"))
    if "stage_outline_md" in output_keys:
        candidate_stage = _normalize_design_field(payload, "stage_outline_md", "")
        expected_stages = _design_structure_guidance(ws)["reference_volume_count"]
        candidate_count, _ = _design_structure_counts(candidate_stage, "")
        if expected_stages > 0 and candidate_count != expected_stages:
            raise RuntimeError(
                f"阶段粗纲调整结果未通过校验：参考小说共 {expected_stages} 卷，"
                f"模型返回 {candidate_count} 个阶段；本轮三个文件均未写入，请重试。"
            )
    result = {}
    _backup_design_files(ws, scope, fields)
    for out_key, rel in output_keys.items():
        content = _normalize_design_field(payload, out_key, "")
        if rel == "rough_outline" and content:
            content = _remove_stage_outline_section(content)
        if content:
            _write_file(fields[rel], content)
            result[rel] = content
        else:
            result[rel] = _read_file(fields[rel])
    result["adjustment_note"] = str(payload.get("adjustment_note") or "").strip() if isinstance(payload, dict) else ""
    if isinstance(payload, dict) and isinstance(payload.get("referenced_arc_paths"), list):
        result["referenced_arc_paths"] = payload["referenced_arc_paths"]
    return result


def _call_design_llm(llm, prompt, label, cancel_event=None):
    print(f"[LLMProvider] 正在调用模型（{label}）...")
    if cancel_event is not None and hasattr(llm, "generate_cancelable"):
        generated = llm.generate_cancelable(
            prompt, cancel_event, temperature=0.3, is_json=True,
        )
    else:
        generated = llm.generate(prompt, temperature=0.3, is_json=True)
    raw = normalize_text(generated)
    if not raw:
        raise RuntimeError(f"{label}未获得模型输出。")
    return raw


def _normalize_design_field(payload, key, fallback_title):
    if not isinstance(payload, dict):
        return ""
    text = str(payload.get(key) or "").strip()
    if not text:
        return (fallback_title + "\n\n（模型未返回 " + key + "，请重试或人工补充。）") if fallback_title else ""
    return text


def _is_real_design_field(text):
    """判断设计字段是否是真实内容，而非空值或占位符。"""
    if not text or not str(text).strip():
        return False
    t = str(text).strip()
    if "模型未返回" in t and "请重试或人工补充" in t:
        return False
    return True


def gen_story_design(ws, force=False, creative_direction=None, direction_file=None):
    """生成长篇网文的玩法、长线主线、舞台和角色线设计资产。"""
    llm = _get_llm()
    if not llm:
        return

    direction = _load_creative_direction(ws, creative_direction, direction_file)
    record_creative_direction(ws, direction, "rebuild")
    world_knowledge = _load_world_knowledge_optional(ws, "故事玩法/舞台/角色线设计")

    _gen_core_gameplay(ws, llm, direction, world_knowledge, force=force)
    _gen_long_mainline(ws, llm, direction, world_knowledge, force=force)
    _gen_stage_roadmap(ws, llm, direction, world_knowledge, force=force)
    _gen_character_arcs(ws, llm, direction, world_knowledge, force=force)
    if force or not _load_story_design_state(ws):
        _record_story_design_reference_snapshot(ws, reset_extensions=force)


def gen_novel_outline(ws, force=False, creative_direction=None, direction_file=None, preserved_content=None):
    """生成核心玩法、全书长线主线、舞台路线图和角色成长线。"""
    print(">>> 生成核心玩法与全书舞台设计 <<<")

    direction = _load_creative_direction(ws, creative_direction, direction_file)
    record_creative_direction(ws, direction, "initial")
    if direction:
        print(f"  -> 创作方向已加载（{len(direction)} 字）")
    else:
        print("  -> 未提供创作方向，将完全由 LLM 自主创作。")
        print("     可通过 --direction 参数或 creative_direction.md 文件提供方向。")

    llm = _get_llm()
    if not llm:
        return

    world_knowledge = _load_world_knowledge_optional(ws, "核心玩法与舞台设计")
    _gen_core_gameplay(ws, llm, direction, world_knowledge, force=force)
    _gen_long_mainline(ws, llm, direction, world_knowledge, force=force)
    _gen_stage_roadmap(ws, llm, direction, world_knowledge, force=force)
    _gen_character_arcs(ws, llm, direction, world_knowledge, force=force)

    # 推荐书名与简介
    print()
    gen_novel_name_synopsis(ws, force=True)
    if force or not _load_story_design_state(ws):
        _record_story_design_reference_snapshot(ws, reset_extensions=force)

    print(f"\n  -> 请审核编辑核心玩法、长线主线、舞台路线图和角色成长线后，再生成故事情节单元。")


def import_target_world_sources(ws, paths, force=False):
    """导入目标题材资料到工作区。"""
    result = import_world_sources(ws, paths, force=force)
    for path in result["imported"]:
        print(f"  已导入：{path}")
    for path in result["skipped"]:
        print(f"  已存在，跳过：{path}")
    for path in result["unsupported"]:
        print(f"  不支持的文件类型，跳过：{path}")
    for path in result["missing"]:
        print(f"  文件不存在，跳过：{path}")
    print(f"  -> manifest：{result['manifest']}")
    return result


def build_target_world_knowledge(ws, force=False, chunk_size=36000, chapter_batch_size=20,
                                 max_workers=4, primary_source=None, merge_only=False):
    """将已导入资料结构化为目标世界知识库。"""
    llm = _get_lite_llm()
    if not llm:
        return None
    print(">>> 构建目标世界知识库 <<<")
    return build_world_knowledge(
        ws,
        llm,
        force=force,
        chunk_size=chunk_size,
        chapter_batch_size=chapter_batch_size,
        max_workers=max_workers,
        primary_source=primary_source,
        merge_only=merge_only,
    )


def _extract_reference_name_synopsis(ws):
    """从 sample_novel.txt 提取参考小说的书名和简介。

    优先识别标记格式：
        【书名】XXX
        【简介】XXX（可多行）
    无标记时走启发式兜底：第一行为书名，章节标题前的连续文本为简介。
    """
    if not os.path.exists(ws.reference_sample):
        return "（未知）", "（未提供）"

    with open(ws.reference_sample, "r", encoding="utf-8") as f:
        content = f.read()

    # 优先匹配标记格式
    name_match = re.search(r'^【书名】(.+)', content, re.MULTILINE)
    synopsis_match = re.search(r'^【简介】(.+?)(?=^【|^第[一二三四五六七八九十百千零\d]+[章回节])', content, re.MULTILINE | re.DOTALL)

    if name_match:
        name = name_match.group(1).strip()
        synopsis = synopsis_match.group(1).strip() if synopsis_match else "（未提供）"
        return name, synopsis

    # 兜底：启发式提取
    lines = content.split('\n')
    name = ""
    synopsis_lines = []
    in_synopsis = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_synopsis and synopsis_lines:
                break
            continue

        if not name:
            name = stripped.strip("《》")
            continue

        if re.match(r'^第[一二三四五六七八九十百千零\d]+[章回节]', stripped):
            break

        in_synopsis = True
        synopsis_lines.append(stripped)

    synopsis = "\n".join(synopsis_lines) if synopsis_lines else "（未提取到简介）"
    return name, synopsis


def gen_novel_name_synopsis(ws, force=False, cancel_event=None):
    """只基于粗略大纲与长线主线推荐书名和简介。"""
    rough_outline = _read_file(_rough_outline_path(ws))
    long_mainline = _read_file(_story_design_path(ws, "long_mainline.md"))
    if not rough_outline or not long_mainline:
        raise RuntimeError("请先生成粗略大纲与长线主线，再生成书名和简介。")

    output_path = os.path.join(ws.file_system, "novel_name_synopsis.md")
    existing = _read_file(output_path)
    if existing and not force:
        print(f"书名与简介推荐已存在：{output_path}")
        print("使用 --force 覆盖。")
        return

    llm = _get_llm()
    if not llm:
        return

    return run_step(
        llm=llm,
        folder="novel_name_synopsis",
        label="书名与简介",
        header=">>> 推荐书名与简介 <<<",
        write_guard=True,
        output_path=output_path,
        prompt_vars=dict(
            rough_outline=rough_outline,
            long_mainline=long_mainline,
        ),
        cancel_event=cancel_event,
    )


def _stage_insert_backup_path(ws):
    return os.path.join(ws.file_system, "adaptation", "stage_roadmap_before_insert.md")


def insert_stage(ws, creative_direction=None, direction_file=None, after_stage=None, before_stage=None):
    """基于新灵感设计新舞台，并插入全书舞台路线图。"""
    stage_direction = _load_creative_direction(ws, creative_direction, direction_file)
    record_creative_direction(ws, stage_direction, "stage_insert")
    if not stage_direction:
        print("错误：请通过 --direction 或 --direction-file 提供新舞台灵感。")
        return

    llm = _get_llm()
    if not llm:
        return

    stage_roadmap_path = _story_design_path(ws, "stage_roadmap.md")
    stage_roadmap = _read_file(stage_roadmap_path)
    if not stage_roadmap:
        print("错误：未找到舞台路线图。请先运行 novel-outline 或 story-design。")
        return

    assets = _load_story_design_assets(ws)
    world_knowledge = _load_world_knowledge_optional(ws, "新舞台插入")
    if after_stage is not None:
        insert_hint = f"请优先插入在舞台{after_stage}之后，并重新编号所有舞台。"
    elif before_stage is not None:
        insert_hint = f"请优先插入在舞台{before_stage}之前，并重新编号所有舞台。"
    else:
        insert_hint = "请根据核心玩法、长线主线和前后承接关系自行判断最佳插入位置。"

    print(">>> 基于灵感插入新舞台 <<<")
    prompt = PromptLoader.load(
        "stage_insert_design",
        stage_direction=stage_direction,
        insert_hint=insert_hint,
        core_gameplay=assets["core_gameplay"],
        long_mainline=assets["long_mainline"],
        stage_roadmap=stage_roadmap,
        character_arcs=assets["character_arcs"],
        world_knowledge=world_knowledge or "（未提供目标世界知识库）",
    )
    result = _normalize_stage_roadmap(normalize_text(llm.generate(prompt)))
    backup_path = _stage_insert_backup_path(ws)
    _write_file(backup_path, stage_roadmap)
    _write_file(stage_roadmap_path, result)
    print(f"  -> 原舞台路线图已备份：{backup_path}")
    print(f"  -> 新舞台路线图已保存：{stage_roadmap_path}")


def _map_to_reference_volumes_sequential(ws, vol_idx, ref_volumes):
    """顺序映射：新小说卷N 使用参考小说卷N。"""
    if not ref_volumes:
        return ""

    idx = min(vol_idx - 1, len(ref_volumes) - 1)
    vol = ref_volumes[idx]
    outline = load_reference_volume_outline(ws.reference_outlines, vol["vol_idx"])
    return f"（参考原作第{vol['vol_idx']}卷）\n{outline}" if outline else "（无对应参考卷纲）"


def _gen_volume_worldview(ws, vol_idx, llm, force, novel_outline, new_novel_worldview):
    """基于新大纲+新全书世界观+本卷卷纲，生成该卷的世界观。"""
    new_wv_dir = os.path.join(ws.file_system, "new_worldviews")
    vol_wv_path = os.path.join(new_wv_dir, f"vol_{vol_idx:02d}_worldview.md")

    existing_wv = _read_file(vol_wv_path)
    if existing_wv and not force:
        print(f"  卷{vol_idx}世界观已存在，跳过。")
        return existing_wv

    # 读取本卷新卷纲（从按卷文件读取）
    vol_outline_dir = os.path.join(ws.file_system, "new_volume_outlines")
    vol_outline_file = os.path.join(vol_outline_dir, f"vol_{vol_idx:02d}_outline.md")
    current_vol_text = _read_file(vol_outline_file) or ""
    if not current_vol_text:
        print(f"  警告：未找到本卷卷纲文件 {vol_outline_file}")
        return
    # 去除终卷标记
    current_vol_text = re.sub(r'\n?\[(?:FINISHED|CONTINUE)\]\s*$', '', current_vol_text).strip()

    # 读取上一卷世界观（衔接参考）
    prev_wv = ""
    if vol_idx > 1:
        prev_path = os.path.join(new_wv_dir, f"vol_{vol_idx - 1:02d}_worldview.md")
        prev_wv = _read_file(prev_path) or ""

    # 旧世界观（force 覆盖时作为参考）
    old_wv = existing_wv or ""

    os.makedirs(new_wv_dir, exist_ok=True)
    print(f"  -> 生成卷{vol_idx}世界观...")

    rewrite_map = load_rewrite_map(ws, vol_idx)

    prompt = (
        "你是一个专业的小说世界观设计专家。请基于新小说的全书世界观，结合本卷卷纲的具体内容，"
        "细化生成指定卷的详细世界观设定。\n\n"
        "【新小说全书世界观】\n" + new_novel_worldview + "\n\n"
        "【本卷卷纲】\n" + current_vol_text + "\n\n"
        "【换皮映射表】（用于理解参考元素如何转译，必须以新小说设定为准）\n" + rewrite_map + "\n\n"
        + (f"【上一卷世界观】（保持世界观演进的一致性）\n{prev_wv}\n\n" if prev_wv else "")
        + (f"【本卷旧世界观】（参考已有设定，在此基础上升级）\n{old_wv}\n\n" if old_wv else "")
        + "【要求】\n"
        "1. 以全书世界观为基础，细化到本卷涉及的具体势力、人物、地点、物品。\n"
        "2. 体现世界观在本卷中的演进：新势力登场、角色成长、新区域解锁等。\n"
        "3. 与上一卷世界观保持连续性，不要出现矛盾设定。\n"
        "4. 每个方面必须列出具体名称，不能概括。\n"
        "5. 不能把参考小说旧世界的事件、人物、时间线和宗教因果固化为新世界观事实。\n"
        "6. 若本卷卷纲中的“对应参考小说”说明包含旧名词，只能理解为映射说明，不能写入新世界观正文。\n"
        "7. 使用纯文本输出，禁止使用 Markdown 格式符号。标题使用 # 标记。段落之间用空行分隔。\n\n"
        "按以下结构输出：\n"
        "一、势力与人物\n"
        "二、修炼体系\n"
        "三、特殊物品\n"
        "四、地理场景\n"
        "五、种族与族群\n"
        "六、核心规则与禁忌\n"
        "七、主角金手指进展"
    )
    result = normalize_text(llm.generate(prompt))

    _write_file(vol_wv_path, result)
    print(f"  -> 卷{vol_idx}世界观已保存：{vol_wv_path}")
    return result


def _gen_volume_stage_plan(ws, vol_idx, llm, force, vol_outline, vol_worldview,
                           novel_outline, new_novel_worldview):
    """为当前卷生成舞台/副本计划。"""
    output_path = _volume_stage_plan_path(ws, vol_idx)
    existing = _read_file(output_path)
    if existing and not force:
        print(f"  卷{vol_idx}舞台计划已存在，跳过。")
        return existing

    assets = _load_story_design_assets(ws)
    rewrite_map = load_rewrite_map(ws, vol_idx)

    return run_step(
        llm=llm,
        folder="volume_stage_plan",
        header=f"  -> 生成卷{vol_idx}舞台计划...",
        save=f"  -> 卷{vol_idx}舞台计划已保存：{output_path}",
        output_path=output_path,
        prompt_vars=dict(
            volume_index=vol_idx,
            core_gameplay=assets["core_gameplay"],
            stage_roadmap=assets["stage_roadmap"],
            character_arcs=assets["character_arcs"],
            novel_outline=novel_outline or "（未生成新小说大纲）",
            new_novel_worldview=new_novel_worldview or "（未生成新小说世界观）",
            volume_outline=vol_outline or "（未生成本卷卷纲）",
            volume_worldview=vol_worldview or "（未生成本卷世界观）",
            rewrite_map=rewrite_map,
        ),
    )


def _gen_single_volume(ws, vol_idx, ref_volumes, force, creative_direction, llm, preserved_content=None):
    """生成单卷卷纲，再生成该卷世界观。返回 True 表示已是终卷。"""
    vol_dir = os.path.join(ws.file_system, "new_volume_outlines")
    vol_file = os.path.join(vol_dir, f"vol_{vol_idx:02d}_outline.md")
    os.makedirs(vol_dir, exist_ok=True)

    existing_this = _read_file(vol_file)
    if existing_this and not force:
        print(f"  -> 卷{vol_idx}卷纲已存在，跳过。（用 --force 覆盖）")
        vol_outline_clean = re.sub(r'\n?\[(?:FINISHED|CONTINUE)\]\s*$', '', existing_this).strip()
        existing_novel_outline = _read_file(os.path.join(ws.file_system, "novel_outline.md")) or ""
        new_novel_worldview = _read_file(os.path.join(ws.file_system, "new_novel_worldview.md")) or "（无新小说世界观，请先运行 novel-outline 命令）"
        vol_worldview = _gen_volume_worldview(ws, vol_idx, llm, force, existing_novel_outline, new_novel_worldview)
        _gen_volume_stage_plan(
            ws,
            vol_idx,
            llm,
            force,
            vol_outline_clean,
            vol_worldview,
            existing_novel_outline,
            new_novel_worldview,
        )
        if existing_this.rstrip().endswith("[FINISHED]"):
            return True
        return False

    print(f"  -> 生成卷{vol_idx}卷纲...")

    direction = _load_creative_direction(ws, creative_direction)

    novel_outline = _read_file(os.path.join(ws.file_system, "novel_outline.md")) or ""

    # 读取上一卷的卷纲（按卷存储）
    prev_vol_file = os.path.join(vol_dir, f"vol_{vol_idx - 1:02d}_outline.md")
    previous_volumes = _read_file(prev_vol_file) if vol_idx > 1 and os.path.exists(prev_vol_file) else ""
    if not previous_volumes:
        previous_volumes = "（无前卷，这是第一卷）"

    # 使用新小说全书世界观
    new_novel_worldview = _read_file(os.path.join(ws.file_system, "new_novel_worldview.md")) or "（无新小说世界观，请先运行 novel-outline 命令）"

    ref_vol_outline = _map_to_reference_volumes_sequential(ws, vol_idx, ref_volumes)
    rewrite_map = load_rewrite_map(ws, vol_idx)

    preserved_section = ""
    if preserved_content:
        preserved_section = f"【已有定稿中值得保留的卷纲内容】\n以下内容来自已定稿章节的分析，重新生成卷纲时必须保留这些内容的延续性：\n{preserved_content}"

    prompt = PromptLoader.load(
        "adaptive_volume_outline",
        novel_outline=novel_outline,
        reference_volume_outline=ref_vol_outline or "（无参考卷纲）",
        new_novel_worldview=new_novel_worldview,
        rewrite_map=rewrite_map,
        inspirations="（无灵感库）",
        volume_index=vol_idx,
        creative_direction=direction or "（用户未提供具体方向）",
        previous_volumes=previous_volumes,
        outline_rules=_load_outline_rules(ws),
        preserved_content=preserved_section,
        audit_feedback="",
    )
    result = normalize_text(llm.generate(prompt))

    if not result:
        return False

    is_finished = result.rstrip().endswith("[FINISHED]")
    result_clean = re.sub(r'\n?\[(?:FINISHED|CONTINUE)\]\s*$', '', result).strip()

    # 写入按卷文件（保留 [FINISHED] 标记以便重跑时检测）
    marker = "\n[FINISHED]" if is_finished else "\n[CONTINUE]"
    _write_file(vol_file, result_clean + marker + "\n")

    if is_finished:
        print(f"  -> 第 {vol_idx} 卷卷纲已保存（终卷，生成完毕）。")
    else:
        print(f"  -> 第 {vol_idx} 卷卷纲已保存，继续生成下一卷。")

    # Step 2: 生成该卷的世界观
    vol_worldview = _gen_volume_worldview(ws, vol_idx, llm, force, novel_outline, new_novel_worldview)
    _gen_volume_stage_plan(
        ws,
        vol_idx,
        llm,
        force,
        result_clean,
        vol_worldview,
        novel_outline,
        new_novel_worldview,
    )

    return is_finished


def _write_aggregate_volume_outline(ws):
    """从按卷文件汇总写入 volume_outline.md（兼容旧引用）。"""
    vol_dir = os.path.join(ws.file_system, "new_volume_outlines")
    if not os.path.isdir(vol_dir):
        return
    vol_files = sorted(f for f in os.listdir(vol_dir) if re.match(r'^vol_\d+_outline\.md$', f))
    if not vol_files:
        return

    parts = []
    for vf in vol_files:
        content = _read_file(os.path.join(vol_dir, vf))
        if content:
            # 去除终卷/续卷标记（仅用于按卷文件的重跑检测）
            clean = re.sub(r'\n?\[(?:FINISHED|CONTINUE)\]\s*$', '', content).strip()
            if clean:
                parts.append(clean)
            parts.append(content.strip())

    output_path = os.path.join(ws.file_system, "volume_outline.md")
    _write_file(output_path, "\n\n---\n\n".join(parts))
    print(f"\n  -> 汇总卷纲已写入：{output_path}")


def gen_volume_outline(ws, volume=None, force=False, creative_direction=None, preserved_content=None):
    """Step 2: 逐卷生成卷纲，由 LLM 判断是否为终卷。"""
    MAX_VOLUMES = 20

    novel_outline = _read_file(os.path.join(ws.file_system, "novel_outline.md"))
    if not novel_outline:
        print("错误：未找到新小说大纲。请先运行 novel-outline 子命令。")
        return

    outlines_dir = ws.reference_outlines
    ref_volumes = list_reference_volumes(outlines_dir)
    if not ref_volumes:
        print("错误：未找到参考小说卷数据。请先运行 outline_builder.py。")
        return

    print(f"  -> 参考小说共 {len(ref_volumes)} 卷，新小说卷数将由 LLM 逐卷判断。")

    llm = _get_llm()
    if not llm:
        return
    _ensure_rewrite_map(ws, llm)

    if volume is not None:
        if volume < 1 or volume > MAX_VOLUMES:
            print(f"错误：卷号 {volume} 超出范围（1-{MAX_VOLUMES}）。")
            return
        print(f">>> 仿写生成卷{volume}卷纲 <<<")
        _gen_single_volume(ws, volume, ref_volumes, force, creative_direction, llm, preserved_content=preserved_content)
    else:
        # 从按卷文件检测已有卷数（支持断点续传）
        vol_dir = os.path.join(ws.file_system, "new_volume_outlines")
        start_vol = 1
        if os.path.isdir(vol_dir) and not force:
            vol_files = sorted(f for f in os.listdir(vol_dir) if re.match(r'^vol_\d+_outline\.md$', f))
            if vol_files:
                # 从最后一个文件推断下一卷
                last_match = re.match(r'^vol_(\d+)_outline\.md$', vol_files[-1])
                if last_match:
                    last_vol = int(last_match.group(1))
                    # 检查终卷标记
                    last_content = _read_file(os.path.join(vol_dir, vol_files[-1]))
                    if last_content and last_content.rstrip().endswith("[FINISHED]"):
                        print(f">>> 卷纲已全部生成（共 {last_vol} 卷），无需继续。使用 --force 覆盖。<<<")
                        return
                    start_vol = last_vol + 1
                    print(f">>> 断点续传：卷1-{last_vol} 已存在，从卷{start_vol}继续生成 <<<")
                else:
                    print(f">>> 仿写逐卷生成全部卷纲（最多 {MAX_VOLUMES} 卷，LLM 自动判断终卷）<<<")
            else:
                print(f">>> 仿写逐卷生成全部卷纲（最多 {MAX_VOLUMES} 卷，LLM 自动判断终卷）<<<")
        else:
            print(f">>> 仿写逐卷生成全部卷纲（最多 {MAX_VOLUMES} 卷，LLM 自动判断终卷）<<<")

        for vol_idx in range(start_vol, MAX_VOLUMES + 1):
            is_finished = _gen_single_volume(ws, vol_idx, ref_volumes, force, creative_direction, llm, preserved_content=preserved_content)
            if is_finished:
                break

    # 汇总写入 volume_outline.md（兼容旧引用）
    _write_aggregate_volume_outline(ws)


def _novel_outlines_dir(ws):
    """返回新小说批次摘要目录。"""
    return os.path.join(ws.file_system, "outlines")


def _novel_story_arcs_dir(ws):
    """返回新小说故事情节单元目录。"""
    return os.path.join(ws.file_system, "story_arcs")


def _volume_story_arc_dir(ws, volume):
    return os.path.join(_novel_story_arcs_dir(ws), f"vol_{volume:02d}")


def _story_arc_file_name(arc_idx, start_ch, end_ch):
    return f"arc_{arc_idx:03d}_ch{start_ch:03d}_{end_ch:03d}.md"


def _story_arc_path(ws, volume, arc_idx, start_ch, end_ch):
    return os.path.join(
        _volume_story_arc_dir(ws, volume),
        _story_arc_file_name(arc_idx, start_ch, end_ch),
    )


def _extract_stage_from_roadmap(stage_roadmap, stage_idx):
    stage_roadmap = _normalize_stage_roadmap(stage_roadmap)
    if not stage_roadmap:
        return ""
    headings = list(STAGE_HEADING_RE.finditer(stage_roadmap))
    for index, heading in enumerate(headings):
        if int(heading.group(1)) != int(stage_idx):
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(stage_roadmap)
        return stage_roadmap[heading.start():end].strip()
    return ""


def _infer_stage_chapter_count(stage_text):
    if not stage_text:
        return 0
    range_patterns = [
        r'预计章节数[：:]\s*(\d+)\s*[-—~至到]\s*(\d+)',
        r'章节数[：:]\s*(\d+)\s*[-—~至到]\s*(\d+)',
        r'预计\s*(\d+)\s*[-—~至到]\s*(\d+)\s*章',
    ]
    for pattern in range_patterns:
        m = re.search(pattern, stage_text)
        if m:
            return max(int(m.group(1)), int(m.group(2)))

    patterns = [
        r'预计章节数[：:]\s*(\d+)',
        r'章节数[：:]\s*(\d+)',
        r'预计\s*(\d+)\s*章',
        r'共\s*(\d+)\s*章',
    ]
    for pattern in patterns:
        m = re.search(pattern, stage_text)
        if m:
            return max(1, int(m.group(1)))

    range_match = re.search(r'第\s*(\d+)\s*[-—~至到]\s*(\d+)\s*章', stage_text)
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        return max(1, end - start + 1)
    return 0


def _load_stage_context(ws, stage_idx):
    stage_roadmap = _read_file(_story_design_path(ws, "stage_roadmap.md"))
    stage_text = _extract_stage_from_roadmap(stage_roadmap, stage_idx)
    if not stage_text:
        return None
    total_chapters = _infer_stage_chapter_count(stage_text)
    if total_chapters <= 0:
        print(f"错误：舞台{stage_idx}缺少“预计章节数”，无法生成故事情节单元。")
        print("请补充 stage_roadmap.md 中该舞台的预计章节数，或重新运行 novel-outline/story-design。")
        return None
    long_mainline = _read_file(_story_design_path(ws, "long_mainline.md")) or "（未生成全书长线主线）"
    stage_worldview = (
        "【全书长线主线】\n" + long_mainline + "\n\n"
        "【当前舞台规则与边界】\n" + stage_text
    )
    return stage_text, stage_worldview, total_chapters


def _list_novel_story_arcs(ws, volume):
    arc_dir = _volume_story_arc_dir(ws, volume)
    if not os.path.isdir(arc_dir):
        return []
    items = []
    for fname in sorted(os.listdir(arc_dir)):
        m = STORY_ARC_FILE_RE.match(fname)
        if not m:
            continue
        path = os.path.join(arc_dir, fname)
        content = _read_file(path)
        if not content:
            continue
        items.append({
            "idx": int(m.group(1)),
            "start_ch": int(m.group(2)),
            "end_ch": int(m.group(3)),
            "file": fname,
            "path": path,
            "content": content,
        })
    return items


def _write_story_arc_index(ws, volume, arc_items):
    index_path = os.path.join(_volume_story_arc_dir(ws, volume), "arcs_index.json")
    lines = ["["]
    for idx, item in enumerate(arc_items):
        comma = "," if idx < len(arc_items) - 1 else ""
        lines.append(
            "  {"
            f"\"id\": {item['idx']}, "
            f"\"start_ch\": {item['start_ch']}, "
            f"\"end_ch\": {item['end_ch']}, "
            f"\"file\": \"{item['file']}\""
            f"}}{comma}"
        )
    lines.append("]")
    _write_file(index_path, "\n".join(lines))


def _clear_story_arc_files(ws, volume):
    arc_dir = _volume_story_arc_dir(ws, volume)
    if not os.path.isdir(arc_dir):
        return
    for fname in os.listdir(arc_dir):
        if STORY_ARC_FILE_RE.match(fname) or fname == "arcs_index.json":
            os.remove(os.path.join(arc_dir, fname))


def _target_story_arc_count(total_chapters):
    return max(1, (total_chapters + STORY_ARC_TARGET_CHAPTERS - 1) // STORY_ARC_TARGET_CHAPTERS)


def _select_reference_arc_groups(reference_arcs, target_count):
    groups = []
    for idx in range(target_count):
        if idx < len(reference_arcs):
            groups.append([reference_arcs[idx]])
        else:
            groups.append([])
    return groups


def _allocate_story_arc_lengths(total_chapters, target_count):
    target_count = max(1, target_count)
    base = total_chapters // target_count
    remainder = total_chapters % target_count
    return [
        max(1, base + (1 if idx < remainder else 0))
        for idx in range(target_count)
    ]


def _reference_story_arc_average_chars(ws, stage_number=None):
    """返回对应参考卷故事片段的平均字符数；未指定舞台时统计全部。"""
    lengths = []
    volumes = list_reference_volumes(ws.reference_outlines)
    if stage_number is not None:
        mapped = _reference_volume_for_stage(ws, stage_number)
        volumes = [mapped] if mapped else []
    for volume in volumes:
        for arc in list_reference_story_arcs(ws.reference_outlines, volume["vol_idx"]):
            content = arc.get("content", "")
            # “字数”按去除空白后的可见字符近似，避免 Markdown 排版拉高统计值。
            char_count = len(re.sub(r"\s+", "", content))
            if char_count:
                lengths.append(char_count)
    if not lengths:
        return 1000
    return max(300, round(sum(lengths) / len(lengths)))


def _reference_volume_for_stage(ws, stage_number):
    """阶段N与按顺序排列的参考卷N一一对应。"""
    volumes = list_reference_volumes(ws.reference_outlines)
    if 1 <= int(stage_number) <= len(volumes):
        return volumes[int(stage_number) - 1]
    return None


def _reference_volume_story_arcs_summary(ws, stage_number):
    """直接汇总对应参考卷的全部故事片段，不再调用模型二次压缩。"""
    volume = _reference_volume_for_stage(ws, stage_number)
    if not volume:
        return "（未找到当前舞台对应的参考卷故事片段）"
    arcs = list_reference_story_arcs(ws.reference_outlines, volume["vol_idx"])
    if not arcs:
        return f"（参考卷{volume['vol_idx']}没有可用故事片段）"
    return "\n\n===\n\n".join(
        f"【参考情节{arc['idx']}：第{arc['start_ch']}-{arc['end_ch']}章】\n{arc.get('content', '').strip()}"
        for arc in arcs
    )


def _simple_story_arc_context(ws, stage_number):
    """故事情节生成唯一允许使用的四类内容资料。"""
    long_mainline = _read_file(_story_design_path(ws, "long_mainline.md")) or "（未生成长线主线）"
    stage_roadmap = _read_file(_story_design_path(ws, "stage_roadmap.md")) or ""
    current_stage = _extract_stage_from_roadmap(stage_roadmap, stage_number) or "（未找到当前舞台）"
    previous_stage = (
        _extract_stage_from_roadmap(stage_roadmap, stage_number - 1)
        if int(stage_number) > 1 else ""
    )
    return {
        "long_mainline": long_mainline,
        "previous_stage": previous_stage or "（这是第一个舞台，无上一舞台）",
        "current_stage": current_stage,
        "reference_story_arcs": _reference_volume_story_arcs_summary(ws, stage_number),
    }


def _visible_char_count(text):
    return len(re.sub(r"\s+", "", text or ""))


def _generate_with_cancel(llm, prompt, cancel_event=None, temperature=0.7):
    if cancel_event is not None and hasattr(llm, "generate_cancelable"):
        return llm.generate_cancelable(prompt, cancel_event, temperature=temperature)
    return llm.generate(prompt, temperature=temperature)


def _compact_story_arc_result(llm, result, arc_idx, start_ch, end_ch, target_char_count,
                              cancel_event=None):
    """对明显超长的情节结果做一次结构不变的压缩，避免冗长内容继续放大。"""
    max_chars = round(target_char_count * 1.25)
    if _visible_char_count(result) <= max_chars:
        return result
    prompt = PromptLoader.load(
        "story_arc_compact",
        arc_index=arc_idx,
        start_chapter=start_ch,
        end_chapter=end_ch,
        target_char_count=target_char_count,
        max_char_count=max_chars,
        original_story_arc=result,
    )
    compacted = normalize_text(_generate_with_cancel(llm, prompt, cancel_event, temperature=0.2))
    return compacted or result


def _format_reference_arc_group(group):
    if not group:
        return "（无参考故事情节单元）"
    parts = []
    for arc in group:
        source_label = "参考故事情节单元" if arc.get("source_type") == "story_arc" else "旧版参考批次"
        parts.append(
            f"【{source_label}{arc['idx']}：第{arc['start_ch']}-{arc['end_ch']}章】\n"
            f"{arc.get('content', '')}"
        )
    return "\n\n---\n\n".join(parts)


def _plan_story_arcs(total_chapters):
    """按总章数规划情节单元的章节范围，不依赖参考小说。"""
    target_count = _target_story_arc_count(total_chapters)
    lengths = _allocate_story_arc_lengths(total_chapters, target_count)
    plans = []
    start_ch = 1
    for idx, length in enumerate(lengths, 1):
        end_ch = min(total_chapters, start_ch + length - 1)
        plans.append({"idx": idx, "start_ch": start_ch, "end_ch": end_ch})
        start_ch = end_ch + 1
    if plans and plans[-1]["end_ch"] < total_chapters:
        plans[-1]["end_ch"] = total_chapters
    return plans


def story_arc_resume_status(ws, volume):
    """根据舞台计划与落盘文件判断故事情节是否可断点续生成。"""
    context = _load_volume_outline_context(ws, volume)
    if not context:
        return {"can_resume": False, "completed": 0, "total": 0}
    _, _, total_chapters = context
    plans = _plan_story_arcs(total_chapters)
    completed_files = {
        (item["idx"], item["start_ch"], item["end_ch"])
        for item in _list_novel_story_arcs(ws, volume)
    }
    completed = sum((plan["idx"], plan["start_ch"], plan["end_ch"]) in completed_files for plan in plans)
    first_missing = next(
        (
            plan["idx"] for plan in plans
            if (plan["idx"], plan["start_ch"], plan["end_ch"]) not in completed_files
        ),
        None,
    )
    return {
        "can_resume": 0 < completed < len(plans),
        "completed": completed,
        "total": len(plans),
        "next_arc": first_missing,
    }


def _plan_story_arcs_from_reference(reference_arcs, total_chapters):
    target_count = _target_story_arc_count(total_chapters)
    groups = _select_reference_arc_groups(reference_arcs, target_count)
    lengths = _allocate_story_arc_lengths(total_chapters, len(groups))

    plans = []
    start_ch = 1
    for idx, (group, length) in enumerate(zip(groups, lengths), 1):
        end_ch = min(total_chapters, start_ch + length - 1)
        plans.append({
            "idx": idx,
            "start_ch": start_ch,
            "end_ch": end_ch,
            "reference_story_arc": _format_reference_arc_group(group),
            "reference_range": "；".join(
                f"第{arc['start_ch']}-{arc['end_ch']}章" for arc in group
            ) or "无",
        })
        start_ch = end_ch + 1

    if plans and plans[-1]["end_ch"] < total_chapters:
        plans[-1]["end_ch"] = total_chapters
    return plans


def _find_story_arc_for_chapter(ws, volume, ch_num):
    for arc in _list_novel_story_arcs(ws, volume):
        if arc["start_ch"] <= ch_num <= arc["end_ch"]:
            return arc["content"]
    return ""


def _find_legacy_batch_for_chapter(ws, volume, ch_num, total_chapters):
    batch_dir = os.path.join(ws.file_system, "outlines", f"vol_{volume:02d}")
    if not os.path.isdir(batch_dir):
        return ""
    batch_idx = (ch_num - 1) // BATCH_SIZE + 1
    bs = (batch_idx - 1) * BATCH_SIZE + 1
    be = min(batch_idx * BATCH_SIZE, total_chapters)
    return _read_file(os.path.join(batch_dir, f"batch_{bs:03d}_{be:03d}.md")) or ""


def _adapted_reference_batch_path(ws, volume, start_ch, end_ch):
    return os.path.join(
        ws.file_system,
        "adaptation",
        "adapted_reference_batches",
        f"vol_{volume:02d}",
        f"batch_{start_ch:03d}_{end_ch:03d}.md",
    )


def _adapt_reference_batch(ws, llm, volume, batch_idx, start_ch, end_ch,
                           vol_outline, vol_worldview, reference_batch,
                           rewrite_map, forbidden_terms, force=False):
    """先将参考批次改写为目标世界可用的节奏草稿，降低旧设定污染。"""
    if not reference_batch:
        return "（无参考批次数据）"

    out_path = _adapted_reference_batch_path(ws, volume, start_ch, end_ch)
    existing = _read_file(out_path)
    if existing and not force:
        return existing

    forbidden_terms_text = format_forbidden_terms(forbidden_terms)
    audit_feedback = ""
    result = ""
    violations = []

    for attempt in range(2):
        prompt = PromptLoader.load(
            "adapt_reference_batch",
            volume_outline=vol_outline,
            volume_worldview=vol_worldview,
            rewrite_map=rewrite_map,
            forbidden_terms=forbidden_terms_text,
            batch_index=batch_idx,
            start_chapter=start_ch,
            end_chapter=end_ch,
            reference_batch=reference_batch,
            audit_feedback=audit_feedback,
        )
        result = normalize_text(llm.generate(prompt))
        violations = scan_forbidden_terms(result, forbidden_terms)
        if not violations:
            _write_file(out_path, result)
            return result

        audit_feedback = (
            f"【上次适配草稿违规项】\n"
            f"仍然出现了以下禁止残留参考元素：{', '.join(violations)}。\n"
            "请重新适配，不要保留这些旧世界元素；若无自然对应物，必须功能替代、删除或延后。"
        )
        print(f"  参考批次适配仍有残留：{', '.join(violations)}，尝试重写...")

    _write_file(out_path, result)
    append_adaptation_report(
        ws,
        f"卷{volume}批次{batch_idx}参考批次适配残留",
        f"文件：{out_path}\n违规项：{', '.join(violations)}",
    )
    return result


def _batch_audit_path(ws, volume, batch_idx, start_ch, end_ch, attempt):
    return os.path.join(
        ws.file_system,
        "adaptation",
        "batch_reasonability_audits",
        f"vol_{volume:02d}",
        f"batch_{start_ch:03d}_{end_ch:03d}_attempt_{attempt}.json",
    )


def _audit_batch_summary_reasonability(ws, llm, volume, batch_idx, start_ch, end_ch,
                                       vol_outline, vol_worldview, previous_batch,
                                       reference_batch, adapted_reference_batch,
                                       rewrite_map, batch_summary, attempt):
    """用 pro 模型审计批次摘要是否符合新书大纲/世界观，而不是做简单禁词扫描。"""
    novel_outline = _read_file(os.path.join(ws.file_system, "novel_outline.md")) or "（未找到新小说全书大纲）"
    new_novel_worldview = _read_file(os.path.join(ws.file_system, "new_novel_worldview.md")) or "（未找到新小说全书世界观）"

    prompt = PromptLoader.load(
        "batch_reasonability_audit",
        novel_outline=novel_outline,
        new_novel_worldview=new_novel_worldview,
        volume_outline=vol_outline,
        volume_worldview=vol_worldview,
        rewrite_map=rewrite_map,
        batch_index=batch_idx,
        start_chapter=start_ch,
        end_chapter=end_ch,
        previous_batch=previous_batch,
        adapted_reference_batch=adapted_reference_batch or "（无适配后的参考批次草稿）",
        reference_batch=reference_batch or "（无参考批次数据）",
        batch_summary=batch_summary,
    )
    raw = normalize_text(llm.generate(prompt))
    audit_path = _batch_audit_path(ws, volume, batch_idx, start_ch, end_ch, attempt)
    _write_file(audit_path, raw)

    try:
        audit = parse_json_response(raw)
    except Exception as e:
        append_adaptation_report(
            ws,
            f"卷{volume}批次{batch_idx}合理性审计解析失败",
            f"文件：{audit_path}\n错误：{e}",
        )
        return {
            "pass": True,
            "score": 0,
            "violations": [],
            "rewrite_instruction": "",
        }

    audit.setdefault("pass", True)
    audit.setdefault("score", 0)
    audit.setdefault("violations", [])
    audit.setdefault("rewrite_instruction", "")
    return audit


def _generate_batch_summary_with_audit(ws, llm, volume, batch_idx, start_ch, end_ch,
                                       vol_outline, vol_worldview, previous_batch,
                                       reference_batch, adapted_reference_batch,
                                       rewrite_map, forbidden_terms):
    forbidden_terms_text = (
        "正式批次摘要阶段不使用静态禁用词表做判断。"
        "请以新小说全书大纲、本卷卷纲、本卷世界观和换皮映射表为准，"
        "确保参考批次只提供节奏和情节功能，不把旧世界因果写成当前新小说事实。"
        "生成后会由 pro 模型进行剧情合理性审计。"
    )
    previous_result = ""
    audit_feedback = ""
    result = ""
    audit = {"pass": True, "violations": [], "rewrite_instruction": ""}

    for attempt in range(2):
        prompt = PromptLoader.load(
            "novel_batch_summary",
            volume_outline=vol_outline,
            volume_worldview=vol_worldview,
            rewrite_map=rewrite_map,
            forbidden_terms=forbidden_terms_text,
            batch_index=batch_idx,
            start_chapter=start_ch,
            end_chapter=end_ch,
            previous_batch=previous_batch,
            adapted_reference_batch=adapted_reference_batch or "（无适配后的参考批次草稿）",
            reference_batch=reference_batch or "（无参考批次数据）",
            audit_feedback=audit_feedback,
            previous_result=previous_result,
        )
        result = normalize_text(llm.generate(prompt))
        audit = _audit_batch_summary_reasonability(
            ws=ws,
            llm=llm,
            volume=volume,
            batch_idx=batch_idx,
            start_ch=start_ch,
            end_ch=end_ch,
            vol_outline=vol_outline,
            vol_worldview=vol_worldview,
            previous_batch=previous_batch,
            reference_batch=reference_batch,
            adapted_reference_batch=adapted_reference_batch,
            rewrite_map=rewrite_map,
            batch_summary=result,
            attempt=attempt + 1,
        )
        if audit.get("pass"):
            return result

        violations = audit.get("violations") or []
        issue_text = "；".join(
            f"{item.get('type', 'unknown')}: {item.get('reason', item.get('text', ''))}"
            if isinstance(item, dict) else str(item)
            for item in violations
        )
        print(f"  新批次摘要剧情合理性审计未通过，尝试重写：{issue_text or '未给出具体原因'}")
        previous_result = f"【上次生成结果】\n{result}"
        rewrite_instruction = audit.get("rewrite_instruction") or "请根据审计意见修正世界观冲突、旧因果残留或阶段不合理问题。"
        audit_feedback = (
            f"【上次批次摘要剧情合理性审计未通过】\n"
            f"审计问题：{issue_text or '未给出具体原因'}\n"
            f"重写指令：{rewrite_instruction}\n"
            "请保留参考节奏和情节功能，但必须让事件、人物、因果和阶段进展符合当前新小说大纲与世界观。"
        )

    if not audit.get("pass"):
        append_adaptation_report(
            ws,
            f"卷{volume}批次{batch_idx}批次摘要合理性审计未通过",
            f"审计结果：{audit}\n最后一次结果仍已返回供人工检查。",
        )
    return result



def _generate_story_arc(ws, llm, volume, arc_idx, start_ch, end_ch,
                        generation_context, target_char_count, cancel_event=None):
    """只基于长线、前后舞台和对应参考卷故事片段生成当前单元。"""
    prompt = PromptLoader.load(
        "novel_story_arc",
        **generation_context,
        arc_index=arc_idx,
        start_chapter=start_ch,
        end_chapter=end_ch,
        target_char_count=target_char_count,
        target_field_chars=max(30, round(target_char_count / 10)),
    )
    result = normalize_text(_generate_with_cancel(llm, prompt, cancel_event))
    return _compact_story_arc_result(
        llm, result, arc_idx, start_ch, end_ch, target_char_count, cancel_event,
    )


def _load_volume_outline_context(ws, volume):
    """加载当前舞台/旧卷纲上下文，并推断总章数。"""
    stage_context = _load_stage_context(ws, volume)
    if stage_context:
        return stage_context

    vol_outline_file = os.path.join(ws.file_system, "new_volume_outlines", f"vol_{volume:02d}_outline.md")
    vol_outline = _read_file(vol_outline_file)
    if not vol_outline:
        print(f"错误：未找到舞台{volume}，也未找到卷{volume}的旧卷纲文件：{vol_outline_file}")
        print("新流程请先运行 novel-outline 生成 stage_roadmap.md，并确保对应舞台存在。")
        return None

    vol_wv_file = os.path.join(ws.file_system, "new_worldviews", f"vol_{volume:02d}_worldview.md")
    vol_worldview = _read_file(vol_wv_file)
    if not vol_worldview:
        print(f"错误：未找到卷{volume}的世界观文件：{vol_wv_file}")
        print("请先运行 volume-outline 命令生成卷纲和世界观。")
        return None

    chapter_nums = re.findall(r'第(\d+)章', vol_outline)
    if not chapter_nums:
        print("错误：无法从卷纲中推断总章数。")
        return None

    return vol_outline, vol_worldview, max(int(c) for c in chapter_nums)


def gen_story_arcs(ws, volume=1, force=False, progress_callback=None, pause_event=None,
                   stop_event=None, cancel_event=None):
    """基于当前舞台设计生成新书故事情节单元。

    返回结果字典：
    - 成功：{"artifacts": [...], "adjustment_note": "..."}
    - 失败：{"error": "...", "artifacts": []}
    """
    context = _load_volume_outline_context(ws, volume)
    if not context:
        return {"error": f"未找到舞台{volume}的上下文，请先在舞台设计步骤生成 stage_roadmap.md，确保对应舞台存在且包含预计章节数。", "artifacts": []}
    _, _, total_chapters = context
    if progress_callback:
        progress_callback("preparing", 0, 0, "正在读取长线主线、舞台与对应参考故事片段")

    llm = _get_lite_llm()
    if not llm:
        return {"error": "未配置可用模型，请先在右上角配置大模型 API。", "artifacts": []}

    generation_context = _simple_story_arc_context(ws, volume)
    print(f"  -> 已读取舞台{volume}的简化故事情节输入（不再生成压缩上下文）。")

    arc_plans = _plan_story_arcs(total_chapters)
    target_char_count = _reference_story_arc_average_chars(ws, volume)
    total_arcs = len(arc_plans)
    story_arc_dir = _volume_story_arc_dir(ws, volume)
    if force:
        _clear_story_arc_files(ws, volume)
    os.makedirs(story_arc_dir, exist_ok=True)

    print(
        f">>> 串行生成卷{volume}的故事情节单元"
        f"（共{total_chapters}章，规划{len(arc_plans)}个情节单元，"
        f"每个约{target_char_count}字）<<<"
    )

    generated_items = []
    for plan in arc_plans:
        if stop_event is not None and stop_event.is_set():
            break
        if pause_event is not None:
            if not pause_event.is_set() and progress_callback:
                progress_callback(
                    "paused", len(generated_items), total_arcs,
                    "已暂停；点击继续后从下一个故事情节接着生成",
                )
            pause_event.wait()
        if stop_event is not None and stop_event.is_set():
            break
        arc_idx = plan["idx"]
        start_ch = plan["start_ch"]
        end_ch = plan["end_ch"]
        if progress_callback:
            progress_callback(
                "generating", len(generated_items), total_arcs,
                f"正在生成情节单元{arc_idx}（第{start_ch}-{end_ch}章）",
            )
        arc_file = _story_arc_path(ws, volume, arc_idx, start_ch, end_ch)
        arc_name = _story_arc_file_name(arc_idx, start_ch, end_ch)
        existing = _read_file(arc_file)
        if existing and not force:
            print(f"  情节单元{arc_idx}（第{start_ch}-{end_ch}章）已存在，跳过。")
            generated_items.append({
                "idx": arc_idx,
                "start_ch": start_ch,
                "end_ch": end_ch,
                "file": arc_name,
                "path": arc_file,
                "content": existing,
            })
            if progress_callback:
                progress_callback(
                    "generating", len(generated_items), total_arcs,
                    f"情节单元{arc_idx}已存在，继续处理下一单元",
                )
            continue

        print(f"  生成故事情节单元{arc_idx}（第{start_ch}-{end_ch}章）...")
        while True:
            try:
                result = _generate_story_arc(
                    ws=ws,
                    llm=llm,
                    volume=volume,
                    arc_idx=arc_idx,
                    start_ch=start_ch,
                    end_ch=end_ch,
                    generation_context=generation_context,
                    target_char_count=target_char_count,
                    cancel_event=cancel_event,
                )
                break
            except LLMCallCancelled:
                if stop_event is not None and stop_event.is_set():
                    result = None
                    break
                if progress_callback:
                    progress_callback(
                        "paused", len(generated_items), total_arcs,
                        "模型请求已暂停；点击继续将重新生成当前情节",
                    )
                if pause_event is not None:
                    pause_event.wait()
                if cancel_event is not None:
                    cancel_event.clear()
        if result is None:
            break
        _write_file(arc_file, result)
        generated_items.append({
            "idx": arc_idx,
            "start_ch": start_ch,
            "end_ch": end_ch,
            "file": arc_name,
            "path": arc_file,
            "content": result,
        })
        if progress_callback:
            progress_callback(
                "generating", len(generated_items), total_arcs,
                f"情节单元{arc_idx}已完成",
            )
        print(f"  -> 故事情节单元{arc_idx}已保存：{arc_file}")

    _write_story_arc_index(ws, volume, generated_items)
    stopped = stop_event is not None and stop_event.is_set()
    if progress_callback:
        progress_callback(
            "stopped" if stopped else "completed",
            len(generated_items), total_arcs,
            "已结束本轮生成，已完成内容均已保留" if stopped else "全部故事情节单元已完成",
        )
    print(f"\n>>> 卷{volume}故事情节单元已生成，共 {len(generated_items)} 个。<<<")

    artifacts = [
        {
            "path": f"file_system/story_arcs/vol_{volume:02d}/{item['file']}",
            "label": f"情节单元{item['idx']}（第{item['start_ch']}-{item['end_ch']}章）",
        }
        for item in generated_items
    ]
    return {
        "artifacts": artifacts,
        "adjustment_note": (
            f"已结束本轮生成，保留 {len(generated_items)} 个故事情节单元。"
            if stopped else f"已生成卷{volume}的故事情节单元，共 {len(generated_items)} 个。"
        ),
        "stopped": stopped,
    }


def refine_story_arcs(ws, volume, instruction, cancel_event=None):
    """基于用户指令调整指定舞台/卷的所有故事情节单元。"""
    print(f">>> 调整卷{volume}故事情节单元 <<<")
    arcs = _list_novel_story_arcs(ws, volume)
    if not arcs:
        print("错误：该卷还没有故事情节单元，请先在聊天框中生成。")
        return {}

    llm = _get_lite_llm()
    if not llm:
        return {}

    generation_context = _simple_story_arc_context(ws, volume)

    current_text = "\n\n===\n\n".join(arc["content"] for arc in arcs)
    prompt = PromptLoader.load(
        "story_arcs_refine",
        **generation_context,
        current_arcs=current_text,
        instruction=instruction,
    )
    raw = normalize_text(_generate_with_cancel(llm, prompt, cancel_event, temperature=0.3))

    # 按分隔符拆分，逐个写回
    segments = [seg.strip() for seg in raw.split("===") if seg.strip()]
    # 备份旧文件
    import time as _time
    stamp = _time.strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(_volume_story_arc_dir(ws, volume), "versions")
    os.makedirs(backup_dir, exist_ok=True)
    for arc in arcs:
        backup_path = os.path.join(backup_dir, f"{arc['file']}_{stamp}")
        os.rename(arc["path"], backup_path) if os.path.exists(arc["path"]) else None

    written = []
    for idx, seg in enumerate(segments):
        if idx < len(arcs):
            arc = arcs[idx]
        else:
            # 新增的单元
            arc = {"file": f"arc_{idx + 1}_ch{'?'}_{'?'}.md"}
        # 从第一行提取章节范围
        first_line = seg.split("\n")[0] if "\n" in seg else seg.split("\n")[0]
        range_match = re.search(r'第(\d+)-(\d+)章', first_line)
        if range_match:
            start_ch = int(range_match.group(1))
            end_ch = int(range_match.group(2))
        elif idx < len(arcs):
            start_ch = arcs[idx]["start_ch"]
            end_ch = arcs[idx]["end_ch"]
        else:
            continue
        arc_idx_num = idx + 1
        arc_path = _story_arc_path(ws, volume, arc_idx_num, start_ch, end_ch)
        arc_name = _story_arc_file_name(arc_idx_num, start_ch, end_ch)
        _write_file(arc_path, seg)
        written.append({"label": f"情节单元{arc_idx_num}（第{start_ch}-{end_ch}章）",
                        "path": f"file_system/story_arcs/vol_{volume:02d}/{arc_name}"})
        print(f"  -> 情节单元{arc_idx_num}已更新：{arc_path}")

    # 更新索引
    updated_items = []
    for idx, seg in enumerate(segments):
        if idx < len(arcs):
            updated_items.append({"idx": idx + 1, "start_ch": arcs[idx]["start_ch"], "end_ch": arcs[idx]["end_ch"], "file": arcs[idx]["file"]})
    if updated_items:
        _write_story_arc_index(ws, volume, updated_items)

    return {"adjustment_note": f"已按指令调整 {len(written)} 个情节单元。", "artifacts": written}


def _normalize_refinement_mode(value, instruction):
    """将路由器返回值归一为 regenerate/revise，并为旧模型输出提供兜底。"""
    normalized = str(value or "").strip().lower()
    if normalized in {"regenerate", "rewrite", "重新生成", "完全重写"}:
        return "regenerate"
    if normalized in {"revise", "adjust", "修改", "调整", "优化"}:
        return "revise"
    compact = re.sub(r"\s+", "", str(instruction or ""))
    regenerate_markers = ("重新生成", "完全重写", "推倒重来", "从头生成", "重新写一版", "重写一版")
    return "regenerate" if any(marker in compact for marker in regenerate_markers) else "revise"


def _route_story_arc_refinement(llm, arcs, instruction, cancel_event=None):
    current_arcs = "\n\n===\n\n".join(arc["content"] for arc in arcs)
    prompt = PromptLoader.load(
        "story_arc_refine_route",
        current_arcs=current_arcs,
        instruction=instruction,
    )
    raw = normalize_text(_generate_with_cancel(llm, prompt, cancel_event, temperature=0.2))
    routed = parse_json_response(raw)
    if not isinstance(routed, dict):
        routed = {}
    existing_ids = {arc["idx"] for arc in arcs}
    try:
        start_arc = int(routed.get("start_arc"))
    except (TypeError, ValueError, AttributeError):
        start_arc = min(existing_ids)
    if start_arc not in existing_ids:
        start_arc = min(existing_ids)
    mode = _normalize_refinement_mode(routed.get("mode"), instruction)
    return start_arc, mode, str(routed.get("reason") or "按用户指令定位最早受影响情节。")


def _serial_refinement_targets(ws, volume, arcs, start_arc):
    """合并已生成情节与本卷完整计划，使调整后可以继续生成缺失单元。"""
    context = _load_volume_outline_context(ws, volume)
    if not context:
        return []
    _, _, total_chapters = context
    existing = {arc["idx"]: arc for arc in arcs}
    targets = []
    for plan in _plan_story_arcs(total_chapters):
        if plan["idx"] < start_arc:
            continue
        saved = existing.get(plan["idx"])
        targets.append({
            **plan,
            "file": saved["file"] if saved else _story_arc_file_name(
                plan["idx"], plan["start_ch"], plan["end_ch"],
            ),
            "path": saved["path"] if saved else _story_arc_path(
                ws, volume, plan["idx"], plan["start_ch"], plan["end_ch"],
            ),
            "content": saved["content"] if saved else "（该情节单元尚未生成，请根据前序最新状态和用户指令创建。）",
            "existed": bool(saved),
        })
    return targets


def refine_story_arcs_serial(ws, volume, instruction, progress_callback=None,
                             pause_event=None, stop_event=None, cancel_event=None):
    """先路由调整起点，再从该单元开始串行重生成后续情节。"""
    arcs = _list_novel_story_arcs(ws, volume)
    if not arcs:
        return {"error": "该卷还没有故事情节单元。", "artifacts": []}
    llm = _get_lite_llm()
    if not llm:
        return {"error": "未配置可用模型。", "artifacts": []}

    if progress_callback:
        progress_callback("routing", 0, len(arcs), "正在分析用户指令影响的最早情节单元")
    while True:
        try:
            start_arc, refinement_mode, route_reason = _route_story_arc_refinement(
                llm, arcs, instruction, cancel_event,
            )
            break
        except LLMCallCancelled:
            if stop_event is not None and stop_event.is_set():
                return {"artifacts": [], "adjustment_note": "已结束本轮调整，原有内容保持不变。", "stopped": True}
            if progress_callback:
                progress_callback("paused", 0, len(arcs), "范围分析已暂停；点击继续将重新分析")
            if pause_event is not None:
                pause_event.wait()
            if cancel_event is not None:
                cancel_event.clear()

    targets = _serial_refinement_targets(ws, volume, arcs, start_arc)
    if not targets:
        return {"error": "无法读取当前卷的完整情节规划。", "artifacts": []}
    target_char_count = _reference_story_arc_average_chars(ws, volume)
    generation_context = _simple_story_arc_context(ws, volume)
    generated_by_idx = {arc["idx"]: arc["content"] for arc in arcs if arc["idx"] < start_arc}
    written = []
    import shutil
    import time as _time
    stamp = _time.strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(_volume_story_arc_dir(ws, volume), "versions")
    os.makedirs(backup_dir, exist_ok=True)

    for target in targets:
        if stop_event is not None and stop_event.is_set():
            break
        if pause_event is not None:
            if not pause_event.is_set() and progress_callback:
                progress_callback("paused", len(written), len(targets), "已暂停串行调整")
            pause_event.wait()
        if stop_event is not None and stop_event.is_set():
            break

        previous = generated_by_idx.get(target["idx"] - 1) or "（这是当前卷第一个情节单元）"
        action_label = (
            "基于原内容调整"
            if target["existed"] and refinement_mode == "revise"
            else "完全重新生成"
            if target["existed"]
            else "继续生成"
        )
        if progress_callback:
            progress_callback(
                "refining", len(written), len(targets),
                f"路由结果：从情节单元{start_arc}开始；正在{action_label}情节单元{target['idx']}",
            )
        prompt = PromptLoader.load(
            "story_arc_serial_refine",
            **generation_context,
            instruction=instruction,
            previous_story_arc=previous,
            current_story_arc=(
                target["content"]
                if refinement_mode == "revise"
                else "（本轮为完全重新生成，不提供当前单元旧版本，也不得臆测或复原旧文。）"
            ),
            arc_index=target["idx"],
            start_chapter=target["start_ch"],
            end_chapter=target["end_ch"],
            target_char_count=target_char_count,
        )
        while True:
            try:
                result = normalize_text(_generate_with_cancel(llm, prompt, cancel_event, temperature=0.3))
                result = _compact_story_arc_result(
                    llm, result, target["idx"], target["start_ch"], target["end_ch"],
                    target_char_count, cancel_event,
                )
                break
            except LLMCallCancelled:
                if stop_event is not None and stop_event.is_set():
                    result = None
                    break
                if progress_callback:
                    progress_callback(
                        "paused", len(written), len(targets),
                        f"情节单元{target['idx']}调整已暂停；继续后重新生成本单元",
                    )
                if pause_event is not None:
                    pause_event.wait()
                if cancel_event is not None:
                    cancel_event.clear()
        if result is None:
            break

        backup_path = os.path.join(backup_dir, f"{target['file']}_{stamp}")
        if target["existed"] and not os.path.exists(backup_path):
            shutil.copy2(target["path"], backup_path)
        _write_file(target["path"], result)
        generated_by_idx[target["idx"]] = result
        written.append({
            "label": f"情节单元{target['idx']}（第{target['start_ch']}-{target['end_ch']}章）",
            "path": f"file_system/story_arcs/vol_{volume:02d}/{target['file']}",
        })
        if progress_callback:
            progress_callback(
                "refining", len(written), len(targets),
                f"情节单元{target['idx']}{action_label}完成",
            )

    stopped = stop_event is not None and stop_event.is_set()
    current_items = _list_novel_story_arcs(ws, volume)
    if current_items:
        _write_story_arc_index(ws, volume, current_items)
    return {
        "adjustment_note": (
            f"已结束本轮处理；从情节单元{start_arc}开始，完成 {len(written)}/{len(targets)} 个。"
            if stopped
            else (
                f"已按指令从情节单元{start_arc}开始串行处理 {len(written)} 个情节单元，"
                f"并补齐此前未生成的后续单元。处理方式："
                f"{'完全重新生成' if refinement_mode == 'regenerate' else '基于当前内容调整'}。"
                f"路由原因：{route_reason}"
            )
        ),
        "artifacts": written,
        "stopped": stopped,
        "start_arc": start_arc,
        "mode": refinement_mode,
        "total_adjusted": len(targets),
    }


STORY_LINE_LIMIT = 100  # 章纲「故事线」字数上限：避免逐章串行生成时越写越长。


def _truncate_plus_chain(content, limit):
    """把「A+B+C」式内容截到 limit 字以内，优先在 + 边界切，保留尽量多的完整节点。"""
    content = (content or "").strip()
    if len(content) <= limit:
        return content
    parts = [part.strip() for part in content.split("+") if part.strip()]
    if len(parts) <= 1:
        return content[:limit].strip()
    kept = ""
    for part in parts:
        candidate = part if not kept else kept + "+" + part
        if len(candidate) <= limit:
            kept = candidate
        else:
            break
    return kept or content[:limit].strip()


def _cap_story_line_in_outline(text, limit=STORY_LINE_LIMIT):
    """把章纲里「# 故事线」一节的内容截到 limit 字以内；其余部分（单章节奏、单章简介等）原样保留。

    用于在章纲写盘前强制约束故事线长度，避免模型逐章生成、参考前序章纲时把故事线越写越长。
    找不到「# 故事线」一节则原样返回。幂等。
    """
    if not text:
        return text
    lines = text.splitlines()
    header_idx = None
    same_line = ""
    for idx, line in enumerate(lines):
        match = re.match(r"^\s*#{0,6}\s*故事线\s*[:：]?\s*(.*)$", line)
        if match:
            header_idx = idx
            same_line = (match.group(1) or "").strip()
            break
    if header_idx is None:
        return text
    body = []
    if same_line:
        body.append(same_line)
    end = len(lines)
    for j in range(header_idx + 1, len(lines)):
        # 故事线一节到下一个标题（# / 【）为止。
        if re.match(r"^\s*(?:#{1,6}\s+\S|【)", lines[j]):
            end = j
            break
        if lines[j].strip():
            body.append(lines[j].strip())
    content = " ".join(body)
    if len(content) <= limit:
        return text
    capped = _truncate_plus_chain(content, limit)
    header_clean = re.match(r"\s*#{0,6}\s*故事线", lines[header_idx]).group(0)
    new_lines = lines[:header_idx] + [header_clean, capped] + lines[end:]
    return "\n".join(new_lines)


def gen_serial_chapter_outlines(ws, volume=1, force=False):
    """基于已生成的新书故事情节单元，串行生成本卷逐章章纲。"""
    context = _load_volume_outline_context(ws, volume)
    if not context:
        return
    _, _, total_chapters = context

    ch_out_dir = os.path.join(ws.file_system, "chapter_outlines", f"vol_{volume:02d}")
    story_arcs = _list_novel_story_arcs(ws, volume)
    if not story_arcs:
        print("错误：未找到故事情节单元，无法生成章纲。请先运行 story-arcs。")
        return

    llm = _get_lite_llm()
    if not llm:
        return
    _ensure_system_panel_decision(ws)
    sync_finalized_drafts_for_outlines(
        llm, ws, volume, total_chapters,
    )
    print(f">>> 串行生成卷{volume}的章纲 <<<")
    os.makedirs(ch_out_dir, exist_ok=True)

    for arc in story_arcs:
        arc_start = arc["start_ch"]
        arc_end = arc["end_ch"]
        arc_content = arc["content"]
        if not arc_content:
            print(f"  警告：故事情节单元 {arc['file']} 为空，跳过。")
            continue

        print(f"\n  --- 故事情节单元{arc['idx']}：第{arc_start}-{arc_end}章 ---")

        for ch_num in range(arc_start, arc_end + 1):
            out_file = os.path.join(ch_out_dir, f"chapter_{ch_num:03d}.md")
            if os.path.exists(out_file) and not force:
                print(f"  第{ch_num}章章纲已存在，跳过。")
                continue

            # 只读取紧邻的上一章章纲，避免重复携带更早内容。
            previous_text = _read_file(
                os.path.join(ch_out_dir, f"chapter_{ch_num - 1:03d}.md")
            ) if ch_num > 1 else ""
            previous_text = re.sub(
                r'\n?\[(?:FINISHED|CONTINUE)\]\s*$', '', previous_text or "",
            ).strip() or "（这是第一章，无上一章章纲）"

            print(f"  生成第{ch_num}章章纲...")
            prompt = PromptLoader.load(
                "serial_chapter_outline",
                previous_system_panel=json.dumps(
                    _previous_system_panel(ws, volume, ch_num), ensure_ascii=False, indent=2,
                ),
                story_arc=arc_content,
                previous_chapter_outline=previous_text,
                chapter_num=ch_num,
            )
            result = normalize_text(llm.generate(prompt))
            _generate_chapter_system_panel(llm, ws, volume, ch_num, result)
            result = _cap_story_line_in_outline(result)
            _write_file(out_file, result)
            print(f"  -> 第{ch_num}章章纲已保存：{out_file}")

    print(f"\n>>> 卷{volume}全部 {total_chapters} 章章纲已生成。<<<")


def chapter_outline_resume_status(ws, volume, arc_idx):
    """返回指定情节单元的章纲断点，供服务重启或页面刷新后继续。"""
    target_arc = next(
        (arc for arc in _list_novel_story_arcs(ws, volume) if arc["idx"] == arc_idx),
        None,
    )
    if not target_arc:
        return {"can_resume": False, "completed": 0, "total": 0, "next_chapter": None}
    ch_out_dir = os.path.join(ws.file_system, "chapter_outlines", f"vol_{volume:02d}")
    chapter_nums = list(range(target_arc["start_ch"], target_arc["end_ch"] + 1))
    panel_status = system_panel_status(ws)
    panel_required = panel_status["enabled"] or not panel_status["decided"]
    has_any_outline = any(
        _read_file(os.path.join(ch_out_dir, f"chapter_{ch:03d}.md"))
        for ch in chapter_nums
    )
    existing = [
        ch for ch in chapter_nums
        if (
            _read_file(os.path.join(ch_out_dir, f"chapter_{ch:03d}.md"))
            and (
                ch in _finalized_chapter_numbers(ws, "outlines", volume)
                or
                not panel_required
                or _read_json_file(_system_panel_chapter_path(ws, volume, ch))
            )
        )
    ]
    missing = [ch for ch in chapter_nums if ch not in existing]
    return {
        "can_resume": bool(has_any_outline and missing),
        "completed": len(existing),
        "total": len(chapter_nums),
        "next_chapter": missing[0] if missing else None,
    }


def gen_chapter_outlines_for_arc(ws, volume, arc_idx, progress_callback=None,
                                 pause_event=None, stop_event=None, cancel_event=None):
    """为指定舞台/卷的单个故事情节单元生成逐章章纲。"""
    context = _load_volume_outline_context(ws, volume)
    if not context:
        return {}
    _, _, total_chapters = context

    story_arcs = _list_novel_story_arcs(ws, volume)
    target_arc = None
    for arc in story_arcs:
        if arc["idx"] == arc_idx:
            target_arc = arc
            break
    if not target_arc:
        print(f"错误：未找到卷{volume}的故事情节单元{arc_idx}。")
        return {}

    llm = _get_lite_llm()
    if not llm:
        return {}

    while True:
        try:
            if progress_callback:
                progress_callback("system_panel_setup", 0, 0, "正在确认是否需要系统面板")
            _ensure_system_panel_decision(ws, cancel_event)
            break
        except LLMCallCancelled:
            if stop_event is not None and stop_event.is_set():
                return {"adjustment_note": "已结束本轮生成。", "artifacts": [], "stopped": True}
            if progress_callback:
                progress_callback("paused", 0, 0, "系统面板判断已暂停；继续后重新判断")
            if pause_event is not None:
                pause_event.wait()
            if cancel_event is not None:
                cancel_event.clear()

    ch_out_dir = os.path.join(ws.file_system, "chapter_outlines", f"vol_{volume:02d}")
    os.makedirs(ch_out_dir, exist_ok=True)
    sync_finalized_drafts_for_outlines(
        llm, ws, volume, target_arc["end_ch"], progress_callback,
        pause_event, stop_event, cancel_event,
    )
    if stop_event is not None and stop_event.is_set():
        return {"adjustment_note": "已结束本轮生成。", "artifacts": [], "stopped": True}
    arc_start = target_arc["start_ch"]
    arc_end = target_arc["end_ch"]
    arc_content = target_arc["content"]
    print(f">>> 生成卷{volume}情节单元{arc_idx}（第{arc_start}-{arc_end}章）的章纲 <<<")

    written = []
    finalized = _finalized_chapter_numbers(ws, "outlines", volume)
    for ch_num in range(arc_start, arc_end + 1):
        out_file = os.path.join(ch_out_dir, f"chapter_{ch_num:03d}.md")
        existing = _read_file(out_file)
        if existing:
            if ch_num in finalized:
                written.append({
                    "label": f"第{ch_num}章章纲",
                    "path": f"file_system/chapter_outlines/vol_{volume:02d}/chapter_{ch_num:03d}.md",
                })
                continue
            panel_required = system_panel_status(ws)["enabled"]
            panel_exists = _read_json_file(_system_panel_chapter_path(ws, volume, ch_num))
            if not panel_required or panel_exists:
                written.append({
                    "label": f"第{ch_num}章章纲",
                    "path": f"file_system/chapter_outlines/vol_{volume:02d}/chapter_{ch_num:03d}.md",
                })
                continue
        if stop_event is not None and stop_event.is_set():
            break
        if pause_event is not None:
            if not pause_event.is_set() and progress_callback:
                progress_callback("paused", len(written), arc_end - arc_start + 1, "章纲生成已暂停")
            pause_event.wait()
        if stop_event is not None and stop_event.is_set():
            break
        previous_text = _read_file(
            os.path.join(ch_out_dir, f"chapter_{ch_num - 1:03d}.md")
        ) if ch_num > 1 else ""
        previous_text = re.sub(
            r'\n?\[(?:FINISHED|CONTINUE)\]\s*$', '', previous_text or "",
        ).strip() or "（这是第一章，无上一章章纲）"

        print(f"  生成第{ch_num}章章纲...")
        prompt = PromptLoader.load(
            "serial_chapter_outline",
            previous_system_panel=json.dumps(
                _previous_system_panel(ws, volume, ch_num), ensure_ascii=False, indent=2,
            ),
            story_arc=arc_content,
            previous_chapter_outline=previous_text,
            chapter_num=ch_num,
        )
        if progress_callback:
            progress_callback(
                "generating", len(written), arc_end - arc_start + 1,
                f"正在生成第{ch_num}章章纲",
            )
        while True:
            try:
                result = normalize_text(
                    _generate_with_cancel(llm, prompt, cancel_event, temperature=0.7)
                )
                break
            except LLMCallCancelled:
                if stop_event is not None and stop_event.is_set():
                    result = None
                    break
                if progress_callback:
                    progress_callback(
                        "paused", len(written), arc_end - arc_start + 1,
                        f"第{ch_num}章生成已暂停；继续后重新生成本章",
                    )
                if pause_event is not None:
                    pause_event.wait()
                if cancel_event is not None:
                    cancel_event.clear()
        if result is None:
            break
        if not _update_chapter_system_panel_with_controls(
            llm, ws, volume, ch_num, result, len(written),
            arc_end - arc_start + 1, progress_callback, pause_event,
            stop_event, cancel_event,
        ):
            break
        result = _cap_story_line_in_outline(result)
        _write_file(out_file, result)
        written.append({
            "label": f"第{ch_num}章章纲",
            "path": f"file_system/chapter_outlines/vol_{volume:02d}/chapter_{ch_num:03d}.md",
        })
        if progress_callback:
            progress_callback(
                "generating", len(written), arc_end - arc_start + 1,
                f"第{ch_num}章章纲已写入",
            )
        print(f"  -> 第{ch_num}章章纲已保存：{out_file}")

    stopped = stop_event is not None and stop_event.is_set()
    return {
        "adjustment_note": (
            f"已结束本轮生成，已保留 {len(written)}/{arc_end - arc_start + 1} 章。"
            if stopped else f"已生成第{arc_start}-{arc_end}章的逐章章纲。"
        ),
        "artifacts": written,
        "stopped": stopped,
    }


def _route_chapter_outline_refinement(llm, outlines, instruction, start_ch, end_ch,
                                      cancel_event=None):
    current_text = "\n\n===\n\n".join(
        f"【第{chapter_num}章】\n{content}"
        for chapter_num, content in outlines
    )
    prompt = PromptLoader.load(
        "chapter_outline_refine_route",
        start_chapter=start_ch,
        end_chapter=end_ch,
        current_outlines=current_text or "（当前尚无章纲）",
        instruction=instruction,
    )
    raw = normalize_text(_generate_with_cancel(llm, prompt, cancel_event, temperature=0.2))
    routed = parse_json_response(raw)
    if not isinstance(routed, dict):
        routed = {}
    try:
        requested_chapter = int(routed.get("start_chapter"))
    except (TypeError, ValueError, AttributeError):
        requested_chapter = start_ch
    routed_chapter = min(end_ch, max(start_ch, requested_chapter))
    reason = str(routed.get("reason") or "按用户指令定位最早受影响章节。")
    if requested_chapter < start_ch:
        reason = f"第{start_ch - 1}章及之前已由最终版正文同步并锁定，可编辑范围从第{start_ch}章开始。"
    mode = _normalize_refinement_mode(routed.get("mode"), instruction)
    return routed_chapter, mode, reason


def refine_chapter_outlines_serial(ws, volume, arc_idx, instruction, progress_callback=None,
                                   pause_event=None, stop_event=None, cancel_event=None):
    """路由最早受影响章节，并从该章串行重生成到情节单元末章。"""
    target_arc = next(
        (arc for arc in _list_novel_story_arcs(ws, volume) if arc["idx"] == arc_idx),
        None,
    )
    if not target_arc:
        return {"error": f"未找到卷{volume}的故事情节单元{arc_idx}。", "artifacts": []}
    llm = _get_lite_llm()
    if not llm:
        return {"error": "未配置可用模型。", "artifacts": []}
    while True:
        try:
            if progress_callback:
                progress_callback("system_panel_setup", 0, 0, "正在确认是否需要系统面板")
            _ensure_system_panel_decision(ws, cancel_event)
            break
        except LLMCallCancelled:
            if stop_event is not None and stop_event.is_set():
                return {"adjustment_note": "已结束本轮调整。", "artifacts": [], "stopped": True}
            if progress_callback:
                progress_callback("paused", 0, 0, "系统面板判断已暂停；继续后重新判断")
            if pause_event is not None:
                pause_event.wait()
            if cancel_event is not None:
                cancel_event.clear()
    ch_out_dir = os.path.join(ws.file_system, "chapter_outlines", f"vol_{volume:02d}")
    os.makedirs(ch_out_dir, exist_ok=True)
    start_ch, end_ch = target_arc["start_ch"], target_arc["end_ch"]
    sync_finalized_drafts_for_outlines(
        llm, ws, volume, end_ch, progress_callback,
        pause_event, stop_event, cancel_event,
    )
    if stop_event is not None and stop_event.is_set():
        return {"adjustment_note": "已结束本轮调整。", "artifacts": [], "stopped": True}
    finalized_boundary = _finalized_chapter_boundary(
        ws, "outlines", volume, start_ch, end_ch,
    )
    editable_start = max(start_ch, finalized_boundary + 1)
    if editable_start > end_ch:
        return {
            "adjustment_note": (
                f"第{start_ch}-{end_ch}章均已由最终版正文同步并锁定，"
                "本轮未修改章纲。"
            ),
            "artifacts": [],
            "stopped": False,
            "start_chapter": None,
            "total_adjusted": 0,
        }
    outlines = []
    for ch_num in range(editable_start, end_ch + 1):
        content = _read_file(os.path.join(ch_out_dir, f"chapter_{ch_num:03d}.md"))
        if content:
            outlines.append((ch_num, content))
    if not outlines:
        return {"error": "该情节单元还没有章纲，请先生成。", "artifacts": []}

    if progress_callback:
        progress_callback(
            "routing", 0, len(outlines),
            f"正在第{editable_start}-{end_ch}章可编辑范围内判断调整起点",
        )
    generic_instruction = instruction.strip() in {"生成", "重新生成", "继续生成", "调整", "优化"}
    if generic_instruction:
        routed_chapter = editable_start
        refinement_mode = _normalize_refinement_mode(None, instruction)
        route_reason = (
            f"第{start_ch}-{editable_start - 1}章已由最终版正文同步并锁定；"
            f"用户未指定具体修改点，从第{editable_start}章开始处理可编辑范围。"
            if editable_start > start_ch else
            f"用户未指定具体修改点，从当前可编辑范围首章第{editable_start}章开始处理。"
        )
    else:
        while True:
            try:
                routed_chapter, refinement_mode, route_reason = _route_chapter_outline_refinement(
                    llm, outlines, instruction, editable_start, end_ch, cancel_event,
                )
                break
            except LLMCallCancelled:
                if stop_event is not None and stop_event.is_set():
                    return {"adjustment_note": "已结束本轮调整，原有章纲保持不变。", "artifacts": [], "stopped": True}
                if progress_callback:
                    progress_callback("paused", 0, len(outlines), "范围分析已暂停；继续后重新分析")
                if pause_event is not None:
                    pause_event.wait()
                if cancel_event is not None:
                    cancel_event.clear()

    finalized = _finalized_chapter_numbers(ws, "outlines", volume)
    finalized_boundary = _finalized_chapter_boundary(
        ws, "outlines", volume, start_ch, end_ch,
    )
    targets = [
        chapter for chapter in range(max(routed_chapter, finalized_boundary + 1), end_ch + 1)
        if chapter not in finalized
    ]
    written = []
    import shutil
    import time as _time
    stamp = _time.strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(ch_out_dir, "versions")
    os.makedirs(backup_dir, exist_ok=True)
    for ch_num in targets:
        if ch_num in _finalized_chapter_numbers(ws, "outlines", volume):
            continue
        if stop_event is not None and stop_event.is_set():
            break
        if pause_event is not None:
            if not pause_event.is_set() and progress_callback:
                progress_callback("paused", len(written), len(targets), "章纲调整已暂停")
            pause_event.wait()
        if stop_event is not None and stop_event.is_set():
            break
        previous = _read_file(os.path.join(ch_out_dir, f"chapter_{ch_num - 1:03d}.md"))
        current_path = os.path.join(ch_out_dir, f"chapter_{ch_num:03d}.md")
        current = _read_file(current_path)
        if progress_callback:
            progress_callback(
                "refining", len(written), len(targets),
                f"路由结果：从第{routed_chapter}章开始；正在处理第{ch_num}章",
            )
        prompt = PromptLoader.load(
            "chapter_outline_serial_refine",
            story_arc=target_arc["content"],
            instruction=instruction,
            previous_outline=previous or "（这是本情节单元的起始章）",
            previous_system_panel=json.dumps(
                _previous_system_panel(ws, volume, ch_num), ensure_ascii=False, indent=2,
            ),
            current_outline=(
                (current or "（该章尚未生成）")
                if refinement_mode == "revise"
                else "（本轮为完全重新生成，不提供当前章旧章纲，也不得臆测或复原旧文。）"
            ),
            chapter_num=ch_num,
        )
        while True:
            try:
                result = normalize_text(_generate_with_cancel(llm, prompt, cancel_event, temperature=0.3))
                break
            except LLMCallCancelled:
                if stop_event is not None and stop_event.is_set():
                    result = None
                    break
                if progress_callback:
                    progress_callback(
                        "paused", len(written), len(targets),
                        f"第{ch_num}章调整已暂停；继续后重新生成本章",
                    )
                if pause_event is not None:
                    pause_event.wait()
                if cancel_event is not None:
                    cancel_event.clear()
        if result is None:
            break
        if current:
            backup_path = os.path.join(backup_dir, f"chapter_{ch_num:03d}.md_{stamp}")
            if not os.path.exists(backup_path):
                shutil.copy2(current_path, backup_path)
        if not _update_chapter_system_panel_with_controls(
            llm, ws, volume, ch_num, result, len(written), len(targets),
            progress_callback, pause_event, stop_event, cancel_event,
        ):
            break
        result = _cap_story_line_in_outline(result)
        _write_file(current_path, result)
        written.append({
            "label": f"第{ch_num}章章纲",
            "path": f"file_system/chapter_outlines/vol_{volume:02d}/chapter_{ch_num:03d}.md",
        })
        if progress_callback:
            progress_callback("refining", len(written), len(targets), f"第{ch_num}章章纲已写入")

    stopped = stop_event is not None and stop_event.is_set()
    return {
        "adjustment_note": (
            f"已结束本轮调整；从第{routed_chapter}章开始，完成 {len(written)}/{len(targets)} 章。"
            if stopped else
            (
                f"已按指令从第{routed_chapter}章开始串行处理 {len(written)} 章。"
                f"处理方式：{'完全重新生成' if refinement_mode == 'regenerate' else '基于当前内容调整'}。"
                f"路由原因：{route_reason}"
            )
        ),
        "artifacts": written,
        "stopped": stopped,
        "start_chapter": routed_chapter,
        "mode": refinement_mode,
        "total_adjusted": len(targets),
    }


def refine_chapter_outlines(ws, volume, arc_idx, instruction):
    """基于用户指令调整指定情节单元的章纲。"""
    llm = _get_lite_llm()
    if not llm:
        return {}

    story_arcs = _list_novel_story_arcs(ws, volume)
    target_arc = None
    for arc in story_arcs:
        if arc["idx"] == arc_idx:
            target_arc = arc
            break
    if not target_arc:
        print(f"错误：未找到卷{volume}的故事情节单元{arc_idx}。")
        return {}

    arc_start = target_arc["start_ch"]
    arc_end = target_arc["end_ch"]
    ch_out_dir = os.path.join(ws.file_system, "chapter_outlines", f"vol_{volume:02d}")

    # 读取当前章纲
    outlines = []
    for ch_num in range(arc_start, arc_end + 1):
        out_file = os.path.join(ch_out_dir, f"chapter_{ch_num:03d}.md")
        content = _read_file(out_file)
        if content:
            outlines.append(content)
    if not outlines:
        print("错误：该情节单元还没有章纲，请先在聊天框中生成。")
        return {}

    current_text = "\n\n===\n\n".join(outlines)
    prompt = PromptLoader.load(
        "chapter_outlines_refine",
        story_arc=target_arc["content"],
        current_outlines=current_text,
        instruction=instruction,
    )
    raw = normalize_text(llm.generate(prompt, temperature=0.3))

    # 按 === 拆分，逐个写回
    segments = [seg.strip() for seg in raw.split("===") if seg.strip()]
    import time as _time
    stamp = _time.strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(ch_out_dir, "versions")
    os.makedirs(backup_dir, exist_ok=True)

    written = []
    ch_num = arc_start
    for idx, seg in enumerate(segments):
        out_file = os.path.join(ch_out_dir, f"chapter_{ch_num:03d}.md")
        if os.path.exists(out_file):
            import shutil
            shutil.copy2(out_file, os.path.join(backup_dir, f"chapter_{ch_num:03d}.md_{stamp}"))
        seg = _cap_story_line_in_outline(seg)
        _write_file(out_file, seg)
        written.append({
            "label": f"第{ch_num}章章纲",
            "path": f"file_system/chapter_outlines/vol_{volume:02d}/chapter_{ch_num:03d}.md",
        })
        ch_num += 1
    print(f"  -> 已调整 {len(written)} 章章纲。")
    return {"adjustment_note": f"已按指令调整 {len(written)} 章章纲。", "artifacts": written}


def _raw_chapter_backup_path(ws, volume, chapter_num):
    raw_dir = os.path.join(ws.file_system, "drafts", f"vol_{volume:02d}", "raw_chapters")
    return os.path.join(raw_dir, f"{chapter_num:03d}_第{chapter_num}章.raw.md")


def _backup_raw_chapter(ws, volume, chapter_num, content):
    """保存最近一次精修前正文，并将不同的旧快照归档到 versions。"""
    backup_path = _raw_chapter_backup_path(ws, volume, chapter_num)
    previous = _read_file(backup_path)
    current = str(content or "").strip()
    if previous is not None and previous != current:
        import shutil
        raw_dir = os.path.dirname(backup_path)
        versions_dir = os.path.join(raw_dir, "versions")
        os.makedirs(versions_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        version_name = f"{chapter_num:03d}_第{chapter_num}章_{stamp}.raw.md"
        shutil.copy2(backup_path, os.path.join(versions_dir, version_name))
    _write_file(backup_path, content)
    return backup_path


_PARAGRAPH_PAIR_CLOSERS = {
    "“": "”", "‘": "’", "「": "」", "『": "』",
    "《": "》", "〈": "〉", "（": "）", "(": ")",
    "【": "】", "[": "]", "〔": "〕",
}
_PARAGRAPH_SENTENCE_ENDS = frozenset("。！？!?")


def _chapter_sentence_units(paragraph):
    """按完整句拆分；成对符号内的标点不作为边界，对话始终保持完整。"""
    text = str(paragraph or "")
    if not text:
        return []
    units = []
    buffer = []
    closers = []
    for index, char in enumerate(text):
        buffer.append(char)
        expected = _PARAGRAPH_PAIR_CLOSERS.get(char)
        if expected:
            closers.append(expected)
        elif closers and char == closers[-1]:
            closers.pop()

        boundary = not closers and char in _PARAGRAPH_SENTENCE_ENDS
        if not closers and char == "…":
            boundary = index + 1 >= len(text) or text[index + 1] != "…"
        if (
            not closers
            and char in _PARAGRAPH_PAIR_CLOSERS.values()
            and index > 0
            and text[index - 1] in _PARAGRAPH_SENTENCE_ENDS.union({"…"})
        ):
            boundary = True
        if boundary:
            unit = "".join(buffer).strip()
            if unit:
                units.append(unit)
            buffer = []
    tail = "".join(buffer).strip()
    if tail:
        units.append(tail)
    return units


def _format_chapter_paragraphs(text, target_length=140, max_length=200):
    """仅对过长正文段落自动分段，不改字，不在对白或成对符号内部切断。"""
    source = str(text or "").strip()
    if not source:
        return source
    formatted = []
    for paragraph in re.split(r"\n\s*\n", source):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        rendered_lines = []
        # 保留作者已有的单行换行，但仍处理标题下一行等单独出现的超长正文。
        for line in paragraph.splitlines():
            line = line.strip()
            if len(line) <= max_length:
                rendered_lines.append(line)
                continue
            units = _chapter_sentence_units(line)
            if len(units) < 2:
                rendered_lines.append(line)
                continue

            groups = []
            current = ""
            for unit in units:
                if current and (
                    len(current) >= target_length
                    or len(current) + len(unit) > max_length
                ):
                    groups.append(current)
                    current = unit
                else:
                    current += unit
            if current:
                groups.append(current)
            # 避免末尾只剩一个过短的孤段；仅在合并后仍不超长时回并。
            if len(groups) > 1 and len(groups[-1]) < 60 and len(groups[-2]) + len(groups[-1]) <= max_length:
                tail = groups.pop()
                groups[-1] += tail
            rendered_lines.append("\n\n".join(groups))
        formatted.append("\n".join(rendered_lines))
    return "\n\n".join(formatted)


_CHAPTER_FORBIDDEN_STYLE_PATTERNS = (
    ("破折号“——”", re.compile(r"——")),
    (
        "“不是/并非……而是/却是……”二分对比套式",
        re.compile(r"(?:不是|并非)[^。！？\n]{0,60}?(?:而是|却是)"),
    ),
    (
        "“不仅/不只是……而且/更……”递进套式",
        re.compile(r"(?:不仅|不只是)[^。！？\n]{0,60}?(?:而且|更(?:是|加)?)"),
    ),
)


def _chapter_style_violations(text):
    """返回正文中必须重修的典型 AI 套式；只做检测，不机械改写语义。"""
    violations = []
    for label, pattern in _CHAPTER_FORBIDDEN_STYLE_PATTERNS:
        matches = list(pattern.finditer(text or ""))
        if not matches:
            continue
        examples = []
        for match in matches[:3]:
            start = max(0, match.start() - 18)
            end = min(len(text or ""), match.end() + 18)
            examples.append(re.sub(r"\s+", " ", (text or "")[start:end]).strip())
        violations.append({
            "label": label,
            "count": len(matches),
            "examples": examples,
        })
    return violations


def _repair_chapter_style(llm, chapter_text, violations, cancel_event=None, max_attempts=2):
    """对明确命中的禁用套式做定向重修，直到通过硬校验或明确失败。"""
    current = chapter_text
    current_violations = violations
    for attempt in range(1, max_attempts + 1):
        issue_text = "\n".join(
            f"- {item['label']}：{item['count']}处；示例："
            + "｜".join(item["examples"])
            for item in current_violations
        )
        prompt = PromptLoader.load(
            "chapter_style_repair",
            chapter_text=current,
            violations=issue_text,
        )
        candidate = normalize_text(
            _generate_with_cancel(llm, prompt, cancel_event, temperature=0.2)
        )
        if candidate:
            current = candidate
        current_violations = _chapter_style_violations(current)
        if not current_violations:
            return current
        print(
            f"  -> 正文风格硬校验第{attempt}次重修后仍有"
            f" {sum(item['count'] for item in current_violations)} 处违规。"
        )
    labels = "、".join(item["label"] for item in current_violations)
    raise RuntimeError(f"正文风格硬校验未通过（{labels}），已停止写入，请重试本章。")


def _humanize_chapter_text(
    llm,
    ws,
    volume,
    chapter_num,
    chapter_text,
    cancel_event=None,
):
    _backup_raw_chapter(ws, volume, chapter_num, chapter_text)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    writing_guide = (
        _read_file(os.path.join(ws.file_system, "writing", "system_prompt.md"))
        or _read_file(os.path.join(project_root, "core", "system_prompt.md"))
        or "（无额外生文规范，请严格保持待精修正文已有的作者声音。）"
    )
    prompt = PromptLoader.load(
        "humanize_chapter",
        chapter_text=chapter_text,
        writing_guide=writing_guide,
    )
    result = normalize_text(_generate_with_cancel(llm, prompt, cancel_event))
    result = result or chapter_text
    violations = _chapter_style_violations(result)
    if violations:
        print(
            "  -> AI精修结果命中风格硬校验，启动定向重修："
            + "、".join(f"{item['label']} {item['count']}处" for item in violations)
        )
        result = _repair_chapter_style(
            llm, result, violations, cancel_event=cancel_event,
        )
    return result


def gen_serial_chapters(
    ws,
    volume=1,
    start_chapter=1,
    max_chapters=None,
    humanize=True,
    humanize_existing=False,
    end_chapter=None,
    regenerate_existing=False,
    writing_instruction="",
    refinement_mode="regenerate",
    progress_callback=None,
    pause_event=None,
    stop_event=None,
    cancel_event=None,
):
    """串行生成正文：以情节单元、章纲、前文、章级面板和写作规范生成下一章。"""
    # 项目根目录
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    context = _load_volume_outline_context(ws, volume)
    if not context:
        return
    # 读取写作文风规范（从项目根目录读取）
    custom_style_path = os.path.join(ws.file_system, "writing", "system_prompt.md")
    style_guide = (
        _read_file(custom_style_path)
        or _read_file(os.path.join(_root, "core", "system_prompt.md"))
        or ""
    )
    agents_md = _read_file(os.path.join(_root, "core", "agents.md")) or ""
    writing_rules = f"{style_guide}\n\n{agents_md}" if style_guide or agents_md else "（无写作文风规范）"
    hard_style_rules = (
        "=== 本轮正文硬性风格约束（最终优先）===\n"
        "1. 不使用二分对比套式：例如“不是A，而是B”“不是X，也不是Y，是Z”。\n"
        "2. 不使用否定递进套式：例如“不仅是A，更是B”“不只是A，更是B”。\n"
        "3. 不使用破折号。需要停顿时用逗号、句号或直接拆句。\n"
        "4. 如果参考小说、章纲、前序正文或写作规范示例中出现上述写法，只能视为反例，不能照搬。\n"
    )
    writing_rules = f"{writing_rules}\n\n{hard_style_rules}"
    print(
        "  -> 已加载写作规范："
        f"{'工作区生文规范' if _read_file(custom_style_path) else 'core/system_prompt.md'} {len(style_guide)} 字；"
        f"core/agents.md {len(agents_md)} 字。"
    )
    if not style_guide and not agents_md:
        print("     警告：未加载到写作规范，正文生成将缺少风格约束。")

    # 扫描章纲
    outlines_dir = os.path.join(ws.file_system, "chapter_outlines", f"vol_{volume:02d}")
    if not os.path.isdir(outlines_dir):
        print(f"错误：未找到章纲目录 {outlines_dir}。请先运行 chapter-outlines。")
        return

    outline_files = sorted(f for f in os.listdir(outlines_dir) if re.match(r'^chapter_\d+\.md$', f))
    if not outline_files:
        print(f"错误：章纲目录为空。请先运行 chapter-outlines。")
        return

    # 推断总章数
    total_chapters = 0
    for f in outline_files:
        m = re.match(r'^chapter_(\d+)\.md$', f)
        if m:
            total_chapters = max(total_chapters, int(m.group(1)))

    print(f">>> 串行生成正文：卷{volume}，共 {total_chapters} 章 <<<")

    llm = _get_lite_llm()
    if not llm:
        return

    def humanize_with_controls(ch_num, text, completed, total):
        while True:
            try:
                return _humanize_chapter_text(
                    llm, ws, volume, ch_num, text, cancel_event=cancel_event,
                )
            except LLMCallCancelled:
                if stop_event is not None and stop_event.is_set():
                    return None
                if progress_callback:
                    progress_callback("paused", completed, total, f"第{ch_num}章精修已暂停；继续后重新精修本章")
                if pause_event is not None:
                    pause_event.wait()
                if cancel_event is not None:
                    cancel_event.clear()
    out_dir = os.path.join(ws.file_system, "chapters", f"vol_{volume:02d}")
    os.makedirs(out_dir, exist_ok=True)

    # 确定待处理章节
    tasks = []
    finalized = _finalized_chapter_numbers(ws, "drafts", volume)
    range_end = min(total_chapters, end_chapter or total_chapters)
    effective_start = start_chapter
    if regenerate_existing or humanize_existing:
        effective_start = max(
            effective_start,
            _finalized_chapter_boundary(
                ws, "drafts", volume, start_chapter, range_end,
            ) + 1,
        )
    for ch_num in range(effective_start, range_end + 1):
        out_file = os.path.join(out_dir, f"{ch_num:03d}_第{ch_num}章.md")
        if os.path.exists(out_file):
            if ch_num in finalized:
                print(f"  第{ch_num}章正文已标记为最终版，跳过。")
                continue
            if humanize and humanize_existing:
                tasks.append(("humanize_existing", ch_num))
            elif regenerate_existing:
                tasks.append(("generate", ch_num))
            else:
                print(f"  第{ch_num}章正文已存在，跳过。")
            if max_chapters and len(tasks) >= max_chapters:
                break
            continue
        tasks.append(("generate", ch_num))
        if max_chapters and len(tasks) >= max_chapters:
            break

    if not tasks:
        print("[Orchestrator] 没有待生成的章节（全部已存在）。")
        if humanize and not humanize_existing:
            print("  如需对已有正文执行去AI味，可使用 --humanize-existing。")
        return {
            "adjustment_note": "所选范围没有需要处理的正文；已标记最终版的章节保持不变。",
            "artifacts": [],
            "stopped": False,
        }

    generate_count = sum(1 for mode, _ in tasks if mode == "generate")
    existing_count = len(tasks) - generate_count
    range_text = f"第 {tasks[0][1]}-{tasks[-1][1]} 章"
    if existing_count:
        print(f"  待处理：{len(tasks)} 章（{range_text}；新生成 {generate_count}，已有正文去AI味 {existing_count}）")
    else:
        print(f"  待生成：{generate_count} 章（{range_text}）")

    processed_chapters = []
    for idx, (task_mode, ch_num) in enumerate(tasks):
        if ch_num in _finalized_chapter_numbers(ws, "drafts", volume):
            if progress_callback:
                progress_callback("generating", idx + 1, len(tasks), f"第{ch_num}章已标记最终版，已跳过")
            continue
        if stop_event is not None and stop_event.is_set():
            break
        if pause_event is not None:
            if not pause_event.is_set() and progress_callback:
                progress_callback("paused", idx, len(tasks), "正文生成已暂停")
            pause_event.wait()
        if stop_event is not None and stop_event.is_set():
            break
        out_file = os.path.join(out_dir, f"{ch_num:03d}_第{ch_num}章.md")
        if progress_callback:
            progress_callback("generating", idx, len(tasks), f"正在处理第{ch_num}章正文")

        if task_mode == "generate":
            print(f"\n--- 撰写第{ch_num}章（{idx + 1}/{len(tasks)}）---")
        else:
            print(f"\n--- 去AI味第{ch_num}章（{idx + 1}/{len(tasks)}）---")

        if task_mode == "humanize_existing":
            existing_text = _read_file(out_file)
            if not existing_text:
                print(f"  警告：第{ch_num}章正文为空，跳过。")
                continue
            result = humanize_with_controls(ch_num, existing_text, idx, len(tasks))
            if result is None:
                break
            result = _format_chapter_paragraphs(result)
            _write_file(out_file, result)
            processed_chapters.append(ch_num)
            if progress_callback:
                progress_callback("generating", idx + 1, len(tasks), f"第{ch_num}章正文已精修并写入")
            print(f"  -> 第{ch_num}章正文已去AI味并保存：{out_file}")
            print(f"     原稿备份：{_raw_chapter_backup_path(ws, volume, ch_num)}")
            continue

        # 读取本章章纲
        chapter_outline = _read_file(os.path.join(outlines_dir, f"chapter_{ch_num:03d}.md"))
        if not chapter_outline:
            print(f"  警告：第{ch_num}章章纲文件不存在，跳过。")
            continue
        chapter_outline = re.sub(r'\n?\[(?:FINISHED|CONTINUE)\]\s*$', '', chapter_outline).strip()

        current_draft_section = ""
        if regenerate_existing and refinement_mode == "revise":
            current_draft = _read_file(out_file)
            if current_draft:
                current_draft_section = (
                    "=== 当前章原正文（以此为基础定向调整）===\n"
                    f"{current_draft.strip()}\n\n"
                )

        # 读取前2章正文（不截断）
        prev_texts = []
        for i in range(max(1, ch_num - 2), ch_num):
            prev_file = os.path.join(out_dir, f"{i:03d}_第{i}章.md")
            content = _read_file(prev_file)
            if content:
                prev_texts.append(content.strip())
        history_section = "\n\n".join(prev_texts) if prev_texts else "（无前序正文，这是第一章）"

        # 读取本章对应的新流程故事情节单元。
        story_arc_summary = _find_story_arc_for_chapter(ws, volume, ch_num)

        # 章初面板是上一章落定后的状态，本章面板是章纲规划的章末目标。
        # 正文必须写出两者之间的变化过程，不能把本章面板当作开篇状态。
        panel_section = ""
        if system_panel_status(ws)["enabled"]:
            previous_panel = _previous_system_panel(ws, volume, ch_num)
            current_panel = _read_json_file(
                _system_panel_chapter_path(ws, volume, ch_num)
            )
            if not current_panel:
                raise RuntimeError(
                    f"第{ch_num}章已启用系统面板，但缺少本章面板。"
                    "请先重新生成或同步本章章纲与系统面板。"
                )
            panel_section = (
                "=== 系统面板状态变化 ===\n"
                "【章初状态（上一章结束后）】\n"
                f"{json.dumps(previous_panel, ensure_ascii=False, indent=2)}\n\n"
                "【章末目标（本章结束后）】\n"
                f"{json.dumps(current_panel, ensure_ascii=False, indent=2)}\n\n"
            )

        context = (
            f"=== 写作规范 ===\n{writing_rules}\n\n"
            f"=== 当前故事情节单元 ===\n{story_arc_summary or '（未找到故事情节单元，请严格以章纲为准）'}\n\n"
            f"=== 前序正文（仅用于承接，不得覆盖本章章纲）===\n{history_section}\n\n"
            + panel_section
            + current_draft_section
            + f"=== 当前章章纲（第{ch_num}章，剧情唯一蓝图）===\n{chapter_outline}\n\n"
            + (f"=== 用户本轮调整要求 ===\n{writing_instruction}\n\n" if writing_instruction else "")
            + "=== 最终执行提醒 ===\n"
            + "只输出本章标题和正文；严格执行章纲；如启用系统面板，"
              "正文要自然呈现章初到章末的变化，不得把章末状态提前生效；"
              "不得照抄前序正文；输出前静默检查全部硬性禁用规则。"
        )

        prompt = PromptLoader.load(
            "adaptive_drafting",
            context=context,
            start_chapter=ch_num,
            end_chapter=ch_num,
            chapter_count=1,
        )
        while True:
            try:
                result = normalize_text(_generate_with_cancel(llm, prompt, cancel_event))
                break
            except LLMCallCancelled:
                if stop_event is not None and stop_event.is_set():
                    result = None
                    break
                if progress_callback:
                    progress_callback("paused", idx, len(tasks), f"第{ch_num}章生成已暂停；继续后重新生成本章")
                if pause_event is not None:
                    pause_event.wait()
                if cancel_event is not None:
                    cancel_event.clear()
        if result is None:
            break
        if humanize:
            print(f"  第{ch_num}章正文去AI味处理中...")
            result = humanize_with_controls(ch_num, result, idx, len(tasks))
            if result is None:
                break
        result = _format_chapter_paragraphs(result)
        if regenerate_existing and os.path.exists(out_file):
            import shutil
            backup_dir = os.path.join(out_dir, "versions")
            os.makedirs(backup_dir, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(backup_dir, f"{os.path.basename(out_file)}_{stamp}")
            if not os.path.exists(backup_path):
                shutil.copy2(out_file, backup_path)
        _write_file(out_file, result)
        processed_chapters.append(ch_num)
        if progress_callback:
            progress_callback("generating", idx + 1, len(tasks), f"第{ch_num}章正文已写入")
        if humanize:
            print(f"  -> 第{ch_num}章正文已保存：{out_file}")
            print(f"     原稿备份：{_raw_chapter_backup_path(ws, volume, ch_num)}")
        else:
            print(f"  -> 第{ch_num}章正文已保存：{out_file}")

    completed = 0
    artifacts = []
    for ch_num in processed_chapters:
        path = os.path.join(out_dir, f"{ch_num:03d}_第{ch_num}章.md")
        if _read_file(path):
            completed += 1
            artifacts.append({
                "label": f"第{ch_num}章正文",
                "path": f"file_system/chapters/vol_{volume:02d}/{ch_num:03d}_第{ch_num}章.md",
            })
    stopped = stop_event is not None and stop_event.is_set()
    print(f"\n  -> 卷{volume}正文处理完毕（共 {completed} 章）。")
    return {
        "adjustment_note": (
            f"已结束本轮正文生成，完成 {completed}/{len(tasks)} 章。"
            if stopped else (
                f"已完成 {completed} 章正文"
                + (
                    f"（{'完全重新生成' if refinement_mode == 'regenerate' else '基于当前内容调整'}）"
                    if regenerate_existing else ""
                )
                + "。"
            )
        ),
        "artifacts": artifacts,
        "stopped": stopped,
    }


def chapter_draft_resume_status(ws, volume, arc_idx):
    arc = next((item for item in _list_novel_story_arcs(ws, volume) if item["idx"] == arc_idx), None)
    if not arc:
        return {"can_resume": False, "completed": 0, "total": 0, "next_chapter": None}
    out_dir = os.path.join(ws.file_system, "chapters", f"vol_{volume:02d}")
    chapters = list(range(arc["start_ch"], arc["end_ch"] + 1))
    existing = [ch for ch in chapters if _read_file(os.path.join(out_dir, f"{ch:03d}_第{ch}章.md"))]
    missing = [ch for ch in chapters if ch not in existing]
    return {
        "can_resume": bool(existing and missing), "completed": len(existing), "total": len(chapters),
        "next_chapter": missing[0] if missing else None,
    }


def route_chapter_draft_refinement(ws, volume, arc_idx, instruction, cancel_event=None):
    arc = next((item for item in _list_novel_story_arcs(ws, volume) if item["idx"] == arc_idx), None)
    if not arc:
        raise ValueError("未找到故事情节单元。")
    out_dir = os.path.join(ws.file_system, "chapters", f"vol_{volume:02d}")
    current = []
    for ch in range(arc["start_ch"], arc["end_ch"] + 1):
        text = _read_file(os.path.join(out_dir, f"{ch:03d}_第{ch}章.md"))
        if text:
            current.append(f"【第{ch}章正文】\n{text}")
    llm = _get_lite_llm()
    if not llm:
        raise RuntimeError("未配置可用模型。")
    prompt = PromptLoader.load(
        "chapter_draft_refine_route",
        start_chapter=arc["start_ch"], end_chapter=arc["end_ch"],
        current_chapters="\n\n===\n\n".join(current),
        instruction=instruction,
    )
    routed = parse_json_response(normalize_text(_generate_with_cancel(llm, prompt, cancel_event, temperature=0.2)))
    if not isinstance(routed, dict):
        routed = {}
    try:
        start = int(routed.get("start_chapter"))
    except (TypeError, ValueError):
        start = arc["start_ch"]
    start = min(arc["end_ch"], max(arc["start_ch"], start))
    mode = _normalize_refinement_mode(routed.get("mode"), instruction)
    return start, mode, str(routed.get("reason") or "按用户要求定位最早受影响章节。")
