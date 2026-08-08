import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from training.adaptive_builder import chapter_finalization_status, set_chapter_finalized
from webui.draft_chat import DraftChatManager


class DraftResetTests(unittest.TestCase):
    def test_reset_removes_only_selected_arc_drafts_and_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws_root = root / "workspaces"
            file_system = ws_root / "作品" / "file_system"
            refined = file_system / "chapters" / "vol_01"
            refined_versions = refined / "versions"
            raw = file_system / "drafts" / "vol_01" / "raw_chapters"
            raw_versions = raw / "versions"
            for directory in (refined_versions, raw_versions):
                directory.mkdir(parents=True)

            for chapter in (1, 2, 3):
                (refined / f"{chapter:03d}_第{chapter}章.md").write_text(
                    f"第{chapter}章精修正文", encoding="utf-8",
                )
                (raw / f"{chapter:03d}_第{chapter}章.raw.md").write_text(
                    f"第{chapter}章原始正文", encoding="utf-8",
                )
                (refined_versions / f"{chapter:03d}_第{chapter}章.md_旧版").write_text(
                    "精修历史", encoding="utf-8",
                )
                (raw_versions / f"{chapter:03d}_第{chapter}章_旧版.raw.md").write_text(
                    "原稿历史", encoding="utf-8",
                )

            ws = SimpleNamespace(file_system=str(file_system))
            set_chapter_finalized(ws, "drafts", 1, 1, True)
            manager = DraftChatManager(ws_root)
            conv = manager.get("作品", 1, 1)
            conv.turns = [{"role": "user", "content": "生成"}]
            conv.save()
            arcs = [
                {"idx": 1, "start_ch": 1, "end_ch": 2},
                {"idx": 2, "start_ch": 3, "end_ch": 3},
            ]
            with (
                patch("webui.draft_chat.init_workspace", return_value=ws),
                patch("training.adaptive_builder._list_novel_story_arcs", return_value=arcs),
            ):
                result = manager.reset("作品", 1, 1)

            self.assertTrue(result["reset"])
            for chapter in (1, 2):
                self.assertFalse((refined / f"{chapter:03d}_第{chapter}章.md").exists())
                self.assertFalse((raw / f"{chapter:03d}_第{chapter}章.raw.md").exists())
                self.assertFalse(list(refined_versions.glob(f"{chapter:03d}_第{chapter}章.md_*")))
                self.assertFalse(list(raw_versions.glob(f"{chapter:03d}_第{chapter}章_*.raw.md")))
            self.assertTrue((refined / "003_第3章.md").exists())
            self.assertTrue((raw / "003_第3章.raw.md").exists())
            self.assertNotIn("1", chapter_finalization_status(ws)["drafts"].get("vol_01", {}))
            self.assertEqual(manager.get("作品", 1, 1).turns, [])


if __name__ == "__main__":
    unittest.main()
