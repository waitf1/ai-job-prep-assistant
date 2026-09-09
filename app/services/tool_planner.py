from pathlib import Path

from app.llm.client import LLMClient
from app.services.prompt_utils import load_prompt, parse_json_response
from app.services.workflow_types import JDAnalysisResult, PlannerDecisionResult
from app.tools.knowledge_base_tools import SearchProjectKnowledgeBaseTool


class ToolPlanner:
    """Let the model decide whether retrieval is needed for this run."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()
        self.prompt_dir = Path(__file__).resolve().parents[2] / "prompts"

    def analyze(
        self,
        resume_text: str,
        job_description: str,
        jd_analysis: JDAnalysisResult,
        mode_name: str,
        knowledge_base_available: bool,
        search_tool: SearchProjectKnowledgeBaseTool | None,
    ) -> PlannerDecisionResult:
        if not knowledge_base_available or search_tool is None:
            return PlannerDecisionResult(
                should_search=False,
                query="",
                reason="当前项目资料库不可用，跳过检索。",
                used_tool_call=False,
                raw_output="",
            )

        system_prompt = load_prompt(self.prompt_dir, "tool_planner_system.txt")
        user_template = load_prompt(self.prompt_dir, "tool_planner_user.txt")
        user_prompt = user_template.format(
            mode_name=mode_name,
            resume_text=resume_text.strip() or "当前未提供额外简历正文或补充说明。",
            job_description=job_description.strip(),
            jd_analysis=jd_analysis.to_prompt_text(),
            knowledge_base_status="可用，系统会自动筛选最相关的资料片段。",
        )

        response = self.llm_client.chat_with_tools(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            tools=[search_tool.to_openai_schema()],
        )

        if response.tool_calls:
            if len(response.tool_calls) != 1:
                raise ValueError("检索计划只能包含一次工具调用。")
            tool_call = response.tool_calls[0]
            if not isinstance(tool_call, dict) or tool_call.get("name") != search_tool.to_openai_schema()["function"]["name"]:
                raise ValueError("模型请求了未授权的检索工具。")
            arguments = tool_call.get("args") or {}
            if not arguments and isinstance(tool_call.get("arguments"), dict):
                arguments = tool_call["arguments"]
            if not isinstance(arguments, dict) or not isinstance(arguments.get("query", ""), str):
                raise ValueError("检索 query 必须是字符串。")
            query = arguments.get("query", "").strip()
            if not query:
                query = jd_analysis.as_query_text().strip() or job_description.strip()
            return PlannerDecisionResult(
                should_search=True,
                query=query,
                reason="模型判断当前分析需要从项目资料库补充项目经历证据。",
                used_tool_call=True,
                raw_output=response.content,
            )

        raw_output = response.content.strip()
        if raw_output:
            try:
                parsed = parse_json_response(raw_output)
                if type(parsed.get("use_search")) is not bool:
                    raise ValueError("use_search 必须为布尔值。")
                if not isinstance(parsed.get("query", ""), str):
                    raise ValueError("query 必须为字符串。")
                return PlannerDecisionResult(
                    should_search=parsed["use_search"],
                    query=str(parsed.get("query", "")).strip(),
                    reason=str(parsed.get("reason", "模型判断当前可跳过检索。")).strip(),
                    used_tool_call=False,
                    raw_output=raw_output,
                )
            except Exception:
                pass

        return PlannerDecisionResult(
            should_search=False,
            query="",
            reason=raw_output or "模型未调用检索工具，默认跳过资料库检索。",
            used_tool_call=False,
            raw_output=raw_output,
        )
