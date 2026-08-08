import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from training.adaptive_builder import extend_stage_design


class _SyncLlm:
    def generate(self, prompt, **kwargs):
        self.prompt = prompt
        return json.dumps({
            "stage_roadmap_md": (
                "# 舞台2：新舞台\n预计章节数：10章\n"
                "# 一、卷纲概览\n承接更新后的全书设计。\n"
                "# 二、三幕结构\n第一幕。第二幕。第三幕。\n"
                "# 三、人物谱系\n主角继续推进。\n"
                "# 四、伏笔追踪\n回收旧伏笔。\n"
                "# 五、核心爽点\n完成翻盘。"
            ),
        }, ensure_ascii=False)


class StageDesignSyncTests(unittest.TestCase):
    def test_sync_preserves_existing_stage_and_only_appends(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            design = root / "story_design"
            design.mkdir(parents=True)
            original_stage = (
                "# 舞台1：旧舞台\n预计章节数：8章\n"
                "# 一、卷纲概览\n必须保持不变。\n"
                "# 二、三幕结构\n第一幕。第二幕。第三幕。\n"
                "# 三、人物谱系\n旧人物。\n"
                "# 四、伏笔追踪\n旧伏笔。\n"
                "# 五、核心爽点\n旧爽点。"
            )
            (design / "rough_outline.md").write_text("# 粗略大纲\n新版内容", encoding="utf-8")
            (design / "worldview.md").write_text("# 世界观\n新版规则", encoding="utf-8")
            (design / "long_mainline.md").write_text("# 全书长线主线\n旧长线", encoding="utf-8")
            (design / "stage_roadmap.md").write_text(original_stage, encoding="utf-8")
            (design / "stage_outline.md").write_text(
                "# 阶段1：旧阶段\n内容\n\n# 阶段2：新阶段\n内容", encoding="utf-8",
            )
            (design / "design_state.json").write_text(json.dumps({
                "concept_revision": 2,
                "stage_synced_concept_revision": 1,
                "pending_reference_stage_sync": True,
            }), encoding="utf-8")
            ws = SimpleNamespace(
                file_system=str(root),
                reference=str(root / "reference"),
                reference_outlines=str(root / "reference" / "outlines"),
            )
            llm = _SyncLlm()
            volumes = [
                {"vol_idx": 1, "title": "卷一", "chapter_count": 8},
                {"vol_idx": 2, "title": "卷二", "chapter_count": 10},
            ]
            with (
                patch("training.adaptive_builder._get_llm", return_value=llm),
                patch("training.adaptive_builder.list_reference_volumes", return_value=volumes),
                patch("training.adaptive_builder.load_reference_volume_outline", return_value="参考卷纲"),
                patch("training.adaptive_builder.list_reference_story_arcs", return_value=[]),
            ):
                result = extend_stage_design(
                    ws, "同步更新后的全书设计", sync_updated_design=True,
                )

            updated = (design / "stage_roadmap.md").read_text(encoding="utf-8")
            self.assertTrue(updated.startswith(original_stage))
            self.assertEqual(updated.count("# 舞台1：旧舞台"), 1)
            self.assertIn("# 舞台2：新舞台", updated)
            self.assertEqual("# 全书长线主线\n旧长线", result["long_mainline"])
            self.assertIn("参考卷纲", llm.prompt)
            state = json.loads((design / "design_state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["stage_synced_concept_revision"], 2)

    def test_same_stage_count_only_regenerates_last_stage(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            design = root / "story_design"
            design.mkdir(parents=True)
            stage1 = (
                "# 舞台1：旧舞台一\n预计章节数：8章\n# 一、卷纲概览\n旧一\n"
                "# 二、三幕结构\n三幕\n# 三、人物谱系\n人物\n# 四、伏笔追踪\n伏笔\n# 五、核心爽点\n爽点"
            )
            stage2 = (
                "# 舞台2：旧舞台二\n预计章节数：10章\n# 一、卷纲概览\n旧二\n"
                "# 二、三幕结构\n三幕\n# 三、人物谱系\n人物\n# 四、伏笔追踪\n伏笔\n# 五、核心爽点\n爽点"
            )
            (design / "long_mainline.md").write_text("# 全书长线主线\n长线", encoding="utf-8")
            (design / "stage_outline.md").write_text("# 阶段1：一\n内容\n# 阶段2：二\n已更新", encoding="utf-8")
            (design / "stage_roadmap.md").write_text(stage1 + "\n\n" + stage2, encoding="utf-8")
            (design / "design_state.json").write_text(json.dumps({
                "concept_revision": 2,
                "stage_synced_concept_revision": 1,
                "pending_reference_stage_sync": True,
            }), encoding="utf-8")
            ws = SimpleNamespace(file_system=str(root), reference_outlines=str(root / "reference" / "outlines"))
            volumes = [
                {"vol_idx": 1, "title": "卷一", "chapter_count": 8},
                {"vol_idx": 2, "title": "卷二", "chapter_count": 10},
            ]
            llm = _SyncLlm()
            with (
                patch("training.adaptive_builder._get_llm", return_value=llm),
                patch("training.adaptive_builder.list_reference_volumes", return_value=volumes),
                patch("training.adaptive_builder.load_reference_volume_outline", return_value="参考卷纲"),
                patch("training.adaptive_builder.list_reference_story_arcs", return_value=[]),
            ):
                result = extend_stage_design(ws, "同步末尾", sync_updated_design=True)

            self.assertIn(stage1, result["stage_roadmap"])
            self.assertNotIn("旧舞台二", result["stage_roadmap"])
            self.assertIn("# 舞台2：新舞台", result["stage_roadmap"])


if __name__ == "__main__":
    unittest.main()
