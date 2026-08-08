import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from webui.task_runner import WorkspaceStore, story_arc_title


class WorkspaceVolumeDetailsTests(unittest.TestCase):
    def test_story_arc_title_is_exposed_to_downstream_pages(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "demo"
            arc_dir = workspace / "file_system" / "story_arcs" / "vol_01"
            arc_dir.mkdir(parents=True)
            (arc_dir / "arc_1_ch1_5.md").write_text(
                "【情节1：第1-5章｜牛马觉醒】\n\n情节功能：建立开局。",
                encoding="utf-8",
            )
            store = WorkspaceStore(root)
            volumes = store._volume_details(workspace, workspace / "file_system")

        self.assertEqual(volumes[0]["arcs"][0]["title"], "牛马觉醒")

    def test_story_arc_without_title_remains_compatible(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "demo"
            arc_dir = workspace / "file_system" / "story_arcs" / "vol_01"
            arc_dir.mkdir(parents=True)
            (arc_dir / "arc_1_ch1_5.md").write_text(
                "情节功能：旧格式没有标题。",
                encoding="utf-8",
            )
            store = WorkspaceStore(root)
            volumes = store._volume_details(workspace, workspace / "file_system")

        self.assertEqual(volumes[0]["arcs"][0]["title"], "")

    def test_story_arc_title_accepts_alternative_heading_formats(self):
        self.assertEqual(
            story_arc_title("# 情节2：第6-10章 | 首次逆转与庇护"),
            "首次逆转与庇护",
        )
        self.assertEqual(
            story_arc_title("情节单元3（第11-15章）：首次反杀与代价初现"),
            "首次反杀与代价初现",
        )


if __name__ == "__main__":
    unittest.main()
