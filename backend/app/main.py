from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db, create_tables, User, Task, TaskView, Solution, Match, UserStats, SessionLocal
from app.schemas import UserRegister, UserLogin, TaskCreate, UserProfileUpdate
from app.auth_middleware import get_current_user, get_admin_user
from app.pdf_parser import extract_best_task_entry, extract_task_entries
from app.pvp_manager import match_manager
from app.utils.text import (
    normalize_text_value as _normalize_text_value,
    strip_source_lines as _strip_source_lines,
    clean_solution_explanation_text as _clean_solution_explanation_text,
    is_unavailable_solution_text as _is_unavailable_solution_text,
    is_generic_solution_explanation as _is_generic_solution_explanation,
    first_sentence as _first_sentence,
    simplify_text_for_search as _simplify_text_for_search,
    normalize_text_for_dedupe as _normalize_text_for_dedupe,
    looks_like_duplicate_paragraph as _looks_like_duplicate_paragraph,
    merge_solution_chunks as _merge_solution_chunks,
    clean_generated_solution_text as _clean_generated_solution_text,
    _fix_mojibake_text,
    URL_RE, SOURCE_LINE_RE,
    GENERIC_SOLUTION_MARKERS, PLACEHOLDER_SOLUTION_MARKERS, UNAVAILABLE_SOLUTION_MARKERS,
)
from app.config import (
    _safe_int,
    APP_DIR, BACKEND_DIR, PROJECT_ROOT, CACHE_DIR,
    PDF_SOURCE_CACHE_DIR, PDF_FRAGMENT_CACHE_DIR, TASK_CROPS_DIR,
    TIME_LIMIT_BY_DIFFICULTY, SUBJECT_ALIASES, OLYMPIAD_ALIASES,
    SUPPORTED_SUBJECTS, BASE_SUBJECTS, NEW_SUBJECTS,
    MONTHS_RU_GENITIVE, SUBJECT_THEMES,
    MANUAL_ANSWER_MARKERS, RECOVERABLE_AI_STATUSES, NON_AUTORETRY_AI_STATUSES,
    ANSWER_LABEL_TOKEN_RE, ANSWER_LABEL_VALUE_RE, ANSWER_GROUP_CHUNK_RE, ANSWER_GROUP_MARK_RE,
    NEGATIVE_NUMBER_RE, DECIMAL_NUMBER_RE,
    YEAR_RE, TASK_NUMBER_RE, VARIANT_NUMBER_RE, POINTS_MARKER_RE,
    ANSWER_PREFIX_RE, ANSWER_NOISE_RE,
    ANSWER_HINT_SINGLE, ANSWER_HINT_LABEL_OR_VALUE, ANSWER_HINT_SERVICE_PREFIX,
    ANSWER_HINT_NEGATIVE_NUMBER, ANSWER_HINT_MULTI_LABEL_OR_VALUE, ANSWER_HINT_MULTI_VALUES,
    ANSWER_HINT_GROUPS, ANSWER_HINT_MANUAL,
    _normalize_difficulty, _time_limit_by_difficulty, _normalize_subject,
    _normalize_olympiad_name, _extract_source_url, _is_manual_answer,
    _synthetic_subjects_enabled, _import_ai_solutions_enabled, _sync_tasks_on_startup_enabled,
)
from app.task_import import (
    enrich_task_from_vsosh_pdfs as _enrich_task_from_vsosh_pdfs,
    ensure_tasks_schema_columns,
    import_tasks_from_json,
    split_compound_tasks_after_import,
    has_seed_tasks as _has_seed_tasks,
)
from app.task_helpers import (
    infer_topic as _infer_topic,
    infer_answer_from_statement as _infer_answer_from_statement,
    generate_fallback_solution as _generate_fallback_solution,
    extract_variant_number as _extract_variant_number,
    parse_title_parts as _parse_title_parts,
    build_task_title as _build_task_title,
    task_identity_key as _task_identity_key,
    task_olympiad as _task_olympiad,
    task_list_payload as _task_list_payload,
    answer_input_hint_for_task as _answer_input_hint_for_task,
    extract_answer_from_official_solution as _extract_answer_from_official_solution,
    collect_task_reference_answers as _collect_task_reference_answers,
    resolve_task_reference_answers as _resolve_task_reference_answers,
    resolve_task_reference_answer as _resolve_task_reference_answer,
    resolve_task_ai_reference_answer as _resolve_task_ai_reference_answer,
    resolve_vsosh_reference_answer as _resolve_vsosh_reference_answer,
    build_generated_subject_task as _build_generated_subject_task,
    augment_tasks_with_new_subjects as _augment_tasks_with_new_subjects,
    is_task_ai_answer_pending as _is_task_ai_answer_pending,
    ensure_task_ai_generation as _ensure_task_ai_generation,
    record_task_view as _record_task_view,
)
from app.ai_worker import (
    classify_ai_error as _classify_ai_error,
    get_or_generate_ai_solution as _get_or_generate_ai_solution,
    generate_solution_with_local_llm as _generate_solution_with_local_llm,
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
from app.utils.pdf import (
    ensure_cache_dirs as _ensure_cache_dirs,
    get_source_pdf_url as _get_source_pdf_url,
    ensure_local_pdf_path as _ensure_local_pdf_path,
    url_exists as _url_exists,
    render_task_fragments as _render_task_fragments,
    find_fragment_for_chunk_in_pdf as _find_fragment_for_chunk_in_pdf,
    split_statement_by_points_markers as _split_statement_by_points_markers,
    source_pdf_cache_path as _source_pdf_cache_path,
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
from app.utils.answer import (
    normalize_answer_token as _normalize_answer_token,
    normalize_compact_answer_token as _normalize_compact_answer_token,
    is_negative_number_answer as _is_negative_number_answer,
    looks_like_meaningful_answer as _looks_like_meaningful_answer,
    is_compact_submission as _is_compact_submission,
    parse_label_answer_pair as _parse_label_answer_pair,
    split_top_level_group_chunks as _split_top_level_group_chunks,
    parse_group_chunk as _parse_group_chunk,
    parse_grouped_answer as _parse_grouped_answer,
    normalize_group_answer as _normalize_group_answer,
    is_multi_answer as _is_multi_answer,
    split_multiple_answer_parts as _split_multiple_answer_parts,
    parse_multi_answer as _parse_multi_answer,
    extract_answer_without_service_prefix as _extract_answer_without_service_prefix,
    build_answer_check_profile as _build_answer_check_profile,
    check_user_answer_against_reference as _check_user_answer_against_reference,
    answer_input_hint_for_reference as _answer_input_hint_for_reference,
    clean_reference_answer_text as _clean_reference_answer_text,
    build_answer_check_status as _build_answer_check_status,
)
from datetime import datetime, timedelta, date
from pathlib import Path
import json
import random
import re
import hashlib
import os
from collections import Counter, deque
from urllib.parse import urlparse
from urllib.request import urlretrieve, Request, urlopen
from urllib.error import HTTPError, URLError


app = FastAPI(title="EzOlimp")




@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"error": "Что-то пошло не так на сервере", "details": str(exc)}
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail}
    )


# Как я понял, это: "Сервер, разрешай всем сайтам к тебе обращаться". Без этого не будет по ПБ, блокирует тварь такая.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Создание таблиц в бд при запуске.
@app.on_event("startup")
def startup():
    create_tables()
    ensure_tasks_schema_columns()
    if not _has_seed_tasks() or _sync_tasks_on_startup_enabled():
        import_tasks_from_json()
        split_compound_tasks_after_import()
    else:
        print("Skipped tasks.json sync on startup: tasks already exist (set SYNC_TASKS_ON_STARTUP=1 to force)")


# Основной хендлер.
@app.get("/")
def root():
    return {"message": "Все ОК"}


@app.get("/stats")
# Проверка доступа к бд.
def stats(db: Session = Depends(get_db)):
    try:
        users = db.query(User).count()
        tasks = db.query(Task).count()
        solutions = db.query(Solution).count()
        matches = db.query(Match).count()
        return {
            "users": users,
            "tasks": tasks,
            "solutions": solutions,
            "matches": matches
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при получении статистики")


@app.get("/users")
def get_users(db: Session = Depends(get_db)):
    try:
        users = db.query(User).limit(10).all()
        result = []
        for user in users:
            result.append({
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "full_name": user.full_name,
                "school": user.school,
                "grade": user.grade,
                "rating": user.rating,
                "is_admin": user.is_admin
            })
        return {"users": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при получении пользователей")



@app.get("/tasks")
def get_tasks(db: Session = Depends(get_db)):
    try:
        tasks = db.query(Task).all()
        result = [_task_list_payload(task) for task in tasks]
        return {"tasks": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при получении задач")


@app.get("/tasks/filters")
def get_task_filters(db: Session = Depends(get_db)):
    try:
        tasks = db.query(Task).all()
        subject_order = {subject: idx for idx, subject in enumerate(SUPPORTED_SUBJECTS)}
        tree = {}
        for task in tasks:
            subject = _normalize_subject(task.subject)
            olympiad = _task_olympiad(task)
            if not subject or not olympiad or task.grade is None:
                continue
            tree.setdefault(subject, {}).setdefault(olympiad, set()).add(str(task.grade))

        subjects = sorted(
            {_normalize_subject(task.subject) for task in tasks if _normalize_subject(task.subject)},
            key=lambda value: (subject_order.get(value, 999), value),
        )
        olympiads = sorted({_task_olympiad(task) for task in tasks if _task_olympiad(task)})
        grades = sorted({task.grade for task in tasks if task.grade is not None and 1 <= int(task.grade) <= 11})

        normalized_tree = {
            subject: {
                olympiad: sorted(grades_set, key=lambda value: int(value) if str(value).isdigit() else 999)
                for olympiad, grades_set in sorted(olympiads_map.items())
            }
            for subject, olympiads_map in sorted(
                tree.items(),
                key=lambda item: (subject_order.get(item[0], 999), item[0]),
            )
        }

        return {"subjects": subjects, "olympiads": olympiads, "grades": grades, "tree": normalized_tree}
    except Exception:
        raise HTTPException(status_code=500, detail="Ошибка при получении фильтров")


@app.get("/tasks/popular/today")
def get_popular_tasks_today(limit: int = 10, db: Session = Depends(get_db)):
    try:
        safe_limit = max(1, min(int(limit or 10), 50))
        today = date.today()

        rows = (
            db.query(Task, TaskView.view_count)
            .join(TaskView, TaskView.task_id == Task.id)
            .filter(TaskView.viewed_on == today)
            .order_by(TaskView.view_count.desc(), Task.id.asc())
            .limit(safe_limit)
            .all()
        )

        result = [_task_list_payload(task, view_count=count) for task, count in rows]
        selected_ids = {task.id for task, _ in rows}

        if len(result) < safe_limit:
            fallback_query = db.query(Task)
            if selected_ids:
                fallback_query = fallback_query.filter(~Task.id.in_(selected_ids))
            fallback_tasks = fallback_query.order_by(Task.id.asc()).limit(safe_limit - len(result)).all()
            result.extend(_task_list_payload(task, view_count=0) for task in fallback_tasks)

        return {"date": today.isoformat(), "tasks": result}
    except Exception:
        raise HTTPException(status_code=500, detail="Ошибка при получении популярных задач")


# Endpoints авторизации
@app.post("/auth/register")
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    try:
        from app.database import hash_password

        if db.query(User).filter(User.username == user_data.username).first():
            raise HTTPException(status_code=400, detail="Пользователь с таким именем уже существует")
        if db.query(User).filter(User.email == user_data.email).first():
            raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")

        avatar_id = hash(user_data.username) % 1000
        user = User(
            username=user_data.username,
            email=user_data.email,
            password_hash=hash_password(user_data.password),
            full_name=user_data.full_name,
            school=user_data.school,
            grade=user_data.grade,
            avatar_url=f"https://i.pravatar.cc/150?img={avatar_id}"
        )
        db.add(user)
        db.commit()
        return {"message": "Регистрация успешна", "user_id": user.id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при регистрации")


@app.post("/auth/login")
def login(login_data: UserLogin, db: Session = Depends(get_db)):
    try:
        from app.database import verify_password

        user = db.query(User).filter(User.username == login_data.username).first()
        if not user:
            raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")

        if not verify_password(login_data.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")

        user.last_login = datetime.now()
        db.commit()

        return {
            "message": "Вход выполнен успешно",
            "token": f"Bearer {user.username}",
            "user": {
                "id": user.id,
                "username": user.username,
                "full_name": user.full_name,
                "is_admin": user.is_admin
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Login error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Ошибка при входе: {str(e)}")


# Защищенные endpoints
@app.get("/auth/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "school": current_user.school,
        "grade": current_user.grade,
        "rating": current_user.rating,
        "is_admin": current_user.is_admin,
        "avatar_url": current_user.avatar_url,
        "bio": current_user.bio,
        "phone": current_user.phone,
        "telegram": current_user.telegram,
        "vk": current_user.vk,
        "github": current_user.github
    }


@app.put("/auth/me")
def update_me(profile_data: UserProfileUpdate, current_user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    try:
        if profile_data.full_name is not None:
            current_user.full_name = profile_data.full_name
        if profile_data.school is not None:
            current_user.school = profile_data.school
        if profile_data.grade is not None:
            current_user.grade = profile_data.grade
        if profile_data.bio is not None:
            current_user.bio = profile_data.bio
        if profile_data.phone is not None:
            current_user.phone = profile_data.phone
        if profile_data.telegram is not None:
            current_user.telegram = profile_data.telegram
        if profile_data.vk is not None:
            current_user.vk = profile_data.vk
        if profile_data.github is not None:
            current_user.github = profile_data.github
        if profile_data.avatar_url is not None:
            current_user.avatar_url = profile_data.avatar_url

        db.commit()
        return {"message": "Профиль обновлен"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Ошибка при обновлении профиля")


@app.get("/users/{user_id}/stats")
def get_user_stats(user_id: int, db: Session = Depends(get_db)):
    try:
        stats = db.query(UserStats).filter(UserStats.user_id == user_id).first()
        if not stats:
            return {
                "total_solved": 0,
                "correct_answers": 0,
                "total_points": 0,
                "current_streak": 0,
                "best_streak": 0
            }
        return {
            "total_solved": stats.total_solved or 0,
            "correct_answers": stats.correct_answers or 0,
            "total_points": stats.total_points or 0,
            "current_streak": stats.current_streak or 0,
            "best_streak": stats.best_streak or 0
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при получении статистики")


@app.get("/users/{user_id}/analytics")
def get_user_analytics(user_id: int, db: Session = Depends(get_db)):
    try:
        from sqlalchemy import func, distinct

        correct_solutions = db.query(Solution).filter(
            Solution.user_id == user_id,
            Solution.is_correct == True
        ).all()

        unique_tasks = {}
        for sol in correct_solutions:
            if sol.task_id not in unique_tasks:
                unique_tasks[sol.task_id] = sol

        if not unique_tasks:
            return {
                "by_subject": {},
                "by_difficulty": {},
                "by_date": [],
                "accuracy": 0
            }

        by_subject = {}
        by_difficulty = {}
        by_date = {}

        for task_id, solution in unique_tasks.items():
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task:
                continue

            subject_key = _normalize_subject(task.subject)
            difficulty_key = _normalize_difficulty(task.difficulty)

            if subject_key not in by_subject:
                by_subject[subject_key] = {"total": 0, "correct": 0}
            by_subject[subject_key]["total"] += 1
            by_subject[subject_key]["correct"] += 1

            if difficulty_key not in by_difficulty:
                by_difficulty[difficulty_key] = {"total": 0, "correct": 0}
            by_difficulty[difficulty_key]["total"] += 1
            by_difficulty[difficulty_key]["correct"] += 1

            date_key = solution.submitted_at.strftime("%Y-%m-%d") if solution.submitted_at else datetime.now().strftime(
                "%Y-%m-%d")
            if date_key not in by_date:
                by_date[date_key] = 0
            by_date[date_key] += 1

        sorted_dates = sorted(by_date.items())

        stats = db.query(UserStats).filter(UserStats.user_id == user_id).first()
        total = stats.total_solved if stats else len(unique_tasks)
        correct = stats.correct_answers if stats else len(unique_tasks)
        accuracy = round((correct / total * 100) if total > 0 else 0, 1)

        return {
            "by_subject": by_subject,
            "by_difficulty": by_difficulty,
            "by_date": sorted_dates,
            "accuracy": accuracy,
            "total_solutions": total,
            "correct_solutions": correct
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")


@app.get("/users/{user_id}/achievements")
def get_user_achievements(user_id: int, db: Session = Depends(get_db)):
    try:
        stats = db.query(UserStats).filter(UserStats.user_id == user_id).first()
        matches = db.query(Match).filter(
            (Match.player1_id == user_id) | (Match.player2_id == user_id),
            Match.status == "finished"
        ).all()
        correct_answers = stats.correct_answers if stats else 0
        best_streak = stats.best_streak if stats else 0
        total_points = stats.total_points if stats else 0
        pvp_wins = sum(1 for m in matches if m.winner_id == user_id)
        pvp_total = len(matches)
        ALL_ACHIEVEMENTS = [
            {"id": "first_solve",
             "title": "\u041f\u0435\u0440\u0432\u043e\u0435 \u0440\u0435\u0448\u0435\u043d\u0438\u0435",
             "description": "\u0420\u0435\u0448\u0438 \u043f\u0435\u0440\u0432\u0443\u044e \u0437\u0430\u0434\u0430\u0447\u0443",
             "color": "yellow", "emoji": "\u2b50", "check": correct_answers >= 1},
            {"id": "solver_5", "title": "\u041d\u0430\u0447\u0438\u043d\u0430\u044e\u0449\u0438\u0439",
             "description": "5 \u043f\u0440\u0430\u0432\u0438\u043b\u044c\u043d\u044b\u0445 \u043e\u0442\u0432\u0435\u0442\u043e\u0432",
             "color": "blue", "emoji": "\ud83d\udcda", "check": correct_answers >= 5},
            {"id": "solver_10", "title": "\u041d\u043e\u0432\u0438\u0447\u043e\u043a",
             "description": "10 \u043f\u0440\u0430\u0432\u0438\u043b\u044c\u043d\u044b\u0445 \u043e\u0442\u0432\u0435\u0442\u043e\u0432",
             "color": "blue", "emoji": "\ud83c\udfc5", "check": correct_answers >= 10},
            {"id": "solver_25", "title": "\u041f\u0440\u043e\u0434\u0432\u0438\u043d\u0443\u0442\u044b\u0439",
             "description": "25 \u043f\u0440\u0430\u0432\u0438\u043b\u044c\u043d\u044b\u0445 \u043e\u0442\u0432\u0435\u0442\u043e\u0432",
             "color": "purple", "emoji": "\ud83d\udd2e", "check": correct_answers >= 25},
            {"id": "solver_50", "title": "\u041e\u043f\u044b\u0442\u043d\u044b\u0439",
             "description": "50 \u043f\u0440\u0430\u0432\u0438\u043b\u044c\u043d\u044b\u0445 \u043e\u0442\u0432\u0435\u0442\u043e\u0432",
             "color": "purple", "emoji": "\ud83e\udd47", "check": correct_answers >= 50},
            {"id": "solver_100", "title": "\u041c\u0430\u0441\u0442\u0435\u0440",
             "description": "100 \u043f\u0440\u0430\u0432\u0438\u043b\u044c\u043d\u044b\u0445 \u043e\u0442\u0432\u0435\u0442\u043e\u0432",
             "color": "orange", "emoji": "\ud83d\udc51", "check": correct_answers >= 100},
            {"id": "solver_250", "title": "\u041b\u0435\u0433\u0435\u043d\u0434\u0430",
             "description": "250 \u043f\u0440\u0430\u0432\u0438\u043b\u044c\u043d\u044b\u0445 \u043e\u0442\u0432\u0435\u0442\u043e\u0432",
             "color": "orange", "emoji": "\ud83d\udd25", "check": correct_answers >= 250},
            {"id": "streak_3", "title": "\u0421\u0435\u0440\u0438\u044f x3",
             "description": "3 \u0437\u0430\u0434\u0430\u0447\u0438 \u043f\u043e\u0434\u0440\u044f\u0434",
             "color": "red", "emoji": "\u26a1", "check": best_streak >= 3},
            {"id": "streak_5", "title": "\u0421\u0435\u0440\u0438\u044f x5",
             "description": "5 \u0437\u0430\u0434\u0430\u0447 \u043f\u043e\u0434\u0440\u044f\u0434", "color": "red",
             "emoji": "\ud83d\udd25", "check": best_streak >= 5},
            {"id": "streak_10", "title": "\u0421\u0435\u0440\u0438\u044f x10",
             "description": "10 \u0437\u0430\u0434\u0430\u0447 \u043f\u043e\u0434\u0440\u044f\u0434", "color": "red",
             "emoji": "\ud83c\udf29\ufe0f", "check": best_streak >= 10},
            {"id": "points_50", "title": "\u041a\u043e\u043f\u0438\u043b\u043a\u0430",
             "description": "50 \u043e\u0447\u043a\u043e\u0432", "color": "yellow", "emoji": "\ud83d\udcb0",
             "check": total_points >= 50},
            {"id": "points_100", "title": "\u041a\u043e\u043b\u043b\u0435\u043a\u0446\u0438\u043e\u043d\u0435\u0440",
             "description": "100 \u043e\u0447\u043a\u043e\u0432", "color": "yellow", "emoji": "\ud83d\udcb8",
             "check": total_points >= 100},
            {"id": "points_500", "title": "\u0411\u043e\u0433\u0430\u0447",
             "description": "500 \u043e\u0447\u043a\u043e\u0432", "color": "orange", "emoji": "\ud83d\udcb3",
             "check": total_points >= 500},
            {"id": "first_pvp_win",
             "title": "\u041f\u0435\u0440\u0432\u0430\u044f \u043f\u043e\u0431\u0435\u0434\u0430",
             "description": "\u041f\u043e\u0431\u0435\u0434\u0438 \u0432 PvP \u043c\u0430\u0442\u0447\u0435",
             "color": "green", "emoji": "\ud83c\udfc6", "check": pvp_wins >= 1},
            {"id": "pvp_5", "title": "\u0411\u043e\u0435\u0446",
             "description": "5 \u043f\u043e\u0431\u0435\u0434 \u0432 PvP", "color": "green", "emoji": "\u2694\ufe0f",
             "check": pvp_wins >= 5},
            {"id": "pvp_master", "title": "\u041c\u0430\u0441\u0442\u0435\u0440 PvP",
             "description": "10 \u043f\u043e\u0431\u0435\u0434 \u0432 PvP", "color": "purple", "emoji": "\ud83d\udc8e",
             "check": pvp_wins >= 10},
            {"id": "pvp_played_10",
             "title": "\u0410\u043a\u0442\u0438\u0432\u043d\u044b\u0439 \u0438\u0433\u0440\u043e\u043a",
             "description": "10 PvP \u043c\u0430\u0442\u0447\u0435\u0439", "color": "blue", "emoji": "\ud83c\udfae",
             "check": pvp_total >= 10},
        ]
        result = [
            {"id": a["id"], "title": a["title"], "description": a["description"],
             "color": a["color"], "emoji": a["emoji"], "unlocked": bool(a["check"])}
            for a in ALL_ACHIEVEMENTS
        ]
        unlocked = [a for a in result if a["unlocked"]]
        locked = [a for a in result if not a["unlocked"]]
        return {"achievements": unlocked + locked, "total_unlocked": len(unlocked),
                "total_available": len(ALL_ACHIEVEMENTS)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")


@app.get("/users/{user_id}/profile")
def get_user_profile(user_id: int, db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        return {
            "id": user.id, "username": user.username, "full_name": user.full_name,
            "school": user.school, "grade": user.grade, "rating": user.rating,
            "avatar_url": user.avatar_url, "bio": user.bio
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при получении профиля")


@app.get("/users/{user_id}/solutions")
def get_user_solutions(user_id: int, db: Session = Depends(get_db)):
    try:
        solutions = db.query(Solution).filter(
            Solution.user_id == user_id, Solution.is_correct == True
        ).order_by(Solution.created_at.desc()).limit(10).all()
        result = []
        for sol in solutions:
            task = db.query(Task).filter(Task.id == sol.task_id).first()
            if task:
                result.append({
                    "task_id": task.id,
                    "task_title": _build_task_title(task.title, _normalize_subject(task.subject), task.grade,
                                                    task.topic),
                    "subject": _normalize_subject(task.subject),
                    "difficulty": _normalize_difficulty(task.difficulty),
                    "points": sol.points_earned,
                    "solved_at": sol.created_at.isoformat() if sol.created_at else None
                })
        return {"solutions": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")


@app.get("/leaderboard")
def get_leaderboard(limit: int = 50, db: Session = Depends(get_db)):
    try:
        users = db.query(User).order_by(User.rating.desc()).limit(limit).all()
        result = []
        for idx, user in enumerate(users, 1):
            stats = db.query(UserStats).filter(UserStats.user_id == user.id).first()
            result.append({
                "rank": idx, "id": user.id, "username": user.username,
                "full_name": user.full_name, "school": user.school or "-",
                "rating": user.rating, "avatar_url": user.avatar_url,
                "total_solved": stats.total_solved if stats else 0
            })
        return {"leaderboard": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при получении рейтинга")


@app.post("/auth/logout")
def logout(current_user: User = Depends(get_current_user)):
    return {"message": "Выход выполнен"}


@app.get("/admin/users")
def admin_get_users(current_user: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    users = db.query(User).all()
    return {
        "users": [{"id": u.id, "username": u.username, "email": u.email, "rating": u.rating, "is_admin": u.is_admin} for
                  u in users]}


@app.post("/test/create_sample_data")
def create_sample_data(db: Session = Depends(get_db)):
    try:
        from app.database import hash_password
        if not db.query(User).filter(User.username == "test_user").first():
            user = User(username="test_user", email="test@example.com",
                        password_hash=hash_password("123456"),
                        full_name="Тестовый Пользователь", school="Школа №123", grade=10)
            db.add(user)
        db.commit()
        return {"message": "Тестовые данные созданы"}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при создании тестовых данных")


@app.post("/users")
def create_user(user_data: UserRegister, db: Session = Depends(get_db)):
    try:
        from app.database import hash_password
        if db.query(User).filter(User.username == user_data.username).first():
            raise HTTPException(status_code=400, detail="Пользователь с таким именем уже существует")
        if db.query(User).filter(User.email == user_data.email).first():
            raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")
        user = User(username=user_data.username, email=user_data.email,
                    password_hash=hash_password(user_data.password),
                    full_name=user_data.full_name, school=user_data.school, grade=user_data.grade)
        db.add(user)
        db.commit()
        return {"message": "Пользователь создан", "id": user.id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при создании пользователя")


@app.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        db.delete(user)
        db.commit()
        return {"message": "Пользователь удален"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при удалении пользователя")


@app.post("/tasks")
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
        source_pdf_url = _normalize_text_value(
            task_data.source_pdf_url
            or _extract_source_url(
                task_data.problem_statement,
                task_data.solution_explanation,
                getattr(task_data, "official_solution_text", None),
            )
        )
        source_solution_pdf_url = _normalize_text_value(getattr(task_data, "source_solution_pdf_url", None))
        source_page_start = _safe_int(task_data.source_page_start, None)
        source_page_end = _safe_int(task_data.source_page_end, None)
        source_fragments = _normalize_source_fragments(task_data.source_fragments)
        full_problem_statement = _normalize_text_value(getattr(task_data, "full_problem_statement", None))
        official_solution_text = _normalize_text_value(getattr(task_data, "official_solution_text", None))
        free_ai_explanation = _normalize_text_value(getattr(task_data, "free_ai_explanation", None))
        free_ai_status = _normalize_text_value(getattr(task_data, "free_ai_status", None))
        if not free_ai_status:
            free_ai_status = "ready" if free_ai_explanation else "empty"
        attachments = _normalize_attachments(task_data.attachments, subject=subject, grade=task_data.grade,
                                             topic=topic_value, statement=statement)
        attachments = _ensure_source_pdf_attachment(attachments, source_pdf_url)
        task = Task(
            title=_build_task_title(task_data.title, subject, task_data.grade, topic_value, force=True),
            problem_statement=statement, answer=answer, subject=subject, grade=task_data.grade,
            difficulty=difficulty, points=task_data.points or 10, input_format=task_data.input_format,
            output_format=task_data.output_format, examples=task_data.examples,
            solution_explanation=explanation or None, topic=topic_value, tags=task_data.tags,
            attachments=_attachments_to_storage(attachments), source_pdf_url=source_pdf_url or None,
            source_solution_pdf_url=source_solution_pdf_url or None,
            source_page_start=source_page_start, source_page_end=source_page_end,
            source_fragments=_source_fragments_to_storage(source_fragments),
            full_problem_statement=full_problem_statement or statement or None,
            official_solution_text=official_solution_text or None,
            free_ai_explanation=free_ai_explanation or None,
            free_ai_status=free_ai_status,
            ai_solution_status="empty", time_limit=_time_limit_by_difficulty(difficulty),
            created_by=current_user.id
        )
        db.add(task)
        db.commit()
        return {"message": "Задача создана", "id": task.id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")


@app.get("/tasks/filter")
def filter_tasks(subject: str = None, olympiad: str = None, grade: int = None, difficulty: str = None,
                 db: Session = Depends(get_db)):
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
            olympiad_value = _normalize_olympiad_name(olympiad)
            tasks = [task for task in tasks if _task_olympiad(task) == olympiad_value]
        result = [_task_list_payload(t) for t in tasks]
        return {"tasks": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при фильтрации задач")


@app.get("/static/task_crops/{img_name}")
def get_task_crop(img_name: str):
    import re as _re
    if not _re.fullmatch(r"task_[\d_v]+_[0-9a-f]+\.webp", img_name):
        raise HTTPException(status_code=404, detail="Not found")
    path = TASK_CROPS_DIR / img_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path=path, media_type="image/webp")


@app.get("/tasks/fragments/{fragment_name}")
def get_task_fragment(fragment_name: str):
    import re as _re
    if not _re.fullmatch(r"[0-9a-f]{64}\.webp", fragment_name):
        raise HTTPException(status_code=404, detail="Fragment not found")
    fragment_path = PDF_FRAGMENT_CACHE_DIR / fragment_name
    if not fragment_path.exists():
        raise HTTPException(status_code=404, detail="Fragment not found")
    return FileResponse(path=fragment_path, media_type="image/webp")


@app.get("/tasks/{task_id}/visual")
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
        raise HTTPException(status_code=500, detail=f"Failed to render task visual: {str(e)}")


@app.get("/generation/jobs")
def get_generation_jobs(current_user: User = Depends(get_current_user)):
    _ = current_user
    return _get_ai_generation_jobs_snapshot()


@app.get("/tasks/{task_id}/solution")
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
        cleaned_free_ai_explanation = _clean_generated_solution_text(free_ai_explanation)
        if cleaned_free_ai_explanation != free_ai_explanation:
            free_ai_explanation = cleaned_free_ai_explanation
            task.free_ai_explanation = free_ai_explanation or None
            db.commit()
        free_ai_is_placeholder = bool(free_ai_explanation) and (
                _is_unavailable_solution_text(free_ai_explanation)
                or _is_generic_solution_explanation(free_ai_explanation)
        )
        if free_ai_is_placeholder:
            free_ai_explanation = ""
            if getattr(task, "free_ai_explanation", None):
                task.free_ai_explanation = None
                task.free_ai_status = "empty"
                db.commit()
        if not free_ai_explanation:
            cached_ai_solution = _normalize_text_value(getattr(task, "ai_solution_full", "") or "")
            cleaned_cached_ai_solution = _clean_generated_solution_text(cached_ai_solution)
            if cleaned_cached_ai_solution != cached_ai_solution:
                cached_ai_solution = cleaned_cached_ai_solution
                task.ai_solution_full = cached_ai_solution or None
                db.commit()
            cached_ai_is_placeholder = bool(cached_ai_solution) and (
                    _is_unavailable_solution_text(cached_ai_solution)
                    or _is_generic_solution_explanation(cached_ai_solution)
            )
            if cached_ai_is_placeholder:
                cached_ai_solution = ""
                if getattr(task, "ai_solution_full", None):
                    task.ai_solution_full = None
                    if task.ai_solution_status == "ready":
                        task.ai_solution_status = "empty"
                    db.commit()
            if cached_ai_solution and task.ai_solution_status == "ready":
                free_ai_explanation = cached_ai_solution
                task.free_ai_explanation = cached_ai_solution
                task.free_ai_status = "ready"
                db.commit()
        if _is_ai_generation_stale(task):
            if _is_ai_generation_job_active(task.id):
                with _ai_solution_jobs_lock:
                    _ai_solution_jobs.discard(task.id)
            stale_after_sec = _resolve_ai_generating_stale_sec()
            task.ai_solution_status = "timeout"
            task.ai_solution_error = f"Генерация превысила {stale_after_sec} сек."
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
                    explanation = ai_solution
                    free_ai_explanation = ai_solution
                    if (
                            _normalize_text_value(getattr(task, "free_ai_explanation", "") or "") != free_ai_explanation
                            or _normalize_text_value(getattr(task, "free_ai_status", "") or "") != "ready"
                    ):
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
            ai_answer_candidate = (
                    _extract_answer_from_solution_text(free_ai_explanation)
                    or _extract_answer_from_solution_text(
                _normalize_text_value(getattr(task, "ai_solution_full", "") or ""))
                    or _extract_answer_from_solution_text(explanation)
            )
            ai_answer_raw = _clean_reference_answer_text(ai_answer_candidate)
        if ai_answer_raw:
            stored_ai_answer = _clean_reference_answer_text(getattr(task, "ai_answer_short", "") or "")
            if stored_ai_answer != ai_answer_raw:
                task.ai_answer_short = ai_answer_raw
                db.commit()
        if _is_generic_solution_explanation(explanation):
            explanation = ""
        if not explanation:
            explanation = _generate_fallback_solution(
                getattr(task, "full_problem_statement", "") or task.problem_statement or "",
                _normalize_subject(task.subject),
                task.topic or "",
                answer_value or task.answer or "",
                task.ai_solution_error or task.ai_solution_status or ai_source,
            )
        if not answer_value:
            answer_value = vsosh_answer_value or _extract_answer_from_solution_text(
                free_ai_explanation) or _extract_answer_from_solution_text(explanation) or "см. решение"
        if not vsosh_answer_value:
            vsosh_answer_value = _extract_answer_from_solution_text(official_solution_text)

        free_status = _normalize_text_value(getattr(task, "free_ai_status", "") or "")
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
            "ai_answer_raw": ai_answer_raw,
            "vsosh_answer_raw": vsosh_answer_value,
            "official_solution_text": official_solution_text,
            "free_ai_explanation": free_ai_explanation,
            "free_ai_status": free_status,
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
        import traceback;
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to get solution: {str(e)}")


@app.get("/tasks/{task_id}")
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
        full_statement = _normalize_text_value(
            getattr(task, "full_problem_statement", "") or task.problem_statement or "")
        if not full_statement:
            full_statement = _strip_source_lines(task.problem_statement or "")
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
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при получении задачи")


@app.post("/tasks/{task_id}/solve")
def solve_task(task_id: int, user_answer: str, current_user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        previous_solution = db.query(Solution).filter(
            Solution.user_id == current_user.id, Solution.task_id == task_id
        ).order_by(Solution.created_at.desc()).first()
        viewed_solution = previous_solution.viewed_solution if previous_solution else False
        previous_correct = bool(previous_solution and previous_solution.is_correct)

        vsosh_reference = _resolve_vsosh_reference_answer(task)
        vsosh_check = _build_answer_check_status(user_answer, vsosh_reference)

        ai_reference = _resolve_task_ai_reference_answer(task)
        ai_check = _build_answer_check_status(user_answer, ai_reference)

        input_hint = _answer_input_hint_for_task(task)
        if ai_check.get("status") in ("correct", "incorrect") and ai_check.get("hint"):
            input_hint = ai_check["hint"]
        elif vsosh_check.get("status") in ("correct", "incorrect") and vsosh_check.get("hint"):
            input_hint = vsosh_check["hint"]

        ai_pending = _is_task_ai_answer_pending(task)
        vsosh_is_correct = bool(vsosh_check.get("is_correct"))
        if ai_pending and not vsosh_is_correct:
            _ensure_task_ai_generation(task, db)
            return {
                "is_correct": False,
                "manual_check": False,
                "pending_ai_check": True,
                "message": "\u041f\u043e\u0434\u043e\u0436\u0434\u0438\u0442\u0435... \u0438\u0434\u0435\u0442 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430.",
                "points_earned": 0,
                "already_solved": previous_correct,
                "answer_input_hint": input_hint,
                "vsosh_check_status": vsosh_check.get("status", "unavailable"),
                "vsosh_is_correct": vsosh_check.get("is_correct"),
                "vsosh_reference_answer": vsosh_check.get("reference", ""),
                "ai_check_status": "pending",
                "ai_is_correct": None,
                "ai_reference_answer": "",
            }

        ai_status = ai_check.get("status", "unavailable")
        vsosh_status = vsosh_check.get("status", "unavailable")
        ai_known = ai_status in ("correct", "incorrect")
        vsosh_known = vsosh_status in ("correct", "incorrect")
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
            return {
                "is_correct": False,
                "manual_check": True,
                "pending_ai_check": False,
                "message": "\u0424\u043e\u0440\u043c\u0430\u0442 \u043e\u0442\u0432\u0435\u0442\u0430 \u0443\u0442\u043e\u0447\u043d\u044f\u0439\u0442\u0435 \u0432 \u0431\u043b\u043e\u043a\u0435 \u0440\u0435\u0448\u0435\u043d\u0438\u044f \u0437\u0430\u0434\u0430\u0447\u0438.",
                "points_earned": 0,
                "already_solved": previous_correct,
                "answer_input_hint": input_hint or ANSWER_HINT_MANUAL,
                "vsosh_check_status": vsosh_check.get("status", "unavailable"),
                "vsosh_is_correct": vsosh_check.get("is_correct"),
                "vsosh_reference_answer": vsosh_check.get("reference", ""),
                "ai_check_status": ai_check.get("status", "unavailable"),
                "ai_is_correct": ai_check.get("is_correct"),
                "ai_reference_answer": ai_check.get("reference", ""),
            }

        is_correct = bool(vsosh_is_correct or ai_is_correct)
        if ai_known and ai_check.get("hint"):
            input_hint = ai_check["hint"]
        elif vsosh_known and vsosh_check.get("hint"):
            input_hint = vsosh_check["hint"]

        points_earned = 0
        if is_correct and not previous_correct and not viewed_solution:
            points_earned = task.points or 0

        solution = Solution(
            user_id=current_user.id,
            task_id=task_id,
            answer=user_answer,
            is_correct=is_correct,
            points_earned=points_earned,
            viewed_solution=viewed_solution,
        )
        db.add(solution)

        user_stats = db.query(UserStats).filter(UserStats.user_id == current_user.id).first()
        if not user_stats:
            user_stats = UserStats(
                user_id=current_user.id,
                total_solved=0,
                correct_answers=0,
                total_points=0,
                current_streak=0,
                best_streak=0,
            )
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
            message = "\u042d\u0442\u0430 \u0437\u0430\u0434\u0430\u0447\u0430 \u0443\u0436\u0435 \u0431\u044b\u043b\u0430 \u0437\u0430\u0441\u0447\u0438\u0442\u0430\u043d\u0430 \u0440\u0430\u043d\u0435\u0435."
        elif viewed_solution and is_correct:
            message = "\u0412\u0435\u0440\u043d\u043e, \u043d\u043e \u0431\u0430\u043b\u043b\u044b \u043d\u0435 \u043d\u0430\u0447\u0438\u0441\u043b\u044f\u044e\u0442\u0441\u044f (\u0440\u0435\u0448\u0435\u043d\u0438\u0435 \u0443\u0436\u0435 \u0431\u044b\u043b\u043e \u043e\u0442\u043a\u0440\u044b\u0442\u043e)."
        elif is_correct:
            message = f"\u0412\u0435\u0440\u043d\u043e! \u041d\u0430\u0447\u0438\u0441\u043b\u0435\u043d\u043e {points_earned} \u0431\u0430\u043b\u043b\u043e\u0432."
        else:
            message = "\u041d\u0435\u0432\u0435\u0440\u043d\u043e. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u0435\u0449\u0451 \u0440\u0430\u0437."
        if ai_pending:
            message = f"{message} \u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u043f\u043e \u043d\u0435\u0439\u0440\u043e\u0441\u0435\u0442\u0438 \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0430\u0435\u0442\u0441\u044f."

        return {
            "is_correct": is_correct,
            "manual_check": False,
            "pending_ai_check": False,
            "message": message,
            "points_earned": points_earned,
            "already_solved": previous_correct,
            "answer_input_hint": input_hint,
            "score_source": final_source,
            "vsosh_check_status": vsosh_check.get("status", "unavailable"),
            "vsosh_is_correct": vsosh_check.get("is_correct"),
            "vsosh_reference_answer": vsosh_check.get("reference", ""),
            "ai_check_status": "pending" if ai_pending else ai_check.get("status", "unavailable"),
            "ai_is_correct": ai_check.get("is_correct"),
            "ai_reference_answer": ai_check.get("reference", ""),
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        db.rollback()
        raise HTTPException(status_code=500, detail=f"\u041e\u0448\u0438\u0431\u043a\u0430: {str(e)}")


@app.put("/tasks/{task_id}")
def update_task(task_id: int, title: str = None, problem_statement: str = None, answer: str = None,
                db: Session = Depends(get_db)):
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        if title: task.title = title
        if problem_statement: task.problem_statement = problem_statement
        if answer: task.answer = answer
        db.commit()
        return {"message": "Задача обновлена"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при обновлении задачи")


@app.delete("/tasks/{task_id}")
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
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при удалении задачи")


@app.post("/admin/tasks/generate_ai_solutions")
def generate_ai_solutions(limit: int = 20, force: bool = False,
                          current_user: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    try:
        safe_limit = max(1, min(limit, 200))
        tasks = db.query(Task).order_by(Task.id.asc()).all()
        selected = []
        for task in tasks:
            answer_value = _normalize_text_value(task.answer)
            explanation_value = _clean_solution_explanation_text(task.solution_explanation)
            if force or _is_manual_answer(answer_value) or not explanation_value or _is_generic_solution_explanation(
                    explanation_value):
                selected.append(task)
            if len(selected) >= safe_limit:
                break
        results = []
        for task in selected:
            answer, explanation, source = _get_or_generate_ai_solution(task, db, force=force)
            results.append({"task_id": task.id, "status": task.ai_solution_status,
                            "error": task.ai_solution_error, "source": source,
                            "answer": answer or _extract_answer_from_solution_text(explanation)})
        return {"processed": len(results), "limit": safe_limit, "items": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate AI solutions: {str(e)}")


@app.get("/admin/tasks/export")
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
            "time_limit": t.time_limit
        } for t in tasks]
        return {"tasks": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при экспорте задач")


@app.post("/admin/tasks/import")
def import_tasks(tasks_data: dict, current_user: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    try:
        tasks = tasks_data.get("tasks", [])
        imported_count = 0
        for task_data in tasks:
            grade = _safe_int(task_data.get("grade"), None)
            subject = _normalize_subject(task_data.get("subject", "математика"))
            difficulty = _normalize_difficulty(task_data.get("difficulty", "easy"))
            statement_raw = _normalize_text_value(task_data.get("problem_statement"))
            statement = _strip_source_lines(statement_raw)
            answer = _normalize_text_value(task_data.get("answer"))
            source_pdf_url = _normalize_text_value(
                task_data.get("source_pdf_url")
                or _extract_source_url(
                    statement_raw,
                    task_data.get("solution_explanation"),
                    task_data.get("official_solution_text"),
                )
            )
            source_solution_pdf_url = _normalize_text_value(task_data.get("source_solution_pdf_url"))
            source_fragments = _normalize_source_fragments(task_data.get("source_fragments"))
            full_problem_statement = _normalize_text_value(task_data.get("full_problem_statement"))
            official_solution_text = _normalize_text_value(task_data.get("official_solution_text"))
            free_ai_explanation = _normalize_text_value(task_data.get("free_ai_explanation"))
            free_ai_status = _normalize_text_value(task_data.get("free_ai_status"))
            if not free_ai_status:
                free_ai_status = "ready" if free_ai_explanation else "empty"
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
            attachments = _normalize_attachments(task_data.get("attachments"), subject=subject, grade=grade,
                                                 topic=topic_value, statement=statement)
            attachments = _ensure_source_pdf_attachment(attachments, source_pdf_url)
            task = Task(
                title=_build_task_title(task_data.get("title", ""), subject, grade, topic_value, force=True),
                problem_statement=statement, answer=answer, subject=subject, grade=grade,
                difficulty=difficulty, points=task_data.get("points", 10),
                input_format=task_data.get("input_format"), output_format=task_data.get("output_format"),
                examples=task_data.get("examples"), solution_explanation=explanation or None,
                topic=topic_value, tags=task_data.get("tags"),
                attachments=_attachments_to_storage(attachments), source_pdf_url=source_pdf_url or None,
                source_solution_pdf_url=source_solution_pdf_url or None,
                source_page_start=_safe_int(task_data.get("source_page_start"), None),
                source_page_end=_safe_int(task_data.get("source_page_end"), None),
                source_fragments=_source_fragments_to_storage(source_fragments),
                full_problem_statement=full_problem_statement or statement or None,
                official_solution_text=official_solution_text or None,
                free_ai_explanation=free_ai_explanation or None,
                free_ai_status=free_ai_status,
                ai_solution_status="empty", time_limit=_time_limit_by_difficulty(difficulty),
                created_by=current_user.id
            )
            db.add(task)
            imported_count += 1
        db.commit()
        return {"message": f"Imported tasks: {imported_count}"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Import error: {str(e)}")


@app.delete("/admin/tasks/delete_all")
def delete_all_tasks(current_user: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    try:
        count = db.query(Task).count()
        db.query(Task).delete()
        db.commit()
        return {"message": f"Удалено задач: {count}"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка при удалении: {str(e)}")


@app.websocket("/ws/pvp/{user_id}")
async def pvp_websocket(websocket: WebSocket, user_id: int, db: Session = Depends(get_db)):
    await match_manager.connect(websocket, user_id)
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            await websocket.send_json({"error": "Пользователь не найден"})
            return
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            if action == "find_match":
                match_manager.add_to_queue(user_id, user.username, user.rating)
                await websocket.send_json({"type": "queue_joined", "message": "Ищем соперника..."})
                match_result = match_manager.find_match(user_id)
                if match_result:
                    player1, player2 = match_result
                    tasks = db.query(Task).all()
                    if not tasks:
                        await websocket.send_json({"error": "Нет доступных задач"})
                        continue
                    task = random.choice(tasks)
                    match_id = match_manager.create_match(player1, player2, task.id)
                    db_match = Match(player1_id=player1["user_id"], player2_id=player2["user_id"],
                                     task_id=task.id, status="active", started_at=datetime.now())
                    db.add(db_match)
                    db.commit()
                    match_data = {
                        "type": "match_found", "match_id": match_id,
                        "opponent": player2["username"] if player1["user_id"] == user_id else player1["username"],
                        "task": {"id": task.id,
                                 "title": _build_task_title(task.title, _normalize_subject(task.subject), task.grade,
                                                            task.topic),
                                 "problem_statement": _strip_source_lines(task.problem_statement or ""),
                                 "difficulty": _normalize_difficulty(task.difficulty),
                                 "points": task.points, "time_limit": _time_limit_by_difficulty(task.difficulty)}
                    }
                    await websocket.send_json(match_data)
                    opponent_id = player2["user_id"] if player1["user_id"] == user_id else player1["user_id"]
                    if opponent_id in match_manager.connections:
                        opp_data = dict(match_data)
                        opp_data["opponent"] = player1["username"] if player2["user_id"] == opponent_id else player2[
                            "username"]
                        await match_manager.connections[opponent_id].send_json(opp_data)
                else:
                    await websocket.send_json({"type": "waiting", "message": "Ожидание соперника..."})
            elif action == "submit_answer":
                match_id = data.get("match_id")
                answer = data.get("answer")
                match = match_manager.submit_answer(match_id, user_id, answer)
                if not match:
                    await websocket.send_json({"error": "Матч не найден"})
                    continue
                task = db.query(Task).filter(Task.id == match["task_id"]).first()
                reference_answers, manual_check = _resolve_task_reference_answers(task)
                if manual_check:
                    is_correct = False
                else:
                    is_correct = any(
                        _check_user_answer_against_reference(answer or "", reference)["is_correct"]
                        for reference in reference_answers
                    )
                if match["player1"]["user_id"] == user_id:
                    if is_correct: match["player1_score"] = task.points
                else:
                    if is_correct: match["player2_score"] = task.points
                await websocket.send_json({
                    "type": "answer_result", "is_correct": is_correct,
                    "your_score": match["player1_score"] if match["player1"]["user_id"] == user_id else match[
                        "player2_score"],
                    "opponent_score": match["player2_score"] if match["player1"]["user_id"] == user_id else match[
                        "player1_score"]
                })
                if match["player1_answer"] and match["player2_answer"]:
                    winner_id = None
                    if match["player1_score"] > match["player2_score"]:
                        winner_id = match["player1"]["user_id"]
                    elif match["player2_score"] > match["player1_score"]:
                        winner_id = match["player2"]["user_id"]
                    p1 = db.query(User).filter(User.id == match["player1"]["user_id"]).first()
                    p2 = db.query(User).filter(User.id == match["player2"]["user_id"]).first()
                    K = 32
                    e1 = 1 / (1 + 10 ** ((p2.rating - p1.rating) / 400))
                    e2 = 1 / (1 + 10 ** ((p1.rating - p2.rating) / 400))
                    s1, s2 = (1, 0) if winner_id == p1.id else (0, 1) if winner_id == p2.id else (0.5, 0.5)
                    p1.rating += int(K * (s1 - e1))
                    p2.rating += int(K * (s2 - e2))
                    db_match = db.query(Match).filter(
                        Match.player1_id == match["player1"]["user_id"],
                        Match.player2_id == match["player2"]["user_id"],
                        Match.status == "active"
                    ).first()
                    if db_match:
                        db_match.winner_id = winner_id
                        db_match.player1_score = match["player1_score"]
                        db_match.player2_score = match["player2_score"]
                        db_match.status = "finished"
                        db_match.finished_at = datetime.now()
                    db.commit()
                    result_data = {
                        "type": "match_finished", "winner_id": winner_id,
                        "your_score": match["player1_score"] if match["player1"]["user_id"] == user_id else match[
                            "player2_score"],
                        "opponent_score": match["player2_score"] if match["player1"]["user_id"] == user_id else match[
                            "player1_score"],
                        "rating_change": int(K * (s1 - e1)) if match["player1"]["user_id"] == user_id else int(
                            K * (s2 - e2))
                    }
                    await websocket.send_json(result_data)
                    opponent_id = match["player2"]["user_id"] if match["player1"]["user_id"] == user_id else \
                        match["player1"]["user_id"]
                    if opponent_id in match_manager.connections:
                        opp_result = dict(result_data)
                        opp_result["your_score"] = match["player2_score"] if match["player2"][
                                                                                 "user_id"] == opponent_id else match[
                            "player1_score"]
                        opp_result["opponent_score"] = match["player1_score"] if match["player2"][
                                                                                     "user_id"] == opponent_id else \
                            match["player2_score"]
                        opp_result["rating_change"] = int(K * (s2 - e2)) if match["player2"][
                                                                                "user_id"] == opponent_id else int(
                            K * (s1 - e1))
                        await match_manager.connections[opponent_id].send_json(opp_result)
                    match_manager.finish_match(match_id)
    except WebSocketDisconnect:
        match_manager.disconnect(user_id)
    except Exception as e:
        await websocket.send_json({"error": str(e)})
        match_manager.disconnect(user_id)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
