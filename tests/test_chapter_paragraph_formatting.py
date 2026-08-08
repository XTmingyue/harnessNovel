import unittest

from training.adaptive_builder import _format_chapter_paragraphs


class ChapterParagraphFormattingTests(unittest.TestCase):
    def test_short_paragraphs_remain_unchanged(self):
        source = "第1章 山雨\n\n雨落在瓦上。\n\n他推门走了进去。"
        self.assertEqual(source, _format_chapter_paragraphs(source))

    def test_long_narrative_is_split_only_at_sentence_boundaries(self):
        sentences = [
            "山风卷着冷雨掠过长街，檐下的灯笼被吹得来回摇晃。",
            "沈砚沿着墙根往前走，鞋底每一次落下都避开积水。",
            "远处忽然传来沉闷钟声，原本喧闹的酒楼同时关上窗户。",
            "他停在巷口看了一眼，随后把斗笠压低，继续朝城门走去。",
            "守门士卒已经换了陌生面孔，腰间还挂着从未见过的黑木牌。",
            "沈砚没有上前盘问，只把这一幕牢牢记下，转身混入避雨的人群。",
        ]
        source = "".join(sentences)
        result = _format_chapter_paragraphs(source, target_length=80, max_length=120)
        paragraphs = result.split("\n\n")
        self.assertGreater(len(paragraphs), 1)
        self.assertEqual(source, "".join(paragraphs))
        self.assertTrue(all(part[-1] in "。！？!?…”’」』）】》〉" for part in paragraphs))

    def test_dialogue_is_never_cut_inside_quotes(self):
        dialogue = "“你若现在进城，就再也没有回头路了。巡夜司已经封住南门，他们等的正是你。”"
        source = (
            "雨水顺着斗笠边缘不断滴落，巷口的人影却始终没有移动。"
            + dialogue
            + "沈砚没有回答，只将袖中的铜牌握紧，抬眼看向城楼。"
            + "钟声再次响起，城门后的铁链开始缓慢绷紧，街上行人纷纷退开。"
        )
        result = _format_chapter_paragraphs(source, target_length=55, max_length=85)
        paragraphs = result.split("\n\n")
        self.assertEqual(source, "".join(paragraphs))
        self.assertEqual(1, sum(dialogue in paragraph for paragraph in paragraphs))

    def test_unclosed_dialogue_is_kept_as_one_paragraph(self):
        source = "“这条路不能走。" + "风已经变了，城里的人也变了。" * 20
        self.assertEqual(source, _format_chapter_paragraphs(source, target_length=40, max_length=60))

    def test_existing_manual_line_breaks_are_preserved(self):
        source = "风起。\n灯灭。\n有人踏雨而来。" * 20
        self.assertEqual(source, _format_chapter_paragraphs(source, target_length=40, max_length=60))

    def test_title_with_single_line_break_does_not_disable_body_formatting(self):
        body = "夜雨敲打着屋瓦，院中的积水漫过青石。" * 12
        source = f"第1章 夜雨\n{body}"
        result = _format_chapter_paragraphs(source, target_length=55, max_length=90)
        self.assertTrue(result.startswith("第1章 夜雨\n"))
        self.assertIn("\n\n", result)
        self.assertEqual(source.replace("\n", ""), result.replace("\n", ""))


if __name__ == "__main__":
    unittest.main()
