import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from training.adaptive_builder import (
    _backup_raw_chapter,
    _humanize_chapter_text,
    _raw_chapter_backup_path,
)


class RawChapterBackupTests(unittest.TestCase):
    def test_latest_raw_replaces_snapshot_and_archives_previous_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = SimpleNamespace(file_system=tmp)
            path = Path(_raw_chapter_backup_path(ws, 1, 3))

            _backup_raw_chapter(ws, 1, 3, "第一次生成的正文")
            _backup_raw_chapter(ws, 1, 3, "重新生成后的正文")

            self.assertEqual(path.read_text(encoding="utf-8").strip(), "重新生成后的正文")
            versions = list((path.parent / "versions").glob("003_第3章_*.raw.md"))
            self.assertEqual(len(versions), 1)
            self.assertEqual(versions[0].read_text(encoding="utf-8").strip(), "第一次生成的正文")

    def test_same_raw_content_does_not_create_duplicate_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = SimpleNamespace(file_system=tmp)
            path = Path(_raw_chapter_backup_path(ws, 1, 1))

            _backup_raw_chapter(ws, 1, 1, "相同正文")
            _backup_raw_chapter(ws, 1, 1, "相同正文")

            versions_dir = path.parent / "versions"
            self.assertFalse(versions_dir.exists())

    def test_humanizer_receives_workspace_writing_guide(self):
        class FakeLlm:
            def generate(self, prompt, temperature=0.7):
                self.prompt = prompt
                return "精修结果"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            guide = root / "writing" / "system_prompt.md"
            guide.parent.mkdir(parents=True)
            guide.write_text("保持半文半白的仙侠语感。", encoding="utf-8")
            ws = SimpleNamespace(file_system=str(root))
            llm = FakeLlm()

            result = _humanize_chapter_text(llm, ws, 1, 1, "第1章 测试\n原始正文")

        self.assertEqual(result, "精修结果")
        self.assertIn("保持半文半白的仙侠语感", llm.prompt)
        self.assertIn("原始正文", llm.prompt)


if __name__ == "__main__":
    unittest.main()
