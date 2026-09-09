"""Versioned SQLite storage for explicit, independently saved result snapshots."""

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class HistoryRecord:
    record_id: str
    kind: str
    title: str
    created_at: str
    updated_at: str
    analysis_id: str | None
    payload: dict[str, Any]


class HistoryStore:
    """Persist snapshots without accessing resume files or vector collections.

    This repository intentionally uses a separate database from the dormant
    legacy history_store implementation. Existing legacy data is not migrated.
    Connections are short lived so a Streamlit session never owns a DB lock.
    """

    def __init__(self, db_path: str | Path = "data/history.sqlite3") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=1.0)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
        except Exception:
            connection.close()
            raise
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            # A single transaction prevents partial schemas and concurrent
            # initializers from racing on the schema version.
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise sqlite3.DatabaseError(
                    f"不支持的历史数据库版本：{version}，当前支持版本：{SCHEMA_VERSION}。"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS history_records (
                    record_id TEXT PRIMARY KEY NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('analysis', 'interview')),
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    analysis_id TEXT REFERENCES history_records(record_id)
                        ON DELETE SET NULL,
                    payload_json TEXT NOT NULL,
                    CHECK(kind = 'interview' OR analysis_id IS NULL)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS history_records_created "
                "ON history_records(created_at DESC, record_id DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS history_records_analysis "
                "ON history_records(analysis_id)"
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def save(
        self,
        record_id: str,
        kind: str,
        title: str,
        payload: dict[str, Any],
        analysis_id: str | None = None,
    ) -> HistoryRecord:
        _validate_identifier(record_id, "记录 ID")
        _validate_kind(kind)
        if not isinstance(title, str):
            raise ValueError("历史标题必须是文本。")
        if not isinstance(payload, dict):
            raise ValueError("历史内容必须是字典。")
        if analysis_id is not None:
            _validate_identifier(analysis_id, "关联分析 ID")
            if kind != "interview":
                raise ValueError("只有面试记录可以关联岗位分析。")
        # Serialize before opening the write transaction. No Python objects or
        # session state are pickled; snapshot field selection belongs to callers.
        serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        now = _now()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT kind FROM history_records WHERE record_id = ?", (record_id,)
            ).fetchone()
            if existing is not None and existing["kind"] != kind:
                raise ValueError("同一历史记录不能改变类型。")
            if analysis_id is not None:
                parent = connection.execute(
                    "SELECT kind FROM history_records WHERE record_id = ?", (analysis_id,)
                ).fetchone()
                if parent is None or parent["kind"] != "analysis":
                    raise ValueError("关联的岗位分析不存在或类型不正确。")
            connection.execute(
                """
                INSERT INTO history_records (
                    record_id, kind, title, created_at, updated_at,
                    analysis_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(record_id) DO UPDATE SET
                    title = excluded.title,
                    updated_at = excluded.updated_at,
                    analysis_id = excluded.analysis_id,
                    payload_json = excluded.payload_json
                """,
                (record_id, kind, title, now, now, analysis_id, serialized),
            )
            row = connection.execute(
                "SELECT * FROM history_records WHERE record_id = ?", (record_id,)
            ).fetchone()
            return _to_record(row)

    def get(self, record_id: str) -> HistoryRecord:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM history_records WHERE record_id = ?", (record_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"未找到历史记录：{record_id}")
        return _to_record(row)

    def list_records(
        self, kind: str | None = None, since: str | None = None
    ) -> list[HistoryRecord]:
        clauses: list[str] = []
        values: list[str] = []
        if kind is not None:
            _validate_kind(kind)
            clauses.append("kind = ?")
            values.append(kind)
        if since is not None:
            clauses.append("created_at >= ?")
            values.append(_normalize_timestamp(since))
        query = "SELECT * FROM history_records"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC, record_id DESC"
        with closing(self._connect()) as connection:
            rows = connection.execute(query, values).fetchall()
        return [_to_record(row) for row in rows]

    def delete(self, record_id: str) -> None:
        with closing(self._connect()) as connection, connection:
            # Foreign keys are enabled on every connection. Deleting an
            # analysis only clears its interviews' optional relational link.
            connection.execute(
                "DELETE FROM history_records WHERE record_id = ?", (record_id,)
            )


def _validate_identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}不能为空。")


def _validate_kind(kind: str) -> None:
    if kind not in ("analysis", "interview"):
        raise ValueError("历史类型必须是 analysis 或 interview。")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _normalize_timestamp(value: str) -> str:
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _to_record(row: sqlite3.Row) -> HistoryRecord:
    try:
        payload = json.loads(row["payload_json"])
    except (ValueError, TypeError) as exc:
        raise sqlite3.DatabaseError("历史记录内容已损坏，无法读取。") from exc
    if not isinstance(payload, dict):
        raise sqlite3.DatabaseError("历史记录内容格式不正确。")
    return HistoryRecord(
        record_id=row["record_id"],
        kind=row["kind"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        analysis_id=row["analysis_id"],
        payload=payload,
    )
