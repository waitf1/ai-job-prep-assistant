from pathlib import Path

from app.llm import LLMClient
from app.services.prompt_utils import ensure_string_list, load_prompt, parse_json_response
from app.services.workflow_types import JDAnalysisResult, MatchAnalysisResult


class JobMatchAnalyzer:
    """Analyze job-match evidence and gaps for the workflow."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()
        self.prompt_dir = Path(__file__).resolve().parents[2] / "prompts"

    def analyze(
        self,
        resume_text: str,
        job_description: str,
        jd_analysis: JDAnalysisResult,
        retrieved_context: str = "",
    ) -> MatchAnalysisResult:
        system_prompt = load_prompt(self.prompt_dir, "match_analysis_system.txt")
        user_template = load_prompt(self.prompt_dir, "match_analysis_user.txt")
        user_prompt = user_template.format(
            resume_text=resume_text.strip(),
            job_description=job_description.strip(),
            jd_analysis=jd_analysis.to_prompt_text(),
            retrieved_context=retrieved_context.strip() or "当前未使用 RAG 检索上下文。",
        )
        response_text = self.llm_client.chat(system_prompt, user_prompt)
        parsed = parse_json_response(response_text)
        return MatchAnalysisResult(
            matched_points=ensure_string_list(parsed, "matched_points"),
            gaps=ensure_string_list(parsed, "gaps"),
            evidence_notes=ensure_string_list(parsed, "evidence_notes"),
            raw_output=response_text,
            citations=validate_citations(parsed.get("citations", []), resume_text, retrieved_context, len(parsed.get("matched_points", []))),
        )


def validate_citations(items, resume_text, retrieved_context, point_count):
    if not isinstance(items, list):
        raise ValueError("citations 必须为列表。")
    sources = {"resume": resume_text, "project": retrieved_context}
    result = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("引用必须为对象。")
        point = item.get("point_index")
        source = item.get("source")
        quote = item.get("quote")
        if type(point) is not int or not 0 <= point < point_count or source not in sources:
            raise ValueError("引用的匹配点或来源无效。")
        if not isinstance(quote, str) or len(quote.strip()) < 8:
            raise ValueError("引用须包含至少 8 个字符的原文。")
        quote = quote.strip()
        start = sources[source].find(quote)
        result.append({"point_index": point, "source": source, "quote": quote,
                       "verified": start >= 0, "start": start})
    return result
