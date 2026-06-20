import unittest

from app.services.pdf_captions import is_caption_text, parse_caption_line
from app.services.pdf_refs import extract_figure_refs, text_mentions_figure_number


class ParseCaptionLineTests(unittest.TestCase):
    def test_chinese_figure_caption(self) -> None:
        parsed = parse_caption_line("图 4-7 修改起弧时间图示")
        assert parsed is not None
        kind, number, description, full_text = parsed
        self.assertEqual(kind, "figure")
        self.assertEqual(number, "4-7")
        self.assertEqual(description, "修改起弧时间图示")
        self.assertEqual(full_text, "图 4-7 修改起弧时间图示")

    def test_chinese_table_caption(self) -> None:
        parsed = parse_caption_line("表 2-1 额定参数表")
        assert parsed is not None
        kind, number, _, _ = parsed
        self.assertEqual(kind, "table")
        self.assertEqual(number, "2-1")

    def test_english_figure_caption(self) -> None:
        for line in (
            "Figure 4-7 Arc start time illustration",
            "figure 4-7 Arc start time illustration",
            "Fig. 4-7 Arc start time illustration",
            "fig 4-7 Arc start time illustration",
        ):
            with self.subTest(line=line):
                parsed = parse_caption_line(line)
                assert parsed is not None
                kind, number, description, _ = parsed
                self.assertEqual(kind, "figure")
                self.assertEqual(number, "4-7")
                self.assertEqual(description, "Arc start time illustration")

    def test_english_table_caption(self) -> None:
        parsed = parse_caption_line("Table 2-1 Rated parameters")
        assert parsed is not None
        kind, number, description, _ = parsed
        self.assertEqual(kind, "table")
        self.assertEqual(number, "2-1")
        self.assertEqual(description, "Rated parameters")

    def test_rejects_colon_separator(self) -> None:
        self.assertIsNone(parse_caption_line("Figure: 4-7 illustration"))

    def test_is_caption_text_single_line_only(self) -> None:
        self.assertTrue(is_caption_text("Figure 4-7 illustration"))
        self.assertFalse(is_caption_text("Figure 4-7 illustration\nextra line"))


class ExtractFigureRefsTests(unittest.TestCase):
    def test_english_figure_refs(self) -> None:
        text = "Set arc time to 0.5 s (see Figure 4-7). Check scan position as shown in Fig. 4-8."
        refs = extract_figure_refs(text)
        numbers = [ref.figure_number for ref in refs if ref.kind == "figure"]
        self.assertEqual(numbers, ["4-7", "4-8"])

    def test_english_table_refs(self) -> None:
        text = "Parameters refer to Table 2-1 below."
        refs = extract_figure_refs(text)
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].kind, "table")
        self.assertEqual(refs[0].figure_number, "2-1")

    def test_text_mentions_figure_number_english(self) -> None:
        self.assertTrue(
            text_mentions_figure_number("see Figure 4-7 for details", "figure", "4-7")
        )
        self.assertTrue(
            text_mentions_figure_number("refer to Table 2-1", "table", "2-1")
        )


if __name__ == "__main__":
    unittest.main()
