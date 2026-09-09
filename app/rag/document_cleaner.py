from collections import Counter
from dataclasses import dataclass
import re
import unicodedata


EXCLUDED_SECTION_TYPES = {
    "toc",
    "reference",
    "acknowledgement",
    "declaration",
}

SECTION_PATTERNS = [
    ("reference", re.compile(r"^(参考文献|参考资料|引用文献|references|bibliography)\s*$", re.I)),
    ("toc", re.compile(r"^(目录|contents|table\s+of\s+contents)\s*$", re.I)),
    ("acknowledgement", re.compile(r"^(致谢|鸣谢|acknowledg(e)?ments?)\s*$", re.I)),
    ("declaration", re.compile(r"^(原创性声明|版权声明|学术诚信声明|declaration)\s*$", re.I)),
    ("project", re.compile(r"^(项目经历|项目介绍|项目设计|系统设计|系统实现|个人项目)\s*$", re.I)),
    ("method", re.compile(r"^(研究方法|实现方法|技术方案|架构设计|核心技术)\s*$", re.I)),
    ("result", re.compile(r"^(实验结果|测试结果|项目成果|总结与展望|结论)\s*$", re.I)),
]

PAGE_MARKER_PATTERN = re.compile(r"^-{3}\s*Page\s+\d+\s*-{3}$", re.I)
PAGE_NUMBER_PATTERN = re.compile(
    r"^(?:第\s*)?\d+\s*(?:页)?(?:\s*/\s*(?:共\s*)?\d+\s*页?)?$|^page\s+\d+(?:\s+of\s+\d+)?$",
    re.I,
)
SEPARATOR_PATTERN = re.compile(r"^[\s\-_=·•—–…│┃|.]{3,}$")
TOC_LINE_PATTERN = re.compile(r"^.{1,80}[.…·\s]{3,}\d+\s*$")
REFERENCE_ENTRY_PATTERN = re.compile(r"^\s*(?:\[\d+\]|\(\d+\)|（\d+）)\s*")
REFERENCE_MARKER_PATTERN = re.compile(r"\[(?:J|M|C|D|R|S|P|EB/OL)\]", re.I)


@dataclass(frozen=True)
class CleaningStats:
    original_line_count: int = 0
    kept_line_count: int = 0
    removed_noise_line_count: int = 0
    removed_repeated_header_footer_count: int = 0
    excluded_section_count: int = 0


@dataclass(frozen=True)
class CleanedDocument:
    text: str
    stats: CleaningStats


def clean_project_document(text: str) -> CleanedDocument:
    pages = _split_pages(text)
    repeated_edges = _find_repeated_page_edges(pages)
    output_lines: list[str] = []
    removed_noise = 0
    removed_repeated = 0
    excluded_sections = 0
    active_section_type = "body"

    for marker, lines in pages:
        short_noise_indexes = _find_short_line_noise_indexes(lines)
        if marker:
            output_lines.extend([marker, ""])

        for line_index, raw_line in enumerate(lines):
            line = _normalize_line(raw_line)
            if not line:
                if output_lines and output_lines[-1]:
                    output_lines.append("")
                continue

            if line in repeated_edges:
                removed_repeated += 1
                continue
            if line_index in short_noise_indexes:
                removed_noise += 1
                continue

            section_type = classify_section_title(line)
            if section_type:
                if section_type in EXCLUDED_SECTION_TYPES:
                    excluded_sections += 1
                active_section_type = section_type
                if section_type not in EXCLUDED_SECTION_TYPES:
                    output_lines.extend([line, ""])
                continue

            if active_section_type in EXCLUDED_SECTION_TYPES:
                continue

            if is_noise_line(line):
                removed_noise += 1
                continue

            output_lines.append(line)

    cleaned = _compact_blank_lines("\n".join(output_lines))
    original_line_count = len(text.splitlines())
    kept_line_count = len([line for line in cleaned.splitlines() if line.strip()])
    return CleanedDocument(
        text=cleaned,
        stats=CleaningStats(
            original_line_count=original_line_count,
            kept_line_count=kept_line_count,
            removed_noise_line_count=removed_noise,
            removed_repeated_header_footer_count=removed_repeated,
            excluded_section_count=excluded_sections,
        ),
    )


def classify_section_title(line: str) -> str | None:
    normalized = re.sub(r"^[#\d.\s、（）()一二三四五六七八九十]+", "", line).strip(" ：:")
    for section_type, pattern in SECTION_PATTERNS:
        if pattern.fullmatch(normalized):
            return section_type
    return None


def is_high_confidence_noise(text: str, section_title: str = "") -> bool:
    if classify_section_title(section_title) in EXCLUDED_SECTION_TYPES:
        return True

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return True
    reference_hits = sum(
        bool(REFERENCE_ENTRY_PATTERN.match(line) or REFERENCE_MARKER_PATTERN.search(line))
        for line in lines
    )
    if reference_hits >= 2 and reference_hits / len(lines) >= 0.5:
        return True
    return sum(is_noise_line(line) for line in lines) / len(lines) >= 0.6


def needs_ai_review(text: str, content_type: str) -> bool:
    if content_type != "body" or len(text) < 80:
        return False
    lines = [line for line in text.splitlines() if line.strip()]
    suspicious_hits = sum(
        bool(REFERENCE_ENTRY_PATTERN.match(line) or TOC_LINE_PATTERN.match(line))
        for line in lines
    )
    readable_ratio = _readable_ratio(text)
    return suspicious_hits > 0 or readable_ratio < 0.75


def is_noise_line(line: str) -> bool:
    if PAGE_MARKER_PATTERN.fullmatch(line):
        return False
    if PAGE_NUMBER_PATTERN.fullmatch(line):
        return True
    if SEPARATOR_PATTERN.fullmatch(line):
        return True
    if TOC_LINE_PATTERN.fullmatch(line):
        return True
    if len(line) <= 2 and not re.search(r"[\w\u4e00-\u9fff]", line):
        return True
    return len(line) >= 8 and _readable_ratio(line) < 0.45


def _split_pages(text: str) -> list[tuple[str, list[str]]]:
    pages: list[tuple[str, list[str]]] = []
    current_marker = ""
    current_lines: list[str] = []
    for line in text.splitlines():
        if PAGE_MARKER_PATTERN.fullmatch(line.strip()):
            if current_lines or current_marker:
                pages.append((current_marker, current_lines))
            current_marker = line.strip()
            current_lines = []
        else:
            current_lines.append(line)
    pages.append((current_marker, current_lines))
    return pages


def _find_repeated_page_edges(pages: list[tuple[str, list[str]]]) -> set[str]:
    if len(pages) < 2:
        return set()
    candidates: list[str] = []
    for _, lines in pages:
        non_empty = [_normalize_line(line) for line in lines if _normalize_line(line)]
        if not non_empty:
            continue
        page_candidates = set(non_empty[:2] + non_empty[-2:])
        for line in page_candidates:
            if 3 <= len(line) <= 80 and not classify_section_title(line):
                candidates.append(line)
    minimum_repeats = 2 if len(pages) <= 3 else 3
    return {
        line
        for line, count in Counter(candidates).items()
        if count >= minimum_repeats
    }


def _find_short_line_noise_indexes(lines: list[str]) -> set[int]:
    noise_indexes: set[int] = set()
    run: list[int] = []

    def flush_run() -> None:
        if len(run) >= 5:
            noise_indexes.update(run)
        run.clear()

    for index, raw_line in enumerate(lines):
        line = _normalize_line(raw_line)
        if line and len(line) <= 2 and not classify_section_title(line):
            run.append(index)
        else:
            flush_run()
    flush_run()
    return noise_indexes


def _normalize_line(line: str) -> str:
    line = line.replace("\u200b", "").replace("\ufeff", "")
    line = "".join(char for char in line if unicodedata.category(char) != "Cc" or char == "\t")
    return re.sub(r"[ \t]+", " ", line).strip()


def _readable_ratio(text: str) -> float:
    visible = [char for char in text if not char.isspace()]
    if not visible:
        return 0.0
    readable = sum(
        char.isalnum()
        or "\u4e00" <= char <= "\u9fff"
        or char in "，。！？；：、,.!?;:()（）[]【】+-_/%"
        for char in visible
    )
    return readable / len(visible)


def _compact_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).strip()
