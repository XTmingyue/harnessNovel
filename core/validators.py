"""Deterministic validation for structured narrative frames."""

from typing import Iterable, List, Optional

from core.models import (
    ArcFrame,
    ChapterFrame,
    CriticIssue,
    CriticReport,
    NovelSpine,
    StageFrame,
    VolumeRoadmap,
)


SEVERITY_COST = {
    "high": 25,
    "medium": 12,
    "low": 5,
}


def _issue(kind: str, severity: str, location: str, reason: str, repair: str) -> CriticIssue:
    return CriticIssue(
        type=kind,
        severity=severity,
        location=location,
        reason=reason,
        repair_instruction=repair,
    )


def _report(target_type: str, target_id: str, issues: List[CriticIssue]) -> CriticReport:
    score = max(0, 100 - sum(SEVERITY_COST.get(item.severity, 10) for item in issues))
    passed = score >= 70 and not any(item.severity == "high" for item in issues)
    summary = "pass" if passed else f"{len(issues)} issue(s), score {score}"
    return CriticReport(
        target_type=target_type,
        target_id=target_id,
        passed=passed,
        score=score,
        issues=issues,
        summary=summary,
    )


def validate_novel_spine(spine: NovelSpine) -> CriticReport:
    issues: List[CriticIssue] = []
    location = "novel_spine"
    if not spine.central_question:
        issues.append(
            _issue(
                "missing_central_question",
                "high",
                location,
                "novel spine has no central story question",
                "Add the core long-running question that keeps readers tracking the whole book.",
            )
        )
    if not spine.final_destination:
        issues.append(
            _issue(
                "missing_final_destination",
                "medium",
                location,
                "novel spine has no visible destination",
                "Add an early-stage destination or implied endgame, even if the truth stays hidden.",
            )
        )
    if not spine.protagonist_arc:
        issues.append(
            _issue(
                "missing_protagonist_arc",
                "medium",
                location,
                "novel spine does not define protagonist state evolution",
                "Describe how the protagonist's identity, power, relations, or worldview should change.",
            )
        )
    if not spine.volume_functions:
        issues.append(
            _issue(
                "missing_volume_functions",
                "medium",
                location,
                "novel spine has no volume-level function map",
                "Add one structural function per planned volume so volume roadmaps can stay aligned.",
            )
        )
    if not spine.long_debts:
        issues.append(
            _issue(
                "missing_long_debts",
                "low",
                location,
                "novel spine lacks long-running debts or promises",
                "Add delayed payoffs, mysteries, relationship debts, or resource promises.",
            )
        )
    return _report("novel_spine", location, issues)


def validate_volume_roadmap(roadmap: VolumeRoadmap) -> CriticReport:
    location = f"vol_{roadmap.volume:02d}/volume_roadmap"
    issues: List[CriticIssue] = []
    if roadmap.expected_chapters <= 0:
        issues.append(
            _issue(
                "missing_expected_chapters",
                "high",
                location,
                "volume roadmap does not declare expected chapter count",
                "Add expected_chapters before generating arcs and chapters.",
            )
        )
    if not roadmap.volume_function:
        issues.append(
            _issue(
                "missing_volume_function",
                "high",
                location,
                "volume roadmap has no structural function",
                "Define what this volume changes in the whole-book trajectory.",
            )
        )
    if not roadmap.volume_goal:
        issues.append(
            _issue(
                "missing_volume_goal",
                "medium",
                location,
                "volume roadmap has no visible short-term goal",
                "Add a concrete target the protagonist and reader can track through this volume.",
            )
        )
    if not roadmap.opening_state or not roadmap.end_state:
        issues.append(
            _issue(
                "missing_state_transition",
                "medium",
                location,
                "volume roadmap lacks opening/end state",
                "Add the protagonist and situation state before and after this volume.",
            )
        )
    if not roadmap.major_payoffs and not roadmap.new_debts:
        issues.append(
            _issue(
                "missing_debt_payoff_plan",
                "medium",
                location,
                "volume roadmap has no payoff/debt plan",
                "Specify what old expectation is paid off and what new expectation is created.",
            )
        )
    if not roadmap.state_anchors:
        issues.append(
            _issue(
                "missing_state_anchors",
                "low",
                location,
                "volume roadmap has no state anchors",
                "Add several state anchors that later arcs/chapters can refine.",
            )
        )
    return _report("volume_roadmap", location, issues)


def validate_stage_frame(frame: StageFrame) -> CriticReport:
    location = f"stage_{frame.volume:03d}"
    issues: List[CriticIssue] = []
    if frame.expected_chapters <= 0:
        issues.append(
            _issue(
                "missing_expected_chapters",
                "high",
                location,
                "stage frame does not declare expected chapter count",
                "Add or regenerate the stage with an explicit chapter count.",
            )
        )
    if not frame.stage_function:
        issues.append(
            _issue(
                "missing_stage_function",
                "medium",
                location,
                "stage frame lacks a clear structural function",
                "Fill the stage function so downstream arcs know what this stage is for.",
            )
        )
    if not frame.hooks:
        issues.append(
            _issue(
                "missing_stage_hook",
                "medium",
                location,
                "stage frame lacks aftereffects or hooks",
                "Add a stage-level hook or consequence to carry reader expectation forward.",
            )
        )
    return _report("stage_frame", location, issues)


def validate_arc_frame(frame: ArcFrame) -> CriticReport:
    location = f"vol_{frame.volume:02d}/arc_{frame.arc_index:03d}"
    issues: List[CriticIssue] = []
    if frame.start_chapter > frame.end_chapter:
        issues.append(
            _issue(
                "invalid_chapter_range",
                "high",
                location,
                "arc start chapter is greater than end chapter",
                "Regenerate or rename the arc with a valid chapter range.",
            )
        )
    if not frame.core_event:
        issues.append(
            _issue(
                "missing_core_event",
                "high",
                location,
                "arc frame has no core event",
                "Regenerate the story arc or add the core event section.",
            )
        )
    if not frame.emotion_curve:
        issues.append(
            _issue(
                "missing_emotion_curve",
                "medium",
                location,
                "arc frame has no readable emotion curve",
                "Add an explicit emotion curve in the arc's conflict/emotion section.",
            )
        )
    if not frame.protagonist_state_change:
        issues.append(
            _issue(
                "missing_state_change",
                "medium",
                location,
                "arc does not describe protagonist state change",
                "State the protagonist's start/end identity, power, resource, knowledge, or relation changes.",
            )
        )
    if not frame.chapter_pacing:
        issues.append(
            _issue(
                "missing_chapter_pacing",
                "low",
                location,
                "arc has no chapter pacing suggestion",
                "Add pacing distribution so chapter frame generation can stay on beat.",
            )
        )
    return _report("arc_frame", location, issues)


def validate_chapter_frame(frame: ChapterFrame, arc_frame: Optional[ArcFrame] = None) -> CriticReport:
    location = f"vol_{frame.volume:02d}/chapter_{frame.chapter:03d}"
    issues: List[CriticIssue] = []
    if not frame.goal:
        issues.append(
            _issue(
                "missing_goal",
                "high",
                location,
                "chapter frame has no chapter goal/opening state",
                "Regenerate the chapter outline with a clear opening state and short-term goal.",
            )
        )
    if len(frame.events) < 3:
        issues.append(
            _issue(
                "too_few_events",
                "high",
                location,
                "chapter frame has fewer than three event beats",
                "Regenerate the outline with five concrete event beats.",
            )
        )
    if not frame.emotion_curve:
        issues.append(
            _issue(
                "missing_emotion_curve",
                "medium",
                location,
                "chapter frame has no emotion curve",
                "Add a concrete reader emotion curve and mark the strongest beat.",
            )
        )
    if not frame.hook:
        issues.append(
            _issue(
                "missing_hook",
                "medium",
                location,
                "chapter frame has no ending hook",
                "Add a chapter ending hook that creates suspense, delayed payoff, or a new question.",
            )
        )
    if arc_frame and not (arc_frame.start_chapter <= frame.chapter <= arc_frame.end_chapter):
        issues.append(
            _issue(
                "arc_range_mismatch",
                "high",
                location,
                "chapter is linked to an arc whose chapter range does not include it",
                "Rebuild chapter frames after regenerating story arcs, or correct the arc index.",
            )
        )
    if not frame.foreshadowing:
        issues.append(
            _issue(
                "missing_foreshadowing",
                "low",
                location,
                "chapter frame has no foreshadowing or information-difference entry",
                "Add at least one information delta, clue, promise, or explicit note that none is intended.",
            )
        )
    return _report("chapter_frame", location, issues)


def validate_chapter_sequence(frames: Iterable[ChapterFrame], volume: int) -> CriticReport:
    ordered = sorted(frames, key=lambda item: item.chapter)
    location = f"vol_{volume:02d}/chapter_sequence"
    issues: List[CriticIssue] = []
    if not ordered:
        issues.append(
            _issue(
                "missing_chapters",
                "high",
                location,
                "no chapter frames found for this volume",
                "Run chapter-outlines or trajectory-sync for this volume.",
            )
        )
        return _report("chapter_sequence", location, issues)
    expected = list(range(ordered[0].chapter, ordered[-1].chapter + 1))
    actual = [item.chapter for item in ordered]
    missing = [item for item in expected if item not in actual]
    if missing:
        issues.append(
            _issue(
                "chapter_gap",
                "high",
                location,
                f"missing chapter frame(s): {missing}",
                "Regenerate missing chapter outlines or rerun trajectory-sync.",
            )
        )
    duplicates = sorted({item for item in actual if actual.count(item) > 1})
    if duplicates:
        issues.append(
            _issue(
                "duplicate_chapter",
                "high",
                location,
                f"duplicate chapter frame(s): {duplicates}",
                "Remove duplicate frame files and rerun trajectory-sync.",
            )
        )
    return _report("chapter_sequence", location, issues)


def validate_mechanics_presence(frames: Iterable[ChapterFrame], volume: int, mechanics_enabled: bool) -> CriticReport:
    ordered = sorted(frames, key=lambda item: item.chapter)
    location = f"vol_{volume:02d}/mechanics_sequence"
    issues: List[CriticIssue] = []
    if not mechanics_enabled or not ordered:
        return _report("mechanics_sequence", location, issues)

    empty = [frame.chapter for frame in ordered if not frame.mechanics_events]
    if len(empty) == len(ordered):
        issues.append(
            _issue(
                "missing_mechanics_events",
                "high",
                location,
                "reference mechanics are enabled, but all chapter frames lack mechanics_events",
                "Regenerate trajectory with MechanicsPatternBank or add mechanics_events to chapter frames.",
            )
        )
    elif len(empty) >= max(3, len(ordered) // 2):
        issues.append(
            _issue(
                "sparse_mechanics_events",
                "medium",
                location,
                f"many chapter frames lack mechanics_events: {empty[:20]}",
                "Check whether task/reward/skill/panel events should appear more regularly.",
            )
        )
    return _report("mechanics_sequence", location, issues)
