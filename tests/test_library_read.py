from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import uuid
import chromadb
from app.rag.vector_store import ProfileKnowledgeBase


class LibraryReadTests(TestCase):
    def test_empty_read_does_not_create_collection_or_load_model(self):
        with TemporaryDirectory() as directory:
            kb = ProfileKnowledgeBase(persist_dir=Path(directory), collection_name="test_" + uuid.uuid4().hex)
            kb.client = chromadb.EphemeralClient()
            with patch.object(kb, "_get_embedding_function", side_effect=AssertionError("model loaded")):
                self.assertEqual(kb.count(), 0)
                self.assertEqual(kb.list_chunks(), [])
                self.assertNotIn(kb.collection_name, [c.name for c in kb.client.list_collections()])

    def test_read_keeps_data_and_separate_write_handle(self):
        with TemporaryDirectory() as directory:
            kb = ProfileKnowledgeBase(persist_dir=Path(directory), collection_name="test_" + uuid.uuid4().hex)
            kb.client = chromadb.EphemeralClient()
            collection = kb.client.create_collection(kb.collection_name, embedding_function=None)
            collection.add(ids=["one"], documents=["project evidence"], embeddings=[[1., 0.]],
                           metadatas=[{"source": "project.txt", "chunk_index": 0}])
            with patch.object(kb, "_get_embedding_function", side_effect=AssertionError("model loaded")):
                self.assertEqual(kb.count(), 1)
                self.assertEqual(kb.list_chunks()[0].text, "project evidence")
            self.assertIsNone(kb.collection)
            with patch.object(kb, "_get_or_create_configured_collection", return_value=collection) as configured:
                self.assertIs(kb._get_collection(require_embedding=True), collection)
                configured.assert_called_once()
            self.assertEqual(collection.count(), 1)
