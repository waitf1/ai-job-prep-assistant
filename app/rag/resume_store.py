from dataclasses import asdict, dataclass
import hashlib
import importlib
import json
from pathlib import Path

from app.rag.vector_store import DEFAULT_EMBEDDING_MODEL
from app.services.document_parser import ParsedDocument


@dataclass(frozen=True)
class ResumeRecord:
    resume_id: str
    file_name: str
    file_type: str
    text: str


@dataclass(frozen=True)
class ResumeSelection:
    record: ResumeRecord
    mode: str
    distance: float | None


@dataclass(frozen=True)
class AddResumesResult:
    added_resumes: int
    skipped_resumes: list[str]


class ResumeStore:
    """Persist full resumes and use a separate vector index for resume selection."""

    def __init__(
        self,
        storage_dir: str | Path = "data/resumes",
        index_persist_dir: str | Path = "data/vector_store",
        collection_name: str = "resume_documents",
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    ) -> None:
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.index_persist_dir = Path(index_persist_dir)
        self.index_persist_dir.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self.embedding_model = embedding_model
        self.client = None
        self.collection = None
        self.embedding_function = None

    def add_documents(self, documents: list[ParsedDocument]) -> AddResumesResult:
        existing_ids = {record.resume_id for record in self.list_records()}
        added = 0
        skipped: list[str] = []
        collection = self._get_collection(require_embedding=True)

        for document in documents:
            resume_id = hashlib.sha256(document.text.encode("utf-8")).hexdigest()[:24]
            if resume_id in existing_ids:
                skipped.append(document.file_name)
                continue

            record = ResumeRecord(
                resume_id=resume_id,
                file_name=document.file_name,
                file_type=document.file_type,
                text=document.text,
            )
            record_path = self._record_path(resume_id)
            record_path.write_text(
                json.dumps(asdict(record), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            try:
                collection.add(
                    ids=[resume_id],
                    documents=[self._build_selection_text(document.text)],
                    metadatas=[{"file_name": document.file_name, "file_type": document.file_type}],
                )
            except Exception:
                record_path.unlink(missing_ok=True)
                raise
            existing_ids.add(resume_id)
            added += 1

        return AddResumesResult(added_resumes=added, skipped_resumes=skipped)

    def list_records(self) -> list[ResumeRecord]:
        records: list[ResumeRecord] = []
        for path in self.storage_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                records.append(ResumeRecord(**data))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return sorted(records, key=lambda record: record.file_name.lower())

    def get(self, resume_id: str) -> ResumeRecord:
        path = self._record_path(resume_id)
        if not path.exists():
            raise KeyError(f"未找到简历：{resume_id}")
        return ResumeRecord(**json.loads(path.read_text(encoding="utf-8")))

    def select(self, query: str, resume_id: str | None = None) -> ResumeSelection:
        if resume_id:
            return ResumeSelection(record=self.get(resume_id), mode="manual", distance=None)

        records = self.list_records()
        if not records:
            raise ValueError("简历库为空，请先上传至少一份简历。")
        if len(records) == 1:
            return ResumeSelection(record=records[0], mode="automatic", distance=0.0)

        result = self._get_collection(require_embedding=True).query(
            query_texts=[query],
            n_results=1,
        )
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        if not ids:
            return ResumeSelection(record=records[0], mode="automatic", distance=None)
        distance = distances[0] if distances else None
        return ResumeSelection(
            record=self.get(str(ids[0])),
            mode="automatic",
            distance=float(distance) if distance is not None else None,
        )

    def delete(self, resume_id: str) -> None:
        self._record_path(resume_id).unlink(missing_ok=True)
        collection = self._get_collection(require_embedding=False)
        existing_ids = collection.get(ids=[resume_id]).get("ids", [])
        if existing_ids:
            collection.delete(ids=[resume_id])

    def reset(self) -> None:
        for path in self.storage_dir.glob("*.json"):
            path.unlink(missing_ok=True)
        collection = self._get_collection(require_embedding=False)
        ids = collection.get().get("ids", [])
        if ids:
            collection.delete(ids=ids)

    def _record_path(self, resume_id: str) -> Path:
        return self.storage_dir / f"{resume_id}.json"

    def _get_collection(self, require_embedding: bool):
        if self.client is None:
            chromadb = importlib.import_module("chromadb")
            self.client = chromadb.PersistentClient(path=str(self.index_persist_dir))

        if self.collection is None or (require_embedding and self.embedding_function is None):
            kwargs = {
                "name": self.collection_name,
                "metadata": {"description": "Full resume selection index"},
            }
            if require_embedding:
                kwargs["embedding_function"] = self._get_embedding_function()
            self.collection = self.client.get_or_create_collection(**kwargs)
        return self.collection

    def _get_embedding_function(self):
        if self.embedding_function is None:
            module = importlib.import_module("chromadb.utils.embedding_functions")
            embedding_class = getattr(module, "SentenceTransformerEmbeddingFunction")
            self.embedding_function = embedding_class(model_name=self.embedding_model)
        return self.embedding_function

    @staticmethod
    def _build_selection_text(text: str, limit: int = 450) -> str:
        paragraphs = [part.strip() for part in text.split("\n") if part.strip()]
        if len(text) <= limit:
            return text
        if not paragraphs:
            return text[:limit]
        sample_count = min(len(paragraphs), 12)
        indexes = {
            round(index * (len(paragraphs) - 1) / (sample_count - 1))
            for index in range(sample_count)
        } if sample_count > 1 else {0}
        per_paragraph_limit = max(24, (limit - sample_count) // sample_count)
        return "\n".join(
            paragraphs[index][:per_paragraph_limit] for index in sorted(indexes)
        )[:limit]
