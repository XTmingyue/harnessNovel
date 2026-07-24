"""Persistence helpers for reference-novel distillation assets."""

import json
import os
import re
from typing import Any, Dict, List, Optional

from core.models import (
    MechanicsPatternBank,
    MechanicsProfile,
    ReferenceArcCard,
    ReferenceChapterCard,
    ReferenceManifest,
    ReferencePatternBank,
)


class ReferenceRepository:
    """Stores source-novel assets under ``workspace.reference``."""

    def __init__(self, ws):
        self.ws = ws
        self.root = ws.reference

    def _path(self, *parts: str) -> str:
        return os.path.join(self.root, *parts)

    def _write_json(self, path: str, data: Dict[str, Any]) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        return path

    def _write_text(self, path: str, content: str) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content.rstrip() + "\n")
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

    def manifest_path(self) -> str:
        return self._path("reference_manifest.json")

    def write_manifest(self, manifest: ReferenceManifest) -> str:
        return self._write_json(self.manifest_path(), manifest.to_dict())

    def read_manifest(self) -> Optional[ReferenceManifest]:
        data = self._read_json(self.manifest_path())
        return ReferenceManifest.from_dict(data) if data else None

    def chapter_card_path(self, volume: int, chapter: int) -> str:
        return self._path("cards", "chapters", f"vol_{volume:02d}", f"chapter_{chapter:03d}.json")

    def write_chapter_card(self, card: ReferenceChapterCard) -> str:
        return self._write_json(self.chapter_card_path(card.volume, card.chapter), card.to_dict())

    def read_chapter_card(self, volume: int, chapter: int) -> Optional[ReferenceChapterCard]:
        data = self._read_json(self.chapter_card_path(volume, chapter))
        return ReferenceChapterCard.from_dict(data) if data else None

    def list_chapter_cards(self, volume: Optional[int] = None) -> List[ReferenceChapterCard]:
        base = self._path("cards", "chapters")
        folders = []
        if volume is not None:
            folders.append(os.path.join(base, f"vol_{volume:02d}"))
        elif os.path.isdir(base):
            folders.extend(
                os.path.join(base, name)
                for name in sorted(os.listdir(base))
                if re.match(r"^vol_\d+$", name)
            )
        cards = []
        for folder in folders:
            for path in self._list_json(folder):
                data = self._read_json(path)
                if data:
                    cards.append(ReferenceChapterCard.from_dict(data))
        cards.sort(key=lambda item: (item.volume, item.chapter))
        return cards

    def arc_card_path(self, volume: int, arc_index: int) -> str:
        return self._path("cards", "arcs", f"vol_{volume:02d}", f"arc_{arc_index:03d}.json")

    def write_arc_card(self, card: ReferenceArcCard) -> str:
        return self._write_json(self.arc_card_path(card.volume, card.arc_index), card.to_dict())

    def read_arc_card(self, volume: int, arc_index: int) -> Optional[ReferenceArcCard]:
        data = self._read_json(self.arc_card_path(volume, arc_index))
        return ReferenceArcCard.from_dict(data) if data else None

    def list_arc_cards(self, volume: Optional[int] = None) -> List[ReferenceArcCard]:
        base = self._path("cards", "arcs")
        folders = []
        if volume is not None:
            folders.append(os.path.join(base, f"vol_{volume:02d}"))
        elif os.path.isdir(base):
            folders.extend(
                os.path.join(base, name)
                for name in sorted(os.listdir(base))
                if re.match(r"^vol_\d+$", name)
            )
        cards = []
        for folder in folders:
            for path in self._list_json(folder):
                data = self._read_json(path)
                if data:
                    cards.append(ReferenceArcCard.from_dict(data))
        cards.sort(key=lambda item: (item.volume, item.arc_index))
        return cards

    def mechanics_profile_path(self) -> str:
        return self._path("mechanics", "mechanics_profile.json")

    def write_mechanics_profile(self, profile: MechanicsProfile) -> str:
        return self._write_json(self.mechanics_profile_path(), profile.to_dict())

    def read_mechanics_profile(self) -> Optional[MechanicsProfile]:
        data = self._read_json(self.mechanics_profile_path())
        return MechanicsProfile.from_dict(data) if data else None

    def mechanics_events_path(self, volume: int, chapter: int) -> str:
        return self._path("mechanics", "events", f"vol_{volume:02d}", f"chapter_{chapter:03d}.json")

    def write_mechanics_events(self, volume: int, chapter: int, payload: Dict[str, Any]) -> str:
        return self._write_json(self.mechanics_events_path(volume, chapter), payload)

    def distill_input_path(self, arc_id: str) -> str:
        safe = re.sub(r"[^0-9A-Za-z_.-]+", "_", arc_id or "arc")
        return self._path("distill_inputs", "arcs", f"{safe}.json")

    def write_distill_input(self, arc_id: str, payload: Dict[str, Any]) -> str:
        return self._write_json(self.distill_input_path(arc_id), payload)

    def list_distill_inputs(self) -> List[Dict[str, Any]]:
        folder = self._path("distill_inputs", "arcs")
        items = []
        for path in self._list_json(folder):
            data = self._read_json(path)
            if data:
                items.append(data)
        return items

    def reference_pattern_bank_path(self) -> str:
        return self._path("pattern_bank", "reference_patterns.json")

    def write_reference_pattern_bank(self, bank: ReferencePatternBank) -> str:
        return self._write_json(self.reference_pattern_bank_path(), bank.to_dict())

    def read_reference_pattern_bank(self) -> Optional[ReferencePatternBank]:
        data = self._read_json(self.reference_pattern_bank_path())
        return ReferencePatternBank.from_dict(data) if data else None

    def mechanics_pattern_bank_path(self) -> str:
        return self._path("pattern_bank", "mechanics_patterns.json")

    def write_mechanics_pattern_bank(self, bank: MechanicsPatternBank) -> str:
        return self._write_json(self.mechanics_pattern_bank_path(), bank.to_dict())

    def read_mechanics_pattern_bank(self) -> Optional[MechanicsPatternBank]:
        data = self._read_json(self.mechanics_pattern_bank_path())
        return MechanicsPatternBank.from_dict(data) if data else None

    def invalid_json_path(self, category: str, item_id: str) -> str:
        safe_category = re.sub(r"[^0-9A-Za-z_.-]+", "_", category or "unknown")
        safe_item = re.sub(r"[^0-9A-Za-z_.-]+", "_", item_id or "item")
        return self._path("debug", "invalid_json", safe_category, f"{safe_item}.txt")

    def write_invalid_json(self, category: str, item_id: str, raw: str, error: str) -> str:
        content = f"ERROR: {error}\n\nRAW RESPONSE:\n{raw or ''}"
        return self._write_text(self.invalid_json_path(category, item_id), content)
