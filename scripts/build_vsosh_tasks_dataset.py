#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen, urlretrieve


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_CACHE_DIR = ROOT_DIR / "backend" / "cache"
PDF_CACHE_DIR = BACKEND_CACHE_DIR / "pdf_sources"
TASKS_JSON_PATH = ROOT_DIR / "tasks.json"

sys.path.insert(0, str(ROOT_DIR))
from backend.app.pdf_parser import _load_entries  # noqa: E402


ARCHIVE_YEAR_IDS = [
    "2025_2026",
    "2024_2025",
    "2023_2024",
    "2022_2023",
    "2021_2022",
    "2020_2021",
    "2019_2020",
    "2018_2019",
]

SUBJECT_CONFIGS = [
    {"name": "математика", "slugs": {"math"}},
    {"name": "информатика", "slugs": {"iikt"}},
    {"name": "физика", "slugs": {"phys"}},
    {"name": "химия", "slugs": {"chem"}},
    {"name": "биология", "slugs": {"biol"}},
    {"name": "английский", "slugs": {"engl"}},
    {"name": "русский", "slugs": {"russ"}},
    {"name": "история", "slugs": {"hist"}},
    {"name": "география", "slugs": {"geog"}},
    {"name": "обществознание", "slugs": {"soci"}},
    {"name": "право", "slugs": {"law"}},
    {"name": "литература", "slugs": {"litr"}},
    {"name": "экология", "slugs": {"ekol"}},
    {
        "name": "робототехника",
        "slugs": {"robo", "tech"},
        "required_name_tokens": {"robo", "techrobo"},
    },
]

TARGET_GRADES = list(range(5, 12))
TARGET_PER_SUBJECT_GRADE = 20
TARGET_TOTAL_TASKS = 2000
BASE_URL = "https://xn--b1ayi3a.xn--l1afu.xn--p1ai/archive/table/tasks/years/"

STAGE_RANK = {
    "school": 0,
    "prigl": 1,
    "mun": 2,
    "reg": 3,
    "zakl": 4,
}

PDF_LINK_RE = re.compile(r"""href=['"]([^'"]+\.pdf)['"]""", re.IGNORECASE)
PDF_META_RE = re.compile(
    r"/(?P<season>\d{4}-\d{2})/"
    r"(?P<stage>school|prigl|mun|reg|zakl)/"
    r"(?P<slug>[a-z0-9]+)/"
    r"(?P<name>[^/?#]+\.pdf)$",
    re.IGNORECASE,
)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[\.\?!])\s+")
WHITESPACE_RE = re.compile(r"\s+")
TASK_WORD_RE = re.compile(r"(?:задач[аеи]|задани[ея]|task)\s+\d{1,3}", re.IGNORECASE)
ANSWER_PATTERNS = [
    re.compile(r"(?im)^\s*итоговый\s+ответ\s*[:\-]\s*(.+)$"),
    re.compile(r"(?im)^\s*ответ\s*[:\-]\s*(.+)$"),
    re.compile(r"(?im)^\s*final\s+answer\s*[:\-]\s*(.+)$"),
]

STOP_TOKENS = {
    "tasks",
    "task",
    "taskskrit",
    "sol",
    "ans",
    "answer",
    "sch",
    "prigl",
    "mun",
    "reg",
    "zakl",
    "teor",
    "prak",
    "msk",
    "tur1",
    "tur2",
    "secr",
    "home",
}

PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
FAILED_URLS: set[str] = set()


@dataclass
class PdfFile:
    url: str
    year_id: str
    season: str
    stage: str
    slug: str
    name: str
    kind: str
    grades: list[int]


def _fetch_archive_pdf_links(year_id: str) -> list[str]:
    url = f"{BASE_URL}{year_id}"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    html = urlopen(request, timeout=30).read().decode("utf-8", errors="ignore")
    links = [urljoin(url, m.group(1)) for m in PDF_LINK_RE.finditer(html)]
    deduped: list[str] = []
    seen = set()
    for link in links:
        if link in seen:
            continue
        seen.add(link)
        deduped.append(link)
    return deduped


def _extract_grades_from_name(name: str) -> list[int]:
    nums = [int(x) for x in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", name)]
    grades = sorted({n for n in nums if 1 <= n <= 11})
    if not grades:
        return []
    if len(grades) >= 2 and grades[-1] - grades[0] <= 6:
        return list(range(grades[0], grades[-1] + 1))
    return grades


def _classify_kind(name: str) -> str:
    lower = name.lower()
    if "task" in lower and not any(token in lower for token in ("sol", "ans", "answer")):
        return "tasks"
    if any(token in lower for token in ("sol", "ans", "answer")):
        return "solution"
    return "other"


def _build_catalog() -> list[PdfFile]:
    catalog: list[PdfFile] = []
    for year_id in ARCHIVE_YEAR_IDS:
        links = _fetch_archive_pdf_links(year_id)
        for link in links:
            parsed = PDF_META_RE.search(link)
            if not parsed:
                continue
            season = parsed.group("season").lower()
            stage = parsed.group("stage").lower()
            slug = parsed.group("slug").lower()
            name = parsed.group("name").lower()
            kind = _classify_kind(name)
            grades = _extract_grades_from_name(name)
            if not grades:
                continue
            catalog.append(
                PdfFile(
                    url=link,
                    year_id=year_id,
                    season=season,
                    stage=stage,
                    slug=slug,
                    name=name,
                    kind=kind,
                    grades=grades,
                )
            )
    return catalog


def _pdf_cache_path(url: str) -> Path:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix != ".pdf":
        suffix = ".pdf"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return PDF_CACHE_DIR / f"{digest}{suffix}"


def _ensure_local_pdf(url: str) -> Path:
    path = _pdf_cache_path(url)
    if path.exists() and path.stat().st_size > 0:
        return path
    tmp = path.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink(missing_ok=True)
    urlretrieve(url, tmp)
    if not tmp.exists() or tmp.stat().st_size <= 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to download PDF: {url}")
    tmp.replace(path)
    return path


def _clean_text(text: str, limit: int = 12000) -> str:
    clean = str(text or "").replace("\ufeff", " ")
    clean = WHITESPACE_RE.sub(" ", clean).strip()
    return clean[:limit].strip()


def _looks_like_task_text(text: str) -> bool:
    if not text or len(text) < 35:
        return False
    if len(text) > 20000:
        return False
    if TASK_WORD_RE.findall(text) and len(TASK_WORD_RE.findall(text)) > 4:
        return False
    return True


def _tokenize_name(name: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]+", name.lower()))
    return {token for token in tokens if token not in STOP_TOKENS and len(token) > 1}


def _solution_url_candidates(task_url: str) -> list[str]:
    repl = [
        ("tasks-", "sol-"),
        ("tasks_", "sol_"),
        ("taskskrit-", "ans-"),
        ("taskskrit_", "ans_"),
        ("tasks-", "ans-"),
        ("tasks_", "ans_"),
        ("task-", "sol-"),
        ("task_", "sol_"),
    ]
    candidates = [task_url]
    for old, new in repl:
        if old in task_url:
            candidates.append(task_url.replace(old, new))
    deduped: list[str] = []
    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return deduped


def _match_solution_file(
    task_file: PdfFile,
    solution_lookup: dict[tuple[str, str, str], list[PdfFile]],
    all_solution_urls: set[str],
) -> PdfFile | None:
    for candidate_url in _solution_url_candidates(task_file.url):
        if candidate_url in all_solution_urls:
            for f in solution_lookup.get((task_file.season, task_file.stage, task_file.slug), []):
                if f.url == candidate_url:
                    return f

    candidates = solution_lookup.get((task_file.season, task_file.stage, task_file.slug), [])
    if not candidates:
        return None

    task_tokens = _tokenize_name(task_file.name)
    task_grades = set(task_file.grades)
    best_score = float("-inf")
    best: PdfFile | None = None
    for candidate in candidates:
        overlap = len(task_grades & set(candidate.grades))
        token_overlap = len(task_tokens & _tokenize_name(candidate.name))
        score = overlap * 50 + token_overlap * 5 - abs(len(candidate.name) - len(task_file.name)) * 0.01
        if score > best_score:
            best_score = score
            best = candidate
    return best


def _extract_answer(text: str) -> str:
    clean = _clean_text(text, limit=4000)
    if not clean:
        return "see solution"
    for pattern in ANSWER_PATTERNS:
        match = pattern.search(clean)
        if match:
            answer = _clean_text(match.group(1), limit=256)
            if answer:
                return answer

    tail_numbers = re.findall(r"(?<!\d)(\d+(?:[.,]\d+)?)(?!\d)", clean[-250:])
    if tail_numbers:
        return tail_numbers[-1].replace(",", ".")
    return "see solution"


def _build_ai_explanation(statement: str, official_solution: str, answer: str, subject: str, grade: int) -> str:
    statement_clean = _clean_text(statement, limit=1800)
    official_clean = _clean_text(official_solution, limit=2200)

    idea = ""
    if statement_clean:
        first_sentence = SENTENCE_SPLIT_RE.split(statement_clean)[0].strip()
        idea = first_sentence[:260]
    if not idea:
        idea = f"Рассматриваем задачу по предмету «{subject}» для {grade} класса."

    lines = []
    for chunk in re.split(r"[\n\r]+", official_solution or ""):
        chunk_clean = _clean_text(chunk, limit=350)
        if len(chunk_clean) < 18:
            continue
        if chunk_clean.lower().startswith(("ответ", "итоговый ответ", "final answer")):
            continue
        lines.append(chunk_clean)
        if len(lines) >= 4:
            break

    if not lines and official_clean:
        sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(official_clean) if len(s.strip()) > 18]
        lines = sentences[:4]

    if not lines:
        fallback = []
        if statement_clean:
            fallback.append(f"Из условия выделяем ключевые данные: {statement_clean[:280]}.")
        fallback.append("Строим последовательное решение с проверкой ограничений задачи.")
        if answer and answer != "see solution":
            fallback.append(f"Проверяем вычисления и фиксируем ответ: {answer}.")
        lines = fallback

    steps = [f"{idx}. {line}" for idx, line in enumerate(lines, start=1)]
    answer_line = answer if answer else "см. официальное решение"
    payload = [
        "Решение (сгенерировано нейросетью):",
        f"Идея: {idea}",
        *steps,
        f"Итоговый ответ: {answer_line}",
    ]
    return "\n".join(payload).strip()


def _difficulty_and_points(index_in_bucket: int) -> tuple[str, int]:
    if index_in_bucket < 7:
        return "easy", 6
    if index_in_bucket < 14:
        return "medium", 10
    return "hard", 14


def _season_start_year(season: str, fallback_year_id: str) -> str:
    match = re.match(r"(\d{4})-\d{2}", season or "")
    if match:
        return match.group(1)
    return fallback_year_id.split("_", 1)[0]


def _subject_allows_file(subject_cfg: dict[str, Any], pdf_file: PdfFile) -> bool:
    if pdf_file.slug not in subject_cfg["slugs"]:
        return False
    required_tokens = set(subject_cfg.get("required_name_tokens") or set())
    if not required_tokens:
        return True
    name = pdf_file.name.lower()
    return any(token in name for token in required_tokens)


def _grade_distance(target_grade: int, source_grades: Iterable[int]) -> int:
    grades = list(source_grades)
    if not grades:
        return 99
    return min(abs(target_grade - g) for g in grades)


def _candidate_score(target_grade: int, task_file: PdfFile, entries_count: int) -> float:
    dist = _grade_distance(target_grade, task_file.grades)
    stage_rank = STAGE_RANK.get(task_file.stage, 10)
    season_start = int(_season_start_year(task_file.season, task_file.year_id))
    score = 600.0
    score -= dist * 80
    if target_grade in task_file.grades:
        score += 120
    score -= stage_rank * 6
    if task_file.stage == "school":
        score += 28
    elif task_file.stage == "prigl":
        score += 18
    score += max(0, season_start - 2017) * 2
    score += min(entries_count, 30)
    return score


def _normalize_source_fragments(entry: dict[str, Any], page_start: int | None, page_end: int | None) -> list[dict[str, Any]]:
    raw = entry.get("source_fragments") or []
    normalized: list[dict[str, Any]] = []
    for idx, fragment in enumerate(raw, start=1):
        try:
            page = int(fragment.get("page"))
        except Exception:
            continue
        normalized.append(
            {
                "page": page,
                "x": 0.0 if fragment.get("x") is None else float(fragment.get("x")),
                "y": 0.0 if fragment.get("y") is None else float(fragment.get("y")),
                "width": 1.0 if fragment.get("width") is None else float(fragment.get("width")),
                "height": 1.0 if fragment.get("height") is None else float(fragment.get("height")),
                "unit": str(fragment.get("unit") or "ratio"),
                "order_index": int(fragment.get("order_index") or idx),
            }
        )
    if normalized:
        return normalized

    if page_start and page_end and page_end >= page_start:
        fallback = []
        order = 1
        for page in range(page_start, page_end + 1):
            fallback.append(
                {
                    "page": page,
                    "x": 0.0,
                    "y": 0.0,
                    "width": 1.0,
                    "height": 1.0,
                    "unit": "ratio",
                    "order_index": order,
                }
            )
            order += 1
        return fallback
    return []


def _load_entries_cached(url: str, cache: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    if url in FAILED_URLS:
        return []
    cached = cache.get(url)
    if cached is not None:
        return cached
    try:
        pdf_path = _ensure_local_pdf(url)
        entries = _load_entries(pdf_path)
    except Exception:
        FAILED_URLS.add(url)
        cache[url] = []
        return []
    cache[url] = entries
    return entries


def build_dataset() -> dict[str, Any]:
    catalog = _build_catalog()
    task_files = [f for f in catalog if f.kind == "tasks"]
    solution_files = [f for f in catalog if f.kind == "solution"]

    solution_lookup: dict[tuple[str, str, str], list[PdfFile]] = defaultdict(list)
    for solution_file in solution_files:
        solution_lookup[(solution_file.season, solution_file.stage, solution_file.slug)].append(solution_file)
    all_solution_urls = {f.url for f in solution_files}

    entries_cache: dict[str, list[dict[str, Any]]] = {}
    candidate_pool: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)

    for subject_cfg in SUBJECT_CONFIGS:
        subject_name = subject_cfg["name"]
        matched_task_files = [f for f in task_files if _subject_allows_file(subject_cfg, f)]
        for task_file in matched_task_files:
            task_entries = _load_entries_cached(task_file.url, entries_cache)
            if not task_entries:
                continue

            solution_file = _match_solution_file(task_file, solution_lookup, all_solution_urls)
            solution_map: dict[int, str] = {}
            if solution_file:
                solution_entries = _load_entries_cached(solution_file.url, entries_cache)
                for entry in solution_entries:
                    try:
                        task_num = int(entry.get("task_number"))
                    except Exception:
                        continue
                    text = _clean_text(entry.get("official_solution") or entry.get("statement"), limit=16000)
                    if not text:
                        continue
                    prev = solution_map.get(task_num, "")
                    if len(text) > len(prev):
                        solution_map[task_num] = text

            for entry_index, task_entry in enumerate(task_entries, start=1):
                statement = _clean_text(task_entry.get("statement"), limit=15000)
                if not _looks_like_task_text(statement):
                    continue

                task_number = int(task_entry.get("task_number") or entry_index)
                official_solution = _clean_text(
                    solution_map.get(task_number)
                    or task_entry.get("official_solution")
                    or "",
                    limit=15000,
                )
                if len(official_solution) < 20:
                    continue

                page_start = int(task_entry.get("page_start") or 0) or None
                page_end = int(task_entry.get("page_end") or 0) or page_start
                source_fragments = _normalize_source_fragments(task_entry, page_start, page_end)
                if not source_fragments:
                    continue

                base_id_raw = (
                    f"{subject_name}|{task_file.url}|{page_start}|{page_end}|"
                    f"{task_number}|{hashlib.sha1(statement.encode('utf-8')).hexdigest()[:12]}"
                )
                base_id = hashlib.sha1(base_id_raw.encode("utf-8")).hexdigest()
                source_solution_url = solution_file.url if solution_file else ""

                base_candidate = {
                    "base_id": base_id,
                    "subject": subject_name,
                    "task_file": task_file,
                    "task_number": task_number,
                    "statement": statement,
                    "official_solution": official_solution,
                    "source_pdf_url": task_file.url,
                    "source_solution_pdf_url": source_solution_url,
                    "source_page_start": page_start,
                    "source_page_end": page_end,
                    "source_fragments": source_fragments,
                }

                for target_grade in TARGET_GRADES:
                    score = _candidate_score(target_grade, task_file, len(task_entries))
                    candidate = dict(base_candidate)
                    candidate["target_grade"] = target_grade
                    candidate["score"] = score
                    candidate_pool[(subject_name, target_grade)].append(candidate)

    selected_by_bucket: dict[tuple[str, int], list[dict[str, Any]]] = {}
    overflow_by_bucket: dict[tuple[str, int], list[dict[str, Any]]] = {}

    for subject_cfg in SUBJECT_CONFIGS:
        subject = subject_cfg["name"]
        for grade in TARGET_GRADES:
            key = (subject, grade)
            bucket = sorted(
                candidate_pool.get(key, []),
                key=lambda item: (
                    -item["score"],
                    -len(item["official_solution"]),
                    -len(item["statement"]),
                ),
            )
            unique: list[dict[str, Any]] = []
            seen = set()
            for item in bucket:
                dedup_key = item["base_id"]
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                unique.append(item)

            if len(unique) < TARGET_PER_SUBJECT_GRADE:
                raise RuntimeError(
                    f"Not enough official tasks for {subject} grade {grade}: "
                    f"{len(unique)} < {TARGET_PER_SUBJECT_GRADE}"
                )

            selected_by_bucket[key] = unique[:TARGET_PER_SUBJECT_GRADE]
            overflow_by_bucket[key] = unique[TARGET_PER_SUBJECT_GRADE:]

    tasks: list[dict[str, Any]] = []
    global_seen_titles = set()

    def append_task(candidate: dict[str, Any], index_in_bucket: int, bucket_size: int) -> None:
        subject = candidate["subject"]
        grade = int(candidate["target_grade"])
        task_file: PdfFile = candidate["task_file"]
        season_year = _season_start_year(task_file.season, task_file.year_id)
        difficulty, points = _difficulty_and_points(index_in_bucket)

        answer = _extract_answer(candidate["official_solution"])
        ai_explanation = _build_ai_explanation(
            candidate["statement"],
            candidate["official_solution"],
            answer,
            subject,
            grade,
        )

        signature = candidate["base_id"][:10]
        title = (
            f"ВСОШ {season_year} {grade} класс {subject} "
            f"задача {candidate['task_number']} ({task_file.stage}) #{index_in_bucket + 1}-{signature}"
        )
        if title in global_seen_titles:
            title = f"{title}-dup"
        global_seen_titles.add(title)

        task_payload = {
            "title": title,
            "problem_statement": candidate["statement"],
            "answer": answer,
            "subject": subject,
            "grade": grade,
            "difficulty": difficulty,
            "points": points,
            "input_format": None,
            "output_format": None,
            "examples": None,
            "solution_explanation": ai_explanation,
            "topic": "ВСОШ",
            "tags": "vsosh,official-task",
            "time_limit": 900,
            "attachments": [
                {
                    "type": "pdf",
                    "title": "Оригинал условия (PDF)",
                    "pdf_url": candidate["source_pdf_url"],
                }
            ],
            "source_pdf_url": candidate["source_pdf_url"],
            "source_solution_pdf_url": candidate["source_solution_pdf_url"],
            "source_page_start": candidate["source_page_start"],
            "source_page_end": candidate["source_page_end"],
            "source_fragments": candidate["source_fragments"],
            "full_problem_statement": candidate["statement"],
            "official_solution_text": candidate["official_solution"],
            "free_ai_explanation": ai_explanation,
            "free_ai_status": "ready",
            "ai_answer_short": None,
            "ai_solution_full": None,
            "ai_solution_status": "empty",
            "ai_solution_model": None,
            "ai_solution_error": None,
            "ai_solution_hash": None,
            "ai_solution_generated_at": None,
        }
        tasks.append(task_payload)

    for subject_cfg in SUBJECT_CONFIGS:
        subject = subject_cfg["name"]
        for grade in TARGET_GRADES:
            key = (subject, grade)
            for idx, candidate in enumerate(selected_by_bucket[key]):
                append_task(candidate, idx, TARGET_PER_SUBJECT_GRADE)

    baseline_count = len(tasks)
    if baseline_count != len(SUBJECT_CONFIGS) * len(TARGET_GRADES) * TARGET_PER_SUBJECT_GRADE:
        raise RuntimeError(f"Unexpected baseline count: {baseline_count}")

    extras_needed = max(0, TARGET_TOTAL_TASKS - baseline_count)
    if extras_needed > 0:
        bucket_keys = sorted(
            overflow_by_bucket.keys(),
            key=lambda k: len(overflow_by_bucket[k]),
            reverse=True,
        )
        extra_index_by_bucket = defaultdict(int)
        added = 0
        while added < extras_needed:
            progressed = False
            for key in bucket_keys:
                idx = extra_index_by_bucket[key]
                overflow = overflow_by_bucket[key]
                if idx >= len(overflow):
                    continue
                candidate = overflow[idx]
                extra_index_by_bucket[key] += 1
                append_task(candidate, TARGET_PER_SUBJECT_GRADE + idx, TARGET_PER_SUBJECT_GRADE + 1)
                added += 1
                progressed = True
                if added >= extras_needed:
                    break
            if not progressed:
                raise RuntimeError(
                    f"Unable to reach {TARGET_TOTAL_TASKS} tasks. Built {len(tasks)} tasks."
                )

    if len(tasks) > TARGET_TOTAL_TASKS:
        tasks = tasks[:TARGET_TOTAL_TASKS]

    return {"tasks": tasks}


def _print_coverage(tasks_payload: dict[str, Any]) -> None:
    tasks = tasks_payload.get("tasks", [])
    by_bucket = defaultdict(int)
    by_subject = defaultdict(int)
    for task in tasks:
        subject = str(task.get("subject") or "")
        grade = int(task.get("grade") or 0)
        by_bucket[(subject, grade)] += 1
        by_subject[subject] += 1

    print(f"Total tasks: {len(tasks)}")
    for subject_cfg in SUBJECT_CONFIGS:
        subject = subject_cfg["name"]
        counts = [by_bucket[(subject, grade)] for grade in TARGET_GRADES]
        counts_text = ", ".join(f"{grade}:{count}" for grade, count in zip(TARGET_GRADES, counts))
        print(f"{subject}: {counts_text} | subject_total={by_subject[subject]}")


def main() -> None:
    dataset = build_dataset()
    TASKS_JSON_PATH.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_coverage(dataset)
    print(f"Written: {TASKS_JSON_PATH}")


if __name__ == "__main__":
    main()
