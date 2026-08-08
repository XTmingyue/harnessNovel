import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from training.adaptive_builder import gen_stage_design


def _stage(number, name, chapter_count):
    return (
        f"# 舞台{number}：{name}\n"
        f"预计章节数：{chapter_count}章\n\n"
        "# 一、卷纲概览\n概览\n\n"
        "# 二、三幕结构\n第一幕、第二幕、第三幕\n\n"
        "# 三、人物谱系\n人物\n\n"
        "# 四、伏笔追踪\n伏笔\n\n"
        "# 五、核心爽点\n爽点"
    )


class _RecordingLLM:
    def __init__(self):
        self.prompts = []
        self.responses = [
            {"long_mainline_md": "# 全书长线主线\n长线甲"},
            {"stage_roadmap_md": _stage(1, "矿区", 12)},
            {"stage_roadmap_md": _stage(2, "城市", 20)},
        ]

    def generate(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return json.dumps(self.responses.pop(0), ensure_ascii=False)


class StageDesignSerialPipelineTests(unittest.TestCase):
    def test_long_mainline_then_one_volume_per_stage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fs = root / "file_system"
            design = fs / "story_design"
            outlines = root / "reference_outlines"
            design.mkdir(parents=True)
            outlines.mkdir()
            (design / "worldview.md").write_text("世界观甲", encoding="utf-8")
            (design / "rough_outline.md").write_text("粗略大纲乙", encoding="utf-8")
            (design / "stage_outline.md").write_text(
                "# 阶段粗纲\n\n## 阶段1：起步\n阶段一丙\n\n## 阶段2：扩张\n阶段二丁",
                encoding="utf-8",
            )
            direction = root / "creative_direction.md"
            direction.write_text("灵感", encoding="utf-8")
            volume_ranges = {1: (1, 12), 2: (13, 32)}
            for number in (1, 2):
                volume = outlines / f"vol_{number:02d}_卷{number}"
                volume.mkdir()
                start, end = volume_ranges[number]
                (volume / "volume_outline.md").write_text(
                    f"# 卷纲概览\n参考卷纲{number}专属内容\n"
                    f"# 三幕结构\n第{start}章至第{end}章",
                    encoding="utf-8",
                )
            ws = SimpleNamespace(
                file_system=str(fs),
                reference_outlines=str(outlines),
                creative_direction=str(direction),
            )
            llm = _RecordingLLM()
            progress = []

            with (
                patch("training.adaptive_builder._get_llm", return_value=llm),
                patch("training.adaptive_builder._mark_stage_design_synced"),
                patch("training.adaptive_builder.gen_novel_name_synopsis", return_value={"name": "测试书名"}),
            ):
                result = gen_stage_design(
                    ws,
                    progress_callback=lambda phase, completed, total, detail: progress.append(
                        (phase, completed, total, detail)
                    ),
                )

            self.assertEqual(3, len(llm.prompts))
            self.assertIn("世界观甲", llm.prompts[0])
            self.assertIn("粗略大纲乙", llm.prompts[0])
            self.assertIn("阶段一丙", llm.prompts[0])
            self.assertNotIn("参考卷纲1专属内容", llm.prompts[0])

            self.assertIn("长线甲", llm.prompts[1])
            self.assertIn("阶段一丙", llm.prompts[1])
            self.assertIn("参考卷纲1专属内容", llm.prompts[1])
            self.assertIn("预计章节数：12章", llm.prompts[1])
            self.assertNotIn("预计章节数：20-30章", llm.prompts[1])
            self.assertNotIn("阶段二丁", llm.prompts[1])
            self.assertNotIn("参考卷纲2专属内容", llm.prompts[1])

            self.assertIn("阶段二丁", llm.prompts[2])
            self.assertIn("参考卷纲2专属内容", llm.prompts[2])
            self.assertIn("预计章节数：20章", llm.prompts[2])
            self.assertIn("# 舞台1：矿区", llm.prompts[2])
            self.assertNotIn("参考卷纲1专属内容", llm.prompts[2])

            roadmap = (design / "stage_roadmap.md").read_text(encoding="utf-8")
            self.assertEqual(2, roadmap.count("# 舞台"))
            self.assertIn("# 五、核心爽点", roadmap)
            self.assertEqual(roadmap.strip(), result["stage_roadmap"].strip())
            self.assertTrue(all(item[2] == 2 for item in progress))
            self.assertEqual([1, 2], [
                item[1] for item in progress if item[0] == "stage_complete"
            ])
            self.assertIn("长线主线", progress[0][3])
            self.assertEqual(("completed", 2, 2), progress[-1][:3])


if __name__ == "__main__":
    unittest.main()
