import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from training.adaptive_builder import _remove_stage_outline_section, gen_design_concept


class _RecordingLLM:
    def __init__(self):
        self.prompts = []
        self.responses = [
            {"worldview_md": "# 世界观\n\n# 6. 地图/舞台层级\n- 层级1：矿区｜起点"},
            {"rough_outline_md": "# 粗略大纲\n\n# 核心玩法\n以规则破局。"},
            {
                "stage_outline_md": (
                    "# 阶段粗纲\n\n"
                    "## 阶段1：矿区求生\n完成起步。\n\n"
                    "## 阶段2：城市立足\n完成扩张。\n\n"
                    "## 阶段3：终结矛盾\n完成收束。"
                )
            },
        ]

    def generate(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return json.dumps(self.responses.pop(0), ensure_ascii=False)


class DesignConceptPipelineTests(unittest.TestCase):
    def test_removes_stage_section_without_dropping_following_sections(self):
        rough = (
            "# 核心玩法\n玩法\n"
            "# 阶段粗纲\n## 阶段1\n旧阶段内容\n"
            "# 主要角色\n角色内容"
        )

        cleaned = _remove_stage_outline_section(rough)

        self.assertNotIn("阶段粗纲", cleaned)
        self.assertNotIn("旧阶段内容", cleaned)
        self.assertIn("# 核心玩法", cleaned)
        self.assertIn("# 主要角色", cleaned)

    def test_generates_three_independent_files_with_bounded_inputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fs = root / "file_system"
            outlines = root / "reference_outlines"
            fs.mkdir()
            outlines.mkdir()
            direction_path = root / "creative_direction.md"
            direction_path.write_text("灵感甲", encoding="utf-8")
            ws = SimpleNamespace(
                file_system=str(fs),
                reference_outlines=str(outlines),
                creative_direction=str(direction_path),
            )
            llm = _RecordingLLM()
            progress = []
            guidance = {
                "reference_volume_count": 3,
                "stage_range": "3",
                "stage_min": 3,
                "stage_max": 3,
                "map_range": "3-5",
                "map_min": 3,
                "map_max": 5,
            }

            with (
                patch("training.adaptive_builder._get_llm", return_value=llm),
                patch("training.adaptive_builder._load_reference_context", return_value="参考全书大纲乙"),
                patch("training.adaptive_builder._reference_volume_structure_context", return_value="卷纲概览与三幕结构丙"),
                patch("training.adaptive_builder._design_structure_guidance", return_value=guidance),
                patch("training.adaptive_builder._load_outline_rules", return_value="大纲规则丁"),
                patch("training.adaptive_builder._reference_chapter_cards", return_value=[]),
                patch("training.adaptive_builder._record_story_design_reference_snapshot"),
                patch("training.adaptive_builder._mark_concept_revision"),
            ):
                result = gen_design_concept(
                    ws, creative_direction="灵感甲",
                    progress_callback=lambda phase, completed, total, detail: progress.append(
                        (phase, completed, total, detail)
                    ),
                )

            self.assertEqual(3, len(llm.prompts))
            self.assertIn("灵感甲", llm.prompts[0])
            self.assertIn("参考全书大纲乙", llm.prompts[0])
            self.assertNotIn("卷纲概览与三幕结构丙", llm.prompts[0])
            self.assertNotIn("3-5", llm.prompts[0])
            self.assertNotIn("大纲规则丁", llm.prompts[0])

            self.assertIn(result["worldview"], llm.prompts[1])
            self.assertIn("参考全书大纲乙", llm.prompts[1])
            self.assertNotIn("卷纲概览与三幕结构丙", llm.prompts[1])

            self.assertIn(result["worldview"], llm.prompts[2])
            self.assertIn(result["rough_outline"], llm.prompts[2])
            self.assertIn("卷纲概览与三幕结构丙", llm.prompts[2])
            self.assertNotIn("参考全书大纲乙", llm.prompts[2])

            design = fs / "story_design"
            self.assertEqual(result["worldview"], (design / "worldview.md").read_text(encoding="utf-8").strip())
            self.assertEqual(result["rough_outline"], (design / "rough_outline.md").read_text(encoding="utf-8").strip())
            self.assertEqual(result["stage_outline"], (design / "stage_outline.md").read_text(encoding="utf-8").strip())
            self.assertNotIn("阶段粗纲", result["rough_outline"])
            self.assertEqual([0, 1, 2, 3], [item[1] for item in progress])
            self.assertTrue(all(item[2] == 3 for item in progress))
            self.assertIn("世界观", progress[0][3])
            self.assertIn("全部生成", progress[-1][3])


if __name__ == "__main__":
    unittest.main()
