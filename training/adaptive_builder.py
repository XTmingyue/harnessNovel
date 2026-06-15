import sys
import os
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.llm_provider import LLMProvider
from core.prompt_loader import PromptLoader
from core.config import ConfigLoader
from core.text_utils import normalize_text, parse_json_response
from core.workspace import init_workspace
from core.adaptation import (
    append_adaptation_report,
    format_forbidden_terms,
    load_forbidden_terms,
    load_rewrite_map,
    scan_forbidden_terms,
)
from core.world_knowledge import (
    build_world_knowledge,
    import_world_sources,
    load_world_knowledge_context,
)
from training.reference_finder import (
    list_reference_volumes,
    load_reference_novel_outline,
    load_reference_volume_outline,
    find_reference_batch,
)

BATCH_SIZE = 20


def _get_llm():
    config = ConfigLoader.get_adaptive_builder_config()
    if not config.get("api_key"):
        config["api_key"] = os.getenv("OPENAI_API_KEY")
    if not config.get("api_key"):
        print("错误：未检测到 API Key。")
        return None
    return LLMProvider(**config)


def _get_lite_llm():
    """获取辅助任务 LLM（flash 模型）：世界观、映射表、灵感筛选、书名简介。"""
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


def _load_world_knowledge_optional(ws, purpose):
    """加载目标世界知识库；不存在时降级为纯参考小说+创作方向流程。"""
    world_knowledge = load_world_knowledge_context(ws)
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


def _audit_text(ws, label, text, forbidden_terms, exempt_line_patterns=None):
    """轻量审计生成文本中的参考元素残留，返回违规词列表。"""
    violations = scan_forbidden_terms(
        text,
        forbidden_terms,
        exempt_line_patterns=exempt_line_patterns,
    )
    if violations:
        msg = f"{label} 检测到疑似参考元素残留：{', '.join(violations)}"
        print(f"  警告：{msg}")
        append_adaptation_report(ws, label, msg)
    return violations


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
    reference_worldview = _read_file(os.path.join(ws.file_system, "reference_worldview.md")) or ""
    novel_outline = _read_file(os.path.join(ws.file_system, "novel_outline.md")) or ""
    new_worldview = _read_file(os.path.join(ws.file_system, "new_novel_worldview.md")) or ""

    if not reference_outline or not novel_outline:
        print("  警告：参考大纲或新小说大纲缺失，暂不生成换皮映射表。")
        return ""

    print(">>> 生成全书换皮映射表 <<<")
    prompt = PromptLoader.load(
        "rewrite_map_extract",
        reference_outline=reference_outline,
        reference_worldview=reference_worldview or "（未提取参考世界观）",
        novel_outline=novel_outline,
        new_novel_worldview=new_worldview or "（未生成新小说世界观）",
    )
    result = normalize_text(llm.generate(prompt))
    if result:
        _write_file(output_path, result)
        print(f"  -> 换皮映射表已保存：{output_path}")
    return result


def _ensure_rewrite_map(ws, llm):
    """确保旧工作区在后续阶段也能补齐换皮映射表。"""
    output_path = os.path.join(ws.file_system, "adaptation", "rewrite_map.md")
    if _read_file(output_path):
        return
    _gen_rewrite_map(ws, llm, force=False)


def gen_novel_outline(ws, force=False, creative_direction=None, direction_file=None, preserved_content=None):
    """Step 1: 仿写生成新小说大纲（含按卷世界观）。"""
    output_path = os.path.join(ws.file_system, "novel_outline.md")
    existing = _read_file(output_path)
    if existing and not force:
        print(f"新小说大纲已存在：{output_path}")
        print("使用 --force 覆盖，或手动编辑现有文件。")
        return

    print(">>> 仿写生成新小说大纲 <<<")

    direction = _load_creative_direction(ws, creative_direction, direction_file)
    if direction:
        print(f"  -> 创作方向已加载（{len(direction)} 字）")
    else:
        print("  -> 未提供创作方向，将完全由 LLM 自主创作。")
        print("     可通过 --direction 参数或 creative_direction.md 文件提供方向。")

    llm = _get_llm()
    if not llm:
        return

    print(">>> 调用 LLM 生成大纲 <<<")
    result = _gen_novel_outline_single_ref(ws, llm, direction, preserved_content=preserved_content)

    if result:
        _write_file(output_path, result)
        print(f"  -> 新小说大纲已保存：{output_path}")

        # 自动生成新小说全书世界观
        print()
        _gen_new_novel_worldview_aggregated(ws, llm)

        # 生成后续阶段共用的换皮映射表
        print()
        _gen_rewrite_map(ws, llm, force=force)

        # 推荐书名与简介
        print()
        gen_novel_name_synopsis(ws, force=True)

        print(f"\n  -> 请审核编辑大纲和世界观后，再进行卷纲生成。")


def _gen_novel_outline_single_ref(ws, llm, direction, preserved_content=None):
    """单参考模式：使用 adaptive_novel_outline 提示词。"""
    reference_outline = load_reference_novel_outline(ws.reference_outlines)
    if not reference_outline:
        print("错误：未找到参考小说大纲。请先运行 outline_builder.py。")
        return None

    reference_worldview = _read_file(os.path.join(ws.file_system, "reference_worldview.md")) or "（未提取世界观，请先运行 worldview 命令）"

    preserved_section = ""
    if preserved_content:
        preserved_section = f"【已有定稿中值得保留的大纲内容】\n以下内容来自已定稿章节的分析，重新生成大纲时必须保留这些内容的延续性：\n{preserved_content}"

    prompt = PromptLoader.load(
        "adaptive_novel_outline",
        reference_outline=reference_outline,
        reference_worldview=reference_worldview,
        inspirations="（无灵感库）",
        creative_direction=direction or "（用户未提供具体方向，请自主发挥创意）",
        outline_rules=_load_outline_rules(ws),
        preserved_content=preserved_section,
    )
    draft = normalize_text(llm.generate(prompt))
    world_knowledge = _load_world_knowledge_optional(ws, "新小说大纲合理性校正")
    if not world_knowledge:
        return draft

    draft_path = os.path.join(ws.file_system, "adaptation", "novel_outline_draft.md")
    _write_file(draft_path, draft)
    print(f"  -> 新小说大纲初稿已保存：{draft_path}")
    print(">>> 基于目标世界资料库校正新小说大纲 <<<")

    adjust_prompt = PromptLoader.load(
        "novel_outline_world_adjust",
        creative_direction=direction or "（用户未提供具体方向，请自主发挥创意）",
        reference_worldview=reference_worldview,
        reference_outline=reference_outline,
        world_knowledge=world_knowledge,
        outline_rules=_load_outline_rules(ws),
        preserved_content=preserved_section,
        draft_outline=draft,
    )
    return normalize_text(llm.generate(adjust_prompt))


def _gen_new_novel_worldview_aggregated(ws, llm):
    """基于新小说大纲 + 参考小说全书世界观，生成新小说全书世界观。"""
    novel_outline = _read_file(os.path.join(ws.file_system, "novel_outline.md"))
    if not novel_outline:
        print("错误：未找到新小说大纲。")
        return

    ref_wv = _read_file(os.path.join(ws.file_system, "reference_worldview.md"))
    if not ref_wv:
        print("错误：未找到参考小说世界观。请先运行 worldview 命令。")
        return

    aggregated_path = os.path.join(ws.file_system, "new_novel_worldview.md")
    existing = _read_file(aggregated_path)
    if existing:
        print(f"新小说世界观已存在：{aggregated_path}")
        print("使用 --force 覆盖。")
        return

    print(">>> 生成新小说全书世界观 <<<")
    world_knowledge = _load_world_knowledge_optional(ws, "新小说全书世界观校正")
    world_knowledge_section = (
        "【目标世界知识库】（合理性校验优先级高于参考小说旧世界观）\n"
        + world_knowledge
        + "\n\n"
        if world_knowledge
        else ""
    )

    prompt = PromptLoader.load(
        "new_novel_worldview",
        novel_outline=novel_outline,
        world_knowledge_section=world_knowledge_section,
        reference_worldview=ref_wv,
    )
    result = normalize_text(llm.generate(prompt))
    _write_file(aggregated_path, result)
    print(f"  -> 新小说全书世界观已保存：{aggregated_path}")


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


def build_target_world_knowledge(ws, force=False, chunk_size=12000, chapter_batch_size=20,
                                 max_workers=None, primary_source=None, merge_only=False):
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


def gen_novel_name_synopsis(ws, force=False):
    """基于新小说大纲和世界观，推荐书名和简介。"""
    novel_outline = _read_file(os.path.join(ws.file_system, "novel_outline.md"))
    if not novel_outline:
        print("错误：未找到新小说大纲，请先运行 novel-outline。")
        return

    output_path = os.path.join(ws.file_system, "novel_name_synopsis.md")
    existing = _read_file(output_path)
    if existing and not force:
        print(f"书名与简介推荐已存在：{output_path}")
        print("使用 --force 覆盖。")
        return

    worldview = _read_file(os.path.join(ws.file_system, "new_novel_worldview.md")) or ""
    direction = _read_file(ws.creative_direction) or "（未提供）"
    ref_name, ref_synopsis = _extract_reference_name_synopsis(ws)

    llm = _get_llm()
    if not llm:
        return

    print(">>> 推荐书名与简介 <<<")

    prompt = PromptLoader.load(
        "novel_name_synopsis",
        reference_name=ref_name,
        reference_synopsis=ref_synopsis,
        novel_outline=novel_outline,
        worldview=worldview or "（未生成世界观）",
        creative_direction=direction,
    )
    result = normalize_text(llm.generate(prompt))
    if result:
        _write_file(output_path, result)
        print(f"  -> 书名与简介已保存：{output_path}")


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
        return

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
    forbidden_terms = load_forbidden_terms(ws, vol_idx)
    forbidden_terms_text = format_forbidden_terms(forbidden_terms)

    result = ""
    audit_feedback = ""
    violations = []
    for attempt in range(2):
        prompt = (
            "你是一个专业的小说世界观设计专家。请基于新小说的全书世界观，结合本卷卷纲的具体内容，"
            "细化生成指定卷的详细世界观设定。\n\n"
            "【新小说全书世界观】\n" + new_novel_worldview + "\n\n"
            "【本卷卷纲】\n" + current_vol_text + "\n\n"
            "【换皮映射表】（必须遵守）\n" + rewrite_map + "\n\n"
            "【禁止残留的参考元素】\n" + forbidden_terms_text + "\n\n"
            + (f"【上一卷世界观】（保持世界观演进的一致性）\n{prev_wv}\n\n" if prev_wv else "")
            + (f"【本卷旧世界观】（参考已有设定，在此基础上升级）\n{old_wv}\n\n" if old_wv else "")
            + (audit_feedback + "\n\n" if audit_feedback else "")
            + "【要求】\n"
            "1. 以全书世界观为基础，细化到本卷涉及的具体势力、人物、地点、物品。\n"
            "2. 体现世界观在本卷中的演进：新势力登场、角色成长、新区域解锁等。\n"
            "3. 与上一卷世界观保持连续性，不要出现矛盾设定。\n"
            "4. 每个方面必须列出具体名称，不能概括。\n"
            "5. 不能把参考小说旧世界的事件、人物、时间线和宗教因果固化为新世界观事实。\n"
            "6. 若本卷卷纲中的“对应参考小说”说明包含旧名词，只能理解为映射说明，不能写入新世界观正文。\n"
            "7. 输出前自检：若出现禁止残留参考元素，必须改写为新世界观对应元素或删除。\n"
            "8. 使用纯文本输出，禁止使用 Markdown 格式符号。标题使用 # 标记。段落之间用空行分隔。\n\n"
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
        violations = scan_forbidden_terms(
            result,
            forbidden_terms,
            exempt_line_patterns=["对应参考", "参考小说", "映射说明"],
        )
        if not violations:
            break
        print(f"  卷{vol_idx}世界观检测到参考元素残留：{', '.join(violations)}，尝试重写...")
        audit_feedback = (
            f"【上次世界观违规项】\n"
            f"上次输出把以下参考元素写入了新世界观正文：{', '.join(violations)}。\n"
            "请根据换皮映射表改写或删除这些旧世界元素，不要把它们固化为新设定。"
        )

    _write_file(vol_wv_path, result)
    if violations:
        _audit_text(ws, f"卷{vol_idx}世界观", result, forbidden_terms,
                    exempt_line_patterns=["对应参考", "参考小说", "映射说明"])
    print(f"  -> 卷{vol_idx}世界观已保存：{vol_wv_path}")


def _gen_single_volume(ws, vol_idx, ref_volumes, force, creative_direction, llm, preserved_content=None):
    """生成单卷卷纲，再生成该卷世界观。返回 True 表示已是终卷。"""
    vol_dir = os.path.join(ws.file_system, "new_volume_outlines")
    vol_file = os.path.join(vol_dir, f"vol_{vol_idx:02d}_outline.md")
    os.makedirs(vol_dir, exist_ok=True)

    existing_this = _read_file(vol_file)
    if existing_this and not force:
        print(f"  -> 卷{vol_idx}卷纲已存在，跳过。（用 --force 覆盖）")
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
    forbidden_terms = load_forbidden_terms(ws, vol_idx)

    preserved_section = ""
    if preserved_content:
        preserved_section = f"【已有定稿中值得保留的卷纲内容】\n以下内容来自已定稿章节的分析，重新生成卷纲时必须保留这些内容的延续性：\n{preserved_content}"

    result = ""
    audit_feedback = ""
    violations = []
    for attempt in range(2):
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
            audit_feedback=audit_feedback,
        )
        result = normalize_text(llm.generate(prompt))
        result_for_scan = re.sub(r'\n?\[(?:FINISHED|CONTINUE)\]\s*$', '', result).strip()
        violations = scan_forbidden_terms(
            result_for_scan,
            forbidden_terms,
            exempt_line_patterns=["对应参考", "参考小说", "映射说明"],
        )
        if not violations:
            break
        print(f"  卷{vol_idx}卷纲检测到参考元素残留：{', '.join(violations)}，尝试重写...")
        audit_feedback = (
            f"【上次卷纲违规项】\n"
            f"上次输出在非“对应参考小说/映射说明”的正文设定中出现了：{', '.join(violations)}。\n"
            "请保留卷纲结构和新小说设定，改写或删除这些旧世界元素。"
        )

    if not result:
        return False

    is_finished = result.rstrip().endswith("[FINISHED]")
    result_clean = re.sub(r'\n?\[(?:FINISHED|CONTINUE)\]\s*$', '', result).strip()
    if violations:
        _audit_text(ws, f"卷{vol_idx}卷纲", result_clean, forbidden_terms,
                    exempt_line_patterns=["对应参考", "参考小说", "映射说明"])

    # 写入按卷文件（保留 [FINISHED] 标记以便重跑时检测）
    marker = "\n[FINISHED]" if is_finished else "\n[CONTINUE]"
    _write_file(vol_file, result_clean + marker + "\n")

    if is_finished:
        print(f"  -> 第 {vol_idx} 卷卷纲已保存（终卷，生成完毕）。")
    else:
        print(f"  -> 第 {vol_idx} 卷卷纲已保存，继续生成下一卷。")

    # Step 2: 生成该卷的世界观
    _gen_volume_worldview(ws, vol_idx, llm, force, novel_outline, new_novel_worldview)

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






def gen_serial_chapter_outlines(ws, volume=1, force=False):
    """两阶段串行生成章纲：
    Phase 1: 串行生成本卷的批次摘要
    Phase 2: 串行生成本卷每个batch下的章纲
    """
    # ── 加载基础数据 ──
    vol_outline_file = os.path.join(ws.file_system, "new_volume_outlines", f"vol_{volume:02d}_outline.md")
    vol_outline = _read_file(vol_outline_file)
    if not vol_outline:
        print(f"错误：未找到卷{volume}的卷纲文件：{vol_outline_file}")
        return

    vol_wv_file = os.path.join(ws.file_system, "new_worldviews", f"vol_{volume:02d}_worldview.md")
    vol_worldview = _read_file(vol_wv_file)
    if not vol_worldview:
        print(f"错误：未找到卷{volume}的世界观文件：{vol_wv_file}")
        print("请先运行 volume-outline 命令生成卷纲和世界观。")
        return

    # 从卷纲中推断总章数
    chapter_nums = re.findall(r'第(\d+)章', vol_outline)
    if not chapter_nums:
        print("错误：无法从卷纲中推断总章数。")
        return
    total_chapters = max(int(c) for c in chapter_nums)

    llm = _get_llm()
    if not llm:
        return
    _ensure_rewrite_map(ws, llm)

    # 参考卷映射
    outlines_dir = ws.reference_outlines
    ref_volumes = list_reference_volumes(outlines_dir)
    if not ref_volumes:
        print("错误：未找到参考小说卷数据。")
        return
    ref_vol = ref_volumes[min(volume - 1, len(ref_volumes) - 1)]
    rewrite_map = load_rewrite_map(ws, volume)
    forbidden_terms = load_forbidden_terms(ws, volume)
    forbidden_terms_text = format_forbidden_terms(forbidden_terms)

    # ═══════════════════════════════════════════
    # Phase 1: 串行生成批次摘要
    # ═══════════════════════════════════════════
    print(f">>> Phase 1: 串行生成卷{volume}的批次摘要（共{total_chapters}章，每批{BATCH_SIZE}章）<<<")

    vol_batch_dir = os.path.join(_novel_outlines_dir(ws), f"vol_{volume:02d}")
    os.makedirs(vol_batch_dir, exist_ok=True)

    batch_count = (total_chapters + BATCH_SIZE - 1) // BATCH_SIZE
    for batch_idx in range(1, batch_count + 1):
        start_ch = (batch_idx - 1) * BATCH_SIZE + 1
        end_ch = min(batch_idx * BATCH_SIZE, total_chapters)
        batch_file = os.path.join(vol_batch_dir, f"batch_{start_ch:03d}_{end_ch:03d}.md")

        if os.path.exists(batch_file) and not force:
            print(f"  批次{batch_idx}（第{start_ch}-{end_ch}章）已存在，跳过。")
            continue

        # 读取上一批次
        prev_batch = ""
        if batch_idx > 1:
            prev_start = (batch_idx - 2) * BATCH_SIZE + 1
            prev_end = min((batch_idx - 1) * BATCH_SIZE, total_chapters)
            prev_file = os.path.join(vol_batch_dir, f"batch_{prev_start:03d}_{prev_end:03d}.md")
            prev_batch = _read_file(prev_file) or ""
        if not prev_batch:
            prev_batch = "（无前序批次，这是第一个batch）"

        # 参考批次
        ref_batch = find_reference_batch(
            outlines_dir, ref_vol["vol_idx"],
            start_ch, end_ch, total_chapters,
            ref_vol["chapter_count"],
        )

        print(f"  生成批次{batch_idx}（第{start_ch}-{end_ch}章）...")
        adapted_reference_batch = _adapt_reference_batch(
            ws=ws,
            llm=llm,
            volume=volume,
            batch_idx=batch_idx,
            start_ch=start_ch,
            end_ch=end_ch,
            vol_outline=vol_outline,
            vol_worldview=vol_worldview,
            reference_batch=ref_batch or "",
            rewrite_map=rewrite_map,
            forbidden_terms=forbidden_terms,
            force=force,
        )
        result = _generate_batch_summary_with_audit(
            ws=ws,
            llm=llm,
            volume=volume,
            batch_idx=batch_idx,
            start_ch=start_ch,
            end_ch=end_ch,
            vol_outline=vol_outline,
            vol_worldview=vol_worldview,
            previous_batch=prev_batch,
            reference_batch=ref_batch or "",
            adapted_reference_batch=adapted_reference_batch,
            rewrite_map=rewrite_map,
            forbidden_terms=forbidden_terms,
        )
        _write_file(batch_file, result)
        print(f"  -> 批次{batch_idx}已保存：{batch_file}")

    print(f"\n>>> Phase 1 完成，共 {batch_count} 个批次 <<<")

    # ═══════════════════════════════════════════
    # Phase 2: 串行生成章纲（按batch逐章生成）
    # ═══════════════════════════════════════════
    print(f"\n>>> Phase 2: 串行生成卷{volume}的章纲 <<<")

    ch_out_dir = os.path.join(ws.file_system, "chapter_outlines", f"vol_{volume:02d}")
    os.makedirs(ch_out_dir, exist_ok=True)

    # 按批次文件顺序读取
    batch_files = sorted(
        f for f in os.listdir(vol_batch_dir)
        if re.match(r'^batch_\d+_\d+\.md$', f)
    )

    for bf_name in batch_files:
        m = re.match(r'^batch_(\d+)_(\d+)\.md$', bf_name)
        if not m:
            continue
        batch_start = int(m.group(1))
        batch_end = int(m.group(2))

        batch_content = _read_file(os.path.join(vol_batch_dir, bf_name))
        if not batch_content:
            print(f"  警告：批次文件 {bf_name} 为空，跳过。")
            continue

        print(f"\n  --- 批次：第{batch_start}-{batch_end}章 ---")

        for ch_num in range(batch_start, batch_end + 1):
            out_file = os.path.join(ch_out_dir, f"chapter_{ch_num:03d}.md")
            if os.path.exists(out_file) and not force:
                print(f"  第{ch_num}章章纲已存在，跳过。")
                continue

            # 读取前2章章纲
            prev_outlines = []
            for i in range(max(1, ch_num - 2), ch_num):
                prev_file = os.path.join(ch_out_dir, f"chapter_{i:03d}.md")
                content = _read_file(prev_file)
                if content:
                    clean = re.sub(r'\n?\[(?:FINISHED|CONTINUE)\]\s*$', '', content).strip()
                    prev_outlines.append(f"【第{i}章 章纲】\n{clean}")
            previous_text = "\n\n".join(prev_outlines) if prev_outlines else "（无前序章纲，这是本章节范围内第一章）"

            print(f"  生成第{ch_num}章章纲...")
            prompt = PromptLoader.load(
                "serial_chapter_outline",
                volume_outline=vol_outline,
                volume_worldview=vol_worldview,
                rewrite_map=rewrite_map,
                forbidden_terms="章纲阶段不执行禁用词扫描。请以本卷卷纲、本卷世界观、换皮映射表和当前批次摘要为准，保持剧情合理性，不要主动引入与当前阶段不符的旧世界因果。",
                batch_summary=batch_content,
                previous_chapter_outlines=previous_text,
                chapter_num=ch_num,
            )
            result = normalize_text(llm.generate(prompt))
            _write_file(out_file, result)
            print(f"  -> 第{ch_num}章章纲已保存：{out_file}")

    print(f"\n>>> 卷{volume}全部 {total_chapters} 章章纲已生成。<<<")


def gen_serial_chapters(ws, volume=1, start_chapter=1, max_chapters=None):
    """串行生成正文：以卷纲+本卷世界观+本章章纲+前2章正文+写作文风为输入生成下一章正文。"""
    # 项目根目录
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 读取卷纲
    vol_outline = _read_file(os.path.join(ws.file_system, "new_volume_outlines", f"vol_{volume:02d}_outline.md"))
    if not vol_outline:
        print(f"错误：未找到卷{volume}的卷纲文件。请先运行 volume-outline。")
        return

    # 读取本卷世界观
    vol_worldview = _read_file(os.path.join(ws.file_system, "new_worldviews", f"vol_{volume:02d}_worldview.md"))
    if not vol_worldview:
        print(f"错误：未找到卷{volume}的世界观文件。请先运行 volume-outline。")
        return

    # 读取写作文风规范（从项目根目录读取）
    style_guide = _read_file(os.path.join(_root, "core", "system_prompt.md")) or ""
    agents_md = _read_file(os.path.join(_root, "core", "agents.md")) or ""
    writing_rules = f"{style_guide}\n\n{agents_md}" if style_guide or agents_md else "（无写作文风规范）"

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

    llm = _get_llm()
    if not llm:
        return
    _ensure_rewrite_map(ws, llm)
    rewrite_map = load_rewrite_map(ws, volume)
    forbidden_terms = load_forbidden_terms(ws, volume)
    forbidden_terms_text = format_forbidden_terms(forbidden_terms)

    out_dir = os.path.join(ws.file_system, "chapters", f"vol_{volume:02d}")
    os.makedirs(out_dir, exist_ok=True)

    # 确定待生成章节
    pending = []
    for ch_num in range(start_chapter, total_chapters + 1):
        out_file = os.path.join(out_dir, f"{ch_num:03d}_第{ch_num}章.md")
        if os.path.exists(out_file):
            print(f"  第{ch_num}章正文已存在，跳过。")
            continue
        pending.append(ch_num)
        if max_chapters and len(pending) >= max_chapters:
            break

    if not pending:
        print("[Orchestrator] 没有待生成的章节（全部已存在）。")
        return

    print(f"  待生成：{len(pending)} 章（第 {pending[0]}-{pending[-1]} 章）")

    for idx, ch_num in enumerate(pending):
        out_file = os.path.join(out_dir, f"{ch_num:03d}_第{ch_num}章.md")

        # 读取本章章纲
        chapter_outline = _read_file(os.path.join(outlines_dir, f"chapter_{ch_num:03d}.md"))
        if not chapter_outline:
            print(f"  警告：第{ch_num}章章纲文件不存在，跳过。")
            continue
        chapter_outline = re.sub(r'\n?\[(?:FINISHED|CONTINUE)\]\s*$', '', chapter_outline).strip()

        print(f"\n--- 撰写第{ch_num}章（{idx + 1}/{len(pending)}）---")

        # 读取前2章正文（不截断）
        prev_texts = []
        for i in range(max(1, ch_num - 2), ch_num):
            prev_file = os.path.join(out_dir, f"{i:03d}_第{i}章.md")
            content = _read_file(prev_file)
            if content:
                prev_texts.append(content.strip())
        history_section = "\n\n".join(prev_texts) if prev_texts else "（无前序正文，这是第一章）"

        # 读取本章对应的批次摘要
        batch_summary = ""
        batch_dir = os.path.join(ws.file_system, "outlines", f"vol_{volume:02d}")
        if os.path.isdir(batch_dir):
            batch_idx = (ch_num - 1) // BATCH_SIZE + 1
            bs = (batch_idx - 1) * BATCH_SIZE + 1
            be = min(batch_idx * BATCH_SIZE, total_chapters)
            bf = os.path.join(batch_dir, f"batch_{bs:03d}_{be:03d}.md")
            batch_content = _read_file(bf)
            if batch_content:
                batch_summary = batch_content

        # 加载参考小说对应章节正文
        from training.outline_builder import load_chapter_text
        ref_chapter_text = load_chapter_text(ws, volume, ch_num, total_chapters)

        context = (
            f"=== 前序正文 ===\n{history_section}\n\n"
            f"=== 章纲（第{ch_num}章）===\n{chapter_outline}\n\n"
            f"=== 换皮映射表 ===\n{rewrite_map}\n\n"
            f"=== 禁止残留的参考元素 ===\n{forbidden_terms_text}\n\n"
            + (f"=== 参考小说本章正文 ===\n{ref_chapter_text}\n\n" if ref_chapter_text else "")
            + f"=== 写作规范 ===\n{writing_rules}"
        )

        result = ""
        violations = []
        for attempt in range(2):
            retry_context = context
            if violations:
                retry_context += (
                    f"\n\n=== 上次生成违规项 ===\n"
                    f"正文出现了以下禁止残留参考元素：{', '.join(violations)}。\n"
                    "请保留本章章纲事件和情绪节点，改写或删除这些旧世界元素。"
                )
            prompt = PromptLoader.load(
                "adaptive_drafting",
                context=retry_context,
                start_chapter=ch_num,
                end_chapter=ch_num,
                chapter_count=1,
            )
            result = normalize_text(llm.generate(prompt))
            violations = scan_forbidden_terms(result, forbidden_terms)
            if not violations:
                break
            print(f"  第{ch_num}章正文检测到参考元素残留：{', '.join(violations)}，尝试重写...")
        if violations:
            append_adaptation_report(
                ws,
                f"卷{volume}第{ch_num}章正文残留",
                f"违规项：{', '.join(violations)}\n文件：{out_file}",
            )
        _write_file(out_file, result)
        print(f"  -> 第{ch_num}章正文已保存：{out_file}")

    print(f"\n  -> 卷{volume}正文生成完毕（共 {len(pending)} 章）。")


def gen_worldview(ws):
    """按卷提取世界观，再汇总为完整世界观。"""
    from training.reference_finder import list_reference_volumes, load_reference_volume_outline
    import glob

    print(">>> 提取参考小说世界观 <<<")

    # 世界观存储目录
    worldview_dir = os.path.join(ws.file_system, "worldviews")
    aggregated_path = os.path.join(ws.file_system, "reference_worldview.md")

    ref_volumes = list_reference_volumes(ws.reference_outlines)
    if not ref_volumes:
        print("错误：未找到参考小说卷数据。请先运行 outline_builder.py。")
        return

    llm = _get_lite_llm()
    if not llm:
        return

    print(">>> 按卷提取参考小说世界观 <<<")

    # 阶段一：按卷提取世界观
    os.makedirs(worldview_dir, exist_ok=True)
    volume_worldviews = []

    for vol in ref_volumes:
        vol_idx = vol["vol_idx"]
        vol_title = vol["title"]
        vol_wv_path = os.path.join(worldview_dir, f"vol_{vol_idx:02d}_worldview.md")

        existing = _read_file(vol_wv_path)
        if existing:
            print(f"  卷{vol_idx}世界观已存在，跳过。")
            volume_worldviews.append({"vol_idx": vol_idx, "title": vol_title, "content": existing})
            continue

        print(f"  提取卷{vol_idx}（{vol_title}）世界观...")

        vol_outline = load_reference_volume_outline(ws.reference_outlines, vol_idx)

        # 收集本卷的批次摘要
        batch_files = sorted(glob.glob(os.path.join(vol["dir_path"], "batch_*.md")))
        batch_contents = []
        for bf in batch_files:
            content = _read_file(bf)
            if content:
                batch_contents.append(content)

        if not batch_contents:
            print(f"  卷{vol_idx}无批次摘要，跳过。")
            continue

        batches_text = "\n\n---\n\n".join(batch_contents)
        prompt = PromptLoader.load(
            "worldview_extract",
            volume_title=vol_title,
            volume_outline=vol_outline or "（无卷纲）",
            batch_summaries=batches_text,
        )
        result = normalize_text(llm.generate(prompt))
        _write_file(vol_wv_path, result)
        volume_worldviews.append({"vol_idx": vol_idx, "title": vol_title, "content": result})
        print(f"  卷{vol_idx}世界观已保存")

    if not volume_worldviews:
        print("错误：未提取到任何卷的世界观。")
        return

    # 阶段二：汇总所有卷的世界观
    existing_agg = _read_file(aggregated_path)
    if existing_agg:
        print(f"\n汇总世界观已存在：{aggregated_path}")
        print("如需重新生成，请先删除该文件。")
        return

    print(f"\n>>> 汇总 {len(volume_worldviews)} 卷世界观 <<<")

    all_wv = "\n\n---\n\n".join(
        f"# {wv['title']}（卷{wv['vol_idx']}）\n{wv['content']}"
        for wv in volume_worldviews
    )

    if len(volume_worldviews) == 1:
        _write_file(aggregated_path, volume_worldviews[0]["content"])
    else:
        prompt = PromptLoader.load("worldview_merge", volume_worldviews=all_wv)
        result = normalize_text(llm.generate(prompt))
        _write_file(aggregated_path, result)

    print(f"  -> 汇总世界观已保存：{aggregated_path}")
    print(f"  -> 按卷世界观保存在：{worldview_dir}/")
