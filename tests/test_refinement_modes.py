import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from training.adaptive_builder import (
    _normalize_refinement_mode,
    route_chapter_draft_refinement,
)


class RefinementModeTests(unittest.TestCase):
    def test_mode_fallback_distinguishes_regenerate_and_revise(self):
        self.assertEqual(
            _normalize_refinement_mode(None, "从第一章开始完全重新生成"),
            "regenerate",
        )
        self.assertEqual(
            _normalize_refinement_mode(None, "调整第一章人物说话方式"),
            "revise",
        )

    def test_draft_router_returns_revise_mode(self):
        class FakeLlm:
            def generate(self, prompt, temperature=0.7):
                self.prompt = prompt
                return '{"start_chapter": 2, "mode": "revise", "reason": "第二章首次出现目标对话"}'

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chapter_dir = root / "chapters" / "vol_01"
            chapter_dir.mkdir(parents=True)
            (chapter_dir / "001_第1章.md").write_text("第一章旧正文", encoding="utf-8")
            (chapter_dir / "002_第2章.md").write_text("第二章旧正文", encoding="utf-8")
            ws = SimpleNamespace(file_system=str(root))
            arc = {"idx": 1, "start_ch": 1, "end_ch": 2}
            llm = FakeLlm()
            with (
                patch("training.adaptive_builder._list_novel_story_arcs", return_value=[arc]),
                patch("training.adaptive_builder._get_lite_llm", return_value=llm),
            ):
                start, mode, reason = route_chapter_draft_refinement(
                    ws, 1, 1, "调整第二章的对话",
                )

        self.assertEqual(start, 2)
        self.assertEqual(mode, "revise")
        self.assertIn("第二章", reason)
        self.assertIn("第二章旧正文", llm.prompt)

    def test_draft_router_returns_regenerate_mode(self):
        class FakeLlm:
            def generate(self, prompt, temperature=0.7):
                return '{"start_chapter": 1, "mode": "regenerate", "reason": "用户要求重新创作"}'

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chapter_dir = root / "chapters" / "vol_01"
            chapter_dir.mkdir(parents=True)
            (chapter_dir / "001_第1章.md").write_text("第一章旧正文", encoding="utf-8")
            ws = SimpleNamespace(file_system=str(root))
            arc = {"idx": 1, "start_ch": 1, "end_ch": 1}
            with (
                patch("training.adaptive_builder._list_novel_story_arcs", return_value=[arc]),
                patch("training.adaptive_builder._get_lite_llm", return_value=FakeLlm()),
            ):
                start, mode, reason = route_chapter_draft_refinement(
                    ws, 1, 1, "完全重新生成",
                )

        self.assertEqual(start, 1)
        self.assertEqual(mode, "regenerate")
        self.assertIn("重新创作", reason)


if __name__ == "__main__":
    unittest.main()
