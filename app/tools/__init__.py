__all__ = [
    "AnalyzeJobDescriptionTool",
    "GenerateInterviewQuestionsTool",
    "GenerateResumeAdviceTool",
    "ParseDocumentTool",
    "SearchProfileKnowledgeBaseTool",
    "SearchProjectKnowledgeBaseTool",
    "ToolCallRecord",
    "ToolExecutionContext",
    "ToolResult",
]


def __getattr__(name: str):
    if name in {"ToolCallRecord", "ToolExecutionContext", "ToolResult"}:
        from app.tools.tool_types import ToolCallRecord, ToolExecutionContext, ToolResult

        mapping = {
            "ToolCallRecord": ToolCallRecord,
            "ToolExecutionContext": ToolExecutionContext,
            "ToolResult": ToolResult,
        }
        return mapping[name]

    if name == "ParseDocumentTool":
        from app.tools.document_tools import ParseDocumentTool

        return ParseDocumentTool

    if name in {"SearchProfileKnowledgeBaseTool", "SearchProjectKnowledgeBaseTool"}:
        from app.tools.knowledge_base_tools import (
            SearchProfileKnowledgeBaseTool,
            SearchProjectKnowledgeBaseTool,
        )

        return {
            "SearchProfileKnowledgeBaseTool": SearchProfileKnowledgeBaseTool,
            "SearchProjectKnowledgeBaseTool": SearchProjectKnowledgeBaseTool,
        }[name]

    if name in {
        "AnalyzeJobDescriptionTool",
        "GenerateResumeAdviceTool",
        "GenerateInterviewQuestionsTool",
    }:
        from app.tools.analysis_tools import (
            AnalyzeJobDescriptionTool,
            GenerateInterviewQuestionsTool,
            GenerateResumeAdviceTool,
        )

        mapping = {
            "AnalyzeJobDescriptionTool": AnalyzeJobDescriptionTool,
            "GenerateResumeAdviceTool": GenerateResumeAdviceTool,
            "GenerateInterviewQuestionsTool": GenerateInterviewQuestionsTool,
        }
        return mapping[name]

    raise AttributeError(f"module 'app.tools' has no attribute {name!r}")
