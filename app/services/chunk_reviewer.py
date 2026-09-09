from dataclasses import dataclass
from pathlib import Path

from app.llm import LLMClient
from app.rag.chunking import TextChunk
from app.services.prompt_utils import load_prompt, parse_json_response


ALLOWED_CONTENT_TYPES = {
    "project",
    "method",
    "result",
    "body",
    "toc",
    "reference",
    "acknowledgement",
    "declaration",
    "noise",
    "other",
}
INDEXABLE_CONTENT_TYPES = {"project", "method", "result", "body"}


@dataclass(frozen=True)
class ChunkReviewResult:
    keep: bool
    content_type: str
    reason: str
    confidence: float
    review_failed: bool = False


class ChunkReviewer:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()
        self.prompt_dir = Path(__file__).resolve().parents[2] / "prompts"

    def review(self, chunk: TextChunk) -> ChunkReviewResult:
        return self.review_batch([chunk])[0]

    def review_batch(self, chunks: list[TextChunk]) -> list[ChunkReviewResult]:
        """Review a small, ordered group of chunks in one model request."""
        if not chunks:
            return []

        try:
            response = self.llm_client.chat(
                load_prompt(self.prompt_dir, "chunk_review_batch_system.txt"),
                load_prompt(self.prompt_dir, "chunk_review_batch_user.txt").format(
                    chunks=self._format_chunks(chunks),
                ),
            )
            parsed = parse_json_response(response)
            reviews = parsed.get("reviews")
            if not isinstance(reviews, list):
                raise ValueError("模型未返回 reviews 数组。")

            results_by_index: dict[int, ChunkReviewResult] = {}
            for raw_review in reviews:
                if not isinstance(raw_review, dict):
                    raise ValueError("reviews 中包含非对象结果。")
                index = raw_review.get("index")
                if not isinstance(index, int) or index < 0 or index >= len(chunks):
                    raise ValueError("模型返回了无效片段索引。")
                if index in results_by_index:
                    raise ValueError("模型重复返回了片段索引。")
                results_by_index[index] = self._parse_review(raw_review)

            expected_indexes = set(range(len(chunks)))
            if set(results_by_index) != expected_indexes:
                raise ValueError("模型未覆盖本批次的全部片段。")
            return [results_by_index[index] for index in range(len(chunks))]
        except Exception as exc:
            return [
                ChunkReviewResult(
                    keep=True,
                    content_type=chunk.content_type,
                    reason=f"AI 批量复核失败，已保守保留：{exc}",
                    confidence=0.0,
                    review_failed=True,
                )
                for chunk in chunks
            ]

    @staticmethod
    def _parse_review(raw_review: dict) -> ChunkReviewResult:
        content_type = str(raw_review.get("content_type", "other")).strip().lower()
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise ValueError(f"不支持的内容类型：{content_type}")
        confidence = max(0.0, min(1.0, float(raw_review.get("confidence", 0.0))))
        keep = raw_review.get("keep") is True and content_type in INDEXABLE_CONTENT_TYPES
        return ChunkReviewResult(
            keep=keep,
            content_type=content_type,
            reason=str(raw_review.get("reason", "模型未提供理由。")).strip(),
            confidence=confidence,
        )

    @staticmethod
    def _format_chunks(chunks: list[TextChunk]) -> str:
        parts = []
        for index, chunk in enumerate(chunks):
            parts.append(
                "\n".join(
                    [
                        f"[片段 {index}]",
                        f"章节：{chunk.section_title}",
                        f"规则初步分类：{chunk.content_type}",
                        "片段原文：",
                        chunk.text,
                    ]
                )
            )
        return "\n\n".join(parts)
