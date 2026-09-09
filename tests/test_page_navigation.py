"""Page routing regressions with isolated stores and no provider calls."""

import json
from test_interview_ui import choose
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from app.services.document_parser import ParsedDocument
from app.services.workflow_types import JDAnalysisResult, WorkflowRunResult
from app.storage.history_repository import HistoryStore
from app.storage.history_snapshots import make_analysis_snapshot


class NavigationLLM:
    def __init__(self):
        self.responses = []
        self.prompts = []

    def chat(self, system_prompt, user_prompt):
        self.prompts.append(user_prompt)
        if not self.responses:
            raise AssertionError("Navigation unexpectedly requested a model response")
        return json.dumps(self.responses.pop(0), ensure_ascii=False)


def round_feedback():
    return {
        "score": 76,
        "strengths": ["能解释检索设计"],
        "improvements": ["补充评估数据"],
        "answer_structure": ["背景", "实现", "结果"],
        "overall_feedback": "请继续说明验证过程。",
        "next_question": "如何验证检索质量？",
        "next_question_source": "project",
    }


class PageNavigationTests(TestCase):
    def setUp(self):
        st.cache_resource.clear()
        self.addCleanup(st.cache_resource.clear)
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.history_path = Path(self.temp.name) / "navigation.sqlite3"
        self.repository = HistoryStore(self.history_path)
        self.resume_store = Mock()
        self.resume_store.list_records.return_value = []
        self.project_store = Mock()
        self.project_store.count.return_value = 0
        self.project_store.list_chunks.return_value = []
        self.llm = NavigationLLM()
        self.workflow = Mock()
        self.result = WorkflowRunResult(
            jd_analysis=JDAnalysisResult(
                responsibilities=["岗位职责标记"], required_skills=["Python"],
                bonus_points=["跨页面分析结论"], ai_keywords=["RAG"],
                interview_focus=["检索实现"], raw_output="",
            ),
            effective_resume_text="完整简历：实现检索应用并负责评估。",
        )
        self.workflow.run.return_value = self.result
        for target, value in (
            ("app.rag.ResumeStore", self.resume_store),
            ("app.rag.ProfileKnowledgeBase", self.project_store),
            ("app.services.interview_session.LLMClient", self.llm),
            ("app.services.job_prep_workflow.JobPrepWorkflow", self.workflow),
        ):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        history_patcher = patch(
            "app.storage.HistoryStore",
            side_effect=lambda *args, **kwargs: HistoryStore(self.history_path),
        )
        history_patcher.start()
        self.addCleanup(history_patcher.stop)
        self.app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app/main.py"))
        self.app.run()
        self.assert_no_exception()

    def assert_no_exception(self):
        self.assertFalse(self.app.exception, [item.message for item in self.app.exception])

    def button(self, label):
        return next(item for item in self.app.button if item.label == label)

    def navigate(self, page):
        self.app.radio(key="navigation").set_value(page).run()
        self.assert_no_exception()

    def analyze(self):
        self.navigate("岗位分析")
        self.app.text_area(key="resume_text").set_value(self.result.effective_resume_text)
        self.app.text_area(key="job_description").set_value("招聘 Python 应用工程师")
        self.button("开始岗位分析").click().run()
        self.assert_no_exception()

    def start_interview(self):
        self.navigate("模拟面试")
        choose(self.app, "interview_context_choice", ["独立面试"])
        choose(self.app, "interview_sources", ["简历项目经历"])
        choose(self.app, "direct_resume_methods", ["自行上传或输入"])
        self.app.text_area(key="direct_resume_text").set_value(self.result.effective_resume_text)
        self.llm.responses = [{"question": "请介绍检索项目。", "question_source": "project"}]
        self.button("开始模拟面试").click().run()
        self.assert_no_exception()

    def answer_box(self):
        return next(item for item in self.app.text_area if item.label == "你的回答")

    def test_project_preview_reads_chunks_only_when_requested(self):
        self.project_store.count.return_value = 2
        self.project_store.list_chunks.return_value = []
        self.navigate("资料库")
        self.app.radio(key="library_section").set_value("项目资料库").run()
        self.assert_no_exception()
        self.project_store.list_chunks.assert_not_called()
        self.app.toggle(key="browse_project_chunks").set_value(True).run()
        self.assert_no_exception()
        self.project_store.list_chunks.assert_called_once()

    def test_navigation_has_four_pages_with_separate_task_forms(self):
        self.assertEqual(
            self.app.radio(key="navigation").options,
            ["岗位分析", "模拟面试", "资料库", "历史记录"],
        )
        for page, expected, forbidden in (
            ("岗位分析", "开始岗位分析", {"开始模拟面试", "添加到简历库", "使用此分析准备面试"}),
            ("模拟面试", "开始模拟面试", {"开始岗位分析", "添加到简历库", "使用此分析准备面试"}),
            ("资料库", "添加到简历库", {"开始岗位分析", "开始模拟面试", "使用此分析准备面试"}),
        ):
            with self.subTest(page=page):
                self.navigate(page)
                labels = {item.label for item in self.app.button}
                self.assertIn(expected, labels)
                self.assertFalse(labels & forbidden)
                self.assertFalse(any(item.key == "history_kind" for item in self.app.selectbox))
        self.navigate("历史记录")
        self.assertEqual(self.app.session_state["history_kind_choice"], ["全部"])
        self.assertFalse(
            {"开始岗位分析", "开始模拟面试", "添加到简历库"}
            & {item.label for item in self.app.button}
        )
        self.assertEqual(self.llm.prompts, [])
        self.workflow.run.assert_not_called()

    def test_resume_and_jd_drafts_survive_leaving_the_analysis_page(self):
        self.app.text_area(key="resume_text").set_value("  简历草稿\n保留原始格式。")
        self.app.text_area(key="job_description").set_value("  JD 草稿\nPython 与 RAG")
        for page in ("资料库", "历史记录", "岗位分析"):
            self.navigate(page)
        self.assertEqual(self.app.text_area(key="resume_text").value, "  简历草稿\n保留原始格式。")
        self.assertEqual(self.app.text_area(key="job_description").value, "  JD 草稿\nPython 与 RAG")
        self.assertEqual(self.app.radio(key="analysis_mode").value, "普通分析模式")
        self.assertEqual(self.llm.prompts, [])

    def test_rag_mode_manual_resume_and_notes_survive_page_switches(self):
        self.resume_store.list_records.return_value = [
            SimpleNamespace(resume_id="one", file_name="第一份简历.md"),
            SimpleNamespace(resume_id="two", file_name="第二份简历.md"),
        ]
        self.app.radio(key="analysis_mode").set_value("RAG 资料库模式").run()
        self.app.selectbox(key="preferred_resume_option").set_value("two")
        self.app.text_area(key="job_description").set_value("数据应用开发岗位")
        self.app.text_area(key="supplementary_note").set_value("重点关注检索能力")
        self.navigate("资料库")
        self.app.radio(key="library_section").set_value("项目资料库").run()
        self.navigate("历史记录")
        self.navigate("岗位分析")
        self.assertEqual(self.app.radio(key="analysis_mode").value, "RAG 资料库模式")
        self.assertEqual(self.app.selectbox(key="preferred_resume_option").value, "two")
        self.assertEqual(self.app.text_area(key="job_description").value, "数据应用开发岗位")
        self.assertEqual(self.app.text_area(key="supplementary_note").value, "重点关注检索能力")
        self.resume_store.reset.assert_not_called()
        self.resume_store.delete.assert_not_called()
        self.project_store.reset.assert_not_called()

    def test_analysis_to_interview_only_prepares_until_explicit_start(self):
        self.analyze()
        self.button("去模拟面试").click().run()
        self.assert_no_exception()
        self.assertEqual(self.app.radio(key="navigation").value, "模拟面试")
        self.assertEqual(self.app.session_state["interview_context_choice"], ["通过岗位分析结果进行面试"])
        self.assertEqual(self.llm.prompts, [])
        self.assertTrue(any(item.label == "开始模拟面试" for item in self.app.button))
        self.workflow.run.assert_called_once()
        self.navigate("岗位分析")
        self.assertTrue(any("跨页面分析结论" in item.value for item in self.app.markdown))
        self.assertEqual(self.llm.prompts, [])

    def test_answer_draft_and_full_round_survive_all_other_pages(self):
        self.start_interview()
        self.answer_box().set_value("  尚未提交的回答\n第一行保留。")
        for page in ("资料库", "历史记录", "岗位分析", "模拟面试"):
            self.navigate(page)
        self.assertEqual(self.answer_box().value, "  尚未提交的回答\n第一行保留。")
        self.assertEqual(len(self.llm.prompts), 1)
        self.llm.responses = [round_feedback()]
        self.answer_box().set_value("  我设计了分块与检索。\n")
        self.button("提交回答并继续").click().run()
        self.assert_no_exception()
        self.answer_box().set_value("第二轮未提交草稿")
        for page in ("历史记录", "资料库", "岗位分析", "模拟面试"):
            self.navigate(page)
        self.assertEqual(self.answer_box().value, "第二轮未提交草稿")
        session = self.app.session_state["interview_session"]
        self.assertEqual(len(session.rounds), 1)
        self.assertEqual(session.rounds[0].answer, "  我设计了分块与检索。\n")
        self.assertEqual(session.rounds[0].question, "请介绍检索项目。")
        self.assertEqual(session.rounds[0].question_source, "project")
        self.assertEqual(session.rounds[0].feedback.score, 76)
        self.assertEqual(session.rounds[0].feedback.strengths, ["能解释检索设计"])
        self.assertEqual(session.rounds[0].feedback.improvements, ["补充评估数据"])
        self.assertEqual(session.rounds[0].feedback.answer_structure, ["背景", "实现", "结果"])
        self.assertEqual(session.rounds[0].feedback.overall_feedback, "请继续说明验证过程。")
        self.assertTrue(any(item.value == "  我设计了分块与检索。" for item in self.app.code))
        self.assertEqual(len(self.llm.prompts), 2)

    def test_saved_analysis_id_and_result_survive_interview_and_resources(self):
        self.analyze()
        self.button("保存本次分析").click().run()
        initial_record = self.repository.list_records(kind="analysis")[0]
        self.button("去模拟面试").click().run()
        choose(self.app, "interview_sources", ["简历项目经历"])
        self.llm.responses = [{"question": "请介绍项目。", "question_source": "project"}]
        self.button("开始模拟面试").click().run()
        self.assert_no_exception()
        self.navigate("资料库")
        self.navigate("历史记录")
        self.navigate("岗位分析")
        self.assertTrue(any("跨页面分析结论" in item.value for item in self.app.markdown))
        self.button("保存本次分析").click().run()
        self.assert_no_exception()
        records = self.repository.list_records(kind="analysis")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].record_id, initial_record.record_id)
        self.assertEqual(records[0].payload, initial_record.payload)
        self.workflow.run.assert_called_once()
        self.assertEqual(len(self.llm.prompts), 1)

    def test_history_filters_and_replacement_resume_draft_survive_navigation(self):
        payload = make_analysis_snapshot(
            self.result, "历史 JD", False, self.result.effective_resume_text,
        )
        self.repository.save("older-analysis", "analysis", "历史岗位", payload)
        self.navigate("历史记录")
        choose(self.app, "history_kind_choice", ["岗位分析"])
        choose(self.app, "history_days_choice", [30])
        self.app.button(key="history_view_older-analysis").click().run()
        self.button("去模拟面试").click().run()
        choose(self.app, "analysis_resume_method_older-analysis", ["重新上传或输入"])
        self.app.text_area(key="analysis_resume_text_older-analysis").set_value("新简历的草稿正文")
        self.app.checkbox(key="analysis_resume_confirm_older-analysis").check()
        for page in ("岗位分析", "资料库", "历史记录", "模拟面试"):
            self.navigate(page)
        self.assertEqual(self.app.session_state["history_kind_choice"], ["岗位分析"])
        self.assertEqual(self.app.session_state["history_days_choice"], [30])
        self.assertEqual(self.app.session_state["history_detail_id"], "older-analysis")
        self.assertEqual(self.app.text_area(key="analysis_resume_text_older-analysis").value, "新简历的草稿正文")
        self.assertTrue(self.app.checkbox(key="analysis_resume_confirm_older-analysis").value)
        self.assertEqual(len(self.repository.list_records()), 1)
        self.assertEqual(self.llm.prompts, [])
        self.workflow.run.assert_not_called()

    def test_interview_configuration_survives_analysis_and_library_navigation(self):
        self.navigate("模拟面试")
        choose(self.app, "interview_sources", ["岗位技术理论"])
        choose(self.app, "interview_round_limit", [5])
        choose(self.app, "direct_jd_methods", ["自行上传或输入"])
        self.app.text_area(key="direct_jd_text").set_value("算法工程师岗位")
        self.navigate("资料库")
        self.navigate("岗位分析")
        self.navigate("模拟面试")
        self.assertEqual(self.app.session_state["interview_sources"], ["岗位技术理论"])
        self.assertEqual(self.app.session_state["interview_round_limit"], [5])
        self.assertEqual(self.app.text_area(key="direct_jd_text").value, "算法工程师岗位")
        self.assertEqual(self.llm.prompts, [])
        self.resume_store.reset.assert_not_called()
        self.project_store.reset.assert_not_called()

    def test_staged_question_bank_survives_navigation_and_clear_blocks_reuse(self):
        documents = [ParsedDocument("面试题库.md", "md", "1. 如何验证检索质量？\n2. 什么是向量检索？")]
        self.app.session_state["interview_bank_documents"] = documents
        self.navigate("模拟面试")
        choose(self.app, "interview_sources", ["自选题库"])
        for page in ("资料库", "历史记录", "岗位分析", "模拟面试"):
            self.navigate(page)
        self.assertEqual(self.app.session_state["interview_bank_documents"], documents)
        self.assertTrue(any("面试题库.md" in item.value for item in self.app.caption))
        self.llm.responses = [{"question": "如何验证检索质量？", "question_source": "question_bank"}]
        self.button("开始模拟面试").click().run()
        self.assert_no_exception()
        session = self.app.session_state["interview_session"]
        self.assertEqual(session.context.question_modes, ("question_bank",))
        self.assertEqual(session.context.question_bank, ["如何验证检索质量？", "什么是向量检索？"])
        self.assertEqual(session.current_question_source, "question_bank")
        self.assertEqual(len(self.llm.prompts), 1)
        self.button("重新开始").click().run()
        self.app.button(key="interview_bank_clear").click().run()
        self.assert_no_exception()
        for page in ("岗位分析", "资料库", "模拟面试"):
            self.navigate(page)
        self.button("开始模拟面试").click().run()
        self.assert_no_exception()
        self.assertTrue(any("题库" in item.value for item in self.app.warning))
        self.assertEqual(len(self.llm.prompts), 1)
        self.assertFalse(any("面试题库.md" in item.value for item in self.app.caption))
        self.assertIsNone(self.app.session_state.filtered_state.get("interview_session"))

    def test_staged_library_uploads_survive_navigation_and_clear_independently(self):
        resumes = [ParsedDocument("待入库简历.md", "md", "候选人负责检索系统实现。")]
        projects = [ParsedDocument("待入库项目报告.md", "md", "项目使用向量检索和结果重排。")]
        self.app.session_state["resume_library_documents"] = resumes
        self.app.session_state["project_kb_documents"] = projects
        self.navigate("资料库")
        self.assertFalse(self.button("添加到简历库").disabled)
        self.app.radio(key="library_section").set_value("项目资料库").run()
        self.assertFalse(self.button("建立项目库").disabled)
        for page in ("岗位分析", "模拟面试", "历史记录", "资料库"):
            self.navigate(page)
        self.assertEqual(self.app.radio(key="library_section").value, "项目资料库")
        self.assertEqual(self.app.session_state["project_kb_documents"], projects)
        self.assertTrue(any("待入库项目报告.md" in item.value for item in self.app.caption))
        self.app.radio(key="library_section").set_value("简历库").run()
        self.assertEqual(self.app.session_state["resume_library_documents"], resumes)
        self.assertTrue(any("待入库简历.md" in item.value for item in self.app.caption))
        self.app.button(key="resume_library_clear").click().run()
        self.assert_no_exception()
        self.assertTrue(self.button("添加到简历库").disabled)
        self.assertEqual(self.app.session_state["project_kb_documents"], projects)
        self.app.radio(key="library_section").set_value("项目资料库").run()
        self.app.button(key="project_kb_clear").click().run()
        self.navigate("岗位分析")
        self.navigate("资料库")
        self.assertTrue(self.button("建立项目库").disabled)
        self.assertFalse(any("待入库项目报告.md" in item.value for item in self.app.caption))
        self.resume_store.add_documents.assert_not_called()
        self.resume_store.reset.assert_not_called()
        self.resume_store.delete.assert_not_called()
        self.project_store.add_documents.assert_not_called()
        self.project_store.reset.assert_not_called()
        self.assertEqual(self.llm.prompts, [])
