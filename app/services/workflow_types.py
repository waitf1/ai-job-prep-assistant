from dataclasses import dataclass, field

from app.rag.vector_store import RetrievedChunk
from app.tools.tool_types import ToolCallRecord


@dataclass(frozen=True)
class JDAnalysisResult:
    responsibilities: list[str]
    required_skills: list[str]
    bonus_points: list[str]
    ai_keywords: list[str]
    interview_focus: list[str]
    raw_output: str

    def as_query_text(self) -> str:
        parts = [
            "岗位职责：",
            *self.responsibilities,
            "必备技能：",
            *self.required_skills,
            "加分项：",
            *self.bonus_points,
            "AI关键词：",
            *self.ai_keywords,
        ]
        return "\n".join(part for part in parts if part)

    def to_prompt_text(self) -> str:
        sections = [
            ("岗位职责", self.responsibilities),
            ("必备技能", self.required_skills),
            ("加分项", self.bonus_points),
            ("AI 关键词", self.ai_keywords),
            ("面试关注点", self.interview_focus),
        ]
        lines: list[str] = []
        for title, items in sections:
            lines.append(f"{title}：")
            if items:
                lines.extend(f"- {item}" for item in items)
            else:
                lines.append("- 无")
        return "\n".join(lines)


@dataclass(frozen=True)
class MatchAnalysisResult:
    matched_points: list[str]
    gaps: list[str]
    evidence_notes: list[str]
    raw_output: str
    citations: list[dict] = field(default_factory=list)

    def to_prompt_text(self) -> str:
        sections = [
            ("当前匹配点", self.matched_points),
            ("当前缺口", self.gaps),
            ("证据说明", self.evidence_notes),
        ]
        lines: list[str] = []
        for title, items in sections:
            lines.append(f"{title}：")
            if items:
                lines.extend(f"- {item}" for item in items)
            else:
                lines.append("- 无")
        return "\n".join(lines)


@dataclass(frozen=True)
class ResumeAdviceResult:
    direct_edits: list[str]
    future_edits: list[str]
    raw_output: str

    def to_prompt_text(self) -> str:
        sections = [
            ("当前可以直接修改的表达", self.direct_edits),
            ("完成补充项目后可新增的表达", self.future_edits),
        ]
        lines: list[str] = []
        for title, items in sections:
            lines.append(f"{title}：")
            if items:
                lines.extend(f"- {item}" for item in items)
            else:
                lines.append("- 无")
        return "\n".join(lines)


@dataclass(frozen=True)
class InterviewPrepResult:
    questions: list[str]
    short_term_focus: list[str]
    raw_output: str

    def to_prompt_text(self) -> str:
        sections = [
            ("面试问题", self.questions),
            ("短期补强建议", self.short_term_focus),
        ]
        lines: list[str] = []
        for title, items in sections:
            lines.append(f"{title}：")
            if items:
                lines.extend(f"- {item}" for item in items)
            else:
                lines.append("- 无")
        return "\n".join(lines)


@dataclass(frozen=True)
class PlannerDecisionResult:
    should_search: bool
    query: str
    reason: str
    used_tool_call: bool
    raw_output: str


@dataclass(frozen=True)
class SelectedResumeResult:
    resume_id: str
    file_name: str
    selection_mode: str
    distance: float | None


@dataclass(frozen=True)
class WorkflowRunResult:
    jd_analysis: JDAnalysisResult
    effective_resume_text: str = ""
    selected_resume: SelectedResumeResult | None = None
    raw_retrieved_chunks: list[RetrievedChunk] = field(default_factory=list)
    retrieved_chunks: list[RetrievedChunk] = field(default_factory=list)
    content_filtered_chunks: list[RetrievedChunk] = field(default_factory=list)
    distance_filtered_chunks: list[RetrievedChunk] = field(default_factory=list)
    gap_truncated_chunks: list[RetrievedChunk] = field(default_factory=list)
    ai_rerank_excluded_chunks: list[RetrievedChunk] = field(default_factory=list)
    retrieved_context: str = ""
    retrieval_query: str = ""
    retrieval_candidate_limit: int | None = None
    max_retrieval_distance: float | None = None
    content_filtered_chunk_count: int = 0
    filtered_chunk_count: int = 0
    gap_truncated_chunk_count: int = 0
    ai_rerank_excluded_chunk_count: int = 0
    ai_rerank_reason: str = ""
    ai_rerank_failed: bool = False
    retrieval_status: str = "not_requested"
    retrieval_message: str = ""
    planner_decision: PlannerDecisionResult | None = None
    match_analysis: MatchAnalysisResult | None = None
    resume_advice: ResumeAdviceResult | None = None
    interview_prep: InterviewPrepResult | None = None
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
