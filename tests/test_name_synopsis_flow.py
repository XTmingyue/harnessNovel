import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from training.adaptive_builder import gen_novel_name_synopsis


class _NameLlm:
    def __init__(self):
        self.prompt = ""

    def generate(self, prompt, **kwargs):
        self.prompt = prompt
        return "方案一\n书名：测试书名\n一句话简介：测试简介\n完整简介：完整内容"


class NameSynopsisFlowTests(unittest.TestCase):
    def test_new_design_files_feed_name_synopsis_and_result_is_returned(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            design = root / "story_design"
            design.mkdir()
            (design / "rough_outline.md").write_text("新版粗略大纲", encoding="utf-8")
            (design / "worldview.md").write_text("新版世界观", encoding="utf-8")
            (design / "long_mainline.md").write_text("新版长线主线", encoding="utf-8")
            (design / "stage_roadmap.md").write_text("新版舞台路线图", encoding="utf-8")
            ws = SimpleNamespace(
                file_system=str(root),
                creative_direction=str(root / "creative_direction.md"),
                reference_sample=str(root / "missing.txt"),
            )
            llm = _NameLlm()

            with patch("training.adaptive_builder._get_llm", return_value=llm):
                result = gen_novel_name_synopsis(ws, force=True)

            self.assertIn("测试书名", result)
            self.assertIn("新版粗略大纲", llm.prompt)
            self.assertIn("新版长线主线", llm.prompt)
            self.assertNotIn("新版世界观", llm.prompt)
            self.assertNotIn("新版舞台路线图", llm.prompt)
            self.assertIn(
                "测试书名",
                (root / "novel_name_synopsis.md").read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
