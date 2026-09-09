import tempfile
import unittest
from pathlib import Path

from app.rag.resume_store import ResumeStore
from app.services.document_parser import ParsedDocument


class FakeResumeCollection:
    def __init__(self) -> None:
        self.items: dict[str, tuple[str, dict]] = {}
        self.query_id = ""
        self.query_distance = 0.2

    def add(self, ids, documents, metadatas) -> None:
        for resume_id, document, metadata in zip(ids, documents, metadatas):
            self.items[resume_id] = (document, metadata)

    def query(self, query_texts, n_results):
        selected_id = self.query_id or next(iter(self.items))
        return {"ids": [[selected_id]], "distances": [[self.query_distance]]}

    def get(self, ids=None):
        if ids is None:
            return {"ids": list(self.items)}
        return {"ids": [resume_id for resume_id in ids if resume_id in self.items]}

    def delete(self, ids) -> None:
        for resume_id in ids:
            self.items.pop(resume_id, None)


def make_document(file_name: str, text: str) -> ParsedDocument:
    return ParsedDocument(file_name=file_name, file_type="txt", text=text)


class ResumeStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.store = ResumeStore(
            storage_dir=root / "resumes",
            index_persist_dir=root / "vectors",
        )
        self.collection = FakeResumeCollection()
        self.store.client = object()
        self.store.collection = self.collection
        self.store.embedding_function = object()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_adds_full_resumes_and_skips_duplicate_content(self) -> None:
        result = self.store.add_documents(
            [
                make_document("AI简历.txt", "完整简历正文 A"),
                make_document("重复名称.txt", "完整简历正文 A"),
                make_document("后端简历.txt", "完整简历正文 B"),
            ]
        )

        self.assertEqual(result.added_resumes, 2)
        self.assertEqual(result.skipped_resumes, ["重复名称.txt"])
        self.assertEqual(len(self.store.list_records()), 2)
        self.assertEqual(self.store.list_records()[0].text.startswith("完整简历正文"), True)

    def test_selects_best_resume_and_returns_full_text(self) -> None:
        self.store.add_documents(
            [
                make_document("AI简历.txt", "AI 简历完整正文"),
                make_document("后端简历.txt", "后端简历完整正文"),
            ]
        )
        backend_record = next(
            record for record in self.store.list_records() if record.file_name == "后端简历.txt"
        )
        self.collection.query_id = backend_record.resume_id

        selection = self.store.select("招聘后端开发", resume_id=None)

        self.assertEqual(selection.record.file_name, "后端简历.txt")
        self.assertEqual(selection.record.text, "后端简历完整正文")
        self.assertEqual(selection.mode, "automatic")

    def test_manual_selection_and_delete(self) -> None:
        self.store.add_documents([make_document("AI简历.txt", "AI 简历完整正文")])
        record = self.store.list_records()[0]

        selection = self.store.select("任意岗位", resume_id=record.resume_id)
        self.store.delete(record.resume_id)

        self.assertEqual(selection.mode, "manual")
        self.assertEqual(self.store.list_records(), [])

    def test_selection_index_samples_the_whole_resume(self) -> None:
        paragraphs = [f"第{index}段内容-" + ("甲" * 80) for index in range(20)]

        index_text = self.store._build_selection_text("\n".join(paragraphs))

        self.assertLessEqual(len(index_text), 450)
        self.assertIn("第0段内容", index_text)
        self.assertIn("第19段内容", index_text)


if __name__ == "__main__":
    unittest.main()
