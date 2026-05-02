from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db, User, Task
from app.auth_middleware import get_admin_user
from app.config import (
    _safe_int, _normalize_subject, _normalize_difficulty, _time_limit_by_difficulty,
    _is_manual_answer, _extract_source_url,
)
from app.utils.text import (
    normalize_text_value as _normalize_text_value,
    strip_source_lines as _strip_source_lines,
    clean_solution_explanation_text as _clean_solution_explanation_text,
    is_generic_solution_explanation as _is_generic_solution_explanation,
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
from app.task_helpers import (
    parse_title_parts as _parse_title_parts,
    build_task_title as _build_task_title,
    infer_topic as _infer_topic,
    infer_answer_from_statement as _infer_answer_from_statement,
)
from app.ai_worker import (
    get_or_generate_ai_solution as _get_or_generate_ai_solution,
    _extract_answer_from_solution_text,
)

router = APIRouter()


@router.get("/admin/users")
def admin_get_users(current_user: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    users = db.query(User).all()
    return {"users": [{"id": u.id, "username": u.username, "email": u.email, "rating": u.rating, "is_admin": u.is_admin} for u in users]}


@router.post("/admin/tasks/generate_ai_solutions")
def generate_ai_solutions(limit: int = 20, force: bool = False, current_user: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    try:
        safe_limit = max(1, min(limit, 200))
        selected = []
        for task in db.query(Task).order_by(Task.id.asc()).all():
            answer_value = _normalize_text_value(task.answer)
            explanation_value = _clean_solution_explanation_text(task.solution_explanation)
            if force or _is_manual_answer(answer_value) or not explanation_value or _is_generic_solution_explanation(explanation_value):
                selected.append(task)
            if len(selected) >= safe_limit:
                break
        results = []
        for task in selected:
            answer, explanation, source = _get_or_generate_ai_solution(task, db, force=force)
            results.append({"task_id": task.id, "status": task.ai_solution_status, "error": task.ai_solution_error,
                            "source": source, "answer": answer or _extract_answer_from_solution_text(explanation)})
        return {"processed": len(results), "limit": safe_limit, "items": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка генерации решений")


@router.get("/admin/tasks/export")
def export_tasks(current_user: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    try:
        tasks = db.query(Task).all()
        result = [{
            "title": t.title, "problem_statement": t.problem_statement, "answer": t.answer,
            "subject": t.subject, "grade": t.grade, "difficulty": t.difficulty, "points": t.points,
            "input_format": t.input_format, "output_format": t.output_format, "examples": t.examples,
            "solution_explanation": t.solution_explanation, "topic": t.topic, "tags": t.tags,
            "attachments": _attachments_from_storage(t.attachments),
            "source_pdf_url": t.source_pdf_url, "source_page_start": t.source_page_start,
            "source_page_end": t.source_page_end,
            "source_fragments": _source_fragments_from_storage(t.source_fragments),
            "source_solution_pdf_url": _normalize_text_value(getattr(t, "source_solution_pdf_url", "") or ""),
            "full_problem_statement": _normalize_text_value(getattr(t, "full_problem_statement", "") or ""),
            "official_solution_text": _normalize_text_value(getattr(t, "official_solution_text", "") or ""),
            "free_ai_explanation": _normalize_text_value(getattr(t, "free_ai_explanation", "") or ""),
            "free_ai_status": _normalize_text_value(getattr(t, "free_ai_status", "") or ""),
            "ai_answer_short": t.ai_answer_short, "ai_solution_full": t.ai_solution_full,
            "ai_solution_status": t.ai_solution_status, "ai_solution_model": t.ai_solution_model,
            "ai_solution_error": t.ai_solution_error, "ai_solution_hash": t.ai_solution_hash,
            "ai_solution_generated_at": t.ai_solution_generated_at.isoformat() if t.ai_solution_generated_at else None,
            "time_limit": t.time_limit,
        } for t in tasks]
        return {"tasks": result}
    except Exception:
        raise HTTPException(status_code=500, detail="Ошибка при экспорте задач")


@router.post("/admin/tasks/import")
def import_tasks(tasks_data: dict, current_user: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    try:
        imported_count = 0
        for task_data in tasks_data.get("tasks", []):
            grade = _safe_int(task_data.get("grade"), None)
            subject = _normalize_subject(task_data.get("subject", "математика"))
            difficulty = _normalize_difficulty(task_data.get("difficulty", "easy"))
            statement_raw = _normalize_text_value(task_data.get("problem_statement"))
            statement = _strip_source_lines(statement_raw)
            answer = _normalize_text_value(task_data.get("answer"))
            source_pdf_url = _normalize_text_value(task_data.get("source_pdf_url") or _extract_source_url(statement_raw, task_data.get("solution_explanation"), task_data.get("official_solution_text")))
            source_fragments = _normalize_source_fragments(task_data.get("source_fragments"))
            full_problem_statement = _normalize_text_value(task_data.get("full_problem_statement"))
            official_solution_text = _normalize_text_value(task_data.get("official_solution_text"))
            free_ai_explanation = _normalize_text_value(task_data.get("free_ai_explanation"))
            free_ai_status = _normalize_text_value(task_data.get("free_ai_status")) or ("ready" if free_ai_explanation else "empty")
            _, _, task_number = _parse_title_parts(task_data.get("title", ""))
            topic_value = _normalize_text_value(task_data.get("topic")) or _infer_topic(subject, statement, task_number)
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
            db.add(Task(
                title=_build_task_title(task_data.get("title", ""), subject, grade, topic_value, force=True),
                problem_statement=statement, answer=answer, subject=subject, grade=grade,
                difficulty=difficulty, points=task_data.get("points", 10),
                input_format=task_data.get("input_format"), output_format=task_data.get("output_format"),
                examples=task_data.get("examples"), solution_explanation=explanation or None,
                topic=topic_value, tags=task_data.get("tags"),
                attachments=_attachments_to_storage(attachments), source_pdf_url=source_pdf_url or None,
                source_solution_pdf_url=_normalize_text_value(task_data.get("source_solution_pdf_url")) or None,
                source_page_start=_safe_int(task_data.get("source_page_start"), None),
                source_page_end=_safe_int(task_data.get("source_page_end"), None),
                source_fragments=_source_fragments_to_storage(source_fragments),
                full_problem_statement=full_problem_statement or statement or None,
                official_solution_text=official_solution_text or None,
                free_ai_explanation=free_ai_explanation or None, free_ai_status=free_ai_status,
                ai_solution_status="empty", time_limit=_time_limit_by_difficulty(difficulty),
                created_by=current_user.id,
            ))
            imported_count += 1
        db.commit()
        return {"message": f"Imported tasks: {imported_count}"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Ошибка импорта задач")


@router.delete("/admin/tasks/delete_all")
def delete_all_tasks(current_user: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    try:
        count = db.query(Task).count()
        db.query(Task).delete()
        db.commit()
        return {"message": f"Удалено задач: {count}"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Ошибка при удалении")
