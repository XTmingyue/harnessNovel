"""Convert existing Markdown planning assets into structured story frames."""

import os
import re
from typing import Dict, Iterable, List, Optional

from core.models import ArcFrame, ChapterFrame, StageFrame, StoryBible


SECTION_RE = re.compile(r"(?m)^#\s*(.+?)\s*$")


def split_sections(text: str) -> Dict[str, str]:
    """Split prompt-style Markdown sections keyed by heading text."""
    if not text:
        return {}
    matches = list(SECTION_RE.finditer(text))
    if not matches:
        return {}
    sections: Dict[str, str] = {}
    for idx, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if title in sections:
            sections[title] = sections[title].rstrip() + "\n\n" + content
        else:
            sections[title] = content
    return sections


def _section(sections: Dict[str, str], *names: str) -> str:
    for name in names:
        if name in sections:
            return sections[name].strip()
    for key, value in sections.items():
        if any(name in key for name in names):
            return value.strip()
    return ""


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _split_items(text: str) -> List[str]:
    text = (text or "").strip()
    if not text or text in {"无", "（无）"}:
        return []
    raw_items: List[str] = []
    for line in text.splitlines():
        stripped = line.strip().strip("-*• \t")
        if not stripped:
            continue
        if len(stripped) > 80 and not re.match(r"^(第?\d+|[一二三四五六七八九十]+)[、.：:]", stripped):
            raw_items.append(stripped)
            continue
        raw_items.extend(item.strip() for item in re.split(r"[；;]", stripped) if item.strip())
    return raw_items


def _extract_curve(text: str) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    match = re.search(r"情绪曲线[：:]\s*([^\n。]+)", text)
    curve_text = match.group(1) if match else _first_line(text)
    parts = re.split(r"\s*(?:→|->|=>|，|,|、)\s*", curve_text)
    return [part.strip("。；; ") for part in parts if part.strip("。；; ")]


def _extract_hook_type(text: str) -> str:
    match = re.search(r"钩子类型[（(]?(.*?)[）)]?[：:]\s*([^\n。；;]+)", text or "")
    if match:
        return match.group(2).strip()
    match = re.search(r"类型[：:]\s*([^\n。；;]+)", text or "")
    return match.group(1).strip() if match else ""


def _extract_labeled_field(text: str, label: str, labels: Iterable[str]) -> str:
    labels_pattern = "|".join(re.escape(item) for item in labels)
    pattern = re.compile(
        rf"(?ms)^{re.escape(label)}\s*[：:]\s*(.*?)(?=^(?:{labels_pattern})\s*[：:]|^#|\Z)"
    )
    match = pattern.search(text or "")
    return match.group(1).strip() if match else ""


STAGE_LABELS = [
    "预计章节数",
    "阶段功能",
    "玩法价值",
    "长线主线推进",
    "舞台规则",
    "舞台内短线",
    "主要资源",
    "主要敌人/压力",
    "盟友/见证者",
    "角色节点",
    "结束状态",
    "后患与钩子",
    "不能提前",
]


def extract_stage_frames(stage_roadmap: str) -> List[StageFrame]:
    frames: List[StageFrame] = []
    if not stage_roadmap:
        return frames
    pattern = re.compile(r"(?ms)^#\s*舞台\s*0*(\d+)[：:](.*?)(?=^#\s*舞台\s*\d+[：:]|\Z)")
    for match in pattern.finditer(stage_roadmap):
        volume = int(match.group(1))
        raw = match.group(0).strip()
        title = _first_line(match.group(2)).strip()
        title = title.splitlines()[0].strip() if title else f"舞台{volume}"
        expected_text = _extract_labeled_field(raw, "预计章节数", STAGE_LABELS)
        nums = [int(item) for item in re.findall(r"\d+", expected_text)]
        expected_chapters = max(nums) if nums else 0
        frames.append(
            StageFrame(
                volume=volume,
                title=title,
                expected_chapters=expected_chapters,
                stage_function=_extract_labeled_field(raw, "阶段功能", STAGE_LABELS),
                gameplay_value=_extract_labeled_field(raw, "玩法价值", STAGE_LABELS),
                mainline_progress=_extract_labeled_field(raw, "长线主线推进", STAGE_LABELS),
                rules=_extract_labeled_field(raw, "舞台规则", STAGE_LABELS),
                shortlines=_split_items(_extract_labeled_field(raw, "舞台内短线", STAGE_LABELS)),
                resources=_split_items(_extract_labeled_field(raw, "主要资源", STAGE_LABELS)),
                pressures=_split_items(_extract_labeled_field(raw, "主要敌人/压力", STAGE_LABELS)),
                allies=_split_items(_extract_labeled_field(raw, "盟友/见证者", STAGE_LABELS)),
                character_nodes=_extract_labeled_field(raw, "角色节点", STAGE_LABELS),
                end_state=_extract_labeled_field(raw, "结束状态", STAGE_LABELS),
                hooks=_extract_labeled_field(raw, "后患与钩子", STAGE_LABELS),
                cannot_reveal=_extract_labeled_field(raw, "不能提前", STAGE_LABELS),
                raw_text=raw,
            )
        )
    return frames


def build_story_bible_from_assets(
    *,
    creative_direction: str = "",
    core_gameplay: str = "",
    long_mainline: str = "",
    stage_roadmap: str = "",
    character_arcs: str = "",
    name_synopsis: str = "",
    source_paths: Optional[Dict[str, str]] = None,
) -> StoryBible:
    sections = split_sections(name_synopsis)
    title = ""
    synopsis = ""
    if name_synopsis:
        title_match = re.search(r"(?:书名|标题)[：:]\s*([^\n]+)", name_synopsis)
        title = title_match.group(1).strip() if title_match else _first_line(name_synopsis).lstrip("#").strip()
        synopsis = _section(sections, "简介", "故事简介", "文案")
    core_sections = split_sections(core_gameplay)
    reader_contract = _section(core_sections, "读者情绪反馈循环", "核心玩法一句话")
    return StoryBible(
        title=title,
        synopsis=synopsis,
        creative_direction=creative_direction or "",
        core_gameplay=core_gameplay or "",
        reader_contract=reader_contract,
        long_mainline=long_mainline or "",
        stage_count=len(extract_stage_frames(stage_roadmap)),
        source_paths=source_paths or {},
        raw_sections={
            "core_gameplay": core_gameplay or "",
            "long_mainline": long_mainline or "",
            "stage_roadmap": stage_roadmap or "",
            "character_arcs": character_arcs or "",
            "name_synopsis": name_synopsis or "",
        },
    )


def arc_frame_from_markdown(
    *,
    volume: int,
    arc_index: int,
    start_chapter: int,
    end_chapter: int,
    text: str,
    source_path: str = "",
) -> ArcFrame:
    sections = split_sections(text)
    first = _first_line(text)
    title = first
    title_match = re.search(r"【情节\d*：第\d+-\d+章[｜|:：]\s*(.*?)】", first)
    if title_match:
        title = title_match.group(1).strip()
    conflict = _section(sections, "矛盾与情绪")
    return ArcFrame(
        volume=volume,
        arc_index=arc_index,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        title=title,
        core_event=_section(sections, "核心事件"),
        pattern_landing=_section(sections, "叙事模式落地"),
        conflict=conflict,
        emotion_curve=_extract_curve(conflict),
        protagonist_state_change=_section(sections, "主角状态变化"),
        foreshadowing=_split_items(_section(sections, "伏笔与线索")),
        chapter_pacing=_split_items(_section(sections, "章节节奏建议")),
        world_elements=_split_items(_section(sections, "世界观元素")),
        self_check=_section(sections, "合理性自检"),
        raw_text=text or "",
        source_path=source_path,
        metadata={"source_file": os.path.basename(source_path) if source_path else ""},
    )


def chapter_frame_from_outline(
    *,
    volume: int,
    chapter: int,
    outline_text: str,
    source_outline_path: str = "",
    story_arc_index: Optional[int] = None,
) -> ChapterFrame:
    sections = split_sections(outline_text)
    first = _first_line(outline_text)
    title = first.strip("【】")
    title_match = re.search(r"第\s*\d+\s*章\s*(.*)", first)
    if title_match:
        title = title_match.group(1).strip() or first
    opening_state = _section(sections, "本章目标与开局")
    events = []
    for idx in range(1, 8):
        content = _section(sections, f"情节点{idx}")
        if content:
            events.append({"label": f"情节点{idx}", "text": content})
    emotion_text = _section(sections, "情绪曲线与爆点")
    hook_text = _section(sections, "章末钩子")
    mechanics_text = _section(sections, "机制事件草案")
    return ChapterFrame(
        volume=volume,
        chapter=chapter,
        title=title,
        story_arc_index=story_arc_index,
        opening_state=opening_state,
        goal=opening_state[:240],
        events=events,
        emotion_curve=_extract_curve(emotion_text),
        emotional_peak=emotion_text,
        hook=hook_text,
        hook_type=_extract_hook_type(hook_text),
        foreshadowing=_split_items(_section(sections, "伏笔与信息差")),
        characters=_split_items(_section(sections, "本章角色")),
        world_elements=_split_items(_section(sections, "本章世界观元素")),
        mechanics_events=_split_items(mechanics_text),
        start_state={"opening_state": opening_state},
        end_state={"hook": hook_text, "last_event": events[-1]["text"] if events else ""},
        source_outline_path=source_outline_path,
        raw_outline=outline_text or "",
        metadata={"source_file": os.path.basename(source_outline_path) if source_outline_path else ""},
    )
