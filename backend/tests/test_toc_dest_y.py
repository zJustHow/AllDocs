import unittest

import fitz

from app.services.pdf_toc import (
    _count_non_decreasing,
    _dest_y_from_pdf_space,
    _document_toc_dest_already_top_down,
    _toc_dest_coordinate_votes,
)


class TocDestYTests(unittest.TestCase):
    def setUp(self) -> None:
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=595, height=842)

    def tearDown(self) -> None:
        self.doc.close()

    def test_count_non_decreasing(self) -> None:
        self.assertEqual(_count_non_decreasing([72.0, 414.6, 551.4]), 2)
        self.assertEqual(_count_non_decreasing([769.0, 427.0, 290.0]), 0)

    def test_page_votes_manual_style_top_down_outline(self) -> None:
        raw_ys = [72.0, 414.6, 551.4, 657.0]
        top_down, pdf_space = _toc_dest_coordinate_votes(self.page, raw_ys)
        self.assertGreater(top_down, pdf_space)

    def test_page_votes_pdf_bottom_left_outline(self) -> None:
        raw_ys = [764.0, 500.0, 100.0]
        top_down, pdf_space = _toc_dest_coordinate_votes(self.page, raw_ys)
        self.assertGreater(pdf_space, top_down)

    def test_single_anchor_zone_vote(self) -> None:
        top_down, pdf_space = _toc_dest_coordinate_votes(self.page, [72.0])
        self.assertEqual(top_down, 1)
        self.assertEqual(pdf_space, 0)

        raw_y = 764.0
        top_down, pdf_space = _toc_dest_coordinate_votes(self.page, [raw_y])
        self.assertEqual(top_down, 0)
        self.assertEqual(pdf_space, 1)
        self.assertLess(_dest_y_from_pdf_space(self.page, 0.0, raw_y), 100.0)

    def test_document_vote_aggregates_all_bookmark_pages(self) -> None:
        page_top_down = self.doc.new_page(width=595, height=842)
        page_ambiguous = self.doc.new_page(width=595, height=842)

        page_raw_ys = {
            1: [72.0, 414.6, 551.4, 657.0],
            2: [400.0],
        }
        self.assertTrue(_document_toc_dest_already_top_down(self.doc, page_raw_ys))

        pdf_page = fitz.open()
        pdf_page.new_page(width=595, height=842)
        pdf_page.new_page(width=595, height=842)
        self.assertFalse(
            _document_toc_dest_already_top_down(
                pdf_page,
                {1: [764.0, 500.0, 100.0], 2: [400.0]},
            )
        )
        pdf_page.close()

        # Unused pages keep the fixture honest about multi-page docs.
        self.assertIsNotNone(page_top_down)
        self.assertIsNotNone(page_ambiguous)


if __name__ == "__main__":
    unittest.main()
