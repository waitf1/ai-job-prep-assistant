from app.llm import LLMClient
from app.rag import (
    DEFAULT_DISTANCE_GAP_THRESHOLD,
    DEFAULT_MAX_RETRIEVAL_DISTANCE,
    DEFAULT_MAX_SELECTED_CHUNKS,
    DEFAULT_RETRIEVAL_CANDIDATE_LIMIT,
    ProfileKnowledgeBase,
    ResumeStore,
    RetrievedChunk,
    select_retrieved_chunks,
)
from app.services.interview_preparer import InterviewPreparer
from app.services.jd_analyzer import JDAnalyzer
from app.services.match_analyzer import JobMatchAnalyzer
from app.services.retrieval_reranker import RetrievalReranker
from app.services.resume_advisor import ResumeAdvisor
from app.services.tool_planner import ToolPlanner
from app.services.workflow_types import (
    PlannerDecisionResult,
    SelectedResumeResult,
    WorkflowRunResult,
)
from app.tools.analysis_tools import (
    AnalyzeJobDescriptionTool,
    GenerateInterviewQuestionsTool,
    GenerateResumeAdviceTool,
)
from app.tools.knowledge_base_tools import SearchProjectKnowledgeBaseTool
from app.tools.tool_types import ToolExecutionContext, ToolResult


def format_retrieved_context(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return ""

    parts = []
    for index, chunk in enumerate(chunks, start=1):
        parts.append(
            "\n".join(
                [
                    f"[片段 {index}]",
                    f"来源：{chunk.source}",
                    f"章节：{chunk.section_title}",
                    f"片段编号：{chunk.chunk_index}",
                    f"距离：{chunk.distance:.4f}" if chunk.distance is not None else "距离：未知",
                    "内容：",
                    chunk.text,
                ]
            )
        )
    return "\n\n".join(parts)


class JobPrepWorkflow:
    """Fixed-order workflow for job preparation analysis."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        knowledge_base: ProfileKnowledgeBase | None = None,
        resume_store: ResumeStore | None = None,
        project_knowledge_base: ProfileKnowledgeBase | None = None,
    ) -> None:
        llm_client = llm_client or LLMClient()
        self.resume_store = resume_store
        self.project_knowledge_base = project_knowledge_base or knowledge_base
        self.jd_analyzer = JDAnalyzer(llm_client=llm_client)
        self.match_analyzer = JobMatchAnalyzer(llm_client=llm_client)
        self.retrieval_reranker = RetrievalReranker(llm_client=llm_client)
        self.resume_advisor = ResumeAdvisor(llm_client=llm_client)
        self.interview_preparer = InterviewPreparer(llm_client=llm_client)
        self.tool_planner = ToolPlanner(llm_client=llm_client)
        self.jd_tool = AnalyzeJobDescriptionTool(self.jd_analyzer)
        self.resume_advice_tool = GenerateResumeAdviceTool(self.resume_advisor)
        self.interview_questions_tool = GenerateInterviewQuestionsTool(self.interview_preparer)
        self.search_tool = (
            SearchProjectKnowledgeBaseTool(self.project_knowledge_base)
            if self.project_knowledge_base is not None
            else None
        )

    def run(
        self,
        resume_text: str,
        job_description: str,
        use_rag: bool = False,
        preferred_resume_id: str | None = None,
    ) -> WorkflowRunResult:
        tool_context = ToolExecutionContext()
        jd_analysis = self._consume_tool_result(
            tool_context,
            self.jd_tool.run(job_description=job_description),
        )
        selected_resume: SelectedResumeResult | None = None
        effective_resume_text = resume_text
        if use_rag and self.resume_store is not None:
            selection = self.resume_store.select(
                query=jd_analysis.as_query_text() or job_description,
                resume_id=preferred_resume_id,
            )
            selected_resume = SelectedResumeResult(
                resume_id=selection.record.resume_id,
                file_name=selection.record.file_name,
                selection_mode=selection.mode,
                distance=selection.distance,
            )
            effective_resume_text = selection.record.text
            supplementary_note = resume_text.strip()
            if supplementary_note:
                effective_resume_text += f"\n\n【用户补充说明】\n{supplementary_note}"

        retrieved_chunks: list[RetrievedChunk] = []
        raw_retrieved_chunks: list[RetrievedChunk] = []
        retrieved_context = ""
        retrieval_query = ""
        retrieval_candidate_limit: int | None = None
        max_retrieval_distance: float | None = None
        filtered_chunk_count = 0
        gap_truncated_chunks: list[RetrievedChunk] = []
        gap_truncated_chunk_count = 0
        content_filtered_chunks: list[RetrievedChunk] = []
        content_filtered_chunk_count = 0
        distance_filtered_chunks: list[RetrievedChunk] = []
        ai_rerank_excluded_chunks: list[RetrievedChunk] = []
        ai_rerank_excluded_chunk_count = 0
        ai_rerank_reason = ""
        ai_rerank_failed = False
        retrieval_status = "not_requested"
        retrieval_message = "当前为普通分析模式，未请求资料库检索。"
        planner_decision = PlannerDecisionResult(
            should_search=False,
            query="",
            reason="当前为普通分析模式，默认跳过资料库检索。",
            used_tool_call=False,
            raw_output="",
        )

        if use_rag:
            knowledge_base_available = (
                self.project_knowledge_base is not None
                and self.search_tool is not None
                and self.project_knowledge_base.count() > 0
            )
            planner_decision = self.tool_planner.analyze(
                resume_text=effective_resume_text,
                job_description=job_description,
                jd_analysis=jd_analysis,
                mode_name="RAG 资料库模式",
                knowledge_base_available=knowledge_base_available,
                search_tool=self.search_tool,
            )

            if planner_decision.should_search and self.search_tool is not None:
                retrieval_query = planner_decision.query.strip() or jd_analysis.as_query_text().strip() or job_description.strip()
                max_retrieval_distance = DEFAULT_MAX_RETRIEVAL_DISTANCE
                retrieval_candidate_limit = min(
                    self.project_knowledge_base.count()
                    if self.project_knowledge_base is not None
                    else 0,
                    DEFAULT_RETRIEVAL_CANDIDATE_LIMIT,
                )
                raw_retrieved_chunks = self._consume_tool_result(
                    tool_context,
                    self.search_tool.run(
                        query=retrieval_query,
                        candidate_limit=retrieval_candidate_limit,
                    ),
                )
                selection = select_retrieved_chunks(
                    raw_retrieved_chunks,
                    max_distance=max_retrieval_distance,
                    max_chunks=DEFAULT_MAX_SELECTED_CHUNKS,
                    distance_gap_threshold=DEFAULT_DISTANCE_GAP_THRESHOLD,
                )
                content_filtered_chunks = selection.content_filtered_chunks
                distance_filtered_chunks = selection.distance_filtered_chunks
                gap_truncated_chunks = selection.gap_truncated_chunks
                filtered_chunk_count = len(distance_filtered_chunks)
                content_filtered_chunk_count = len(content_filtered_chunks)
                gap_truncated_chunk_count = len(gap_truncated_chunks)
                ai_candidates = [
                    chunk
                    for chunk in raw_retrieved_chunks
                    if chunk not in content_filtered_chunks
                    and chunk not in distance_filtered_chunks
                ]
                rerank_result = self.retrieval_reranker.rerank(
                    chunks=ai_candidates,
                    jd_analysis=jd_analysis,
                    resume_text=effective_resume_text,
                    max_chunks=DEFAULT_MAX_SELECTED_CHUNKS,
                    fallback_chunks=selection.selected_chunks,
                )
                retrieved_chunks = rerank_result.selected_chunks
                ai_rerank_excluded_chunks = rerank_result.excluded_chunks
                ai_rerank_excluded_chunk_count = len(ai_rerank_excluded_chunks)
                ai_rerank_reason = rerank_result.reason
                ai_rerank_failed = rerank_result.review_failed

                if retrieved_chunks:
                    retrieval_status = "retrieved"
                    retrieval_message = f"系统自动采用 {len(retrieved_chunks)} 个相关资料片段。"
                    retrieved_context = format_retrieved_context(retrieved_chunks)
                elif raw_retrieved_chunks:
                    retrieval_status = "no_relevant_results"
                    retrieval_message = (
                        "模型已请求检索，但召回片段均未达到相关性要求，"
                        "后续分析未引用资料库内容。"
                    )
                    retrieved_context = "本次未检索到足够相关的资料片段，后续分析不引用资料库内容。"
                else:
                    retrieval_status = "no_results"
                    retrieval_message = "模型已请求检索，但资料库未返回任何片段。"
                    retrieved_context = "本次未检索到相关资料片段，后续分析不引用资料库内容。"
            else:
                retrieval_status = "skipped_by_model"
                retrieval_message = planner_decision.reason

        match_analysis = self.match_analyzer.analyze(
            resume_text=effective_resume_text,
            job_description=job_description,
            jd_analysis=jd_analysis,
            retrieved_context=retrieved_context,
        )
        resume_advice = self._consume_tool_result(
            tool_context,
            self.resume_advice_tool.run(
                resume_text=effective_resume_text,
                jd_analysis=jd_analysis,
                match_analysis=match_analysis,
                retrieved_context=retrieved_context,
            ),
        )
        interview_prep = self._consume_tool_result(
            tool_context,
            self.interview_questions_tool.run(
                resume_text=effective_resume_text,
                jd_analysis=jd_analysis,
                match_analysis=match_analysis,
                retrieved_context=retrieved_context,
            ),
        )

        return WorkflowRunResult(
            jd_analysis=jd_analysis,
            effective_resume_text=effective_resume_text,
            selected_resume=selected_resume,
            raw_retrieved_chunks=raw_retrieved_chunks,
            retrieved_chunks=retrieved_chunks,
            content_filtered_chunks=content_filtered_chunks,
            distance_filtered_chunks=distance_filtered_chunks,
            gap_truncated_chunks=gap_truncated_chunks,
            ai_rerank_excluded_chunks=ai_rerank_excluded_chunks,
            retrieved_context=retrieved_context,
            retrieval_query=retrieval_query,
            retrieval_candidate_limit=retrieval_candidate_limit,
            max_retrieval_distance=max_retrieval_distance,
            content_filtered_chunk_count=content_filtered_chunk_count,
            filtered_chunk_count=filtered_chunk_count,
            gap_truncated_chunk_count=gap_truncated_chunk_count,
            ai_rerank_excluded_chunk_count=ai_rerank_excluded_chunk_count,
            ai_rerank_reason=ai_rerank_reason,
            ai_rerank_failed=ai_rerank_failed,
            retrieval_status=retrieval_status,
            retrieval_message=retrieval_message,
            planner_decision=planner_decision,
            match_analysis=match_analysis,
            resume_advice=resume_advice,
            interview_prep=interview_prep,
            tool_calls=tool_context.records,
        )

    @staticmethod
    def _consume_tool_result(tool_context: ToolExecutionContext, result: ToolResult):
        tool_context.add_result(result)
        if not result.success:
            raise RuntimeError(f"工具 {result.tool_name} 执行失败：{result.error_message}")
        return result.data
