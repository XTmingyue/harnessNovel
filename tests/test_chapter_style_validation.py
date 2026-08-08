import unittest

from training.adaptive_builder import (
    _chapter_style_violations,
    _repair_chapter_style,
)


class _FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def generate(self, prompt, **kwargs):
        self.calls += 1
        return self.responses.pop(0)


class ChapterStyleValidationTests(unittest.TestCase):
    def test_detects_forbidden_ai_patterns(self):
        text = (
            "他注意的不是齿轮，而是线圈。\n"
            "门后传来一声巨响——有人来了。\n"
            "这不仅更快，而且更稳。"
        )

        violations = _chapter_style_violations(text)

        self.assertEqual(3, len(violations))
        self.assertEqual(3, sum(item["count"] for item in violations))

    def test_clean_prose_passes(self):
        text = "他掠过齿轮，目光停在线圈上。门后骤然一响。有人来了。"

        self.assertEqual([], _chapter_style_violations(text))

    def test_repair_retries_until_output_passes(self):
        llm = _FakeLLM([
            "第1章\n他看的不是门，而是窗。——风进来了。",
            "第1章\n他的目光停在窗上。风从缝隙里钻了进来。",
        ])
        source = "第1章\n他看的不是门，而是窗。"

        result = _repair_chapter_style(
            llm, source, _chapter_style_violations(source), max_attempts=2,
        )

        self.assertEqual(2, llm.calls)
        self.assertEqual([], _chapter_style_violations(result))

    def test_repair_blocks_invalid_output(self):
        llm = _FakeLLM([
            "第1章\n不是门，而是窗。",
            "第1章\n不是门，而是窗。",
        ])
        source = "第1章\n不是门，而是窗。"

        with self.assertRaisesRegex(RuntimeError, "已停止写入"):
            _repair_chapter_style(
                llm, source, _chapter_style_violations(source), max_attempts=2,
            )


if __name__ == "__main__":
    unittest.main()
