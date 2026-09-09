from pathlib import Path

from app.llm import LLMClient
from app.services.prompt_utils import ensure_string_list, load_prompt, parse_json_response
from app.services.workflow_types import JDAnalysisResult


class JDAnalyzer:
    """Parse a job description into structured fields for later workflow steps."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()
        self.prompt_dir = Path(__file__).resolve().parents[2] / "prompts"

    def analyze(self, job_description: str) -> JDAnalysisResult:
        system_prompt = load_prompt(self.prompt_dir, "jd_analysis_system.txt")
        user_template = load_prompt(self.prompt_dir, "jd_analysis_user.txt")
        user_prompt = user_template.format(job_description=job_description.strip())

        response_text = self.llm_client.chat(system_prompt, user_prompt)
        parsed = parse_json_response(response_text)

        return JDAnalysisResult(
            responsibilities=ensure_string_list(parsed, "responsibilities"),
            required_skills=ensure_string_list(parsed, "required_skills"),
            bonus_points=ensure_string_list(parsed, "bonus_points"),
            ai_keywords=ensure_string_list(parsed, "ai_keywords"),
            interview_focus=ensure_string_list(parsed, "interview_focus"),
            raw_output=response_text,
        )
