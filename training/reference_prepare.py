"""Prepare reference-novel assets for trajectory distillation."""

import hashlib
import json
import os
import re
from typing import Any, Dict, List, Optional

from core.config import ConfigLoader
from core.llm_provider import LLMProvider
from core.models import (
    MechanicsProfile,
    ReferenceArcCard,
    ReferenceChapterCard,
    ReferenceManifest,
)
from core.prompt_loader import PromptLoader
from core.reference_repository import ReferenceRepository
from core.text_utils import parse_json_response
from training.reference_finder import list_reference_story_arcs, list_reference_volumes


CHAPTER_FILE_RE = re.compile(r"^(\d+)_.*\.md$")


def _get_llm():
    config = ConfigLoader.get_data_builder_config()
    if not config.get("api_key"):
        config = ConfigLoader.get_adaptive_builder_lite_config() or config
    if not config.get("api_key"):
        config["api_key"] = os.getenv("OPENAI_API_KEY")
    if not config.get("api_key"):
        print("  警告：未检测到 API Key，仅生成 manifest / bundle 骨架。")
        return None
    return LLMProvider(**config)


def _read_file(path: str) -> str:
    if not path or not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def _hash_file(path: str) -> str:
    if not os.path.exists(path):
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _json_loads(raw: str, label: str) -> Dict[str, Any]:
    try:
        return parse_json_response(raw)
    except Exception as e:
        raise ValueError(f"{label} JSON 解析失败：{e}\n原始输出前500字：{raw[:500]}") from e


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


def _chapter_title_from_file(path: str, fallback: str) -> str:
    text = _read_file(path)
    if text:
        return text.splitlines()[0].strip()[:80]
    return fallback


def build_reference_manifest(ws) -> ReferenceManifest:
    repo = ReferenceRepository(ws)
    chapters_root = ws.reference_chapters
    volumes_meta_path = os.path.join(chapters_root, "_volumes.json")
    volumes = []
    chapters = []

    if os.path.exists(volumes_meta_path):
        with open(volumes_meta_path, "r", encoding="utf-8") as f:
            volume_meta = json.load(f)
        for vol_idx, item in enumerate(volume_meta, 1):
            vol_dir = os.path.join(chapters_root, item["dir"])
            chapter_files = []
            if os.path.isdir(vol_dir):
                chapter_files = [
                    name for name in sorted(os.listdir(vol_dir))
                    if name.endswith(".md") and not name.startswith("_")
                ]
            start_global = None
            end_global = None
            for local_idx, fname in enumerate(chapter_files, 1):
                match = CHAPTER_FILE_RE.match(fname)
                global_index = int(match.group(1)) if match else len(chapters) + 1
                start_global = global_index if start_global is None else min(start_global, global_index)
                end_global = global_index if end_global is None else max(end_global, global_index)
                path = os.path.join(vol_dir, fname)
                chapters.append({
                    "chapter_id": f"ref_ch_{global_index:04d}",
                    "global_index": global_index,
                    "volume": vol_idx,
                    "local_index": local_idx,
                    "title": _chapter_title_from_file(path, fname),
                    "file": path,
                    "char_count": len(_read_file(path)),
                })
            volumes.append({
                "volume_id": f"ref_vol_{vol_idx:03d}",
                "volume": vol_idx,
                "title": item.get("title", f"卷{vol_idx}"),
                "dir": item.get("dir", ""),
                "start_chapter": start_global or 0,
                "end_chapter": end_global or 0,
                "chapter_count": len(chapter_files),
            })

    story_arcs = []
    for vol in list_reference_volumes(ws.reference_outlines):
        for arc in list_reference_story_arcs(ws.reference_outlines, vol["vol_idx"]):
            story_arcs.append({
                "arc_id": f"ref_arc_v{vol['vol_idx']:02d}_{arc['idx']:03d}",
                "volume": vol["vol_idx"],
                "arc_index": arc["idx"],
                "start_chapter": arc["start_ch"],
                "end_chapter": arc["end_ch"],
                "file": arc.get("path", ""),
                "source_type": arc.get("source_type", "story_arc"),
            })

    manifest = ReferenceManifest(
        source_file=ws.reference_sample,
        source_hash=_hash_file(ws.reference_sample),
        volumes=volumes,
        chapters=sorted(chapters, key=lambda item: item["global_index"]),
        story_arcs=sorted(story_arcs, key=lambda item: (item["volume"], item["arc_index"])),
        metadata={"builder": "reference_prepare.build_reference_manifest"},
    )
    repo.write_manifest(manifest)
    print(f"  -> reference manifest 已保存：{repo.manifest_path()}")
    return manifest


def _sample_reference_text(manifest: ReferenceManifest, max_chapters: int = 8, max_chars: int = 24000) -> str:
    parts = []
    for ch in manifest.chapters[:max_chapters]:
        text = _read_file(ch.get("file", ""))
        if text:
            parts.append(f"=== {ch.get('chapter_id')} {ch.get('title')} ===\n{text[:3000]}")
        if sum(len(part) for part in parts) >= max_chars:
            break
    return "\n\n".join(parts)[:max_chars]


def detect_reference_mechanics(ws, llm, manifest: ReferenceManifest, force: bool = False) -> MechanicsProfile:
    repo = ReferenceRepository(ws)
    existing = repo.read_mechanics_profile()
    if existing and not force:
        print("  -> mechanics profile 已存在，跳过检测。")
        return existing

    if not llm:
        profile = MechanicsProfile(enabled=False, type="unknown", confidence=0.0, signals=["未配置 LLM，未检测。"])
        repo.write_mechanics_profile(profile)
        return profile

    raw = llm.generate(
        PromptLoader.load("reference_mechanics_detect", sample_text=_sample_reference_text(manifest)),
        is_json=True,
    )
    try:
        data = _json_loads(raw, "reference_mechanics_detect")
    except ValueError as e:
        repo.write_invalid_json("mechanics_detect", "mechanics_profile", raw, str(e))
        print(f"  警告：mechanics 检测 JSON 解析失败，已保存原始输出并降级为 disabled：{e}")
        profile = MechanicsProfile(enabled=False, type="unknown", confidence=0.0, signals=["mechanics JSON parse failed"])
        repo.write_mechanics_profile(profile)
        return profile
    profile = MechanicsProfile(
        enabled=bool(data.get("enabled", False)),
        type=str(data.get("type", "none")),
        confidence=float(data.get("confidence", 0.0) or 0.0),
        signals=_as_text_list(data.get("signals")),
        panel_names=_as_text_list(data.get("panel_names")),
        tracked_domains=_as_text_list(data.get("tracked_domains")),
        raw=data,
    )
    repo.write_mechanics_profile(profile)
    print(f"  -> mechanics profile 已保存：{repo.mechanics_profile_path()}")
    return profile


def _normalize_chapter_card(data: Dict[str, Any], ch: Dict[str, Any]) -> ReferenceChapterCard:
    events = []
    for item in _as_list(data.get("mechanics_events")):
        if isinstance(item, dict):
            events.append(item)
    return ReferenceChapterCard(
        chapter_id=str(data.get("chapter_id") or ch["chapter_id"]),
        volume=int(data.get("volume") or ch["volume"]),
        chapter=int(data.get("chapter") or ch["local_index"]),
        global_index=int(data.get("global_index") or ch["global_index"]),
        title=str(data.get("title") or ch["title"]),
        opening_state=str(data.get("opening_state", "")),
        core_event=str(data.get("core_event", "")),
        emotion_curve=_as_text_list(data.get("emotion_curve")),
        strongest_emotional_beat=str(data.get("strongest_emotional_beat", "")),
        payoff=str(data.get("payoff", "")),
        hook=str(data.get("hook", "")),
        hook_type=str(data.get("hook_type", "")),
        state_delta=_as_dict(data.get("state_delta")),
        foreshadowing=_as_text_list(data.get("foreshadowing")),
        reader_question_at_end=str(data.get("reader_question_at_end", "")),
        mechanics_events=events,
        raw={"source": "reference_chapter_card_extract"},
    )


def extract_reference_chapter_cards(ws, llm, manifest: ReferenceManifest, profile: MechanicsProfile,
                                    force: bool = False, max_chapters: Optional[int] = None) -> int:
    repo = ReferenceRepository(ws)
    if not llm:
        return 0
    total = 0
    chapters = manifest.chapters[:max_chapters] if max_chapters else manifest.chapters
    for ch in chapters:
        volume = int(ch["volume"])
        local = int(ch["local_index"])
        if repo.read_chapter_card(volume, local) and not force:
            continue
        text = _read_file(ch.get("file", ""))
        if not text:
            continue
        print(f"  -> 抽取章节卡：卷{volume} 第{local}章")
        raw = llm.generate(
            PromptLoader.load(
                "reference_chapter_card_extract",
                chapter_id=ch["chapter_id"],
                volume=volume,
                chapter=local,
                global_index=ch["global_index"],
                title=ch["title"].replace('"', "'"),
                mechanics_profile=json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
                chapter_text=text[:12000],
            ),
            is_json=True,
        )
        try:
            data = _json_loads(raw, f"chapter_card {ch['chapter_id']}")
        except ValueError as e:
            debug_path = repo.write_invalid_json("chapter_card", ch["chapter_id"], raw, str(e))
            print(f"  警告：章节卡 JSON 解析失败，已跳过 {ch['chapter_id']}。原始输出：{debug_path}")
            continue
        card = _normalize_chapter_card(data, ch)
        repo.write_chapter_card(card)
        if card.mechanics_events:
            repo.write_mechanics_events(volume, local, {
                "chapter_id": card.chapter_id,
                "events": card.mechanics_events,
            })
        total += 1
    print(f"  -> 章节卡已生成/更新：{total} 个")
    return total


def _compact_card_dict(card: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in card.items()
        if key not in {"schema_version", "raw"} and value not in ("", [], {}, None)
    }


def _cards_for_arc(repo: ReferenceRepository, volume: int, start_ch: int, end_ch: int) -> List[Dict[str, Any]]:
    cards = []
    for ch in range(start_ch, end_ch + 1):
        card = repo.read_chapter_card(volume, ch)
        if card:
            cards.append(_compact_card_dict(card.to_dict()))
    return cards


def extract_reference_arc_cards(ws, llm, manifest: ReferenceManifest, force: bool = False,
                                max_arcs: Optional[int] = None) -> int:
    repo = ReferenceRepository(ws)
    if not llm:
        return 0
    total = 0
    arcs = manifest.story_arcs[:max_arcs] if max_arcs else manifest.story_arcs
    for arc in arcs:
        volume = int(arc["volume"])
        arc_idx = int(arc["arc_index"])
        if repo.read_arc_card(volume, arc_idx) and not force:
            continue
        arc_text = _read_file(arc.get("file", ""))
        if not arc_text:
            continue
        print(f"  -> 抽取情节卡：卷{volume} 情节{arc_idx}")
        raw = llm.generate(
            PromptLoader.load(
                "reference_arc_card_extract",
                arc_id=arc["arc_id"],
                volume=volume,
                arc_index=arc_idx,
                start_chapter=arc["start_chapter"],
                end_chapter=arc["end_chapter"],
                arc_text=arc_text,
                chapter_cards=json.dumps(
                    _cards_for_arc(repo, volume, int(arc["start_chapter"]), int(arc["end_chapter"])),
                    ensure_ascii=False,
                    indent=2,
                ),
            ),
            is_json=True,
        )
        try:
            data = _json_loads(raw, f"arc_card {arc['arc_id']}")
        except ValueError as e:
            debug_path = repo.write_invalid_json("arc_card", arc["arc_id"], raw, str(e))
            print(f"  警告：情节卡 JSON 解析失败，已跳过 {arc['arc_id']}。原始输出：{debug_path}")
            continue
        card = ReferenceArcCard(
            arc_id=str(data.get("arc_id") or arc["arc_id"]),
            volume=volume,
            arc_index=arc_idx,
            start_chapter=int(data.get("start_chapter") or arc["start_chapter"]),
            end_chapter=int(data.get("end_chapter") or arc["end_chapter"]),
            title=str(data.get("title", "")),
            arc_function=str(data.get("arc_function", "")),
            boundary_reason=str(data.get("boundary_reason", "")),
            emotion_curve=_as_text_list(data.get("emotion_curve")),
            pressure_points=_as_text_list(data.get("pressure_points")),
            payoff_points=_as_text_list(data.get("payoff_points")),
            hook_points=_as_text_list(data.get("hook_points")),
            progression_pattern=str(data.get("progression_pattern", "")),
            foreshadowing_pattern=str(data.get("foreshadowing_pattern", "")),
            reader_retention_mechanism=str(data.get("reader_retention_mechanism", "")),
            copy_risk_elements=_as_text_list(data.get("copy_risk_elements")),
            raw={"source": "reference_arc_card_extract"},
        )
        repo.write_arc_card(card)
        total += 1
    print(f"  -> 情节卡已生成/更新：{total} 个")
    return total


def _chapter_excerpt(path: str) -> Dict[str, str]:
    text = _read_file(path)
    if not text:
        return {"opening_excerpt": "", "ending_excerpt": ""}
    return {
        "opening_excerpt": text[:1200],
        "ending_excerpt": text[-1600:],
    }


def build_distill_inputs(ws, manifest: ReferenceManifest, force: bool = False) -> int:
    repo = ReferenceRepository(ws)
    total = 0
    chapters_by_key = {(int(ch["volume"]), int(ch["local_index"])): ch for ch in manifest.chapters}
    for arc in manifest.story_arcs:
        path = repo.distill_input_path(arc["arc_id"])
        if os.path.exists(path) and not force:
            continue
        volume = int(arc["volume"])
        start = int(arc["start_chapter"])
        end = int(arc["end_chapter"])
        chapter_cards = _cards_for_arc(repo, volume, start, end)
        samples = []
        for ch_num in range(start, end + 1):
            ch = chapters_by_key.get((volume, ch_num))
            if not ch:
                continue
            excerpts = _chapter_excerpt(ch.get("file", ""))
            samples.append({
                "chapter_id": ch["chapter_id"],
                "title": ch["title"],
                **excerpts,
            })
        arc_card = repo.read_arc_card(volume, int(arc["arc_index"]))
        arc_card_payload = _compact_card_dict(arc_card.to_dict()) if arc_card else {}
        payload = {
            "arc": arc,
            "arc_card": arc_card_payload,
            "chapter_cards": chapter_cards,
            "chapter_text_samples": samples,
        }
        repo.write_distill_input(arc["arc_id"], payload)
        total += 1
    print(f"  -> distill input bundles 已生成/更新：{total} 个")
    return total


def prepare_reference_assets(ws, *, force: bool = False, lite: bool = False,
                             max_chapters: Optional[int] = None,
                             max_arcs: Optional[int] = None):
    """Prepare reference assets for reference-distill."""
    print(">>> 准备参考小说蒸馏输入 <<<")
    manifest = build_reference_manifest(ws)
    llm = _get_llm()
    profile = detect_reference_mechanics(ws, llm, manifest, force=force)
    if not lite:
        extract_reference_chapter_cards(ws, llm, manifest, profile, force=force, max_chapters=max_chapters)
        extract_reference_arc_cards(ws, llm, manifest, force=force, max_arcs=max_arcs)
    else:
        print("  -> lite 模式：跳过章节卡和情节卡 LLM 抽取。")
    build_distill_inputs(ws, manifest, force=force)
    print(">>> 参考小说蒸馏输入准备完成 <<<")
