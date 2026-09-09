from dataclasses import dataclass, field
from pathlib import Path

from app.llm import LLMClient
from app.services.prompt_utils import ensure_string_list, load_prompt, parse_json_response
from app.services.workflow_types import WorkflowRunResult


MIN_INTERVIEW_ROUNDS = 1
MAX_INTERVIEW_ROUNDS = 10
QUESTION_MODE_THEORY = "theory"
QUESTION_MODE_PROJECT = "project"
QUESTION_MODE_QUESTION_BANK = "question_bank"
QUESTION_MODES = {
    QUESTION_MODE_THEORY,
    QUESTION_MODE_PROJECT,
    QUESTION_MODE_QUESTION_BANK,
}


@dataclass(frozen=True)
class InterviewContext:
    jd_analysis: str
    match_analysis: str
    resume_text: str
    retrieved_context: str
    suggested_questions: list[str]
    question_modes: tuple[str, ...] = (QUESTION_MODE_THEORY, QUESTION_MODE_PROJECT)
    question_bank: list[str] = field(default_factory=list)
    has_job_description: bool = True

    @classmethod
    def from_workflow_result(
        cls,
        result: WorkflowRunResult,
        question_modes: tuple[str, ...] = (QUESTION_MODE_THEORY, QUESTION_MODE_PROJECT),
        question_bank: list[str] | None = None,
    ) -> "InterviewContext":
        return cls(
            jd_analysis=result.jd_analysis.to_prompt_text(),
            match_analysis=(
                result.match_analysis.to_prompt_text()
                if result.match_analysis is not None
                else "暂无匹配分析。"
            ),
            resume_text=result.effective_resume_text,
            retrieved_context=result.retrieved_context or "本次未使用项目资料库补充证据。",
            suggested_questions=(
                result.interview_prep.questions if result.interview_prep is not None else []
            ),
            question_modes=question_modes,
            question_bank=question_bank or [],
            has_job_description=True,
        )

    @classmethod
    def from_direct_input(
        cls,
        job_description: str,
        resume_text: str,
        question_modes: tuple[str, ...],
        question_bank: list[str] | None = None,
    ) -> "InterviewContext":
        return cls(
            jd_analysis=job_description.strip() or "未提供岗位 JD。",
            match_analysis="本次为独立模拟面试，未执行岗位匹配分析。",
            resume_text=resume_text.strip(),
            retrieved_context="本次未使用项目资料库补充证据。",
            suggested_questions=[],
            question_modes=question_modes,
            question_bank=question_bank or [],
            has_job_description=bool(job_description.strip()),
        )


@dataclass(frozen=True)
class InterviewFeedback:
    score: int
    strengths: list[str]
    improvements: list[str]
    answer_structure: list[str]
    overall_feedback: str


@dataclass(frozen=True)
class InterviewRound:
    question: str
    question_source: str
    answer: str
    feedback: InterviewFeedback


@dataclass(frozen=True)
class InterviewSummary:
    strengths: list[str]
    weaknesses: list[str]
    answer_structure_advice: list[str]
    practice_plan: list[str]
    overall_summary: str


@dataclass
class InterviewSession:
    context: InterviewContext
    max_rounds: int | None
    current_question: str
    current_question_source: str
    rounds: list[InterviewRound] = field(default_factory=list)
    status: str = "active"
    summary: InterviewSummary | None = None

    @property
    def current_round_number(self) -> int:
        return len(self.rounds) + 1


class InterviewSessionService:
    """Run a code-bounded multi-round interview session."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()
        self.prompt_dir = Path(__file__).resolve().parents[2] / "prompts"

    def start(self, context: InterviewContext, max_rounds: int | None = 3) -> InterviewSession:
        self._validate_round_limit(max_rounds)
        self._validate_question_modes(context)
        response = self.llm_client.chat(
            load_prompt(self.prompt_dir, "interview_session_start_system.txt"),
            load_prompt(self.prompt_dir, "interview_session_start_user.txt").format(
                context=self._format_context(context),
            ),
        )
        parsed = parse_json_response(response)
        question = str(parsed.get("question", "")).strip()
        if not question:
            raise ValueError("模型未生成有效的首个面试问题。")
        question_source = self._normalize_question_source(
            parsed.get("question_source"),
            context.question_modes,
        )
        return InterviewSession(
            context=context,
            max_rounds=max_rounds,
            current_question=question,
            current_question_source=question_source,
        )

    def submit_answer(self, session: InterviewSession, answer: str) -> InterviewFeedback:
        if session.status != "active" or (session.max_rounds is not None and len(session.rounds) >= session.max_rounds):
            raise ValueError("当前面试已结束，请重新开始。")
        self._validate_answer(answer.strip())

        response = self.llm_client.chat(
            load_prompt(self.prompt_dir, "interview_session_turn_system.txt"),
            load_prompt(self.prompt_dir, "interview_session_turn_user.txt").format(
                context=self._format_context(session.context),
                history=self._format_history(session.rounds),
                round_number=session.current_round_number,
                question=session.current_question,
                question_source=session.current_question_source,
                answer=answer,
                should_generate_next_question=session.max_rounds is None or len(session.rounds) + 1 < session.max_rounds,
            ),
        )
        parsed = parse_json_response(response)
        feedback = self._parse_feedback(parsed)
        has_next_round = session.max_rounds is None or len(session.rounds) + 1 < session.max_rounds
        next_question = ""
        next_question_source = ""
        if has_next_round:
            next_question = str(parsed.get("next_question", "")).strip()
            if not next_question:
                raise ValueError("模型未生成下一轮面试问题。")
            next_question_source = self._normalize_question_source(
                parsed.get("next_question_source"),
                session.context.question_modes,
            )

        session.rounds.append(
            InterviewRound(
                question=session.current_question,
                question_source=session.current_question_source,
                answer=answer,
                feedback=feedback,
            )
        )
        if has_next_round:
            session.current_question = next_question
            session.current_question_source = next_question_source
        else:
            self.finish(session)
        return feedback

    def finish(self, session: InterviewSession) -> InterviewSummary:
        if session.summary is not None:
            return session.summary
        if not session.rounds:
            raise ValueError("至少完成一轮问答后才能结束面试。")

        # Once ending is requested, only summary retries are allowed.
        session.status = "summary_pending"
        response = self.llm_client.chat(
            load_prompt(self.prompt_dir, "interview_session_summary_system.txt"),
            load_prompt(self.prompt_dir, "interview_session_summary_user.txt").format(
                context=self._format_context(session.context),
                history=self._format_summary_history(session.rounds),
            ),
        )
        parsed = parse_json_response(response)
        summary = InterviewSummary(
            strengths=ensure_string_list(parsed, "strengths"),
            weaknesses=ensure_string_list(parsed, "weaknesses"),
            answer_structure_advice=ensure_string_list(parsed, "answer_structure_advice"),
            practice_plan=ensure_string_list(parsed, "practice_plan"),
            overall_summary=str(parsed.get("overall_summary", "")).strip(),
        )
        session.summary = summary
        session.status = "completed"
        return summary

    @staticmethod
    def _validate_round_limit(max_rounds: int | None) -> None:
        if max_rounds is None:
            return
        if type(max_rounds) is not int or not MIN_INTERVIEW_ROUNDS <= max_rounds <= MAX_INTERVIEW_ROUNDS:
            raise ValueError(
                f"面试轮数必须在 {MIN_INTERVIEW_ROUNDS} 到 {MAX_INTERVIEW_ROUNDS} 之间。"
            )

    @staticmethod
    def _validate_question_modes(context: InterviewContext) -> None:
        if not context.question_modes:
            raise ValueError("请至少选择一种面试题目方式。")
        unsupported = set(context.question_modes) - QUESTION_MODES
        if unsupported:
            raise ValueError(f"不支持的题目方式：{', '.join(sorted(unsupported))}")
        if (
            QUESTION_MODE_QUESTION_BANK in context.question_modes
            and not context.question_bank
        ):
            raise ValueError("选择自建题库时，请先上传包含有效题目的题库文件。")
        if QUESTION_MODE_THEORY in context.question_modes and not context.has_job_description:
            raise ValueError("岗位技术理论面试需要先输入或上传岗位 JD。")
        if QUESTION_MODE_PROJECT in context.question_modes and not context.resume_text.strip():
            raise ValueError("简历项目经历面试需要提供真实的完整简历。")

    @staticmethod
    def _validate_answer(answer: str) -> None:
        if not answer:
            raise ValueError("请先输入你的回答。")

    @staticmethod
    def _normalize_question_source(
        raw_source: object,
        allowed_modes: tuple[str, ...],
    ) -> str:
        source = str(raw_source or "").strip().lower()
        if source in allowed_modes:
            return source
        raise ValueError("模型返回的题目来源缺失或不在已选范围，请重试。")

    @staticmethod
    def _parse_feedback(data: dict) -> InterviewFeedback:
        score = data.get("score")
        if type(score) is not int or not 0 <= score <= 100:
            raise ValueError("面试分数必须是 0–100 的整数。")
        for key in ("strengths", "improvements", "answer_structure"):
            if key not in data:
                raise ValueError(f"面试反馈缺少 {key}。")
        if not isinstance(data.get("overall_feedback"), str) or not data["overall_feedback"].strip():
            raise ValueError("面试反馈缺少有效的整体评价。")
        return InterviewFeedback(
            score=score,
            strengths=ensure_string_list(data, "strengths"),
            improvements=ensure_string_list(data, "improvements"),
            answer_structure=ensure_string_list(data, "answer_structure"),
            overall_feedback=str(data.get("overall_feedback", "")).strip(),
        )

    @staticmethod
    def _format_context(context: InterviewContext) -> str:
        parts = [
            f"可用出题方式（严格白名单）：\n{', '.join(context.question_modes)}",
            f"岗位要求：\n{context.jd_analysis}",
        ]
        if QUESTION_MODE_PROJECT in context.question_modes:
            suggested_questions = "\n".join(
                f"- {question}" for question in context.suggested_questions
            ) or "- 暂无预生成问题。"
            parts.extend(
                [
                    f"匹配分析：\n{context.match_analysis}",
                    f"简历：\n{context.resume_text}",
                    f"项目证据：\n{context.retrieved_context}",
                    f"建议考察方向：\n{suggested_questions}",
                ]
            )
        else:
            parts.append("项目资料：当前未选择 project，禁止提出项目经历问题。")
        if QUESTION_MODE_QUESTION_BANK in context.question_modes:
            parts.append(
                "用户自建题库：\n"
                f"{InterviewSessionService._format_question_bank(context.question_bank)}"
            )
        return "\n\n".join(parts)

    @staticmethod
    def _format_question_bank(questions: list[str]) -> str:
        return "\n".join(f"- {question}" for question in questions) or "题库为空。"

    @staticmethod
    def _format_history(rounds: list[InterviewRound]) -> str:
        if not rounds:
            return "尚未进行问答。"
        parts = ["以下仅包含最近 8 轮；单轮长文本会截断，更早记录仍保存在页面。不得推断未提供的内容。"]
        for index, item in enumerate(rounds[-8:], start=max(1, len(rounds) - 7)):
            parts.append(
                "\n".join(
                    [
                        f"第 {index} 轮问题：{item.question[:1000]}",
                        f"用户回答：{item.answer[:3000]}",
                        f"本轮反馈：{item.feedback.overall_feedback[:1000]}",
                    ]
                )
            )
        return "\n\n".join(parts)

    @staticmethod
    def _format_summary_history(rounds):
        # Summaries sample across the whole session instead of only recent turns.
        indexes = list(range(len(rounds)))
        if len(indexes) > 50:
            indexes = sorted({round(i * (len(rounds) - 1) / 49) for i in range(50)})
        parts = [f"共 {len(rounds)} 轮；以下覆盖全程的 {len(indexes)} 轮摘录，文本可能截断。仅评价可见内容，不推断省略内容。"]
        for i in indexes:
            item = rounds[i]
            parts.append(f"第 {i+1} 轮：{item.question[:120]}\n回答：{item.answer[:250]}\n评分：{item.feedback.score}\n反馈：{item.feedback.overall_feedback[:180]}")
        return "\n\n".join(parts)
