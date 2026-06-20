import unittest
from unittest.mock import patch

from app.config import Settings
from app.services.answer_alignment import (
    _best_sentence_for_sub,
    build_aligned_embeds,
    sentence_has_markdown_table,
    should_skip_table_embed,
    split_answer_sentences,
)


class SentenceHasMarkdownTableTests(unittest.TestCase):
    def test_detects_pipe_rows(self) -> None:
        text = "| 项目 | 值 |\n| --- | --- |\n| 电压 | 220V |"
        self.assertTrue(sentence_has_markdown_table(text))

    def test_rejects_single_pipe_line(self) -> None:
        self.assertFalse(sentence_has_markdown_table("| 仅一行 |"))

    def test_rejects_plain_text(self) -> None:
        self.assertFalse(sentence_has_markdown_table("额定电压 220V。"))


class ShouldSkipTableEmbedTests(unittest.TestCase):
    def test_skips_when_table_is_in_lookback_window(self) -> None:
        sentences = split_answer_sentences(
            "| 项目 | 值 |\n| --- | --- |\n| 电压 | 220V |\n\n详见上表。[1]"
        )
        settings = Settings(embed_skip_table_when_answer_has_markdown=True, embed_skip_table_lookback=2)
        asset = {"type": "table", "asset_id": "table-1"}

        self.assertTrue(
            should_skip_table_embed(
                asset,
                ref=1,
                sentence_index=1,
                sentences=sentences,
                settings=settings,
            )
        )

    def test_does_not_skip_without_markdown_table(self) -> None:
        sentences = split_answer_sentences("额定电压 220V。[1]")
        settings = Settings(embed_skip_table_when_answer_has_markdown=True)
        asset = {"type": "table", "asset_id": "table-1"}

        self.assertFalse(
            should_skip_table_embed(
                asset,
                ref=1,
                sentence_index=0,
                sentences=sentences,
                settings=settings,
            )
        )

    def test_does_not_skip_figures(self) -> None:
        sentences = split_answer_sentences("| A | B |\n|---|---|[1]")
        settings = Settings(embed_skip_table_when_answer_has_markdown=True)
        asset = {"type": "figure", "asset_id": "fig-1"}

        self.assertFalse(
            should_skip_table_embed(
                asset,
                ref=1,
                sentence_index=0,
                sentences=sentences,
                settings=settings,
            )
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

    def test_does_not_split_numbered_list_markers(self) -> None:
        answer = (
            "1. 接通伺服电源（回放模式下）：\n"
            "   - 按下示教器上的【伺服准备】键 [1]。\n"
            "2. 启动执行：\n"
            "   - 按下【启动】键 [3]。"
        )

        sentences = split_answer_sentences(answer)

        self.assertEqual(len(sentences), 2)
        self.assertIn("1. 接通伺服电源", sentences[0]["raw_text"])
        self.assertEqual(sentences[0]["citation_refs"], [1])
        self.assertIn("2. 启动执行", sentences[1]["raw_text"])
        self.assertEqual(sentences[1]["citation_refs"], [3])
        self.assertTrue(sentences[0]["raw_text"].startswith("1. 接通"))
        self.assertTrue(sentences[1]["raw_text"].startswith("2. 启动"))


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

    def _table_chunk(self, *, asset_id: str, sub_text: str) -> dict:
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
                    "type": "table",
                    "figure_number": "3-1",
                    "figure_caption": "表3-1",
                    "page": 10,
                    "bbox": [0.0, 0.0, 100.0, 100.0],
                }
            ],
        }

    def test_skips_table_embed_when_answer_already_has_markdown_table(self) -> None:
        answer = (
            "| 项目 | 值 |\n"
            "| --- | --- |\n"
            "| 电压 | 220V |\n\n"
            "详见上表。[1]"
        )
        chunk = self._table_chunk(
            asset_id="table-1",
            sub_text="表3-1 额定参数 | 项目 | 值 |",
        )
        vectors = {
            "详见上表。": [1.0, 0.0],
            "表3-1 额定参数 | 项目 | 值 |": [0.95, 0.05],
        }

        class _FakeEmbedding:
            def embed_queries(self, texts: list[str]) -> list[list[float]]:
                return [vectors.get(text, [0.0, 1.0]) for text in texts]

        with patch(
            "app.services.answer_alignment.get_embedding_service",
            return_value=_FakeEmbedding(),
        ):
            embeds = build_aligned_embeds(answer, [chunk])

        self.assertEqual(embeds, [])

    def test_keeps_table_embed_when_answer_has_no_markdown_table(self) -> None:
        answer = "额定电压 220V，详见手册。[1]"
        chunk = self._table_chunk(
            asset_id="table-1",
            sub_text="表3-1 额定电压 220V",
        )
        vectors = {
            "额定电压 220V，详见手册。": [1.0, 0.0],
            "表3-1 额定电压 220V": [0.95, 0.05],
        }

        class _FakeEmbedding:
            def embed_queries(self, texts: list[str]) -> list[list[float]]:
                return [vectors.get(text, [0.0, 1.0]) for text in texts]

        with patch(
            "app.services.answer_alignment.get_embedding_service",
            return_value=_FakeEmbedding(),
        ):
            embeds = build_aligned_embeds(answer, [chunk])

        self.assertEqual(len(embeds), 1)
        self.assertEqual(embeds[0]["asset_id"], "table-1")
        self.assertEqual(embeds[0]["type"], "table")

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
