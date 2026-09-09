"""Resolve a new interview from saved analysis without repeating model analysis."""

from dataclasses import replace

from app.services.interview_session import (
    InterviewContext,
    InterviewSessionService,
    QUESTION_MODE_PROJECT,
    QUESTION_MODE_QUESTION_BANK,
    QUESTION_MODE_THEORY,
    QUESTION_MODES,
)
from app.storage.history_snapshots import restore_analysis, resume_fingerprint


def _read_resume_text(resume_store, resume_id: str) -> str:
    # ResumeStore IDs become filenames; do not allow a saved reference to escape
    # its library directory if a history record has been edited outside the app.
    if not isinstance(resume_id, str) or not resume_id or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for character in resume_id
    ):
        raise ValueError("历史简历引用无效，请重新提供或选择完整简历。")
    if resume_store is None:
        raise ValueError("无法读取简历库，请重新提供或选择完整简历。")
    try:
        record = resume_store.get(resume_id)
    except (KeyError, OSError, ValueError, TypeError) as error:
        raise ValueError("关联简历已删除或无法读取，请重新提供或选择完整简历。") from error
    text = getattr(record, "text", None)
    if not isinstance(text, str) or not text.strip():
        raise ValueError("所选简历没有有效正文，请重新提供或选择完整简历。")
    return text


def build_history_interview_context(
    payload: dict,
    question_modes: tuple[str, ...],
    question_bank: list[str] | None = None,
    *,
    resume_store=None,
    replacement_resume_text: str | None = None,
    replacement_resume_id: str | None = None,
    confirm_replacement: bool = False,
) -> InterviewContext:
    """Revalidate source material before a history record can generate questions.

    Saved analyses intentionally contain no resume body or reusable question
    bank. A matching library reference is the only automatic resume recovery;
    all other resume choices must be explicitly confirmed by the user.
    """
    if not question_modes:
        raise ValueError("请至少选择一种面试题目方式。")
    unsupported = set(question_modes) - QUESTION_MODES
    if unsupported:
        raise ValueError(f"不支持的题目方式：{', '.join(sorted(unsupported))}")
    result = restore_analysis(payload)
    job_description = payload.get("job_description", "")
    if not isinstance(job_description, str):
        raise ValueError("历史岗位 JD 格式无效。")
    has_job_description = bool(job_description.strip())
    if QUESTION_MODE_THEORY in question_modes and not has_job_description:
        raise ValueError("岗位技术理论面试需要先输入或上传岗位 JD。")
    current_bank = [item.strip() for item in (question_bank or []) if isinstance(item, str) and item.strip()]
    if QUESTION_MODE_QUESTION_BANK in question_modes and not current_bank:
        raise ValueError("选择自建题库时，请先上传包含有效题目的题库文件。")

    resume_text = ""
    reuse_analysis = False
    if QUESTION_MODE_PROJECT in question_modes:
        reference = payload.get("resume_ref") or {}
        if not isinstance(reference, dict):
            raise ValueError("历史简历引用格式无效，请重新提供或选择完整简历。")
        fingerprint = reference.get("fingerprint")
        replacement_text = replacement_resume_text or ""
        if not isinstance(replacement_text, str):
            raise ValueError("请提供有效的完整简历正文。")
        has_replacement_text = bool(replacement_text.strip())
        if replacement_resume_id and has_replacement_text:
            raise ValueError("请选择一份简历或提供简历正文，不要同时提供两种替代简历。")
        if replacement_resume_id or has_replacement_text:
            if not confirm_replacement:
                raise ValueError("请先确认使用重新提供或选择的完整简历。")
            resume_text = (
                _read_resume_text(resume_store, replacement_resume_id)
                if replacement_resume_id
                else replacement_text
            )
            reuse_analysis = resume_fingerprint(resume_text) == fingerprint
        else:
            original_id = reference.get("resume_id")
            if not original_id:
                raise ValueError("原分析使用临时简历，请重新提供或选择完整简历并确认使用。")
            resume_text = _read_resume_text(resume_store, original_id)
            if resume_fingerprint(resume_text) != fingerprint:
                raise ValueError("关联简历内容已变化，请重新提供或选择完整简历并确认使用。")
            reuse_analysis = True

    context = replace(
        InterviewContext.from_workflow_result(result, question_modes, current_bank),
        resume_text=resume_text,
        has_job_description=has_job_description,
    )
    if not reuse_analysis:
        context = replace(
            context,
            match_analysis=(
                "本次使用重新提供的简历，尚未对该简历执行岗位匹配分析；请仅依据当前完整简历出题。"
                if QUESTION_MODE_PROJECT in question_modes
                else "当前未选择项目经历题。"
            ),
            retrieved_context="",
            suggested_questions=[],
        )
    InterviewSessionService._validate_question_modes(context)
    return context
