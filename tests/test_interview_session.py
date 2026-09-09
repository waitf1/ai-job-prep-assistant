import json
import unittest

from app.services.interview_session import (
    InterviewContext,
    InterviewSessionService,
    MAX_INTERVIEW_ROUNDS,
    MIN_INTERVIEW_ROUNDS,
    QUESTION_MODE_QUESTION_BANK,
    QUESTION_MODE_THEORY,
)


class FakeInterviewLLM:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        self.prompts.append(user_prompt)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return json.dumps(response, ensure_ascii=False)


def make_context() -> InterviewContext:
    return InterviewContext(
        jd_analysis="必备技能：\n- Python\n- RAG",
        match_analysis="当前匹配点：\n- 具备项目经验",
        resume_text="候选人实现过 RAG 岗位助手。",
        retrieved_context="项目资料：实现了 Chroma 检索。",
        suggested_questions=["请介绍 RAG 项目的检索流程。"],
    )


def feedback(next_question: str) -> dict:
    return {
        "score": 80,
        "strengths": ["回答说明了实现思路"],
        "improvements": ["补充量化结果"],
        "answer_structure": ["背景", "做法", "结果"],
        "overall_feedback": "回答基础扎实。",
        "next_question": next_question,
        "next_question_source": "project",
    }


class InterviewSessionServiceTests(unittest.TestCase):
    def test_completes_three_round_interview_and_generates_summary(self) -> None:
        llm = FakeInterviewLLM(
            [
                {"question": "请介绍你的 RAG 项目。", "question_source": "project"},
                feedback("你如何控制检索质量？"),
                feedback("Tool Calling 在其中有什么作用？"),
                feedback(""),
                {
                    "strengths": ["能说明 RAG 基础链路"],
                    "weaknesses": ["指标量化不足"],
                    "answer_structure_advice": ["使用 STAR 结构"],
                    "practice_plan": ["练习解释召回与重排序"],
                    "overall_summary": "具备基础项目表达能力。",
                },
            ]
        )
        service = InterviewSessionService(llm_client=llm)

        session = service.start(make_context(), max_rounds=3)
        first_feedback = service.submit_answer(session, "我先解析文档并建立向量库。")
        service.submit_answer(session, "我使用距离阈值和 AI 重排序。")
        service.submit_answer(session, "工具负责统一执行检索。")

        self.assertEqual(first_feedback.score, 80)
        self.assertEqual(len(session.rounds), 3)
        self.assertEqual(session.status, "completed")
        self.assertIsNotNone(session.summary)
        self.assertEqual(session.summary.weaknesses, ["指标量化不足"])

    def test_rejects_blank_answer_and_invalid_round_limit(self) -> None:
        llm = FakeInterviewLLM([{"question": "问题", "question_source": "project"}])
        service = InterviewSessionService(llm_client=llm)
        with self.assertRaises(ValueError):
            service.start(make_context(), max_rounds=MIN_INTERVIEW_ROUNDS - 1)
        with self.assertRaises(ValueError):
            service.start(make_context(), max_rounds=MAX_INTERVIEW_ROUNDS + 1)

        session = service.start(make_context(), max_rounds=3)
        with self.assertRaises(ValueError):
            service.submit_answer(session, "  ")
        self.assertEqual(len(llm.prompts), 1)

    def test_honest_no_experience_answer_is_sent_to_the_model(self) -> None:
        llm = FakeInterviewLLM(
            [
                {"question": "你有相关经历吗？", "question_source": "project"},
                feedback("你准备如何补足这项能力？"),
            ]
        )
        service = InterviewSessionService(llm_client=llm)
        session = service.start(make_context(), max_rounds=3)

        service.submit_answer(session, "没有相关经历。")

        self.assertEqual(session.rounds[0].answer, "没有相关经历。")
        self.assertEqual(len(llm.prompts), 2)

    def test_can_finish_early_after_one_round(self) -> None:
        llm = FakeInterviewLLM(
            [
                {"question": "请介绍项目。", "question_source": "project"},
                feedback("你如何测试它？"),
                {
                    "strengths": ["项目描述清晰"],
                    "weaknesses": ["缺少细节"],
                    "answer_structure_advice": ["补充结果"],
                    "practice_plan": ["复盘项目指标"],
                    "overall_summary": "需要继续练习。",
                },
            ]
        )
        service = InterviewSessionService(llm_client=llm)
        session = service.start(make_context(), max_rounds=3)
        service.submit_answer(session, "我负责资料库检索。")
        summary = service.finish(session)

        self.assertEqual(session.status, "completed")
        self.assertEqual(summary.practice_plan, ["复盘项目指标"])

    def test_question_bank_only_requires_uploaded_questions(self) -> None:
        context = InterviewContext.from_direct_input(
            job_description="招聘 AI 应用开发实习生",
            resume_text="",
            question_modes=(QUESTION_MODE_QUESTION_BANK,),
        )
        service = InterviewSessionService(
            llm_client=FakeInterviewLLM([{"question": "无效", "question_source": "project"}])
        )

        with self.assertRaises(ValueError):
            service.start(context)

    def test_theory_mode_requires_job_description(self) -> None:
        context = InterviewContext.from_direct_input(
            job_description="",
            resume_text="",
            question_modes=(QUESTION_MODE_THEORY,),
        )
        service = InterviewSessionService(
            llm_client=FakeInterviewLLM([{"question": "不应调用模型", "question_source": "project"}])
        )

        with self.assertRaisesRegex(ValueError, "岗位 JD"):
            service.start(context)

    def test_direct_context_keeps_selected_modes_and_question_bank(self) -> None:
        context = InterviewContext.from_direct_input(
            job_description="招聘 AI 应用开发实习生",
            resume_text="",
            question_modes=(QUESTION_MODE_THEORY, QUESTION_MODE_QUESTION_BANK),
            question_bank=["什么是 RAG？"],
        )

        self.assertEqual(context.question_modes, (QUESTION_MODE_THEORY, QUESTION_MODE_QUESTION_BANK))
        self.assertEqual(context.question_bank, ["什么是 RAG？"])

    def test_model_cannot_select_unapproved_question_source(self) -> None:
        context = InterviewContext.from_direct_input(
            job_description="要求掌握 Python 和 RAG",
            resume_text="包含不应进入理论题上下文的项目经历",
            question_modes=(QUESTION_MODE_THEORY,),
        )
        llm = FakeInterviewLLM(
            [{"question": "什么是向量检索？", "question_source": "project"}]
        )

        with self.assertRaisesRegex(ValueError, "题目来源"):
            InterviewSessionService(llm_client=llm).start(context)
        self.assertNotIn("不应进入理论题上下文", llm.prompts[0])
        self.assertIn("禁止提出项目经历问题", llm.prompts[0])

    def test_project_requires_resume_before_calling_model(self):
        for modes in (("project",), ("theory", "project")):
            context = InterviewContext.from_direct_input("JD", "  ", modes)
            llm = FakeInterviewLLM([])
            with self.assertRaisesRegex(ValueError, "完整简历"):
                InterviewSessionService(llm).start(context)
            self.assertEqual(llm.prompts, [])

    def test_summary_failure_blocks_answers_and_retry_does_not_duplicate(self):
        llm = FakeInterviewLLM([
            {"question": "首题", "question_source": "project"},
            feedback("第二题"), feedback("第三题"), feedback(""),
            RuntimeError("offline"), {"overall_summary": "完成"},
        ])
        service = InterviewSessionService(llm)
        session = service.start(make_context())
        service.submit_answer(session, "  原始回答\n")
        service.submit_answer(session, "第二答")
        with self.assertRaisesRegex(RuntimeError, "offline"):
            service.submit_answer(session, "第三答")
        self.assertEqual(session.status, "summary_pending")
        self.assertEqual(session.rounds[0].answer, "  原始回答\n")
        self.assertEqual(len(session.rounds), 3)
        calls = len(llm.prompts)
        with self.assertRaises(ValueError):
            service.submit_answer(session, "重复回答")
        self.assertEqual(len(llm.prompts), calls)
        service.finish(session)
        service.finish(session)
        self.assertEqual(len(llm.prompts), calls + 1)
        self.assertEqual(len(session.rounds), 3)
        self.assertEqual(session.status, "completed")

    def test_invalid_next_source_does_not_mutate_round(self):
        bad_feedback = feedback("越界题")
        bad_feedback["next_question_source"] = "unknown"
        llm = FakeInterviewLLM([
            {"question": "首题", "question_source": "project"}, bad_feedback,
        ])
        service = InterviewSessionService(llm)
        session = service.start(make_context())
        with self.assertRaisesRegex(ValueError, "题目来源"):
            service.submit_answer(session, "回答")
        self.assertEqual(session.rounds, [])
        self.assertEqual(session.current_question, "首题")

    def test_missing_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "题目来源"):
            InterviewSessionService(FakeInterviewLLM([{"question": "首题"}])).start(make_context())

    def test_mixed_empty_question_bank_rejected(self):
        context = InterviewContext.from_direct_input("JD", "", ("theory", "question_bank"))
        with self.assertRaisesRegex(ValueError, "题库"):
            InterviewSessionService(FakeInterviewLLM([])).start(context)

    def test_early_finish_failure_can_retry(self):
        llm = FakeInterviewLLM([
            {"question": "首题", "question_source": "project"}, feedback("第二题"),
            RuntimeError("offline"), {"overall_summary": "完成"},
        ])
        service = InterviewSessionService(llm)
        session = service.start(make_context())
        service.submit_answer(session, "回答")
        with self.assertRaises(RuntimeError):
            service.finish(session)
        self.assertEqual(session.status, "summary_pending")
        service.finish(session)
        self.assertEqual(len(session.rounds), 1)


if __name__ == "__main__":
    unittest.main()
