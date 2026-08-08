import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from webui.chapter_chat import ChapterOutlineChatManager


class ChapterChatResetTests(unittest.TestCase):
    def test_reset_removes_outline_and_system_panel_for_target_arc_only(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace_root = root / "workspaces"
            file_system = workspace_root / "demo" / "file_system"
            outline_dir = file_system / "chapter_outlines" / "vol_01"
            panel_dir = file_system / "system_panels" / "vol_01"
            outline_dir.mkdir(parents=True)
            panel_dir.mkdir(parents=True)
            for chapter in (1, 2, 3):
                (outline_dir / f"chapter_{chapter:03d}.md").write_text(
                    f"第{chapter}章", encoding="utf-8",
                )
                (panel_dir / f"chapter_{chapter:03d}.json").write_text(
                    f'{{"chapter":{chapter}}}', encoding="utf-8",
                )
            previous_outline_dir = file_system / "chapter_outlines" / "vol_00"
            previous_panel_dir = file_system / "system_panels" / "vol_00"
            previous_outline_dir.mkdir(parents=True)
            previous_panel_dir.mkdir(parents=True)
            (previous_outline_dir / "chapter_001.md").write_text("上一舞台", encoding="utf-8")
            (previous_panel_dir / "chapter_001.json").write_text(
                '{"chapter":1}', encoding="utf-8",
            )

            manager = ChapterOutlineChatManager(workspace_root)
            ws = SimpleNamespace(file_system=str(file_system))
            arcs = [
                {"idx": 1, "start_ch": 1, "end_ch": 2},
                {"idx": 2, "start_ch": 3, "end_ch": 3},
            ]
            with (
                patch("webui.chapter_chat.init_workspace", return_value=ws),
                patch("training.adaptive_builder._list_novel_story_arcs", return_value=arcs),
            ):
                manager.reset("demo", 1, 1)

            self.assertFalse((outline_dir / "chapter_001.md").exists())
            self.assertFalse((outline_dir / "chapter_002.md").exists())
            self.assertFalse((panel_dir / "chapter_001.json").exists())
            self.assertFalse((panel_dir / "chapter_002.json").exists())
            self.assertTrue((outline_dir / "chapter_003.md").exists())
            self.assertTrue((panel_dir / "chapter_003.json").exists())
            self.assertTrue((previous_outline_dir / "chapter_001.md").exists())
            self.assertTrue((previous_panel_dir / "chapter_001.json").exists())


if __name__ == "__main__":
    unittest.main()
