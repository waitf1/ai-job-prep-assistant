from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sqlite3
from pathlib import Path
from typing import Any

from app.services.interview_session import InterviewContext, InterviewSession
from app.services.workflow_types import WorkflowRunResult


@dataclass(frozen=True)
class AnalysisHistory:
    analysis_id: int
    created_at: str
    job_description: str
    analysis_mode: str
    resume_file_name: str
    summary: dict[str, Any]


@dataclass(frozen=True)
class InterviewHistory:
    interview_id: int
    analysis_id: int | None
    created_at: str
    completed_at: str
    question_modes: list[str]
    round_count: int
    rounds: list[dict[str, Any]]
    summary: dict[str, Any]


class HistoryStore:
    """SQLite persistence for structured summaries only, never raw documents or keys."""

    def __init__(self, db_path: str | Path = "data/app_history.sqlite3") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    job_description TEXT NOT NULL,
                    analysis_mode TEXT NOT NULL,
                    resume_file_name TEXT NOT NULL DEFAULT '',
                    summary_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS interviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    analysis_id INTEGER REFERENCES analyses(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    question_modes_json TEXT NOT NULL,
                    rounds_json TEXT NOT NULL,
                    summary_json TEXT NOT NULL
                );
                """
            )

    def save_analysis(self, result: WorkflowRunResult, job_description: str, analysis_mode: str) -> int:
        selected = result.selected_resume.file_name if result.selected_resume else ""
        summary = {
            "jd": result.jd_analysis.to_prompt_text(),
            "matched_points": result.match_analysis.matched_points if result.match_analysis else [],
            "gaps": result.match_analysis.gaps if result.match_analysis else [],
            "evidence_notes": result.match_analysis.evidence_notes if result.match_analysis else [],
            "resume_direct_edits": result.resume_advice.direct_edits if result.resume_advice else [],
            "resume_future_edits": result.resume_advice.future_edits if result.resume_advice else [],
            "interview_questions": result.interview_prep.questions if result.interview_prep else [],
            "interview_focus": result.interview_prep.short_term_focus if result.interview_prep else [],
            "project_evidence": [chunk.text for chunk in result.retrieved_chunks],
        }
        now = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO analyses(created_at, job_description, analysis_mode, resume_file_name, summary_json) VALUES (?, ?, ?, ?, ?)",
                (now, job_description[:20000], analysis_mode, selected, json.dumps(summary, ensure_ascii=False)),
            )
            return int(cursor.lastrowid)

    def list_analyses(self) -> list[AnalysisHistory]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM analyses ORDER BY created_at DESC, id DESC").fetchall()
        return [
            AnalysisHistory(row["id"], row["created_at"], row["job_description"], row["analysis_mode"], row["resume_file_name"], json.loads(row["summary_json"]))
            for row in rows
        ]

    def get_analysis(self, analysis_id: int) -> AnalysisHistory:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
        if row is None:
            raise KeyError(f"未找到历史分析：{analysis_id}")
        return AnalysisHistory(row["id"], row["created_at"], row["job_description"], row["analysis_mode"], row["resume_file_name"], json.loads(row["summary_json"]))

    def delete_analysis(self, analysis_id: int) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,))

    def save_interview(self, session: InterviewSession, analysis_id: int | None = None) -> int:
        if session.summary is None:
            raise ValueError("只有已生成复盘的面试才能保存。")
        rounds = [
            {
                "question": item.question,
                "question_source": item.question_source,
                "answer": item.answer,
                "score": item.feedback.score,
                "strengths": item.feedback.strengths,
                "improvements": item.feedback.improvements,
                "answer_structure": item.feedback.answer_structure,
                "overall_feedback": item.feedback.overall_feedback,
            }
            for item in session.rounds
        ]
        summary = {
            "strengths": session.summary.strengths,
            "weaknesses": session.summary.weaknesses,
            "answer_structure_advice": session.summary.answer_structure_advice,
            "practice_plan": session.summary.practice_plan,
            "overall_summary": session.summary.overall_summary,
        }
        now = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO interviews(analysis_id, created_at, completed_at, question_modes_json, rounds_json, summary_json) VALUES (?, ?, ?, ?, ?, ?)",
                (analysis_id, now, now, json.dumps(list(session.context.question_modes)), json.dumps(rounds, ensure_ascii=False), json.dumps(summary, ensure_ascii=False)),
            )
            return int(cursor.lastrowid)

    def list_interviews(self, analysis_id: int | None = None) -> list[InterviewHistory]:
        query = "SELECT * FROM interviews"
        params: tuple[Any, ...] = ()
        if analysis_id is not None:
            query += " WHERE analysis_id = ?"
            params = (analysis_id,)
        query += " ORDER BY completed_at DESC, id DESC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [InterviewHistory(row["id"], row["analysis_id"], row["created_at"], row["completed_at"], json.loads(row["question_modes_json"]), len(json.loads(row["rounds_json"])), json.loads(row["rounds_json"]), json.loads(row["summary_json"])) for row in rows]

    def get_interview(self, interview_id: int) -> InterviewHistory:
        with self._connect() as connection:
            row = connection.execute('SELECT * FROM interviews WHERE id = ?', (interview_id,)).fetchone()
        if row is None:
            raise KeyError(f'未找到历史面试：{interview_id}')
        rounds = json.loads(row['rounds_json'])
        return InterviewHistory(row['id'], row['analysis_id'], row['created_at'], row['completed_at'], json.loads(row['question_modes_json']), len(rounds), rounds, json.loads(row['summary_json']))

    def build_interview_context(self, analysis_id: int) -> InterviewContext:
        analysis = self.get_analysis(analysis_id)
        summary = analysis.summary
        return InterviewContext(
            jd_analysis=summary.get("jd", analysis.job_description),
            match_analysis="\n".join([f"匹配点：{item}" for item in summary.get("matched_points", [])] + [f"缺口：{item}" for item in summary.get("gaps", [])]),
            resume_text="历史记录未保存完整简历，请在开始面试前补充简历或从当前简历库选择。",
            retrieved_context="\n".join(summary.get("project_evidence", [])) or "历史记录未保存完整项目原文。",
            suggested_questions=summary.get("interview_questions", []),
            question_modes=("theory", "project"),
            question_bank=[],
            has_job_description=bool(analysis.job_description.strip()),
            has_resume=False,
        )

    def delete_interview(self, interview_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM interviews WHERE id = ?", (interview_id,))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
