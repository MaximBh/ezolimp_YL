import json
import os
import re
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import _safe_int, NON_AUTORETRY_AI_STATUSES, RECOVERABLE_AI_STATUSES
from app.utils.text import (
    normalize_text_value as _normalize_text_value,
    strip_source_lines as _strip_source_lines,
    clean_solution_explanation_text as _clean_solution_explanation_text,
    is_unavailable_solution_text as _is_unavailable_solution_text,
    is_generic_solution_explanation as _is_generic_solution_explanation,
    merge_solution_chunks as _merge_solution_chunks,
    normalize_text_for_dedupe as _normalize_text_for_dedupe,
    clean_generated_solution_text as _clean_generated_solution_text,
)
from app.config import _normalize_subject, _is_manual_answer


def classify_ai_error(exc: Exception) -> str:
    text = str(exc or "").lower()
    if "timed out" in text or "timeout" in text:
        return "timeout"
    if "connection refused" in text or "failed to establish" in text or "name or service not known" in text or "temporary failure in name resolution" in text:
        return "unavailable"
    if "invalid_api_key" in text or "invalid api key" in text or "authentication" in text or "unauthorized" in text or "forbidden" in text or "401" in text or "403" in text:
        return "invalid_api_key"
    if "rate limit" in text or "ratelimit" in text or "rate_limit" in text or "429" in text:
        return "rate_limited"
    if "model" in text and ("not found" in text or "does not exist" in text or "invalid model" in text):
        return "model_not_found"
    return "error"


def _resolve_local_llm_provider() -> str:
    provider = (os.getenv("LOCAL_LLM_PROVIDER", "").strip() or "ollama").lower()
    return "openai_compat" if provider in {"vllm", "openai", "openai_compat", "openai-compatible"} else "ollama"


def _resolve_local_llm_model(provider: str) -> str:
    explicit = os.getenv("LOCAL_LLM_MODEL", "").strip()
    if explicit:
        return explicit
    if provider == "ollama":
        return os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct").strip() or "qwen2.5:7b-instruct"
    default_model = os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-7B-Instruct").strip() or "Qwen/Qwen2.5-7B-Instruct"
    return os.getenv("LOCAL_OPENAI_MODEL", default_model).strip() or default_model


def _resolve_local_llm_max_tokens(model: str) -> int:
    raw = os.getenv("LOCAL_LLM_MAX_TOKENS", "").strip()
    if raw:
        try:
            v = int(raw)
            if v > 0:
                return max(128, min(v, 16384))
        except Exception:
            pass
    return 512 if "deepseek-r1" in str(model or "").lower() else 768


def _resolve_local_llm_timeout_sec() -> int:
    raw = os.getenv("LOCAL_LLM_TIMEOUT_SEC", "").strip()
    if raw:
        try:
            v = int(raw)
            if v > 0:
                return max(30, min(v, 900))
        except Exception:
            pass
    return 300


def _resolve_local_llm_max_continuations(model: str = "") -> int:
    raw = os.getenv("LOCAL_LLM_MAX_CONTINUATIONS", "").strip()
    if raw:
        try:
            return max(0, min(int(raw), 20))
        except Exception:
            pass
    return 2


def resolve_ai_generating_stale_sec() -> int:
    raw = os.getenv("AI_GENERATING_STALE_SEC", "").strip()
    if raw:
        try:
            v = int(raw)
            if v > 0:
                return max(90, min(v, 3600))
        except Exception:
            pass
    return 300


def _resolve_ollama_think_flag(model: str):
    raw = os.getenv("OLLAMA_THINK", "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return False if "deepseek-r1" in str(model or "").lower() else None


def _resolve_ollama_chat_url() -> str:
    explicit = os.getenv("OLLAMA_API_URL", "").strip()
    if explicit:
        return explicit
    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip() or "http://localhost:11434"
    return f"{base.rstrip('/')}/api/chat"


def _resolve_openai_compat_chat_url() -> str:
    explicit = os.getenv("LOCAL_OPENAI_API_URL", "").strip() or os.getenv("VLLM_API_URL", "").strip()
    if explicit:
        return explicit
    base = os.getenv("LOCAL_OPENAI_BASE_URL", "").strip() or os.getenv("VLLM_BASE_URL", "").strip() or "http://localhost:8000/v1"
    return f"{base.rstrip('/')}/chat/completions"


def _needs_solution_continuation(solution_text: str) -> bool:
    text = _normalize_text_value(solution_text or "")
    if not text:
        return True
    tail = text.rstrip()
    if not tail:
        return True
    if re.search(r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?(итоговый\s+ответ|ответ|final\s+answer)(?:\*\*)?\s*[:\-]", tail):
        return False
    if tail.count("**") % 2 == 1 or tail.count("```") % 2 == 1:
        return True
    if tail[-1] in ":;,(-—":
        return True
    last_line = tail.splitlines()[-1].strip()
    if not last_line:
        return True
    if re.match(r"^\s*(?:[-*]|\d+[.])\s+", last_line) and not re.search(r"[.!?…:]$", last_line):
        return True
    if re.search(r"[A-Za-zА-Яа-яЁё0-9]$", tail) and not re.search(r"[.!?…]$", tail):
        return True
    return False


def _extract_content_from_openai_response(response_data: dict) -> str:
    choices = response_data.get("choices") or []
    if not choices:
        raise RuntimeError(f"OpenAI-compatible server returned no choices: {response_data}")
    message = choices[0].get("message") or {}
    content = message.get("content", "")
    if isinstance(content, list):
        content = "\n".join(str(p.get("text") or p.get("content") or "") if isinstance(p, dict) else str(p) for p in content if p)
    return _normalize_text_value(content or "")


def _extract_content_from_ollama_response(response_data: dict) -> str:
    message = response_data.get("message") or {}

    def _flatten(field):
        value = message.get(field, "")
        if isinstance(value, list):
            return "\n".join(str(p.get("text") or p.get("content") or p.get("thinking") or "") if isinstance(p, dict) else str(p) for p in value if p)
        return str(value or "")

    content = _normalize_text_value(_flatten("content"))
    if content:
        return content
    thinking = _normalize_text_value(_flatten("thinking"))
    if thinking:
        return thinking
    legacy = response_data.get("response")
    if isinstance(legacy, list):
        legacy = "\n".join(str(p) for p in legacy)
    return _normalize_text_value(legacy or "")


_local_llm_lock = threading.Lock()
_local_llm_last_call = 0.0
_LOCAL_LLM_MIN_INTERVAL = 1.0


def _local_llm_chat_completion(provider: str, model: str, messages, temperature: float = 0.3, max_tokens: int = 1024) -> str:
    timeout_sec = _resolve_local_llm_timeout_sec()
    headers = {"Content-Type": "application/json"}
    request_url = ""

    def _request_once(payload_obj: dict) -> dict:
        result_holder = {}
        done = threading.Event()

        def _run():
            req = Request(request_url, data=json.dumps(payload_obj, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
            try:
                with urlopen(req, timeout=timeout_sec) as resp:
                    result_holder["raw"] = resp.read()
            except HTTPError as exc:
                try:
                    detail = exc.read().decode("utf-8", errors="ignore") or str(exc.reason or exc)
                except Exception:
                    detail = str(exc.reason or exc)
                result_holder["error"] = RuntimeError(f"Local LLM HTTP {exc.code}: {detail.strip()}")
            except (URLError, Exception) as exc:
                result_holder["error"] = RuntimeError(f"Local LLM request failed: {exc}")
            finally:
                done.set()

        threading.Thread(target=_run, daemon=True, name="local-llm-http").start()
        if not done.wait(timeout=timeout_sec):
            raise RuntimeError(f"Local LLM request timed out after {timeout_sec} seconds")
        if "error" in result_holder:
            raise result_holder["error"]
        try:
            return json.loads(result_holder.get("raw", b"").decode("utf-8", errors="ignore"))
        except Exception as exc:
            raise RuntimeError(f"Local LLM returned invalid JSON: {exc}") from exc

    if provider == "ollama":
        payload = {"model": model, "messages": messages, "stream": False, "options": {"temperature": temperature, "num_predict": max_tokens}}
        think_flag = _resolve_ollama_think_flag(model)
        if think_flag is not None:
            payload["think"] = think_flag
        request_url = _resolve_ollama_chat_url()
    else:
        payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        request_url = _resolve_openai_compat_chat_url()
        api_key = os.getenv("LOCAL_OPENAI_API_KEY", "").strip() or os.getenv("VLLM_API_KEY", "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

    response_data = _request_once(payload)
    if provider != "ollama":
        return _extract_content_from_openai_response(response_data)

    combined_text = _extract_content_from_ollama_response(response_data)
    done_reason = _normalize_text_value(str(response_data.get("done_reason") or "")).lower()
    budget = _resolve_local_llm_max_continuations(model)

    if budget > 0 and (done_reason == "length" or _needs_solution_continuation(combined_text)):
        cont_messages = [dict(m) for m in messages]
        if combined_text:
            cont_messages.append({"role": "assistant", "content": combined_text})
        for _ in range(budget):
            if done_reason != "length" and not _needs_solution_continuation(combined_text):
                break
            cont_messages.append({"role": "user", "content": "Продолжи решение строго с места остановки без повторов. Сначала заверши последнюю незавершённую мысль, затем добавь отдельной строкой: Итоговый ответ: ..."})
            payload["messages"] = cont_messages
            response_data = _request_once(payload)
            chunk = _extract_content_from_ollama_response(response_data)
            done_reason = _normalize_text_value(str(response_data.get("done_reason") or "")).lower()
            if not chunk:
                break
            merged = _merge_solution_chunks(combined_text, chunk)
            if _normalize_text_for_dedupe(merged) == _normalize_text_for_dedupe(combined_text):
                continue
            combined_text = merged
            cont_messages.append({"role": "assistant", "content": chunk})

    return _clean_generated_solution_text(combined_text)


def _build_ai_prompt(task) -> str:
    statement = re.sub(r"\s+", " ", _strip_source_lines(task.problem_statement or "")).strip()
    if len(statement) > 900:
        statement = f"{statement[:900]}..."
    official_solution = _normalize_text_value(getattr(task, "official_solution_text", "") or "")
    if len(official_solution) > 500:
        official_solution = f"{official_solution[:500]}..."
    metadata = json.dumps({
        "subject": _normalize_subject(task.subject or ""),
        "grade": task.grade,
        "topic": task.topic or "",
    }, ensure_ascii=False)
    prompt = (
        "Реши олимпиадную задачу строго по данным из условия.\n"
        "Нельзя придумывать отсутствующие данные.\n"
        "Если данных недостаточно, явно укажи это и не выдумывай ответ.\n\n"
        "Не повторяй одинаковые пункты, не дублируй заголовки.\n\n"
        "Формат ответа:\n"
        "1) Краткая идея решения (1-2 предложения).\n"
        "2) Пошаговое решение (3-4 коротких шага).\n"
        "3) Отдельная строка в конце: Итоговый ответ: <ответ>\n"
        "Итоговый ответ — только число, слово или последовательность без пояснений.\n"
        "Ограничение: не более 900 символов.\n\n"
        f"Метаданные задачи:\n{metadata}\n\n"
        f"Текст условия:\n{statement}"
    )
    if official_solution:
        prompt += (
            "\n\nОфициальное решение из источника (если применимо):\n"
            f"{official_solution}\n\n"
            "Если официальный текст корректный, опирайся на него и сделай краткое объяснение."
        )
    return prompt


def _extract_answer_from_solution_text(solution_text: str) -> str:
    from app.utils.answer import clean_reference_answer_text, looks_like_meaningful_answer
    text = _normalize_text_value(solution_text or "")
    if not text:
        return ""
    match = re.search(r"(?im)^\s*(?:[-*\u2022]\s*)?(?:\*\*)?final\s+answer(?:\*\*)?\s*[:\-]\s*([^\n\r]+)$", text)
    if match:
        candidate = clean_reference_answer_text(match.group(1))
        if candidate and looks_like_meaningful_answer(candidate) and not _is_manual_answer(candidate):
            return candidate
    from app.utils.answer import normalize_answer_token, normalize_compact_answer_token
    for line in reversed(text.splitlines()[-20:]):
        line = line.strip()
        m = re.match(r"^\s*(?:[-*\u2022]\s*)?(?:\*\*)?([^:\n\r]{1,80})(?:\*\*)?\s*[:\-]\s*(.+)$", line)
        if not m:
            continue
        label_norm = normalize_answer_token(m.group(1))
        candidate = clean_reference_answer_text(m.group(2))
        if not candidate or not looks_like_meaningful_answer(candidate) or _is_manual_answer(candidate):
            continue
        if "answer" not in label_norm:
            if not normalize_compact_answer_token(candidate) or len(candidate) > 160 or len(candidate.split()) > 10:
                continue
        return candidate
    return ""


def generate_solution_with_local_llm(task):
    global _local_llm_last_call
    provider = _resolve_local_llm_provider()
    model = _resolve_local_llm_model(provider)
    max_tokens = _resolve_local_llm_max_tokens(model)
    prompt = _build_ai_prompt(task)

    with _local_llm_lock:
        now = time.monotonic()
        wait = _LOCAL_LLM_MIN_INTERVAL - (now - _local_llm_last_call)
        if wait > 0:
            time.sleep(wait)
        _local_llm_last_call = time.monotonic()

    last_exc = None
    for attempt in range(3):
        try:
            solution_text = _local_llm_chat_completion(
                provider=provider, model=model,
                messages=[
                    {"role": "system", "content": (
                        "You solve school olympiad tasks. "
                        "Return a concise solution in Russian (up to 4 short steps, max 900 characters) and a final answer line. "
                        "Do not add any extra text after the final answer line. "
                        "Do not output meta-thinking about how you reason."
                    )},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3, max_tokens=max_tokens,
            )
            if not solution_text:
                raise RuntimeError(f"Local LLM ({provider}) returned empty solution")
            solution_text = _clean_generated_solution_text(solution_text)
            answer_short = _extract_answer_from_solution_text(solution_text).strip()
            return answer_short, solution_text, f"{provider}:{model}"
        except Exception as exc:
            last_exc = exc
            if any(k in str(exc).lower() for k in ("rate_limit", "rate limit", "429", "too many requests")):
                time.sleep(20 * (attempt + 1))
                continue
            break
    raise RuntimeError(str(last_exc or "Local LLM generation failed"))


def _task_solution_hash(task) -> str:
    from app.utils.attachments import attachments_from_storage, source_fragments_from_storage
    payload = {
        "problem_statement": _strip_source_lines(task.problem_statement or ""),
        "subject": _normalize_subject(task.subject or ""),
        "grade": task.grade,
        "topic": task.topic or "",
        "attachments": attachments_from_storage(task.attachments),
        "source_pdf_url": task.source_pdf_url or "",
        "source_fragments": source_fragments_from_storage(task.source_fragments),
    }
    import hashlib
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def get_or_generate_ai_solution(task, db, force: bool = False):
    expected_hash = _task_solution_hash(task)
    if not force and task.ai_solution_status == "ready" and (task.ai_solution_hash or "") == expected_hash and (task.ai_solution_full or "").strip():
        return task.ai_answer_short or "", task.ai_solution_full or "", "cache"
    try:
        answer_short, solution_full, model_name = generate_solution_with_local_llm(task)
        task.ai_answer_short = answer_short or None
        task.ai_solution_full = solution_full
        task.ai_solution_status = "ready"
        task.ai_solution_model = model_name
        task.ai_solution_error = None
        task.ai_solution_hash = expected_hash
        task.ai_solution_generated_at = datetime.utcnow()
        db.commit()
        return answer_short, solution_full, "generated"
    except Exception as exc:
        status = classify_ai_error(exc)
        task.ai_solution_status = status
        task.ai_solution_error = str(exc)[:1000]
        task.ai_solution_hash = expected_hash
        task.ai_solution_generated_at = datetime.utcnow()
        task.ai_solution_full = None
        task.ai_answer_short = None
        db.commit()
        print(f"Local LLM generation failed for task {task.id}: {exc}")
        return "", "", status


def should_generate_ai_solution(task, answer_value: str, free_ai_explanation: str, force: bool = False) -> bool:
    status = _normalize_text_value(getattr(task, "ai_solution_status", "") or "")
    if not force and status in NON_AUTORETRY_AI_STATUSES:
        return False
    norm_free = _normalize_text_value(free_ai_explanation or "")
    if norm_free and (_is_unavailable_solution_text(norm_free) or _is_generic_solution_explanation(norm_free)):
        norm_free = ""
    explanation = norm_free or _clean_solution_explanation_text(task.solution_explanation)
    return force or not norm_free or _is_manual_answer(answer_value) or not explanation or _is_generic_solution_explanation(explanation) or task.ai_solution_status in RECOVERABLE_AI_STATUSES


def is_ai_generation_stale(task) -> bool:
    if _normalize_text_value(getattr(task, "ai_solution_status", "") or "") != "generating":
        return False
    started_at = getattr(task, "ai_solution_generated_at", None)
    if not started_at:
        return True
    try:
        return (datetime.utcnow() - started_at).total_seconds() > resolve_ai_generating_stale_sec()
    except Exception:
        return False


# --- очередь ---

_jobs_lock = threading.Lock()
_jobs: set = set()
_queue: deque = deque()
_job_force: dict = {}
_active_task_id = None
_worker_started = False
_job_state: dict = {}

_final_visibility_sec = max(2, min(_safe_int(os.getenv("AI_GENERATION_NOTIFY_VISIBLE_SEC", "4"), 4) or 4, 30))
_state_limit = max(10, min(_safe_int(os.getenv("AI_GENERATION_NOTIFY_LIMIT", "40"), 40) or 40, 200))


def _datetime_to_iso(value):
    return value.isoformat() if isinstance(value, datetime) else None


def _cleanup_state_locked(now=None):
    if now is None:
        now = datetime.utcnow()
    queued_ids = set(_queue)
    to_remove = [
        tid for tid, state in _job_state.items()
        if tid != _active_task_id and tid not in queued_ids and tid not in _jobs
        and isinstance(state.get("visible_until"), datetime) and state["visible_until"] <= now
    ]
    for tid in to_remove:
        _job_state.pop(tid, None)
    if len(_job_state) <= _state_limit:
        return
    candidates = sorted(
        [(state.get("finished_at") or state.get("created_at") or datetime.min, tid)
         for tid, state in _job_state.items()
         if tid != _active_task_id and tid not in queued_ids and tid not in _jobs and str(state.get("status") or "") in ("success", "error")]
    )
    for _, tid in candidates[:len(_job_state) - _state_limit]:
        _job_state.pop(tid, None)


def _upsert_state_locked(task_id: int, status: str, message: str = "", error_text: str = "", started_at=None, finished_at=None, visible_until=None):
    now = datetime.utcnow()
    state = _job_state.get(task_id) or {"id": f"task-{task_id}", "task_id": task_id, "created_at": now}
    state.update({"status": status, "message": message or "", "error_text": error_text or "", "updated_at": now})
    if started_at is not None:
        state["started_at"] = started_at
    elif "started_at" not in state:
        state["started_at"] = None
    if finished_at is not None:
        state["finished_at"] = finished_at
    elif status in ("queued", "running"):
        state["finished_at"] = None
    if visible_until is not None:
        state["visible_until"] = visible_until
    elif status in ("queued", "running"):
        state["visible_until"] = None
    _job_state[task_id] = state
    return state


def get_ai_generation_jobs_snapshot():
    with _jobs_lock:
        now = datetime.utcnow()
        _cleanup_state_locked(now)
        queue_order = {tid: idx + 1 for idx, tid in enumerate(_queue)}
        jobs = []
        for tid, state in _job_state.items():
            status = str(state.get("status") or "")
            if tid != _active_task_id and status == "queued" and tid not in queue_order:
                continue
            pos = 0 if (tid == _active_task_id and status == "running") else (queue_order.get(tid) if status == "queued" else None)
            jobs.append({
                "id": state.get("id") or f"task-{tid}",
                "task_id": tid,
                "status": status or "queued",
                "created_at": _datetime_to_iso(state.get("created_at")),
                "started_at": _datetime_to_iso(state.get("started_at")),
                "finished_at": _datetime_to_iso(state.get("finished_at")),
                "message": state.get("message") or "",
                "error_text": state.get("error_text") or "",
                "position_in_queue": pos,
                "auto_hide_at": _datetime_to_iso(state.get("visible_until")),
            })

        def _sort_key(item):
            s = item.get("status")
            if s == "running":
                return (0, item.get("task_id") or 0)
            if s == "queued":
                return (1, item.get("position_in_queue") or 10 ** 9)
            fa = item.get("finished_at") or ""
            try:
                score = int(datetime.fromisoformat(fa).timestamp())
            except Exception:
                score = 0
            return (2, -score)

        jobs.sort(key=_sort_key)
        return {"active_task_id": _active_task_id, "running_count": 1 if _active_task_id else 0, "queue_size": len(_queue), "jobs": jobs, "updated_at": now.isoformat()}


def _finalize_job(task_id: int, success: bool, message: str, error_text: str = ""):
    global _active_task_id
    with _jobs_lock:
        now = datetime.utcnow()
        _active_task_id = None
        _jobs.discard(task_id)
        _job_force.pop(task_id, None)
        _upsert_state_locked(task_id, "success" if success else "error", message, error_text, finished_at=now, visible_until=now + timedelta(seconds=_final_visibility_sec))
        _cleanup_state_locked(now)


def _worker_loop():
    global _active_task_id
    from app.database import SessionLocal, Task
    while True:
        task_id = force = None
        with _jobs_lock:
            _cleanup_state_locked(datetime.utcnow())
            if _active_task_id is None and _queue:
                task_id = _queue.popleft()
                force = bool(_job_force.get(task_id))
                _active_task_id = task_id
                _upsert_state_locked(task_id, "running", "Идет генерация...", started_at=datetime.utcnow())
        if task_id is None:
            time.sleep(0.2)
            continue

        db = SessionLocal()
        task_local = success = None
        error_text = ""
        try:
            task_local = db.query(Task).filter(Task.id == task_id).first()
            if not task_local:
                error_text = "Задача не найдена."
            else:
                task_local.ai_solution_status = "generating"
                task_local.ai_solution_error = None
                task_local.ai_solution_generated_at = datetime.utcnow()
                db.commit()
                get_or_generate_ai_solution(task_local, db, force=force)
                db.refresh(task_local)
                success = str(task_local.ai_solution_status or "").lower() == "ready"
                if not success:
                    error_text = _normalize_text_value(task_local.ai_solution_error or "")
        except Exception as exc:
            error_text = str(exc)[:1000]
            try:
                if task_local is None:
                    task_local = db.query(Task).filter(Task.id == task_id).first()
                if task_local:
                    task_local.ai_solution_status = classify_ai_error(exc)
                    task_local.ai_solution_error = error_text
                    task_local.ai_solution_generated_at = datetime.utcnow()
                    task_local.ai_solution_full = task_local.ai_answer_short = None
                    db.commit()
            except Exception:
                pass
            print(f"Background AI generation failed for task {task_id}: {exc}")
        finally:
            db.close()

        _finalize_job(task_id, bool(success), f"Генерация для задачи #{task_id} {'успешно завершена' if success else 'завершилась с ошибкой'}.", error_text=error_text)


def queue_ai_solution_generation(task_id: int, force: bool = False) -> bool:
    global _worker_started
    should_start = False
    with _jobs_lock:
        _cleanup_state_locked(datetime.utcnow())
        if task_id in _jobs:
            if force:
                _job_force[task_id] = True
            return False
        _jobs.add(task_id)
        _job_force[task_id] = bool(force)
        _queue.append(task_id)
        _upsert_state_locked(task_id, "queued", "В очереди")
        if not _worker_started:
            _worker_started = True
            should_start = True
    if should_start:
        threading.Thread(target=_worker_loop, daemon=True, name="ai-solution-worker").start()
    return True


def is_ai_generation_job_active(task_id: int) -> bool:
    with _jobs_lock:
        return task_id in _jobs
