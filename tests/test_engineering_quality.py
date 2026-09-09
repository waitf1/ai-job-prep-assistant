import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.config import LLMSettings
from app.llm.client import LLMClient, CALL_RECORDS, ToolChatResponse
from app.services.prompt_utils import parse_json_response, ensure_string_list
from app.services.match_analyzer import validate_citations
from app.services.interview_session import InterviewSessionService
from app.services.tool_planner import ToolPlanner
from app.services.workflow_types import JDAnalysisResult


class EngineeringQualityTests(unittest.TestCase):
    def test_json_requires_object(self):
        for value in ('[]', 'null', 'true', '12'):
            with self.assertRaises(ValueError):
                parse_json_response(value)

    def test_list_rejects_coercion(self):
        with self.assertRaises(ValueError):
            ensure_string_list({"items": [{"fake": "text"}]}, "items")

    def test_feedback_rejects_invalid_score_and_missing_fields(self):
        for value in (True, "80", -1, 101, None):
            with self.assertRaises(ValueError):
                InterviewSessionService._parse_feedback({"score": value})
        with self.assertRaises(ValueError):
            InterviewSessionService._parse_feedback({"score": 80})

    def planner(self, response):
        llm = Mock()
        llm.chat_with_tools.return_value = response
        tool = Mock()
        tool.to_openai_schema.return_value = {"function": {"name": "search_project_knowledge_base"}}
        return ToolPlanner(llm).analyze("resume", "jd", JDAnalysisResult([], [], [], [], [], ""), "rag", True, tool)

    def test_string_false_never_triggers_search(self):
        result = self.planner(ToolChatResponse('{"use_search":"false"}'))
        self.assertFalse(result.should_search)

    def test_unknown_tool_rejected(self):
        with self.assertRaises(ValueError):
            self.planner(ToolChatResponse("", [{"name": "delete", "args": {}}]))

    def test_citation_is_literal_not_model_claim(self):
        items = [{"point_index": 0, "source": "resume", "quote": "实现了一个真实的项目"},
                 {"point_index": 0, "source": "resume", "quote": "不存在的虚构项目经历"}]
        result = validate_citations(items, "我实现了一个真实的项目。", "", 1)
        self.assertTrue(result[0]["verified"])
        self.assertFalse(result[1]["verified"])
        with self.assertRaises(ValueError):
            validate_citations(items, "", "", 0)

    def test_history_budget_preserves_records_and_summary_spans_session(self):
        rounds = [SimpleNamespace(question=f"question{i}", answer="x" * 10000,
                  feedback=SimpleNamespace(score=80, overall_feedback="y"*4000)) for i in range(100)]
        text = InterviewSessionService._format_history(rounds)
        self.assertLess(len(text), 42000)
        self.assertIn("question99", text)
        self.assertNotIn("question0", text)
        summary = InterviewSessionService._format_summary_history(rounds)
        self.assertIn("question0", summary)
        self.assertIn("question99", summary)
        self.assertLess(len(summary), 32000)
        self.assertEqual(len(rounds[0].answer), 10000)

    def client(self):
        with patch("app.llm.client.ChatOpenAI"):
            return LLMClient(LLMSettings("https://example.invalid/v1", "secret-key", "test"))

    def test_telemetry_never_records_content(self):
        client = self.client()
        client.model.invoke.return_value = SimpleNamespace(content="secret-output", usage_metadata={"input_tokens": 10, "output_tokens": 3})
        client.chat("private resume", "private answer")
        record = CALL_RECORDS[-1]
        self.assertEqual(record["input_tokens"], 10)
        self.assertNotIn("private", str(record))
        client.model.invoke.side_effect = RuntimeError("secret-key secret-answer")
        with self.assertRaises(RuntimeError):
            client.chat("private", "private")
        self.assertEqual(CALL_RECORDS[-1]["error_type"], "RuntimeError")
        self.assertNotIn("secret", str(CALL_RECORDS[-1]))

    def test_oversize_input_rejected_before_request(self):
        client = self.client()
        with self.assertRaises(ValueError):
            client.chat("x" * 100001, "")
        client.model.invoke.assert_not_called()

    def test_missing_usage_is_unknown_not_zero(self):
        client = self.client()
        client.model.invoke.return_value = SimpleNamespace(content="ok")
        client.chat("system", "user")
        self.assertIsNone(CALL_RECORDS[-1]["input_tokens"])

    def test_citations_history_rechecks_and_omits_resume(self):
        from dataclasses import replace
        from app.storage.history_snapshots import restore_analysis, make_analysis_snapshot
        from app.rag.vector_store import RetrievedChunk
        from test_history_interview import make_payload
        result = restore_analysis(make_payload())
        quote = "这是一个可核查的项目原文"
        chunk = RetrievedChunk(quote, "demo.txt", 0, .1)
        citations = [{"point_index": 0, "source": "project", "quote": quote, "verified": False, "start": -1},
                     {"point_index": 0, "source": "resume", "quote": "PRIVATE_RESUME_QUOTE", "verified": True, "start": 0}]
        result = replace(result, retrieved_chunks=[chunk], match_analysis=replace(result.match_analysis, citations=citations))
        saved = make_analysis_snapshot(result, "jd", True, "resume")
        self.assertNotIn("PRIVATE_RESUME_QUOTE", str(saved))
        restored = restore_analysis(saved)
        self.assertTrue(restored.match_analysis.citations[0]["verified"])

    def test_citation_ui_displays_failed_verification(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_string("""
from dataclasses import replace
from test_history_interview import make_payload
from app.storage.history_snapshots import restore_analysis
from app.ui.analysis_result import render_workflow_result
result = restore_analysis(make_payload())
result = replace(result, match_analysis=replace(result.match_analysis, citations=[
    {"point_index":0,"source":"resume","quote":"无法核对的引用内容","verified":False,"start":-1}]))
render_workflow_result(result, False)
""").run()
        self.assertFalse(app.exception)
        self.assertTrue(any("请勿作为可靠证据" in item.value for item in app.warning))
