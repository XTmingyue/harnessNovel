import unittest

from training.adaptive_builder import (
    _extract_stage_from_roadmap,
    _infer_stage_chapter_count,
    _next_stage_number,
    _normalize_stage_roadmap,
)


class StageRoadmapParsingTests(unittest.TestCase):
    def test_accepts_nested_markdown_stage_headings(self):
        roadmap = """# 舞台路线图

## 舞台1：混沌初赛
预计章节数：12-15章
阶段功能：完成初赛。

## 舞台2：炼狱擂台
预计章节数：10章
阶段功能：进入复赛。
"""
        first = _extract_stage_from_roadmap(roadmap, 1)

        self.assertIn("混沌初赛", first)
        self.assertNotIn("炼狱擂台", first)
        self.assertEqual(_infer_stage_chapter_count(first), 15)
        self.assertEqual(_next_stage_number(roadmap), 3)

    def test_accepts_one_to_six_heading_levels_and_leading_zero(self):
        roadmap = "### 舞台01：开始\n预计章节数：5章\n###### Stage 2: Later\n预计章节数：6章"

        self.assertIn("开始", _extract_stage_from_roadmap(roadmap, 1))
        self.assertIn("Later", _extract_stage_from_roadmap(roadmap, 2))
        self.assertEqual(_next_stage_number(roadmap), 3)

    def test_normalize_strips_document_title_and_promotes_to_level_one(self):
        roadmap = "# 舞台路线图\n\n## 舞台1：混沌初赛\n预计章节数：12-15章\n阶段功能：完成初赛。"

        normalized = _normalize_stage_roadmap(roadmap)

        self.assertNotIn("舞台路线图", normalized)
        self.assertIn("# 舞台1：混沌初赛", normalized)
        # 总标题被移除后，舞台正文里仍保留「预计章节数」。
        first = _extract_stage_from_roadmap(roadmap, 1)
        self.assertIn("混沌初赛", first)
        self.assertEqual(_infer_stage_chapter_count(first), 15)
        self.assertEqual(_next_stage_number(roadmap), 2)

    def test_normalize_handles_bold_and_plain_stage_lines(self):
        roadmap = "**舞台1：新手村**\n预计章节数：10章\n\n舞台2：学院\n预计章节数：8章"

        normalized = _normalize_stage_roadmap(roadmap)

        self.assertIn("# 舞台1：新手村", normalized)
        self.assertIn("# 舞台2：学院", normalized)
        self.assertIn("新手村", _extract_stage_from_roadmap(roadmap, 1))
        self.assertIn("学院", _extract_stage_from_roadmap(roadmap, 2))
        self.assertEqual(_next_stage_number(roadmap), 3)

    def test_normalize_strips_code_fences(self):
        roadmap = "```markdown\n# 舞台1：秘境\n预计章节数：6章\n```"

        normalized = _normalize_stage_roadmap(roadmap)

        self.assertNotIn("```", normalized)
        self.assertIn("# 舞台1：秘境", normalized)
        self.assertEqual(_next_stage_number(roadmap), 2)

    def test_body_lines_with_stage_keyword_are_not_misread_as_stage(self):
        # 「舞台规则：」「舞台内短线：」等正文行「舞台」后无数字，绝不能被判成舞台标题。
        roadmap = "# 舞台1：测试\n预计章节数：5章\n舞台规则：限制主角\n舞台内短线：小目标"

        normalized = _normalize_stage_roadmap(roadmap)

        self.assertEqual(normalized.count("# 舞台"), 1)
        self.assertIn("舞台规则：限制主角", normalized)
        self.assertIn("舞台内短线：小目标", normalized)
        self.assertEqual(_next_stage_number(roadmap), 2)

    def test_normalize_is_idempotent(self):
        roadmap = "# 舞台路线图\n\n## 舞台01：开始\n预计章节数：5章\n\n**舞台2：进阶**\n预计章节数：7章"

        once = _normalize_stage_roadmap(roadmap)
        twice = _normalize_stage_roadmap(once)

        self.assertEqual(once, twice)
        self.assertEqual(_next_stage_number(roadmap), 3)


if __name__ == "__main__":
    unittest.main()
