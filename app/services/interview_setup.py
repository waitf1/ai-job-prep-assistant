"""Resolve standalone interview inputs without modifying the current session."""

from app.services.interview_session import (
    InterviewContext, InterviewSessionService, QUESTION_MODE_PROJECT,
)


def build_direct_interview_context(
    job_description, resume_text, question_modes, question_bank=None,
    *, use_rag=False, resume_store=None, preferred_resume_id=None,
):
    if use_rag:
        # Never reuse a hidden temporary resume from ordinary mode.
        resume_text = ""
        if QUESTION_MODE_PROJECT in question_modes:
            if resume_store is None:
                raise ValueError("请先在简历库添加完整简历。")
            records = resume_store.list_records()
            if not records:
                raise ValueError("简历库为空，请先添加完整简历。")
            if len(records) > 1 and not preferred_resume_id and not job_description.strip():
                raise ValueError("没有岗位 JD 时，请在左侧手动选择一份简历。")
            resume_text = resume_store.select(
                query=job_description.strip(), resume_id=preferred_resume_id,
            ).record.text
    context = InterviewContext.from_direct_input(
        job_description, resume_text, question_modes, question_bank,
    )
    InterviewSessionService._validate_question_modes(context)
    return context
