"""Build and audit structured narrative trajectory assets.

This module bridges the legacy Markdown workflow and the new structured frame
layer. It intentionally does not call an LLM; it only parses existing planning
assets, writes JSON frames, and runs deterministic audits.
"""

import os
import re
from typing import Dict, List, Optional

from core.frame_extractor import (
    arc_frame_from_markdown,
    build_story_bible_from_assets,
    chapter_frame_from_outline,
    extract_stage_frames,
)
from core.models import ContinuityLedger
from core.reference_repository import ReferenceRepository
from core.repository import NarrativeRepository
from core.validators import (
    validate_arc_frame,
    validate_chapter_frame,
    validate_chapter_sequence,
    validate_mechanics_presence,
    validate_novel_spine,
    validate_stage_frame,
    validate_volume_roadmap,
)


ARC_FILE_RE = re.compile(r"^arc_(\d+)_ch(\d+)_(\d+)\.md$")
CHAPTER_OUTLINE_RE = re.compile(r"^chapter_(\d+)\.md$")
VOL_DIR_RE = re.compile(r"^vol_(\d+)$")


def _read_file(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def _story_design_path(ws, name: str) -> str:
    return os.path.join(ws.file_system, "story_design", name)


def _source_paths(ws) -> Dict[str, str]:
    return {
        "creative_direction": ws.creative_direction,
        "core_gameplay": _story_design_path(ws, "core_gameplay.md"),
        "long_mainline": _story_design_path(ws, "long_mainline.md"),
        "stage_roadmap": _story_design_path(ws, "stage_roadmap.md"),
        "character_arcs": _story_design_path(ws, "character_arcs.md"),
        "novel_name_synopsis": os.path.join(ws.file_system, "novel_name_synopsis.md"),
    }


def _available_volumes(base_dir: str) -> List[int]:
    if not os.path.isdir(base_dir):
        return []
    volumes = []
    for name in sorted(os.listdir(base_dir)):
        match = VOL_DIR_RE.match(name)
        if match and os.path.isdir(os.path.join(base_dir, name)):
            volumes.append(int(match.group(1)))
    return volumes


def sync_story_design_frames(ws, quiet: bool = False) -> Dict[str, int]:
    repo = NarrativeRepository(ws)
    paths = _source_paths(ws)
    stage_roadmap = _read_file(paths["stage_roadmap"])
    bible = build_story_bible_from_assets(
        creative_direction=_read_file(paths["creative_direction"]),
        core_gameplay=_read_file(paths["core_gameplay"]),
        long_mainline=_read_file(paths["long_mainline"]),
        stage_roadmap=stage_roadmap,
        character_arcs=_read_file(paths["character_arcs"]),
        name_synopsis=_read_file(paths["novel_name_synopsis"]),
        source_paths=paths,
    )
    repo.write_story_bible(bible)

    stage_count = 0
    repo.remove_generated_stage_frames()
    for frame in extract_stage_frames(stage_roadmap):
        repo.write_stage_frame(frame)
        repo.write_critic_report(validate_stage_frame(frame), category="trajectory")
        stage_count += 1

    if not quiet:
        print(f"  -> 已同步结构化故事圣经与舞台帧：{stage_count} 个舞台")
    return {"story_bible": 1, "stage_frames": stage_count}


def sync_arc_frames(ws, volume: Optional[int] = None, clear: bool = True, quiet: bool = False) -> Dict[str, int]:
    repo = NarrativeRepository(ws)
    source_base = os.path.join(ws.file_system, "story_arcs")
    volumes = [volume] if volume is not None else _available_volumes(source_base)
    total = 0
    for vol in volumes:
        source_dir = os.path.join(source_base, f"vol_{vol:02d}")
        if not os.path.isdir(source_dir):
            continue
        if clear:
            repo.remove_generated_arc_frames(vol)
        for name in sorted(os.listdir(source_dir)):
            match = ARC_FILE_RE.match(name)
            if not match:
                continue
            path = os.path.join(source_dir, name)
            text = _read_file(path)
            if not text:
                continue
            frame = arc_frame_from_markdown(
                volume=vol,
                arc_index=int(match.group(1)),
                start_chapter=int(match.group(2)),
                end_chapter=int(match.group(3)),
                text=text,
                source_path=path,
            )
            repo.write_arc_frame(frame)
            repo.write_critic_report(validate_arc_frame(frame), category="trajectory")
            total += 1
    if not quiet:
        suffix = f"卷{volume}" if volume is not None else "全部卷"
        print(f"  -> 已同步{suffix}结构化情节帧：{total} 个")
    return {"arc_frames": total}


def _arc_for_chapter(arcs, chapter: int):
    for arc in arcs:
        if arc.start_chapter <= chapter <= arc.end_chapter:
            return arc
    return None


def sync_chapter_frames(ws, volume: Optional[int] = None, clear: bool = True, quiet: bool = False) -> Dict[str, int]:
    repo = NarrativeRepository(ws)
    source_base = os.path.join(ws.file_system, "chapter_outlines")
    volumes = [volume] if volume is not None else _available_volumes(source_base)
    total = 0
    for vol in volumes:
        source_dir = os.path.join(source_base, f"vol_{vol:02d}")
        if not os.path.isdir(source_dir):
            continue
        if clear:
            repo.remove_generated_chapter_frames(vol)
        arcs = repo.list_arc_frames(vol)
        for name in sorted(os.listdir(source_dir)):
            match = CHAPTER_OUTLINE_RE.match(name)
            if not match:
                continue
            chapter = int(match.group(1))
            path = os.path.join(source_dir, name)
            text = _read_file(path)
            if not text:
                continue
            arc = _arc_for_chapter(arcs, chapter)
            frame = chapter_frame_from_outline(
                volume=vol,
                chapter=chapter,
                outline_text=text,
                source_outline_path=path,
                story_arc_index=arc.arc_index if arc else None,
            )
            repo.write_chapter_frame(frame)
            repo.write_critic_report(validate_chapter_frame(frame, arc_frame=arc), category="trajectory")
            total += 1
        sequence_report = validate_chapter_sequence(repo.list_chapter_frames(vol), vol)
        repo.write_critic_report(sequence_report, category="trajectory")
    if not quiet:
        suffix = f"卷{volume}" if volume is not None else "全部卷"
        print(f"  -> 已同步{suffix}结构化章节帧：{total} 个")
    return {"chapter_frames": total}


def sync_ledger(ws, volume: Optional[int] = None, quiet: bool = False) -> Dict[str, int]:
    repo = NarrativeRepository(ws)
    frames = repo.list_chapter_frames(volume)
    existing_paths: Dict[int, str] = {}
    if volume is not None:
        existing_paths = repo.existing_chapter_paths(volume)

    entries = []
    for frame in frames:
        chapter_file = ""
        if volume is not None:
            chapter_file = existing_paths.get(frame.chapter, "")
        else:
            chapter_file = repo.existing_chapter_paths(frame.volume).get(frame.chapter, "")
        entries.append(
            {
                "volume": frame.volume,
                "chapter": frame.chapter,
                "title": frame.title,
                "story_arc_index": frame.story_arc_index,
                "chapter_file": chapter_file,
                "start_state": frame.start_state,
                "end_state": frame.end_state,
                "hook": frame.hook,
                "foreshadowing": frame.foreshadowing,
                "mechanics_events": frame.mechanics_events,
            }
        )

    current_volume = 0
    current_chapter = 0
    written_entries = [item for item in entries if item.get("chapter_file")]
    if written_entries:
        last = sorted(written_entries, key=lambda item: (item["volume"], item["chapter"]))[-1]
        current_volume = int(last["volume"])
        current_chapter = int(last["chapter"])
    elif entries:
        last = sorted(entries, key=lambda item: (item["volume"], item["chapter"]))[-1]
        current_volume = int(last["volume"])
        current_chapter = int(last["chapter"])

    ledger = ContinuityLedger(
        current_volume=current_volume,
        current_chapter=current_chapter,
        chapters=entries,
        open_hooks=[item["hook"] for item in entries if item.get("hook")][-50:],
        foreshadowing_open=[
            clue
            for item in entries
            for clue in (item.get("foreshadowing") or [])
        ][-100:],
        metadata={
            "source": "trajectory_builder.sync_ledger",
            "volume_filter": volume,
            "chapter_frame_count": len(frames),
        },
    )
    repo.write_ledger(ledger)
    if not quiet:
        print(f"  -> 已同步连续性账本：{len(entries)} 条章节状态")
    return {"ledger_entries": len(entries)}


def sync_trajectory_frames(ws, volume: Optional[int] = None, quiet: bool = False) -> Dict[str, int]:
    result = {}
    result.update(sync_story_design_frames(ws, quiet=quiet))
    result.update(sync_arc_frames(ws, volume=volume, clear=True, quiet=quiet))
    result.update(sync_chapter_frames(ws, volume=volume, clear=True, quiet=quiet))
    result.update(sync_ledger(ws, volume=volume, quiet=quiet))
    return result


def audit_trajectory_frames(ws, volume: Optional[int] = None, quiet: bool = False) -> Dict[str, int]:
    repo = NarrativeRepository(ws)
    ref_repo = ReferenceRepository(ws)
    mechanics_profile = ref_repo.read_mechanics_profile()
    mechanics_enabled = bool(mechanics_profile and mechanics_profile.enabled)
    reports = []
    spine = repo.read_novel_spine()
    if spine:
        reports.append(validate_novel_spine(spine))
    for roadmap in repo.list_volume_roadmaps(volume):
        reports.append(validate_volume_roadmap(roadmap))

    for stage in repo.list_stage_frames():
        if volume is not None and stage.volume != volume:
            continue
        reports.append(validate_stage_frame(stage))

    arcs = repo.list_arc_frames(volume)
    for arc in arcs:
        reports.append(validate_arc_frame(arc))

    chapters = repo.list_chapter_frames(volume)
    for frame in chapters:
        arc = _arc_for_chapter([item for item in arcs if item.volume == frame.volume], frame.chapter)
        reports.append(validate_chapter_frame(frame, arc_frame=arc))

    volumes = sorted({frame.volume for frame in chapters})
    for vol in volumes:
        vol_frames = [item for item in chapters if item.volume == vol]
        reports.append(validate_chapter_sequence(vol_frames, vol))
        reports.append(validate_mechanics_presence(vol_frames, vol, mechanics_enabled))

    failed = 0
    issues = 0
    for report in reports:
        repo.write_critic_report(report, category="trajectory")
        if not report.passed:
            failed += 1
            issues += len(report.issues)

    if not quiet:
        print(f"  -> 审计完成：{len(reports)} 份报告，未通过 {failed} 份，问题 {issues} 个")
    return {"reports": len(reports), "failed_reports": failed, "issues": issues}
