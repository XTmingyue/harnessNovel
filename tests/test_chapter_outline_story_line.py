import unittest

from training.adaptive_builder import (
    STORY_LINE_LIMIT,
    _cap_story_line_in_outline,
)


def _outline(story_line, rhythm="情绪基调：紧张\n节奏拆解：危机+爆发", brief="本章主角遇险并破局。" * 40):
    return (
        "【第1章 章纲】\n\n"
        "# 故事线\n"
        f"{story_line}\n\n"
        "# 单章节奏\n"
        f"{rhythm}\n\n"
        "# 单章简介\n"
        f"{brief}\n"
    )


class CapStoryLineTests(unittest.TestCase):
    def test_short_story_line_unchanged(self):
        text = _outline("主角穿越+初遇危机+金手指登场")
        self.assertEqual(_cap_story_line_in_outline(text), text)

    def test_trims_overlong_plus_chain_at_boundary(self):
        long_line = "+".join(f"事件节点{i}" for i in range(40))  # 远超 100 字
        self.assertGreater(len(long_line), STORY_LINE_LIMIT)
        capped = _cap_story_line_in_outline(_outline(long_line))
        story = capped.split("# 故事线", 1)[1].split("# 单章节奏", 1)[0].strip()
        self.assertLessEqual(len(story), STORY_LINE_LIMIT)
        # 在 + 边界切分，不会出现半截节点。
        self.assertTrue(all(not p.startswith("节点") or p.startswith("事件节点") for p in story.split("+")))

    def test_paragraph_hard_cut_when_no_plus(self):
        long_sentence = "，".join(f"主角在第{i}处遭遇变故" for i in range(40))
        self.assertGreater(len(long_sentence), STORY_LINE_LIMIT)
        capped = _cap_story_line_in_outline(_outline(long_sentence))
        story = capped.split("# 故事线", 1)[1].split("# 单章节奏", 1)[0].strip()
        self.assertLessEqual(len(story), STORY_LINE_LIMIT)

    def test_other_sections_preserved(self):
        long_line = "+".join(f"事件节点{i}" for i in range(40))
        text = _outline(long_line, rhythm="情绪基调：期待\n节奏拆解：铺垫+爆发", brief="简介正文。" * 30)
        capped = _cap_story_line_in_outline(text)
        self.assertIn("# 单章节奏", capped)
        self.assertIn("情绪基调：期待", capped)
        self.assertIn("# 单章简介", capped)
        self.assertIn("简介正文。", capped)

    def test_missing_section_returned_unchanged(self):
        text = "【第1章 章纲】\n\n没有故事线一节的章纲内容。\n"
        self.assertEqual(_cap_story_line_in_outline(text), text)

    def test_same_line_content_capped(self):
        long_line = "+".join(f"事件节点{i}" for i in range(40))
        text = f"【第1章 章纲】\n\n# 故事线：{long_line}\n\n# 单章节奏\n情绪基调：紧张\n"
        capped = _cap_story_line_in_outline(text)
        story = capped.split("# 故事线", 1)[1].split("# 单章节奏", 1)[0].strip()
        self.assertLessEqual(len(story), STORY_LINE_LIMIT)

    def test_idempotent(self):
        long_line = "+".join(f"事件节点{i}" for i in range(40))
        once = _cap_story_line_in_outline(_outline(long_line))
        twice = _cap_story_line_in_outline(once)
        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
