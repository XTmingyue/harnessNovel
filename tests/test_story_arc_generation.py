import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from training.adaptive_builder import (
    _compact_story_arc_result,
    _generate_story_arc,
    _reference_story_arc_average_chars,
    _simple_story_arc_context,
    _route_story_arc_refinement,
    _serial_refinement_targets,
    story_arc_resume_status,
)


class StoryArcGenerationTests(unittest.TestCase):
    def test_simplified_context_contains_only_four_content_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            design = root / "file_system" / "story_design"
            ref_arc_dir = root / "reference" / "outlines" / "vol_01_参考卷" / "story_arcs"
            design.mkdir(parents=True)
            ref_arc_dir.mkdir(parents=True)
            (design / "long_mainline.md").write_text("长线甲", encoding="utf-8")
            (design / "stage_roadmap.md").write_text(
                "# 舞台1：旧城\n预计章节数：10章\n当前舞台乙",
                encoding="utf-8",
            )
            (ref_arc_dir / "arc_001_ch001_005.md").write_text("参考片段丙", encoding="utf-8")
            ws = SimpleNamespace(
                file_system=str(root / "file_system"),
                reference_outlines=str(root / "reference" / "outlines"),
            )

            context = _simple_story_arc_context(ws, 1)

            self.assertEqual(
                {"long_mainline", "previous_stage", "current_stage", "reference_story_arcs"},
                set(context),
            )
            self.assertIn("长线甲", context["long_mainline"])
            self.assertIn("当前舞台乙", context["current_stage"])
            self.assertIn("参考片段丙", context["reference_story_arcs"])

    def test_generation_prompt_does_not_include_old_full_design_context(self):
        class FakeLLM:
            def generate(self, prompt, temperature=None):
                self.prompt = prompt
                return "【情节1：第1-5章｜新情节】\n情节功能：推进。"

        llm = FakeLLM()
        context = {
            "long_mainline": "长线甲",
            "previous_stage": "上一舞台乙",
            "current_stage": "当前舞台丙",
            "reference_story_arcs": "参考片段丁",
        }
        ws = SimpleNamespace(reference_outlines="/不存在")

        _generate_story_arc(
            ws, llm, 1, 1, 1, 5, context, target_char_count=1000,
        )

        self.assertIn("长线甲", llm.prompt)
        self.assertIn("上一舞台乙", llm.prompt)
        self.assertIn("当前舞台丙", llm.prompt)
        self.assertIn("参考片段丁", llm.prompt)
        self.assertNotIn("rough_outline", llm.prompt)
        self.assertNotIn("worldview", llm.prompt)

    def test_reference_story_arc_average_chars_ignores_whitespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            outlines = Path(tmp) / "outlines"
            arc_dir = outlines / "vol_01_测试" / "story_arcs"
            arc_dir.mkdir(parents=True)
            (arc_dir / "arc_001_ch001_002.md").write_text("甲 乙\n丙", encoding="utf-8")
            (arc_dir / "arc_002_ch003_004.md").write_text("一二三四五", encoding="utf-8")

            ws = SimpleNamespace(reference_outlines=str(outlines))

            # 平均值虽只有 4 字，仍使用安全下限，避免生成退化为过短提要。
            self.assertEqual(_reference_story_arc_average_chars(ws), 300)

    def test_reference_story_arc_average_chars_falls_back_without_arcs(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = SimpleNamespace(reference_outlines=str(Path(tmp) / "outlines"))
            self.assertEqual(_reference_story_arc_average_chars(ws), 1000)

    def test_overlong_story_arc_is_compacted_before_saving(self):
        class FakeLLM:
            def __init__(self):
                self.calls = 0

            def generate(self, prompt, temperature=None):
                self.calls += 1
                self.prompt = prompt
                return "精简结果"

        llm = FakeLLM()
        result = _compact_story_arc_result(
            llm, "冗" * 1000, arc_idx=1, start_ch=1, end_ch=5,
            target_char_count=600,
        )
        self.assertEqual(result, "精简结果")
        self.assertEqual(llm.calls, 1)
        self.assertIn("最多不得超过 750", llm.prompt)

    def test_story_arc_within_limit_skips_compaction(self):
        class UnexpectedLLM:
            def generate(self, prompt, temperature=None):
                raise AssertionError("不应调用压缩模型")

        result = _compact_story_arc_result(
            UnexpectedLLM(), "简" * 700, arc_idx=1, start_ch=1, end_ch=5,
            target_char_count=600,
        )
        self.assertEqual(result, "简" * 700)

    def test_resume_status_finds_first_missing_planned_arc(self):
        existing = [
            {"idx": 1, "start_ch": 1, "end_ch": 5},
            {"idx": 2, "start_ch": 6, "end_ch": 10},
        ]
        with (
            patch("training.adaptive_builder._load_volume_outline_context", return_value=("outline", "world", 20)),
            patch("training.adaptive_builder._list_novel_story_arcs", return_value=existing),
        ):
            status = story_arc_resume_status(SimpleNamespace(), 1)

        self.assertTrue(status["can_resume"])
        self.assertEqual(status["completed"], 2)
        self.assertEqual(status["total"], 4)
        self.assertEqual(status["next_arc"], 3)

    def test_refinement_router_selects_earliest_affected_arc(self):
        class RouterLLM:
            def generate(self, prompt, temperature=None):
                self.prompt = prompt
                return '{"start_arc": 3, "reason": "第三单元首次建立目标关系"}'

        arcs = [
            {"idx": 1, "content": "情节1"},
            {"idx": 2, "content": "情节2"},
            {"idx": 3, "content": "情节3"},
            {"idx": 4, "content": "情节4"},
        ]
        llm = RouterLLM()
        start, mode, reason = _route_story_arc_refinement(llm, arcs, "调整第三单元建立的关系")

        self.assertEqual(start, 3)
        self.assertEqual(mode, "revise")
        self.assertIn("第三单元", reason)
        self.assertIn("当前卷故事情节", llm.prompt)

    def test_refinement_router_recognizes_complete_regeneration(self):
        class RouterLLM:
            def generate(self, prompt, temperature=None):
                return '{"start_arc": 1, "mode": "regenerate", "reason": "用户要求推倒重写"}'

        arcs = [{"idx": 1, "content": "旧情节"}]
        start, mode, reason = _route_story_arc_refinement(
            RouterLLM(), arcs, "从头重新生成",
        )

        self.assertEqual(start, 1)
        self.assertEqual(mode, "regenerate")
        self.assertIn("推倒重写", reason)

    def test_serial_refinement_targets_include_unwritten_planned_arcs(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = SimpleNamespace(file_system=str(Path(tmp) / "file_system"))
            existing = [
                {
                    "idx": idx,
                    "start_ch": (idx - 1) * 5 + 1,
                    "end_ch": idx * 5,
                    "file": f"arc_{idx:03d}_ch{(idx - 1) * 5 + 1:03d}_{idx * 5:03d}.md",
                    "path": str(Path(tmp) / f"arc_{idx}.md"),
                    "content": f"情节{idx}",
                }
                for idx in range(1, 6)
            ]
            with patch(
                "training.adaptive_builder._load_volume_outline_context",
                return_value=("outline", "world", 70),
            ):
                targets = _serial_refinement_targets(ws, 1, existing, start_arc=3)

        self.assertEqual(len(targets), 12)
        self.assertEqual(targets[0]["idx"], 3)
        self.assertTrue(targets[2]["existed"])
        self.assertEqual(targets[3]["idx"], 6)
        self.assertFalse(targets[3]["existed"])
        self.assertEqual(targets[-1]["idx"], 14)


if __name__ == "__main__":
    unittest.main()
