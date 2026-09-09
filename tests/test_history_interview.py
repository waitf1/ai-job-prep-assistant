from copy import deepcopy
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from app.rag.vector_store import RetrievedChunk
from app.services.history_interview import build_history_interview_context
from app.services.interview_session import InterviewSessionService
from app.services.workflow_types import (
    InterviewPrepResult,
    JDAnalysisResult,
    MatchAnalysisResult,
    SelectedResumeResult,
    WorkflowRunResult,
)
from app.storage.history_snapshots import make_analysis_snapshot


ORIGINAL_RESUME = "  完整简历\n候选人开发了旧项目并负责资料检索。\n"


def make_payload(resume_id="original", job_description="招聘 Python 工程师"):
    result = WorkflowRunResult(
        jd_analysis=JDAnalysisResult(
            responsibilities=["开发业务系统"], required_skills=["Python"],
            bonus_points=[], ai_keywords=[], interview_focus=["技术基础"], raw_output="",
        ),
        effective_resume_text=ORIGINAL_RESUME,
        selected_resume=(
            SelectedResumeResult(resume_id, "完整简历.md", "manual", None)
            if resume_id else None
        ),
        match_analysis=MatchAnalysisResult(["旧项目匹配点"], [], ["旧项目匹配证据"], ""),
        interview_prep=InterviewPrepResult(["请介绍旧项目的检索流程。"], [], ""),
        retrieved_chunks=[RetrievedChunk(
            text="旧项目的历史检索证据", source="旧项目报告.md", chunk_index=0,
            distance=0.1, section_title="项目实现", content_type="project", cleaning_status="cleaned",
        )],
    )
    return make_analysis_snapshot(result, job_description, bool(resume_id), ORIGINAL_RESUME)


def make_store(records=None):
    contents = {"original": ORIGINAL_RESUME} if records is None else records
    store = Mock()
    store.get.side_effect = lambda resume_id: SimpleNamespace(text=contents[resume_id])
    return store


class HistoryInterviewTests(TestCase):
    def setUp(self):
        self.llm_factory = patch("app.services.interview_session.LLMClient").start()
        self.addCleanup(patch.stopall)

    def tearDown(self):
        # Context recovery must neither run fresh analysis nor generate questions.
        self.llm_factory.assert_not_called()

    def test_matching_link_restores_full_resume_and_analysis_without_mutating_history(self):
        payload = make_payload()
        original_payload = deepcopy(payload)
        store = make_store()

        context = build_history_interview_context(payload, ("theory", "project"), resume_store=store)

        self.assertEqual(context.resume_text, ORIGINAL_RESUME)
        self.assertIn("旧项目匹配点", context.match_analysis)
        self.assertIn("旧项目的历史检索证据", context.retrieved_context)
        self.assertEqual(context.suggested_questions, ["请介绍旧项目的检索流程。"])
        self.assertIn("Python", context.jd_analysis)
        store.get.assert_called_once_with("original")
        self.assertEqual(payload, original_payload)

    def test_deleted_original_blocks_project_interview(self):
        with self.assertRaisesRegex(ValueError, "已删除"):
            build_history_interview_context(make_payload(), ("project",), resume_store=make_store({}))

    def test_changed_original_blocks_project_interview(self):
        with self.assertRaisesRegex(ValueError, "已变化"):
            build_history_interview_context(
                make_payload(), ("project",), resume_store=make_store({"original": "更改后的完整简历"}),
            )

    def test_missing_store_and_missing_reference_block_project_interview(self):
        with self.assertRaisesRegex(ValueError, "简历库"):
            build_history_interview_context(make_payload(), ("project",))
        payload = make_payload()
        payload.pop("resume_ref")
        with self.assertRaisesRegex(ValueError, "重新提供"):
            build_history_interview_context(payload, ("project",), resume_store=make_store())

    def test_temporary_resume_must_be_provided_again_and_confirmed(self):
        payload = make_payload(resume_id=None)
        with self.assertRaisesRegex(ValueError, "临时简历"):
            build_history_interview_context(payload, ("project",))
        with self.assertRaisesRegex(ValueError, "确认"):
            build_history_interview_context(payload, ("project",), replacement_resume_text=ORIGINAL_RESUME)
        context = build_history_interview_context(
            payload, ("project",), replacement_resume_text=ORIGINAL_RESUME, confirm_replacement=True,
        )
        self.assertEqual(context.resume_text, ORIGINAL_RESUME)
        self.assertIn("旧项目匹配点", context.match_analysis)
        self.assertIn("旧项目的历史检索证据", context.retrieved_context)

    def test_reselected_matching_resume_can_reuse_analysis_after_original_deleted(self):
        context = build_history_interview_context(
            make_payload(), ("project",), resume_store=make_store({"replacement": ORIGINAL_RESUME}),
            replacement_resume_id="replacement", confirm_replacement=True,
        )
        self.assertEqual(context.resume_text, ORIGINAL_RESUME)
        self.assertEqual(context.suggested_questions, ["请介绍旧项目的检索流程。"])

    def test_changed_replacement_excludes_old_experience_and_keeps_original_jd_analysis(self):
        context = build_history_interview_context(
            make_payload(), ("theory", "project"), replacement_resume_text="新简历：负责订单系统。",
            confirm_replacement=True,
        )
        self.assertEqual(context.resume_text, "新简历：负责订单系统。")
        self.assertIn("尚未", context.match_analysis)
        self.assertEqual(context.retrieved_context, "")
        self.assertEqual(context.suggested_questions, [])
        self.assertIn("Python", context.jd_analysis)
        self.assertNotIn("旧项目", InterviewSessionService._format_context(context))

    def test_changed_library_resume_must_be_reselected_and_confirmed(self):
        store = make_store({"original": "新的简历项目经历"})
        with self.assertRaisesRegex(ValueError, "确认"):
            build_history_interview_context(
                make_payload(), ("project",), resume_store=store, replacement_resume_id="original",
            )
        store.get.assert_not_called()
        context = build_history_interview_context(
            make_payload(), ("project",), resume_store=store, replacement_resume_id="original",
            confirm_replacement=True,
        )
        self.assertEqual(context.resume_text, "新的简历项目经历")
        self.assertEqual(context.retrieved_context, "")

    def test_theory_and_bank_can_start_without_any_resume(self):
        for modes, bank in [(("theory",), None), (("question_bank",), ["题目一"]),
                            (("theory", "question_bank"), ["题目二"])]:
            with self.subTest(modes=modes):
                store = make_store({})
                context = build_history_interview_context(make_payload(), modes, bank, resume_store=store)
                self.assertEqual(context.question_modes, modes)
                self.assertEqual(context.resume_text, "")
                self.assertEqual(context.retrieved_context, "")
                self.assertEqual(context.suggested_questions, [])
                self.assertNotIn("旧项目", InterviewSessionService._format_context(context))
                store.get.assert_not_called()

    def test_theory_needs_real_original_jd_not_saved_analysis_placeholder(self):
        payload = make_payload(job_description=" \n ")
        with self.assertRaisesRegex(ValueError, "岗位 JD"):
            build_history_interview_context(payload, ("theory",))
        context = build_history_interview_context(payload, ("project",), resume_store=make_store())
        self.assertFalse(context.has_job_description)

    def test_question_bank_requires_current_nonblank_questions(self):
        payload = make_payload()
        payload["question_bank"] = ["历史题库内容不得替代当前上传"]
        for bank in (None, [], ["  ", "\n"]):
            with self.subTest(bank=bank), self.assertRaisesRegex(ValueError, "题库"):
                build_history_interview_context(payload, ("question_bank",), bank)
        context = build_history_interview_context(payload, ("question_bank",), [" 当前题库题目 "])
        self.assertEqual(context.question_bank, ["当前题库题目"])

    def test_only_bank_can_start_without_jd(self):
        context = build_history_interview_context(
            make_payload(job_description=""), ("question_bank",), ["请解释事务。"],
        )
        self.assertFalse(context.has_job_description)
        self.assertEqual(context.resume_text, "")

    def test_source_whitelist_rejects_empty_or_unknown_modes(self):
        for modes in ((), ("unknown",), ("theory", "unknown")):
            with self.subTest(modes=modes), self.assertRaises(ValueError):
                build_history_interview_context(make_payload(), modes)

    def test_blank_replacement_never_becomes_a_resume_placeholder(self):
        with self.assertRaisesRegex(ValueError, "完整简历"):
            build_history_interview_context(
                make_payload(resume_id=None), ("project",), replacement_resume_text=" \n ",
                confirm_replacement=True,
            )

    def test_missing_or_blank_replacement_library_record_is_rejected(self):
        for records in ({}, {"replacement": "  "}):
            with self.subTest(records=records), self.assertRaisesRegex(ValueError, "完整简历"):
                build_history_interview_context(
                    make_payload(), ("project",), resume_store=make_store(records),
                    replacement_resume_id="replacement", confirm_replacement=True,
                )

    def test_ref_does_not_allow_library_path_traversal(self):
        store = make_store()
        with self.assertRaisesRegex(ValueError, "引用无效"):
            build_history_interview_context(make_payload(resume_id="../elsewhere"), ("project",), resume_store=store)
        store.get.assert_not_called()

    def test_ambiguous_replacement_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "不要同时"):
            build_history_interview_context(
                make_payload(), ("project",), replacement_resume_id="replacement",
                replacement_resume_text=ORIGINAL_RESUME, confirm_replacement=True,
            )

    def test_final_shared_validation_is_called(self):
        with patch.object(InterviewSessionService, "_validate_question_modes") as validate:
            context = build_history_interview_context(make_payload(), ("theory",))
        validate.assert_called_once_with(context)
