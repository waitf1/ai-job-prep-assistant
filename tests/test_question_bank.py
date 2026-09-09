import unittest

from app.services.document_parser import ParsedDocument
from app.services.question_bank import extract_question_bank


class QuestionBankTests(unittest.TestCase):
    def test_extracts_and_deduplicates_questions(self) -> None:
        documents = [
            ParsedDocument(
                file_name="questions.txt",
                file_type="txt",
                text="1. 什么是 RAG？\n2. 如何评估检索质量？\n什么是 RAG？\n注",
            )
        ]

        questions = extract_question_bank(documents)

        self.assertEqual(questions, ["什么是 RAG？", "如何评估检索质量？"])


if __name__ == "__main__":
    unittest.main()
