__all__ = [
    "DocumentParseError",
    "ChunkReviewer",
    "InterviewPreparer",
    "InterviewSession",
    "InterviewSessionService",
    "InterviewPrepResult",
    "JDAnalysisResult",
    "JDAnalyzer",
    "JobMatchAnalyzer",
    "JobPrepWorkflow",
    "MatchAnalysisResult",
    "ParsedDocument",
    "PlannerDecisionResult",
    "ResumeAdviceResult",
    "ResumeAdvisor",
    "SelectedResumeResult",
    "ToolPlanner",
    "WorkflowRunResult",
    "parse_document",
]


def __getattr__(name: str):
    if name in {"DocumentParseError", "ParsedDocument", "parse_document"}:
        from app.services.document_parser import DocumentParseError, ParsedDocument, parse_document

        mapping = {
            "DocumentParseError": DocumentParseError,
            "ParsedDocument": ParsedDocument,
            "parse_document": parse_document,
        }
        return mapping[name]

    if name == "JDAnalyzer":
        from app.services.jd_analyzer import JDAnalyzer

        return JDAnalyzer

    if name == "JobMatchAnalyzer":
        from app.services.match_analyzer import JobMatchAnalyzer

        return JobMatchAnalyzer

    if name == "ResumeAdvisor":
        from app.services.resume_advisor import ResumeAdvisor

        return ResumeAdvisor

    if name == "ChunkReviewer":
        from app.services.chunk_reviewer import ChunkReviewer

        return ChunkReviewer

    if name == "ToolPlanner":
        from app.services.tool_planner import ToolPlanner

        return ToolPlanner

    if name == "InterviewPreparer":
        from app.services.interview_preparer import InterviewPreparer

        return InterviewPreparer

    if name in {"InterviewSession", "InterviewSessionService"}:
        from app.services.interview_session import InterviewSession, InterviewSessionService

        return {
            "InterviewSession": InterviewSession,
            "InterviewSessionService": InterviewSessionService,
        }[name]

    if name == "JobPrepWorkflow":
        from app.services.job_prep_workflow import JobPrepWorkflow

        return JobPrepWorkflow

    if name in {
        "JDAnalysisResult",
        "MatchAnalysisResult",
        "PlannerDecisionResult",
        "ResumeAdviceResult",
        "SelectedResumeResult",
        "InterviewPrepResult",
        "WorkflowRunResult",
    }:
        from app.services.workflow_types import (
            InterviewPrepResult,
            JDAnalysisResult,
            MatchAnalysisResult,
            PlannerDecisionResult,
            ResumeAdviceResult,
            SelectedResumeResult,
            WorkflowRunResult,
        )

        mapping = {
            "JDAnalysisResult": JDAnalysisResult,
            "MatchAnalysisResult": MatchAnalysisResult,
            "PlannerDecisionResult": PlannerDecisionResult,
            "ResumeAdviceResult": ResumeAdviceResult,
            "SelectedResumeResult": SelectedResumeResult,
            "InterviewPrepResult": InterviewPrepResult,
            "WorkflowRunResult": WorkflowRunResult,
        }
        return mapping[name]

    raise AttributeError(f"module 'app.services' has no attribute {name!r}")
