import unittest

from app.rag.vector_store import RetrievedChunk
from app.services.retrieval_reranker import RetrievalReranker
from app.services.workflow_types import JDAnalysisResult


class FakeRerankLLM:
    def __init__(self, response: str | Exception) -> None:
        self.response = response

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def make_jd() -> JDAnalysisResult:
    return JDAnalysisResult(
        responsibilities=["开发 RAG 应用"],
        required_skills=["Python"],
        bonus_points=[],
        ai_keywords=["大模型"],
        interview_focus=[],
        raw_output="",
    )


def make_chunk(index: int) -> RetrievedChunk:
    return RetrievedChunk(
        text=f"项目证据 {index}",
        source="project.txt",
        chunk_index=index,
        distance=0.1 + index * 0.1,
    )


class RetrievalRerankerTests(unittest.TestCase):
    def test_uses_model_selected_indexes_only(self) -> None:
        chunks = [make_chunk(index) for index in range(3)]
        reranker = RetrievalReranker(
            FakeRerankLLM('{"selected_indexes":[2,0,99,0],"reason":"匹配岗位"}')
        )

        result = reranker.rerank(
            chunks=chunks,
            jd_analysis=make_jd(),
            resume_text="简历内容",
            max_chunks=2,
            fallback_chunks=[chunks[0]],
        )

        self.assertEqual(result.selected_chunks, [chunks[2], chunks[0]])
        self.assertEqual(result.excluded_chunks, [chunks[1]])
        self.assertFalse(result.review_failed)

    def test_falls_back_to_rule_selection_on_model_failure(self) -> None:
        chunks = [make_chunk(index) for index in range(3)]
        reranker = RetrievalReranker(FakeRerankLLM(RuntimeError("offline")))

        result = reranker.rerank(
            chunks=chunks,
            jd_analysis=make_jd(),
            resume_text="简历内容",
            max_chunks=2,
            fallback_chunks=[chunks[0]],
        )

        self.assertEqual(result.selected_chunks, [chunks[0]])
        self.assertEqual(result.excluded_chunks, [chunks[1], chunks[2]])
        self.assertTrue(result.review_failed)


if __name__ == "__main__":
    unittest.main()
