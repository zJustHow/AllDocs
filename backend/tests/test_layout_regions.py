import unittest

from app.services.citations_util import public_citations
from app.services.pdf_layout_regions import normalize_layout_regions
from app.services.ingestion import (
    _block_spans_from_joined_blocks,
    _concat_pages,
    _regions_for_range,
    _split_text_with_offsets,
)


class RegionsForRangeTests(unittest.TestCase):
    def test_single_page_uses_block_y_bounds(self) -> None:
        page_spans = [(1, 0, (10.0, 20.0, 500.0, 800.0))]
        block_spans = _block_spans_from_joined_blocks(
            ["Alpha", "Beta"],
            [(100.0, 180.0), (220.0, 300.0)],
        )

        regions = _regions_for_range(page_spans, block_spans, 0, 5, total_len=10)

        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0]["page"], 1)
        self.assertEqual(regions[0]["bbox"], [10.0, 100.0, 500.0, 180.0])

    def test_cross_page_chunk_returns_multiple_regions(self) -> None:
        pages = [
            (1, "Page one text", (0.0, 0.0, 400.0, 800.0), [(0, 13, 50.0, 700.0)]),
            (2, "Page two text", (0.0, 0.0, 400.0, 800.0), [(0, 13, 60.0, 650.0)]),
        ]
        section_text, page_spans, block_spans = _concat_pages(pages)
        chunk_end = len(section_text)

        regions = _regions_for_range(
            page_spans,
            block_spans,
            0,
            chunk_end,
            total_len=len(section_text),
        )

        self.assertEqual([region["page"] for region in regions], [1, 2])
        self.assertEqual(regions[0]["bbox"][1], 50.0)
        self.assertEqual(regions[0]["bbox"][3], 700.0)
        self.assertEqual(regions[1]["bbox"][1], 60.0)
        self.assertEqual(regions[1]["bbox"][3], 650.0)

    def test_partial_last_page_only_highlights_overlap(self) -> None:
        pages = [
            (1, "AAAA", (0.0, 0.0, 400.0, 800.0), [(0, 4, 100.0, 200.0)]),
            (2, "BBBBCCCC", (0.0, 0.0, 400.0, 800.0), [(0, 4, 120.0, 220.0), (4, 8, 300.0, 420.0)]),
        ]
        section_text, page_spans, block_spans = _concat_pages(pages)
        chunks = _split_text_with_offsets(section_text, chunk_size=999, overlap=0)
        self.assertEqual(len(chunks), 1)
        offset, _piece = chunks[0]

        regions = _regions_for_range(
            page_spans,
            block_spans,
            offset,
            len(section_text),
            total_len=len(section_text),
        )

        self.assertEqual([region["page"] for region in regions], [1, 2])


class CitationRegionsTests(unittest.TestCase):
    def test_public_citations_includes_regions(self) -> None:
        citations = public_citations(
            [
                {
                    "document_id": "doc-1",
                    "document_name": "Manual.pdf",
                    "page": 1,
                    "section": "Intro",
                    "snippet": "hello",
                    "score": 0.9,
                    "layout_regions": [
                        {"page": 1, "bbox": [0.0, 10.0, 100.0, 200.0]},
                        {"page": 2, "bbox": [0.0, 20.0, 100.0, 300.0]},
                    ],
                }
            ]
        )

        self.assertEqual(len(citations[0]["regions"]), 2)
        self.assertEqual(citations[0]["regions"][1]["page"], 2)
        self.assertNotIn("bbox", citations[0])

    def test_normalize_layout_regions_requires_region_list(self) -> None:
        regions = normalize_layout_regions(None)

        self.assertEqual(regions, [])


if __name__ == "__main__":
    unittest.main()
