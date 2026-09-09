from pathlib import Path

from app.llm import LLMClient
from app.services.prompt_utils import ensure_string_list, load_prompt, parse_json_response
from app.services.workflow_types import (
    InterviewPrepResult,
    JDAnalysisResult,
    MatchAnalysisResult,
)


class InterviewPreparer:
    """Generate interview questions and short-term preparation advice."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()
        self.prompt_dir = Path(__file__).resolve().parents[2] / "prompts"

    def analyze(
        self,
        resume_text: str,
        jd_analysis: JDAnalysisResult,
        match_analysis: MatchAnalysisResult,
        retrieved_context: str = "",
    ) -> InterviewPrepResult:
        system_prompt = load_prompt(self.prompt_dir, "interview_prep_system.txt")
        user_template = load_prompt(self.prompt_dir, "interview_prep_user.txt")
        user_prompt = user_template.format(
            resume_text=resume_text.strip(),
            jd_analysis=jd_analysis.to_prompt_text(),
            match_analysis=match_analysis.to_prompt_text(),
            retrieved_context=retrieved_context.strip() or "当前未使用 RAG 检索上下文。",
        )
        response_text = self.llm_client.chat(system_prompt, user_prompt)
        parsed = parse_json_response(response_text)
        return InterviewPrepResult(
            questions=ensure_string_list(parsed, "questions"),
            short_term_focus=ensure_string_list(parsed, "short_term_focus"),
            raw_output=response_text,
        )
