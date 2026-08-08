import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from training.adaptive_builder import sync_stage_outline_from_new_reference


class _StageOutlineLlm:
    def __init__(self):
        self.prompts = []

    def generate(self, prompt, **kwargs):
        self.prompts.append(prompt)
        number = 3 if "【目标阶段编号】\n阶段3" in prompt else 2
        return json.dumps({
            "stage_outline_md": f"# 阶段{number}：增量阶段\n新增拆解对应的推进。",
            "adjustment_note": "已同步末尾阶段。",
        }, ensure_ascii=False)


class IncrementalStageOutlineSyncTests(unittest.TestCase):
    def _workspace(self, root):
        design = root / "story_design"
        design.mkdir(parents=True)
        (design / "stage_outline.md").write_text(
            "# 阶段粗纲\n\n# 阶段1：起步\n旧一\n\n# 阶段2：末段\n旧二",
            encoding="utf-8",
        )
        (design / "worldview.md").write_text("# 世界观\n新世界", encoding="utf-8")
        (design / "rough_outline.md").write_text("# 粗略大纲\n新大纲", encoding="utf-8")
        return SimpleNamespace(
            file_system=str(root),
            reference_outlines=str(root / "reference" / "outlines"),
        )

    def test_same_volume_count_only_replaces_last_stage(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ws = self._workspace(root)
            llm = _StageOutlineLlm()
            volumes = [{"vol_idx": 1, "title": "卷一"}, {"vol_idx": 2, "title": "卷二"}]
            with (
                patch("training.adaptive_builder._unused_reference_chapter_context", return_value=[(101, "新增第101章事实卡")]),
                patch("training.adaptive_builder.list_reference_volumes", return_value=volumes),
                patch("training.adaptive_builder.load_reference_volume_outline", return_value="# 一、卷纲概览\n末卷概览\n# 二、三幕结构\n末卷三幕\n# 三、人物谱系\n不应输入"),
                patch("training.adaptive_builder._get_llm", return_value=llm),
                patch("training.adaptive_builder._mark_reference_chapters_used"),
            ):
                result = sync_stage_outline_from_new_reference(ws)

            updated = result["stage_outline"]
            self.assertIn("# 阶段1：起步\n旧一", updated)
            self.assertNotIn("# 阶段2：末段\n旧二", updated)
            self.assertIn("# 阶段2：增量阶段", updated)
            self.assertNotIn("# 阶段3", updated)
            self.assertIn("新世界", llm.prompts[0])
            self.assertIn("新大纲", llm.prompts[0])
            self.assertIn("【倒数第二个阶段】", llm.prompts[0])
            self.assertIn("【当前最后一个阶段】", llm.prompts[0])
            self.assertIn("末卷概览", llm.prompts[0])
            self.assertIn("末卷三幕", llm.prompts[0])
            self.assertNotIn("不应输入", llm.prompts[0])
            self.assertNotIn("新增第101章事实卡", llm.prompts[0])
            state = json.loads((root / "story_design" / "design_state.json").read_text(encoding="utf-8"))
            self.assertTrue(state["pending_reference_stage_sync"])

    def test_new_reference_volume_appends_new_stage(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ws = self._workspace(root)
            llm = _StageOutlineLlm()
            volumes = [
                {"vol_idx": 1, "title": "卷一"},
                {"vol_idx": 2, "title": "卷二"},
                {"vol_idx": 3, "title": "卷三"},
            ]
            with (
                patch("training.adaptive_builder._unused_reference_chapter_context", return_value=[(101, "新增第101章事实卡")]),
                patch("training.adaptive_builder.list_reference_volumes", return_value=volumes),
                patch("training.adaptive_builder.load_reference_volume_outline", return_value="# 一、卷纲概览\n新增卷概览\n# 二、三幕结构\n新增卷三幕"),
                patch("training.adaptive_builder._get_llm", return_value=llm),
                patch("training.adaptive_builder._mark_reference_chapters_used"),
            ):
                result = sync_stage_outline_from_new_reference(ws)

            updated = result["stage_outline"]
            self.assertIn("# 阶段2：末段\n旧二", updated)
            self.assertIn("# 阶段3：增量阶段", updated)
            self.assertNotIn("【倒数第二个阶段】", llm.prompts[0])
            self.assertIn("【当前最后一个阶段】", llm.prompts[0])
            self.assertIn("新增卷概览", llm.prompts[0])


if __name__ == "__main__":
    unittest.main()
