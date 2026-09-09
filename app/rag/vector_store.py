from dataclasses import dataclass
import hashlib
import importlib
from pathlib import Path
from typing import Any, Callable
import uuid

from app.rag.chunking import split_text
from app.rag.document_cleaner import (
    clean_project_document,
    is_high_confidence_noise,
)
from app.services.document_parser import ParsedDocument


DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
DEFAULT_MAX_RETRIEVAL_DISTANCE = 0.8
DEFAULT_RETRIEVAL_CANDIDATE_LIMIT = 10
DEFAULT_MAX_SELECTED_CHUNKS = 5
DEFAULT_DISTANCE_GAP_THRESHOLD = 0.25
DEFAULT_CHUNK_REVIEW_BATCH_SIZE = 5


@dataclass(frozen=True)
class RetrievedChunk:
    text: str
    source: str
    chunk_index: int
    distance: float | None
    section_title: str = "文档内容"
    content_type: str = "body"
    cleaning_status: str = "clean"


@dataclass(frozen=True)
class AddDocumentsResult:
    added_chunks: int
    added_documents: int
    skipped_documents: list[str]
    rule_removed_lines: int = 0
    excluded_sections: int = 0
    ai_reviewed_chunks: int = 0
    ai_excluded_chunks: int = 0
    ai_review_failed_chunks: int = 0


@dataclass(frozen=True)
class ChunkSelectionResult:
    selected_chunks: list[RetrievedChunk]
    content_filtered_chunks: list[RetrievedChunk]
    distance_filtered_chunks: list[RetrievedChunk]
    gap_truncated_chunks: list[RetrievedChunk]


def filter_retrieved_chunks(
    chunks: list[RetrievedChunk],
    max_distance: float = DEFAULT_MAX_RETRIEVAL_DISTANCE,
) -> list[RetrievedChunk]:
    """Keep chunks with an acceptable distance or no distance metadata."""

    return [
        chunk
        for chunk in chunks
        if chunk.distance is None or chunk.distance <= max_distance
    ]


def select_retrieved_chunks(
    chunks: list[RetrievedChunk],
    max_distance: float = DEFAULT_MAX_RETRIEVAL_DISTANCE,
    max_chunks: int = DEFAULT_MAX_SELECTED_CHUNKS,
    distance_gap_threshold: float = DEFAULT_DISTANCE_GAP_THRESHOLD,
) -> ChunkSelectionResult:
    """Filter low-quality candidates and stop at a clear distance gap."""

    content_filtered_chunks = [
        chunk
        for chunk in chunks
        if chunk.content_type not in {"body", "project", "method", "result"}
        or is_high_confidence_noise(chunk.text, chunk.section_title)
    ]
    content_eligible_chunks = [
        chunk for chunk in chunks if chunk not in content_filtered_chunks
    ]
    distance_filtered_chunks = [
        chunk
        for chunk in content_eligible_chunks
        if chunk.distance is not None and chunk.distance > max_distance
    ]
    eligible_chunks = sorted(
        filter_retrieved_chunks(content_eligible_chunks, max_distance=max_distance),
        key=lambda chunk: chunk.distance if chunk.distance is not None else float("inf"),
    )
    selected_chunks: list[RetrievedChunk] = []
    gap_truncated_chunks: list[RetrievedChunk] = []
    previous_distance: float | None = None

    for index, chunk in enumerate(eligible_chunks):
        if len(selected_chunks) >= max_chunks:
            gap_truncated_chunks.extend(eligible_chunks[index:])
            break
        if (
            previous_distance is not None
            and chunk.distance is not None
            and chunk.distance - previous_distance >= distance_gap_threshold
        ):
            gap_truncated_chunks.extend(eligible_chunks[index:])
            break

        selected_chunks.append(chunk)
        if chunk.distance is not None:
            previous_distance = chunk.distance

    return ChunkSelectionResult(
        selected_chunks=selected_chunks,
        content_filtered_chunks=content_filtered_chunks,
        distance_filtered_chunks=distance_filtered_chunks,
        gap_truncated_chunks=gap_truncated_chunks,
    )


class ProfileKnowledgeBase:
    """Persistent Chroma-backed knowledge base for personal documents."""

    def __init__(
        self,
        persist_dir: str | Path = "data/vector_store",
        collection_name: str = "profile_documents",
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    ) -> None:
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.embedding_model = embedding_model
        self.collection_name = collection_name
        self.client = None
        self.embedding_function = None
        self.collection = None

    def add_documents(
        self,
        documents: list[ParsedDocument],
        reviewer: Any | None = None,
        on_review_progress: Callable[[int, int], None] | None = None,
    ) -> AddDocumentsResult:
        """Chunk and add parsed documents to the vector store."""
        collection = self._get_collection(require_embedding=True)
        existing_hashes = self._get_existing_document_hashes()

        ids: list[str] = []
        texts: list[str] = []
        metadatas: list[dict[str, str | int]] = []
        skipped_documents: list[str] = []
        added_documents = 0
        rule_removed_lines = 0
        excluded_sections = 0
        ai_reviewed_chunks = 0
        ai_excluded_chunks = 0
        ai_review_failed_chunks = 0
        prepared_documents: list[tuple[ParsedDocument, str, list[Any]]] = []

        for document in documents:
            document_hash = self._hash_document_text(document.text)
            if document_hash in existing_hashes:
                skipped_documents.append(document.file_name)
                continue

            cleaned_document = clean_project_document(document.text)
            rule_removed_lines += (
                cleaned_document.stats.removed_noise_line_count
                + cleaned_document.stats.removed_repeated_header_footer_count
            )
            excluded_sections += cleaned_document.stats.excluded_section_count
            chunks = split_text(cleaned_document.text)
            prepared_documents.append((document, document_hash, chunks))

        total_review_batches = sum(
            (len(chunks) + DEFAULT_CHUNK_REVIEW_BATCH_SIZE - 1) // DEFAULT_CHUNK_REVIEW_BATCH_SIZE
            for _, _, chunks in prepared_documents
        )
        completed_review_batches = 0

        for document, document_hash, chunks in prepared_documents:
            document_added = False
            review_results: list[Any | None] = [None] * len(chunks)
            if reviewer is not None:
                for start in range(0, len(chunks), DEFAULT_CHUNK_REVIEW_BATCH_SIZE):
                    batch = chunks[start : start + DEFAULT_CHUNK_REVIEW_BATCH_SIZE]
                    batch_reviews = reviewer.review_batch(batch)
                    if len(batch_reviews) != len(batch):
                        raise RuntimeError("AI 复核返回数量与当前审核批次不一致。")
                    review_results[start : start + len(batch)] = batch_reviews
                    completed_review_batches += 1
                    if on_review_progress is not None:
                        on_review_progress(completed_review_batches, total_review_batches)

            for chunk, review in zip(chunks, review_results):
                content_type = chunk.content_type
                cleaning_status = chunk.cleaning_status
                if review is not None:
                    ai_reviewed_chunks += 1
                    content_type = review.content_type
                    cleaning_status = "review_failed" if review.review_failed else "ai_reviewed"
                    if review.review_failed:
                        ai_review_failed_chunks += 1
                    if not review.keep:
                        ai_excluded_chunks += 1
                        continue

                ids.append(f"{Path(document.file_name).stem}-{chunk.index}-{uuid.uuid4().hex[:8]}")
                texts.append(chunk.text)
                metadatas.append(
                    {
                        "doc_hash": document_hash,
                        "source": document.file_name,
                        "file_type": document.file_type,
                        "chunk_index": chunk.index,
                        "section_title": chunk.section_title,
                        "content_type": content_type,
                        "cleaning_status": cleaning_status,
                    }
                )
                document_added = True
            if document_added:
                existing_hashes.add(document_hash)
                added_documents += 1

        if not texts:
            return AddDocumentsResult(
                added_chunks=0,
                added_documents=0,
                skipped_documents=skipped_documents,
                rule_removed_lines=rule_removed_lines,
                excluded_sections=excluded_sections,
                ai_reviewed_chunks=ai_reviewed_chunks,
                ai_excluded_chunks=ai_excluded_chunks,
                ai_review_failed_chunks=ai_review_failed_chunks,
            )

        collection.add(ids=ids, documents=texts, metadatas=metadatas)
        return AddDocumentsResult(
            added_chunks=len(texts),
            added_documents=added_documents,
            skipped_documents=skipped_documents,
            rule_removed_lines=rule_removed_lines,
            excluded_sections=excluded_sections,
            ai_reviewed_chunks=ai_reviewed_chunks,
            ai_excluded_chunks=ai_excluded_chunks,
            ai_review_failed_chunks=ai_review_failed_chunks,
        )

    def search(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        """Retrieve the most relevant chunks for a query."""
        collection = self._get_collection(require_embedding=True)

        if not query.strip():
            return []

        results = collection.query(query_texts=[query], n_results=top_k)
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        chunks: list[RetrievedChunk] = []
        for text, metadata, distance in zip(documents, metadatas, distances):
            chunks.append(
                RetrievedChunk(
                    text=text,
                    source=str(metadata.get("source", "unknown")),
                    chunk_index=int(metadata.get("chunk_index", -1)),
                    distance=float(distance) if distance is not None else None,
                    section_title=str(metadata.get("section_title", "文档内容")),
                    content_type=str(metadata.get("content_type", "body")),
                    cleaning_status=str(metadata.get("cleaning_status", "legacy")),
                )
            )

        return chunks

    def count(self) -> int:
        collection = self._get_read_collection()
        return collection.count() if collection is not None else 0

    def list_chunks(self) -> list[RetrievedChunk]:
        collection = self._get_read_collection()
        if collection is None:
            return []
        results = collection.get(include=["documents", "metadatas"])
        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])

        chunks: list[RetrievedChunk] = []
        for text, metadata in zip(documents, metadatas):
            if not isinstance(metadata, dict):
                continue
            chunks.append(
                RetrievedChunk(
                    text=str(text),
                    source=str(metadata.get("source", "unknown")),
                    chunk_index=int(metadata.get("chunk_index", -1)),
                    distance=None,
                    section_title=str(metadata.get("section_title", "文档内容")),
                    content_type=str(metadata.get("content_type", "body")),
                    cleaning_status=str(metadata.get("cleaning_status", "legacy")),
                )
            )

        return sorted(chunks, key=lambda chunk: (chunk.source, chunk.chunk_index, chunk.text))

    def reset(self) -> None:
        if self.client is None:
            chromadb = importlib.import_module("chromadb")
            self.client = chromadb.PersistentClient(path=str(self.persist_dir))

        # 清空是用户明确发起的重建操作：删除整个集合而不只是文档，
        # 这样旧的 default embedding 配置也会一并移除。
        try:
            self.client.delete_collection(self.collection_name)
        except ValueError:
            # 集合尚未创建时，清空操作仍应视为成功。
            pass
        self.collection = None
        self.embedding_function = None

    def _get_existing_document_hashes(self) -> set[str]:
        collection = self._get_collection(require_embedding=False)
        metadatas = collection.get(include=["metadatas"]).get("metadatas", [])

        hashes: set[str] = set()
        for metadata in metadatas:
            if not isinstance(metadata, dict):
                continue
            document_hash = metadata.get("doc_hash")
            if isinstance(document_hash, str) and document_hash:
                hashes.add(document_hash)
        return hashes

    def _get_read_collection(self):
        """Read existing data without loading a model or creating a collection.

        Do not cache this handle as the write collection: uploads and queries
        still need the explicitly configured embedding function.
        """
        if self.collection is not None:
            return self.collection
        chromadb = importlib.import_module("chromadb")
        if self.client is None:
            self.client = chromadb.PersistentClient(path=str(self.persist_dir))
        try:
            return self.client.get_collection(self.collection_name, embedding_function=None)
        except chromadb.errors.NotFoundError:
            return None

    def _get_collection(self, require_embedding: bool) -> object:
        if self.client is None:
            chromadb = importlib.import_module("chromadb")
            self.client = chromadb.PersistentClient(path=str(self.persist_dir))

        if self.collection is None:
            self.collection = self._get_or_create_configured_collection()

        return self.collection

    def _get_or_create_configured_collection(self) -> object:
        """Create every collection with one fixed embedding configuration.

        The page may call ``count`` before a document is added.  Supplying the
        embedding function even then prevents Chroma from persisting its
        default embedding function and rejecting the first upload later.
        """

        kwargs = {
            "name": self.collection_name,
            "embedding_function": self._get_embedding_function(),
            "metadata": {"description": "Personal profile documents for job matching"},
        }
        try:
            return self.client.get_or_create_collection(**kwargs)
        except ValueError as exc:
            message = str(exc)
            if "Embedding function conflict" not in message:
                raise

            legacy_collection = self.client.get_collection(self.collection_name)
            if legacy_collection.count() > 0:
                raise RuntimeError(
                    "现有项目资料库使用了旧的 embedding 配置，无法安全混用。"
                    "请先清空项目资料库，再重新上传原始项目资料。"
                ) from exc

            self.client.delete_collection(self.collection_name)
            return self.client.get_or_create_collection(**kwargs)

    def _get_embedding_function(self) -> object:
        if self.embedding_function is None:
            embedding_module = importlib.import_module("chromadb.utils.embedding_functions")
            embedding_class = getattr(embedding_module, "SentenceTransformerEmbeddingFunction")
            self.embedding_function = embedding_class(model_name=self.embedding_model)
        return self.embedding_function

    @staticmethod
    def _hash_document_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
