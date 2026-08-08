"""可恢复的参考小说三阶段拆解：单章卡 -> 故事片段 -> 全书结构。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config import ConfigLoader
from core.llm_provider import LLMProvider
from core.prompt_loader import PromptLoader
from core.text_utils import normalize_text, parse_json_response


ARC_FILE_RE = re.compile(r"^arc_(\d+)_ch(\d+)_(\d+)\.md$")
PIPELINE_VERSION = 2


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return data


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace").strip()


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(content.rstrip() + "\n", encoding="utf-8")
    temporary.replace(path)


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _chapter_digest(content: str) -> str:
    """章节级稳定指纹；忽略下载站造成的空白差异，但保留正文字符差异。"""
    canonical = re.sub(r"\s+", "", normalize_text(content or ""))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _ranges(numbers: list[int]) -> list[dict[str, int]]:
    ordered = sorted({number for number in numbers if number > 0})
    if not ordered:
        return []
    result: list[dict[str, int]] = []
    start = previous = ordered[0]
    for number in ordered[1:]:
        if number == previous + 1:
            previous = number
            continue
        result.append({"start": start, "end": previous})
        start = previous = number
    result.append({"start": start, "end": previous})
    return result


def _compact_text(value: Any, limit: int = 1000) -> str:
    text = str(value or "").strip()
    return text[:limit]


class ReferenceAnalyzer:
    """以可独立保存的单章事实卡作为故事片段提取的事实底座。"""

    def __init__(
        self,
        txt_path: str | Path,
        output_dir: str | Path,
        *,
        max_chapters: int | None = None,
        card_batch_size: int = 20,
        max_workers: int = 6,
        segment_load_size: int = 8,
        max_chapters_per_segment: int = 12,
        llm: Any | None = None,
        rebuild: bool = False,
    ) -> None:
        self.txt_path = Path(txt_path)
        self.output_dir = Path(output_dir)
        self.max_chapters = max_chapters
        self.card_batch_size = max(1, int(card_batch_size))
        self.max_workers = max(1, int(max_workers))
        self.segment_load_size = max(1, int(segment_load_size))
        self.max_chapters_per_segment = max(2, int(max_chapters_per_segment))
        self.llm = llm
        self.rebuild = rebuild

        self.cards_dir = self.output_dir / "chapter_cards"
        self.cards_index_path = self.output_dir / "chapter_cards_index.json"
        self.state_path = self.output_dir / "analysis_state.json"
        self.outlines_dir = self.output_dir / "outlines"
        self.state: dict[str, Any] = {}

    def run(self) -> dict[str, Any]:
        if not self.txt_path.is_file():
            raise FileNotFoundError(f"未找到参考小说：{self.txt_path}")

        volumes, chapters = self._load_chapters()
        total_chapters = len(chapters)
        if not total_chapters:
            raise RuntimeError("没有识别到有效章节，无法进行参考拆解。")
        target = min(self.max_chapters or total_chapters, total_chapters)
        if target < 1:
            raise ValueError("拆解章节数必须是正整数。")

        source_digest = _file_digest(self.txt_path)
        self._prepare_state(source_digest, total_chapters)
        previous_target = int(self.state.get("target_chapters") or 0)
        if self.state.get("resegmented") and not self.rebuild:
            completed_target = previous_target
            if target <= completed_target:
                print("  已完成参考拆解并执行智能分卷，复用现有分卷结果。")
                cards = self.state.get("chapter_cards") or {}
                return {
                    "target_chapters": completed_target,
                    "total_chapters": total_chapters,
                    "chapter_card_count": int(cards.get("complete_count") or 0),
                    "segmented_chapter_count": completed_target,
                    "pending_chapter_count": 0,
                    "structure_updated": False,
                    "is_complete": completed_target >= total_chapters,
                }
            self._restore_resegmented_working_volume()
        self.previous_target = previous_target
        volume_specs = self._build_volume_specs(volumes, chapters, target)

        print(f">>> 参考小说三阶段拆解启动 <<<")
        print(f"  单章事实卡：目标第 1-{target}/{total_chapters} 章，并发上限 {self.max_workers}")
        cards = self._extract_missing_cards(volume_specs, source_digest)
        self._write_card_index(cards, target, total_chapters)

        print("\n--- 阶段二：基于事实卡滚动提取故事片段 ---")
        segment_stats = self._extract_story_segments(volume_specs, cards)

        print("\n--- 阶段三：基于已闭合片段梳理结构 ---")
        structure_stats = self._build_structures(volume_specs, target, total_chapters)

        self.state["target_chapters"] = target
        self.state["total_chapters"] = total_chapters
        self.state["source_digest"] = source_digest
        self.state["chapter_cards"] = {
            "complete_count": len(cards),
            "completed_ranges": _ranges([int(card["chapter"]) for card in cards]),
        }
        self.state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        _write_json(self.state_path, self.state)

        return {
            "target_chapters": target,
            "total_chapters": total_chapters,
            "chapter_card_count": len(cards),
            "segmented_chapter_count": segment_stats["segmented_chapter_count"],
            "pending_chapter_count": segment_stats["pending_chapter_count"],
            "structure_updated": structure_stats["updated"],
            "is_complete": target == total_chapters and segment_stats["pending_chapter_count"] == 0,
        }

    def _load_chapters(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        # 延迟导入，避免 outline_builder 调用本模块时形成模块初始化循环。
        from training.outline_builder import split_chapters

        return split_chapters(str(self.txt_path))

    def _prepare_state(self, source_digest: str, total_chapters: int) -> None:
        state = _read_json(self.state_path, {})
        has_legacy = self._has_legacy_outline_assets()
        if self.rebuild and (state or has_legacy):
            self._clear_derived_assets()
            state = {}
            has_legacy = False
        if state and state.get("pipeline_version") != PIPELINE_VERSION:
            if not self.rebuild:
                raise RuntimeError("检测到旧版参考拆解状态。为避免覆盖现有产物，请使用 --rebuild-reference 显式重建。")
            self._clear_derived_assets()
            state = {}
        if not state and has_legacy:
            if not self.rebuild:
                raise RuntimeError("检测到旧版故事片段。新三阶段拆解不会静默覆盖它们；请使用 --rebuild-reference 显式迁移。")
            self._clear_derived_assets()
        if state and state.get("source_digest") and state.get("source_digest") != source_digest:
            if not self.rebuild:
                raise RuntimeError("参考小说源文件已变化。请使用 --rebuild-reference 重新建立单章卡和故事片段。")
            self._clear_derived_assets()
            state = {}

        if not state:
            state = {
                "pipeline_version": PIPELINE_VERSION,
                "source_digest": source_digest,
                "total_chapters": total_chapters,
                "target_chapters": 0,
                "chapter_cards": {},
                "volumes": {},
                "structure": {},
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
        self.state = state
        self.cards_dir.mkdir(parents=True, exist_ok=True)
        self.outlines_dir.mkdir(parents=True, exist_ok=True)

    def _restore_resegmented_working_volume(self) -> None:
        """作者更新后，将智能分卷产物还原为可继续滚动拆解的全书工作卷。

        智能分卷只改变文件归属，故事片段文件中的章节范围仍是全书章节号，因此可以
        无损汇回一个工作卷；新增片段完成后，外层流程会再次检查并执行智能分卷。
        """
        arc_items: dict[tuple[int, int], str] = {}
        for path in self.outlines_dir.glob("vol_*/story_arcs/arc_*_ch*_*.md"):
            match = ARC_FILE_RE.match(path.name)
            if not match:
                continue
            key = (int(match.group(2)), int(match.group(3)))
            arc_items[key] = _read_text(path)
        if not arc_items:
            self.state["resegmented"] = False
            self.state["volumes"] = {}
            return

        backup = self.outlines_dir / f".before_incremental_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup.mkdir(parents=True, exist_ok=True)
        for directory in sorted(self.outlines_dir.glob("vol_*")):
            if directory.is_dir():
                shutil.move(str(directory), str(backup / directory.name))

        working = self.outlines_dir / "vol_01_全书" / "story_arcs"
        working.mkdir(parents=True, exist_ok=True)
        for index, ((start, end), content) in enumerate(sorted(arc_items.items()), start=1):
            _write_text(working / f"arc_{index:03d}_ch{start:03d}_{end:03d}.md", content)
        self.state["resegmented"] = False
        self.state["volumes"] = {}
        self.state.setdefault("incremental_updates", []).append({
            "restored_at": datetime.now().isoformat(timespec="seconds"),
            "previous_target": int(self.state.get("target_chapters") or 0),
            "arc_count": len(arc_items),
        })
        _write_json(self.state_path, self.state)
        print(f"  已还原 {len(arc_items)} 个既有故事片段，准备结合新增章节重新检查末尾边界。")

    def _has_legacy_outline_assets(self) -> bool:
        if not self.outlines_dir.is_dir():
            return False
        return any(self.outlines_dir.glob("vol_*/story_arcs/arc_*.md"))

    def _clear_derived_assets(self) -> None:
        shutil.rmtree(self.cards_dir, ignore_errors=True)
        shutil.rmtree(self.outlines_dir, ignore_errors=True)
        self.cards_index_path.unlink(missing_ok=True)
        self.state_path.unlink(missing_ok=True)

    def _build_volume_specs(
        self,
        volumes: list[dict[str, Any]],
        chapters: list[dict[str, Any]],
        target: int,
    ) -> list[dict[str, Any]]:
        from training.outline_builder import group_chapters_by_volume, _vol_dir_name

        groups = group_chapters_by_volume(chapters, volumes)
        specs = []
        global_chapter = 0
        for index, group in enumerate(groups, start=1):
            all_items = list(group["chapters"])
            start_global = global_chapter + 1
            global_chapter += len(all_items)
            target_count = max(0, min(len(all_items), target - start_global + 1))
            title = str(group["title"])
            directory_name = _vol_dir_name(index - 1, title)
            specs.append({
                "index": index,
                "title": title,
                "directory_name": directory_name,
                "directory": self.outlines_dir / directory_name,
                "global_start": start_global,
                "total_count": len(all_items),
                "target_count": target_count,
                "chapters": all_items[:target_count],
            })
        return specs

    def _card_path(self, chapter: int) -> Path:
        return self.cards_dir / f"chapter_{chapter:04d}.json"

    def _load_card(self, chapter: int, source_digest: str, content_digest: str) -> dict[str, Any] | None:
        card = _read_json(self._card_path(chapter), {})
        if not isinstance(card, dict):
            return None
        saved_chapter_digest = str(card.get("content_digest") or "")
        if saved_chapter_digest:
            if saved_chapter_digest != content_digest:
                return None
        elif card.get("source_digest") != source_digest:
            return None
        return card

    def _extract_missing_cards(self, specs: list[dict[str, Any]], source_digest: str) -> list[dict[str, Any]]:
        planned: list[dict[str, Any]] = []
        existing: dict[int, dict[str, Any]] = {}
        for spec in specs:
            for local, chapter_data in enumerate(spec["chapters"], start=1):
                global_chapter = spec["global_start"] + local - 1
                content_digest = _chapter_digest(chapter_data.get("content", ""))
                card = self._load_card(global_chapter, source_digest, content_digest)
                if card:
                    # 文件整体摘要变化不影响章节事实卡复用；同步到当前快照。
                    card["source_digest"] = source_digest
                    card["content_digest"] = content_digest
                    _write_json(self._card_path(global_chapter), card)
                    existing[global_chapter] = card
                    continue
                planned.append({
                    "chapter": global_chapter,
                    "volume_index": spec["index"],
                    "volume_title": spec["title"],
                    "volume_chapter": local,
                    "title": chapter_data.get("title", f"第{global_chapter}章"),
                    "content": chapter_data.get("content", ""),
                    "content_digest": content_digest,
                })

        if planned:
            print(f"  待拆单章：{len(planned)} 章；已复用：{len(existing)} 章")
        errors: list[str] = []
        for start in range(0, len(planned), self.card_batch_size):
            batch = planned[start : start + self.card_batch_size]
            print(f"  并行提取单章事实卡：第 {batch[0]['chapter']}-{batch[-1]['chapter']} 章（{len(batch)} 章）...")
            workers = min(self.max_workers, len(batch))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(self._extract_one_card, item, source_digest): item for item in batch}
                for future in as_completed(futures):
                    item = futures[future]
                    try:
                        card = future.result()
                    except Exception as exc:  # noqa: BLE001 - 保留已成功的断点资产。
                        errors.append(f"第{item['chapter']}章：{exc}")
                        continue
                    existing[int(card["chapter"])] = card
                    print(f"    -> 第 {item['chapter']} 章事实卡已保存")
            self._update_card_state(existing)

        cards = [existing[number] for number in sorted(existing)]
        if errors:
            raise RuntimeError("单章事实卡存在失败，可直接重试：\n" + "\n".join(errors[:8]))
        return cards

    def _extract_one_card(self, item: dict[str, Any], source_digest: str) -> dict[str, Any]:
        prompt = PromptLoader.load(
            "reference_chapter_card",
            chapter=item["chapter"],
            volume_chapter=item["volume_chapter"],
            title=item["title"],
            chapter_text=item["content"],
        )
        payload = self._generate_json(prompt, f"第{item['chapter']}章事实卡")
        card = self._normalize_card(payload, item, source_digest)
        _write_json(self._card_path(int(card["chapter"])), card)
        return card

    def _generate_json(self, prompt: str, label: str) -> dict[str, Any]:
        if not self.llm:
            raise RuntimeError("未配置可用模型。")
        last_error: Exception | None = None
        current_prompt = prompt
        for attempt in range(3):
            raw = self.llm.generate(current_prompt, temperature=0.2, is_json=True)
            try:
                payload = parse_json_response(raw or "")
                if isinstance(payload, dict):
                    return payload
                raise ValueError("模型没有返回 JSON 对象")
            except Exception as exc:  # noqa: BLE001 - 需要针对模型格式容错重试。
                last_error = exc
                if attempt < 2:
                    current_prompt = (
                        prompt
                        + "\n\n【上次输出无法解析】\n"
                        + f"错误：{exc}\n"
                        + "请只返回合法 JSON 对象，不要包含 Markdown 或解释。"
                    )
        raise RuntimeError(f"{label} JSON 解析失败：{last_error}")

    def _normalize_card(self, payload: dict[str, Any], item: dict[str, Any], source_digest: str) -> dict[str, Any]:
        rhythm = payload.get("chapter_rhythm") or {}
        if not isinstance(rhythm, dict):
            rhythm = {"core_content": str(rhythm)}
        outline = str(payload.get("chapter_outline_600") or payload.get("summary") or "").strip()
        return {
            "chapter": item["chapter"],
            "volume_index": item["volume_index"],
            "volume_title": item["volume_title"],
            "volume_chapter": item["volume_chapter"],
            "title": _compact_text(payload.get("title") or item["title"], 160),
            "chapter_outline_600": _compact_text(outline, 2000),
            "chapter_rhythm": {
                "core_content": _compact_text(rhythm.get("core_content") or rhythm.get("core") or "", 400),
                "emotion_tone": _compact_text(rhythm.get("emotion_tone", ""), 400),
                "beat_detail": _compact_text(rhythm.get("beat_detail") or rhythm.get("detail") or "", 500),
            },
            "story_line": _compact_text(payload.get("story_line", ""), 500),
            "highlights": self._string_list(payload.get("highlights") or []),
            "entities": payload.get("entities") if isinstance(payload.get("entities"), dict) else {},
            "source_digest": source_digest,
            "content_digest": item.get("content_digest") or _chapter_digest(item.get("content", "")),
        }

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [_compact_text(item, 160) for item in value if str(item).strip()]
        if value:
            return [_compact_text(value, 160)]
        return []

    def _update_card_state(self, cards: dict[int, dict[str, Any]]) -> None:
        self.state["chapter_cards"] = {
            "complete_count": len(cards),
            "completed_ranges": _ranges(list(cards)),
        }
        self.state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        _write_json(self.state_path, self.state)

    def _write_card_index(self, cards: list[dict[str, Any]], target: int, total: int) -> None:
        payload = {
            "target_chapters": target,
            "total_chapters": total,
            "card_count": len(cards),
            "cards": [
                {
                    "chapter": card["chapter"],
                    "volume_index": card["volume_index"],
                    "volume_chapter": card["volume_chapter"],
                    "title": card["title"],
                    "path": str(self._card_path(int(card["chapter"])).relative_to(self.output_dir)),
                }
                for card in cards
            ],
        }
        _write_json(self.cards_index_path, payload)

    def _extract_story_segments(self, specs: list[dict[str, Any]], cards: list[dict[str, Any]]) -> dict[str, int]:
        cards_by_chapter = {int(card["chapter"]): card for card in cards}
        segmented_global: list[int] = []
        pending_global: list[int] = []
        for spec in specs:
            if not spec["target_count"]:
                continue
            volume_cards = []
            for local in range(1, spec["target_count"] + 1):
                global_chapter = spec["global_start"] + local - 1
                card = cards_by_chapter.get(global_chapter)
                if card:
                    copied = dict(card)
                    copied["chapter"] = local
                    copied["global_chapter"] = global_chapter
                    volume_cards.append(copied)
            if len(volume_cards) != spec["target_count"]:
                pending_global.extend(spec["global_start"] + local - 1 for local in range(1, spec["target_count"] + 1))
                continue
            result = self._extract_volume_segments(spec, volume_cards)
            segmented_global.extend(result["segmented_global"])
            pending_global.extend(result["pending_global"])
        return {
            "segmented_chapter_count": len(set(segmented_global)),
            "pending_chapter_count": len(set(pending_global)),
        }

    def _extract_volume_segments(self, spec: dict[str, Any], cards: list[dict[str, Any]]) -> dict[str, list[int]]:
        volume_dir: Path = spec["directory"]
        arc_dir = volume_dir / "story_arcs"
        arc_dir.mkdir(parents=True, exist_ok=True)
        existing = self._load_arc_items(arc_dir)
        self._reconsider_previous_tail(spec, cards, arc_dir, existing)
        existing = self._load_arc_items(arc_dir)
        closed_through = self._contiguous_end(existing)
        remaining = [card for card in cards if int(card["chapter"]) > closed_through]
        next_index = max((item["index"] for item in existing), default=0) + 1
        carryover: list[dict[str, Any]] = []
        cursor = 0
        force_final = spec["target_count"] == spec["total_count"]

        while cursor < len(remaining) or (carryover and force_final):
            new_cards = remaining[cursor : cursor + self.segment_load_size]
            cursor += len(new_cards)
            if not new_cards and not carryover:
                break
            window = carryover + new_cards
            if not window:
                break
            is_final_window = force_final and cursor >= len(remaining)
            print(
                f"  卷{spec['index']}滚动片段：第{window[0]['chapter']}-{window[-1]['chapter']}章"
                f"（新增 {len(new_cards)}，遗留 {len(carryover)}）..."
            )
            prompt = PromptLoader.load(
                "reference_segment_extract",
                window_start=window[0]["chapter"],
                window_end=window[-1]["chapter"],
                max_chapters=self.max_chapters_per_segment,
                is_final_window="是" if is_final_window else "否",
                previous_tail_context="（无，本轮按正常滚动窗口识别。）",
                chapter_cards_json=json.dumps(window, ensure_ascii=False, indent=2),
            )
            payload = self._generate_json(prompt, f"卷{spec['index']}故事片段")
            segments = self._normalize_segments(payload, window)
            if not segments:
                if is_final_window or len(window) >= self.max_chapters_per_segment:
                    segments = [self._fallback_segment(window[: self.max_chapters_per_segment], "窗口达到上限或当前范围结束，使用事实卡兜底收束。")]
                else:
                    carryover = window
                    continue

            consumed = int(segments[-1]["end_chapter"])
            for segment in segments:
                segment["segment_id"] = next_index
                _write_text(arc_dir / f"arc_{next_index:03d}_ch{segment['start_chapter']:03d}_{segment['end_chapter']:03d}.md", self._render_segment(segment))
                next_index += 1
            carryover = [card for card in window if int(card["chapter"]) > consumed]
            existing = self._load_arc_items(arc_dir)
            closed_through = self._contiguous_end(existing)
            self._write_arc_index(arc_dir, existing)
            self._update_volume_state(spec, closed_through, len(cards))
            if not carryover and cursor >= len(remaining):
                break

        existing = self._load_arc_items(arc_dir)
        closed_through = self._contiguous_end(existing)
        self._write_arc_index(arc_dir, existing)
        self._update_volume_state(spec, closed_through, len(cards))
        segmented_global = [spec["global_start"] + local - 1 for local in range(1, min(closed_through, len(cards)) + 1)]
        pending_global = [spec["global_start"] + local - 1 for local in range(closed_through + 1, len(cards) + 1)]
        return {"segmented_global": segmented_global, "pending_global": pending_global}

    def _reconsider_previous_tail(
        self,
        spec: dict[str, Any],
        cards: list[dict[str, Any]],
        arc_dir: Path,
        existing: list[dict[str, Any]],
    ) -> None:
        """用旧末片段和新增前10章重新判断一次自然边界。"""
        if not existing or not getattr(self, "previous_target", 0):
            return
        previous_local_end = self.previous_target - int(spec["global_start"]) + 1
        if previous_local_end < 1 or previous_local_end >= len(cards):
            return
        contiguous = [
            item for item in sorted(existing, key=lambda value: value["start_chapter"])
            if item["end_chapter"] <= previous_local_end
        ]
        if not contiguous:
            return
        tail = contiguous[-1]
        window_end = min(len(cards), previous_local_end + 10)
        window = [
            card for card in cards
            if int(tail["start_chapter"]) <= int(card["chapter"]) <= window_end
        ]
        if len(window) <= (tail["end_chapter"] - tail["start_chapter"] + 1):
            return
        print(
            f"  卷{spec['index']}末片段重评：旧第{tail['start_chapter']}-{tail['end_chapter']}章"
            f" + 上次未闭合尾部 + 新增前{window_end - previous_local_end}章..."
        )
        prompt = PromptLoader.load(
            "reference_segment_extract",
            window_start=window[0]["chapter"],
            window_end=window[-1]["chapter"],
            max_chapters=self.max_chapters_per_segment,
            is_final_window="否",
            previous_tail_context=tail["content"],
            chapter_cards_json=json.dumps(window, ensure_ascii=False, indent=2),
        )
        payload = self._generate_json(prompt, f"卷{spec['index']}末故事片段边界重评")
        segments = self._normalize_segments(payload, window)
        if not segments or int(segments[-1]["end_chapter"]) < int(tail["end_chapter"]):
            print("    -> 重评结果未形成可靠的新边界，保留原末片段。")
            return

        tail["path"].unlink(missing_ok=True)
        next_index = int(tail["index"])
        for segment in segments:
            segment["segment_id"] = next_index
            _write_text(
                arc_dir / f"arc_{next_index:03d}_ch{segment['start_chapter']:03d}_{segment['end_chapter']:03d}.md",
                self._render_segment(segment),
            )
            next_index += 1
        print(
            f"    -> 已重新划分末尾边界，当前重评覆盖至第{segments[-1]['end_chapter']}章。"
        )

    def _load_arc_items(self, arc_dir: Path) -> list[dict[str, Any]]:
        items = []
        for path in sorted(arc_dir.glob("arc_*_ch*_*.md")):
            match = ARC_FILE_RE.match(path.name)
            if not match:
                continue
            items.append({
                "index": int(match.group(1)),
                "start_chapter": int(match.group(2)),
                "end_chapter": int(match.group(3)),
                "path": path,
                "content": _read_text(path),
            })
        return items

    @staticmethod
    def _contiguous_end(items: list[dict[str, Any]]) -> int:
        expected = 1
        for item in sorted(items, key=lambda value: (value["start_chapter"], value["end_chapter"])):
            if item["start_chapter"] != expected:
                break
            expected = item["end_chapter"] + 1
        return expected - 1

    def _normalize_segments(self, payload: dict[str, Any], window: list[dict[str, Any]]) -> list[dict[str, Any]]:
        candidates = payload.get("completed_segments") or payload.get("segments") or []
        if not isinstance(candidates, list):
            return []
        expected = int(window[0]["chapter"])
        available = {int(card["chapter"]) for card in window}
        accepted = []
        for raw in candidates:
            if not isinstance(raw, dict):
                continue
            try:
                start = int(raw.get("start_chapter"))
                end = int(raw.get("end_chapter"))
            except (TypeError, ValueError):
                continue
            if end < start or start != expected or end - start + 1 > self.max_chapters_per_segment:
                break
            if any(number not in available for number in range(start, end + 1)):
                break
            accepted.append({
                "start_chapter": start,
                "end_chapter": end,
                "title": _compact_text(raw.get("title") or f"第{start}-{end}章情节", 180),
                "narrative_function": _compact_text(raw.get("narrative_function"), 600),
                "boundary_reason": _compact_text(raw.get("boundary_reason"), 700),
                "structure": _compact_text(raw.get("structure"), 1400),
                "protagonist_action": _compact_text(raw.get("protagonist_action"), 1000),
                "emotion_rhythm": _compact_text(raw.get("emotion_rhythm"), 700),
                "satisfaction_point": _compact_text(raw.get("satisfaction_point"), 700),
                "character_changes": _compact_text(raw.get("character_changes"), 900),
                "gains_costs": _compact_text(raw.get("gains_costs"), 800),
                "foreshadowing": _compact_text(raw.get("foreshadowing"), 900),
            })
            expected = end + 1
        return accepted

    def _fallback_segment(self, cards: list[dict[str, Any]], reason: str) -> dict[str, Any]:
        start = int(cards[0]["chapter"])
        end = int(cards[-1]["chapter"])
        return {
            "start_chapter": start,
            "end_chapter": end,
            "title": f"第{start}-{end}章过渡情节",
            "narrative_function": "基于已保存单章事实卡的阶段推进。",
            "boundary_reason": reason,
            "structure": "；".join(card.get("chapter_outline_600", "") or card.get("summary", "") for card in cards),
            "protagonist_action": "；".join(card.get("story_line", "") for card in cards if card.get("story_line")),
            "emotion_rhythm": " -> ".join(
                (card.get("chapter_rhythm") or {}).get("emotion_tone", "") for card in cards if (card.get("chapter_rhythm") or {}).get("emotion_tone")
            ),
            "satisfaction_point": "待后续片段或人工补充。",
            "character_changes": "；".join(
                (card.get("chapter_rhythm") or {}).get("beat_detail", "") for card in cards if (card.get("chapter_rhythm") or {}).get("beat_detail")
            ),
            "gains_costs": "待后续片段或人工补充。",
            "foreshadowing": "；".join("；".join(card.get("highlights", [])) for card in cards if card.get("highlights")),
        }

    @staticmethod
    def _render_segment(segment: dict[str, Any]) -> str:
        return "\n\n".join([
            f"【情节{segment['segment_id']}：第{segment['start_chapter']}-{segment['end_chapter']}章｜{segment['title']}】",
            f"情节功能：{segment['narrative_function']}",
            f"自然边界判断：{segment['boundary_reason']}",
            f"起承转合：{segment['structure']}",
            "叙事阶段识别：以单章事实卡归纳当前情节的推进、加压、转折与阶段性收束。",
            f"主角行动链：{segment['protagonist_action']}",
            f"矛盾与情绪曲线：{segment['emotion_rhythm']}",
            f"核心爽点或张力点：{segment['satisfaction_point']}",
            f"角色与关系变化：{segment['character_changes']}",
            f"收获与代价：{segment['gains_costs']}",
            f"伏笔与下个困境：{segment['foreshadowing']}",
        ])

    @staticmethod
    def _write_arc_index(arc_dir: Path, items: list[dict[str, Any]]) -> None:
        _write_json(arc_dir / "arcs_index.json", [
            {
                "id": item["index"],
                "start_ch": item["start_chapter"],
                "end_ch": item["end_chapter"],
                "file": item["path"].name,
            }
            for item in items
        ])

    def _update_volume_state(self, spec: dict[str, Any], closed_through: int, available_through: int) -> None:
        volumes = self.state.setdefault("volumes", {})
        volumes[str(spec["index"])] = {
            "title": spec["title"],
            "directory": spec["directory_name"],
            "global_start": spec["global_start"],
            "total_chapters": spec["total_count"],
            "available_through": available_through,
            "closed_through": closed_through,
            "pending_start": closed_through + 1 if closed_through < available_through else None,
        }
        self.state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        _write_json(self.state_path, self.state)

    def _build_structures(self, specs: list[dict[str, Any]], target: int, total: int) -> dict[str, bool]:
        volume_outlines = []
        segmented_global: list[int] = []
        fingerprint_parts = []
        for spec in specs:
            arc_items = self._load_arc_items(spec["directory"] / "story_arcs")
            closed = self._contiguous_end(arc_items)
            if not arc_items or not closed:
                continue
            arc_texts = [item["content"] for item in arc_items if item["content"]]
            if not arc_texts:
                continue
            digest = hashlib.sha256("\n".join(arc_texts).encode("utf-8")).hexdigest()
            fingerprint_parts.append(f"{spec['index']}:{digest}")
            state = self.state.setdefault("volumes", {}).setdefault(str(spec["index"]), {})
            outline_path = spec["directory"] / "volume_outline.md"
            if state.get("structure_digest") != digest or not outline_path.is_file():
                suffix = "已完成本卷" if closed >= spec["total_count"] else f"当前仅覆盖本卷第1-{closed}章"
                prompt = PromptLoader.load(
                    "volume_merge",
                    volume_title=f"{spec['title']}（{suffix}）",
                    start_chapter=1,
                    end_chapter=closed,
                    total_chapters=closed,
                    total_batches=len(arc_texts),
                    batch_summaries="\n\n---\n\n".join(arc_texts),
                )
                outline = normalize_text(self._generate_text(prompt, f"卷{spec['index']}结构梳理"))
                _write_text(outline_path, outline)
                state["structure_digest"] = digest
            volume_outlines.append({"title": spec["title"], "outline": _read_text(outline_path)})
            segmented_global.extend(spec["global_start"] + local - 1 for local in range(1, closed + 1))

        fingerprint = hashlib.sha256("|".join(fingerprint_parts).encode("utf-8")).hexdigest()
        structure = self.state.setdefault("structure", {})
        novel_outline_path = self.outlines_dir / "novel_outline.md"
        changed = structure.get("fingerprint") != fingerprint or not novel_outline_path.is_file()
        if not volume_outlines:
            return {"updated": False}
        if changed:
            all_outlines = "\n\n---\n\n".join(
                f"【{item['title']}】\n{item['outline']}" for item in volume_outlines
            )
            prompt = PromptLoader.load("novel_extract", all_volume_outlines=all_outlines)
            generated = normalize_text(self._generate_text(prompt, "参考小说整体结构梳理"))
            coverage = self._coverage_header(target, total, segmented_global)
            _write_text(novel_outline_path, coverage + "\n\n" + generated)
            structure.update({
                "fingerprint": fingerprint,
                "segmented_ranges": _ranges(segmented_global),
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            })
        return {"updated": changed}

    def _generate_text(self, prompt: str, label: str) -> str:
        if not self.llm:
            raise RuntimeError("未配置可用模型。")
        result = self.llm.generate(prompt, temperature=0.2)
        if not result:
            raise RuntimeError(f"{label}未获得模型输出。")
        return result

    @staticmethod
    def _coverage_header(target: int, total: int, segmented_global: list[int]) -> str:
        ranges = _ranges(segmented_global)
        range_text = "、".join(
            f"第{item['start']}章" if item["start"] == item["end"] else f"第{item['start']}-{item['end']}章"
            for item in ranges
        ) or "暂无"
        state = "最终结构" if target == total and ranges and ranges[-1]["end"] >= total else "阶段性结构"
        return "\n".join([
            "# 拆解覆盖状态",
            "",
            f"结构类型：{state}",
            f"单章事实卡覆盖：第1-{target}章 / 全书{total}章",
            f"已闭合故事片段覆盖：{range_text}",
            "说明：未闭合尾部不会被强行纳入结构，后续拆解会在保持已闭合片段不变的前提下继续补齐。",
        ])


def run_reference_analysis(
    txt_path: str | Path,
    output_dir: str | Path,
    *,
    batch_size: int = 20,
    max_chapters: int | None = None,
    resume: bool = False,
    rebuild: bool = False,
) -> dict[str, Any]:
    """CLI 入口：使用参考拆解模型运行新的三阶段分析。"""
    config = ConfigLoader.get_data_builder_config()
    if not config.get("api_key"):
        config["api_key"] = os.getenv("OPENAI_API_KEY")
    if not config.get("api_key"):
        raise RuntimeError("未检测到参考拆解模型 API Key。")
    analyzer = ReferenceAnalyzer(
        txt_path,
        output_dir,
        max_chapters=max_chapters,
        card_batch_size=batch_size,
        max_workers=min(8, max(2, batch_size)),
        segment_load_size=min(8, max(4, batch_size // 2)),
        max_chapters_per_segment=12,
        llm=LLMProvider(**config),
        rebuild=rebuild,
    )
    return analyzer.run()


def mark_resegmented(output_dir: str | Path) -> None:
    """记录旧版虚拟分卷已重组，后续完整重试不再回写原始单卷目录。"""
    state_path = Path(output_dir) / "analysis_state.json"
    state = _read_json(state_path, {})
    if not isinstance(state, dict) or state.get("pipeline_version") != PIPELINE_VERSION:
        return
    state["resegmented"] = True
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json(state_path, state)
