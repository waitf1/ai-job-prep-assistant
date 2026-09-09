from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from app.services.interview_setup import build_direct_interview_context


class InterviewSetupTests(TestCase):
    def store(self, count=2):
        store = Mock()
        store.list_records.return_value = [object()] * count
        store.select.return_value = SimpleNamespace(record=SimpleNamespace(text="完整简历\n项目经历"))
        return store

    def test_rag_uses_full_resume_and_ignores_stale_input(self):
        store = self.store()
        context = build_direct_interview_context("JD", "旧临时简历", ("project",), use_rag=True, resume_store=store)
        self.assertEqual(context.resume_text, "完整简历\n项目经历")
        store.select.assert_called_once_with(query="JD", resume_id=None)

    def test_manual_selection_without_jd(self):
        store = self.store()
        build_direct_interview_context("", "", ("project",), use_rag=True, resume_store=store, preferred_resume_id="chosen")
        store.select.assert_called_once_with(query="", resume_id="chosen")

    def test_multiple_resumes_without_jd_require_selection(self):
        store = self.store()
        with self.assertRaisesRegex(ValueError, "手动选择"):
            build_direct_interview_context("", "", ("project",), use_rag=True, resume_store=store)
        store.select.assert_not_called()

    def test_single_resume_without_jd(self):
        context = build_direct_interview_context("", "", ("project",), use_rag=True, resume_store=self.store(1))
        self.assertIn("完整简历", context.resume_text)

    def test_empty_or_unavailable_resume_rejected(self):
        with self.assertRaises(ValueError):
            build_direct_interview_context("", "", ("project",))
        with self.assertRaises(ValueError):
            build_direct_interview_context("JD", "旧简历", ("project",), use_rag=True, resume_store=self.store(0))
        store = self.store()
        store.select.return_value.record.text = "  "
        with self.assertRaisesRegex(ValueError, "完整简历"):
            build_direct_interview_context("JD", "", ("project",), use_rag=True, resume_store=store)

    def test_theory_and_bank_do_not_require_resume_store(self):
        for modes, bank in [(("theory",), []), (("question_bank",), ["题目"] )]:
            context = build_direct_interview_context("JD", "旧简历", modes, bank, use_rag=True)
            self.assertEqual(context.resume_text, "")
