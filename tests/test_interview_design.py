from types import SimpleNamespace
from unittest import TestCase

from app.services.document_parser import ParsedDocument
from app.services.interview_session import InterviewSessionService
from app.storage.history_snapshots import make_interview_snapshot, restore_interview
from test_interview_session import FakeInterviewLLM, feedback, make_context
import test_interview_ui as ui_fixture
from test_interview_ui import choose
import test_history_interview as history_fixture


class RoundLimitTests(TestCase):
    def test_one_round_finishes_and_ten_rounds_are_accepted(self):
        llm = FakeInterviewLLM([{"question": "首题", "question_source": "project"}, feedback(""), {"overall_summary": "单轮复盘"}])
        service = InterviewSessionService(llm)
        session = service.start(make_context(), max_rounds=1)
        service.submit_answer(session, "我的真实回答")
        self.assertEqual(session.status, "completed")
        self.assertEqual(len(session.rounds), 1)
        self.assertEqual(session.summary.overall_summary, "单轮复盘")
        service._validate_round_limit(10)
        for value in (0, 11, -1, True, 2.5, "3"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                service._validate_round_limit(value)

    def test_unlimited_passes_ten_rounds_and_stops_only_on_finish(self):
        llm = FakeInterviewLLM([{"question": "首题", "question_source": "project"}] + [feedback(f"下一题{i}") for i in range(12)] + [{"overall_summary": "循环复盘"}])
        service = InterviewSessionService(llm)
        session = service.start(make_context(), max_rounds=None)
        for i in range(12):
            service.submit_answer(session, f"回答{i}")
        self.assertEqual(len(session.rounds), 12)
        self.assertEqual(session.status, "active")
        self.assertIsNone(session.summary)
        service.finish(session)
        payload = make_interview_snapshot(session)
        self.assertIsNone(payload["max_rounds"])
        rounds, summary = restore_interview(payload)
        self.assertEqual(len(rounds), 12)
        self.assertEqual(summary.overall_summary, "循环复盘")
        with self.assertRaises(ValueError):
            service.submit_answer(session, "不能重复提交")

    def test_unlimited_summary_failure_can_retry_without_duplicate_answer(self):
        llm = FakeInterviewLLM([{"question": "首题", "question_source": "project"}, feedback("下一题"), RuntimeError("offline"), {"overall_summary": "重试完成"}])
        service = InterviewSessionService(llm)
        session = service.start(make_context(), max_rounds=None)
        service.submit_answer(session, "回答")
        with self.assertRaises(RuntimeError):
            service.finish(session)
        self.assertEqual(session.status, "summary_pending")
        service.finish(session)
        self.assertEqual(len(session.rounds), 1)


class InterviewDesignUITests(TestCase):
    setUp = ui_fixture.InterviewUITests.setUp
    button = ui_fixture.InterviewUITests.button
    navigate = ui_fixture.InterviewUITests.navigate
    configure = ui_fixture.InterviewUITests.configure
    answer = ui_fixture.InterviewUITests.answer

    def test_source_toggle_shows_only_required_materials_and_second_click_unchecks(self):
        self.navigate("模拟面试")
        choose(self.app, "interview_sources", [])
        self.assertFalse(self.app.text_area)
        self.assertFalse(self.app.get("file_uploader"))
        choose(self.app, "interview_sources", ["岗位技术理论"])
        self.assertFalse(self.app.get("file_uploader"))
        choose(self.app, "direct_jd_methods", ["自行上传或输入"])
        self.assertEqual([x.label for x in self.app.text_area], ["补充或粘贴岗位 JD"])
        choose(self.app, "direct_jd_methods", [])
        self.assertFalse(self.app.text_area)
        choose(self.app, "interview_sources", ["自选题库"])
        self.assertFalse(self.app.text_area)
        self.assertEqual(len(self.app.get("file_uploader")), 1)
        self.assertEqual(self.llm.prompts, [])

    def test_multiple_historical_jds_and_uploads_merge_only_selected_materials(self):
        from app.storage.history_repository import HistoryStore
        from pathlib import Path
        store = HistoryStore(Path(self.temp_ui.name) / "history.db")
        for key, jd in (("one", "Python 岗位"), ("two", "检索工程师岗位"), ("skip", "不应采用的岗位")):
            payload = history_fixture.make_payload()
            payload["job_description"] = jd
            store.save(key, "analysis", jd, payload)
        self.navigate("模拟面试")
        choose(self.app, "interview_sources", ["岗位技术理论"])
        choose(self.app, "direct_jd_methods", ["历史岗位 JD", "自行上传或输入"])
        choose(self.app, "direct_jd_ids", ["one", "two"])
        self.app.session_state["direct_jd_documents"] = [ParsedDocument("补充.md", "md", "评测岗位要求")]
        self.app.run()
        self.llm.responses = [{"question": "如何做检索评测？", "question_source": "theory"}]
        self.button("开始模拟面试").click().run()
        self.assertFalse(self.app.exception)
        context = self.app.session_state["interview_session"].context
        for text in ("Python 岗位", "检索工程师岗位", "评测岗位要求"):
            self.assertIn(text, context.jd_analysis)
        self.assertNotIn("不应采用", context.jd_analysis)
        self.assertEqual(context.resume_text, "")
        self.store.get.assert_not_called()

    def test_unlimited_ui_waits_for_submit_then_manual_finish(self):
        self.configure()
        choose(self.app, "interview_round_limit", ["循环直到自行停止"])
        self.llm.responses = [{"question": "首题", "question_source": "project"}, feedback("继续问题"), {"overall_summary": "手动结束"}]
        self.button("开始模拟面试").click().run()
        self.assertIsNone(self.app.session_state["interview_session"].max_rounds)
        self.app.run()
        self.assertEqual(len(self.llm.prompts), 1)
        self.answer("回答")
        self.button("结束并生成复盘").click().run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any(tab.label == "整体评价" for tab in self.app.tabs))

    def test_preview_and_clear_library_require_dialog_actions(self):
        self.store.list_records.return_value = [SimpleNamespace(resume_id="a", file_name="完整简历.md")]
        self.store.get.return_value = SimpleNamespace(file_name="完整简历.md", text="保留格式\n完整正文")
        self.navigate("资料库")
        choose(self.app, "library_preview_choice", ["a"])
        self.button("查看完整简历").click().run()
        self.assertTrue(any("完整正文" in x.value for x in self.app.text))
        # Equivalent to the native dialog X callback; it never mutates a store.
        del self.app.session_state["library_dialog"]
        self.app.run()
        self.button("清空简历库").click().run()
        self.store.reset.assert_not_called()
        self.button("取消").click().run()
        self.store.reset.assert_not_called()
        self.button("清空简历库").click().run()
        self.button("确认清空").click().run()
        self.assertFalse(self.app.exception)
        self.store.reset.assert_called_once()
