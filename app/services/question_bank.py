import re

from app.services.document_parser import ParsedDocument


def extract_question_bank(documents: list[ParsedDocument], limit: int = 80) -> list[str]:
    """Extract readable, deduplicated questions for the current interview session."""
    questions: list[str] = []
    seen: set[str] = set()
    for document in documents:
        for raw_line in document.text.splitlines():
            question = re.sub(r"^\s*(?:[（(]?\d+[）).、]?\s*|[-*•]\s*)", "", raw_line).strip()
            if len(question) < 6:
                continue
            normalized = re.sub(r"\s+", "", question).lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            questions.append(question)
            if len(questions) >= limit:
                return questions
    return questions
