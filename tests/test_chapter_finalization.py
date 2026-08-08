import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from training.adaptive_builder import (
    _finalized_chapter_boundary,
    _mark_finalized_draft_synced,
    chapter_finalization_status,
    chapter_outline_resume_status,
    configure_system_panel,
    set_chapter_finalized,
    sync_finalized_drafts_for_outlines,
)


class ChapterFinalizationTests(unittest.TestCase):
    def test_finalized_draft_starts_pending_sync(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = SimpleNamespace(file_system=tmp)
            draft_dir = root / "chapters" / "vol_01"
            draft_dir.mkdir(parents=True)
            (draft_dir / "003_第3章.md").write_text("最终正文", encoding="utf-8")
            set_chapter_finalized(ws, "drafts", 1, 3, True)
            status = chapter_finalization_status(ws)

        self.assertTrue(status["drafts"]["vol_01"]["3"]["finalized"])
        self.assertEqual(status["drafts"]["vol_01"]["3"]["status"], "pending")

    def test_latest_finalized_chapter_is_the_editing_boundary(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = SimpleNamespace(file_system=tmp)
            draft_dir = root / "chapters" / "vol_01"
            draft_dir.mkdir(parents=True)
            (draft_dir / "002_第2章.md").write_text("第二章", encoding="utf-8")
            (draft_dir / "004_第4章.md").write_text("第四章", encoding="utf-8")
            set_chapter_finalized(ws, "drafts", 1, 2, True)
            set_chapter_finalized(ws, "drafts", 1, 4, True)

            boundary = _finalized_chapter_boundary(ws, "drafts", 1, 1, 5)

        self.assertEqual(boundary, 4)

    def test_finalized_outline_is_complete_even_when_panel_is_absent(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            outline_dir = root / "chapter_outlines" / "vol_01"
            outline_dir.mkdir(parents=True)
            (outline_dir / "chapter_001.md").write_text("最终章纲", encoding="utf-8")
            draft_dir = root / "chapters" / "vol_01"
            draft_dir.mkdir(parents=True)
            draft_text = "最终正文"
            (draft_dir / "001_第1章.md").write_text(draft_text, encoding="utf-8")
            ws = SimpleNamespace(file_system=tmp)
            configure_system_panel(ws, "enabled")
            status = set_chapter_finalized(ws, "drafts", 1, 1, True)
            _mark_finalized_draft_synced(
                ws, 1, 1, status["drafts"]["vol_01"]["1"]["current_hash"],
            )
            arcs = [{"idx": 1, "start_ch": 1, "end_ch": 1}]
            with patch("training.adaptive_builder._list_novel_story_arcs", return_value=arcs):
                resume = chapter_outline_resume_status(ws, 1, 1)

        self.assertFalse(resume["can_resume"])
        self.assertEqual(resume["completed"], 1)

    def test_finalized_draft_syncs_outline_panel_and_becomes_dirty_after_edit(self):
        class FakeLlm:
            def __init__(self):
                self.responses = iter([
                    "【第1章 章纲】\n# 故事线\n最终事实\n# 单章节奏\n情绪基调：紧张\n节奏拆解：推进\n# 单章简介\n以最终正文为准。",
                    '{"panel":{"境界":"炼体一阶","当前状态":"清醒"},'
                    '"changes":[{"field":"境界","before":"无","after":"炼体一阶",'
                    '"reason":"最终正文中完成突破"}]}',
                ])

            def generate(self, prompt, temperature=0.7):
                return next(self.responses)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = SimpleNamespace(file_system=tmp)
            draft_dir = root / "chapters" / "vol_01"
            outline_dir = root / "chapter_outlines" / "vol_01"
            draft_dir.mkdir(parents=True)
            outline_dir.mkdir(parents=True)
            draft_path = draft_dir / "001_第1章.md"
            draft_path.write_text("主角在最终正文中突破到炼体一阶。", encoding="utf-8")
            (outline_dir / "chapter_001.md").write_text("旧章纲", encoding="utf-8")
            configure_system_panel(ws, "enabled")
            set_chapter_finalized(ws, "drafts", 1, 1, True)

            synced = sync_finalized_drafts_for_outlines(FakeLlm(), ws, 1, 1)
            after_sync = chapter_finalization_status(ws)
            synced_outline = (outline_dir / "chapter_001.md").read_text(encoding="utf-8")
            panel_exists = (root / "system_panels" / "vol_01" / "chapter_001.json").is_file()
            draft_path.write_text("用户再次编辑了最终正文。", encoding="utf-8")
            after_edit = chapter_finalization_status(ws)

        self.assertEqual(synced, [1])
        self.assertIn("最终事实", synced_outline)
        self.assertTrue(panel_exists)
        self.assertEqual(after_sync["drafts"]["vol_01"]["1"]["status"], "synced")
        self.assertEqual(after_edit["drafts"]["vol_01"]["1"]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
