import unittest

from app.services.chunk_alignment import build_chunk_sub_index


def _asset(
    asset_id: str,
    *,
    figure_number: str | None = None,
    figure_caption: str | None = None,
    page: int = 1,
    y: float = 0.0,
) -> dict:
    return {
        "asset_id": asset_id,
        "type": "figure",
        "figure_number": figure_number,
        "figure_caption": figure_caption,
        "page": page,
        "bbox": [0.0, y, 100.0, y + 50.0],
    }


class BuildChunkSubIndexTests(unittest.TestCase):
    def test_ref_sub_only_gets_explicitly_cited_asset(self) -> None:
        text = "焊枪喷嘴蹭着工件（如图5-1）。查看电弧跟踪模式设置。"
        assets = [
            _asset("a1", figure_number="5-1", figure_caption="图5-1", page=10, y=100.0),
            _asset("a2", figure_number="5-2", figure_caption="图5-2 电弧跟踪模式设置", page=10, y=200.0),
        ]

        subs = build_chunk_sub_index(text, assets)
        ref_sub = next(sub for sub in subs if sub.get("kind") == "ref")

        self.assertEqual(ref_sub["asset_ids"], ["a1"])
        self.assertNotIn("a2", ref_sub["asset_ids"])

    def test_unmatched_in_text_gap_becomes_gap_sub(self) -> None:
        text = "焊枪喷嘴蹭着工件（如图5-1）。查看电弧跟踪模式设置。"
        assets = [
            _asset("a1", figure_number="5-1", page=10, y=100.0),
            _asset("a2", figure_number="5-2", figure_caption="图5-2 电弧跟踪模式设置", page=10, y=200.0),
        ]

        subs = build_chunk_sub_index(text, assets)
        gap_subs = [sub for sub in subs if sub.get("kind") == "gap" and sub.get("text")]

        self.assertEqual(len(gap_subs), 1)
        self.assertIn("电弧跟踪模式", gap_subs[0]["text"])
        self.assertEqual(gap_subs[0]["asset_ids"], ["a2"])

    def test_empty_gap_attaches_unmatched_to_nearest_ref_sub(self) -> None:
        text = "如图5-1所示。如图5-3所示。"
        assets = [
            _asset("a1", figure_number="5-1", page=10, y=100.0),
            _asset("a2", figure_number="5-2", page=10, y=150.0),
            _asset("a3", figure_number="5-3", page=10, y=300.0),
        ]

        subs = build_chunk_sub_index(text, assets)
        first_ref = next(sub for sub in subs if sub.get("kind") == "ref" and "5-1" in sub["figure_numbers"])
        second_ref = next(sub for sub in subs if sub.get("kind") == "ref" and "5-3" in sub["figure_numbers"])

        self.assertIn("a2", first_ref["asset_ids"])
        self.assertNotIn("a2", second_ref["asset_ids"])
        self.assertFalse(any(sub.get("text") for sub in subs if sub.get("kind") == "gap"))

    def test_no_ref_sentences_keeps_caption_only_sub(self) -> None:
        assets = [_asset("a1", figure_number="5-2", figure_caption="图5-2", page=3, y=10.0)]
        subs = build_chunk_sub_index("只有正文，没有图引用。", assets)

        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["asset_ids"], ["a1"])
        self.assertEqual(subs[0]["text"], "")


if __name__ == "__main__":
    unittest.main()
