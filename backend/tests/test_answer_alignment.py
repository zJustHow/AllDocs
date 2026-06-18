import unittest
from unittest.mock import patch

from app.services.answer_alignment import (
    _best_sentence_for_sub,
    build_aligned_embeds,
    split_answer_sentences,
)


class SplitAnswerSentencesTests(unittest.TestCase):
    def test_splits_on_chinese_and_english_punctuation(self) -> None:
        answer = (
            "确认精度异常表现。[1][2]\n"
            "第一步：机器人轴零点标定.[1]\n"
            "Check TCP settings: verify the tool.[3]"
        )

        sentences = split_answer_sentences(answer)

        self.assertEqual(len(sentences), 3)
        self.assertEqual(sentences[0]["sentence_index"], 0)
        self.assertEqual(sentences[0]["citation_refs"], [1, 2])
        self.assertEqual(sentences[1]["citation_refs"], [1])
        self.assertEqual(sentences[2]["citation_refs"], [3])
        self.assertIn("Check TCP settings", sentences[2]["text"])

    def test_keeps_single_sentence_without_boundary(self) -> None:
        sentences = split_answer_sentences("仅有一句话带引用[1]")

        self.assertEqual(len(sentences), 1)
        self.assertEqual(sentences[0]["citation_refs"], [1])


class BuildAlignedEmbedsTests(unittest.TestCase):
    def _chunk(
        self,
        *,
        asset_id: str,
        sub_text: str,
        figure_number: str = "1-28",
    ) -> dict:
        return {
            "document_id": "doc-1",
            "document_name": "手册",
            "page": 10,
            "text": sub_text,
            "sub_index": [
                {
                    "kind": "ref",
                    "text": sub_text,
                    "index_text": sub_text,
                    "asset_ids": [asset_id],
                }
            ],
            "assets": [
                {
                    "asset_id": asset_id,
                    "type": "figure",
                    "figure_number": figure_number,
                    "figure_caption": f"图{figure_number}",
                    "page": 10,
                    "bbox": [0.0, 0.0, 100.0, 100.0],
                }
            ],
        }

    def test_places_embed_on_best_matching_cited_sentence(self) -> None:
        answer = (
            "确认精度异常表现。[1][2]\n"
            "第一步：机器人轴零点标定。[1]"
        )
        chunk_offset = self._chunk(
            asset_id="asset-offset",
            sub_text="设备精度异常导致偏焊。",
            figure_number="27",
        )
        chunk_zero = self._chunk(
            asset_id="asset-zero",
            sub_text="参考图1-28进行机器人轴零点标定。",
            figure_number="1-28",
        )

        vectors = {
            "确认精度异常表现。": [1.0, 0.0, 0.0],
            "第一步：机器人轴零点标定。": [0.0, 1.0, 0.0],
            "设备精度异常导致偏焊。": [0.95, 0.05, 0.0],
            "参考图1-28进行机器人轴零点标定。": [0.05, 0.95, 0.0],
        }

        class _FakeEmbedding:
            def embed_queries(self, texts: list[str]) -> list[list[float]]:
                return [vectors[text] for text in texts]

        with patch(
            "app.services.answer_alignment.get_embedding_service",
            return_value=_FakeEmbedding(),
        ):
            embeds = build_aligned_embeds(
                answer,
                [chunk_zero, chunk_offset],
            )

        by_asset = {item["asset_id"]: item for item in embeds}
        self.assertEqual(by_asset["asset-offset"]["sentence_index"], 0)
        self.assertEqual(by_asset["asset-offset"]["ref"], 2)
        self.assertEqual(by_asset["asset-zero"]["sentence_index"], 1)
        self.assertEqual(by_asset["asset-zero"]["ref"], 1)


class BestSentenceForSubTests(unittest.TestCase):
    def test_only_considers_sentences_with_matching_ref(self) -> None:
        sentences = [
            {
                "sentence_index": 0,
                "text": "概述问题。",
                "citation_refs": [2],
            },
            {
                "sentence_index": 1,
                "text": "执行零点标定。",
                "citation_refs": [1],
            },
        ]
        sub = {"index_text": "零点标定步骤", "asset_ids": ["a1"]}
        vectors = {
            "概述问题。": [1.0, 0.0],
            "执行零点标定。": [0.2, 0.9],
            "零点标定步骤": [0.1, 1.0],
        }

        best = _best_sentence_for_sub(sentences, 1, sub, vectors, threshold=0.4)

        self.assertEqual(best, 1)


if __name__ == "__main__":
    unittest.main()
