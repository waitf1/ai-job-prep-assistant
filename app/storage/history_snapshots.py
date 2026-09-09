"""Versioned, explicit snapshots. No clients, credentials or resume bodies."""

from app.services.match_analyzer import validate_citations

import hashlib
import json

from app.rag.vector_store import RetrievedChunk
from app.services.interview_session import InterviewFeedback, InterviewRound, InterviewSummary
from app.services.job_prep_workflow import format_retrieved_context
from app.services.workflow_types import (
    JDAnalysisResult, MatchAnalysisResult, ResumeAdviceResult, InterviewPrepResult,
    SelectedResumeResult, PlannerDecisionResult, WorkflowRunResult,
)
from app.tools.tool_types import ToolCallRecord


JD_FIELDS = ("responsibilities", "required_skills", "bonus_points", "ai_keywords", "interview_focus")
MATCH_FIELDS = ("matched_points", "gaps", "evidence_notes")
ADVICE_FIELDS = ("direct_edits", "future_edits")
PREP_FIELDS = ("questions", "short_term_focus")
CHUNK_FIELDS = ("text", "source", "chunk_index", "distance", "section_title", "content_type", "cleaning_status")
FEEDBACK_FIELDS = ("score", "strengths", "improvements", "answer_structure", "overall_feedback")
SUMMARY_FIELDS = ("strengths", "weaknesses", "answer_structure_advice", "practice_plan", "overall_summary")
RETRIEVAL_FIELDS = (
    "retrieval_query", "retrieval_candidate_limit", "max_retrieval_distance",
    "content_filtered_chunk_count", "filtered_chunk_count", "gap_truncated_chunk_count",
    "ai_rerank_excluded_chunk_count", "ai_rerank_reason", "ai_rerank_failed",
    "retrieval_status", "retrieval_message",
)


def _pick(value, names):
    return {name: getattr(value, name) for name in names} if value is not None else None


def _freeze(payload):
    return json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))


def resume_fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_analysis_snapshot(result, job_description, use_rag, resume_source_text):
    selected = result.selected_resume
    body = {
        "jd_analysis": _pick(result.jd_analysis, JD_FIELDS),
        "match_analysis": ({**_pick(result.match_analysis, MATCH_FIELDS), "citations": [c for c in result.match_analysis.citations if c["source"] == "project"]} if result.match_analysis else None),
        "resume_advice": _pick(result.resume_advice, ADVICE_FIELDS),
        "interview_prep": _pick(result.interview_prep, PREP_FIELDS),
        "selected_resume": _pick(selected, ("resume_id", "file_name", "selection_mode", "distance")),
        "retrieved_chunks": [_pick(chunk, CHUNK_FIELDS) for chunk in result.retrieved_chunks],
        "raw_retrieved_count": len(result.raw_retrieved_chunks),
        "planner_decision": _pick(result.planner_decision, ("should_search", "query", "reason", "used_tool_call")),
        # Omit raw tool inputs/outputs/errors, which may contain provider payloads.
        "tool_calls": [{"tool_name": call.tool_name, "success": call.success} for call in result.tool_calls],
        **_pick(result, RETRIEVAL_FIELDS),
    }
    return _freeze({
        "schema_version": 1, "job_description": job_description, "use_rag": use_rag,
        "resume_ref": {
            "resume_id": selected.resume_id if selected else None,
            "file_name": selected.file_name if selected else "临时简历",
            "fingerprint": resume_fingerprint(resume_source_text),
        },
        "result": body,
    })


def _check_version(payload):
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("历史记录版本不受支持。")


def _string_lists(data, names):
    values = {}
    for name in names:
        value = data[name]
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError("历史记录内容格式无效。")
        values[name] = value
    return values


def restore_analysis(payload):
    _check_version(payload)
    body = payload["result"]
    chunks = [RetrievedChunk(**{key: chunk[key] for key in CHUNK_FIELDS}) for chunk in body["retrieved_chunks"]]
    def section(name, cls, names):
        return cls(**_string_lists(body[name], names), raw_output="") if body.get(name) is not None else None
    selected = body.get("selected_resume")
    planner = body.get("planner_decision")
    return WorkflowRunResult(
        jd_analysis=JDAnalysisResult(**_string_lists(body["jd_analysis"], JD_FIELDS), raw_output=""),
        match_analysis=(MatchAnalysisResult(**_string_lists(body["match_analysis"], MATCH_FIELDS), raw_output="", citations=validate_citations(body["match_analysis"].get("citations", []), "", format_retrieved_context(chunks), len(body["match_analysis"]["matched_points"]))) if body.get("match_analysis") else None),
        resume_advice=section("resume_advice", ResumeAdviceResult, ADVICE_FIELDS),
        interview_prep=section("interview_prep", InterviewPrepResult, PREP_FIELDS),
        selected_resume=SelectedResumeResult(**selected) if selected else None,
        planner_decision=PlannerDecisionResult(**planner, raw_output="") if planner else None,
        retrieved_chunks=chunks, retrieved_context=format_retrieved_context(chunks),
        tool_calls=[ToolCallRecord(tool_name=call["tool_name"], success=call["success"], input_summary="历史仅保留执行状态。", output_summary="") for call in body["tool_calls"]],
        **{key: body[key] for key in RETRIEVAL_FIELDS},
    )


def make_interview_snapshot(session):
    if session.status != "completed" or session.summary is None or not session.rounds:
        raise ValueError("请先完成面试并生成复盘，再保存。")
    return _freeze({
        "schema_version": 1, "max_rounds": session.max_rounds,
        "question_modes": list(session.context.question_modes),
        "rounds": [{
            "question": item.question, "question_source": item.question_source, "answer": item.answer,
            "feedback": _pick(item.feedback, FEEDBACK_FIELDS),
        } for item in session.rounds],
        "summary": _pick(session.summary, SUMMARY_FIELDS),
    })


def restore_interview(payload):
    _check_version(payload)
    rounds = []
    for item in payload["rounds"]:
        feedback = item["feedback"]
        rounds.append(InterviewRound(
            question=item["question"], question_source=item["question_source"], answer=item["answer"],
            feedback=InterviewFeedback(
                score=feedback["score"], overall_feedback=feedback["overall_feedback"],
                **_string_lists(feedback, ("strengths", "improvements", "answer_structure")),
            ),
        ))
    summary = payload["summary"]
    return rounds, InterviewSummary(
        overall_summary=summary["overall_summary"],
        **_string_lists(summary, SUMMARY_FIELDS[:-1]),
    )
