import unittest

from app.rag.chunking import TextChunk, split_text
from app.rag.document_cleaner import clean_project_document, is_high_confidence_noise
from app.services.chunk_reviewer import ChunkReviewer


class FakeReviewLLM:
    def __init__(self, response: str | Exception) -> None:
        self.response = response

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class DocumentCleanerTests(unittest.TestCase):
    def test_removes_format_noise_and_reference_section(self) -> None:
        text = """
--- Page 1 ---
课程设计报告
--------------------
1
项目目标
实现一个停车管理系统。

--- Page 2 ---
课程设计报告
参考文献
[1] 张三. 基于深度学习的停车检测[J]. 2022.
[2] 李四. Web 系统设计[M]. 2021.
"""

        result = clean_project_document(text)

        self.assertIn("实现一个停车管理系统", result.text)
        self.assertNotIn("深度学习的停车检测", result.text)
        self.assertNotIn("--------------------", result.text)
        self.assertGreaterEqual(result.stats.excluded_section_count, 1)
        self.assertGreaterEqual(result.stats.removed_repeated_header_footer_count, 1)

    def test_detects_reference_text_even_with_low_vector_distance(self) -> None:
        reference = "[1] 张三. 检索增强生成方法研究[J]. 2022.\n[2] 李四. 大模型应用开发[M]. 2023."

        self.assertTrue(is_high_confidence_noise(reference, "第 15 页"))

    def test_removes_consecutive_pdf_format_fragments(self) -> None:
        text = "--- Page 1 ---\n项\n目\n报\n告\n书\n\n项目正文内容完整保留。"

        result = clean_project_document(text)

        self.assertNotIn("项\n目\n报\n告\n书", result.text)
        self.assertIn("项目正文内容完整保留", result.text)

    def test_project_section_splits_multiple_dated_projects(self) -> None:
        text = """
# 项目经历

2023.01-2023.06 AI 岗位助手
使用 Python 实现 RAG。

2024.01-2024.06 停车管理系统
使用 Flask 实现后端。
"""

        chunks = split_text(text, chunk_size=240)

        self.assertEqual(len(chunks), 2)
        self.assertTrue(all(chunk.content_type == "project" for chunk in chunks))


class ChunkReviewerTests(unittest.TestCase):
    def test_ai_reviews_rule_classified_body_chunk(self) -> None:
        reviewer = ChunkReviewer(
            llm_client=FakeReviewLLM(
                '{"reviews":[{"index":0,"content_type":"other","keep":false,"reason":"泛泛理论介绍","confidence":0.91}]}'
            )
        )
        chunk = TextChunk(
            text="大模型技术具有广阔的发展前景。" * 10,
            index=0,
            content_type="body",
            cleaning_status="clean",
        )

        result = reviewer.review(chunk)

        self.assertFalse(result.keep)
        self.assertEqual(result.content_type, "other")

    def test_ai_can_exclude_ambiguous_noise(self) -> None:
        reviewer = ChunkReviewer(
            llm_client=FakeReviewLLM(
                '{"reviews":[{"index":0,"content_type":"reference","keep":false,"reason":"文献列表","confidence":0.98}]}'
            )
        )
        chunk = TextChunk(
            text="候选模糊内容" * 20,
            index=0,
            cleaning_status="review_required",
        )

        result = reviewer.review(chunk)

        self.assertFalse(result.keep)
        self.assertEqual(result.content_type, "reference")

    def test_ai_batch_reviews_every_chunk_in_order(self) -> None:
        reviewer = ChunkReviewer(
            llm_client=FakeReviewLLM(
                '{"reviews":['
                '{"index":0,"content_type":"project","keep":true,"reason":"项目实现","confidence":0.95},'
                '{"index":1,"content_type":"other","keep":false,"reason":"泛泛背景","confidence":0.88}'
                ']}'
            )
        )
        chunks = [
            TextChunk(text="实现 RAG 检索流程。", index=0),
            TextChunk(text="人工智能发展迅速。", index=1),
        ]

        results = reviewer.review_batch(chunks)

        self.assertTrue(results[0].keep)
        self.assertFalse(results[1].keep)

    def test_ai_failure_keeps_possible_body(self) -> None:
        reviewer = ChunkReviewer(llm_client=FakeReviewLLM(RuntimeError("offline")))
        chunk = TextChunk(
            text="可能属于项目正文的模糊内容" * 10,
            index=0,
            cleaning_status="review_required",
        )

        result = reviewer.review(chunk)

        self.assertTrue(result.keep)
        self.assertTrue(result.review_failed)

    def test_incomplete_batch_result_falls_back_for_the_whole_batch(self) -> None:
        reviewer = ChunkReviewer(
            llm_client=FakeReviewLLM(
                '{"reviews":[{"index":0,"content_type":"project","keep":true,"reason":"项目实现","confidence":0.95}]}'
            )
        )
        chunks = [
            TextChunk(text="实现 RAG 检索流程。", index=0),
            TextChunk(text="实现向量检索。", index=1),
        ]

        results = reviewer.review_batch(chunks)

        self.assertTrue(all(result.keep for result in results))
        self.assertTrue(all(result.review_failed for result in results))


if __name__ == "__main__":
    unittest.main()
