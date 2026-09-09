from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from dataclasses import replace
import sqlite3

from streamlit.testing.v1 import AppTest

from app.storage.history_repository import HistoryStore
from app.storage.history_snapshots import restore_analysis
import test_interview_ui as ui_fixture
from test_interview_ui import choose
import test_history_interview as fixtures
from test_interview_session import feedback


class HistoryUITests(TestCase):
    button = ui_fixture.InterviewUITests.button
    configure = ui_fixture.InterviewUITests.configure
    answer = ui_fixture.InterviewUITests.answer
    navigate = ui_fixture.InterviewUITests.navigate
    prepare_analysis_interview = ui_fixture.InterviewUITests.prepare_analysis_interview

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "history.sqlite3"
        self.repository = HistoryStore(self.path)
        patcher = patch("app.storage.HistoryStore", side_effect=lambda *args, **kwargs: HistoryStore(self.path))
        self.history_factory = patcher.start()
        self.addCleanup(patcher.stop)
        ui_fixture.InterviewUITests.setUp(self)

    def show_history(self, record_id=None):
        self.navigate("历史记录")
        if self.app.session_state.filtered_state.get("history_detail_id"):
            self.button("返回记录列表").click().run()
        if record_id:
            self.app.button(key=f"history_view_{record_id}").click().run()
        elif self.app.button and any(item.label == "查看详情" for item in self.app.button):
            self.button("查看详情").click().run()

    def restart_app(self):
        self.app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app/main.py")).run()
        self.assertFalse(self.app.exception)

    def test_save_analysis_is_explicit_repeatable_and_survives_restart(self):
        self.configure(combined=True)
        self.button("开始岗位分析").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.repository.list_records(), [])
        self.button("保存本次分析").click().run()
        self.app.text_area(key="job_description").set_value("后来修改的 JD")
        self.button("保存本次分析").click().run()
        records = self.repository.list_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].payload["job_description"], "岗位 JD")
        self.restart_app()
        self.show_history()
        self.assertTrue(any("加分标记" in item.value for item in self.app.markdown))
        self.assertEqual(self.llm.prompts, [])
        self.workflow.run.assert_called_once()

    def test_save_interview_delete_analysis_keeps_full_review(self):
        self.configure(combined=True)
        self.button("开始岗位分析").click().run()
        self.button("保存本次分析").click().run()
        analysis = self.repository.list_records()[0]
        self.llm.responses = [
            {"question": "首题", "question_source": "project"}, feedback("第二题"),
            {"overall_summary": "复盘标记", "weaknesses": ["薄弱点标记"]},
        ]
        self.prepare_analysis_interview()
        self.button("开始模拟面试").click().run()
        self.answer("  原始回答\n")
        self.button("结束并生成复盘").click().run()
        self.button("保存本次复盘").click().run()
        self.button("保存本次复盘").click().run()
        interviews = self.repository.list_records(kind="interview")
        self.assertEqual(len(interviews), 1)
        self.assertEqual(interviews[0].analysis_id, analysis.record_id)
        self.restart_app()
        self.show_history()
        self.show_history(analysis.record_id)
        self.button("删除此记录").click().run()
        self.assertEqual(len(self.repository.list_records(kind="analysis")), 1)
        self.button("确认删除").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.repository.list_records(kind="analysis"), [])
        self.assertIsNone(self.repository.get(interviews[0].record_id).analysis_id)
        self.show_history(interviews[0].record_id)
        self.assertFalse(self.app.exception)
        self.assertTrue(any("复盘标记" in item.value for item in self.app.markdown))
        self.assertEqual(self.app.code[0].value, "  原始回答")  # Streamlit removes the trailing display newline.
        self.assertEqual(self.repository.get(interviews[0].record_id).payload["rounds"][0]["answer"], "  原始回答\n")

    def test_history_project_requires_resume_and_confirmation_then_no_reanalysis(self):
        self.repository.save("saved", "analysis", "历史岗位", fixtures.make_payload(resume_id=None))
        self.show_history()
        self.button("去模拟面试").click().run()
        choose(self.app, "interview_sources", ["简历项目经历"])
        self.button("开始模拟面试").click().run()
        self.assertTrue(any("临时简历" in item.value for item in self.app.warning))
        choose(self.app, "analysis_resume_method_saved", ["重新上传或输入"])
        self.app.text_area(key="analysis_resume_text_saved").set_value("新简历完整正文")
        self.button("开始模拟面试").click().run()
        self.assertTrue(any("确认" in item.value for item in self.app.warning))
        self.app.checkbox(key="analysis_resume_confirm_saved").check().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.radio(key="navigation").value, "模拟面试")
        self.assertEqual(self.app.session_state["interview_context_choice"], ["通过岗位分析结果进行面试"])
        self.assertEqual(self.llm.prompts, [])
        self.llm.responses = [{"question": "首题", "question_source": "project"}]
        self.button("开始模拟面试").click().run()
        self.assertFalse(self.app.exception)
        self.workflow.run.assert_not_called()
        self.assertIn("新简历完整正文", self.llm.prompts[0])
        self.assertNotIn("旧项目", self.llm.prompts[0])

    def test_history_resume_rechecked_when_starting_and_bank_must_be_uploaded(self):
        self.repository.save("saved", "analysis", "历史岗位", fixtures.make_payload())
        self.store.get.return_value = SimpleNamespace(text=fixtures.ORIGINAL_RESUME)
        self.show_history()
        self.button("去模拟面试").click().run()
        choose(self.app, "interview_sources", ["简历项目经历"])
        self.store.get.side_effect = KeyError("deleted")
        self.button("开始模拟面试").click().run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any("已删除" in item.value for item in self.app.warning))
        self.assertEqual(self.llm.prompts, [])
        choose(self.app, "interview_sources", ["自选题库"])
        self.button("开始模拟面试").click().run()
        self.assertTrue(any("题库" in item.value for item in self.app.warning))

    def test_save_failure_preserves_result_and_can_retry(self):
        self.configure(combined=True)
        self.button("开始岗位分析").click().run()
        self.history_factory.side_effect = sqlite3.OperationalError("database is locked")
        self.button("保存本次分析").click().run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any("保存失败" in item.value for item in self.app.error))
        self.assertTrue(any("加分标记" in item.value for item in self.app.markdown))
        self.history_factory.side_effect = lambda *args, **kwargs: HistoryStore(self.path)
        self.button("保存本次分析").click().run()
        self.assertEqual(len(self.repository.list_records()), 1)

    def test_current_rag_result_and_history_survive_page_switches(self):
        payload = fixtures.make_payload()
        payload["result"]["retrieval_query"] = "项目检索词"
        payload["result"]["max_retrieval_distance"] = 0.8
        result = restore_analysis(payload)
        self.workflow.run.return_value = replace(result, effective_resume_text=fixtures.ORIGINAL_RESUME)
        self.store.list_records.return_value = [SimpleNamespace(resume_id="original", file_name="完整简历.md")]
        self.store.get.return_value = SimpleNamespace(text=fixtures.ORIGINAL_RESUME)
        self.app.radio(key="analysis_mode").set_value("RAG 资料库模式").run()
        self.app.text_area(key="job_description").set_value("岗位 JD")
        self.button("开始岗位分析").click().run()
        self.button("保存本次分析").click().run()
        self.show_history()
        self.assertFalse(self.app.exception)
        queries = [x for x in self.app.text_area if x.label == "模型生成的检索查询"]
        self.assertEqual(len(queries), 1)
        self.assertEqual({x.value for x in queries}, {"项目检索词"})
        self.navigate("岗位分析")
        queries = [x for x in self.app.text_area if x.label == "模型生成的检索查询"]
        self.assertEqual([x.value for x in queries], ["项目检索词"])
        self.assertEqual(self.app.text_area(key="job_description").value, "岗位 JD")
        self.workflow.run.assert_called_once()

    def test_new_analysis_gets_new_id_and_independent_review_has_no_link(self):
        self.configure(combined=True)
        self.button("开始岗位分析").click().run()
        self.button("保存本次分析").click().run()
        self.button("开始岗位分析").click().run()
        self.button("保存本次分析").click().run()
        self.assertEqual(len(self.repository.list_records(kind="analysis")), 2)
        self.configure(combined=False)
        self.llm.responses = [
            {"question": "首题", "question_source": "project"}, feedback("下一题"),
            {"overall_summary": "独立复盘"},
        ]
        self.button("开始模拟面试").click().run()
        self.answer("回答")
        self.button("结束并生成复盘").click().run()
        self.button("保存本次复盘").click().run()
        self.assertFalse(self.app.exception)
        self.assertIsNone(self.repository.list_records(kind="interview")[0].analysis_id)

    def test_corrupt_database_does_not_hide_current_analysis(self):
        self.configure(combined=True)
        self.button("开始岗位分析").click().run()
        self.history_factory.side_effect = sqlite3.DatabaseError("not a database")
        self.show_history()
        self.assertFalse(self.app.exception)
        self.assertTrue(any("无法读取" in x.value for x in self.app.error))
        self.navigate("岗位分析")
        self.assertTrue(any("加分标记" in x.value for x in self.app.markdown))

    def test_history_filters_and_interview_settings_survive_navigation(self):
        self.repository.save("first", "analysis", "第一份历史岗位", fixtures.make_payload())
        self.repository.save("second", "analysis", "第二份历史岗位", fixtures.make_payload())
        self.navigate("历史记录")
        self.assertEqual(len([x for x in self.app.button if x.label == "查看详情"]), 2)
        choose(self.app, "history_kind_choice", ["岗位分析"])
        choose(self.app, "history_days_choice", [30])
        self.navigate("资料库")
        self.navigate("历史记录")
        self.assertEqual(self.app.session_state["history_kind_choice"], ["岗位分析"])
        self.assertEqual(self.app.session_state["history_days_choice"], [30])
        self.app.button(key="history_view_first").click().run()
        self.button("去模拟面试").click().run()
        choose(self.app, "interview_sources", ["岗位技术理论"])
        choose(self.app, "interview_round_limit", [5])
        self.navigate("资料库")
        self.navigate("模拟面试")
        self.assertEqual(self.app.session_state["interview_round_limit"], [5])
        self.assertEqual(self.llm.prompts, [])
        self.llm.responses = [{"question": "理论首题", "question_source": "theory"}]
        self.button("开始模拟面试").click().run()
        self.assertFalse(self.app.exception)
        session = self.app.session_state["interview_session"]
        self.assertEqual(session.max_rounds, 5)
        self.assertEqual(session.context.question_modes, ("theory",))
        self.workflow.run.assert_not_called()
