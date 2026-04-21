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
    re.compile(r"^\s*(?:№|n)\s*(\d{1,3})(?:\s*[\.:]|\b|$)", re.IGNORECASE),
]
_VARIANT_RE = re.compile(
    r"^\s*(?:задача|задание|task)\s+(\d{1,3})(?:\s*[\.:])?\s*[Вв]ариант\s+(\d+)(?:\s*[\.:])?",
    re.IGNORECASE,
)
_STANDALONE_VARIANT_RE = re.compile(r"^\s*[Вв]ариант\s+(\d+)(?:\s*[\.:])?", re.IGNORECASE)
_WEAK_TASK_PATTERN = re.compile(r"^\s*(\d{1,3})\.\s+\S")

_ANSWER_MARKER_RE = re.compile(r"^\s*(?:ответ|answer)\s*[:\-]", re.IGNORECASE)
_SOLUTION_START_RE = re.compile(
    r"^\s*(?:решение|разбор|official solution|solution)\s*[:\-]?\s*$",
    re.IGNORECASE,
)
_INLINE_POINTS_MARKER_RE = re.compile(
    r"(\d{1,2}\s+балл(?:а|ов)?\s*\(\s*\d{1,2}\s+балл(?:а|ов)?\s*\))",
    re.IGNORECASE,
)
_HEADER_NOISE_RE = re.compile(
    r"(?:всероссийская олимпиада школьников|пригласительный этап|школьный этап|муниципальный этап|"
    r"региональный этап|заключительный этап|max|максимальное количество баллов)\b",
    re.IGNORECASE,
)
_ACADEMIC_YEAR_RE = re.compile(r"\b20\d{2}\s*[–-]\s*20\d{2}\s*уч\.?\s*г\.?", re.IGNORECASE)
_CITY_DATE_RE = re.compile(
    r"^\s*(?:г\.\s*)?[А-ЯЁ][А-ЯЁа-яё\-\s]{1,48},?\s*\d{1,2}\s+"
    r"(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)"
    r"\s+20\d{2}(?:\s*г(?:ода|\.)?)?\s*$",
    re.IGNORECASE,
)
_PAGE_NUMBER_RE = re.compile(r"^\s*\d{1,4}\s*$")

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


def _statement_strength(value: str) -> int:
    return len(_normalize_text(value or ""))


def _is_noise_line(line: str) -> bool:
    clean = str(line or "").strip()
    if not clean:
        return True
    if _PAGE_NUMBER_RE.match(clean):
        return True
    if _HEADER_NOISE_RE.search(clean):
        if len(clean) <= 180 and "?" not in clean:
            return True
    lowered = clean.lower()
    if _ACADEMIC_YEAR_RE.search(clean) and "этап" in lowered and "класс" in lowered:
        if len(clean) <= 220 and "?" not in clean:
            return True
    if "олимпиад" in lowered and "этап" in lowered and "класс" in lowered:
        if len(clean) <= 220 and "?" not in clean:
            return True
    if "уч. г." in lowered and "этап" in lowered:
        if len(clean) <= 220 and "?" not in clean:
            return True
    if _CITY_DATE_RE.match(clean):
        if len(clean) <= 120 and "?" not in clean:
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


def _clamp_ratio(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _char_range_bbox_ratio(
    text_page,
    text: str,
    start_index: int,
    end_index: int,
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float] | None:
    if page_width <= 0 or page_height <= 0:
        return None
    if start_index < 0:
        start_index = 0
    if end_index <= start_index:
        return None

    max_index = min(len(text), int(text_page.count_chars()))
    if start_index >= max_index:
        return None
    end_index = min(end_index, max_index)

    left = None
    right = None
    bottom = None
    top = None

    for char_index in range(start_index, end_index):
        char_value = text[char_index]
        if char_value in {"\r", "\n"}:
            continue
        try:
            x0, y0, x1, y1 = text_page.get_charbox(char_index)
        except Exception:
            continue

        char_left = min(float(x0), float(x1))
        char_right = max(float(x0), float(x1))
        char_bottom = min(float(y0), float(y1))
        char_top = max(float(y0), float(y1))
        if char_right <= char_left or char_top <= char_bottom:
            continue

        left = char_left if left is None else min(left, char_left)
        right = char_right if right is None else max(right, char_right)
        bottom = char_bottom if bottom is None else min(bottom, char_bottom)
        top = char_top if top is None else max(top, char_top)

    if left is None or right is None or bottom is None or top is None:
        return None

    ratio_left = _clamp_ratio(left / page_width)
    ratio_right = _clamp_ratio(right / page_width)
    ratio_top = _clamp_ratio(1.0 - (top / page_height))
    ratio_bottom = _clamp_ratio(1.0 - (bottom / page_height))
    if ratio_right <= ratio_left or ratio_bottom <= ratio_top:
        return None
    return ratio_left, ratio_top, ratio_right, ratio_bottom


def _split_flattened_line_ranges(line_text: str) -> list[tuple[int, int, bool]]:
    text = str(line_text or "")
    if len(text) < 900:
        return [(0, len(text), False)]

    markers = list(_INLINE_POINTS_MARKER_RE.finditer(text))
    if len(markers) < 2:
        return [(0, len(text), False)]

    boundaries = [0]
    for marker in markers[1:]:
        boundaries.append(marker.start(1))
    boundaries.append(len(text))

    ranges: list[tuple[int, int, bool]] = []
    for idx in range(len(boundaries) - 1):
        start = boundaries[idx]
        end = boundaries[idx + 1]
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if end - start < 40:
            continue
        ranges.append((start, end, True))

    if len(ranges) < 2:
        return [(0, len(text), False)]
    return ranges


def _extract_page_lines(text_page, text: str, page_width: float, page_height: float) -> list[dict[str, Any]]:
    if not text:
        return []

    records: list[dict[str, Any]] = []
    cursor = 0
    for line_with_break in text.splitlines(keepends=True):
        line_text = line_with_break.rstrip("\r\n")
        line_start = cursor
        line_ranges = _split_flattened_line_ranges(line_text)
        for sub_start, sub_end, question_start in line_ranges:
            global_start = line_start + sub_start
            global_end = line_start + sub_end
            sub_text = line_text[sub_start:sub_end]
            line_bbox = _char_range_bbox_ratio(
                text_page,
                text,
                global_start,
                global_end,
                page_width,
                page_height,
            )
            records.append(
                {
                    "text": sub_text,
                    "bbox": line_bbox,
                    "question_start": bool(question_start),
                }
            )
        cursor += len(line_with_break)

    if cursor < len(text):
        line_text = text[cursor:]
        line_ranges = _split_flattened_line_ranges(line_text)
        for sub_start, sub_end, question_start in line_ranges:
            global_start = cursor + sub_start
            global_end = cursor + sub_end
            sub_text = line_text[sub_start:sub_end]
            line_bbox = _char_range_bbox_ratio(
                text_page,
                text,
                global_start,
                global_end,
                page_width,
                page_height,
            )
            records.append(
                {
                    "text": sub_text,
                    "bbox": line_bbox,
                    "question_start": bool(question_start),
                }
            )

    return records


def _merge_ratio_boxes(boxes: list[tuple[float, float, float, float]]):
    if not boxes:
        return None
    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[2] for box in boxes)
    bottom = max(box[3] for box in boxes)

    # Small padding so we don't trim punctuation/superscripts at the edges.
    pad_x = 0.006
    pad_y = 0.008
    left = _clamp_ratio(left - pad_x)
    top = _clamp_ratio(top - pad_y)
    right = _clamp_ratio(right + pad_x)
    bottom = _clamp_ratio(bottom + pad_y)
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _entry_source_fragments(entry: dict[str, Any]) -> list[dict[str, Any]]:
    line_boxes_by_page = entry.get("line_boxes_by_page") or {}
    fragments: list[dict[str, Any]] = []
    order_index = 1

    if isinstance(line_boxes_by_page, dict):
        for page_num in sorted(line_boxes_by_page):
            try:
                page_int = int(page_num)
            except Exception:
                continue
            page_boxes = line_boxes_by_page.get(page_num) or []
            merged = _merge_ratio_boxes(page_boxes)
            if not merged:
                continue
            left, top, right, bottom = merged
            fragments.append(
                {
                    "page": page_int,
                    "x": left,
                    "y": top,
                    "width": right - left,
                    "height": bottom - top,
                    "unit": "ratio",
                    "order_index": order_index,
                }
            )
            order_index += 1

    if fragments:
        return fragments

    page_start = int(entry.get("page_start") or 0)
    page_end = int(entry.get("page_end") or page_start)
    if page_start <= 0 or page_end < page_start:
        return []

    fallback = []
    order_index = 1
    for page_num in range(page_start, page_end + 1):
        fallback.append(
            {
                "page": page_num,
                "x": 0.0,
                "y": 0.0,
                "width": 1.0,
                "height": 1.0,
                "unit": "ratio",
                "order_index": order_index,
            }
        )
        order_index += 1
    return fallback


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
                width, height = page.get_size()
                line_records = _extract_page_lines(text_page, text, width, height)
            finally:
                text_page.close()
            pages.append(
                {
                    "page": page_index + 1,
                    "text": text,
                    "lines": line_records,
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
            current["source_fragments"] = _entry_source_fragments(current)
            entries.append(current)
        current = None

    for page_data in pages:
        page_num = int(page_data.get("page") or 0)
        page_lines = page_data.get("lines")
        if isinstance(page_lines, list) and page_lines:
            line_records = page_lines
        else:
            line_records = [{"text": line} for line in str(page_data.get("text") or "").splitlines()]

        for line_item in line_records:
            if isinstance(line_item, dict):
                raw_line = line_item.get("text")
                line_bbox = line_item.get("bbox")
                question_start = bool(line_item.get("question_start"))
            else:
                raw_line = line_item
                line_bbox = None
                question_start = False

            clean = str(raw_line or "").strip()
            if _is_noise_line(clean):
                previous_clean = clean
                continue

            matched_number: int | None = None
            matched_variant: int | None = None

            vm = _VARIANT_RE.match(clean)
            if vm:
                matched_number = int(vm.group(1))
                matched_variant = int(vm.group(2))
            else:
                for pattern in _STRONG_TASK_PATTERNS:
                    match = pattern.match(clean)
                    if match:
                        matched_number = int(match.group(1))
                        break

            if matched_number is None:
                weak = _WEAK_TASK_PATTERN.match(clean)
                if weak:
                    if not previous_clean or _is_noise_line(previous_clean):
                        matched_number = int(weak.group(1))

            if matched_number is None and current:
                standalone_variant = _STANDALONE_VARIANT_RE.match(clean)
                if standalone_variant and current.get("variant") is None:
                    current["variant"] = int(standalone_variant.group(1))

            should_start_new = matched_number is not None or (question_start and current is not None)

            if should_start_new:
                flush_current()
                current = {
                    "task_number": matched_number,
                    "variant": matched_variant,
                    "page_start": page_num,
                    "page_end": page_num,
                    "lines": [clean],
                    "line_boxes_by_page": {page_num: [line_bbox]} if line_bbox else {},
                }
            elif current is None:
                current = {
                    "task_number": None,
                    "variant": None,
                    "page_start": page_num,
                    "page_end": page_num,
                    "lines": [clean],
                    "line_boxes_by_page": {page_num: [line_bbox]} if line_bbox else {},
                }
            else:
                current["page_end"] = page_num
                current["lines"].append(clean)
                if line_bbox:
                    page_boxes = current.setdefault("line_boxes_by_page", {}).setdefault(page_num, [])
                    page_boxes.append(line_bbox)

            previous_clean = clean

    flush_current()

    for index, entry in enumerate(entries, start=1):
        statement = str(entry.get("statement") or "")
        entry["index"] = index
        entry["statement_norm"] = _normalize_text(statement)
        entry.pop("line_boxes_by_page", None)
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


def extract_task_entries(pdf_path: Path) -> list[dict[str, Any]]:
    entries = _load_entries(pdf_path)
    result: list[dict[str, Any]] = []
    for entry in entries:
        result.append(
            {
                "task_number": entry.get("task_number"),
                "variant": entry.get("variant"),
                "index": entry.get("index"),
                "full_problem_statement": str(entry.get("statement") or "").strip(),
                "official_solution_text": str(entry.get("official_solution") or "").strip(),
                "source_page_start": int(entry.get("page_start") or 0) or None,
                "source_page_end": int(entry.get("page_end") or 0) or None,
                "source_fragments": entry.get("source_fragments") or [],
            }
        )
    return result


def extract_best_task_entry(
    pdf_path: Path,
    task_number: int | None = None,
    variant_number: int | None = None,
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
    candidate_entries = entries
    if task_number is not None:
        task_matches = [
            entry
            for entry in candidate_entries
            if int(entry.get("task_number") or -1) == int(task_number)
        ]
        task_matches = [
            entry for entry in task_matches if _statement_strength(str(entry.get("statement") or "")) >= 30
        ]
        if task_matches:
            candidate_entries = task_matches

    if variant_number is not None:
        variant_matches = [
            entry
            for entry in candidate_entries
            if entry.get("variant") is not None and int(entry.get("variant")) == int(variant_number)
        ]
        variant_matches = [
            entry for entry in variant_matches if _statement_strength(str(entry.get("statement") or "")) >= 30
        ]
        if variant_matches:
            candidate_entries = variant_matches

    best_score = -1.0
    best_entry: dict[str, Any] | None = None

    for idx, entry in enumerate(candidate_entries):
        score = 0.0
        statement_strength = _statement_strength(str(entry.get("statement") or ""))
        if statement_strength < 16:
            score -= 2.5
        elif statement_strength < 30:
            score -= 1.2
        elif statement_strength < 60:
            score -= 0.35
        if task_number is not None:
            if int(entry.get("task_number") or -1) == int(task_number):
                score += 2.0
            else:
                score -= 0.2

        if variant_number is not None:
            entry_variant = entry.get("variant")
            if entry_variant is None:
                score -= 0.05
            elif int(entry_variant) == int(variant_number):
                score += 1.5
            else:
                score -= 1.0

        if hint:
            score += _similarity(hint, str(entry.get("statement") or ""))

        # Stable tiebreaker by original order.
        stable_index = int(entry.get("index") or (idx + 1))
        score -= stable_index * 0.0001
        if score > best_score:
            best_score = score
            best_entry = entry

    if best_entry is None:
        best_entry = candidate_entries[0] if candidate_entries else entries[0]

    return {
        "found": True,
        "task_number": best_entry.get("task_number"),
        "variant": best_entry.get("variant"),
        "full_problem_statement": str(best_entry.get("statement") or "").strip(),
        "official_solution_text": str(best_entry.get("official_solution") or "").strip(),
        "source_page_start": int(best_entry.get("page_start") or 0) or None,
        "source_page_end": int(best_entry.get("page_end") or 0) or None,
        "source_fragments": best_entry.get("source_fragments") or [],
    }
