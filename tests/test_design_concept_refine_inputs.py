import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from training.adaptive_builder import refine_design_concept


class _RefineLlm:
    def __init__(self):
        self.prompt = ""

    def generate(self, prompt, **kwargs):
        self.prompt = prompt
        return json.dumps({
            "worldview_md": "# 世界观\n调整后世界",
            "rough_outline_md": "# 粗略大纲\n调整后大纲",
            "stage_outline_md": "# 阶段1：一\n调整后阶段",
            "adjustment_note": "完成",
        }, ensure_ascii=False)


class DesignConceptRefineInputTests(unittest.TestCase):
    def test_only_instruction_and_current_three_files_enter_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            design = root / "story_design"
            design.mkdir()
            (design / "worldview.md").write_text("# 世界观\n当前世界", encoding="utf-8")
            (design / "rough_outline.md").write_text("# 粗略大纲\n当前大纲", encoding="utf-8")
            (design / "stage_outline.md").write_text("# 阶段1：一\n当前阶段", encoding="utf-8")
            creative = root / "creative_direction.md"
            creative.write_text("不应输入的初始方向", encoding="utf-8")
            ws = SimpleNamespace(
                file_system=str(root),
                creative_direction=str(creative),
                reference_outlines=str(root / "reference" / "outlines"),
            )
            llm = _RefineLlm()
            with patch("training.adaptive_builder._get_llm", return_value=llm):
                refine_design_concept(ws, "用户本轮指令", compact_summary="不应输入的历史摘要")

            self.assertIn("用户本轮指令", llm.prompt)
            self.assertIn("当前世界", llm.prompt)
            self.assertIn("当前大纲", llm.prompt)
            self.assertIn("当前阶段", llm.prompt)
            self.assertNotIn("不应输入的初始方向", llm.prompt)
            self.assertNotIn("不应输入的历史摘要", llm.prompt)


if __name__ == "__main__":
    unittest.main()
