import sys
import os
import re
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.llm_provider import LLMProvider
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


def _get_llm():
    config = ConfigLoader.get_adaptive_builder_config()
    if not config.get("api_key"):
        config["api_key"] = os.getenv("OPENAI_API_KEY")
    if not config.get("api_key"):
        print("错误：未检测到 API Key。")
        return None
    return LLMProvider(**config)


def _get_lite_llm():
    """获取辅助任务 LLM（flash 模型）：世界观、资料库、灵感筛选、书名简介。"""
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


def run_step(*, llm, folder, prompt_vars, output_path, label=None,
             header=None, save=None, write_guard=False):
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
    result = normalize_text(llm.generate(prompt))
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
    reference_worldview = _read_file(os.path.join(ws.file_system, "reference_worldview.md")) or ""
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
            reference_worldview=reference_worldview or "（未提取参考世界观）",
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


def _load_story_design_assets(ws):
    return {
        "core_gameplay": _read_file(_story_design_path(ws, "core_gameplay.md")) or "（未生成核心玩法文档）",
        "long_mainline": _read_file(_story_design_path(ws, "long_mainline.md")) or "（未生成全书长线主线）",
        "stage_roadmap": _read_file(_story_design_path(ws, "stage_roadmap.md")) or "（未生成舞台路线图）",
        "character_arcs": _read_file(_story_design_path(ws, "character_arcs.md")) or "（未生成角色成长线）",
    }


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
    _write_json_file(_mechanics_path(ws, "profile.json"), payload["profile"])
    _write_file(_mechanics_path(ws, "design.md"), payload["design"] or "（无机制层设计说明）")
    _write_json_file(_mechanics_path(ws, "rules.json"), payload["rules"])
    _write_json_file(_mechanics_path(ws, "state.json"), payload["state"])


def _load_mechanics_context(ws):
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


def init_mechanics(ws, force=False, creative_direction=None, direction_file=None,
                   mechanics_file=None, disable=False):
    """初始化可选机制层：none / light_state / explicit_mechanics。"""
    profile_path = _mechanics_path(ws, "profile.json")
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
    print(f"  -> 机制层 profile 已保存：{_mechanics_path(ws, 'profile.json')}")
    print(f"  -> 机制层设计已保存：{_mechanics_path(ws, 'design.md')}")
    print(f"  -> 机制层规则已保存：{_mechanics_path(ws, 'rules.json')}")
    print(f"  -> 机制层状态已保存：{_mechanics_path(ws, 'state.json')}")
    print(f"  -> 机制层模式：{payload['profile']['mode']}")


def _gen_core_gameplay(ws, llm, direction, world_knowledge, force=False):
    output_path = _story_design_path(ws, "core_gameplay.md")
    existing = _read_file(output_path)
    if existing and not force:
        print(f"核心玩法文档已存在：{output_path}")
        return existing

    reference_outline = load_reference_novel_outline(ws.reference_outlines)
    reference_worldview = _read_file(os.path.join(ws.file_system, "reference_worldview.md")) or "（未提取参考世界观）"

    return run_step(
        llm=llm,
        folder="core_gameplay_design",
        label="核心玩法文档",
        output_path=output_path,
        prompt_vars=dict(
            creative_direction=direction or "（用户未提供具体方向）",
            reference_outline=reference_outline or "（无参考小说全书大纲）",
            reference_worldview=reference_worldview,
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
    reference_worldview = _read_file(os.path.join(ws.file_system, "reference_worldview.md")) or "（未提取参考世界观）"
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
            reference_worldview=reference_worldview,
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

    return run_step(
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


def gen_story_design(ws, force=False, creative_direction=None, direction_file=None):
    """生成长篇网文的玩法、长线主线、舞台和角色线设计资产。"""
    llm = _get_llm()
    if not llm:
        return

    direction = _load_creative_direction(ws, creative_direction, direction_file)
    world_knowledge = _load_world_knowledge_optional(ws, "故事玩法/舞台/角色线设计")

    _gen_core_gameplay(ws, llm, direction, world_knowledge, force=force)
    _gen_long_mainline(ws, llm, direction, world_knowledge, force=force)
    _gen_stage_roadmap(ws, llm, direction, world_knowledge, force=force)
    _gen_character_arcs(ws, llm, direction, world_knowledge, force=force)


def gen_novel_outline(ws, force=False, creative_direction=None, direction_file=None, preserved_content=None):
    """生成核心玩法、全书长线主线、舞台路线图和角色成长线。"""
    print(">>> 生成核心玩法与全书舞台设计 <<<")

    direction = _load_creative_direction(ws, creative_direction, direction_file)
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
    """基于故事设计资产，推荐书名和简介。"""
    novel_outline = _read_file(os.path.join(ws.file_system, "novel_outline.md"))
    if not novel_outline:
        assets = _load_story_design_assets(ws)
        novel_outline = (
            "【核心玩法】\n" + assets["core_gameplay"] + "\n\n"
            "【全书长线主线】\n" + assets["long_mainline"] + "\n\n"
            "【舞台路线图】\n" + assets["stage_roadmap"] + "\n\n"
            "【角色成长线】\n" + assets["character_arcs"]
        )

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

    run_step(
        llm=llm,
        folder="novel_name_synopsis",
        label="书名与简介",
        header=">>> 推荐书名与简介 <<<",
        write_guard=True,
        output_path=output_path,
        prompt_vars=dict(
            reference_name=ref_name,
            reference_synopsis=ref_synopsis,
            novel_outline=novel_outline,
            worldview=worldview or "（未生成世界观）",
            creative_direction=direction,
        ),
    )


def _stage_insert_backup_path(ws):
    return os.path.join(ws.file_system, "adaptation", "stage_roadmap_before_insert.md")


def insert_stage(ws, creative_direction=None, direction_file=None, after_stage=None, before_stage=None):
    """基于新灵感设计新舞台，并插入全书舞台路线图。"""
    stage_direction = _load_creative_direction(ws, creative_direction, direction_file)
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
    result = normalize_text(llm.generate(prompt))
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


def _story_pattern_path(ws, volume, arc_idx, start_ch, end_ch):
    return os.path.join(
        ws.file_system,
        "adaptation",
        "story_patterns",
        f"vol_{volume:02d}",
        f"arc_{arc_idx:03d}_ch{start_ch:03d}_{end_ch:03d}.md",
    )


def _arc_context_path(ws, volume):
    return os.path.join(
        ws.file_system,
        "adaptation",
        "arc_contexts",
        f"vol_{volume:02d}_context.md",
    )


def _extract_stage_from_roadmap(stage_roadmap, stage_idx):
    if not stage_roadmap:
        return ""
    pattern = re.compile(
        rf'(?ms)^#\s*舞台\s*0*{stage_idx}\b.*?(?=^#\s*舞台\s*\d+\b|\Z)'
    )
    match = pattern.search(stage_roadmap)
    return match.group(0).strip() if match else ""


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


def _build_arc_context(ws, llm, volume, total_chapters, vol_outline, vol_worldview,
                       rewrite_map, force=False):
    """将全书/当前舞台上下文压缩为故事情节生成专用上下文。"""
    out_path = _arc_context_path(ws, volume)
    existing = _read_file(out_path)
    if existing and not force:
        return existing

    assets = _load_story_design_assets(ws)
    current_stage = _extract_stage_from_roadmap(assets["stage_roadmap"], volume)
    if not current_stage:
        current_stage = _read_file(_volume_stage_plan_path(ws, volume)) or "（未生成当前舞台计划）"

    return run_step(
        llm=llm,
        folder="arc_context_extract",
        output_path=out_path,
        prompt_vars=dict(
            volume_index=volume,
            total_chapters=total_chapters,
            core_gameplay=assets["core_gameplay"],
            long_mainline=assets["long_mainline"],
            current_stage=current_stage,
            stage_roadmap=assets["stage_roadmap"],
            character_arcs=assets["character_arcs"],
            mechanics_context=_load_mechanics_context(ws),
            volume_outline=vol_outline,
            volume_worldview=vol_worldview,
            rewrite_map=rewrite_map or "（新流程不依赖换皮映射表；参考小说只提供叙事功能）",
        ),
    )


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



def _extract_story_pattern(ws, llm, volume, arc_idx, start_ch, end_ch,
                           arc_context, reference_story_arc, force=False):
    """将参考故事情节抽象为叙事模式，避免后续直接换皮。"""
    out_path = _story_pattern_path(ws, volume, arc_idx, start_ch, end_ch)
    existing = _read_file(out_path)
    if existing and not force:
        return existing

    return run_step(
        llm=llm,
        folder="story_pattern_extract",
        output_path=out_path,
        prompt_vars=dict(
            arc_context=arc_context,
            arc_index=arc_idx,
            start_chapter=start_ch,
            end_chapter=end_ch,
            reference_story_arc=reference_story_arc or "（无参考故事情节单元）",
        ),
    )


def _generate_story_arc_with_audit(ws, llm, volume, arc_idx, start_ch, end_ch,
                                   arc_context, previous_story_arc,
                                   reference_story_arc, story_pattern):
    """基于叙事模式生成新书故事情节单元。"""
    prompt = PromptLoader.load(
        "novel_story_arc",
        arc_context=arc_context,
        arc_index=arc_idx,
        start_chapter=start_ch,
        end_chapter=end_ch,
        previous_story_arc=previous_story_arc,
        reference_story_arc=reference_story_arc or "（无参考故事情节单元）",
        story_pattern=story_pattern,
        audit_feedback="",
        previous_result="",
    )
    return normalize_text(llm.generate(prompt))


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


def gen_story_arcs(ws, volume=1, force=False):
    """基于参考故事情节提取叙事模式，生成新书故事情节单元。"""
    context = _load_volume_outline_context(ws, volume)
    if not context:
        return
    vol_outline, vol_worldview, total_chapters = context

    llm = _get_llm()
    if not llm:
        return

    # 参考卷映射
    outlines_dir = ws.reference_outlines
    ref_volumes = list_reference_volumes(outlines_dir)
    if not ref_volumes:
        print("错误：未找到参考小说卷数据。")
        return
    ref_vol = ref_volumes[min(volume - 1, len(ref_volumes) - 1)]
    rewrite_map = load_rewrite_map(ws, volume)
    print(f"  -> 构建卷{volume}故事情节生成上下文...")
    arc_context = _build_arc_context(
        ws=ws,
        llm=llm,
        volume=volume,
        total_chapters=total_chapters,
        vol_outline=vol_outline,
        vol_worldview=vol_worldview,
        rewrite_map=rewrite_map,
        force=force,
    )

    reference_arcs = list_reference_story_arcs(outlines_dir, ref_vol["vol_idx"])
    arc_plans = _plan_story_arcs_from_reference(reference_arcs, total_chapters)
    story_arc_dir = _volume_story_arc_dir(ws, volume)
    if force:
        _clear_story_arc_files(ws, volume)
    os.makedirs(story_arc_dir, exist_ok=True)

    print(f">>> 串行生成卷{volume}的故事情节单元（共{total_chapters}章，规划{len(arc_plans)}个情节单元）<<<")

    generated_items = []
    for plan in arc_plans:
        arc_idx = plan["idx"]
        start_ch = plan["start_ch"]
        end_ch = plan["end_ch"]
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
            continue

        previous_story_arc = ""
        if generated_items:
            previous_story_arc = generated_items[-1]["content"]
        if not previous_story_arc:
            previous_story_arc = "（无前序故事情节单元，这是本卷第一个情节单元）"

        print(f"  提取情节单元{arc_idx}叙事模式（第{start_ch}-{end_ch}章，叙事样本：{plan['reference_range']}）...")
        story_pattern = _extract_story_pattern(
            ws=ws,
            llm=llm,
            volume=volume,
            arc_idx=arc_idx,
            start_ch=start_ch,
            end_ch=end_ch,
            arc_context=arc_context,
            reference_story_arc=plan["reference_story_arc"],
            force=force,
        )

        print(f"  生成新故事情节单元{arc_idx}（第{start_ch}-{end_ch}章）...")
        result = _generate_story_arc_with_audit(
            ws=ws,
            llm=llm,
            volume=volume,
            arc_idx=arc_idx,
            start_ch=start_ch,
            end_ch=end_ch,
            arc_context=arc_context,
            previous_story_arc=previous_story_arc,
            reference_story_arc=plan["reference_story_arc"],
            story_pattern=story_pattern,
        )
        _write_file(arc_file, result)
        generated_items.append({
            "idx": arc_idx,
            "start_ch": start_ch,
            "end_ch": end_ch,
            "file": arc_name,
            "path": arc_file,
            "content": result,
        })
        print(f"  -> 故事情节单元{arc_idx}已保存：{arc_file}")

    _write_story_arc_index(ws, volume, generated_items)
    print(f"\n>>> 卷{volume}故事情节单元已生成，共 {len(generated_items)} 个。<<<")


def gen_serial_chapter_outlines(ws, volume=1, force=False):
    """基于已生成的新书故事情节单元，串行生成本卷逐章章纲。"""
    context = _load_volume_outline_context(ws, volume)
    if not context:
        return
    vol_outline, vol_worldview, total_chapters = context

    ch_out_dir = os.path.join(ws.file_system, "chapter_outlines", f"vol_{volume:02d}")
    story_arcs = _list_novel_story_arcs(ws, volume)
    if not story_arcs:
        print("错误：未找到故事情节单元，无法生成章纲。请先运行 story-arcs。")
        return

    llm = _get_llm()
    if not llm:
        return
    rewrite_map = load_rewrite_map(ws, volume)
    mechanics_context = _load_mechanics_context(ws)

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
                forbidden_terms="章纲阶段不执行禁用词扫描。请以当前舞台、当前故事情节单元、角色线和长线主线为准，保持剧情合理性，不要主动引入与当前阶段不符的旧世界因果。",
                mechanics_context=mechanics_context,
                batch_summary=arc_content,
                previous_chapter_outlines=previous_text,
                chapter_num=ch_num,
            )
            result = normalize_text(llm.generate(prompt))
            _write_file(out_file, result)
            print(f"  -> 第{ch_num}章章纲已保存：{out_file}")

    print(f"\n>>> 卷{volume}全部 {total_chapters} 章章纲已生成。<<<")


def _raw_chapter_backup_path(ws, volume, chapter_num):
    raw_dir = os.path.join(ws.file_system, "drafts", f"vol_{volume:02d}", "raw_chapters")
    return os.path.join(raw_dir, f"{chapter_num:03d}_第{chapter_num}章.raw.md")


def _backup_raw_chapter(ws, volume, chapter_num, content):
    """保存去AI味前的原稿；已存在时保留第一次备份。"""
    backup_path = _raw_chapter_backup_path(ws, volume, chapter_num)
    if os.path.exists(backup_path):
        return backup_path
    _write_file(backup_path, content)
    return backup_path


def _humanize_chapter_text(
    llm,
    ws,
    volume,
    chapter_num,
    chapter_text,
):
    _backup_raw_chapter(ws, volume, chapter_num, chapter_text)
    prompt = PromptLoader.load(
        "humanize_chapter",
        chapter_text=chapter_text,
    )
    result = normalize_text(llm.generate(prompt))
    return result or chapter_text


def gen_serial_chapters(
    ws,
    volume=1,
    start_chapter=1,
    max_chapters=None,
    humanize=True,
    humanize_existing=False,
):
    """串行生成正文：以当前舞台+故事情节单元+本章章纲+前2章正文+写作文风为输入生成下一章正文。"""
    # 项目根目录
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    context = _load_volume_outline_context(ws, volume)
    if not context:
        return
    vol_outline, vol_worldview, _ = context

    # 读取写作文风规范（从项目根目录读取）
    style_guide = _read_file(os.path.join(_root, "core", "system_prompt.md")) or ""
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
        f"core/system_prompt.md {len(style_guide)} 字；"
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

    llm = _get_llm()
    if not llm:
        return
    rewrite_map = load_rewrite_map(ws, volume)
    legacy_map_section = (
        f"=== 旧流程换皮映射表（仅兼容旧工作区；若与当前舞台冲突，以当前舞台为准）===\n{rewrite_map}\n\n"
        if rewrite_map
        else ""
    )
    mechanics_context = _load_mechanics_context(ws)

    out_dir = os.path.join(ws.file_system, "chapters", f"vol_{volume:02d}")
    os.makedirs(out_dir, exist_ok=True)

    # 确定待处理章节
    tasks = []
    for ch_num in range(start_chapter, total_chapters + 1):
        out_file = os.path.join(out_dir, f"{ch_num:03d}_第{ch_num}章.md")
        if os.path.exists(out_file):
            if humanize and humanize_existing:
                tasks.append(("humanize_existing", ch_num))
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
        return

    generate_count = sum(1 for mode, _ in tasks if mode == "generate")
    existing_count = len(tasks) - generate_count
    range_text = f"第 {tasks[0][1]}-{tasks[-1][1]} 章"
    if existing_count:
        print(f"  待处理：{len(tasks)} 章（{range_text}；新生成 {generate_count}，已有正文去AI味 {existing_count}）")
    else:
        print(f"  待生成：{generate_count} 章（{range_text}）")

    for idx, (task_mode, ch_num) in enumerate(tasks):
        out_file = os.path.join(out_dir, f"{ch_num:03d}_第{ch_num}章.md")

        if task_mode == "generate":
            print(f"\n--- 撰写第{ch_num}章（{idx + 1}/{len(tasks)}）---")
        else:
            print(f"\n--- 去AI味第{ch_num}章（{idx + 1}/{len(tasks)}）---")

        if task_mode == "humanize_existing":
            existing_text = _read_file(out_file)
            if not existing_text:
                print(f"  警告：第{ch_num}章正文为空，跳过。")
                continue
            result = _humanize_chapter_text(
                llm,
                ws,
                volume,
                ch_num,
                existing_text,
            )
            _write_file(out_file, result)
            print(f"  -> 第{ch_num}章正文已去AI味并保存：{out_file}")
            print(f"     原稿备份：{_raw_chapter_backup_path(ws, volume, ch_num)}")
            continue

        # 读取本章章纲
        chapter_outline = _read_file(os.path.join(outlines_dir, f"chapter_{ch_num:03d}.md"))
        if not chapter_outline:
            print(f"  警告：第{ch_num}章章纲文件不存在，跳过。")
            continue
        chapter_outline = re.sub(r'\n?\[(?:FINISHED|CONTINUE)\]\s*$', '', chapter_outline).strip()

        # 读取前2章正文（不截断）
        prev_texts = []
        for i in range(max(1, ch_num - 2), ch_num):
            prev_file = os.path.join(out_dir, f"{i:03d}_第{i}章.md")
            content = _read_file(prev_file)
            if content:
                prev_texts.append(content.strip())
        history_section = "\n\n".join(prev_texts) if prev_texts else "（无前序正文，这是第一章）"

        # 读取本章对应的故事情节单元；旧工作区回退批次摘要。
        story_arc_summary = _find_story_arc_for_chapter(ws, volume, ch_num)
        if not story_arc_summary:
            story_arc_summary = _find_legacy_batch_for_chapter(ws, volume, ch_num, total_chapters)

        # 加载参考小说对应章节正文
        from training.outline_builder import load_chapter_text
        ref_chapter_text = load_chapter_text(ws, volume, ch_num, total_chapters)

        context = (
            f"=== 前序正文 ===\n{history_section}\n\n"
            f"=== 当前舞台 ===\n{vol_outline}\n\n"
            f"=== 当前舞台长线与边界 ===\n{vol_worldview}\n\n"
            f"=== 当前故事情节单元 ===\n{story_arc_summary or '（未找到故事情节单元，请严格以章纲为准）'}\n\n"
            f"=== 章纲（第{ch_num}章）===\n{chapter_outline}\n\n"
            f"=== 机制层 mechanics ===\n{mechanics_context}\n\n"
            + legacy_map_section
            + (f"=== 参考小说本章正文 ===\n{ref_chapter_text}\n\n" if ref_chapter_text else "")
            + f"=== 写作规范 ===\n{writing_rules}"
        )

        prompt = PromptLoader.load(
            "adaptive_drafting",
            context=context,
            start_chapter=ch_num,
            end_chapter=ch_num,
            chapter_count=1,
        )
        result = normalize_text(llm.generate(prompt))
        if humanize:
            print(f"  第{ch_num}章正文去AI味处理中...")
            result = _humanize_chapter_text(
                llm,
                ws,
                volume,
                ch_num,
                result,
            )
        _write_file(out_file, result)
        if humanize:
            print(f"  -> 第{ch_num}章正文已保存：{out_file}")
            print(f"     原稿备份：{_raw_chapter_backup_path(ws, volume, ch_num)}")
        else:
            print(f"  -> 第{ch_num}章正文已保存：{out_file}")

    print(f"\n  -> 卷{volume}正文处理完毕（共 {len(tasks)} 章）。")


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

        # 收集本卷的故事情节单元；旧工作区回退批次摘要
        arc_files = sorted(glob.glob(os.path.join(vol["dir_path"], "story_arcs", "arc_*.md")))
        source_files = arc_files or sorted(glob.glob(os.path.join(vol["dir_path"], "batch_*.md")))
        batch_contents = []
        for bf in source_files:
            content = _read_file(bf)
            if content:
                batch_contents.append(content)

        if not batch_contents:
            print(f"  卷{vol_idx}无故事情节单元或批次摘要，跳过。")
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
