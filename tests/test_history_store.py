from contextlib import closing
from dataclasses import FrozenInstanceError
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app.storage import HistoryRecord, HistoryStore


class HistoryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.path = self.root / "data" / "history.sqlite3"
        self.store = HistoryStore(self.path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def save_analysis(self, record_id="analysis-1", payload=None) -> HistoryRecord:
        return self.store.save(
            record_id, "analysis", "后端开发岗位", payload if payload is not None else {"schema_version": 1}
        )

    def test_initialization_is_idempotent_and_records_survive_reopen(self) -> None:
        record = self.save_analysis(payload={"schema_version": 1, "jd": "岗位要求\n熟悉 Python", "evidence": ["项目证据"]})
        reopened = HistoryStore(self.path)
        self.assertEqual(reopened.get(record.record_id), record)
        self.assertEqual(HistoryStore(self.path).list_records(), [record])
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_interview_preserves_chinese_multiline_answers_and_full_feedback(self) -> None:
        payload = {
            "schema_version": 1,
            "rounds": [{
                "question": "为什么选择这个方案？",
                "question_source": "project",
                "answer": "第一行\n  第二行\n没有相关经历。",
                "score": 2,
                "strengths": [],
                "improvements": ["补充取舍依据"],
                "answer_structure": ["背景", "方案", "结果"],
                "overall_feedback": "如实回答，但证据不足。",
            }],
            "summary": {"overall_summary": "继续练习"},
        }
        saved = self.store.save("interview-1", "interview", "练习复盘", payload)
        self.assertEqual(HistoryStore(self.path).get(saved.record_id).payload, payload)
        payload["rounds"][0]["answer"] = "外部修改"
        self.assertNotEqual(saved.payload, payload)
        with self.assertRaises(FrozenInstanceError):
            saved.title = "不能赋值"

    def test_duplicate_save_updates_record_and_preserves_creation_time(self) -> None:
        with patch("app.storage.history_repository._now", return_value="2026-09-01T00:00:00.000000+00:00"):
            first = self.save_analysis()
        with patch("app.storage.history_repository._now", return_value="2026-09-02T00:00:00.000000+00:00"):
            updated = self.store.save(first.record_id, "analysis", "更新标题", {"value": 2})
        self.assertEqual(len(self.store.list_records()), 1)
        self.assertEqual(updated.created_at, first.created_at)
        self.assertGreater(updated.updated_at, first.updated_at)
        self.assertEqual(updated.title, "更新标题")
        self.assertEqual(updated.payload, {"value": 2})

    def test_duplicate_id_cannot_change_kind_and_existing_value_survives(self) -> None:
        first = self.save_analysis()
        with self.assertRaisesRegex(ValueError, "类型"):
            self.store.save(first.record_id, "interview", "错误替换", {})
        self.assertEqual(self.store.get(first.record_id), first)

    def test_deleting_analysis_unlinks_interview_without_changing_payload(self) -> None:
        analysis = self.save_analysis()
        interview = self.store.save("interview-1", "interview", "完整复盘", {"rounds": [{"answer": "原回答"}]}, analysis.record_id)
        self.store.delete(analysis.record_id)
        kept = HistoryStore(self.path).get(interview.record_id)
        self.assertIsNone(kept.analysis_id)
        self.assertEqual(kept.payload, interview.payload)
        self.assertEqual(kept.created_at, interview.created_at)
        self.assertEqual(kept.updated_at, interview.updated_at)
        self.assertEqual(self.store.list_records(), [kept])
        with self.assertRaises(KeyError):
            self.store.get(analysis.record_id)

    def test_deleting_interview_keeps_analysis_and_other_interviews(self) -> None:
        analysis = self.save_analysis()
        self.store.save("interview-1", "interview", "练习一", {}, analysis.record_id)
        other = self.store.save("interview-2", "interview", "练习二", {}, analysis.record_id)
        self.store.delete("interview-1")
        self.assertEqual(self.store.get(analysis.record_id), analysis)
        self.assertEqual(self.store.get(other.record_id), other)
        self.store.delete("missing-id")

    def test_invalid_analysis_links_are_rejected_without_partial_writes(self) -> None:
        analysis = self.save_analysis()
        self.store.save("interview-existing", "interview", "先前练习", {})
        for parent_id in ("missing-id", "interview-existing", "new-interview"):
            with self.subTest(parent_id=parent_id), self.assertRaises(ValueError):
                self.store.save("new-interview", "interview", "无效关联", {}, parent_id)
        with self.assertRaises(ValueError):
            self.store.save("analysis-2", "analysis", "无效关联", {}, analysis.record_id)
        self.assertEqual(len(self.store.list_records()), 2)
        with self.assertRaises(KeyError):
            self.store.get("new-interview")

    def test_invalid_relink_leaves_saved_record_unchanged(self) -> None:
        first = self.store.save("interview-1", "interview", "已有结果", {"score": 7})
        with self.assertRaises(ValueError):
            self.store.save(first.record_id, "interview", "错误修改", {}, "missing")
        self.assertEqual(self.store.get(first.record_id), first)

    def test_lists_newest_first_and_filters_type_and_inclusive_utc_time(self) -> None:
        with patch("app.storage.history_repository._now", return_value="2026-09-01T00:00:00.000000+00:00"):
            first = self.save_analysis("analysis-1")
        with patch("app.storage.history_repository._now", return_value="2026-09-02T00:00:00.000000+00:00"):
            second = self.store.save("interview-1", "interview", "练习", {})
        with patch("app.storage.history_repository._now", return_value="2026-09-03T00:00:00.000000+00:00"):
            third = self.save_analysis("analysis-2")
        self.assertEqual(self.store.list_records(), [third, second, first])
        self.assertEqual(self.store.list_records(kind="analysis"), [third, first])
        self.assertEqual(self.store.list_records(since=second.created_at), [third, second])
        self.assertEqual(self.store.list_records(since="2026-09-02T08:00:00+08:00"), [third, second])
        self.assertEqual(self.store.list_records(kind="interview", since="2026-09-02"), [second])
        self.assertEqual(self.store.list_records(since="2027-01-01"), [])

    def test_invalid_inputs_fail_before_writing(self) -> None:
        for record_id, kind, payload in (("", "analysis", {}), ("x", "unknown", {}), ("x", "analysis", []), ("x", "analysis", {"score": float("nan")})):
            with self.subTest(record_id=record_id, kind=kind, payload=payload), self.assertRaises(ValueError):
                self.store.save(record_id, kind, "标题", payload)
        with self.assertRaises(ValueError):
            self.store.list_records(kind="unknown")
        with self.assertRaises(ValueError):
            self.store.list_records(since="not a date")
        self.assertEqual(self.store.list_records(), [])

    def test_locked_database_reports_error_and_allows_retry(self) -> None:
        first = self.save_analysis()
        with closing(sqlite3.connect(self.path)) as locked:
            locked.execute("BEGIN IMMEDIATE")
            with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                self.store.save("analysis-2", "analysis", "新结果", {})
            self.assertEqual(self.store.get(first.record_id), first)
            locked.rollback()
        retried = self.save_analysis("analysis-2")
        self.assertEqual(self.store.get(retried.record_id), retried)

    def test_corrupt_database_is_reported_and_not_overwritten(self) -> None:
        corrupt = self.root / "corrupt.sqlite3"
        contents = b"this file is not a sqlite database"
        corrupt.write_bytes(contents)
        with self.assertRaises(sqlite3.DatabaseError):
            HistoryStore(corrupt)
        self.assertEqual(corrupt.read_bytes(), contents)

    def test_future_schema_is_rejected_without_modification(self) -> None:
        future = self.root / "future.sqlite3"
        with closing(sqlite3.connect(future)) as connection, connection:
            connection.execute("CREATE TABLE future_records (value TEXT)")
            connection.execute("INSERT INTO future_records VALUES ('保留')")
            connection.execute("PRAGMA user_version = 99")
        original = future.read_bytes()
        with self.assertRaisesRegex(sqlite3.DatabaseError, "99"):
            HistoryStore(future)
        self.assertEqual(future.read_bytes(), original)

    def test_corrupt_record_payload_has_actionable_database_error(self) -> None:
        record = self.save_analysis()
        for bad_json in ("{not-json", "[]", "null"):
            with self.subTest(payload=bad_json):
                with closing(sqlite3.connect(self.path)) as connection, connection:
                    connection.execute("UPDATE history_records SET payload_json = ? WHERE record_id = ?", (bad_json, record.record_id))
                with self.assertRaises(sqlite3.DatabaseError):
                    self.store.get(record.record_id)
                with self.assertRaises(sqlite3.DatabaseError):
                    self.store.list_records()

    def test_history_operations_leave_neighboring_user_data_unchanged(self) -> None:
        protected = {
            self.root / "data" / "resumes" / "resume.txt": b"full resume",
            self.root / "data" / "chroma" / "chroma.sqlite3": b"project vectors",
            self.root / "data" / "app_history.sqlite3": b"legacy database",
            self.root / "data" / "question_bank.txt": b"temporary question bank",
        }
        for path, contents in protected.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents)
        analysis = self.save_analysis()
        self.store.save("interview-1", "interview", "练习", {}, analysis.record_id)
        self.store.delete(analysis.record_id)
        self.store.delete("interview-1")
        HistoryStore(self.path)
        for path, contents in protected.items():
            self.assertEqual(path.read_bytes(), contents)


if __name__ == "__main__":
    unittest.main()
