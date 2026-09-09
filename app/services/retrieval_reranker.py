from dataclasses import dataclass
from pathlib import Path

from app.llm import LLMClient
from app.rag.vector_store import RetrievedChunk
from app.services.prompt_utils import load_prompt, parse_json_response
from app.services.workflow_types import JDAnalysisResult


@dataclass(frozen=True)
class RetrievalRerankResult:
    selected_chunks: list[RetrievedChunk]
    excluded_chunks: list[RetrievedChunk]
    reason: str
    review_failed: bool = False


class RetrievalReranker:
    """Ask the model to select project evidence from rule-filtered candidates."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()
        self.prompt_dir = Path(__file__).resolve().parents[2] / "prompts"

    def rerank(
        self,
        chunks: list[RetrievedChunk],
        jd_analysis: JDAnalysisResult,
        resume_text: str,
        max_chunks: int,
        fallback_chunks: list[RetrievedChunk],
    ) -> RetrievalRerankResult:
        if not chunks:
            return RetrievalRerankResult([], [], "没有通过规则过滤的候选片段。")

        try:
            response = self.llm_client.chat(
                load_prompt(self.prompt_dir, "retrieval_rerank_system.txt"),
                load_prompt(self.prompt_dir, "retrieval_rerank_user.txt").format(
                    jd_analysis=jd_analysis.to_prompt_text(),
                    resume_text=resume_text[:6000],
                    max_chunks=max_chunks,
                    candidates=self._format_candidates(chunks),
                ),
            )
            parsed = parse_json_response(response)
            raw_indexes = parsed.get("selected_indexes", [])
            if not isinstance(raw_indexes, list):
                raise ValueError("selected_indexes 必须是数组。")

            selected_indexes: list[int] = []
            for value in raw_indexes:
                index = int(value)
                if index < 0 or index >= len(chunks) or index in selected_indexes:
                    continue
                selected_indexes.append(index)
                if len(selected_indexes) >= max_chunks:
                    break

            selected_chunks = [chunks[index] for index in selected_indexes]
            excluded_chunks = [
                chunk for index, chunk in enumerate(chunks) if index not in selected_indexes
            ]
            return RetrievalRerankResult(
                selected_chunks=selected_chunks,
                excluded_chunks=excluded_chunks,
                reason=str(parsed.get("reason", "模型未提供选择说明。")).strip(),
            )
        except Exception as exc:
            return RetrievalRerankResult(
                selected_chunks=fallback_chunks,
                excluded_chunks=[chunk for chunk in chunks if chunk not in fallback_chunks],
                reason=f"AI 重排序失败，已回退到规则选片：{exc}",
                review_failed=True,
            )

    @staticmethod
    def _format_candidates(chunks: list[RetrievedChunk]) -> str:
        parts = []
        for index, chunk in enumerate(chunks):
            distance = f"{chunk.distance:.4f}" if chunk.distance is not None else "未知"
            parts.append(
                "\n".join(
                    [
                        f"[候选 {index}]",
                        f"来源：{chunk.source}；章节：{chunk.section_title}；向量距离：{distance}",
                        f"内容：{chunk.text[:1600]}",
                    ]
                )
            )
        return "\n\n".join(parts)
