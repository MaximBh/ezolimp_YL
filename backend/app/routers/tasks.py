import re
import traceback
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db, User, Task, TaskView, Solution, UserStats
from app.schemas import TaskCreate
from app.auth_middleware import get_current_user, get_admin_user
from app.config import (
    _safe_int, _normalize_subject, _normalize_difficulty, _time_limit_by_difficulty,
    _normalize_olympiad_name, _is_manual_answer, _extract_source_url,
    SUPPORTED_SUBJECTS, ANSWER_HINT_MANUAL,
    PDF_FRAGMENT_CACHE_DIR, TASK_CROPS_DIR,
)
from app.utils.text import (
    normalize_text_value as _normalize_text_value,
    strip_source_lines as _strip_source_lines,
    clean_solution_explanation_text as _clean_solution_explanation_text,
    is_unavailable_solution_text as _is_unavailable_solution_text,
    is_generic_solution_explanation as _is_generic_solution_explanation,
    clean_generated_solution_text as _clean_generated_solution_text,
)
from app.utils.attachments import (
    normalize_attachments as _normalize_attachments,
    attachments_to_storage as _attachments_to_storage,
    attachments_from_storage as _attachments_from_storage,
    ensure_source_pdf_attachment as _ensure_source_pdf_attachment,
    normalize_source_fragments as _normalize_source_fragments,
    source_fragments_to_storage as _source_fragments_to_storage,
    source_fragments_from_storage as _source_fragments_from_storage,
)
from app.utils.answer import build_answer_check_status as _build_answer_check_status, clean_reference_answer_text as _clean_reference_answer_text
from app.utils.pdf import render_task_fragments as _render_task_fragments
from app.task_helpers import (
    task_olympiad as _task_olympiad,
    task_list_payload as _task_list_payload,
    build_task_title as _build_task_title,
    answer_input_hint_for_task as _answer_input_hint_for_task,
    infer_topic as _infer_topic,
    infer_answer_from_statement as _infer_answer_from_statement,
    generate_fallback_solution as _generate_fallback_solution,
    extract_answer_from_official_solution as _extract_answer_from_official_solution,
    resolve_vsosh_reference_answer as _resolve_vsosh_reference_answer,
    resolve_task_ai_reference_answer as _resolve_task_ai_reference_answer,
    resolve_task_reference_answers as _resolve_task_reference_answers,
    is_task_ai_answer_pending as _is_task_ai_answer_pending,
    ensure_task_ai_generation as _ensure_task_ai_generation,
    record_task_view as _record_task_view,
)
from app.task_import import enrich_task_from_vsosh_pdfs as _enrich_task_from_vsosh_pdfs
from app.ai_worker import (
    get_or_generate_ai_solution as _get_or_generate_ai_solution,
    should_generate_ai_solution as _should_generate_ai_solution,
    is_ai_generation_stale as _is_ai_generation_stale,
    is_ai_generation_job_active as _is_ai_generation_job_active,
    queue_ai_solution_generation as _queue_ai_solution_generation,
    get_ai_generation_jobs_snapshot as _get_ai_generation_jobs_snapshot,
    resolve_ai_generating_stale_sec as _resolve_ai_generating_stale_sec,
    _extract_answer_from_solution_text,
    _jobs_lock as _ai_solution_jobs_lock,
    _jobs as _ai_solution_jobs,
)

router = APIRouter()


@router.get("/tasks")
def get_tasks(db: Session = Depends(get_db)):
    try:
        return {"tasks": [_task_list_payload(t) for t in db.query(Task).all()]}
    except Exception:
        raise HTTPException(status_code=500, detail="Ошибка при получении задач")


@router.get("/tasks/filters")
def get_task_filters(db: Session = Depends(get_db)):
    try:
        tasks = db.query(Task).all()
        subject_order = {s: i for i, s in enumerate(SUPPORTED_SUBJECTS)}
        tree = {}
        for task in tasks:
            subject = _normalize_subject(task.subject)
            olympiad = _task_olympiad(task)
            if not subject or not olympiad or task.grade is None:
                continue
            tree.setdefault(subject, {}).setdefault(olympiad, set()).add(str(task.grade))
        subjects = sorted({_normalize_subject(t.subject) for t in tasks if _normalize_subject(t.subject)}, key=lambda v: (subject_order.get(v, 999), v))
        olympiads = sorted({_task_olympiad(t) for t in tasks if _task_olympiad(t)})
        grades = sorted({t.grade for t in tasks if t.grade is not None and 1 <= int(t.grade) <= 11})
        normalized_tree = {
            s: {o: sorted(gs, key=lambda v: int(v) if str(v).isdigit() else 999) for o, gs in sorted(om.items())}
            for s, om in sorted(tree.items(), key=lambda x: (subject_order.get(x[0], 999), x[0]))
        }
        return {"subjects": subjects, "olympiads": olympiads, "grades": grades, "tree": normalized_tree}
    except Exception:
        raise HTTPException(status_code=500, detail="Ошибка при получении фильтров")


@router.get("/tasks/popular/today")
def get_popular_tasks_today(limit: int = 10, db: Session = Depends(get_db)):
    try:
        safe_limit = max(1, min(int(limit or 10), 50))
        today = date.today()
        rows = db.query(Task, TaskView.view_count).join(TaskView, TaskView.task_id == Task.id).filter(TaskView.viewed_on == today).order_by(TaskView.view_count.desc(), Task.id.asc()).limit(safe_limit).all()
        result = [_task_list_payload(task, view_count=count) for task, count in rows]
        selected_ids = {task.id for task, _ in rows}
        if len(result) < safe_limit:
            fallback = db.query(Task)
            if selected_ids:
                fallback = fallback.filter(~Task.id.in_(selected_ids))
            result.extend(_task_list_payload(t, view_count=0) for t in fallback.order_by(Task.id.asc()).limit(safe_limit - len(result)).all())
        return {"date": today.isoformat(), "tasks": result}
    except Exception:
        raise HTTPException(status_code=500, detail="Ошибка при получении популярных задач")


@router.get("/tasks/filter")
def filter_tasks(subject: str = None, olympiad: str = None, grade: int = None, difficulty: str = None, db: Session = Depends(get_db)):
    try:
        query = db.query(Task)
        if subject:
            query = query.filter(Task.subject == _normalize_subject(subject))
        if grade is not None:
            query = query.filter(Task.grade == grade)
        if difficulty:
            query = query.filter(Task.difficulty == _normalize_difficulty(difficulty))
        tasks = query.all()
        if olympiad:
            ov = _normalize_olympiad_name(olympiad)
            tasks = [t for t in tasks if _task_olympiad(t) == ov]
        return {"tasks": [_task_list_payload(t) for t in tasks]}
    except Exception:
        raise HTTPException(status_code=500, detail="Ошибка при фильтрации задач")


@router.get("/static/task_crops/{img_name}")
def get_task_crop(img_name: str):
    if not re.fullmatch(r"task_[\d_v]+_[0-9a-f]+\.webp", img_name):
        raise HTTPException(status_code=404, detail="Not found")
    path = TASK_CROPS_DIR / img_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path=path, media_type="image/webp")


@router.get("/tasks/fragments/{fragment_name}")
def get_task_fragment(fragment_name: str):
    if not re.fullmatch(r"[0-9a-f]{64}\.webp", fragment_name):
        raise HTTPException(status_code=404, detail="Fragment not found")
    path = PDF_FRAGMENT_CACHE_DIR / fragment_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Fragment not found")
    return FileResponse(path=path, media_type="image/webp")


@router.get("/generation/jobs")
def get_generation_jobs(current_user: User = Depends(get_current_user)):
    return _get_ai_generation_jobs_snapshot()


@router.get("/tasks/{task_id}/visual")
def get_task_visual(task_id: int, enrich: bool = True, db: Session = Depends(get_db)):
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if enrich:
            try:
                _enrich_task_from_vsosh_pdfs(task, db, force=False)
                db.refresh(task)
            except Exception:
                pass
        payload = _render_task_fragments(task)
        payload["task_id"] = task_id
        return payload
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка рендеринга задачи")


@router.put("/tasks/{task_id}")
def update_task(task_id: int, title: str = None, problem_statement: str = None, answer: str = None, db: Session = Depends(get_db)):
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        if title:
            task.title = title
        if problem_statement:
            task.problem_statement = problem_statement
        if answer:
            task.answer = answer
        db.commit()
        return {"message": "Задача обновлена"}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Ошибка при обновлении задачи")


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, current_user: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        db.delete(task)
        db.commit()
        return {"message": "Задача удалена"}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Ошибка при удалении задачи")


@router.post("/tasks")
def create_task(task_data: TaskCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        difficulty = _normalize_difficulty(task_data.difficulty)
        subject = _normalize_subject(task_data.subject)
        statement = _strip_source_lines(_normalize_text_value(task_data.problem_statement))
        topic_value = _normalize_text_value(task_data.topic) or _infer_topic(subject, statement)
        answer = _normalize_text_value(task_data.answer)
        explanation = _clean_solution_explanation_text(task_data.solution_explanation)
        if _is_generic_solution_explanation(explanation):
            explanation = ""
        inferred_answer = _infer_answer_from_statement(statement)
        if _is_manual_answer(answer) and inferred_answer:
            answer = inferred_answer
        if not answer:
            answer = inferred_answer or "см. решение"
        source_pdf_url = _normalize_text_value(task_data.source_pdf_url or _extract_source_url(task_data.problem_statement, task_data.solution_explanation, getattr(task_data, "official_solution_text", None)))
        source_solution_pdf_url = _normalize_text_value(getattr(task_data, "source_solution_pdf_url", None))
        source_fragments = _normalize_source_fragments(task_data.source_fragments)
        full_problem_statement = _normalize_text_value(getattr(task_data, "full_problem_statement", None))
        official_solution_text = _normalize_text_value(getattr(task_data, "official_solution_text", None))
        free_ai_explanation = _normalize_text_value(getattr(task_data, "free_ai_explanation", None))
        free_ai_status = _normalize_text_value(getattr(task_data, "free_ai_status", None))
        if not free_ai_status:
            free_ai_status = "ready" if free_ai_explanation else "empty"
        attachments = _normalize_attachments(task_data.attachments, subject=subject, grade=task_data.grade, topic=topic_value, statement=statement)
        attachments = _ensure_source_pdf_attachment(attachments, source_pdf_url)
        task = Task(
            title=_build_task_title(task_data.title, subject, task_data.grade, topic_value, force=True),
            problem_statement=statement, answer=answer, subject=subject, grade=task_data.grade,
            difficulty=difficulty, points=task_data.points or 10, input_format=task_data.input_format,
            output_format=task_data.output_format, examples=task_data.examples,
            solution_explanation=explanation or None, topic=topic_value, tags=task_data.tags,
            attachments=_attachments_to_storage(attachments), source_pdf_url=source_pdf_url or None,
            source_solution_pdf_url=source_solution_pdf_url or None,
            source_page_start=_safe_int(task_data.source_page_start, None),
            source_page_end=_safe_int(task_data.source_page_end, None),
            source_fragments=_source_fragments_to_storage(source_fragments),
            full_problem_statement=full_problem_statement or statement or None,
            official_solution_text=official_solution_text or None,
            free_ai_explanation=free_ai_explanation or None, free_ai_status=free_ai_status,
            ai_solution_status="empty", time_limit=_time_limit_by_difficulty(difficulty),
            created_by=current_user.id
        )
        db.add(task)
        db.commit()
        return {"message": "Задача создана", "id": task.id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера")


@router.get("/tasks/{task_id}")
def get_task(task_id: int, enrich: bool = True, db: Session = Depends(get_db)):
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        try:
            _record_task_view(task.id, db)
            db.commit()
        except Exception:
            db.rollback()
        enrich_status = "skipped"
        if enrich:
            try:
                _, enrich_status = _enrich_task_from_vsosh_pdfs(task, db, force=False)
                db.refresh(task)
            except Exception as exc:
                enrich_status = f"error: {_normalize_text_value(exc)}"
        full_statement = _normalize_text_value(getattr(task, "full_problem_statement", "") or task.problem_statement or "") or _strip_source_lines(task.problem_statement or "")
        return {
            "id": task.id,
            "title": _build_task_title(task.title, _normalize_subject(task.subject), task.grade, task.topic),
            "problem_statement": _strip_source_lines(task.problem_statement or ""),
            "full_problem_statement": full_statement,
            "input_format": task.input_format, "output_format": task.output_format, "examples": task.examples,
            "solution_explanation": _clean_solution_explanation_text(task.solution_explanation),
            "difficulty": _normalize_difficulty(task.difficulty), "subject": _normalize_subject(task.subject),
            "grade": task.grade, "topic": task.topic, "tags": task.tags,
            "attachments": _attachments_from_storage(task.attachments),
            "source_pdf_url": task.source_pdf_url, "source_page_start": task.source_page_start,
            "source_page_end": task.source_page_end,
            "source_fragments": _source_fragments_from_storage(task.source_fragments),
            "source_solution_pdf_url": _normalize_text_value(getattr(task, "source_solution_pdf_url", "") or ""),
            "official_solution_text": _normalize_text_value(getattr(task, "official_solution_text", "") or ""),
            "free_ai_explanation": _normalize_text_value(getattr(task, "free_ai_explanation", "") or ""),
            "free_ai_status": _normalize_text_value(getattr(task, "free_ai_status", "") or ""),
            "enrich_status": enrich_status,
            "ai_solution_status": task.ai_solution_status, "ai_solution_error": task.ai_solution_error,
            "answer_input_hint": _answer_input_hint_for_task(task),
            "points": task.points, "time_limit": _time_limit_by_difficulty(task.difficulty)
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Ошибка при получении задачи")


@router.get("/tasks/{task_id}/solution")
def get_task_solution(task_id: int, enrich: bool = True, force_regenerate: bool = False, wait_for_ai: bool = False,
                      current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        solution = db.query(Solution).filter(Solution.user_id == current_user.id, Solution.task_id == task_id).first()
        if solution:
            solution.viewed_solution = True
        else:
            solution = Solution(user_id=current_user.id, task_id=task_id, viewed_solution=True, is_correct=False)
            db.add(solution)
        db.commit()
        enrich_status = "skipped"
        if enrich:
            try:
                _, enrich_status = _enrich_task_from_vsosh_pdfs(task, db, force=force_regenerate)
                db.refresh(task)
            except Exception as exc:
                enrich_status = f"error: {_normalize_text_value(exc)}"

        official_solution_text = _normalize_text_value(getattr(task, "official_solution_text", "") or "")
        free_ai_explanation = _normalize_text_value(getattr(task, "free_ai_explanation", "") or "")
        cleaned = _clean_generated_solution_text(free_ai_explanation)
        if cleaned != free_ai_explanation:
            free_ai_explanation = cleaned
            task.free_ai_explanation = free_ai_explanation or None
            db.commit()
        if free_ai_explanation and (_is_unavailable_solution_text(free_ai_explanation) or _is_generic_solution_explanation(free_ai_explanation)):
            free_ai_explanation = ""
            task.free_ai_explanation = None
            task.free_ai_status = "empty"
            db.commit()
        if not free_ai_explanation:
            cached = _normalize_text_value(getattr(task, "ai_solution_full", "") or "")
            cached = _clean_generated_solution_text(cached)
            if cached and (_is_unavailable_solution_text(cached) or _is_generic_solution_explanation(cached)):
                cached = ""
                task.ai_solution_full = None
                if task.ai_solution_status == "ready":
                    task.ai_solution_status = "empty"
                db.commit()
            if cached:
                if task.ai_solution_status == "ready":
                    free_ai_explanation = cached
                    task.free_ai_explanation = cached
                    task.free_ai_status = "ready"
                    db.commit()
                elif task.ai_solution_status in ("generating", "queued"):
                    free_ai_explanation = cached
        if _is_ai_generation_stale(task):
            if _is_ai_generation_job_active(task.id):
                with _ai_solution_jobs_lock:
                    _ai_solution_jobs.discard(task.id)
            stale_sec = _resolve_ai_generating_stale_sec()
            task.ai_solution_status = "timeout"
            task.ai_solution_error = f"Генерация превысила {stale_sec} сек."
            task.ai_solution_generated_at = datetime.utcnow()
            db.commit()

        vsosh_answer_value = _extract_answer_from_official_solution(official_solution_text)
        ai_answer_raw = _clean_reference_answer_text(getattr(task, "ai_answer_short", "") or "")
        answer_value = vsosh_answer_value or _normalize_text_value(task.answer)
        explanation = free_ai_explanation or _clean_solution_explanation_text(task.solution_explanation)
        needs_ai = _should_generate_ai_solution(task, answer_value, free_ai_explanation, force=force_regenerate)
        ai_source = "not_needed"
        if needs_ai:
            if wait_for_ai:
                ai_answer, ai_solution, ai_source = _get_or_generate_ai_solution(task, db, force=force_regenerate)
                if ai_answer and not ai_answer_raw:
                    ai_answer_raw = ai_answer
                if ai_solution:
                    explanation = free_ai_explanation = ai_solution
                    if _normalize_text_value(getattr(task, "free_ai_explanation", "") or "") != free_ai_explanation or _normalize_text_value(getattr(task, "free_ai_status", "") or "") != "ready":
                        task.free_ai_explanation = free_ai_explanation
                        task.free_ai_status = "ready"
                        db.commit()
                if _is_manual_answer(answer_value) and ai_answer:
                    answer_value = ai_answer
            else:
                if task.ai_solution_status not in ("queued", "generating"):
                    task.ai_solution_status = "queued"
                    task.ai_solution_error = None
                    task.ai_solution_generated_at = datetime.utcnow()
                    db.commit()
                queued = _queue_ai_solution_generation(task.id, force=force_regenerate)
                ai_source = "queued" if queued else "queued_existing"

        if not ai_answer_raw:
            ai_answer_raw = _clean_reference_answer_text(
                _extract_answer_from_solution_text(free_ai_explanation)
                or _extract_answer_from_solution_text(_normalize_text_value(getattr(task, "ai_solution_full", "") or ""))
                or _extract_answer_from_solution_text(explanation)
            )
        if ai_answer_raw and _clean_reference_answer_text(getattr(task, "ai_answer_short", "") or "") != ai_answer_raw:
            task.ai_answer_short = ai_answer_raw
            db.commit()
        if _is_generic_solution_explanation(explanation):
            explanation = ""
        if not explanation:
            explanation = _generate_fallback_solution(
                getattr(task, "full_problem_statement", "") or task.problem_statement or "",
                _normalize_subject(task.subject), task.topic or "",
                answer_value or task.answer or "",
                task.ai_solution_error or task.ai_solution_status or ai_source,
            )
        if not answer_value:
            answer_value = vsosh_answer_value or _extract_answer_from_solution_text(free_ai_explanation) or _extract_answer_from_solution_text(explanation) or "см. решение"
        if not vsosh_answer_value:
            vsosh_answer_value = _extract_answer_from_solution_text(official_solution_text)

        if free_ai_explanation:
            free_status = "ready"
        elif task.ai_solution_status in ("queued", "generating") or ai_source in ("queued", "queued_existing"):
            free_status = "generating"
        else:
            free_status = "empty"
        if getattr(task, "free_ai_status", None) != free_status:
            task.free_ai_status = free_status
            db.commit()

        return {
            "answer": answer_value, "explanation": explanation,
            "ai_answer_raw": ai_answer_raw, "vsosh_answer_raw": vsosh_answer_value,
            "official_solution_text": official_solution_text,
            "free_ai_explanation": free_ai_explanation, "free_ai_status": free_status,
            "source_solution_pdf_url": _normalize_text_value(getattr(task, "source_solution_pdf_url", "") or ""),
            "enrich_status": enrich_status,
            "ai_solution_status": task.ai_solution_status, "ai_solution_model": task.ai_solution_model,
            "ai_solution_error": task.ai_solution_error,
            "ai_solution_generated_at": task.ai_solution_generated_at.isoformat() if task.ai_solution_generated_at else None,
            "ai_generation_source": ai_source,
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Ошибка получения решения")


@router.post("/tasks/{task_id}/solve")
def solve_task(task_id: int, user_answer: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        previous_solution = db.query(Solution).filter(Solution.user_id == current_user.id, Solution.task_id == task_id).order_by(Solution.created_at.desc()).first()
        viewed_solution = previous_solution.viewed_solution if previous_solution else False
        previous_correct = bool(previous_solution and previous_solution.is_correct)

        vsosh_check = _build_answer_check_status(user_answer, _resolve_vsosh_reference_answer(task))
        ai_check = _build_answer_check_status(user_answer, _resolve_task_ai_reference_answer(task))

        input_hint = _answer_input_hint_for_task(task)
        if ai_check.get("status") in ("correct", "incorrect") and ai_check.get("hint"):
            input_hint = ai_check["hint"]
        elif vsosh_check.get("status") in ("correct", "incorrect") and vsosh_check.get("hint"):
            input_hint = vsosh_check["hint"]

        ai_pending = _is_task_ai_answer_pending(task)
        vsosh_is_correct = bool(vsosh_check.get("is_correct"))
        if ai_pending and not vsosh_is_correct:
            _ensure_task_ai_generation(task, db)
            return {"is_correct": False, "manual_check": False, "pending_ai_check": True,
                    "message": "Подождите... идет проверка.", "points_earned": 0, "already_solved": previous_correct,
                    "answer_input_hint": input_hint,
                    "vsosh_check_status": vsosh_check.get("status", "unavailable"),
                    "vsosh_is_correct": vsosh_check.get("is_correct"),
                    "vsosh_reference_answer": vsosh_check.get("reference", ""),
                    "ai_check_status": "pending", "ai_is_correct": None, "ai_reference_answer": ""}

        ai_known = ai_check.get("status") in ("correct", "incorrect")
        vsosh_known = vsosh_check.get("status") in ("correct", "incorrect")
        ai_is_correct = bool(ai_check.get("is_correct"))

        final_source = None
        if ai_known and ai_is_correct:
            final_source = "ai"
        elif vsosh_known and vsosh_is_correct:
            final_source = "vsosh"
        elif ai_known:
            final_source = "ai"
        elif vsosh_known:
            final_source = "vsosh"

        if not final_source:
            return {"is_correct": False, "manual_check": True, "pending_ai_check": False,
                    "message": "Формат ответа уточняйте в блоке решения задачи.",
                    "points_earned": 0, "already_solved": previous_correct,
                    "answer_input_hint": input_hint or ANSWER_HINT_MANUAL,
                    "vsosh_check_status": vsosh_check.get("status", "unavailable"),
                    "vsosh_is_correct": vsosh_check.get("is_correct"),
                    "vsosh_reference_answer": vsosh_check.get("reference", ""),
                    "ai_check_status": ai_check.get("status", "unavailable"),
                    "ai_is_correct": ai_check.get("is_correct"),
                    "ai_reference_answer": ai_check.get("reference", "")}

        is_correct = bool(vsosh_is_correct or ai_is_correct)
        if ai_known and ai_check.get("hint"):
            input_hint = ai_check["hint"]
        elif vsosh_known and vsosh_check.get("hint"):
            input_hint = vsosh_check["hint"]

        points_earned = (task.points or 0) if is_correct and not previous_correct and not viewed_solution else 0
        db.add(Solution(user_id=current_user.id, task_id=task_id, answer=user_answer,
                        is_correct=is_correct, points_earned=points_earned, viewed_solution=viewed_solution))

        user_stats = db.query(UserStats).filter(UserStats.user_id == current_user.id).first()
        if not user_stats:
            user_stats = UserStats(user_id=current_user.id, total_solved=0, correct_answers=0, total_points=0, current_streak=0, best_streak=0)
            db.add(user_stats)
        if not previous_correct:
            user_stats.total_solved = (user_stats.total_solved or 0) + 1
            if is_correct and not viewed_solution:
                user_stats.correct_answers = (user_stats.correct_answers or 0) + 1
                user_stats.total_points = (user_stats.total_points or 0) + points_earned
                user_stats.current_streak = (user_stats.current_streak or 0) + 1
                if user_stats.current_streak > (user_stats.best_streak or 0):
                    user_stats.best_streak = user_stats.current_streak
            else:
                user_stats.current_streak = 0
        db.commit()

        if previous_correct:
            message = "Эта задача уже была засчитана ранее."
        elif viewed_solution and is_correct:
            message = "Верно, но баллы не начисляются (решение уже было открыто)."
        elif is_correct:
            message = f"Верно! Начислено {points_earned} баллов."
        else:
            message = "Неверно. Попробуйте ещё раз."
        if ai_pending:
            message = f"{message} Проверка по нейросети продолжается."

        return {"is_correct": is_correct, "manual_check": False, "pending_ai_check": False,
                "message": message, "points_earned": points_earned, "already_solved": previous_correct,
                "answer_input_hint": input_hint, "score_source": final_source,
                "vsosh_check_status": vsosh_check.get("status", "unavailable"),
                "vsosh_is_correct": vsosh_check.get("is_correct"),
                "vsosh_reference_answer": vsosh_check.get("reference", ""),
                "ai_check_status": "pending" if ai_pending else ai_check.get("status", "unavailable"),
                "ai_is_correct": ai_check.get("is_correct"),
                "ai_reference_answer": ai_check.get("reference", "")}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        db.rollback()
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера")
