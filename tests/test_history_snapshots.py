from dataclasses import replace
import json
from unittest import TestCase

from app.services.interview_session import (
    InterviewSession, InterviewRound, InterviewFeedback, InterviewSummary,
)
from app.services.workflow_types import ResumeAdviceResult
from app.storage.history_snapshots import (
    make_analysis_snapshot, make_interview_snapshot, restore_analysis, restore_interview,
)
from app.tools.tool_types import ToolCallRecord
import test_history_interview as fixtures
from test_interview_session import make_context


class HistorySnapshotTests(TestCase):
    def test_analysis_structured_roundtrip_and_omissions(self):
        result = restore_analysis(fixtures.make_payload())
        result = replace(
            result, effective_resume_text="PRIVATE_RESUME_BODY",
            jd_analysis=replace(result.jd_analysis, raw_output="PRIVATE_RAW_MODEL"),
            resume_advice=ResumeAdviceResult(["直接建议"], ["未来建议"], "PRIVATE_RAW_MODEL"),
            tool_calls=[ToolCallRecord("analyze", "PRIVATE_TOOL_INPUT", "PRIVATE_TOOL_OUTPUT", True, "PRIVATE_ERROR")],
        )
        payload = make_analysis_snapshot(result, "历史 JD", True, "PRIVATE_RESUME_BODY")
        serialized = json.dumps(payload, ensure_ascii=False)
        for marker in ("PRIVATE_RESUME_BODY", "PRIVATE_RAW_MODEL", "PRIVATE_TOOL_INPUT", "PRIVATE_TOOL_OUTPUT", "PRIVATE_ERROR"):
            self.assertNotIn(marker, serialized)
        restored = restore_analysis(payload)
        self.assertEqual(restored.effective_resume_text, "")
        self.assertEqual(restored.jd_analysis.required_skills, result.jd_analysis.required_skills)
        self.assertEqual(restored.match_analysis, result.match_analysis)
        self.assertEqual(restored.resume_advice.future_edits, ["未来建议"])
        self.assertEqual(restored.retrieved_chunks, result.retrieved_chunks)
        self.assertEqual(restored.selected_resume, result.selected_resume)
        self.assertEqual(restored.tool_calls[0].tool_name, "analyze")
        self.assertTrue(restored.tool_calls[0].success)
        result.jd_analysis.required_skills.append("后续修改")
        self.assertNotIn("后续修改", payload["result"]["jd_analysis"]["required_skills"])

    def test_complete_rounds_preserved_without_context_or_bank(self):
        feedback = InterviewFeedback(15, [], ["改进"], ["结构"], "整体反馈")
        rounds = [InterviewRound(f"问题 {index}", "project", f"  原始答案 {index}\n", feedback) for index in range(3)]
        summary = InterviewSummary([], ["薄弱"], ["回答结构"], ["练习"], "总结")
        context = replace(make_context(), resume_text="PRIVATE_RESUME_BODY", question_bank=["UNUSED_BANK_QUESTION"])
        session = InterviewSession(context, 3, "", "", rounds, "completed", summary)
        payload = make_interview_snapshot(session)
        self.assertEqual(restore_interview(payload), (rounds, summary))
        serialized = json.dumps(payload)
        for marker in ("PRIVATE_RESUME_BODY", "UNUSED_BANK_QUESTION", "context", "api_key"):
            self.assertNotIn(marker, serialized)
        rounds[0].feedback.improvements.append("修改")
        self.assertEqual(payload["rounds"][0]["feedback"]["improvements"], ["改进"])

    def test_incomplete_or_empty_session_not_saved(self):
        session = InterviewSession(make_context(), 3, "首题", "project")
        with self.assertRaises(ValueError):
            make_interview_snapshot(session)
        session.status = "completed"
        session.summary = InterviewSummary([], [], [], [], "总结")
        with self.assertRaises(ValueError):
            make_interview_snapshot(session)

    def test_unsupported_version_and_invalid_lists_rejected(self):
        with self.assertRaises(ValueError):
            restore_analysis({"schema_version": 2})
        with self.assertRaises(ValueError):
            restore_interview({"schema_version": 2})
        payload = fixtures.make_payload()
        payload["result"]["jd_analysis"]["required_skills"] = "非法列表"
        with self.assertRaises(ValueError):
            restore_analysis(payload)
