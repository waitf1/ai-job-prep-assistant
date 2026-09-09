from dataclasses import dataclass
import re

from app.rag.document_cleaner import (
    EXCLUDED_SECTION_TYPES,
    classify_section_title,
    is_high_confidence_noise,
    needs_ai_review,
)


@dataclass(frozen=True)
class TextChunk:
    text: str
    index: int
    section_title: str = "文档内容"
    content_type: str = "body"
    cleaning_status: str = "clean"
    exclusion_reason: str = ""


def split_text(text: str, chunk_size: int = 700, overlap: int = 120) -> list[TextChunk]:
    """Split text at headings and paragraphs before splitting long sections."""

    del overlap  # Kept for call-site compatibility with the former sliding-window API.
    normalized = _compact_blank_lines(text)
    if not normalized:
        return []
    if chunk_size < 200:
        raise ValueError("chunk_size must be at least 200")

    chunks: list[TextChunk] = []
    for section_title, content_type, paragraphs in _split_sections(normalized):
        if content_type in EXCLUDED_SECTION_TYPES:
            continue
        paragraph_groups = (
            [[unit] for unit in _split_project_units(paragraphs)]
            if content_type == "project"
            else [paragraphs]
        )
        for paragraph_group in paragraph_groups:
            for chunk_text in _pack_paragraphs(section_title, paragraph_group, chunk_size):
                if is_high_confidence_noise(chunk_text, section_title):
                    continue
                chunks.append(
                    TextChunk(
                        text=chunk_text,
                        index=len(chunks),
                        section_title=section_title,
                        content_type=content_type,
                        cleaning_status=(
                            "review_required"
                            if needs_ai_review(chunk_text, content_type)
                            else "clean"
                        ),
                    )
                )
    return chunks


def _split_sections(text: str) -> list[tuple[str, str, list[str]]]:
    sections: list[tuple[str, str, list[str]]] = []
    current_title = "文档内容"
    current_content_type = "body"
    current_paragraph_lines: list[str] = []
    current_paragraphs: list[str] = []

    def flush_paragraph() -> None:
        if current_paragraph_lines:
            current_paragraphs.append("\n".join(current_paragraph_lines).strip())
            current_paragraph_lines.clear()

    def flush_section() -> None:
        flush_paragraph()
        if current_paragraphs:
            sections.append((current_title, current_content_type, current_paragraphs.copy()))
            current_paragraphs.clear()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        heading = _detect_heading(line)
        if heading:
            flush_section()
            current_title = heading
            current_content_type = _content_type_for_heading(heading)
        elif line:
            current_paragraph_lines.append(line)
        else:
            flush_paragraph()

    flush_section()
    return sections


def _detect_heading(line: str) -> str | None:
    markdown_match = re.match(r"^#{1,6}\s+(.+)$", line)
    if markdown_match:
        return markdown_match.group(1).strip()

    page_match = re.match(r"^-{3}\s*Page\s+(\d+)\s*-{3}$", line, flags=re.IGNORECASE)
    if page_match:
        return f"第 {page_match.group(1)} 页"

    chinese_section_match = re.match(r"^第[一二三四五六七八九十百千万\d]+[章节部分]\s*[:：]?.*$", line)
    if chinese_section_match and len(line) <= 80:
        return line

    if classify_section_title(line):
        return line

    numbered_heading = re.match(r"^(?:\d+(?:\.\d+)*|[一二三四五六七八九十]+、)\s+(.+)$", line)
    if numbered_heading and len(line) <= 80:
        return line

    return None


def _content_type_for_heading(heading: str) -> str:
    classified = classify_section_title(heading)
    if classified:
        return classified
    if re.match(r"^第\s*\d+\s*页$", heading):
        return "body"
    return "body"


def _split_project_units(paragraphs: list[str]) -> list[str]:
    units: list[str] = []
    current: list[str] = []
    date_pattern = re.compile(
        r"\b(?:19|20)\d{2}[./年-]\d{0,2}\s*(?:[-–—至~]|到)\s*(?:至今|(?:19|20)\d{2})"
    )

    for paragraph in paragraphs:
        first_line = paragraph.splitlines()[0].strip()
        starts_new_project = bool(
            current
            and (
                date_pattern.search(first_line)
                or re.match(r"^(?:项目名称|项目名)\s*[:：]", first_line)
            )
        )
        if starts_new_project:
            units.append("\n\n".join(current))
            current = [paragraph]
        else:
            current.append(paragraph)

    if current:
        units.append("\n\n".join(current))
    return units


def _pack_paragraphs(section_title: str, paragraphs: list[str], chunk_size: int) -> list[str]:
    prefix = f"【{section_title}】\n"
    content_limit = max(200, chunk_size - len(prefix))
    units: list[str] = []
    for paragraph in paragraphs:
        units.extend(_split_long_paragraph(paragraph, content_limit))

    packed_chunks: list[str] = []
    current_units: list[str] = []
    current_length = 0

    for unit in units:
        separator_length = 2 if current_units else 0
        if current_units and current_length + separator_length + len(unit) > content_limit:
            packed_chunks.append(prefix + "\n\n".join(current_units))
            current_units = [unit]
            current_length = len(unit)
        else:
            current_units.append(unit)
            current_length += separator_length + len(unit)

    if current_units:
        packed_chunks.append(prefix + "\n\n".join(current_units))
    return packed_chunks


def _split_long_paragraph(paragraph: str, limit: int) -> list[str]:
    if len(paragraph) <= limit:
        return [paragraph]

    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[。！？；.!?;])\s*", paragraph)
        if sentence.strip()
    ]
    if len(sentences) <= 1:
        return _split_by_length(paragraph, limit)

    parts: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > limit:
            parts.append(current)
            current = sentence
        else:
            current += sentence

    if current:
        parts.append(current)

    split_parts: list[str] = []
    for part in parts:
        split_parts.extend(_split_by_length(part, limit))
    return split_parts


def _split_by_length(text: str, limit: int) -> list[str]:
    return [text[start : start + limit].strip() for start in range(0, len(text), limit) if text[start : start + limit].strip()]


def _compact_blank_lines(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    compacted = []
    previous_blank = False

    for line in lines:
        is_blank = not line
        if is_blank and previous_blank:
            continue
        compacted.append(line)
        previous_blank = is_blank

    return "\n".join(compacted).strip()
