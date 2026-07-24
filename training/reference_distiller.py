"""Distill reference-novel pattern banks for trajectory planning."""

import json
import os
from typing import Any, Dict, List, Optional

from core.config import ConfigLoader
from core.llm_provider import LLMProvider
from core.models import MechanicsPatternBank, ReferencePatternBank
from core.prompt_loader import PromptLoader
from core.reference_repository import ReferenceRepository
from core.text_utils import parse_json_response
from training.reference_finder import load_reference_novel_outline


def _get_llm():
    config = ConfigLoader.get_data_builder_config()
    if not config.get("api_key"):
        config = ConfigLoader.get_adaptive_builder_lite_config() or config
    if not config.get("api_key"):
        config["api_key"] = os.getenv("OPENAI_API_KEY")
    if not config.get("api_key"):
        print("错误：未检测到 API Key。")
        return None
    return LLMProvider(**config)


def _parse(raw: str, label: str) -> Dict[str, Any]:
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


def _normalize_reference_bank(data: Dict[str, Any]) -> ReferencePatternBank:
    return ReferencePatternBank(
        summary=str(data.get("summary", "")),
        story_contract_signals=_as_text_list(data.get("story_contract_signals")),
        emotion_patterns=[item for item in _as_list(data.get("emotion_patterns")) if isinstance(item, dict)],
        hook_patterns=[item for item in _as_list(data.get("hook_patterns")) if isinstance(item, dict)],
        progression_patterns=[item for item in _as_list(data.get("progression_patterns")) if isinstance(item, dict)],
        foreshadowing_patterns=[item for item in _as_list(data.get("foreshadowing_patterns")) if isinstance(item, dict)],
        anti_patterns=_as_text_list(data.get("anti_patterns")),
        raw=data,
    )


def _normalize_mechanics_bank(data: Dict[str, Any]) -> MechanicsPatternBank:
    return MechanicsPatternBank(
        enabled=bool(data.get("enabled", False)),
        panel_frequency=str(data.get("panel_frequency", "")),
        reward_loop=_as_text_list(data.get("reward_loop")),
        common_event_types=_as_text_list(data.get("common_event_types")),
        panel_display_rules=_as_text_list(data.get("panel_display_rules")),
        anti_patterns=_as_text_list(data.get("anti_patterns")),
        raw=data,
    )


def _select_inputs(inputs: List[Dict[str, Any]], volumes: Optional[List[int]], max_arcs: Optional[int]) -> List[Dict[str, Any]]:
    selected = []
    for item in inputs:
        arc = item.get("arc") or {}
        if volumes and int(arc.get("volume", 0)) not in volumes:
            continue
        selected.append(item)
        if max_arcs and len(selected) >= max_arcs:
            break
    return selected


def _strip_debug_fields(value):
    if isinstance(value, dict):
        return {
            key: _strip_debug_fields(item)
            for key, item in value.items()
            if key not in {"raw", "schema_version"} and item not in ("", [], {}, None)
        }
    if isinstance(value, list):
        return [_strip_debug_fields(item) for item in value]
    return value


def _compact_inputs(inputs: List[Dict[str, Any]], max_chars: int = 50000) -> str:
    compact = []
    for item in inputs:
        compact.append({
            "arc": item.get("arc"),
            "arc_card": item.get("arc_card"),
            "chapter_cards": item.get("chapter_cards"),
            "chapter_text_samples": item.get("chapter_text_samples", [])[:3],
        })
    text = json.dumps(_strip_debug_fields(compact), ensure_ascii=False, indent=2)
    return text[:max_chars]


def _mechanics_samples(inputs: List[Dict[str, Any]], max_chars: int = 40000) -> str:
    samples = []
    for item in inputs:
        for card in item.get("chapter_cards") or []:
            events = card.get("mechanics_events") or []
            if events:
                samples.append({
                    "chapter_id": card.get("chapter_id"),
                    "emotion_curve": card.get("emotion_curve"),
                    "payoff": card.get("payoff"),
                    "hook": card.get("hook"),
                    "mechanics_events": events,
                })
    return json.dumps(samples, ensure_ascii=False, indent=2)[:max_chars]


def distill_reference_patterns(ws, *, force: bool = False, volumes: Optional[List[int]] = None,
                               max_arcs: Optional[int] = None):
    repo = ReferenceRepository(ws)
    if repo.read_reference_pattern_bank() and not force:
        print("ReferencePatternBank 已存在。使用 --force 重新蒸馏。")
        return

    inputs = repo.list_distill_inputs()
    if not inputs:
        print("错误：未找到 reference/distill_inputs/arcs。请先运行 novel reference-prepare。")
        return
    selected = _select_inputs(inputs, volumes, max_arcs)
    if not selected:
        print("错误：筛选后没有可蒸馏的参考情节。")
        return

    llm = _get_llm()
    if not llm:
        return

    print(f">>> 蒸馏 ReferencePatternBank（{len(selected)} 个情节样本）<<<")
    raw = llm.generate(
        PromptLoader.load(
            "reference_pattern_distill",
            reference_outline=load_reference_novel_outline(ws.reference_outlines) or "（无参考全书大纲）",
            distill_inputs=_compact_inputs(selected),
        ),
        is_json=True,
    )
    bank = _normalize_reference_bank(_parse(raw, "reference_pattern_distill"))
    repo.write_reference_pattern_bank(bank)
    print(f"  -> ReferencePatternBank 已保存：{repo.reference_pattern_bank_path()}")

    profile = repo.read_mechanics_profile()
    if profile and profile.enabled:
        print(">>> 蒸馏 MechanicsPatternBank <<<")
        raw_mechanics = llm.generate(
            PromptLoader.load(
                "reference_mechanics_pattern_distill",
                mechanics_profile=json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
                mechanics_samples=_mechanics_samples(selected),
            ),
            is_json=True,
        )
        mechanics_bank = _normalize_mechanics_bank(_parse(raw_mechanics, "reference_mechanics_pattern_distill"))
        repo.write_mechanics_pattern_bank(mechanics_bank)
        print(f"  -> MechanicsPatternBank 已保存：{repo.mechanics_pattern_bank_path()}")
    else:
        repo.write_mechanics_pattern_bank(MechanicsPatternBank(enabled=False, raw={"reason": "reference mechanics disabled"}))
        print("  -> 未启用 mechanics，已写入 disabled MechanicsPatternBank。")
