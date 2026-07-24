"""Structured narrative models for long-form novel planning.

The existing project stores most planning assets as Markdown. These
dataclasses provide a machine-readable layer that can be generated from the
same assets, validated, repaired, and later used as training data.
"""

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional, Type, TypeVar


T = TypeVar("T")


def _filtered_kwargs(cls: Type[T], data: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {item.name for item in fields(cls)}
    return {key: value for key, value in (data or {}).items() if key in allowed}


def model_to_dict(model: Any) -> Dict[str, Any]:
    return asdict(model)


def model_from_dict(cls: Type[T], data: Optional[Dict[str, Any]]) -> T:
    return cls(**_filtered_kwargs(cls, data or {}))


@dataclass
class StoryContract:
    schema_version: int = 1
    genre: str = ""
    target_reader: str = ""
    core_appeal: str = ""
    reader_promises: List[str] = field(default_factory=list)
    emotional_palette: List[str] = field(default_factory=list)
    taboo_breaks: List[str] = field(default_factory=list)
    comparison_notes: List[str] = field(default_factory=list)
    success_criteria: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "StoryContract":
        return model_from_dict(cls, data)

    def to_dict(self) -> Dict[str, Any]:
        return model_to_dict(self)


@dataclass
class StoryBible:
    schema_version: int = 1
    title: str = ""
    synopsis: str = ""
    creative_direction: str = ""
    story_contract: Dict[str, Any] = field(default_factory=dict)
    core_gameplay: str = ""
    reader_contract: str = ""
    long_mainline: str = ""
    stage_count: int = 0
    source_paths: Dict[str, str] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    raw_sections: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "StoryBible":
        return model_from_dict(cls, data)

    def to_dict(self) -> Dict[str, Any]:
        return model_to_dict(self)


@dataclass
class NovelSpine:
    schema_version: int = 1
    premise: str = ""
    central_question: str = ""
    final_destination: str = ""
    protagonist_arc: str = ""
    core_conflict: str = ""
    antagonist_pressure: str = ""
    progression_axis: List[str] = field(default_factory=list)
    long_debts: List[str] = field(default_factory=list)
    payoff_schedule: List[Dict[str, Any]] = field(default_factory=list)
    volume_functions: List[Dict[str, Any]] = field(default_factory=list)
    state_anchors: List[Dict[str, Any]] = field(default_factory=list)
    must_not_break: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "NovelSpine":
        return model_from_dict(cls, data)

    def to_dict(self) -> Dict[str, Any]:
        return model_to_dict(self)


@dataclass
class VolumeRoadmap:
    schema_version: int = 1
    volume: int = 1
    title: str = ""
    expected_chapters: int = 0
    volume_function: str = ""
    volume_goal: str = ""
    opening_state: str = ""
    end_state: str = ""
    main_conflict: str = ""
    reader_expectation: str = ""
    gameplay_value: str = ""
    rules: str = ""
    shortlines: List[str] = field(default_factory=list)
    resources: List[str] = field(default_factory=list)
    pressures: List[str] = field(default_factory=list)
    allies: List[str] = field(default_factory=list)
    major_payoffs: List[str] = field(default_factory=list)
    new_debts: List[str] = field(default_factory=list)
    hidden_threads: List[str] = field(default_factory=list)
    mechanics_plan: List[str] = field(default_factory=list)
    state_anchors: List[Dict[str, Any]] = field(default_factory=list)
    cannot_reveal: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "VolumeRoadmap":
        return model_from_dict(cls, data)

    def to_dict(self) -> Dict[str, Any]:
        return model_to_dict(self)


@dataclass
class StageFrame:
    schema_version: int = 1
    volume: int = 1
    title: str = ""
    expected_chapters: int = 0
    stage_function: str = ""
    gameplay_value: str = ""
    mainline_progress: str = ""
    rules: str = ""
    shortlines: List[str] = field(default_factory=list)
    resources: List[str] = field(default_factory=list)
    pressures: List[str] = field(default_factory=list)
    allies: List[str] = field(default_factory=list)
    character_nodes: str = ""
    end_state: str = ""
    hooks: str = ""
    cannot_reveal: str = ""
    raw_text: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "StageFrame":
        return model_from_dict(cls, data)

    def to_dict(self) -> Dict[str, Any]:
        return model_to_dict(self)


@dataclass
class ArcFrame:
    schema_version: int = 1
    volume: int = 1
    arc_index: int = 1
    start_chapter: int = 1
    end_chapter: int = 1
    title: str = ""
    core_event: str = ""
    pattern_landing: str = ""
    conflict: str = ""
    emotion_curve: List[str] = field(default_factory=list)
    protagonist_state_change: str = ""
    foreshadowing: List[str] = field(default_factory=list)
    chapter_pacing: List[str] = field(default_factory=list)
    world_elements: List[str] = field(default_factory=list)
    self_check: str = ""
    raw_text: str = ""
    source_path: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ArcFrame":
        return model_from_dict(cls, data)

    def to_dict(self) -> Dict[str, Any]:
        return model_to_dict(self)


@dataclass
class ChapterFrame:
    schema_version: int = 1
    volume: int = 1
    chapter: int = 1
    title: str = ""
    story_arc_index: Optional[int] = None
    opening_state: str = ""
    goal: str = ""
    events: List[Dict[str, str]] = field(default_factory=list)
    emotion_curve: List[str] = field(default_factory=list)
    emotional_peak: str = ""
    hook: str = ""
    hook_type: str = ""
    foreshadowing: List[str] = field(default_factory=list)
    characters: List[str] = field(default_factory=list)
    world_elements: List[str] = field(default_factory=list)
    mechanics_events: List[str] = field(default_factory=list)
    start_state: Dict[str, Any] = field(default_factory=dict)
    end_state: Dict[str, Any] = field(default_factory=dict)
    must_not_happen: List[str] = field(default_factory=list)
    source_outline_path: str = ""
    raw_outline: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ChapterFrame":
        return model_from_dict(cls, data)

    def to_dict(self) -> Dict[str, Any]:
        return model_to_dict(self)


@dataclass
class SceneFrame:
    schema_version: int = 1
    volume: int = 1
    chapter: int = 1
    scene_index: int = 1
    location: str = ""
    viewpoint: str = ""
    purpose: str = ""
    conflict: str = ""
    emotional_target: str = ""
    entry_state: Dict[str, Any] = field(default_factory=dict)
    exit_state: Dict[str, Any] = field(default_factory=dict)
    key_actions: List[str] = field(default_factory=list)
    key_dialogue: List[str] = field(default_factory=list)
    hook: str = ""
    must_include: List[str] = field(default_factory=list)
    must_avoid: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "SceneFrame":
        return model_from_dict(cls, data)

    def to_dict(self) -> Dict[str, Any]:
        return model_to_dict(self)


@dataclass
class ReferenceManifest:
    schema_version: int = 1
    source_file: str = ""
    source_hash: str = ""
    volumes: List[Dict[str, Any]] = field(default_factory=list)
    chapters: List[Dict[str, Any]] = field(default_factory=list)
    story_arcs: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ReferenceManifest":
        return model_from_dict(cls, data)

    def to_dict(self) -> Dict[str, Any]:
        return model_to_dict(self)


@dataclass
class MechanicsEvent:
    schema_version: int = 1
    type: str = ""
    timing: str = ""
    trigger: str = ""
    delta: Dict[str, Any] = field(default_factory=dict)
    narrative_function: str = ""
    emotion_effect: str = ""
    display_mode: str = "none"
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "MechanicsEvent":
        return model_from_dict(cls, data)

    def to_dict(self) -> Dict[str, Any]:
        return model_to_dict(self)


@dataclass
class ReferenceChapterCard:
    schema_version: int = 1
    chapter_id: str = ""
    volume: int = 1
    chapter: int = 1
    global_index: int = 1
    title: str = ""
    opening_state: str = ""
    core_event: str = ""
    emotion_curve: List[str] = field(default_factory=list)
    strongest_emotional_beat: str = ""
    payoff: str = ""
    hook: str = ""
    hook_type: str = ""
    state_delta: Dict[str, Any] = field(default_factory=dict)
    foreshadowing: List[str] = field(default_factory=list)
    reader_question_at_end: str = ""
    mechanics_events: List[Dict[str, Any]] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ReferenceChapterCard":
        return model_from_dict(cls, data)

    def to_dict(self) -> Dict[str, Any]:
        return model_to_dict(self)


@dataclass
class ReferenceArcCard:
    schema_version: int = 1
    arc_id: str = ""
    volume: int = 1
    arc_index: int = 1
    start_chapter: int = 1
    end_chapter: int = 1
    title: str = ""
    arc_function: str = ""
    boundary_reason: str = ""
    emotion_curve: List[str] = field(default_factory=list)
    pressure_points: List[str] = field(default_factory=list)
    payoff_points: List[str] = field(default_factory=list)
    hook_points: List[str] = field(default_factory=list)
    progression_pattern: str = ""
    foreshadowing_pattern: str = ""
    reader_retention_mechanism: str = ""
    copy_risk_elements: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ReferenceArcCard":
        return model_from_dict(cls, data)

    def to_dict(self) -> Dict[str, Any]:
        return model_to_dict(self)


@dataclass
class MechanicsProfile:
    schema_version: int = 1
    enabled: bool = False
    type: str = "none"
    confidence: float = 0.0
    signals: List[str] = field(default_factory=list)
    panel_names: List[str] = field(default_factory=list)
    tracked_domains: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "MechanicsProfile":
        return model_from_dict(cls, data)

    def to_dict(self) -> Dict[str, Any]:
        return model_to_dict(self)


@dataclass
class ReferencePatternBank:
    schema_version: int = 1
    summary: str = ""
    story_contract_signals: List[str] = field(default_factory=list)
    emotion_patterns: List[Dict[str, Any]] = field(default_factory=list)
    hook_patterns: List[Dict[str, Any]] = field(default_factory=list)
    progression_patterns: List[Dict[str, Any]] = field(default_factory=list)
    foreshadowing_patterns: List[Dict[str, Any]] = field(default_factory=list)
    anti_patterns: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ReferencePatternBank":
        return model_from_dict(cls, data)

    def to_dict(self) -> Dict[str, Any]:
        return model_to_dict(self)


@dataclass
class MechanicsPatternBank:
    schema_version: int = 1
    enabled: bool = False
    panel_frequency: str = ""
    reward_loop: List[str] = field(default_factory=list)
    common_event_types: List[str] = field(default_factory=list)
    panel_display_rules: List[str] = field(default_factory=list)
    anti_patterns: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "MechanicsPatternBank":
        return model_from_dict(cls, data)

    def to_dict(self) -> Dict[str, Any]:
        return model_to_dict(self)


@dataclass
class CriticIssue:
    type: str = ""
    severity: str = "medium"
    location: str = ""
    reason: str = ""
    repair_instruction: str = ""

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "CriticIssue":
        return model_from_dict(cls, data)

    def to_dict(self) -> Dict[str, Any]:
        return model_to_dict(self)


@dataclass
class CriticReport:
    schema_version: int = 1
    target_type: str = ""
    target_id: str = ""
    passed: bool = True
    score: int = 100
    issues: List[CriticIssue] = field(default_factory=list)
    summary: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "CriticReport":
        raw = data or {}
        report = model_from_dict(cls, raw)
        report.passed = bool(raw.get("passed", raw.get("pass", report.passed)))
        report.issues = [
            issue if isinstance(issue, CriticIssue) else CriticIssue.from_dict(issue)
            for issue in (raw.get("issues") or [])
        ]
        return report

    def to_dict(self) -> Dict[str, Any]:
        data = model_to_dict(self)
        data["pass"] = self.passed
        return data


@dataclass
class ContinuityLedger:
    schema_version: int = 1
    current_volume: int = 0
    current_chapter: int = 0
    chapters: List[Dict[str, Any]] = field(default_factory=list)
    open_hooks: List[str] = field(default_factory=list)
    foreshadowing_open: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ContinuityLedger":
        return model_from_dict(cls, data)

    def to_dict(self) -> Dict[str, Any]:
        return model_to_dict(self)
