from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.services.document_parser import DocumentParseError
import test_interview_ui as ui_fixture
from test_interview_ui import choose


class UploadUITests(TestCase):
    """Exercise upload failures through the page's actual submit actions."""

    button = ui_fixture.InterviewUITests.button
    configure = ui_fixture.InterviewUITests.configure
    navigate = ui_fixture.InterviewUITests.navigate

    def setUp(self):
        ui_fixture.InterviewUITests.setUp(self)
        self.uploads = {}
        # AppTest has no upload setter, so replace only the file-input boundary.
        # The parsing failure, text widgets, callbacks and submit paths remain real.
        uploader = patch(
            "app.ui.session_widgets.st.file_uploader",
            side_effect=lambda label, **kwargs: self.uploads.get(
                kwargs["key"], [] if kwargs.get("accept_multiple_files") else None
            ),
        )
        uploader.start()
        self.addCleanup(uploader.stop)
        parser = patch(
            "app.ui.session_widgets.parse_document",
            side_effect=DocumentParseError("文件内容损坏"),
        )
        parser.start()
        self.addCleanup(parser.stop)

    def configure_bad_upload(self, text_key, *, combined):
        self.configure(combined=combined)
        self.app.run()
        if not combined:
            text_key = "direct_jd_text" if text_key == "job_description" else "direct_resume_text"
        self.input_key = text_key
        self.old_text = self.app.text_area(key=text_key).value
        upload_key = "jd_file" if text_key == "job_description" else "resume_file"
        self.uploads[upload_key] = SimpleNamespace(
            name="损坏文档.pdf", getvalue=lambda: b"not a valid PDF"
        )
        if not combined:
            namespace = "direct_jd" if text_key == "direct_jd_text" else "direct_resume"
            self.uploads = {f"{namespace}_files_0": [next(iter(self.uploads.values()))]}
            self.namespace = namespace
        self.start_label = "开始岗位分析" if combined else "开始模拟面试"
        self.button(self.start_label).click().run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any("文件解析失败" in item.value for item in self.app.error))
        self.assertEqual(self.app.text_area(key=text_key).value, self.old_text)
        self.workflow.run.assert_not_called()
        self.assertEqual(self.llm.prompts, [])

    def test_failed_jd_upload_blocks_analysis_and_preserves_old_text(self):
        self.configure_bad_upload("job_description", combined=True)

    def test_failed_resume_upload_blocks_analysis_and_preserves_old_text(self):
        self.configure_bad_upload("resume_text", combined=True)

    def test_failed_jd_upload_blocks_independent_interview_and_preserves_old_text(self):
        self.configure_bad_upload("job_description", combined=False)

    def test_failed_resume_upload_blocks_independent_interview_and_preserves_old_text(self):
        self.configure_bad_upload("resume_text", combined=False)

    def test_editing_retained_jd_recovers_analysis_with_explicit_new_text(self):
        self.configure_bad_upload("job_description", combined=True)
        self.app.text_area(key="job_description").set_value("手动确认的新岗位 JD")
        self.button(self.start_label).click().run()
        self.assertFalse(self.app.exception)
        self.assertFalse(any("文件解析失败" in item.value for item in self.app.error))
        self.workflow.run.assert_called_once()
        self.assertEqual(self.workflow.run.call_args.kwargs["job_description"], "手动确认的新岗位 JD")
        self.assertEqual(self.llm.prompts, [])

    def test_editing_retained_resume_recovers_interview_with_explicit_new_text(self):
        self.configure_bad_upload("resume_text", combined=False)
        self.uploads.clear()
        self.app.button(key=f"{self.namespace}_clear").click().run()
        self.app.text_area(key="direct_resume_text").set_value("手动确认的新简历与真实项目经历")
        self.llm.responses = [{"question": "首题", "question_source": "project"}]
        self.button(self.start_label).click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(
            self.app.session_state["interview_session"].context.resume_text,
            "手动确认的新简历与真实项目经历",
        )
        self.assertEqual(len(self.llm.prompts), 1)
        self.workflow.run.assert_not_called()

    def test_removing_bad_resume_file_allows_analysis_with_retained_text(self):
        self.configure_bad_upload("resume_text", combined=True)
        self.uploads.clear()
        self.button(self.start_label).click().run()
        self.assertFalse(self.app.exception)
        self.assertFalse(any("文件解析失败" in item.value for item in self.app.error))
        self.workflow.run.assert_called_once()
        self.assertEqual(self.workflow.run.call_args.kwargs["resume_text"], self.old_text)

    def test_removing_bad_jd_file_allows_interview_with_retained_text(self):
        self.configure_bad_upload("job_description", combined=False)
        self.uploads.clear()
        self.app.button(key=f"{self.namespace}_clear").click().run()
        self.llm.responses = [{"question": "首题", "question_source": "project"}]
        self.button(self.start_label).click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state["interview_session"].context.jd_analysis, self.old_text)
        self.assertEqual(len(self.llm.prompts), 1)
        self.workflow.run.assert_not_called()

    def test_resume_delete_confirmation_does_not_follow_a_different_resume(self):
        records = [
            SimpleNamespace(resume_id="a", file_name="A 简历.txt"),
            SimpleNamespace(resume_id="b", file_name="B 简历.txt"),
        ]
        self.store.list_records.side_effect = lambda: list(records)
        self.store.get.return_value = SimpleNamespace(text="完整简历正文")

        def delete_record(selected):
            records[:] = [record for record in records if record.resume_id != selected]

        self.store.delete.side_effect = delete_record
        self.navigate("资料库")
        choose(self.app, "library_delete_choices", ["a"])
        self.button("删除所选简历").click().run()
        self.store.delete.assert_not_called()
        self.assertTrue(any("A 简历.txt" in x.value for x in self.app.text))
        self.button("取消").click().run()
        self.store.delete.assert_not_called()
        choose(self.app, "library_delete_choices", ["b"])
        self.button("删除所选简历").click().run()
        self.store.delete.assert_not_called()
        self.button("确认删除").click().run()
        self.assertFalse(self.app.exception)
        self.store.delete.assert_called_once_with("b")
        self.assertTrue(self.button("删除所选简历").disabled)
