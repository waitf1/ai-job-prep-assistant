import json
import unittest

from app.llm.client import ToolChatResponse
from app.rag.resume_store import ResumeRecord, ResumeSelection
from app.rag.vector_store import RetrievedChunk
from app.services.job_prep_workflow import JobPrepWorkflow


class FakeLLMClient:
    def __init__(self, planner_response: ToolChatResponse) -> None:
        self.planner_response = planner_response
        self.chat_call_index = 0
        self.user_prompts: list[str] = []

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        self.user_prompts.append(user_prompt)
        if "项目证据审核员" in system_prompt:
            return json.dumps(
                {
                    "selected_indexes": [0],
                    "reason": "候选片段直接说明了与岗位要求相关的实现经验。",
                },
                ensure_ascii=False,
            )
        responses = [
            json.dumps(
                {
                    "responsibilities": ["完成 AI 应用原型开发"],
                    "required_skills": ["Python", "RAG", "Tool Calling"],
                    "bonus_points": ["Streamlit"],
                    "ai_keywords": ["大模型应用", "提示词工程"],
                    "interview_focus": ["项目实现细节"],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "matched_points": ["具备 Python 与大模型应用开发经验"],
                    "gaps": ["工程稳定性经验还需加强"],
                    "evidence_notes": ["已有 RAG 和工具调用相关项目经验"],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "direct_edits": ["突出 RAG 与工具调用实现经历"],
                    "future_edits": ["补充一次完整部署或评测经历"],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "questions": ["请说明你如何让模型决定是否检索资料库？"],
                    "short_term_focus": ["熟悉工具调用失败时的降级处理"],
                },
                ensure_ascii=False,
            ),
        ]
        response = responses[self.chat_call_index]
        self.chat_call_index += 1
        return response

    def chat_with_tools(self, system_prompt: str, user_prompt: str, tools: list[dict]) -> ToolChatResponse:
        return self.planner_response


class FakeKnowledgeBase:
    def __init__(self, chunks: list[RetrievedChunk], count_value: int | None = None) -> None:
        self.chunks = chunks
        self.count_value = count_value if count_value is not None else len(chunks)
        self.last_query = ""
        self.last_top_k = 0

    def count(self) -> int:
        return self.count_value

    def search(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        self.last_query = query
        self.last_top_k = top_k
        return self.chunks[:top_k]


class FakeResumeStore:
    def __init__(self, text: str) -> None:
        self.record = ResumeRecord(
            resume_id="resume-1",
            file_name="完整简历.txt",
            file_type="txt",
            text=text,
        )

    def select(self, query: str, resume_id: str | None = None) -> ResumeSelection:
        return ResumeSelection(
            record=self.record,
            mode="manual" if resume_id else "automatic",
            distance=None if resume_id else 0.18,
        )


class ModelDrivenToolCallingWorkflowTests(unittest.TestCase):
    def test_normal_mode_skips_planner_search(self) -> None:
        llm_client = FakeLLMClient(
            planner_response=ToolChatResponse(content="", tool_calls=[]),
        )
        workflow = JobPrepWorkflow(llm_client=llm_client)

        result = workflow.run(
            resume_text="我做过大模型应用项目。",
            job_description="招聘 AI 应用开发实习生，要求熟悉 Python 和 RAG。",
            use_rag=False,
        )

        self.assertFalse(result.planner_decision.should_search)
        self.assertEqual(result.retrieval_query, "")
        self.assertEqual(result.retrieved_chunks, [])
        self.assertEqual(
            [call.tool_name for call in result.tool_calls],
            [
                "analyze_job_description",
                "generate_resume_advice",
                "generate_interview_questions",
            ],
        )

    def test_rag_mode_executes_search_when_model_calls_tool(self) -> None:
        llm_client = FakeLLMClient(
            planner_response=ToolChatResponse(
                content="",
                tool_calls=[
                    {
                        "name": "search_project_knowledge_base",
                        "args": {"query": "RAG 项目经历 Streamlit Tool Calling"},
                    }
                ],
            ),
        )
        knowledge_base = FakeKnowledgeBase(
            chunks=[
                RetrievedChunk(
                    text="我实现过 Chroma 检索、资料去重以及工具调用记录展示。",
                    source="project_notes.txt",
                    chunk_index=0,
                    distance=0.12,
                )
            ]
        )
        workflow = JobPrepWorkflow(llm_client=llm_client, knowledge_base=knowledge_base)

        result = workflow.run(
            resume_text="我做过大模型应用项目。",
            job_description="招聘 AI 应用开发实习生，要求熟悉 Python 和 RAG。",
            use_rag=True,
        )

        self.assertTrue(result.planner_decision.should_search)
        self.assertTrue(result.planner_decision.used_tool_call)
        self.assertEqual(result.retrieval_query, "RAG 项目经历 Streamlit Tool Calling")
        self.assertEqual(len(result.retrieved_chunks), 1)
        self.assertEqual(knowledge_base.last_query, "RAG 项目经历 Streamlit Tool Calling")
        self.assertEqual(knowledge_base.last_top_k, 1)
        self.assertIn("search_project_knowledge_base", [call.tool_name for call in result.tool_calls])

    def test_rag_mode_can_skip_search_from_model_decision(self) -> None:
        llm_client = FakeLLMClient(
            planner_response=ToolChatResponse(
                content=json.dumps(
                    {
                        "use_search": False,
                        "reason": "当前输入已经足够完成本轮分析，无需额外检索资料库。",
                    },
                    ensure_ascii=False,
                ),
                tool_calls=[],
            ),
        )
        knowledge_base = FakeKnowledgeBase(
            chunks=[
                RetrievedChunk(
                    text="这条数据不应在本测试中被取回。",
                    source="project_notes.txt",
                    chunk_index=0,
                    distance=0.12,
                )
            ]
        )
        workflow = JobPrepWorkflow(llm_client=llm_client, knowledge_base=knowledge_base)

        result = workflow.run(
            resume_text="我做过大模型应用项目。",
            job_description="招聘 AI 应用开发实习生，要求熟悉 Python 和 RAG。",
            use_rag=True,
        )

        self.assertFalse(result.planner_decision.should_search)
        self.assertEqual(result.planner_decision.query, "")
        self.assertEqual(result.retrieval_query, "")
        self.assertEqual(result.retrieved_chunks, [])
        self.assertEqual(knowledge_base.last_query, "")
        self.assertNotIn("search_project_knowledge_base", [call.tool_name for call in result.tool_calls])

    def test_rag_mode_filters_irrelevant_chunks_before_analysis(self) -> None:
        llm_client = FakeLLMClient(
            planner_response=ToolChatResponse(
                content="",
                tool_calls=[
                    {
                        "name": "search_project_knowledge_base",
                        "args": {"query": "RAG 项目经历"},
                    }
                ],
            ),
        )
        relevant_chunk = RetrievedChunk(
            text="我实现过 Chroma 检索、资料去重以及工具调用记录展示。",
            source="relevant.txt",
            chunk_index=0,
            distance=0.12,
        )
        irrelevant_chunk = RetrievedChunk(
            text="这是一段与当前岗位无关的课程资料。",
            source="irrelevant.txt",
            chunk_index=0,
            distance=1.5,
        )
        knowledge_base = FakeKnowledgeBase(chunks=[relevant_chunk, irrelevant_chunk])
        workflow = JobPrepWorkflow(llm_client=llm_client, knowledge_base=knowledge_base)

        result = workflow.run(
            resume_text="我做过大模型应用项目。",
            job_description="招聘 AI 应用开发实习生，要求熟悉 Python 和 RAG。",
            use_rag=True,
        )

        self.assertEqual(result.raw_retrieved_chunks, [relevant_chunk, irrelevant_chunk])
        self.assertEqual(result.retrieved_chunks, [relevant_chunk])
        self.assertEqual(result.filtered_chunk_count, 1)
        self.assertEqual(result.retrieval_status, "retrieved")
        self.assertIn(relevant_chunk.text, result.retrieved_context)
        self.assertNotIn(irrelevant_chunk.text, result.retrieved_context)

    def test_rag_mode_degrades_when_all_chunks_are_filtered(self) -> None:
        llm_client = FakeLLMClient(
            planner_response=ToolChatResponse(
                content="",
                tool_calls=[
                    {
                        "name": "search_project_knowledge_base",
                        "args": {"query": "RAG 项目经历"},
                    }
                ],
            ),
        )
        irrelevant_chunk = RetrievedChunk(
            text="这是一段与当前岗位无关的课程资料。",
            source="irrelevant.txt",
            chunk_index=0,
            distance=1.5,
        )
        knowledge_base = FakeKnowledgeBase(chunks=[irrelevant_chunk])
        workflow = JobPrepWorkflow(llm_client=llm_client, knowledge_base=knowledge_base)

        result = workflow.run(
            resume_text="我做过大模型应用项目。",
            job_description="招聘 AI 应用开发实习生，要求熟悉 Python 和 RAG。",
            use_rag=True,
        )

        self.assertEqual(result.retrieved_chunks, [])
        self.assertEqual(result.filtered_chunk_count, 1)
        self.assertEqual(result.retrieval_status, "no_relevant_results")
        self.assertIn("后续分析不引用资料库内容", result.retrieved_context)

    def test_rag_mode_uses_selected_full_resume_without_project_library(self) -> None:
        full_resume = "简历前半部分\n简历后半部分：包含目标岗位需要的关键项目经验。"
        llm_client = FakeLLMClient(
            planner_response=ToolChatResponse(content="", tool_calls=[]),
        )
        workflow = JobPrepWorkflow(
            llm_client=llm_client,
            resume_store=FakeResumeStore(full_resume),
            project_knowledge_base=None,
        )

        result = workflow.run(
            resume_text="希望突出通用开发能力。",
            job_description="招聘通用软件开发实习生。",
            use_rag=True,
        )

        self.assertEqual(result.selected_resume.file_name, "完整简历.txt")
        self.assertEqual(result.retrieval_status, "skipped_by_model")
        downstream_prompts = "\n".join(llm_client.user_prompts[1:])
        self.assertIn("简历后半部分", downstream_prompts)
        self.assertIn("希望突出通用开发能力", downstream_prompts)


if __name__ == "__main__":
    unittest.main()
