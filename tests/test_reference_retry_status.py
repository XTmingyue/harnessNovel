import json
import tempfile
import unittest
from pathlib import Path

from webui.task_runner import WorkspaceStore


class ReferenceRetryStatusTests(unittest.TestCase):
    def test_reference_analysis_completion_does_not_depend_on_legacy_worldview(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "测试"
            reference = workspace / "reference"
            chapters = reference / "chapters"
            file_system = workspace / "file_system"
            chapters.mkdir(parents=True)
            file_system.mkdir(parents=True)
            (reference / "sample_novel.txt").write_text("第1章\n正文", encoding="utf-8")
            (chapters / "chapter_0001.txt").write_text("正文", encoding="utf-8")
            (reference / "import_state.json").write_text(
                json.dumps({
                    "processed_chapters": 1,
                    "total_chapters": 1,
                    "is_complete": True,
                    "status": "complete",
                }),
                encoding="utf-8",
            )
            store = WorkspaceStore(root)
            complete = store.summary("测试")["reference"]
            self.assertTrue(complete["analysis_complete"])
            self.assertTrue(complete["is_complete"])
            self.assertNotIn("worldview_ready", complete)

    def test_large_chapter_cache_does_not_hide_reference_outlines(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "测试"
            cards = workspace / "reference" / "chapter_cards"
            outlines = workspace / "reference" / "outlines" / "vol_01_测试" / "story_arcs"
            cards.mkdir(parents=True)
            outlines.mkdir(parents=True)
            for number in range(900):
                (cards / f"chapter_{number:04d}.json").write_text("{}", encoding="utf-8")
            arc = outlines / "arc_001_ch1_5.md"
            arc.write_text("故事片段", encoding="utf-8")

            items = WorkspaceStore(root).tree("测试")
            paths = {item["path"] for item in items}
            self.assertIn(
                "reference/outlines/vol_01_测试/story_arcs/arc_001_ch1_5.md",
                paths,
            )
            self.assertFalse(any(path.startswith("reference/chapter_cards/") for path in paths))


if __name__ == "__main__":
    unittest.main()
