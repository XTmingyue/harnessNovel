"""Persistence helpers for structured narrative assets."""

import json
import os
import re
from typing import Any, Dict, List, Optional

from core.models import (
    ArcFrame,
    ChapterFrame,
    ContinuityLedger,
    CriticReport,
    NovelSpine,
    SceneFrame,
    StageFrame,
    StoryBible,
    StoryContract,
    VolumeRoadmap,
)


def _safe_name(value: str) -> str:
    value = str(value or "").strip()
    value = re.sub(r"[^0-9A-Za-z_.-]+", "_", value)
    return value.strip("_") or "item"


class NarrativeRepository:
    """Stores machine-readable story trajectory assets inside a workspace."""

    def __init__(self, ws):
        self.ws = ws
        self.root = ws.file_system

    def _path(self, *parts: str) -> str:
        return os.path.join(self.root, *parts)

    def _write_json(self, path: str, data: Dict[str, Any]) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        return path

    def _read_json(self, path: str) -> Optional[Dict[str, Any]]:
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _list_json(self, folder: str) -> List[str]:
        if not os.path.isdir(folder):
            return []
        return [
            os.path.join(folder, name)
            for name in sorted(os.listdir(folder))
            if name.endswith(".json")
        ]

    def story_bible_path(self) -> str:
        return self._path("bible", "story_bible.json")

    def story_contract_path(self) -> str:
        return self._path("bible", "story_contract.json")

    def write_story_contract(self, contract: StoryContract) -> str:
        return self._write_json(self.story_contract_path(), contract.to_dict())

    def read_story_contract(self) -> Optional[StoryContract]:
        data = self._read_json(self.story_contract_path())
        return StoryContract.from_dict(data) if data else None

    def write_story_bible(self, bible: StoryBible) -> str:
        return self._write_json(self.story_bible_path(), bible.to_dict())

    def read_story_bible(self) -> Optional[StoryBible]:
        data = self._read_json(self.story_bible_path())
        return StoryBible.from_dict(data) if data else None

    def novel_spine_path(self) -> str:
        return self._path("trajectory", "novel_spine.json")

    def write_novel_spine(self, spine: NovelSpine) -> str:
        return self._write_json(self.novel_spine_path(), spine.to_dict())

    def read_novel_spine(self) -> Optional[NovelSpine]:
        data = self._read_json(self.novel_spine_path())
        return NovelSpine.from_dict(data) if data else None

    def volume_roadmap_path(self, volume: int) -> str:
        return self._path("trajectory", "volumes", f"vol_{volume:02d}.json")

    def write_volume_roadmap(self, roadmap: VolumeRoadmap) -> str:
        return self._write_json(self.volume_roadmap_path(roadmap.volume), roadmap.to_dict())

    def read_volume_roadmap(self, volume: int) -> Optional[VolumeRoadmap]:
        data = self._read_json(self.volume_roadmap_path(volume))
        return VolumeRoadmap.from_dict(data) if data else None

    def list_volume_roadmaps(self, volume: Optional[int] = None) -> List[VolumeRoadmap]:
        if volume is not None:
            paths = [self.volume_roadmap_path(volume)]
        else:
            paths = self._list_json(self._path("trajectory", "volumes"))
        roadmaps = []
        for path in paths:
            data = self._read_json(path)
            if data:
                roadmaps.append(VolumeRoadmap.from_dict(data))
        roadmaps.sort(key=lambda item: item.volume)
        return roadmaps

    def stage_frame_path(self, volume: int) -> str:
        return self._path("trajectory", "stages", f"stage_{volume:03d}.json")

    def write_stage_frame(self, frame: StageFrame) -> str:
        return self._write_json(self.stage_frame_path(frame.volume), frame.to_dict())

    def read_stage_frame(self, volume: int) -> Optional[StageFrame]:
        data = self._read_json(self.stage_frame_path(volume))
        return StageFrame.from_dict(data) if data else None

    def list_stage_frames(self) -> List[StageFrame]:
        paths = self._list_json(self._path("trajectory", "stages"))
        frames = []
        for path in paths:
            data = self._read_json(path)
            if data:
                frames.append(StageFrame.from_dict(data))
        return frames

    def arc_frame_path(self, volume: int, arc_index: int, start_chapter: int, end_chapter: int) -> str:
        return self._path(
            "trajectory",
            "arcs",
            f"vol_{volume:02d}",
            f"arc_{arc_index:03d}_ch{start_chapter:03d}_{end_chapter:03d}.json",
        )

    def write_arc_frame(self, frame: ArcFrame) -> str:
        return self._write_json(
            self.arc_frame_path(
                frame.volume,
                frame.arc_index,
                frame.start_chapter,
                frame.end_chapter,
            ),
            frame.to_dict(),
        )

    def list_arc_frames(self, volume: Optional[int] = None) -> List[ArcFrame]:
        base = self._path("trajectory", "arcs")
        folders = []
        if volume is not None:
            folders.append(os.path.join(base, f"vol_{volume:02d}"))
        elif os.path.isdir(base):
            folders.extend(
                os.path.join(base, name)
                for name in sorted(os.listdir(base))
                if re.match(r"^vol_\d+$", name)
            )
        frames = []
        for folder in folders:
            for path in self._list_json(folder):
                data = self._read_json(path)
                if data:
                    frames.append(ArcFrame.from_dict(data))
        frames.sort(key=lambda item: (item.volume, item.arc_index, item.start_chapter))
        return frames

    def chapter_frame_path(self, volume: int, chapter: int) -> str:
        return self._path(
            "trajectory",
            "chapters",
            f"vol_{volume:02d}",
            f"chapter_{chapter:03d}.json",
        )

    def write_chapter_frame(self, frame: ChapterFrame) -> str:
        return self._write_json(self.chapter_frame_path(frame.volume, frame.chapter), frame.to_dict())

    def read_chapter_frame(self, volume: int, chapter: int) -> Optional[ChapterFrame]:
        data = self._read_json(self.chapter_frame_path(volume, chapter))
        return ChapterFrame.from_dict(data) if data else None

    def list_chapter_frames(self, volume: Optional[int] = None) -> List[ChapterFrame]:
        base = self._path("trajectory", "chapters")
        folders = []
        if volume is not None:
            folders.append(os.path.join(base, f"vol_{volume:02d}"))
        elif os.path.isdir(base):
            folders.extend(
                os.path.join(base, name)
                for name in sorted(os.listdir(base))
                if re.match(r"^vol_\d+$", name)
            )
        frames = []
        for folder in folders:
            for path in self._list_json(folder):
                data = self._read_json(path)
                if data:
                    frames.append(ChapterFrame.from_dict(data))
        frames.sort(key=lambda item: (item.volume, item.chapter))
        return frames

    def scene_frame_path(self, volume: int, chapter: int, scene_index: int) -> str:
        return self._path(
            "trajectory",
            "scenes",
            f"vol_{volume:02d}",
            f"chapter_{chapter:03d}",
            f"scene_{scene_index:02d}.json",
        )

    def write_scene_frame(self, frame: SceneFrame) -> str:
        return self._write_json(
            self.scene_frame_path(frame.volume, frame.chapter, frame.scene_index),
            frame.to_dict(),
        )

    def list_scene_frames(self, volume: Optional[int] = None, chapter: Optional[int] = None) -> List[SceneFrame]:
        base = self._path("trajectory", "scenes")
        folders = []
        if volume is not None and chapter is not None:
            folders.append(os.path.join(base, f"vol_{volume:02d}", f"chapter_{chapter:03d}"))
        elif volume is not None:
            vol_dir = os.path.join(base, f"vol_{volume:02d}")
            if os.path.isdir(vol_dir):
                folders.extend(
                    os.path.join(vol_dir, name)
                    for name in sorted(os.listdir(vol_dir))
                    if re.match(r"^chapter_\d+$", name)
                )
        elif os.path.isdir(base):
            for vol_name in sorted(os.listdir(base)):
                vol_dir = os.path.join(base, vol_name)
                if not os.path.isdir(vol_dir) or not re.match(r"^vol_\d+$", vol_name):
                    continue
                folders.extend(
                    os.path.join(vol_dir, name)
                    for name in sorted(os.listdir(vol_dir))
                    if re.match(r"^chapter_\d+$", name)
                )
        frames = []
        for folder in folders:
            for path in self._list_json(folder):
                data = self._read_json(path)
                if data:
                    frames.append(SceneFrame.from_dict(data))
        frames.sort(key=lambda item: (item.volume, item.chapter, item.scene_index))
        return frames

    def critic_report_path(self, category: str, target_type: str, target_id: str) -> str:
        return self._path(
            "critics",
            _safe_name(category),
            _safe_name(target_type),
            f"{_safe_name(target_id)}.json",
        )

    def write_critic_report(self, report: CriticReport, category: str = "trajectory") -> str:
        return self._write_json(
            self.critic_report_path(category, report.target_type, report.target_id),
            report.to_dict(),
        )

    def ledger_path(self) -> str:
        return self._path("ledger", "global_state.json")

    def write_ledger(self, ledger: ContinuityLedger) -> str:
        return self._write_json(self.ledger_path(), ledger.to_dict())

    def read_ledger(self) -> Optional[ContinuityLedger]:
        data = self._read_json(self.ledger_path())
        return ContinuityLedger.from_dict(data) if data else None

    def existing_chapter_paths(self, volume: int) -> Dict[int, str]:
        chapter_dir = self._path("chapters", f"vol_{volume:02d}")
        result = {}
        if not os.path.isdir(chapter_dir):
            return result
        for name in sorted(os.listdir(chapter_dir)):
            match = re.match(r"^(\d+)_.*\.md$", name)
            if match:
                result[int(match.group(1))] = os.path.join(chapter_dir, name)
        return result

    def remove_generated_arc_frames(self, volume: int) -> None:
        folder = self._path("trajectory", "arcs", f"vol_{volume:02d}")
        for path in self._list_json(folder):
            os.remove(path)

    def remove_generated_chapter_frames(self, volume: int) -> None:
        folder = self._path("trajectory", "chapters", f"vol_{volume:02d}")
        for path in self._list_json(folder):
            os.remove(path)

    def remove_generated_stage_frames(self) -> None:
        folder = self._path("trajectory", "stages")
        for path in self._list_json(folder):
            os.remove(path)

    def remove_generated_volume_roadmaps(self, volume: Optional[int] = None) -> None:
        if volume is not None:
            path = self.volume_roadmap_path(volume)
            if os.path.exists(path):
                os.remove(path)
            return
        folder = self._path("trajectory", "volumes")
        for path in self._list_json(folder):
            os.remove(path)
