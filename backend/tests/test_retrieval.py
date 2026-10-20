from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.db.repository import configure_database, save_term_card
from backend.app.retrieval.service import search_documents, search_study_memory


class FakeEmbeddings:
    model_name = "fake-embeddings-v1"

    def __init__(self):
        self.document_calls = 0

    @staticmethod
    def _vector(text: str) -> list[float]:
        lowered = text.casefold()
        if "payload" in lowered or "항체" in lowered and "약물" in lowered:
            return [1.0, 0.0, 0.0]
        if "car-t" in lowered or "t세포" in lowered:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_calls += len(texts)
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class FailingEmbeddings(FakeEmbeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("synthetic embedding outage")


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="pharmamate-rag-test-")
        configure_database(Path(self.temp_dir.name))
        self.term = {
            "term": "항체-약물 접합체 (ADC)",
            "aliases": ["ADC"],
            "category": "Modality",
            "simple_definition": "항체에 항암 약물을 연결해 표적에 전달하는 치료",
            "article_context": "합성 테스트 기사",
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_semantic_paraphrase_returns_scoped_source(self):
        embedder = FakeEmbeddings()
        documents = [
            {
                "owner_id": "local", "source_type": "term", "source_id": "adc",
                "term_key": "adc", "title": "ADC", "content": "ADC antibody drug payload",
            },
            {
                "owner_id": "local", "source_type": "term", "source_id": "cart",
                "term_key": "cart", "title": "CAR-T", "content": "CAR-T T세포 치료",
            },
            {
                "owner_id": "private", "source_type": "note", "source_id": "hidden",
                "term_key": "hidden", "title": "private", "content": "항체 약물 payload",
            },
        ]
        result = search_documents(
            documents, "표적 세포에 독성 payload를 전달", embedding_provider=embedder, limit=3
        )
        self.assertEqual(result[0]["record_id"], "term:adc")
        self.assertTrue(all(row["owner_id"] == "local" for row in result))

    def test_persistent_vectors_are_reused_and_rebuilt_after_edit(self):
        save_term_card(self.term, "article-1", "https://example.test")
        embedder = FakeEmbeddings()
        first = search_study_memory("항체에 payload를 연결하는 치료", embedding_provider=embedder)
        self.assertEqual(first[0]["source_type"], "term")
        first_call_count = embedder.document_calls
        self.assertGreater(first_call_count, 0)

        search_study_memory("항체 약물 접합체", embedding_provider=embedder)
        self.assertEqual(embedder.document_calls, first_call_count)

        updated = {**self.term, "simple_definition": "업데이트된 ADC 치료 정의"}
        save_term_card(updated, "article-1", "https://example.test")
        search_study_memory("ADC", embedding_provider=embedder)
        self.assertGreater(embedder.document_calls, first_call_count)

    def test_unknown_owner_cannot_search_local_records(self):
        save_term_card(self.term, "article-1", "https://example.test")
        result = search_study_memory("ADC", owner_id="another-user", embedding_provider=FakeEmbeddings())
        self.assertEqual(result, [])

    def test_embedding_failure_uses_legacy_lexical_fallback(self):
        save_term_card(self.term, "article-1", "https://example.test")
        result = search_study_memory("ADC", embedding_provider=FailingEmbeddings())
        self.assertEqual(result[0]["term_key"], "adc")
        self.assertNotIn("embedding_json", result[0])


if __name__ == "__main__":
    unittest.main()
