"""Phase 0 + Phase 1 implementation for the trajectory-first novel engine.

Phase 0 defines the structured protocol. Phase 1 uses an LLM to generate a
small but complete story trajectory MVP:

    idea/reference -> StoryContract -> StoryBible -> NovelSpine
    -> VolumeRoadmap -> ArcFrame -> ChapterFrame

The generated ChapterFrames are also decoded into the legacy chapter outline
Markdown format so the existing `novel write` command can produce prose.
"""

import json
import os
from typing import Any, Dict, List, Optional

from core.config import ConfigLoader
from core.llm_provider import LLMProvider
from core.models import (
    ArcFrame,
    ChapterFrame,
    NovelSpine,
    StageFrame,
    StoryBible,
    StoryContract,
    VolumeRoadmap,
)
from core.prompt_loader import PromptLoader
from core.reference_repository import ReferenceRepository
from core.repository import NarrativeRepository
from core.text_utils import parse_json_response
from core.validators import (
    validate_arc_frame,
    validate_chapter_frame,
    validate_chapter_sequence,
    validate_novel_spine,
    validate_stage_frame,
    validate_volume_roadmap,
)
from core.world_knowledge import load_world_knowledge_context
from training.reference_finder import load_reference_novel_outline
from training.trajectory_builder import sync_ledger


def _get_llm():
    config = ConfigLoader.get_adaptive_builder_config()
    if not config.get("api_key"):
        config["api_key"] = os.getenv("OPENAI_API_KEY")
    if not config.get("api_key"):
        print("错误：未检测到 API Key。")
        return None
    return LLMProvider(**config)


def _read_file(path: str) -> str:
    if not path or not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def _write_file(path: str, content: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content.rstrip() + "\n")
    return path


def _load_creative_direction(ws, cli_input=None, direction_file=None) -> str:
    if cli_input:
        return cli_input
    if direction_file:
        return _read_file(direction_file)
    return _read_file(ws.creative_direction)


def _as_list(value) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _as_text_list(value) -> List[str]:
    return [str(item).strip() for item in _as_list(value) if str(item).strip()]


def _as_dict(value) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_dict_list(value) -> List[Dict[str, Any]]:
    return [item for item in _as_list(value) if isinstance(item, dict)]


def _as_int(value, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_json_result(raw: str, label: str) -> Dict[str, Any]:
    try:
        return parse_json_response(raw)
    except Exception as e:
        raise ValueError(f"{label} JSON 解析失败：{e}\n原始输出前500字：{raw[:500]}") from e


def _reference_worldview(ws) -> str:
    return _read_file(os.path.join(ws.file_system, "reference_worldview.md"))


def _reference_patterns(ws, max_chars: int = 16000) -> str:
    repo = ReferenceRepository(ws)
    reference_bank = repo.read_reference_pattern_bank()
    mechanics_bank = repo.read_mechanics_pattern_bank()
    if reference_bank:
        print("  -> 已加载 ReferencePatternBank。")
        payload = {"reference_patterns": reference_bank.to_dict()}
        if mechanics_bank:
            payload["mechanics_patterns"] = mechanics_bank.to_dict()
            if mechanics_bank.enabled:
                print("  -> 已加载 MechanicsPatternBank。")
        return json.dumps(payload, ensure_ascii=False, indent=2)[:max_chars]

    print("  -> 未检测到 ReferencePatternBank，降级使用参考大纲/世界观。建议运行 novel reference-distill。")
    parts = []
    outline = load_reference_novel_outline(ws.reference_outlines)
    if outline:
        parts.append("【参考小说全书结构】\n" + outline[:max_chars])
    worldview = _reference_worldview(ws)
    if worldview:
        parts.append("【参考小说世界观】\n" + worldview[: max_chars // 2])
    return "\n\n".join(parts) or "（暂无参考叙事模式，完全根据用户灵感生成。）"


def _normalize_story_contract(data: Dict[str, Any]) -> StoryContract:
    return StoryContract(
        genre=str(data.get("genre", "")),
        target_reader=str(data.get("target_reader", "")),
        core_appeal=str(data.get("core_appeal", "")),
        reader_promises=_as_text_list(data.get("reader_promises")),
        emotional_palette=_as_text_list(data.get("emotional_palette")),
        taboo_breaks=_as_text_list(data.get("taboo_breaks")),
        comparison_notes=_as_text_list(data.get("comparison_notes")),
        success_criteria=_as_text_list(data.get("success_criteria")),
        raw=data,
    )


def _normalize_story_bible(data: Dict[str, Any], direction: str, contract: StoryContract) -> StoryBible:
    return StoryBible(
        title=str(data.get("title", "")),
        synopsis=str(data.get("synopsis", "")),
        creative_direction=direction,
        story_contract=contract.to_dict(),
        core_gameplay=str(data.get("core_gameplay", "")),
        reader_contract=str(data.get("reader_contract", "")),
        long_mainline=str(data.get("long_mainline", "")),
        notes=_as_text_list(data.get("notes")),
        raw_sections={"phase1_story_bible": json.dumps(data, ensure_ascii=False, indent=2)},
    )


def _normalize_novel_spine(data: Dict[str, Any]) -> NovelSpine:
    return NovelSpine(
        premise=str(data.get("premise", "")),
        central_question=str(data.get("central_question", "")),
        final_destination=str(data.get("final_destination", "")),
        protagonist_arc=str(data.get("protagonist_arc", "")),
        core_conflict=str(data.get("core_conflict", "")),
        antagonist_pressure=str(data.get("antagonist_pressure", "")),
        progression_axis=_as_text_list(data.get("progression_axis")),
        long_debts=_as_text_list(data.get("long_debts")),
        payoff_schedule=_as_dict_list(data.get("payoff_schedule")),
        volume_functions=_as_dict_list(data.get("volume_functions")),
        state_anchors=_as_dict_list(data.get("state_anchors")),
        must_not_break=_as_text_list(data.get("must_not_break")),
        raw=data,
    )


def _normalize_volume_roadmap(data: Dict[str, Any], volume: int, chapters_per_stage: int) -> VolumeRoadmap:
    return VolumeRoadmap(
        volume=_as_int(data.get("volume"), volume),
        title=str(data.get("title") or f"第{volume}卷"),
        expected_chapters=_as_int(data.get("expected_chapters"), chapters_per_stage),
        volume_function=str(data.get("volume_function") or data.get("stage_function") or ""),
        volume_goal=str(data.get("volume_goal") or data.get("goal") or ""),
        opening_state=str(data.get("opening_state", "")),
        end_state=str(data.get("end_state", "")),
        main_conflict=str(data.get("main_conflict") or data.get("conflict") or ""),
        reader_expectation=str(data.get("reader_expectation", "")),
        gameplay_value=str(data.get("gameplay_value", "")),
        rules=str(data.get("rules", "")),
        shortlines=_as_text_list(data.get("shortlines")),
        resources=_as_text_list(data.get("resources")),
        pressures=_as_text_list(data.get("pressures")),
        allies=_as_text_list(data.get("allies")),
        major_payoffs=_as_text_list(data.get("major_payoffs")),
        new_debts=_as_text_list(data.get("new_debts")),
        hidden_threads=_as_text_list(data.get("hidden_threads")),
        mechanics_plan=_as_text_list(data.get("mechanics_plan")),
        state_anchors=_as_dict_list(data.get("state_anchors")),
        cannot_reveal=str(data.get("cannot_reveal", "")),
        raw=data,
    )


def _stage_from_volume_roadmap(roadmap: VolumeRoadmap) -> StageFrame:
    return StageFrame(
        volume=roadmap.volume,
        title=roadmap.title,
        expected_chapters=roadmap.expected_chapters,
        stage_function=roadmap.volume_function,
        gameplay_value=roadmap.gameplay_value,
        mainline_progress=roadmap.volume_goal,
        rules=roadmap.rules,
        shortlines=roadmap.shortlines,
        resources=roadmap.resources,
        pressures=roadmap.pressures,
        allies=roadmap.allies,
        character_nodes=roadmap.reader_expectation,
        end_state=roadmap.end_state,
        hooks="；".join(roadmap.new_debts + roadmap.hidden_threads),
        cannot_reveal=roadmap.cannot_reveal,
        raw_text=json.dumps(roadmap.to_dict(), ensure_ascii=False, indent=2),
        metadata={"source": "phase1_builder.volume_roadmap"},
    )


def _normalize_arc_frame(data: Dict[str, Any], volume: int, arc_index: int, chapters_per_stage: int) -> ArcFrame:
    start = _as_int(data.get("start_chapter"), 1)
    end = _as_int(data.get("end_chapter"), start)
    start = max(1, min(chapters_per_stage, start))
    end = max(start, min(chapters_per_stage, end))
    return ArcFrame(
        volume=_as_int(data.get("volume"), volume),
        arc_index=_as_int(data.get("arc_index"), arc_index),
        start_chapter=start,
        end_chapter=end,
        title=str(data.get("title") or f"情节单元{arc_index}"),
        core_event=str(data.get("core_event", "")),
        pattern_landing=str(data.get("pattern_landing", "")),
        conflict=str(data.get("conflict", "")),
        emotion_curve=_as_text_list(data.get("emotion_curve")),
        protagonist_state_change=str(data.get("protagonist_state_change", "")),
        foreshadowing=_as_text_list(data.get("foreshadowing")),
        chapter_pacing=_as_text_list(data.get("chapter_pacing")),
        world_elements=_as_text_list(data.get("world_elements")),
        self_check=str(data.get("self_check", "")),
        raw_text=json.dumps(data, ensure_ascii=False, indent=2),
        metadata={"source": "phase1_builder.arc_lattice"},
    )


def _normalize_stage(data: Dict[str, Any], stage_index: int, chapters_per_stage: int) -> StageFrame:
    return StageFrame(
        volume=int(data.get("volume") or stage_index),
        title=str(data.get("title", f"舞台{stage_index}")),
        expected_chapters=int(data.get("expected_chapters") or chapters_per_stage),
        stage_function=str(data.get("stage_function", "")),
        gameplay_value=str(data.get("gameplay_value", "")),
        mainline_progress=str(data.get("mainline_progress", "")),
        rules=str(data.get("rules", "")),
        shortlines=_as_text_list(data.get("shortlines")),
        resources=_as_text_list(data.get("resources")),
        pressures=_as_text_list(data.get("pressures")),
        allies=_as_text_list(data.get("allies")),
        character_nodes=str(data.get("character_nodes", "")),
        end_state=str(data.get("end_state", "")),
        hooks=str(data.get("hooks", "")),
        cannot_reveal=str(data.get("cannot_reveal", "")),
        raw_text=json.dumps(data, ensure_ascii=False, indent=2),
        metadata={"source": "phase1_builder"},
    )


def _normalize_chapter(
    data: Dict[str, Any],
    stage_index: int,
    chapter_num: int,
    chapters_per_stage: int,
) -> ChapterFrame:
    events = []
    for idx, event in enumerate(_as_list(data.get("events")), 1):
        if isinstance(event, dict):
            label = str(event.get("label") or f"情节点{idx}")
            text = str(event.get("text") or event.get("event") or "")
        else:
            label = f"情节点{idx}"
            text = str(event)
        if text.strip():
            events.append({"label": label, "text": text.strip()})

    return ChapterFrame(
        volume=_as_int(data.get("volume"), stage_index),
        chapter=_as_int(data.get("chapter"), chapter_num),
        title=str(data.get("title", f"第{chapter_num}章")),
        story_arc_index=_as_int(data.get("story_arc_index") or data.get("arc_index"), 0) or None,
        opening_state=str(data.get("opening_state", "")),
        goal=str(data.get("goal", "")),
        events=events,
        emotion_curve=_as_text_list(data.get("emotion_curve")),
        emotional_peak=str(data.get("emotional_peak", "")),
        hook=str(data.get("hook", "")),
        hook_type=str(data.get("hook_type", "")),
        foreshadowing=_as_text_list(data.get("foreshadowing")),
        characters=_as_text_list(data.get("characters")),
        world_elements=_as_text_list(data.get("world_elements")),
        mechanics_events=_as_text_list(data.get("mechanics_events")),
        start_state=_as_dict(data.get("start_state")),
        end_state=_as_dict(data.get("end_state")),
        must_not_happen=_as_text_list(data.get("must_not_happen")),
        metadata={
            "source": "phase1_builder",
            "global_chapter": (stage_index - 1) * chapters_per_stage + _as_int(data.get("chapter"), chapter_num),
        },
    )


def _render_stage_roadmap(stages: List[StageFrame]) -> str:
    parts = []
    for stage in sorted(stages, key=lambda item: item.volume):
        parts.append(
            "\n".join(
                [
                    f"# 舞台{stage.volume}：{stage.title}",
                    f"预计章节数：{stage.expected_chapters}",
                    f"阶段功能：{stage.stage_function}",
                    f"玩法价值：{stage.gameplay_value}",
                    f"长线主线推进：{stage.mainline_progress}",
                    f"舞台规则：{stage.rules}",
                    "舞台内短线：" + "；".join(stage.shortlines),
                    "主要资源：" + "；".join(stage.resources),
                    "主要敌人/压力：" + "；".join(stage.pressures),
                    "盟友/见证者：" + "；".join(stage.allies),
                    f"角色节点：{stage.character_nodes}",
                    f"结束状态：{stage.end_state}",
                    f"后患与钩子：{stage.hooks}",
                    f"不能提前：{stage.cannot_reveal}",
                ]
            )
        )
    return "\n\n".join(parts)


def _render_novel_spine(spine: NovelSpine) -> str:
    def lines_for_dicts(items: List[Dict[str, Any]]) -> List[str]:
        return ["- " + json.dumps(item, ensure_ascii=False) for item in items]

    lines = [
        "# 全书主线 Spine",
        "",
        "## 核心命题",
        spine.premise or "待补充",
        "",
        "## 中央问题",
        spine.central_question or "待补充",
        "",
        "## 终局方向",
        spine.final_destination or "待补充",
        "",
        "## 主角长期变化",
        spine.protagonist_arc or "待补充",
        "",
        "## 核心矛盾",
        spine.core_conflict or "待补充",
        "",
        "## 压力来源",
        spine.antagonist_pressure or "待补充",
        "",
        "## 推进轴",
        "\n".join(f"- {item}" for item in spine.progression_axis) or "- 待补充",
        "",
        "## 长线债务",
        "\n".join(f"- {item}" for item in spine.long_debts) or "- 待补充",
        "",
        "## 兑现排期",
        "\n".join(lines_for_dicts(spine.payoff_schedule)) or "- 待补充",
        "",
        "## 分卷功能",
        "\n".join(lines_for_dicts(spine.volume_functions)) or "- 待补充",
        "",
        "## 状态锚点",
        "\n".join(lines_for_dicts(spine.state_anchors)) or "- 待补充",
        "",
        "## 不能破坏",
        "\n".join(f"- {item}" for item in spine.must_not_break) or "- 待补充",
    ]
    return "\n".join(lines)


def _render_volume_roadmaps(roadmaps: List[VolumeRoadmap]) -> str:
    parts = []
    for roadmap in sorted(roadmaps, key=lambda item: item.volume):
        parts.append(
            "\n".join(
                [
                    f"# 卷{roadmap.volume}：{roadmap.title}",
                    f"预计章节数：{roadmap.expected_chapters}",
                    f"卷功能：{roadmap.volume_function}",
                    f"卷目标：{roadmap.volume_goal}",
                    f"开局状态：{roadmap.opening_state}",
                    f"结束状态：{roadmap.end_state}",
                    f"核心冲突：{roadmap.main_conflict}",
                    f"读者期待：{roadmap.reader_expectation}",
                    f"玩法价值：{roadmap.gameplay_value}",
                    f"舞台规则：{roadmap.rules}",
                    "短线：" + "；".join(roadmap.shortlines),
                    "资源：" + "；".join(roadmap.resources),
                    "压力：" + "；".join(roadmap.pressures),
                    "盟友/功能位：" + "；".join(roadmap.allies),
                    "本卷兑现：" + "；".join(roadmap.major_payoffs),
                    "新增债务：" + "；".join(roadmap.new_debts),
                    "隐藏线：" + "；".join(roadmap.hidden_threads),
                    "机制计划：" + "；".join(roadmap.mechanics_plan),
                    f"不能提前：{roadmap.cannot_reveal}",
                ]
            )
        )
    return "\n\n".join(parts)


def render_chapter_outline(frame: ChapterFrame) -> str:
    lines = [f"【第{frame.chapter}章 章纲】", "# 本章目标与开局"]
    lines.append(frame.opening_state or frame.goal or "本章开局状态待补充。")
    events = frame.events[:5]
    while len(events) < 5:
        events.append({"label": f"情节点{len(events) + 1}", "text": "承接本章目标推进一个具体事件，并制造明确情绪刺激。"})
    for idx, event in enumerate(events, 1):
        lines.extend(["", f"# 情节点{idx}", event.get("text", "").strip() or "待补充。"])

    curve = "→".join(frame.emotion_curve) if frame.emotion_curve else "待补充"
    lines.extend(
        [
            "",
            "# 情绪曲线与爆点",
            f"情绪曲线：{curve}。本章最强情绪爆点：{frame.emotional_peak or '待补充'}",
            "",
            "# 伏笔与信息差",
            "；".join(frame.foreshadowing) if frame.foreshadowing else "无",
            "",
            "# 章末钩子",
            (frame.hook or "待补充章末钩子") + (f"。钩子类型：{frame.hook_type}" if frame.hook_type else ""),
            "",
            "# 本章角色",
            "；".join(frame.characters) if frame.characters else "待补充",
            "",
            "# 本章世界观元素",
            "；".join(frame.world_elements) if frame.world_elements else "无",
            "",
            "# 机制事件草案",
            "；".join(frame.mechanics_events) if frame.mechanics_events else "无",
        ]
    )
    return "\n".join(lines)


def _write_story_design_assets(
    ws,
    bible: StoryBible,
    spine: NovelSpine,
    roadmaps: List[VolumeRoadmap],
    stages: List[StageFrame],
) -> None:
    design_dir = os.path.join(ws.file_system, "story_design")
    _write_file(os.path.join(design_dir, "core_gameplay.md"), bible.core_gameplay or "（未生成核心玩法）")
    _write_file(os.path.join(design_dir, "long_mainline.md"), _render_novel_spine(spine))
    _write_file(os.path.join(design_dir, "volume_roadmaps.md"), _render_volume_roadmaps(roadmaps))
    _write_file(os.path.join(design_dir, "stage_roadmap.md"), _render_stage_roadmap(stages))
    _write_file(
        os.path.join(design_dir, "character_arcs.md"),
        "\n".join(bible.notes) if bible.notes else "（Phase 1 MVP 未单独生成角色成长线，请在后续阶段补充。）",
    )
    _write_file(
        os.path.join(ws.file_system, "novel_name_synopsis.md"),
        f"# {bible.title or '暂定书名'}\n\n{bible.synopsis or '（未生成简介）'}",
    )


def _write_chapter_outlines(ws, frames: List[ChapterFrame]) -> None:
    for frame in frames:
        path = os.path.join(
            ws.file_system,
            "chapter_outlines",
            f"vol_{frame.volume:02d}",
            f"chapter_{frame.chapter:03d}.md",
        )
        _write_file(path, render_chapter_outline(frame))


def _infer_arc_index(arcs: List[ArcFrame], chapter: int) -> Optional[int]:
    for arc in arcs:
        if arc.start_chapter <= chapter <= arc.end_chapter:
            return arc.arc_index
    return None


def generate_phase1_trajectory(
    ws,
    *,
    force: bool = False,
    creative_direction: Optional[str] = None,
    direction_file: Optional[str] = None,
    stage_count: int = 3,
    chapters_per_stage: int = 20,
    decode_outlines: bool = True,
    write_first: int = 0,
    humanize: bool = True,
):
    """Generate the Phase 1 MVP trajectory and optional first prose chapters."""
    repo = NarrativeRepository(ws)
    if repo.read_story_contract() and not force:
        print("Phase 1 轨迹已存在。使用 --force 重新生成。")
        return

    llm = _get_llm()
    if not llm:
        return

    direction = _load_creative_direction(ws, creative_direction, direction_file)
    if direction:
        _write_file(ws.creative_direction, direction)

    reference_outline = load_reference_novel_outline(ws.reference_outlines) or "（暂无参考小说全书大纲）"
    reference_worldview = _reference_worldview(ws) or "（暂无参考小说世界观）"
    world_knowledge = load_world_knowledge_context(ws) or "（未提供目标世界资料）"
    reference_patterns = _reference_patterns(ws)

    print(">>> Phase 1：生成 StoryContract 与 StoryBible <<<")
    raw_contract = llm.generate(
        PromptLoader.load(
            "phase1_story_contract",
            creative_direction=direction or "（用户未提供具体方向）",
            reference_outline=reference_outline,
            reference_worldview=reference_worldview,
            world_knowledge=world_knowledge,
            reference_patterns=reference_patterns,
            stage_count=stage_count,
            chapters_per_stage=chapters_per_stage,
        ),
        is_json=True,
    )
    payload = _parse_json_result(raw_contract, "StoryContract")
    contract = _normalize_story_contract(_as_dict(payload.get("story_contract")))
    bible = _normalize_story_bible(_as_dict(payload.get("story_bible")), direction, contract)
    bible.stage_count = stage_count
    repo.write_story_contract(contract)
    repo.write_story_bible(bible)

    print(">>> Phase 1：生成全书主线 NovelSpine <<<")
    raw_spine = llm.generate(
        PromptLoader.load(
            "phase1_novel_spine",
            story_contract=json.dumps(contract.to_dict(), ensure_ascii=False, indent=2),
            story_bible=json.dumps(bible.to_dict(), ensure_ascii=False, indent=2),
            reference_patterns=reference_patterns,
            world_knowledge=world_knowledge,
            stage_count=stage_count,
            chapters_per_stage=chapters_per_stage,
        ),
        is_json=True,
    )
    spine_payload = _parse_json_result(raw_spine, "NovelSpine")
    spine = _normalize_novel_spine(_as_dict(spine_payload.get("novel_spine") or spine_payload.get("spine") or spine_payload))
    repo.write_novel_spine(spine)
    repo.write_critic_report(validate_novel_spine(spine), category="trajectory")

    all_stages: List[StageFrame] = []
    all_roadmaps: List[VolumeRoadmap] = []
    all_arcs: List[ArcFrame] = []
    all_chapters: List[ChapterFrame] = []
    previous_volume_summary = "（无前序卷，这是第一卷。）"

    if force:
        repo.remove_generated_volume_roadmaps()
        repo.remove_generated_stage_frames()
        for volume in range(1, stage_count + 1):
            repo.remove_generated_arc_frames(volume)
            repo.remove_generated_chapter_frames(volume)

    for volume in range(1, stage_count + 1):
        print(f">>> Phase 1：生成卷 {volume}/{stage_count} 的 VolumeRoadmap <<<")
        raw_roadmap = llm.generate(
            PromptLoader.load(
                "phase1_volume_roadmap",
                story_contract=json.dumps(contract.to_dict(), ensure_ascii=False, indent=2),
                story_bible=json.dumps(bible.to_dict(), ensure_ascii=False, indent=2),
                novel_spine=json.dumps(spine.to_dict(), ensure_ascii=False, indent=2),
                stage_count=stage_count,
                volume=volume,
                chapters_per_stage=chapters_per_stage,
                previous_volume_summary=previous_volume_summary,
                reference_patterns=reference_patterns,
            ),
            is_json=True,
        )
        roadmap_payload = _parse_json_result(raw_roadmap, f"VolumeRoadmap {volume}")
        roadmap = _normalize_volume_roadmap(
            _as_dict(roadmap_payload.get("volume_roadmap") or roadmap_payload.get("roadmap") or roadmap_payload),
            volume,
            chapters_per_stage,
        )
        repo.write_volume_roadmap(roadmap)
        repo.write_critic_report(validate_volume_roadmap(roadmap), category="trajectory")
        all_roadmaps.append(roadmap)

        stage = _stage_from_volume_roadmap(roadmap)
        repo.write_stage_frame(stage)
        repo.write_critic_report(validate_stage_frame(stage), category="trajectory")
        all_stages.append(stage)

        print(f">>> Phase 1：生成卷 {volume}/{stage_count} 的 Arc Lattice <<<")
        raw_arcs = llm.generate(
            PromptLoader.load(
                "phase1_arc_lattice",
                story_contract=json.dumps(contract.to_dict(), ensure_ascii=False, indent=2),
                story_bible=json.dumps(bible.to_dict(), ensure_ascii=False, indent=2),
                novel_spine=json.dumps(spine.to_dict(), ensure_ascii=False, indent=2),
                volume_roadmap=json.dumps(roadmap.to_dict(), ensure_ascii=False, indent=2),
                stage_count=stage_count,
                volume=volume,
                chapters_per_stage=chapters_per_stage,
                reference_patterns=reference_patterns,
            ),
            is_json=True,
        )
        arc_payload = _parse_json_result(raw_arcs, f"ArcLattice {volume}")
        if isinstance(arc_payload, list):
            arc_payloads = arc_payload
        else:
            arc_payloads = _as_list(arc_payload.get("arcs") or arc_payload.get("arc_lattice"))
        volume_arcs: List[ArcFrame] = []
        for idx, item in enumerate(arc_payloads, 1):
            if not isinstance(item, dict):
                continue
            arc = _normalize_arc_frame(item, volume, idx, chapters_per_stage)
            repo.write_arc_frame(arc)
            repo.write_critic_report(validate_arc_frame(arc), category="trajectory")
            volume_arcs.append(arc)
            all_arcs.append(arc)

        print(f">>> Phase 1：生成卷 {volume}/{stage_count} 的 Chapter Trajectory <<<")
        raw_chapters = llm.generate(
            PromptLoader.load(
                "phase1_chapter_trajectory",
                story_contract=json.dumps(contract.to_dict(), ensure_ascii=False, indent=2),
                story_bible=json.dumps(bible.to_dict(), ensure_ascii=False, indent=2),
                novel_spine=json.dumps(spine.to_dict(), ensure_ascii=False, indent=2),
                volume_roadmap=json.dumps(roadmap.to_dict(), ensure_ascii=False, indent=2),
                arc_lattice=json.dumps([arc.to_dict() for arc in volume_arcs], ensure_ascii=False, indent=2),
                stage_count=stage_count,
                volume=volume,
                chapters_per_stage=chapters_per_stage,
                previous_volume_summary=previous_volume_summary,
                reference_patterns=reference_patterns,
            ),
            is_json=True,
        )
        chapter_payload = _parse_json_result(raw_chapters, f"ChapterTrajectory {volume}")
        if isinstance(chapter_payload, list):
            chapter_payloads = chapter_payload
        else:
            chapter_payloads = _as_list(chapter_payload.get("chapters") or chapter_payload.get("chapter_trajectory"))
        if len(chapter_payloads) != chapters_per_stage:
            print(f"  警告：卷{volume}返回 {len(chapter_payloads)} 章，目标为 {chapters_per_stage} 章。")
        volume_chapters = []
        for idx, item in enumerate(chapter_payloads, 1):
            if not isinstance(item, dict):
                continue
            frame = _normalize_chapter(item, volume, idx, chapters_per_stage)
            frame.volume = volume
            if frame.story_arc_index is None:
                frame.story_arc_index = _infer_arc_index(volume_arcs, frame.chapter)
            repo.write_chapter_frame(frame)
            repo.write_critic_report(validate_chapter_frame(frame), category="trajectory")
            volume_chapters.append(frame)
            all_chapters.append(frame)

        repo.write_critic_report(validate_chapter_sequence(volume_chapters, volume), category="trajectory")
        previous_volume_summary = (
            f"卷{roadmap.volume}《{roadmap.title}》结束状态：{roadmap.end_state}\n"
            f"已兑现：{'；'.join(roadmap.major_payoffs)}\n"
            f"新债务：{'；'.join(roadmap.new_debts + roadmap.hidden_threads)}"
        )

    _write_story_design_assets(ws, bible, spine, all_roadmaps, all_stages)
    if decode_outlines:
        _write_chapter_outlines(ws, all_chapters)
        print(f"  -> 已解码章纲：{len(all_chapters)} 章")
    sync_ledger(ws, quiet=True)

    print(
        f"\n>>> Phase 1 轨迹生成完成：1 条 NovelSpine，{len(all_roadmaps)} 个 VolumeRoadmap，"
        f"{len(all_arcs)} 个 ArcFrame，{len(all_chapters)} 个 ChapterFrame。<<<"
    )

    if write_first > 0:
        print(f"\n>>> 基于 Phase 1 轨迹生成前 {write_first} 章章节细纲 <<<")
        from training.adaptive_builder import gen_serial_chapter_detail_outlines

        remaining = write_first
        for volume in range(1, stage_count + 1):
            if remaining <= 0:
                break
            count = min(remaining, chapters_per_stage)
            gen_serial_chapter_detail_outlines(
                ws,
                volume=volume,
                start_chapter=1,
                max_chapters=count,
            )
            remaining -= count
