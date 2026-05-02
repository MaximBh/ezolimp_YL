import json
import re
from pathlib import Path
from urllib.request import Request, urlopen

from app.config import (
    _safe_int, _normalize_subject, _normalize_difficulty, _time_limit_by_difficulty,
    _is_manual_answer, _extract_source_url, _synthetic_subjects_enabled,
    _import_ai_solutions_enabled, _sync_tasks_on_startup_enabled,
    PROJECT_ROOT, POINTS_MARKER_RE,
)
from app.utils.text import (
    normalize_text_value as _normalize_text_value,
    strip_source_lines as _strip_source_lines,
    clean_solution_explanation_text as _clean_solution_explanation_text,
    is_unavailable_solution_text as _is_unavailable_solution_text,
    is_generic_solution_explanation as _is_generic_solution_explanation,
    simplify_text_for_search as _simplify_text_for_search,
)
from app.utils.attachments import (
    normalize_attachments as _normalize_attachments,
    attachments_to_storage as _attachments_to_storage,
    ensure_source_pdf_attachment as _ensure_source_pdf_attachment,
    normalize_source_fragments as _normalize_source_fragments,
    source_fragments_to_storage as _source_fragments_to_storage,
    source_fragments_from_storage as _source_fragments_from_storage,
)
from app.utils.pdf import (
    get_source_pdf_url as _get_source_pdf_url,
    ensure_local_pdf_path as _ensure_local_pdf_path,
    find_fragment_for_chunk_in_pdf as _find_fragment_for_chunk_in_pdf,
    split_statement_by_points_markers as _split_statement_by_points_markers,
)
from app.task_helpers import (
    parse_title_parts as _parse_title_parts,
    build_task_title as _build_task_title,
    task_identity_key as _task_identity_key,
    infer_topic as _infer_topic,
    infer_answer_from_statement as _infer_answer_from_statement,
    extract_answer_from_official_solution as _extract_answer_from_official_solution,
    extract_variant_number as _extract_variant_number,
    augment_tasks_with_new_subjects as _augment_tasks_with_new_subjects,
    build_task_title as _build_task_title,
)


def _build_solution_pdf_candidates(source_pdf_url: str) -> list:
    raw_url = _normalize_text_value(source_pdf_url or "")
    if not raw_url:
        return []
    candidates = [raw_url]
    for old, new in [("tasks-", "sol-"), ("tasks_", "sol_"), ("/tasks/", "/solutions/"), ("task-", "solution-"), ("task_", "solution_")]:
        if old in raw_url:
            candidates.append(raw_url.replace(old, new))
    seen = set()
    return [c for c in candidates if c and not (seen.add(c) or c in seen - {c})]


def _url_exists(url: str) -> bool:
    if not url:
        return False
    if not (url.startswith("http://") or url.startswith("https://")):
        path = Path(url)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path.exists()
    for method in ("HEAD", "GET"):
        try:
            with urlopen(Request(url, method=method), timeout=12) as resp:
                if 200 <= getattr(resp, "status", 200) < 400:
                    return True
        except Exception:
            continue
    return False


def _resolve_solution_pdf_url(task) -> str:
    explicit = _normalize_text_value(getattr(task, "source_solution_pdf_url", "") or "")
    if explicit:
        return explicit
    source_pdf = _get_source_pdf_url(task)
    for candidate in _build_solution_pdf_candidates(source_pdf):
        if candidate != source_pdf and _url_exists(candidate):
            return candidate
    return ""


def _extract_points_from_statement(statement: str, default_points: int = 10) -> int:
    text = _normalize_text_value(statement or "")
    if not text:
        return max(1, _safe_int(default_points, 10) or 10)
    match = POINTS_MARKER_RE.search(text[:240])
    if not match:
        return max(1, _safe_int(default_points, 10) or 10)
    return max(1, _safe_int(match.group(1), default_points) or 1)


def _fragments_are_full_page_only(fragments) -> bool:
    for fragment in _normalize_source_fragments(fragments):
        if not isinstance(fragment, dict):
            continue
        if float(fragment.get("width") or 0.0) < 0.98 or float(fragment.get("height") or 0.0) < 0.98:
            return False
    return True


def _is_compound_task_candidate(task) -> bool:
    statement = _normalize_text_value(getattr(task, "full_problem_statement", "") or task.problem_statement or "")
    if len(statement) < 1200 or len(POINTS_MARKER_RE.findall(statement)) < 2:
        return False
    if not _fragments_are_full_page_only(_source_fragments_from_storage(task.source_fragments)):
        return False
    return bool(_get_source_pdf_url(task))


def _entry_matches_task_statement(entry_statement: str, task_statement_norm: str) -> bool:
    entry_norm = _simplify_text_for_search(entry_statement or "")
    if not entry_norm or len(entry_norm) < 40 or not task_statement_norm:
        return False
    anchor = entry_norm[:min(len(entry_norm), 220)]
    return (anchor and anchor in task_statement_norm) or entry_norm in task_statement_norm


def _split_task_title(task, entry: dict, part_index: int) -> str:
    if part_index == 1:
        return _normalize_text_value(task.title or "") or f"Task {task.id}"
    entry_task_number = _safe_int(entry.get("task_number"), None)
    entry_variant = _safe_int(entry.get("variant"), None)
    if entry_task_number is not None:
        topic = f"задача {entry_task_number}"
        if entry_variant is not None:
            topic = f"{topic} вариант {entry_variant}"
        return _build_task_title(task.title, _normalize_subject(task.subject), task.grade, topic=topic, force=True)
    return f"{_normalize_text_value(task.title or '')} [часть {part_index}]".strip()


def enrich_task_from_vsosh_pdfs(task, db, force: bool = False):
    from app.pdf_parser import extract_best_task_entry
    source_url = _get_source_pdf_url(task)
    if not source_url:
        return False, "no_source_pdf"

    has_full_statement = bool(_normalize_text_value(getattr(task, "full_problem_statement", "") or ""))
    has_official_solution = bool(_normalize_text_value(getattr(task, "official_solution_text", "") or ""))
    free_ai_cached = _normalize_text_value(getattr(task, "free_ai_explanation", "") or "")
    has_free_text = bool(free_ai_cached) and not _is_unavailable_solution_text(free_ai_cached)
    source_fragments_cached = _normalize_source_fragments(_source_fragments_from_storage(task.source_fragments))
    has_precise_fragments = any(
        float(item.get("width") or 0) < 0.98 or float(item.get("height") or 0) < 0.98
        for item in source_fragments_cached if isinstance(item, dict)
    )
    expected_variant = _extract_variant_number(task.title or "") or _extract_variant_number(getattr(task, "topic", "") or "")
    full_statement_variant = _extract_variant_number(getattr(task, "full_problem_statement", "") or "")
    has_variant_mismatch = (expected_variant is not None and full_statement_variant is not None and expected_variant != full_statement_variant)

    if not force and has_full_statement and has_official_solution and has_free_text and has_precise_fragments and not has_variant_mismatch:
        return False, "cached"

    changed = False
    _, _, task_number_raw = _parse_title_parts(task.title or "")
    task_number = _safe_int(task_number_raw, None)
    task_hint = _strip_source_lines(task.problem_statement or "")

    try:
        task_pdf_path = _ensure_local_pdf_path(source_url)
        parsed_task = extract_best_task_entry(task_pdf_path, task_number=task_number, variant_number=expected_variant, statement_hint=task_hint)
        if parsed_task.get("found"):
            full_statement = _normalize_text_value(parsed_task.get("full_problem_statement") or "")
            if full_statement and getattr(task, "full_problem_statement", None) != full_statement:
                task.full_problem_statement = full_statement
                changed = True
            for field in ("source_page_start", "source_page_end"):
                val = _safe_int(parsed_task.get(field), None)
                if val is not None and getattr(task, field) != val:
                    setattr(task, field, val)
                    changed = True
            source_fragments = _normalize_source_fragments(parsed_task.get("source_fragments"))
            if source_fragments and _source_fragments_from_storage(task.source_fragments) != source_fragments:
                task.source_fragments = _source_fragments_to_storage(source_fragments)
                changed = True
    except Exception:
        if not _normalize_text_value(getattr(task, "full_problem_statement", "") or ""):
            fallback = _strip_source_lines(task.problem_statement or "")
            if fallback:
                task.full_problem_statement = fallback
                changed = True

    solution_pdf_url = _resolve_solution_pdf_url(task)
    if solution_pdf_url and getattr(task, "source_solution_pdf_url", None) != solution_pdf_url:
        task.source_solution_pdf_url = solution_pdf_url
        changed = True

    if solution_pdf_url:
        try:
            solution_pdf_path = _ensure_local_pdf_path(solution_pdf_url)
            parsed_solution = extract_best_task_entry(
                solution_pdf_path, task_number=task_number, variant_number=expected_variant,
                statement_hint=_normalize_text_value(getattr(task, "full_problem_statement", "") or task_hint),
            )
            if parsed_solution.get("found"):
                official_solution = _normalize_text_value(parsed_solution.get("official_solution_text") or parsed_solution.get("full_problem_statement") or "")
                if official_solution and getattr(task, "official_solution_text", None) != official_solution:
                    task.official_solution_text = official_solution
                    changed = True
        except Exception:
            if not _normalize_text_value(getattr(task, "official_solution_text", "") or ""):
                task.official_solution_text = "Официальное решение из PDF не извлечено."
                changed = True

    if not _normalize_text_value(getattr(task, "official_solution_text", "") or ""):
        fallback_official = _clean_solution_explanation_text(task.solution_explanation or "")
        if fallback_official and getattr(task, "official_solution_text", None) != fallback_official:
            task.official_solution_text = fallback_official
            changed = True

    if force or not _normalize_text_value(getattr(task, "free_ai_explanation", "") or "") or _is_unavailable_solution_text(getattr(task, "free_ai_explanation", "") or ""):
        free_text = _normalize_text_value(task.ai_solution_full or "")
        if _is_generic_solution_explanation(free_text) or _is_unavailable_solution_text(free_text):
            free_text = ""
        if free_text and getattr(task, "free_ai_explanation", None) != free_text:
            task.free_ai_explanation = free_text
            changed = True
        elif not free_text and _normalize_text_value(getattr(task, "free_ai_explanation", "") or ""):
            task.free_ai_explanation = None
            changed = True

    free_status_value = _normalize_text_value(getattr(task, "free_ai_explanation", "") or "")
    free_status = "ready" if free_status_value and not _is_unavailable_solution_text(free_status_value) else "empty"
    if getattr(task, "free_ai_status", None) != free_status:
        task.free_ai_status = free_status
        changed = True

    official_answer = _extract_answer_from_official_solution(getattr(task, "official_solution_text", "") or "")
    if _is_manual_answer(task.answer or "") and official_answer:
        if _normalize_text_value(task.answer or "") != official_answer:
            task.answer = official_answer
            changed = True

    if changed:
        db.commit()
        return True, "updated"
    return False, "no_changes"


def has_seed_tasks() -> bool:
    from app.database import SessionLocal, Task
    db = SessionLocal()
    try:
        return db.query(Task.id).first() is not None
    except Exception:
        return False
    finally:
        db.close()


def _find_tasks_json() -> Path:
    current_file = Path(__file__).resolve()
    candidates = [
        current_file.parents[2] / "tasks.json",
        current_file.parents[3] / "tasks.json",
        Path.cwd().parent / "tasks.json",
        Path.cwd() / "tasks.json",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def ensure_tasks_schema_columns():
    from app.database import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        columns = db.execute(text("PRAGMA table_info(tasks)")).fetchall()
        column_names = {col[1] for col in columns}
        new_columns = {
            "grade": "INTEGER", "attachments": "TEXT", "ai_answer_short": "TEXT",
            "ai_solution_full": "TEXT", "ai_solution_status": "VARCHAR(32)",
            "ai_solution_model": "VARCHAR(64)", "ai_solution_error": "TEXT",
            "ai_solution_hash": "VARCHAR(64)", "ai_solution_generated_at": "DATETIME",
            "source_pdf_url": "TEXT", "source_page_start": "INTEGER",
            "source_page_end": "INTEGER", "source_fragments": "TEXT",
            "source_solution_pdf_url": "TEXT", "full_problem_statement": "TEXT",
            "official_solution_text": "TEXT", "free_ai_explanation": "TEXT",
            "free_ai_status": "VARCHAR(32)",
        }
        for col, col_type in new_columns.items():
            if col not in column_names:
                db.execute(text(f"ALTER TABLE tasks ADD COLUMN {col} {col_type}"))
                print(f"Added tasks.{col} column")
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"Failed to ensure tasks schema columns: {exc}")
    finally:
        db.close()


def import_tasks_from_json():
    from app.database import SessionLocal, Task
    db = SessionLocal()
    try:
        tasks_file = _find_tasks_json()
        if not tasks_file.exists():
            print(f"tasks.json not found: {tasks_file}")
            return 0
        with tasks_file.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        raw_tasks = payload.get("tasks", []) if isinstance(payload, dict) else []
        if not isinstance(raw_tasks, list) or not raw_tasks:
            return 0
        if _synthetic_subjects_enabled():
            raw_tasks = _augment_tasks_with_new_subjects(raw_tasks)
        import_ai_solutions = _import_ai_solutions_enabled()

        existing_tasks = db.query(Task).all()
        index = {}
        duplicates = []
        for task in existing_tasks:
            if task.created_by is not None:
                continue
            identity = _task_identity_key(task.title, task.subject, task.grade, task.problem_statement)
            if identity in index:
                duplicates.append(task)
            else:
                index[identity] = task

        inserted = updated = deleted = 0
        payload_identities = set()

        for task_data in raw_tasks:
            if not isinstance(task_data, dict):
                continue
            title_raw = _normalize_text_value(task_data.get("title"))
            statement_raw = _normalize_text_value(task_data.get("problem_statement"))
            answer = _normalize_text_value(task_data.get("answer"))
            if not title_raw or not statement_raw:
                continue
            grade = _safe_int(task_data.get("grade"), None)
            if grade is not None and (grade < 1 or grade > 11):
                grade = None
            subject = _normalize_subject(task_data.get("subject"))
            difficulty = _normalize_difficulty(task_data.get("difficulty"))
            statement = _strip_source_lines(statement_raw)
            source_pdf_url = _normalize_text_value(task_data.get("source_pdf_url") or task_data.get("source_url") or task_data.get("source") or _extract_source_url(statement_raw, task_data.get("solution_explanation"), task_data.get("official_solution_text")))
            source_fragments = _normalize_source_fragments(task_data.get("source_fragments"))
            full_problem_statement = _normalize_text_value(task_data.get("full_problem_statement"))
            official_solution_text = _normalize_text_value(task_data.get("official_solution_text"))
            free_ai_explanation = ""
            free_ai_status = "empty"
            if import_ai_solutions:
                free_ai_explanation = _normalize_text_value(task_data.get("free_ai_explanation"))
                if _is_generic_solution_explanation(free_ai_explanation):
                    free_ai_explanation = ""
                free_ai_status = _normalize_text_value(task_data.get("free_ai_status"))
                if free_ai_status == "ready" and not free_ai_explanation:
                    free_ai_status = "empty"
                if not free_ai_status:
                    free_ai_status = "ready" if free_ai_explanation else "empty"
            _, _, task_number = _parse_title_parts(title_raw)
            topic_value = _normalize_text_value(task_data.get("topic"))
            if not topic_value or topic_value.upper() == "VSOSH":
                topic_value = _infer_topic(subject, statement, task_number)
            explanation = _clean_solution_explanation_text(task_data.get("solution_explanation"))
            if _is_generic_solution_explanation(explanation):
                explanation = ""
            inferred_answer = _infer_answer_from_statement(statement)
            if _is_manual_answer(answer) and inferred_answer:
                answer = inferred_answer
            if not answer:
                answer = inferred_answer or "see solution"
            attachments = _normalize_attachments(task_data.get("attachments"), subject=subject, grade=grade, topic=topic_value, statement=statement)
            attachments = _ensure_source_pdf_attachment(attachments, source_pdf_url)
            payload_data = {
                "title": _build_task_title(title_raw, subject, grade, topic_value, force=True),
                "problem_statement": statement, "answer": answer, "subject": subject, "grade": grade,
                "difficulty": difficulty, "points": _safe_int(task_data.get("points"), 10),
                "input_format": task_data.get("input_format"), "output_format": task_data.get("output_format"),
                "examples": task_data.get("examples"), "solution_explanation": explanation or None,
                "topic": topic_value, "tags": task_data.get("tags"),
                "attachments": _attachments_to_storage(attachments),
                "source_pdf_url": source_pdf_url or None,
                "source_solution_pdf_url": _normalize_text_value(task_data.get("source_solution_pdf_url")) or None,
                "source_page_start": _safe_int(task_data.get("source_page_start"), None),
                "source_page_end": _safe_int(task_data.get("source_page_end"), None),
                "source_fragments": _source_fragments_to_storage(source_fragments),
                "full_problem_statement": full_problem_statement or statement or None,
                "official_solution_text": official_solution_text or None,
                "free_ai_explanation": free_ai_explanation or None,
                "free_ai_status": free_ai_status,
                "time_limit": _time_limit_by_difficulty(difficulty),
            }
            identity = _task_identity_key(payload_data["title"], subject, grade, payload_data["problem_statement"])
            payload_identities.add(identity)
            existing = index.get(identity)
            if existing:
                changed = False
                for field, value in payload_data.items():
                    if getattr(existing, field) != value:
                        setattr(existing, field, value)
                        changed = True
                if changed:
                    updated += 1
            else:
                task = Task(**payload_data)
                db.add(task)
                index[identity] = task
                inserted += 1

        for dup in duplicates:
            db.delete(dup)
            deleted += 1

        for task in db.query(Task).all():
            if task.created_by is not None:
                continue
            identity = _task_identity_key(task.title, task.subject, task.grade, task.problem_statement)
            if identity not in payload_identities:
                db.delete(task)
                deleted += 1

        if inserted or updated or deleted:
            db.commit()
            print(f"Synced tasks from {tasks_file}: inserted={inserted}, updated={updated}, deleted={deleted}")
        return inserted + updated
    except Exception as exc:
        db.rollback()
        print(f"Failed to import tasks from tasks.json: {exc}")
        return 0
    finally:
        db.close()


def split_compound_tasks_after_import():
    from app.database import SessionLocal, Task
    db = SessionLocal()
    try:
        from app.pdf_parser import extract_task_entries
        all_tasks = db.query(Task).all()
        identity_map = {}
        for item in all_tasks:
            if item.created_by is not None:
                continue
            identity_map[_task_identity_key(item.title, item.subject, item.grade, item.problem_statement)] = item

        split_groups = updated_count = created_count = 0

        for task in all_tasks:
            if task.created_by is not None or not _is_compound_task_candidate(task):
                continue
            source_url = _get_source_pdf_url(task)
            if not source_url:
                continue
            try:
                pdf_path = _ensure_local_pdf_path(source_url)
                entries = extract_task_entries(pdf_path)
            except Exception:
                continue
            if not entries:
                continue

            page_start = _safe_int(task.source_page_start, None)
            page_end = _safe_int(task.source_page_end, None)
            if page_start is None and page_end is not None:
                page_start = page_end
            if page_end is None and page_start is not None:
                page_end = page_start

            task_statement_raw = _normalize_text_value(getattr(task, "full_problem_statement", "") or task.problem_statement or "")
            task_statement_norm = _simplify_text_for_search(task_statement_raw)

            matched_entries = []
            for entry in entries:
                statement_value = _normalize_text_value(entry.get("full_problem_statement") or "")
                if not statement_value:
                    continue
                ep_start = _safe_int(entry.get("source_page_start"), None)
                ep_end = _safe_int(entry.get("source_page_end"), ep_start)
                if page_start is not None and page_end is not None and ep_start is not None and ep_end is not None:
                    if ep_end < page_start or ep_start > page_end:
                        continue
                if _entry_matches_task_statement(statement_value, task_statement_norm):
                    matched_entries.append(entry)

            seen_norm = set()
            deduped_entries = []
            for entry in sorted(matched_entries, key=lambda e: (_safe_int(e.get("source_page_start"), 10**9), _safe_int(e.get("index"), 10**9))):
                statement_value = _normalize_text_value(entry.get("full_problem_statement") or "")
                norm_key = _simplify_text_for_search(statement_value)
                if not norm_key or norm_key in seen_norm:
                    continue
                seen_norm.add(norm_key)
                deduped_entries.append(entry)

            usable = [
                e for e in deduped_entries
                if len(_normalize_text_value(e.get("full_problem_statement") or "")) >= 120
                and _simplify_text_for_search(_normalize_text_value(e.get("full_problem_statement") or "")) != task_statement_norm
                and (POINTS_MARKER_RE.search(_normalize_text_value(e.get("full_problem_statement") or "")[:240]) or "?" in _normalize_text_value(e.get("full_problem_statement") or ""))
            ]

            if len(usable) >= 2:
                deduped_entries = usable
            else:
                chunks = _split_statement_by_points_markers(task_statement_raw)
                if len(chunks) < 2:
                    continue
                base_fragments = _normalize_source_fragments(_source_fragments_from_storage(task.source_fragments))
                synthesized = []
                for idx, chunk in enumerate(chunks, start=1):
                    chunk_statement = _strip_source_lines(_normalize_text_value(chunk))
                    if len(chunk_statement) < 80:
                        continue
                    chunk_fragments = _find_fragment_for_chunk_in_pdf(pdf_path, chunk_statement, page_start=page_start, page_end=page_end) or list(base_fragments)
                    chunk_task_number = None
                    num_match = re.match(r"^\s*(?:№|N)\s*(\d{1,3})\b", chunk_statement, re.IGNORECASE)
                    if num_match:
                        chunk_task_number = _safe_int(num_match.group(1), None)
                    cp_start = cp_end = page_start
                    if chunk_fragments:
                        first_page = _safe_int(chunk_fragments[0].get("page"), None)
                        if first_page is not None:
                            cp_start = cp_end = first_page
                    synthesized.append({"task_number": chunk_task_number, "variant": None, "index": idx, "full_problem_statement": chunk_statement, "official_solution_text": "", "source_page_start": cp_start, "source_page_end": cp_end, "source_fragments": chunk_fragments})
                deduped_entries = synthesized

            if len(deduped_entries) < 2:
                continue

            split_groups += 1
            base_subject = _normalize_subject(task.subject)
            base_difficulty = _normalize_difficulty(task.difficulty)
            base_answer_fallback = _normalize_text_value(task.answer or "")
            base_source_solution_pdf_url = _normalize_text_value(getattr(task, "source_solution_pdf_url", "") or "")

            for index, entry in enumerate(deduped_entries, start=1):
                statement_value = _strip_source_lines(_normalize_text_value(entry.get("full_problem_statement") or ""))
                if not statement_value:
                    continue
                entry_fragments = _normalize_source_fragments(entry.get("source_fragments"))
                inferred_answer = _infer_answer_from_statement(statement_value)
                payload = {
                    "title": _split_task_title(task, entry, index),
                    "problem_statement": statement_value, "full_problem_statement": statement_value,
                    "answer": inferred_answer or base_answer_fallback or "see solution",
                    "subject": base_subject, "grade": task.grade, "difficulty": base_difficulty,
                    "points": _extract_points_from_statement(statement_value, task.points),
                    "input_format": task.input_format, "output_format": task.output_format,
                    "examples": task.examples, "solution_explanation": task.solution_explanation,
                    "topic": task.topic, "tags": task.tags, "attachments": task.attachments,
                    "source_pdf_url": source_url,
                    "source_solution_pdf_url": base_source_solution_pdf_url or None,
                    "source_page_start": _safe_int(entry.get("source_page_start"), None),
                    "source_page_end": _safe_int(entry.get("source_page_end"), _safe_int(entry.get("source_page_start"), None)),
                    "source_fragments": _source_fragments_to_storage(entry_fragments),
                    "official_solution_text": _normalize_text_value(entry.get("official_solution_text") or "") or None,
                    "free_ai_explanation": None, "free_ai_status": "empty",
                    "ai_answer_short": None, "ai_solution_full": None, "ai_solution_status": "empty",
                    "ai_solution_model": None, "ai_solution_error": None, "ai_solution_hash": None,
                    "ai_solution_generated_at": None,
                    "time_limit": _time_limit_by_difficulty(base_difficulty),
                    "created_by": task.created_by,
                }
                if index == 1:
                    changed = False
                    for field, value in payload.items():
                        if getattr(task, field) != value:
                            setattr(task, field, value)
                            changed = True
                    if changed:
                        updated_count += 1
                    identity_map[_task_identity_key(task.title, task.subject, task.grade, task.problem_statement)] = task
                    continue
                identity = _task_identity_key(payload["title"], payload["subject"], payload["grade"], payload["problem_statement"])
                existing = identity_map.get(identity)
                if existing:
                    changed = False
                    for field, value in payload.items():
                        if field == "created_by":
                            continue
                        if getattr(existing, field) != value:
                            setattr(existing, field, value)
                            changed = True
                    if changed:
                        updated_count += 1
                else:
                    new_task = Task(**payload)
                    db.add(new_task)
                    created_count += 1
                    identity_map[identity] = new_task

        if split_groups > 0:
            db.commit()
            print(f"Split compound tasks after import: groups={split_groups}, updated={updated_count}, created={created_count}")
    except Exception as exc:
        db.rollback()
        print(f"Failed to split compound tasks after import: {exc}")
    finally:
        db.close()
