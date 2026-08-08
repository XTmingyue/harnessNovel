import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from training.adaptive_builder import refine_stage_design


def _stage(number, name, chapter_count, marker):
    return (
        f"# 舞台{number}：{name}\n"
        f"预计章节数：{chapter_count}章\n\n"
        f"# 一、卷纲概览\n{marker}\n\n"
        "# 二、三幕结构\n三幕\n\n"
        "# 三、人物谱系\n人物\n\n"
        "# 四、伏笔追踪\n伏笔\n\n"
        "# 五、核心爽点\n爽点"
    )


class _RouteAndStageLLM:
    def __init__(self):
        self.prompts = []
        self.responses = [
            {
                "start_stage": 2,
                "mode": "revise",
                "update_long_mainline": False,
                "reason": "用户指定舞台2",
            },
            {"stage_roadmap_md": _stage(2, "新二", 10, "新舞台二")},
            {"stage_roadmap_md": _stage(3, "新三", 11, "新舞台三")},
        ]

    def generate(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return json.dumps(self.responses.pop(0), ensure_ascii=False)


class StageDesignSerialRefineTests(unittest.TestCase):
    def test_routes_then_preserves_prefix_and_regenerates_tail_serially(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            design = root / "file_system" / "story_design"
            outlines = root / "reference_outlines"
            design.mkdir(parents=True)
            outlines.mkdir()
            (design / "long_mainline.md").write_text("# 全书长线主线\n旧长线", encoding="utf-8")
            (design / "stage_outline.md").write_text(
                "# 阶段粗纲\n\n## 阶段1：一\n阶段一\n\n"
                "## 阶段2：二\n阶段二\n\n## 阶段3：三\n阶段三",
                encoding="utf-8",
            )
            old_stages = [
                _stage(1, "旧一", 9, "必须保留的舞台一"),
                _stage(2, "旧二", 10, "舞台二原版本"),
                _stage(3, "旧三", 11, "舞台三原版本"),
            ]
            (design / "stage_roadmap.md").write_text("\n\n".join(old_stages), encoding="utf-8")
            ranges = ((1, 9), (10, 19), (20, 30))
            for number, (start, end) in enumerate(ranges, 1):
                volume = outlines / f"vol_{number:02d}_卷{number}"
                volume.mkdir()
                (volume / "volume_outline.md").write_text(
                    f"# 卷纲概览\n卷{number}\n# 三幕结构\n第{start}章至第{end}章",
                    encoding="utf-8",
                )
            ws = SimpleNamespace(
                file_system=str(root / "file_system"),
                reference_outlines=str(outlines),
            )
            llm = _RouteAndStageLLM()

            with (
                patch("training.adaptive_builder._get_llm", return_value=llm),
                patch("training.adaptive_builder._backup_design_files"),
            ):
                result = refine_stage_design(ws, "调整舞台2的核心冲突")

            self.assertEqual(2, result["start_stage"])
            self.assertEqual("revise", result["mode"])
            self.assertEqual(3, len(llm.prompts))
            self.assertIn("舞台二原版本", llm.prompts[1])
            self.assertIn("新舞台二", llm.prompts[2])
            roadmap = (design / "stage_roadmap.md").read_text(encoding="utf-8")
            self.assertIn("必须保留的舞台一", roadmap)
            self.assertNotIn("舞台二原版本", roadmap)
            self.assertIn("新舞台二", roadmap)
            self.assertIn("新舞台三", roadmap)


if __name__ == "__main__":
    unittest.main()
