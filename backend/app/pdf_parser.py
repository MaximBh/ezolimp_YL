from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any

try:
    import pypdfium2 as pdfium
except Exception:  # pragma: no cover - handled by callers
    pdfium = None


_STRONG_TASK_PATTERNS = [
    re.compile(r"^\s*(?:задача|задание|task)\s+(\d{1,3})(?:\s*[\.:]|$)", re.IGNORECASE),
    re.compile(r"^\s*№\s*(\d{1,3})(?:\s*[\.:]|$)", re.IGNORECASE),
]
_WEAK_TASK_PATTERN = re.compile(r"^\s*(\d{1,3})\.\s+\S")

_ANSWER_MARKER_RE = re.compile(r"^\s*(?:ответ|answer)\s*[:\-]", re.IGNORECASE)
_SOLUTION_START_RE = re.compile(
    r"^\s*(?:решение|разбор|official solution|solution)\s*[:\-]?\s*$",
    re.IGNORECASE,
)
_HEADER_NOISE_RE = re.compile(
    r"^\s*(?:всероссийская олимпиада школьников|школьный этап|муниципальный этап|региональный этап|"
    r"заключительный этап|max|максимальное количество баллов)\b",
    re.IGNORECASE,
)
_PAGE_NUMBER_RE = re.compile(r"^\s*\d{1,3}\s*$")

_CACHE: dict[tuple[str, int, int], list[dict[str, Any]]] = {}


def _normalize_text(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-zа-яё0-9]+", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def _similarity(left: str, right: str) -> float:
    left_norm = _normalize_text(left)
    right_norm = _normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm in right_norm:
        return 0.95
    ratio = difflib.SequenceMatcher(None, left_norm, right_norm).ratio()
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    overlap = 0.0
    if left_tokens and right_tokens:
        overlap = len(left_tokens & right_tokens) / max(len(left_tokens), 1)
    return max(ratio, 0.45 * ratio + 0.55 * overlap)


def _is_noise_line(line: str) -> bool:
    clean = str(line or "").strip()
    if not clean:
        return True
    if _PAGE_NUMBER_RE.match(clean):
        return True
    if _HEADER_NOISE_RE.match(clean):
        return True
    return False


def _split_statement_and_solution(lines: list[str]) -> tuple[str, str]:
    statement_lines: list[str] = []
    solution_lines: list[str] = []
    in_solution = False

    for raw_line in lines:
        line = str(raw_line or "").strip()
        if not line:
            if in_solution:
                if solution_lines and solution_lines[-1] != "":
                    solution_lines.append("")
            else:
                if statement_lines and statement_lines[-1] != "":
                    statement_lines.append("")
            continue

        if not in_solution and (_ANSWER_MARKER_RE.match(line) or _SOLUTION_START_RE.match(line)):
            in_solution = True
            solution_lines.append(line)
            continue

        if in_solution:
            solution_lines.append(line)
        else:
            statement_lines.append(line)

    statement = "\n".join(statement_lines).strip()
    solution = "\n".join(solution_lines).strip()
    return statement, solution


def _extract_pages(pdf_path: Path) -> list[dict[str, Any]]:
    if pdfium is None:
        raise RuntimeError("pypdfium2 is not installed")

    document = pdfium.PdfDocument(str(pdf_path))
    pages: list[dict[str, Any]] = []
    try:
        for page_index in range(len(document)):
            page = document[page_index]
            text_page = page.get_textpage()
            try:
                text = text_page.get_text_range() or ""
            finally:
                text_page.close()
            width, height = page.get_size()
            pages.append(
                {
                    "page": page_index + 1,
                    "text": text,
                    "width": width,
                    "height": height,
                }
            )
            page.close()
    finally:
        document.close()
    return pages


def _detect_entries(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    previous_clean = ""

    def flush_current() -> None:
        nonlocal current
        if not current:
            return
        statement, official_solution = _split_statement_and_solution(current["lines"])
        if statement:
            current["statement"] = statement
            current["official_solution"] = official_solution
            entries.append(current)
        current = None

    for page_data in pages:
        page_num = int(page_data.get("page") or 0)
        lines = str(page_data.get("text") or "").splitlines()
        for line in lines:
            clean = str(line or "").strip()
            if _is_noise_line(clean):
                previous_clean = clean
                continue

            matched_number: int | None = None
            for pattern in _STRONG_TASK_PATTERNS:
                match = pattern.match(clean)
                if match:
                    matched_number = int(match.group(1))
                    break

            if matched_number is None:
                weak = _WEAK_TASK_PATTERN.match(clean)
                if weak:
                    # Start a new task on weak marker only when the previous
                    # visible line is empty/noise to reduce false positives.
                    if not previous_clean or _is_noise_line(previous_clean):
                        matched_number = int(weak.group(1))

            if matched_number is not None:
                flush_current()
                current = {
                    "task_number": matched_number,
                    "page_start": page_num,
                    "page_end": page_num,
                    "lines": [clean],
                }
            elif current:
                current["page_end"] = page_num
                current["lines"].append(clean)

            previous_clean = clean

    flush_current()

    for index, entry in enumerate(entries, start=1):
        statement = str(entry.get("statement") or "")
        entry["index"] = index
        entry["statement_norm"] = _normalize_text(statement)
        entry["source_fragments"] = [
            {
                "page": page_num,
                "x": 0.0,
                "y": 0.0,
                "width": 1.0,
                "height": 1.0,
                "unit": "ratio",
                "order_index": page_num - int(entry["page_start"]) + 1,
            }
            for page_num in range(int(entry["page_start"]), int(entry["page_end"]) + 1)
        ]
    return entries


def _load_entries(pdf_path: Path) -> list[dict[str, Any]]:
    stat = pdf_path.stat()
    key = (str(pdf_path.resolve()), int(stat.st_mtime_ns), int(stat.st_size))
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    pages = _extract_pages(pdf_path)
    entries = _detect_entries(pages)
    # Keep a small multi-file cache to avoid reparsing the same PDFs
    # when switching between tasks and solution documents.
    if len(_CACHE) >= 24:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = entries
    return entries


def extract_best_task_entry(
    pdf_path: Path,
    task_number: int | None = None,
    statement_hint: str = "",
) -> dict[str, Any]:
    entries = _load_entries(pdf_path)
    if not entries:
        return {
            "found": False,
            "full_problem_statement": "",
            "official_solution_text": "",
            "source_page_start": None,
            "source_page_end": None,
            "source_fragments": [],
        }

    hint = str(statement_hint or "").strip()
    best_score = -1.0
    best_entry: dict[str, Any] | None = None

    for idx, entry in enumerate(entries):
        score = 0.0
        if task_number is not None:
            if int(entry.get("task_number") or -1) == int(task_number):
                score += 2.0
            else:
                score -= 0.2

        if hint:
            score += _similarity(hint, str(entry.get("statement") or ""))

        # Stable tiebreaker by original order.
        score -= idx * 0.0001
        if score > best_score:
            best_score = score
            best_entry = entry

    if best_entry is None:
        best_entry = entries[0]

    return {
        "found": True,
        "task_number": best_entry.get("task_number"),
        "full_problem_statement": str(best_entry.get("statement") or "").strip(),
        "official_solution_text": str(best_entry.get("official_solution") or "").strip(),
        "source_page_start": int(best_entry.get("page_start") or 0) or None,
        "source_page_end": int(best_entry.get("page_end") or 0) or None,
        "source_fragments": list(best_entry.get("source_fragments") or []),
    }

