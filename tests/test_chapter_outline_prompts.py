import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from core.prompt_loader import PromptLoader
from training.adaptive_builder import (
    _generate_chapter_system_panel,
    _mark_finalized_draft_synced,
    _route_chapter_outline_refinement,
    _write_mechanics_payload,
    chapter_outline_resume_status,
    configure_system_panel,
    gen_chapter_outlines_for_arc,
    refine_chapter_outlines_serial,
    set_chapter_finalized,
)


class ChapterOutlinePromptTests(unittest.TestCase):
    def test_generated_outline_uses_three_sections_without_dialogue(self):
        prompt = PromptLoader.load(
            "serial_chapter_outline",
            previous_system_panel="无",
            story_arc="故事情节",
            previous_chapter_outline="上一章",
            chapter_num=1,
        )
        self.assertIn("# 故事线", prompt)
        self.assertIn("情绪基调：", prompt)
        self.assertIn("节奏拆解：", prompt)
        self.assertIn("# 单章简介", prompt)
        self.assertIn("禁止出现任何人物对白", prompt)
        self.assertNotIn("# highlights", prompt)
        self.assertNotIn("core_content：", prompt)
        self.assertIn("上一章系统面板", prompt)
        self.assertIn("当前故事情节单元", prompt)
        self.assertIn("上一章章纲", prompt)
        self.assertNotIn("兼容旧流程", prompt)
        self.assertNotIn("换皮映射表", prompt)

    def test_refinement_converts_legacy_outline_to_three_sections(self):
        prompt = PromptLoader.load(
            "chapter_outlines_refine",
            story_arc="故事情节",
            current_outlines="旧章纲",
            instruction="调整",
        )
        self.assertIn("统一改为以下 3 个部分", prompt)
        self.assertIn("即使原章纲是旧的四段结构", prompt)
        self.assertIn("禁止人物对白", prompt)

    def test_adjustment_router_clamps_chapter_to_arc_range(self):
        class FakeLlm:
            def generate(self, prompt, temperature=0.7):
                return '{"start_chapter": 99, "reason": "影响后续"}'

        start, mode, reason = _route_chapter_outline_refinement(
            FakeLlm(), [(5, "章纲")], "调整", 5, 8,
        )
        self.assertEqual(start, 8)
        self.assertEqual(mode, "revise")
        self.assertEqual(reason, "影响后续")

    def test_adjustment_router_does_not_route_before_finalized_boundary(self):
        class FakeLlm:
            def generate(self, prompt, temperature=0.7):
                return '{"start_chapter": 1, "reason": "默认从首章开始"}'

        start, mode, reason = _route_chapter_outline_refinement(
            FakeLlm(), [(5, "第五章")], "生成", 5, 8,
        )
        self.assertEqual(start, 5)
        self.assertEqual(mode, "revise")
        self.assertIn("第4章及之前已由最终版正文同步并锁定", reason)

    def test_adjustment_router_returns_regenerate_mode(self):
        class FakeLlm:
            def generate(self, prompt, temperature=0.7):
                return '{"start_chapter": 5, "mode": "regenerate", "reason": "完全重写"}'

        start, mode, reason = _route_chapter_outline_refinement(
            FakeLlm(), [(5, "第五章")], "把本情节全部重新生成", 5, 8,
        )
        self.assertEqual(start, 5)
        self.assertEqual(mode, "regenerate")
        self.assertEqual(reason, "完全重写")

    def test_generic_refinement_starts_after_synced_finalized_chapters(self):
        class FakeLlm:
            def __init__(self):
                self.calls = 0

            def generate(self, prompt, temperature=0.7):
                self.calls += 1
                return "第5章更新章纲"

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = SimpleNamespace(file_system=str(root))
            outline_dir = root / "chapter_outlines" / "vol_01"
            draft_dir = root / "chapters" / "vol_01"
            outline_dir.mkdir(parents=True)
            draft_dir.mkdir(parents=True)
            for chapter in range(1, 6):
                (outline_dir / f"chapter_{chapter:03d}.md").write_text(
                    f"第{chapter}章旧章纲", encoding="utf-8",
                )
            for chapter in range(1, 5):
                draft = f"第{chapter}章最终正文"
                (draft_dir / f"{chapter:03d}_第{chapter}章.md").write_text(
                    draft, encoding="utf-8",
                )
                status = set_chapter_finalized(ws, "drafts", 1, chapter, True)
                _mark_finalized_draft_synced(
                    ws, 1, chapter,
                    status["drafts"]["vol_01"][str(chapter)]["current_hash"],
                )
            configure_system_panel(ws, "disabled")
            llm = FakeLlm()
            arc = {"idx": 1, "start_ch": 1, "end_ch": 5, "content": "情节"}
            with (
                patch("training.adaptive_builder._list_novel_story_arcs", return_value=[arc]),
                patch("training.adaptive_builder._get_lite_llm", return_value=llm),
            ):
                result = refine_chapter_outlines_serial(ws, 1, 1, "生成")

        self.assertEqual(result["start_chapter"], 5)
        self.assertIn("第1-4章已由最终版正文同步并锁定", result["adjustment_note"])
        self.assertEqual(llm.calls, 1)

    def test_resume_status_finds_first_missing_chapter(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            chapter_dir = root / "chapter_outlines" / "vol_01"
            chapter_dir.mkdir(parents=True)
            (chapter_dir / "chapter_001.md").write_text("第一章", encoding="utf-8")
            (chapter_dir / "chapter_003.md").write_text("第三章", encoding="utf-8")
            panel_dir = root / "system_panels" / "vol_01"
            panel_dir.mkdir(parents=True)
            (panel_dir / "chapter_001.json").write_text('{"chapter": 1}', encoding="utf-8")
            (panel_dir / "chapter_003.json").write_text('{"chapter": 3}', encoding="utf-8")
            ws = SimpleNamespace(file_system=str(root))
            arcs = [{"idx": 1, "start_ch": 1, "end_ch": 4}]
            with patch("training.adaptive_builder._list_novel_story_arcs", return_value=arcs):
                status = chapter_outline_resume_status(ws, 1, 1)
        self.assertTrue(status["can_resume"])
        self.assertEqual(status["completed"], 2)
        self.assertEqual(status["total"], 4)
        self.assertEqual(status["next_chapter"], 2)

    def test_system_panel_definition_is_consolidated_into_one_file(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = SimpleNamespace(file_system=str(root))
            payload = {
                "profile": {"enabled": True, "visible_panel": True, "mode": "explicit_mechanics", "type": "system_panel", "reason": "测试"},
                "design": "设计",
                "rules": {"constraints": ["保持连续"]},
                "state": {"values": {"level": 1}, "inventory": {}, "skills": {}, "tasks": {}, "relationships": {}, "flags": {}},
            }
            _write_mechanics_payload(ws, payload)
            files = sorted(path.name for path in (root / "mechanics").iterdir())
            definition = json.loads(
                (root / "mechanics" / "system_panel.json").read_text(encoding="utf-8")
            )
        self.assertEqual(files, ["system_panel.json"])
        self.assertEqual(definition["initial_panel"]["核心数值"]["level"], 1)

    def test_disabled_system_panel_does_not_block_outline_completion(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            chapter_dir = root / "chapter_outlines" / "vol_01"
            chapter_dir.mkdir(parents=True)
            (chapter_dir / "chapter_001.md").write_text("第一章", encoding="utf-8")
            ws = SimpleNamespace(file_system=str(root))
            configure_system_panel(ws, "disabled")
            arcs = [{"idx": 1, "start_ch": 1, "end_ch": 1}]
            with patch("training.adaptive_builder._list_novel_story_arcs", return_value=arcs):
                status = chapter_outline_resume_status(ws, 1, 1)
        self.assertFalse(status["can_resume"])
        self.assertEqual(status["completed"], 1)

    def test_system_panel_retries_invalid_json_and_keeps_rich_panel(self):
        class FakeLlm:
            def __init__(self):
                self.calls = 0

            def generate(self, prompt, temperature=0.7):
                self.calls += 1
                if self.calls == 1:
                    return "这不是 JSON"
                return (
                    '{"panel":{"姓名":"林一","境界":"炼体一阶",'
                    '"天赋":["筋骨强健"],"技能":[{"名称":"斩魔刀法","阶段":"小成"}],'
                    '"精神":"20（心神澄澈）"},'
                    '"changes":[{"field":"境界","before":"无","after":"炼体一阶",'
                    '"reason":"本章完成突破"}]}'
                )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = SimpleNamespace(file_system=str(root))
            configure_system_panel(ws, "enabled")
            panel_dir = root / "system_panels" / "vol_01"
            panel_dir.mkdir(parents=True)
            (panel_dir / "chapter_001.json").write_text(
                '{"chapter":1,"protagonist_state":{"resources":{"灵石":12}}}',
                encoding="utf-8",
            )
            llm = FakeLlm()
            panel = _generate_chapter_system_panel(llm, ws, 1, 2, "获得五枚灵石")

        self.assertEqual(llm.calls, 2)
        self.assertEqual(panel["panel"]["境界"], "炼体一阶")
        self.assertEqual(panel["panel"]["天赋"], ["筋骨强健"])
        self.assertEqual(panel["panel"]["技能"][0]["阶段"], "小成")
        self.assertEqual(panel["changes"][0]["before"], "无")
        self.assertEqual(panel["changes"][0]["after"], "炼体一阶")
        self.assertNotIn("protagonist_state", panel)

    def test_system_panel_retries_schema_error(self):
        class FakeLlm:
            def __init__(self):
                self.responses = iter([
                    '{"panel":[],"changes":[]}',
                    '{"panel":{"当前状态":"正常"},"changes":[]}',
                ])

            def generate(self, prompt, temperature=0.7):
                return next(self.responses)

        with TemporaryDirectory() as tmp:
            ws = SimpleNamespace(file_system=tmp)
            configure_system_panel(ws, "enabled")
            panel = _generate_chapter_system_panel(FakeLlm(), ws, 1, 1, "相识")

        self.assertEqual(panel["changes"], [])
        self.assertEqual(panel["panel"]["当前状态"], "正常")

    def test_missing_last_panel_regenerates_outline_and_panel_as_one_unit(self):
        class FakeLlm:
            def __init__(self):
                self.responses = iter([
                    "修正后的新章纲",
                    '{"panel":{"境界":"炼体一阶","灵石":1},'
                    '"changes":[{"field":"灵石","before":3,"after":1,"reason":"购买"}]}',
                ])

            def generate(self, prompt, temperature=0.7):
                return next(self.responses)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = SimpleNamespace(file_system=str(root))
            configure_system_panel(ws, "enabled")
            outline_dir = root / "chapter_outlines" / "vol_01"
            panel_dir = root / "system_panels" / "vol_01"
            outline_dir.mkdir(parents=True)
            panel_dir.mkdir(parents=True)
            (outline_dir / "chapter_005.md").write_text("遗留的半完成章纲", encoding="utf-8")
            (panel_dir / "chapter_004.json").write_text(
                '{"chapter":4,"protagonist_state":{"inventory":{"灵石":3}}}',
                encoding="utf-8",
            )
            arc = {"idx": 1, "start_ch": 5, "end_ch": 5, "content": "第五章情节"}
            with (
                patch("training.adaptive_builder._load_volume_outline_context",
                      return_value=("舞台", "世界观", 5)),
                patch("training.adaptive_builder._list_novel_story_arcs", return_value=[arc]),
                patch("training.adaptive_builder._get_lite_llm", return_value=FakeLlm()),
                patch("training.adaptive_builder._ensure_system_panel_decision"),
                patch("training.adaptive_builder.load_rewrite_map", return_value="无"),
                patch("training.adaptive_builder._load_mechanics_context", return_value="已启用"),
            ):
                result = gen_chapter_outlines_for_arc(ws, 1, 1)

            saved_outline = (outline_dir / "chapter_005.md").read_text(encoding="utf-8").strip()
            saved_panel = json.loads(
                (panel_dir / "chapter_005.json").read_text(encoding="utf-8")
            )

        self.assertEqual(saved_outline, "修正后的新章纲")
        self.assertEqual(saved_panel["panel"]["灵石"], 1)
        self.assertEqual(saved_panel["panel"]["境界"], "炼体一阶")
        self.assertEqual(len(result["artifacts"]), 1)


if __name__ == "__main__":
    unittest.main()
