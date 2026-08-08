import json
import os
import re
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

from novel_cli import cmd_init, _replace_reference_with_latest_snapshot
from training.reference_analyzer import ReferenceAnalyzer, mark_resegmented
from webui.task_runner import WorkspaceStore


class FakeLLM:
    """用确定性输出验证断点资产，不依赖真实模型或 API 配置。"""

    def __init__(self):
        self.card_calls: list[int] = []

    def generate(self, prompt, temperature=0.2, is_json=False):
        if "【章节正文】" in prompt:
            chapter = int(re.search(r"【全书第 (\d+) 章", prompt).group(1))
            self.card_calls.append(chapter)
            return json.dumps({
                "title": f"第{chapter}章",
                "summary": f"第{chapter}章的事实摘要",
                "event_chain": "触发 -> 推进 -> 结果",
                "narrative_function": "推进",
                "emotion_rhythm": "平静 -> 紧张",
                "ending_hook": "新的疑问",
                "status_changes": "目标推进",
                "open_threads": "后续危机",
                "entities": {"characters": ["主角"]},
            }, ensure_ascii=False)
        if "【单章事实卡窗口】" in prompt:
            start, end = map(int, re.search(r"【窗口范围】第 (\d+)-(\d+) 章", prompt).groups())
            if start == 1 and end >= 2:
                segments = [self._segment(1, 2)]
            elif start == 3 and end >= 5:
                segments = [self._segment(3, 5)]
            else:
                segments = []
            return json.dumps({"completed_segments": segments, "carryover_reason": "等待后续章节"}, ensure_ascii=False)
        return "# 结构梳理\n\n按已闭合故事片段整理。"

    @staticmethod
    def _segment(start, end):
        return {
            "title": f"第{start}-{end}章事件",
            "start_chapter": start,
            "end_chapter": end,
            "narrative_function": "阶段推进",
            "boundary_reason": "阶段目标已完成",
            "structure": "触发 -> 推进 -> 收束",
            "protagonist_action": "主角行动并得到结果",
            "emotion_rhythm": "压迫 -> 反击",
            "satisfaction_point": "阶段兑现",
            "character_changes": "关系推进",
            "gains_costs": "获得线索并承担风险",
            "foreshadowing": "新的危机",
        }


class ReferenceAnalyzerTest(unittest.TestCase):
    def _source(self, root: Path) -> Path:
        source = root / "reference.txt"
        chapters = []
        for number in range(1, 6):
            chapters.append(f"第{number}章 测试\n" + (f"这是第{number}章的正文内容。" * 12))
        source.write_text("\n\n".join(chapters), encoding="utf-8")
        return source

    def test_resume_reuses_cards_and_closes_previous_tail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            llm = FakeLLM()
            source = self._source(root)
            output = root / "reference"

            first = ReferenceAnalyzer(
                source, output, max_chapters=3, card_batch_size=2,
                max_workers=2, segment_load_size=2, llm=llm,
            ).run()

            self.assertEqual(first["chapter_card_count"], 3)
            self.assertEqual(first["segmented_chapter_count"], 2)
            self.assertEqual(first["pending_chapter_count"], 1)
            self.assertEqual(sorted(llm.card_calls), [1, 2, 3])
            arcs = output / "outlines" / "vol_01_全书" / "story_arcs"
            self.assertTrue((arcs / "arc_001_ch001_002.md").is_file())

            second = ReferenceAnalyzer(
                source, output, max_chapters=5, card_batch_size=2,
                max_workers=2, segment_load_size=2, llm=llm,
            ).run()

            self.assertEqual(second["chapter_card_count"], 5)
            self.assertEqual(second["segmented_chapter_count"], 5)
            self.assertEqual(second["pending_chapter_count"], 0)
            self.assertEqual(sorted(llm.card_calls), [1, 2, 3, 4, 5])
            self.assertTrue((arcs / "arc_002_ch003_005.md").is_file())

            state = json.loads((output / "analysis_state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["volumes"]["1"]["closed_through"], 5)

            # 智能分卷后会移动原始“全书”目录；完整重试必须直接复用分卷结果。
            mark_resegmented(output)
            repeated = ReferenceAnalyzer(
                source, output, max_chapters=5, card_batch_size=2,
                max_workers=2, segment_load_size=2, llm=llm,
            ).run()
            self.assertTrue(repeated["is_complete"])
            self.assertEqual(sorted(llm.card_calls), [1, 2, 3, 4, 5])

    def test_latest_full_snapshot_reuses_prefix_without_duplicating_chapters(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            reference = root / "reference"
            cards = reference / "chapter_cards"
            cards.mkdir(parents=True)
            old_source = self._source(root)
            sample = reference / "sample_novel.txt"
            sample.write_text(old_source.read_text(encoding="utf-8"), encoding="utf-8")
            for number in range(1, 4):
                (cards / f"chapter_{number:04d}.json").write_text(
                    json.dumps({"chapter": number, "source_digest": "old"}, ensure_ascii=False),
                    encoding="utf-8",
                )
            (reference / "analysis_state.json").write_text(json.dumps({
                "pipeline_version": 2,
                "source_digest": "old",
                "target_chapters": 3,
                "chapter_cards": {"complete_count": 3},
            }), encoding="utf-8")
            ws = SimpleNamespace(reference=str(reference), reference_sample=str(sample))

            result = _replace_reference_with_latest_snapshot(ws, old_source)

            self.assertEqual(result["total_chapters"], 5)
            self.assertEqual(result["reused_cards"], 3)
            self.assertEqual(result["new_chapters"], 2)
            from training.outline_builder import split_chapters
            _, chapters = split_chapters(str(sample))
            self.assertEqual(len(chapters), 5)
            reused = json.loads((cards / "chapter_0001.json").read_text(encoding="utf-8"))
            self.assertTrue(reused["content_digest"])

    def test_new_snapshot_reconsiders_previous_forced_tail_with_next_chapters(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            llm = FakeLLM()
            full_source = self._source(root)
            reference = root / "reference"
            partial = root / "partial.txt"
            text = full_source.read_text(encoding="utf-8")
            marker = text.index("第4章")
            partial.write_text(text[:marker], encoding="utf-8")

            ReferenceAnalyzer(
                partial, reference, card_batch_size=2, max_workers=2,
                segment_load_size=3, llm=llm,
            ).run()
            sample = reference / "sample_novel.txt"
            sample.write_text(partial.read_text(encoding="utf-8"), encoding="utf-8")
            ws = SimpleNamespace(reference=str(reference), reference_sample=str(sample))
            _replace_reference_with_latest_snapshot(ws, full_source)

            updated = ReferenceAnalyzer(
                sample, reference, card_batch_size=2, max_workers=2,
                segment_load_size=3, llm=llm,
            ).run()

            arcs = reference / "outlines" / "vol_01_全书" / "story_arcs"
            self.assertTrue((arcs / "arc_002_ch003_005.md").is_file())
            self.assertFalse((arcs / "arc_002_ch003_003.md").exists())
            self.assertTrue(updated["structure_updated"])
            self.assertTrue((reference / "outlines" / "novel_outline.md").is_file())

    def test_import_only_does_not_start_analysis(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._source(root)
            original_home = os.environ.get("HARNESS_NOVEL_HOME")
            os.environ["HARNESS_NOVEL_HOME"] = str(root / "workspaces")
            try:
                cmd_init(Namespace(
                    workspace="仅导入测试",
                    txt=str(source),
                    batch_size=20,
                    max_chapters=None,
                    no_analyze=True,
                    rebuild_reference=False,
                ))
            finally:
                if original_home is None:
                    os.environ.pop("HARNESS_NOVEL_HOME", None)
                else:
                    os.environ["HARNESS_NOVEL_HOME"] = original_home

            reference = root / "workspaces" / "仅导入测试" / "reference"
            self.assertTrue((reference / "sample_novel.txt").is_file())
            self.assertFalse((reference / "analysis_state.json").exists())

    def test_reference_story_arc_exposes_covered_source_chapters_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "workspaces"
            workspace = root / "章节浏览"
            reference = workspace / "reference"
            reference.mkdir(parents=True)
            source = self._source(root)
            (reference / "sample_novel.txt").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

            ReferenceAnalyzer(
                reference / "sample_novel.txt", reference, max_chapters=5,
                card_batch_size=2, max_workers=2, segment_load_size=2, llm=FakeLLM(),
            ).run()

            store = WorkspaceStore(root)
            arc_path = "reference/outlines/vol_01_全书/story_arcs/arc_001_ch001_002.md"
            data = store.reference_arc_chapters("章节浏览", arc_path)
            self.assertEqual([chapter["number"] for chapter in data["chapters"]], [1, 2])
            # 应返回拆解后的事实卡字段，而非参考小说原文。
            self.assertEqual(data["chapters"][0]["source"], "card")
            self.assertNotIn("content", data["chapters"][0])
            self.assertEqual(data["chapters"][0]["summary"], "第1章的事实摘要")
            self.assertIn("主角", data["chapters"][0]["entities"]["characters"])
            with self.assertRaisesRegex(ValueError, "只读"):
                store.write_file("章节浏览", arc_path, "不应写入")


if __name__ == "__main__":
    unittest.main()
