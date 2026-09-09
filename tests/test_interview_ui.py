from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from app.services.workflow_types import JDAnalysisResult, WorkflowRunResult
from test_interview_session import FakeInterviewLLM, feedback
from app.ui.choices import choice_key
from tempfile import TemporaryDirectory
from app.storage.history_repository import HistoryStore


def choose(app, key, values):
    if key == "interview_context_choice":
        app.radio(key="interview_context_toggle").set_value(values[0]).run()
        assert not app.exception, app.exception
        return
    current = list(app.session_state.filtered_state.get(key, []))
    for value in current:
        if value not in values:
            app.checkbox(key=choice_key(key, value)).uncheck().run()
    for value in values:
        if value not in app.session_state.filtered_state.get(key, []):
            app.checkbox(key=choice_key(key, value)).check().run()
    assert not app.exception, app.exception



class InterviewUITests(TestCase):
    def setUp(self):
        st.cache_resource.clear()
        self.addCleanup(st.cache_resource.clear)
        self.temp_ui = TemporaryDirectory()
        self.addCleanup(self.temp_ui.cleanup)
        history_patch = patch("app.storage.HistoryStore", side_effect=lambda *a, **k: HistoryStore(Path(self.temp_ui.name) / "history.db"))
        # HistoryUITests installs its own temporary repository before this fixture.
        if not hasattr(self, "repository"):
            history_patch.start()
            self.addCleanup(history_patch.stop)
        self.store = Mock()
        self.store.list_records.return_value = []
        kb = Mock()
        kb.count.return_value = 0
        kb.list_chunks.return_value = []
        self.llm = FakeInterviewLLM([])
        self.workflow = Mock()
        self.workflow.run.return_value = WorkflowRunResult(
            JDAnalysisResult(["职责标记"], ["技能"], ["加分标记"], ["关键词"], ["关注点"], ""),
            effective_resume_text="完整简历",
        )
        for target, value in (
            ("app.rag.ResumeStore", self.store),
            ("app.rag.ProfileKnowledgeBase", kb),
            ("app.services.interview_session.LLMClient", self.llm),
            ("app.services.job_prep_workflow.JobPrepWorkflow", self.workflow),
        ):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app/main.py"))
        self.app.run()
        self.assertFalse(self.app.exception)

    def button(self, label):
        return next(item for item in self.app.button if item.label == label)

    def navigate(self, page):
        self.app.radio(key="navigation").set_value(page).run()
        self.assertFalse(self.app.exception)

    def configure(self, combined=False):
        self.navigate("岗位分析" if combined else "模拟面试")
        if combined:
            self.app.text_area(key="resume_text").set_value("完整简历")
            self.app.text_area(key="job_description").set_value("岗位 JD")
        else:
            choose(self.app, "interview_context_choice", ["独立面试"])
            choose(self.app, "interview_sources", ["岗位技术理论", "简历项目经历"])
            choose(self.app, "direct_jd_methods", ["自行上传或输入"])
            choose(self.app, "direct_resume_methods", ["自行上传或输入"])
            self.app.text_area(key="direct_resume_text").set_value("完整简历")
            self.app.text_area(key="direct_jd_text").set_value("岗位 JD")

    def prepare_analysis_interview(self):
        self.button("去模拟面试").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.radio(key="navigation").value, "模拟面试")
        self.assertEqual(self.app.session_state["interview_context_choice"], ["通过岗位分析结果进行面试"])
        choose(self.app, "interview_sources", ["简历项目经历"])

    def answer(self, text):
        next(item for item in self.app.text_area if item.label == "你的回答").set_value(text)
        self.button("提交回答并继续").click().run()
        self.assertFalse(self.app.exception)

    def test_combined_waits_for_confirmation_and_keeps_full_analysis(self):
        self.configure(combined=True)
        self.button("开始岗位分析").click().run()
        self.assertEqual(self.llm.prompts, [])
        self.assertEqual([item.label for item in self.app.tabs],
                         ["能力匹配", "简历建议", "面试准备", "岗位要求", "项目证据与检索详情", "工具调用过程"])
        self.assertFalse(any(item.label == "分析资料与设置" for item in self.app.tabs))
        self.prepare_analysis_interview()
        self.assertEqual(self.llm.prompts, [])
        self.assertFalse(any(item.label == "工具调用过程" for item in self.app.tabs))
        self.llm.responses = [{"question": "首题", "question_source": "project"}, feedback("第二题")]
        self.button("开始模拟面试").click().run()
        self.answer("原始答案")
        self.navigate("岗位分析")
        self.assertTrue(any("加分标记" in item.value for item in self.app.markdown))
        self.assertTrue(any(item.label == "工具调用过程" for item in self.app.tabs))
        # Starting independently must also preserve the earlier analysis.
        self.navigate("模拟面试")
        self.button("重新开始").click().run()
        self.configure()
        self.llm.responses = [{"question": "新首题", "question_source": "project"}]
        self.button("开始模拟面试").click().run()
        self.assertFalse(self.app.exception)
        self.navigate("岗位分析")
        self.assertTrue(any("加分标记" in item.value for item in self.app.markdown))
        self.workflow.run.assert_called_once()

    def test_all_round_feedback_survives_completion_and_summary_retry(self):
        self.configure()
        self.llm.responses = [
            {"question": "首题", "question_source": "project"},
            feedback("第二题"), feedback("第三题"), feedback(""),
            RuntimeError("offline"), {"overall_summary": "最终复盘"},
        ]
        self.button("开始模拟面试").click().run()
        self.answer("第一答")
        self.answer("第二答")
        self.assertEqual(len([x for x in self.app.tabs if "完整记录" in x.label]), 2)
        self.answer("第三答")
        self.assertFalse(any(x.label == "你的回答" for x in self.app.text_area))
        self.assertEqual(len(self.app.session_state["interview_session"].rounds), 3)
        self.button("重试生成复盘").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual([x.value for x in self.app.code], ["第一答", "第二答", "第三答"])
        for item in [x for x in self.app.tabs if "完整记录" in x.label]:
            texts = " ".join(x.value for x in item.markdown)
            for value in ("回答说明了实现思路", "补充量化结果", "背景", "回答基础扎实"):
                self.assertIn(value, texts)
            self.assertTrue(any("简历项目经历" in x.value for x in item.caption))
            self.assertTrue(any("80 / 100" in x.value for x in item.caption))

    def test_empty_resume_rejected_without_llm(self):
        self.configure()
        self.app.text_area(key="direct_resume_text").set_value(" ")
        self.button("开始模拟面试").click().run()
        self.assertTrue(any("完整简历" in x.value for x in self.app.warning))
        self.assertEqual(self.llm.prompts, [])

    def test_restart_clears_answer_draft(self):
        self.configure()
        self.llm.responses = [
            {"question": "首题", "question_source": "project"},
            {"question": "新题", "question_source": "project"},
        ]
        self.button("开始模拟面试").click().run()
        next(x for x in self.app.text_area if x.label == "你的回答").set_value("旧草稿")
        self.button("重新开始").click().run()
        self.button("开始模拟面试").click().run()
        self.assertEqual(next(x for x in self.app.text_area if x.label == "你的回答").value, "")

    def test_rag_standalone_selects_library_resume(self):
        self.store.list_records.return_value = [SimpleNamespace(resume_id="saved", file_name="简历.txt")]
        self.store.get.return_value = SimpleNamespace(text="库中完整简历与项目细节")
        self.navigate("模拟面试")
        choose(self.app, "interview_sources", ["简历项目经历"])
        choose(self.app, "direct_resume_methods", ["简历库"])
        choose(self.app, "direct_resume_ids", ["saved"])
        self.llm.responses = [{"question": "首题", "question_source": "project"}]
        self.button("开始模拟面试").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state["interview_session"].context.resume_text, "库中完整简历与项目细节")
        self.assertIn("库中完整简历与项目细节", self.llm.prompts[0])

    def test_navigation_keeps_inputs_and_separates_workspace_sections(self):
        self.assertEqual(self.app.radio(key="navigation").options, ["岗位分析", "模拟面试", "资料库", "历史记录"])
        self.configure(combined=True)
        self.app.run()
        self.navigate("资料库")
        self.assertFalse(any(item.label == "开始岗位分析" for item in self.app.button))
        self.assertFalse(any(item.label == "开始模拟面试" for item in self.app.button))
        self.navigate("岗位分析")
        self.assertEqual(self.app.text_area(key="resume_text").value, "完整简历")
        self.assertEqual(self.app.text_area(key="job_description").value, "岗位 JD")
        self.navigate("模拟面试")
        self.assertFalse(any(item.key == "resume_text" for item in self.app.text_area))
        self.assertEqual(self.app.session_state["resume_text"], "完整简历")
        self.assertFalse(any(item.label == "开始岗位分析" for item in self.app.button))
        self.assertEqual(self.llm.prompts, [])
        self.workflow.run.assert_not_called()

    def test_navigation_keeps_interview_progress_and_unsubmitted_answer(self):
        self.configure()
        self.llm.responses = [
            {"question": "首题", "question_source": "project"}, feedback("第二题")
        ]
        self.button("开始模拟面试").click().run()
        self.answer("已提交的第一答")
        next(item for item in self.app.text_area if item.label == "你的回答").set_value("未提交的第二答")
        self.navigate("资料库")
        self.navigate("岗位分析")
        self.navigate("模拟面试")
        self.assertEqual(len(self.app.session_state["interview_session"].rounds), 1)
        self.assertEqual(self.app.session_state["interview_session"].current_question, "第二题")
        self.assertEqual(next(item for item in self.app.text_area if item.label == "你的回答").value, "未提交的第二答")
        self.assertEqual(len(self.llm.prompts), 2)
