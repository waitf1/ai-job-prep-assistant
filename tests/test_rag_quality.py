import unittest

from app.rag.chunking import split_text
from app.rag.vector_store import (
    DEFAULT_DISTANCE_GAP_THRESHOLD,
    DEFAULT_MAX_RETRIEVAL_DISTANCE,
    DEFAULT_MAX_SELECTED_CHUNKS,
    RetrievedChunk,
    filter_retrieved_chunks,
    select_retrieved_chunks,
    ProfileKnowledgeBase,
)
from app.services.chunk_reviewer import ChunkReviewResult
from app.services.document_parser import ParsedDocument


def make_chunk(distance: float | None) -> RetrievedChunk:
    return RetrievedChunk(
        text=f"距离为 {distance} 的片段",
        source="test.txt",
        chunk_index=0,
        distance=distance,
    )


class RetrievedChunkFilterTests(unittest.TestCase):
    def test_keeps_chunks_within_default_distance(self) -> None:
        chunks = [make_chunk(0.12), make_chunk(DEFAULT_MAX_RETRIEVAL_DISTANCE)]

        result = filter_retrieved_chunks(chunks)

        self.assertEqual(result, chunks)

    def test_filters_chunks_above_maximum_distance(self) -> None:
        relevant_chunk = make_chunk(0.12)
        irrelevant_chunk = make_chunk(DEFAULT_MAX_RETRIEVAL_DISTANCE + 0.01)

        result = filter_retrieved_chunks([relevant_chunk, irrelevant_chunk])

        self.assertEqual(result, [relevant_chunk])

    def test_keeps_chunks_without_distance_for_backward_compatibility(self) -> None:
        chunk_without_distance = make_chunk(None)

        result = filter_retrieved_chunks([chunk_without_distance])

        self.assertEqual(result, [chunk_without_distance])

    def test_handles_empty_results(self) -> None:
        self.assertEqual(filter_retrieved_chunks([]), [])

    def test_stops_selecting_at_clear_distance_gap(self) -> None:
        best_chunk = make_chunk(0.12)
        second_chunk = make_chunk(0.20)
        weaker_chunk = make_chunk(0.20 + DEFAULT_DISTANCE_GAP_THRESHOLD)

        result = select_retrieved_chunks([best_chunk, second_chunk, weaker_chunk])

        self.assertEqual(result.selected_chunks, [best_chunk, second_chunk])
        self.assertEqual(result.gap_truncated_chunks, [weaker_chunk])

    def test_limits_selected_chunks_when_all_candidates_are_similar(self) -> None:
        chunks = [make_chunk(0.10 + index * 0.01) for index in range(7)]

        result = select_retrieved_chunks(chunks)

        self.assertEqual(len(result.selected_chunks), DEFAULT_MAX_SELECTED_CHUNKS)
        self.assertEqual(len(result.gap_truncated_chunks), 2)


class KnowledgeBaseResetTests(unittest.TestCase):
    def test_reset_deletes_collection_configuration(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.deleted_name = ""

            def delete_collection(self, name: str) -> None:
                self.deleted_name = name

        knowledge_base = ProfileKnowledgeBase(collection_name="project_documents")
        client = FakeClient()
        knowledge_base.client = client
        knowledge_base.collection = object()
        knowledge_base.embedding_function = object()

        knowledge_base.reset()

        self.assertEqual(client.deleted_name, "project_documents")
        self.assertIsNone(knowledge_base.collection)
        self.assertIsNone(knowledge_base.embedding_function)


class BatchIngestionTests(unittest.TestCase):
    def test_reviews_chunks_in_batches_and_reports_progress(self) -> None:
        class FakeCollection:
            def __init__(self) -> None:
                self.added_documents: list[str] = []
                self.metadatas: list[dict] = []

            def get(self, include=None):
                return {"metadatas": []}

            def add(self, ids, documents, metadatas) -> None:
                self.added_documents.extend(documents)
                self.metadatas.extend(metadatas)

        class FakeReviewer:
            def __init__(self) -> None:
                self.batch_sizes: list[int] = []

            def review_batch(self, chunks):
                self.batch_sizes.append(len(chunks))
                return [
                    ChunkReviewResult(
                        keep=chunk.index != 1,
                        content_type="project" if chunk.index != 1 else "other",
                        reason="测试结果",
                        confidence=1.0,
                    )
                    for chunk in chunks
                ]

        collection = FakeCollection()
        reviewer = FakeReviewer()
        knowledge_base = ProfileKnowledgeBase()
        knowledge_base.client = object()
        knowledge_base.collection = collection
        knowledge_base.embedding_function = object()
        progress: list[tuple[int, int]] = []
        document = ParsedDocument(
            file_name="project.md",
            file_type="md",
            text="\n\n".join(f"# 模块 {index}\n实现内容 {index}" for index in range(6)),
        )

        result = knowledge_base.add_documents(
            [document],
            reviewer=reviewer,
            on_review_progress=lambda completed, total: progress.append((completed, total)),
        )

        self.assertEqual(reviewer.batch_sizes, [5, 1])
        self.assertEqual(progress, [(1, 2), (2, 2)])
        self.assertEqual(result.ai_reviewed_chunks, 6)
        self.assertEqual(result.ai_excluded_chunks, 1)
        self.assertEqual(result.added_chunks, 5)
        self.assertEqual(len(collection.added_documents), 5)


class StructuralChunkingTests(unittest.TestCase):
    def test_keeps_markdown_section_context(self) -> None:
        chunks = split_text("# 项目经历\n\n实现 RAG 检索。\n\n# 技术栈\n\n使用 Python 和 Streamlit。")

        self.assertEqual([chunk.section_title for chunk in chunks], ["项目经历", "技术栈"])
        self.assertTrue(chunks[0].text.startswith("【项目经历】"))
        self.assertTrue(chunks[1].text.startswith("【技术栈】"))

    def test_recognizes_pdf_page_markers(self) -> None:
        chunks = split_text("--- Page 2 ---\n页面中的项目说明。\n\n--- Page 3 ---\n页面中的技术细节。")

        self.assertEqual([chunk.section_title for chunk in chunks], ["第 2 页", "第 3 页"])

    def test_splits_long_paragraph_at_sentence_boundaries(self) -> None:
        sentence = "这是一个用于验证按句子切分的长段落。"
        chunks = split_text(sentence * 80, chunk_size=240)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk.text) <= 240 for chunk in chunks))
        self.assertTrue(all(chunk.text.startswith("【文档内容】") for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
