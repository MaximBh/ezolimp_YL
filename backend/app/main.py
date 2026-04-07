from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db, create_tables, User, Task, Solution, Match, UserStats, SessionLocal
from app.schemas import UserRegister, UserLogin, TaskCreate, UserProfileUpdate
from app.auth_middleware import get_current_user, get_admin_user
from app.pdf_parser import extract_best_task_entry
from app.pvp_manager import match_manager
from datetime import datetime, timedelta
from pathlib import Path
import json
import random
import re
import hashlib
import os
from collections import Counter
from urllib.parse import urlparse
from urllib.request import urlretrieve, Request, urlopen

# Загружаем .env.local если есть
def _load_env_file(path: Path):
    if not path.exists() or not path.is_file():
        return
    try:
        content = path.read_text(encoding="utf-8-sig", errors="ignore")
    except Exception:
        return
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        parsed_value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, parsed_value)


_seen_env_paths = set()
_search_dirs = [
    Path(__file__).resolve().parents[2],  # project root
    Path(__file__).resolve().parents[1],  # backend
    Path.cwd(),
]
for _search_dir in _search_dirs:
    for _env_name in (".env.local", ".evn.local"):
        _candidate = (_search_dir / _env_name).resolve()
        key = str(_candidate).lower()
        if key in _seen_env_paths:
            continue
        _seen_env_paths.add(key)
        _load_env_file(_candidate)

app = FastAPI(title="EzOlimp")

def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


TIME_LIMIT_BY_DIFFICULTY = {
    "easy": 30,
    "medium": 60,
    "hard": 90,
}

SUBJECT_ALIASES = {
    "математика": "математика",
    "math": "математика",
    "информатика": "информатика",
    "informatics": "информатика",
    "физика": "физика",
    "physics": "физика",
    "химия": "химия",
    "chemistry": "химия",
    "биология": "биология",
    "biology": "биология",
    "английский": "английский",
    "английский язык": "английский",
    "english": "английский",
    "русский": "русский",
    "русский язык": "русский",
    "russian": "русский",
    "обществознание": "обществознание",
    "social studies": "обществознание",
    "право": "право",
    "law": "право",
    "история": "история",
    "history": "история",
    "география": "география",
    "geography": "география",
    "экология": "экология",
    "ecology": "экология",
    "литература": "литература",
    "literature": "литература",
    "робототехника": "робототехника",
    "robotics": "робототехника",
}

OLYMPIAD_ALIASES = {
    "VSOSH": "ВСОШ",
    "ВСОШ": "ВСОШ",
}

URL_RE = re.compile(r'https?://[^\s<>"]+')
SOURCE_LINE_RE = re.compile("^\\s*(source|\u0438\u0441\u0442\u043e\u0447\u043d\u0438\u043a|official materials)\\s*:", re.IGNORECASE)
YEAR_RE = re.compile(r"(20\d{2})")
TASK_NUMBER_RE = re.compile("(?:task|\u0437\u0430\u0434\u0430\u0447\u0430)\\s*(\\d+)", re.IGNORECASE)
MANUAL_ANSWER_MARKERS = {"see editorial", "см. разбор", "см. решение", "n/a", "manual"}
MOJIBAKE_SEQ_RE = re.compile(
    r"(?:[\u0420\u0421][\u0400-\u045F\u00A0-\u00BF]){2,}|(?:[\u00D0\u00D1][\u0080-\u00BF]){2,}"
)
CYRILLIC_CORE_RE = re.compile(r"[\u0410-\u044F\u0401\u0451]")
MOJIBAKE_NOISE_RE = re.compile(r"[\u0402-\u040F\u0452-\u045F]")
GENERIC_SOLUTION_MARKERS = (
    "внимательно выписываем данные задачи",
    "выбираем подходящий метод",
    "см. итоговый вывод",
    "extract all numeric and logical constraints",
    "apply an appropriate method step by step",
    "validate the result against every condition",
    "given (short):",
    "final answer: see detailed reasoning",
)
PLACEHOLDER_SOLUTION_MARKERS = (
    "official materials",
    "see editorial",
    "\u0441\u043c. \u0440\u0435\u0448\u0435\u043d\u0438\u0435",
    "\u0441\u043c. \u0440\u0430\u0437\u0431\u043e\u0440",
)
UNAVAILABLE_SOLUTION_MARKERS = (
    "vsosh_enrich_fallback",
    "groq ai \u043d\u0435 \u0441\u043c\u043e\u0433 \u0441\u0433\u0435\u043d\u0435\u0440\u0438\u0440\u043e\u0432\u0430\u0442\u044c \u043e\u0442\u0432\u0435\u0442",
    "\u0440\u0435\u0448\u0435\u043d\u0438\u0435 \u0432\u0440\u0435\u043c\u0435\u043d\u043d\u043e \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u043e",
    "solution is temporarily unavailable",
)
RECOVERABLE_AI_STATUSES = ("", "empty", "error", "model_not_found", "no_api_key", "invalid_api_key", "rate_limited", None)

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent
CACHE_DIR = BACKEND_DIR / "cache"
PDF_SOURCE_CACHE_DIR = CACHE_DIR / "pdf_sources"
PDF_FRAGMENT_CACHE_DIR = CACHE_DIR / "pdf_fragments"
TASK_CROPS_DIR = CACHE_DIR / "task_crops"

SUPPORTED_SUBJECTS = [
    "математика",
    "информатика",
    "физика",
    "химия",
    "биология",
    "английский",
    "русский",
    "обществознание",
    "право",
    "история",
    "география",
    "экология",
    "литература",
    "робототехника",
]

BASE_SUBJECTS = ["математика", "информатика", "физика", "химия", "биология"]
NEW_SUBJECTS = [subject for subject in SUPPORTED_SUBJECTS if subject not in BASE_SUBJECTS]

MONTHS_RU_GENITIVE = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}

SUBJECT_THEMES = {
    "математика": ["арифметика", "алгебра", "логика", "геометрия", "комбинаторика", "теория чисел"],
    "информатика": ["алгоритмы", "циклы", "условия", "массивы", "графы", "логика"],
    "физика": ["механика", "электричество", "оптика", "давление", "тепловые процессы", "графики движения"],
    "химия": ["химические реакции", "растворы", "стехиометрия", "органическая химия", "массовая доля", "кислоты и основания"],
    "биология": ["клетка", "генетика", "экосистемы", "анатомия", "эволюция", "физиология"],
    "английский": ["reading comprehension", "vocabulary", "grammar", "word formation", "prepositions", "tenses"],
    "русский": ["орфография", "пунктуация", "морфология", "синтаксис", "лексика", "словообразование"],
    "обществознание": ["социальные институты", "экономика", "политика", "правовые нормы", "общественные процессы", "финансовая грамотность"],
    "право": ["конституционное право", "гражданское право", "административное право", "трудовое право", "права несовершеннолетних", "ответственность"],
    "история": ["хронология", "исторические источники", "государственные реформы", "международные отношения", "культура", "исторические личности"],
    "география": ["климат", "карты и масштабы", "природные зоны", "население", "экономическая география", "географические координаты"],
    "экология": ["экосистемы", "загрязнение среды", "переработка отходов", "устойчивое развитие", "углеродный след", "охрана природы"],
    "литература": ["анализ текста", "жанры", "литературные направления", "герои произведений", "средства выразительности", "авторская позиция"],
    "робототехника": ["датчики", "управляющие алгоритмы", "траектории", "энергопотребление", "сбор данных", "автоматизация"],
}


def _normalize_difficulty(value) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in TIME_LIMIT_BY_DIFFICULTY else "easy"


def _time_limit_by_difficulty(value) -> int:
    return TIME_LIMIT_BY_DIFFICULTY[_normalize_difficulty(value)]


def _normalize_subject(value) -> str:
    subject = _fix_mojibake_text(str(value or "")).strip()
    if not subject:
        return "\u043c\u0430\u0442\u0435\u043c\u0430\u0442\u0438\u043a\u0430"
    return SUBJECT_ALIASES.get(subject.lower(), subject)


def _extract_source_url(*texts):
    for text in texts:
        if not text:
            continue
        match = URL_RE.search(str(text))
        if match:
            return match.group(0).rstrip(".,);")
    return None


def _strip_source_lines(text: str) -> str:
    if not text:
        return ""
    fixed_text = _fix_mojibake_text(str(text))
    cleaned_lines = []
    for line in fixed_text.splitlines():
        if SOURCE_LINE_RE.match(line.strip()):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def _clean_solution_explanation_text(text: str) -> str:
    if not text:
        return ""
    fixed_text = _fix_mojibake_text(str(text))
    lines = []
    for line in fixed_text.splitlines():
        if SOURCE_LINE_RE.match(line.strip()):
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    cleaned = URL_RE.sub("", cleaned)
    return cleaned.strip(" \n:-")


def _cyrillic_score(text: str) -> int:
    return len(CYRILLIC_CORE_RE.findall(str(text or "")))


def _fix_mojibake_text(value: str) -> str:
    raw = str(value or "")
    if not raw:
        return raw

    candidates = [raw]
    for source_encoding in ("cp1251", "latin1", "cp1252"):
        try:
            fixed = raw.encode(source_encoding, errors="strict").decode("utf-8", errors="strict")
            candidates.append(fixed)
            for second_encoding in ("cp1251", "latin1"):
                try:
                    fixed_twice = fixed.encode(second_encoding, errors="strict").decode("utf-8", errors="strict")
                    candidates.append(fixed_twice)
                except Exception:
                    continue
        except Exception:
            continue

    def _score(text: str) -> int:
        mojibake_penalty = 30 if MOJIBAKE_SEQ_RE.search(text) else 0
        mojibake_noise_penalty = len(MOJIBAKE_NOISE_RE.findall(text)) * 3
        question_penalty = text.count("?") * 2
        replacement_penalty = text.count("\ufffd") * 4
        return _cyrillic_score(text) * 3 - mojibake_penalty - mojibake_noise_penalty - question_penalty - replacement_penalty

    best = max(candidates, key=_score)
    return best if _score(best) >= _score(raw) + 4 else raw


def _is_unavailable_solution_text(text: str) -> bool:
    normalized = _clean_solution_explanation_text(_fix_mojibake_text(text or "")).lower()
    if not normalized:
        return False
    return any(marker in normalized for marker in UNAVAILABLE_SOLUTION_MARKERS)


def _is_generic_solution_explanation(text: str) -> bool:
    normalized = _clean_solution_explanation_text(_fix_mojibake_text(text or "")).lower()
    if not normalized:
        return True
    if _is_unavailable_solution_text(normalized):
        return True
    if any(marker in normalized for marker in PLACEHOLDER_SOLUTION_MARKERS):
        return True
    hits = sum(1 for marker in GENERIC_SOLUTION_MARKERS if marker in normalized)
    return hits >= 2


def _normalize_text_value(value):
    return _fix_mojibake_text(str(value or "")).strip()


def _is_manual_answer(answer: str) -> bool:
    normalized = str(answer or "").strip().lower()
    return normalized in MANUAL_ANSWER_MARKERS


def _first_sentence(text: str) -> str:
    clean = _strip_source_lines(text or "")
    if not clean:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", clean, maxsplit=1)
    return parts[0].strip()


def _infer_topic(subject: str, statement: str, fallback_task_number: str = "") -> str:
    normalized_subject = _normalize_subject(subject)
    statement_lower = _strip_source_lines(statement or "").lower()
    candidate_topics = SUBJECT_THEMES.get(normalized_subject, [])

    keyword_map = {
        "граф": "графики",
        "таблиц": "табличные данные",
        "скорост": "механика",
        "раствор": "растворы",
        "клетк": "клетка",
        "пунктуац": "пунктуация",
        "хронолог": "хронология",
        "климат": "климат",
        "экосистем": "экосистемы",
        "датчик": "датчики",
        "grammar": "grammar",
        "vocabulary": "vocabulary",
    }

    for marker, topic in keyword_map.items():
        if marker in statement_lower and (not candidate_topics or topic in candidate_topics):
            return topic

    if candidate_topics:
        checksum = sum(ord(ch) for ch in statement_lower) if statement_lower else 0
        return candidate_topics[checksum % len(candidate_topics)]

    if fallback_task_number:
        return f"тема задачи {fallback_task_number}"
    return "общая тема"


def _build_default_attachment(subject: str, grade, topic: str, statement: str):
    summary = _first_sentence(statement) or "См. полный текст условия."
    if len(summary) > 180:
        summary = f"{summary[:177]}..."
    return [
        {
            "type": "table",
            "title": "Сводка условия",
            "headers": ["Параметр", "Значение"],
            "rows": [
                ["Предмет", subject or "—"],
                ["Класс", str(grade) if grade is not None else "—"],
                ["Тема", topic or "общая тема"],
                ["Ключевая информация", summary],
            ],
        }
    ]


def _normalize_attachments(raw, subject: str, grade, topic: str, statement: str):
    value = raw
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            value = []
        else:
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError:
                value = [{"type": "note", "title": "Дополнительные материалы", "content": stripped}]
    elif value is None:
        value = []

    if isinstance(value, dict):
        value = [value]

    normalized = []
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "note").strip().lower()
            title = str(item.get("title") or "").strip()
            if item_type == "table":
                headers = item.get("headers") if isinstance(item.get("headers"), list) else []
                rows = item.get("rows") if isinstance(item.get("rows"), list) else []
                normalized.append(
                    {
                        "type": "table",
                        "title": title or "Таблица",
                        "headers": [str(header) for header in headers],
                        "rows": [[str(cell) for cell in row] for row in rows if isinstance(row, list)],
                    }
                )
                continue

            if item_type == "image":
                image_url = str(item.get("image_url") or item.get("url") or "").strip()
                if image_url:
                    normalized.append(
                        {
                            "type": "image",
                            "title": title or "Иллюстрация",
                            "image_url": image_url,
                            "caption": str(item.get("caption") or "").strip(),
                        }
                    )
                continue

            content = str(item.get("content") or item.get("text") or "").strip()
            if content:
                normalized.append(
                    {
                        "type": "note",
                        "title": title or "Материалы к задаче",
                        "content": content,
                    }
                )

    if not normalized:
        normalized = _build_default_attachment(subject, grade, topic, statement)
    return normalized


def _attachments_to_storage(attachments) -> str:
    return json.dumps(attachments or [], ensure_ascii=False)


def _attachments_from_storage(raw):
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
            return value if isinstance(value, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _normalize_source_fragments(raw):
    value = raw
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            value = []
        else:
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError:
                value = []
    elif value is None:
        value = []

    if isinstance(value, dict):
        value = [value]

    normalized = []
    def _safe_float(value):
        try:
            if value is None or value == "":
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            page = _safe_int(item.get("page"), None)
            width = _safe_float(item.get("width"))
            height = _safe_float(item.get("height"))
            fragment = {
                "page": page,
                "x": _safe_float(item.get("x")),
                "y": _safe_float(item.get("y")),
                "width": width,
                "height": height,
                "order_index": _safe_int(item.get("order_index"), len(normalized) + 1),
                "unit": str(item.get("unit") or "").strip().lower() or "pt",
            }
            if page is None or width is None or height is None:
                continue
            normalized.append(fragment)
    return normalized


def _source_fragments_to_storage(fragments) -> str:
    return json.dumps(fragments or [], ensure_ascii=False)


def _source_fragments_from_storage(raw):
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
            return value if isinstance(value, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _ensure_source_pdf_attachment(attachments, source_pdf_url: str):
    source_url = str(source_pdf_url or "").strip()
    if not source_url:
        return attachments

    prepared = list(attachments or [])
    has_pdf = False
    for item in prepared:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip().lower()
        if item_type == "pdf" and str(item.get("pdf_url") or "").strip() == source_url:
            has_pdf = True
            break

    if not has_pdf:
        prepared.append(
            {
                "type": "pdf",
                "title": "Оригинал условия (PDF)",
                "pdf_url": source_url,
            }
        )
    return prepared


def _ensure_cache_dirs():
    PDF_SOURCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    PDF_FRAGMENT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    TASK_CROPS_DIR.mkdir(parents=True, exist_ok=True)


def _source_pdf_cache_path(source_url: str) -> Path:
    parsed = urlparse(source_url)
    suffix = Path(parsed.path or "").suffix.lower()
    if suffix != ".pdf":
        suffix = ".pdf"
    key = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
    return PDF_SOURCE_CACHE_DIR / f"{key}{suffix}"


def _get_source_pdf_url(task: Task) -> str:
    direct = _normalize_text_value(task.source_pdf_url or "")
    if direct:
        return direct
    for item in _attachments_from_storage(task.attachments):
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip().lower()
        if item_type != "pdf":
            continue
        url = _normalize_text_value(item.get("pdf_url") or item.get("url") or "")
        if url:
            return url
    fallback = _extract_source_url(
        getattr(task, "problem_statement", ""),
        getattr(task, "solution_explanation", ""),
        getattr(task, "official_solution_text", ""),
    )
    return _normalize_text_value(fallback or "")


def _ensure_local_pdf_path(source_url: str) -> Path:
    _ensure_cache_dirs()
    normalized_url = str(source_url or "").strip()
    if not normalized_url:
        raise RuntimeError("source_pdf_url is empty")

    if normalized_url.startswith("http://") or normalized_url.startswith("https://"):
        cache_path = _source_pdf_cache_path(normalized_url)
        if cache_path.exists() and cache_path.stat().st_size > 0:
            return cache_path

        tmp_path = cache_path.with_suffix(".tmp")
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        urlretrieve(normalized_url, tmp_path)
        tmp_size = tmp_path.stat().st_size if tmp_path.exists() else 0
        if tmp_size <= 0:
            tmp_path.unlink(missing_ok=True)
            raise RuntimeError("downloaded PDF is empty")
        tmp_path.replace(cache_path)
        return cache_path

    local_path = Path(normalized_url)
    if not local_path.is_absolute():
        local_path = PROJECT_ROOT / local_path
    if not local_path.exists():
        raise RuntimeError(f"source PDF not found: {local_path}")
    return local_path


def _normalize_visual_fragment(fragment: dict, page_width: float, page_height: float):
    x = fragment.get("x")
    y = fragment.get("y")
    width = fragment.get("width")
    height = fragment.get("height")
    unit = str(fragment.get("unit") or "pt").strip().lower()

    try:
        x = float(x)
        y = float(y)
        width = float(width)
        height = float(height)
    except (TypeError, ValueError):
        return None

    if width <= 0 or height <= 0:
        return None

    is_ratio = unit in {"ratio", "relative", "norm"} or (
        x <= 1.0 and y <= 1.0 and width <= 1.0 and height <= 1.0
    )
    if is_ratio:
        left = x
        top = y
        right = x + width
        bottom = y + height
    else:
        if page_width <= 0 or page_height <= 0:
            return None
        left = x / page_width
        top = y / page_height
        right = (x + width) / page_width
        bottom = (y + height) / page_height

    left = max(0.0, min(1.0, left))
    top = max(0.0, min(1.0, top))
    right = max(0.0, min(1.0, right))
    bottom = max(0.0, min(1.0, bottom))

    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _simplify_text_for_search(text: str) -> str:
    raw = _normalize_text_value(text or "").lower()
    return re.sub(r"[^a-zа-яё0-9]+", "", raw, flags=re.IGNORECASE)


def _infer_page_index_from_statement(pdf_doc, statement: str) -> int:
    snippet = _strip_source_lines(statement or "")
    if not snippet:
        return 0
    snippet = snippet[:220]
    anchor = _simplify_text_for_search(snippet)
    if not anchor:
        return 0

    page_count = len(pdf_doc)
    for page_index in range(page_count):
        page = pdf_doc[page_index]
        text_page = page.get_textpage()
        page_text = text_page.get_text_range() or ""
        text_page.close()
        page.close()
        normalized_page_text = _simplify_text_for_search(page_text)
        if not normalized_page_text:
            continue

        # The statement in DB can be truncated, so check short prefixes first.
        prefix_lengths = [80, 60, 40, 30, 20]
        for length in prefix_lengths:
            if len(anchor) < length:
                continue
            if anchor[:length] in normalized_page_text:
                return page_index
    return 0


def _build_fallback_fragments(task: Task, pdf_doc):
    page_count = len(pdf_doc)
    if page_count <= 0:
        return []

    if task.source_page_start and task.source_page_start > 0:
        start_page = min(task.source_page_start, page_count)
    else:
        start_page = _infer_page_index_from_statement(pdf_doc, task.problem_statement or "") + 1
        if start_page <= 0:
            start_page = 1

    end_page = start_page
    if task.source_page_end and task.source_page_end >= start_page:
        end_page = min(task.source_page_end, page_count)

    fragments = []
    order_index = 1
    for page in range(start_page, end_page + 1):
        fragments.append(
            {
                "page": page,
                "x": 0.0,
                "y": 0.0,
                "width": 1.0,
                "height": 1.0,
                "unit": "ratio",
                "order_index": order_index,
            }
        )
        order_index += 1
    return fragments


def _render_task_fragments(task: Task):
    source_url = _get_source_pdf_url(task)
    if not source_url:
        return {
            "available": False,
            "reason": "no_source_pdf",
            "images": [],
        }

    try:
        local_pdf_path = _ensure_local_pdf_path(source_url)
    except Exception as exc:
        return {
            "available": False,
            "reason": "source_pdf_unavailable",
            "error": str(exc),
            "images": [],
            "source_pdf_url": source_url,
        }

    try:
        import pypdfium2 as pdfium
    except Exception:
        return {
            "available": False,
            "reason": "pdf_renderer_not_installed",
            "images": [],
            "source_pdf_url": source_url,
        }

    try:
        pdf_doc = pdfium.PdfDocument(str(local_pdf_path))
    except Exception as exc:
        return {
            "available": False,
            "reason": "pdf_open_failed",
            "error": str(exc),
            "images": [],
            "source_pdf_url": source_url,
        }

    try:
        source_fragments = _source_fragments_from_storage(task.source_fragments)
        fragments = _normalize_source_fragments(source_fragments)
        visual_mode = "bbox" if fragments else "page_fallback"
        if not fragments:
            fragments = _build_fallback_fragments(task, pdf_doc)

        if not fragments:
            return {
                "available": False,
                "reason": "no_fragments",
                "images": [],
                "source_pdf_url": source_url,
            }

        _ensure_cache_dirs()
        images = []
        local_pdf_stats = local_pdf_path.stat()
        pdf_fingerprint = f"{local_pdf_path.resolve()}:{local_pdf_stats.st_mtime_ns}:{local_pdf_stats.st_size}"

        ordered_fragments = sorted(fragments, key=lambda item: item.get("order_index", 0))
        for fragment in ordered_fragments:
            page_num = _safe_int(fragment.get("page"), None)
            if page_num is None:
                continue
            if page_num < 1 or page_num > len(pdf_doc):
                continue
            page_index = page_num - 1
            page = pdf_doc[page_index]
            page_width, page_height = page.get_size()
            normalized_bbox = _normalize_visual_fragment(fragment, page_width, page_height)
            if not normalized_bbox:
                page.close()
                continue

            left, top, right, bottom = normalized_bbox
            render_scale = 2.2
            cache_key_payload = {
                "task_id": task.id,
                "pdf": pdf_fingerprint,
                "page": page_num,
                "bbox": [left, top, right, bottom],
                "scale": render_scale,
            }
            cache_key = hashlib.sha256(
                json.dumps(cache_key_payload, sort_keys=True).encode("utf-8")
            ).hexdigest()
            cache_path = PDF_FRAGMENT_CACHE_DIR / f"{cache_key}.webp"

            if not cache_path.exists():
                pil_img = page.render(scale=render_scale).to_pil()
                page.close()
                img_w, img_h = pil_img.size
                crop_box = (
                    int(round(left * img_w)),
                    int(round(top * img_h)),
                    int(round(right * img_w)),
                    int(round(bottom * img_h)),
                )
                cropped = pil_img.crop(crop_box)
                cropped.save(cache_path, format="WEBP", quality=90, method=6)
            else:
                page.close()

            images.append(
                {
                    "url": f"/tasks/fragments/{cache_path.name}",
                    "page": page_num,
                    "order_index": _safe_int(fragment.get("order_index"), len(images) + 1),
                }
            )

        return {
            "available": bool(images),
            "reason": "ok" if images else "render_empty",
            "visual_mode": visual_mode,
            "source_pdf_url": source_url,
            "images": images,
        }
    finally:
        pdf_doc.close()


def _task_solution_hash(task: Task) -> str:
    payload = {
        "problem_statement": _strip_source_lines(task.problem_statement or ""),
        "subject": _normalize_subject(task.subject or ""),
        "grade": task.grade,
        "topic": task.topic or "",
        "attachments": _attachments_from_storage(task.attachments),
        "source_pdf_url": task.source_pdf_url or "",
        "source_fragments": _source_fragments_from_storage(task.source_fragments),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_solution_pdf_candidates(source_pdf_url: str):
    raw_url = _normalize_text_value(source_pdf_url or "")
    if not raw_url:
        return []

    candidates = [raw_url]
    replacements = [
        ("tasks-", "sol-"),
        ("tasks_", "sol_"),
        ("/tasks/", "/solutions/"),
        ("task-", "solution-"),
        ("task_", "solution_"),
    ]
    for old, new in replacements:
        if old in raw_url:
            candidates.append(raw_url.replace(old, new))

    seen = set()
    deduped = []
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return deduped


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
            request = Request(url, method=method)
            with urlopen(request, timeout=12) as response:
                status = getattr(response, "status", 200)
                if 200 <= status < 400:
                    return True
        except Exception:
            continue
    return False


def _resolve_solution_pdf_url(task: Task):
    explicit = _normalize_text_value(getattr(task, "source_solution_pdf_url", "") or "")
    if explicit:
        return explicit
    source_pdf = _get_source_pdf_url(task)
    for candidate in _build_solution_pdf_candidates(source_pdf):
        if candidate == source_pdf:
            continue
        if _url_exists(candidate):
            return candidate
    return ""


def _extract_answer_from_official_solution(official_solution_text: str) -> str:
    clean = _normalize_text_value(official_solution_text or "")
    if not clean:
        return ""

    patterns = [
        r"(?im)^\s*итоговый\s+ответ\s*[:\-]\s*(.+)$",
        r"(?im)^\s*ответ\s*[:\-]\s*(.+)$",
        r"(?im)^\s*final\s+answer\s*[:\-]\s*(.+)$",
    ]
    for pattern in patterns:
        answer_match = re.search(pattern, clean)
        if answer_match:
            return _normalize_text_value(answer_match.group(1))
    return ""


def _enrich_task_from_vsosh_pdfs(task: Task, db: Session, force: bool = False):
    source_url = _get_source_pdf_url(task)
    if not source_url:
        return False, "no_source_pdf"

    has_full_statement = bool(_normalize_text_value(getattr(task, "full_problem_statement", "") or ""))
    has_official_solution = bool(_normalize_text_value(getattr(task, "official_solution_text", "") or ""))
    free_ai_cached = _normalize_text_value(getattr(task, "free_ai_explanation", "") or "")
    has_free_text = bool(free_ai_cached) and not _is_unavailable_solution_text(free_ai_cached)
    if not force and has_full_statement and has_official_solution and has_free_text:
        return False, "cached"

    changed = False
    _, _, task_number_raw = _parse_title_parts(task.title or "")
    task_number = _safe_int(task_number_raw, None)
    task_hint = _strip_source_lines(task.problem_statement or "")

    try:
        task_pdf_path = _ensure_local_pdf_path(source_url)
        parsed_task = extract_best_task_entry(
            task_pdf_path,
            task_number=task_number,
            statement_hint=task_hint,
        )
        if parsed_task.get("found"):
            full_statement = _normalize_text_value(parsed_task.get("full_problem_statement") or "")
            if full_statement and getattr(task, "full_problem_statement", None) != full_statement:
                task.full_problem_statement = full_statement
                changed = True

            source_page_start = _safe_int(parsed_task.get("source_page_start"), None)
            source_page_end = _safe_int(parsed_task.get("source_page_end"), None)
            if source_page_start is not None and task.source_page_start != source_page_start:
                task.source_page_start = source_page_start
                changed = True
            if source_page_end is not None and task.source_page_end != source_page_end:
                task.source_page_end = source_page_end
                changed = True

            source_fragments = _normalize_source_fragments(parsed_task.get("source_fragments"))
            if source_fragments and _source_fragments_from_storage(task.source_fragments) != source_fragments:
                task.source_fragments = _source_fragments_to_storage(source_fragments)
                changed = True
    except Exception as exc:
        if not _normalize_text_value(getattr(task, "full_problem_statement", "") or ""):
            fallback_statement = _strip_source_lines(task.problem_statement or "")
            if fallback_statement:
                task.full_problem_statement = fallback_statement
                changed = True
        if not _normalize_text_value(getattr(task, "free_ai_explanation", "") or ""):
            task.free_ai_explanation = f"Не удалось прочитать PDF условия: {_normalize_text_value(exc)}"
            changed = True

    solution_pdf_url = _resolve_solution_pdf_url(task)
    if solution_pdf_url and getattr(task, "source_solution_pdf_url", None) != solution_pdf_url:
        task.source_solution_pdf_url = solution_pdf_url
        changed = True

    if solution_pdf_url:
        try:
            solution_pdf_path = _ensure_local_pdf_path(solution_pdf_url)
            parsed_solution = extract_best_task_entry(
                solution_pdf_path,
                task_number=task_number,
                statement_hint=_normalize_text_value(getattr(task, "full_problem_statement", "") or task_hint),
            )
            if parsed_solution.get("found"):
                official_solution = _normalize_text_value(
                    parsed_solution.get("official_solution_text")
                    or parsed_solution.get("full_problem_statement")
                    or ""
                )
                if official_solution and getattr(task, "official_solution_text", None) != official_solution:
                    task.official_solution_text = official_solution
                    changed = True
        except Exception as exc:
            if not _normalize_text_value(getattr(task, "official_solution_text", "") or ""):
                task.official_solution_text = (
                    f"Официальное решение из PDF не извлечено: {_normalize_text_value(exc)}"
                )
                changed = True

    if not _normalize_text_value(getattr(task, "official_solution_text", "") or ""):
        fallback_official = _clean_solution_explanation_text(task.solution_explanation or "")
        if fallback_official and getattr(task, "official_solution_text", None) != fallback_official:
            task.official_solution_text = fallback_official
            changed = True

    if force or not _normalize_text_value(getattr(task, "free_ai_explanation", "") or "") or _is_unavailable_solution_text(getattr(task, "free_ai_explanation", "") or ""):
        free_text = _normalize_text_value(task.ai_solution_full or "")
        if not free_text:
            free_text = _clean_solution_explanation_text(task.solution_explanation or "")
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


def _extract_answer_from_solution_text(solution_text: str) -> str:
    text = str(solution_text or "").strip()
    if not text:
        return ""

    patterns = [
        r"(?im)^итоговый\s+ответ\s*[:\-]\s*(.+)$",
        r"(?im)^ответ\s*[:\-]\s*(.+)$",
        r"(?im)^final\s+answer\s*[:\-]\s*(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def _build_ai_prompt(task: Task) -> str:
    statement = _strip_source_lines(task.problem_statement or "")
    attachments = _attachments_from_storage(task.attachments)[:8]
    source_fragments = _source_fragments_from_storage(task.source_fragments)
    metadata = {
        "subject": _normalize_subject(task.subject or ""),
        "grade": task.grade,
        "topic": task.topic or "",
        "source_pdf_url": task.source_pdf_url or "",
        "source_page_start": task.source_page_start,
        "source_page_end": task.source_page_end,
        "source_fragments": source_fragments,
        "attachments": attachments,
    }

    return (
        "Реши олимпиадную задачу строго по данным из условия.\n"
        "Нельзя придумывать отсутствующие данные.\n"
        "Если данных недостаточно, явно укажи это в решении и не выдумывай ответ.\n\n"
        "Формат ответа:\n"
        "1) Краткая идея решения (1-3 предложения).\n"
        "2) Полное пошаговое решение.\n"
        "3) Отдельная строка в конце: Итоговый ответ: ...\n\n"
        f"Метаданные задачи:\n{json.dumps(metadata, ensure_ascii=False)}\n\n"
        f"Полный текст условия:\n{statement}"
    )


def _classify_ai_error(exc: Exception) -> str:
    text = str(exc or "").lower()
    if "invalid_api_key" in text or "invalid api key" in text or "authentication" in text:
        return "invalid_api_key"
    if "rate limit" in text or "ratelimit" in text or "rate_limit" in text:
        return "rate_limited"
    if "model" in text and ("not found" in text or "does not exist" in text):
        return "model_not_found"
    return "error"


# Глобальный простой rate-limiter для Groq
import threading as _threading
import time as _time
_groq_lock = _threading.Lock()
_groq_last_call = 0.0
_GROQ_MIN_INTERVAL = 3.0  # секунд между запросами (20/min запас)


def _generate_solution_with_groq(task: Task):
    global _groq_last_call
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set")
    model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant").strip() or "llama-3.1-8b-instant"
    try:
        from groq import Groq
    except Exception as exc:
        raise RuntimeError(f"groq SDK not installed: {exc}") from exc
    client = Groq(api_key=api_key)
    prompt = _build_ai_prompt(task)

    # rate-limit: ждём если прошло меньше интервала
    with _groq_lock:
        now = _time.monotonic()
        wait = _GROQ_MIN_INTERVAL - (now - _groq_last_call)
        if wait > 0:
            _time.sleep(wait)
        _groq_last_call = _time.monotonic()

    last_exc = None
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "Ты решаешь школьные олимпиадные задачи. Давай чёткие пошаговые решения на русском языке."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=1024,
            )
            solution_text = _normalize_text_value(response.choices[0].message.content or "")
            if not solution_text:
                raise RuntimeError("Groq returned empty solution")
            answer_short = _extract_answer_from_solution_text(solution_text).strip()
            return answer_short, solution_text, model
        except Exception as exc:
            last_exc = exc
            err = str(exc).lower()
            if "rate_limit" in err or "rate limit" in err or "429" in err:
                _time.sleep(20 * (attempt + 1))
                continue
            break
    raise RuntimeError(str(last_exc or "Groq generation failed"))


def _get_or_generate_ai_solution(task: Task, db: Session, force: bool = False):
    expected_hash = _task_solution_hash(task)
    has_cache = (
        task.ai_solution_status == "ready"
        and (task.ai_solution_hash or "") == expected_hash
        and bool((task.ai_solution_full or "").strip())
    )
    if has_cache and not force:
        return task.ai_answer_short or "", task.ai_solution_full or "", "cache"

    if not os.getenv("GROQ_API_KEY", "").strip():
        task.ai_solution_status = "no_api_key"
        task.ai_solution_error = "GROQ_API_KEY is not set"
        task.ai_solution_hash = expected_hash
        task.ai_solution_full = None
        task.ai_answer_short = None
        db.commit()
        return "", "", "no_api_key"

    try:
        answer_short, solution_full, model_name = _generate_solution_with_groq(task)
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
        status = _classify_ai_error(exc)
        task.ai_solution_status = status
        task.ai_solution_error = str(exc)[:1000]
        task.ai_solution_hash = expected_hash
        task.ai_solution_generated_at = datetime.utcnow()
        task.ai_solution_full = None
        task.ai_answer_short = None
        db.commit()
        print(f"Groq generation failed for task {task.id}: {exc}")
        return "", "", status


def _infer_answer_from_statement(statement: str):
    clean = _strip_source_lines(statement or "")
    if not clean:
        return None

    winter_match = re.search(r"первый зимний день\s*1\s*декабря.*?дат[ау]\s*(\d+)\s*дня\s*зимы", clean, re.IGNORECASE | re.DOTALL)
    if winter_match:
        day_number = _safe_int(winter_match.group(1), None)
        if day_number and day_number >= 1:
            date_value = datetime(datetime.now().year, 12, 1) + timedelta(days=day_number - 1)
            month = MONTHS_RU_GENITIVE.get(date_value.month, "")
            return f"{date_value.day} {month}".strip()

    sum_match = re.search(r"сумм[ауы].*?(\d+)\s*[+]\s*(\d+)", clean, re.IGNORECASE)
    if sum_match:
        left = _safe_int(sum_match.group(1), 0)
        right = _safe_int(sum_match.group(2), 0)
        return str(left + right)

    return None


def _generate_fallback_solution(statement: str, subject: str, topic: str, answer: str, failure_reason: str = ""):
    cleaned_statement = _strip_source_lines(statement or "")
    inferred_answer = _infer_answer_from_statement(cleaned_statement)
    final_answer = _normalize_text_value(answer)
    if _is_manual_answer(final_answer):
        final_answer = inferred_answer or ""
    if not final_answer:
        final_answer = inferred_answer or ""

    short_statement = cleaned_statement.strip()
    if len(short_statement) > 700:
        short_statement = f"{short_statement[:700]}..."

    subject_part = subject or "не указан"
    topic_part = topic or "не указана"
    reason_part = _normalize_text_value(failure_reason or "")

    lines = [
        "Решение временно недоступно. Groq AI не смог сгенерировать ответ.",
        f"Предмет: {subject_part}. Тема: {topic_part}.",
    ]
    if reason_part:
        lines.append(f"Причина: {reason_part}")
    if short_statement:
        lines.append(f"Фрагмент условия: {short_statement}")

    if final_answer:
        lines.append(f"Итоговый ответ: {final_answer}")
    else:
        lines.append(
            "Итоговый ответ недоступен: для точного решения нужен рабочий Groq API и полный текст условия."
        )
    return "\n".join(lines)

def _task_identity_key(raw_title: str, subject: str, grade, problem_statement: str = ""):
    olympiad, year, task_number = _parse_title_parts(raw_title)
    normalized_subject = _normalize_subject(subject).lower()
    grade_part = "" if grade is None else str(grade)
    normalized_statement = re.sub(r"\s+", " ", _strip_source_lines(problem_statement or "").strip().lower())
    statement_hash = hashlib.sha1(normalized_statement.encode("utf-8")).hexdigest()[:12] if normalized_statement else ""
    if year and task_number:
        base = f"{olympiad.lower()}|{year}|{normalized_subject}|{grade_part}|{task_number}"
        return f"{base}|{statement_hash}" if statement_hash else base

    normalized_title = re.sub(r"\s+", " ", str(raw_title or "").strip().lower())
    base = f"{normalized_subject}|{grade_part}|{normalized_title}"
    return f"{base}|{statement_hash}" if statement_hash else base


def _build_generated_subject_task(subject: str, grade: int, local_task_number: int, year: int):
    base_value = grade * 10 + local_task_number
    topic = SUBJECT_THEMES.get(subject, ["общая тема"])[(local_task_number - 1) % len(SUBJECT_THEMES.get(subject, ["общая тема"]))]

    if subject == "английский":
        known_words = 45 + base_value
        new_words = 8 + (local_task_number % 6)
        statement = (
            "Прочитайте условие полностью.\n"
            f"На уроке английского ученики разобрали текст по теме «{topic}». "
            f"В тексте уже знакомы {known_words} слов, а также добавили {new_words} новых слов.\n"
            "Сколько слов нужно повторить всего после урока?"
        )
        answer = str(known_words + new_words)
    elif subject == "русский":
        words_total = 18 + local_task_number
        punctuation_marks = 3 + (grade % 4)
        statement = (
            "Прочитайте условие полностью.\n"
            f"На разборе темы «{topic}» ученики анализировали предложение из {words_total} слов "
            f"и нашли {punctuation_marks} пунктуационных конструкций.\n"
            "Сколько объектов разбора получилось всего (слова + конструкции)?"
        )
        answer = str(words_total + punctuation_marks)
    elif subject == "обществознание":
        family_budget = 70 + base_value
        transport = 10 + (local_task_number % 8)
        statement = (
            "Прочитайте условие полностью.\n"
            f"В задаче по теме «{topic}» рассматривается семейный бюджет: {family_budget} единиц на обязательные расходы "
            f"и {transport} единиц на транспорт.\n"
            "Каков общий объём обязательных расходов?"
        )
        answer = str(family_budget + transport)
    elif subject == "право":
        rights_cases = 12 + local_task_number
        duties_cases = 7 + (grade % 5)
        statement = (
            "Прочитайте условие полностью.\n"
            f"На занятии по теме «{topic}» разобрали {rights_cases} примеров прав и {duties_cases} примеров обязанностей.\n"
            "Сколько всего правовых ситуаций рассмотрели?"
        )
        answer = str(rights_cases + duties_cases)
    elif subject == "история":
        event_a = 900 + base_value
        event_b = event_a + 15 + (local_task_number % 9)
        statement = (
            "Прочитайте условие полностью.\n"
            f"По теме «{topic}» заданы даты двух событий: {event_a} год и {event_b} год.\n"
            "На сколько лет второе событие позже первого?"
        )
        answer = str(event_b - event_a)
    elif subject == "география":
        city_a = 12 + (grade % 6) + local_task_number
        city_b = 8 + (local_task_number % 7)
        city_c = 10 + (grade % 5)
        statement = (
            "Прочитайте условие полностью.\n"
            f"По теме «{topic}» известны средние температуры трёх городов: {city_a}°C, {city_b}°C и {city_c}°C.\n"
            "Найдите среднюю температуру трёх городов."
        )
        answer = f"{(city_a + city_b + city_c) / 3:.1f}"
    elif subject == "экология":
        emissions_before = 140 + base_value
        emissions_after = emissions_before - (10 + (local_task_number % 6))
        statement = (
            "Прочитайте условие полностью.\n"
            f"В задаче по теме «{topic}» выбросы до проекта составили {emissions_before} единиц, "
            f"а после проекта — {emissions_after} единиц.\n"
            "На сколько единиц удалось снизить выбросы?"
        )
        answer = str(emissions_before - emissions_after)
    elif subject == "литература":
        citations = 20 + local_task_number
        analysis_points = 5 + (grade % 6)
        statement = (
            "Прочитайте условие полностью.\n"
            f"На семинаре по теме «{topic}» ученики подготовили {citations} цитат и {analysis_points} тезисов анализа.\n"
            "Сколько элементов литературного разбора получилось всего?"
        )
        answer = str(citations + analysis_points)
    else:  # робототехника
        route_a = 35 + base_value
        route_b = 18 + (local_task_number % 10)
        statement = (
            "Прочитайте условие полностью.\n"
            f"В проекте по теме «{topic}» робот прошёл {route_a} метров в первом тесте и {route_b} метров во втором.\n"
            "Какой общий путь прошёл робот?"
        )
        answer = str(route_a + route_b)

    attachments = [
        {
            "type": "table",
            "title": "Данные к задаче",
            "headers": ["Поле", "Значение"],
            "rows": [
                ["Предмет", subject],
                ["Класс", str(grade)],
                ["Тема", topic],
                ["Год варианта", str(year)],
                ["Номер задачи", str(local_task_number)],
            ],
        }
    ]

    return {
        "title": f"VSOSH {year} {subject} grade {grade} task {local_task_number}",
        "problem_statement": statement,
        "answer": answer,
        "subject": subject,
        "grade": grade,
        "difficulty": "easy" if local_task_number <= 7 else ("medium" if local_task_number <= 14 else "hard"),
        "points": 8 if local_task_number <= 7 else (10 if local_task_number <= 14 else 12),
        "solution_explanation": (
            "Решение (сгенерировано ChatGPT):\n"
            "1. Выпишите все числа из условия и определите требуемую операцию.\n"
            "2. Выполните вычисление и проверьте единицы измерения.\n"
            f"Ответ: {answer}."
        ),
        "topic": topic,
        "tags": "vsosh,generated-task",
        "attachments": attachments,
    }


def _augment_tasks_with_new_subjects(raw_tasks):
    prepared = [dict(item) for item in raw_tasks if isinstance(item, dict)]
    if not prepared:
        return prepared

    subject_counter = Counter(_normalize_subject(item.get("subject")) for item in prepared)
    target_per_subject = max(subject_counter.values()) if subject_counter else 0
    if target_per_subject <= 0:
        return prepared

    for subject in NEW_SUBJECTS:
        existing = subject_counter.get(subject, 0)
        if existing >= target_per_subject:
            continue

        for index in range(existing, target_per_subject):
            grade = 5 + ((index // 20) % 7)
            local_task_number = (index % 20) + 1
            year = 2025 if local_task_number <= 10 else 2024
            prepared.append(_build_generated_subject_task(subject, grade, local_task_number, year))
        subject_counter[subject] = target_per_subject

    return prepared


def _normalize_olympiad_name(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "\u041e\u043b\u0438\u043c\u043f\u0438\u0430\u0434\u0430"
    return OLYMPIAD_ALIASES.get(raw.upper(), raw)


def _parse_title_parts(raw_title: str):
    title = str(raw_title or "").strip()
    year_match = YEAR_RE.search(title)
    task_match = TASK_NUMBER_RE.search(title)

    year = year_match.group(1) if year_match else ""
    task_number = task_match.group(1) if task_match else ""

    if year_match and year_match.start() > 0:
        olympiad_raw = title[:year_match.start()].strip()
    else:
        olympiad_raw = title.split()[0] if title else ""

    olympiad = _normalize_olympiad_name(olympiad_raw)
    return olympiad, year, task_number


def _needs_standard_title(raw_title: str) -> bool:
    title = str(raw_title or "").strip().lower()
    if not title:
        return True
    return any(marker in title for marker in ("vsosh", "grade", "task"))


def _build_task_title(raw_title: str, subject: str, grade, topic: str = None, force: bool = False) -> str:
    title = str(raw_title or "").strip()
    if title and not force and not _needs_standard_title(title):
        return title

    olympiad, year, task_number = _parse_title_parts(title)
    year_value = year or str(datetime.now().year)
    grade_value = f"{grade}" if grade is not None else "\u0431\u0435\u0437"

    topic_value = str(topic or "").strip()
    if topic_value.upper() == olympiad.upper():
        topic_value = ""
    if not topic_value:
        topic_value = f"\u0437\u0430\u0434\u0430\u0447\u0430 {task_number}" if task_number else "\u043e\u0431\u0449\u0430\u044f \u0442\u0435\u043c\u0430"

    return f"{olympiad} {year_value} {grade_value} \u043a\u043b\u0430\u0441\u0441 {subject} {topic_value}".strip()


def _synthetic_subjects_enabled() -> bool:
    flag = str(os.getenv("ENABLE_SYNTHETIC_SUBJECTS", "")).strip().lower()
    return flag in {"1", "true", "yes", "on"}


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
    db = SessionLocal()
    try:
        columns = db.execute(text("PRAGMA table_info(tasks)")).fetchall()
        column_names = {col[1] for col in columns}
        if "grade" not in column_names:
            db.execute(text("ALTER TABLE tasks ADD COLUMN grade INTEGER"))
            print("Added tasks.grade column")
        if "attachments" not in column_names:
            db.execute(text("ALTER TABLE tasks ADD COLUMN attachments TEXT"))
            print("Added tasks.attachments column")
        if "ai_answer_short" not in column_names:
            db.execute(text("ALTER TABLE tasks ADD COLUMN ai_answer_short TEXT"))
            print("Added tasks.ai_answer_short column")
        if "ai_solution_full" not in column_names:
            db.execute(text("ALTER TABLE tasks ADD COLUMN ai_solution_full TEXT"))
            print("Added tasks.ai_solution_full column")
        if "ai_solution_status" not in column_names:
            db.execute(text("ALTER TABLE tasks ADD COLUMN ai_solution_status VARCHAR(32)"))
            print("Added tasks.ai_solution_status column")
        if "ai_solution_model" not in column_names:
            db.execute(text("ALTER TABLE tasks ADD COLUMN ai_solution_model VARCHAR(64)"))
            print("Added tasks.ai_solution_model column")
        if "ai_solution_error" not in column_names:
            db.execute(text("ALTER TABLE tasks ADD COLUMN ai_solution_error TEXT"))
            print("Added tasks.ai_solution_error column")
        if "ai_solution_hash" not in column_names:
            db.execute(text("ALTER TABLE tasks ADD COLUMN ai_solution_hash VARCHAR(64)"))
            print("Added tasks.ai_solution_hash column")
        if "ai_solution_generated_at" not in column_names:
            db.execute(text("ALTER TABLE tasks ADD COLUMN ai_solution_generated_at DATETIME"))
            print("Added tasks.ai_solution_generated_at column")
        if "source_pdf_url" not in column_names:
            db.execute(text("ALTER TABLE tasks ADD COLUMN source_pdf_url TEXT"))
            print("Added tasks.source_pdf_url column")
        if "source_page_start" not in column_names:
            db.execute(text("ALTER TABLE tasks ADD COLUMN source_page_start INTEGER"))
            print("Added tasks.source_page_start column")
        if "source_page_end" not in column_names:
            db.execute(text("ALTER TABLE tasks ADD COLUMN source_page_end INTEGER"))
            print("Added tasks.source_page_end column")
        if "source_fragments" not in column_names:
            db.execute(text("ALTER TABLE tasks ADD COLUMN source_fragments TEXT"))
            print("Added tasks.source_fragments column")
        if "source_solution_pdf_url" not in column_names:
            db.execute(text("ALTER TABLE tasks ADD COLUMN source_solution_pdf_url TEXT"))
            print("Added tasks.source_solution_pdf_url column")
        if "full_problem_statement" not in column_names:
            db.execute(text("ALTER TABLE tasks ADD COLUMN full_problem_statement TEXT"))
            print("Added tasks.full_problem_statement column")
        if "official_solution_text" not in column_names:
            db.execute(text("ALTER TABLE tasks ADD COLUMN official_solution_text TEXT"))
            print("Added tasks.official_solution_text column")
        if "free_ai_explanation" not in column_names:
            db.execute(text("ALTER TABLE tasks ADD COLUMN free_ai_explanation TEXT"))
            print("Added tasks.free_ai_explanation column")
        if "free_ai_status" not in column_names:
            db.execute(text("ALTER TABLE tasks ADD COLUMN free_ai_status VARCHAR(32)"))
            print("Added tasks.free_ai_status column")
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"Failed to ensure tasks schema columns: {exc}")
    finally:
        db.close()


def import_tasks_from_json():
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

        existing_tasks = db.query(Task).all()
        index = {}
        duplicate_existing_tasks = []
        for task in existing_tasks:
            if task.created_by is not None:
                continue
            identity = _task_identity_key(task.title, task.subject, task.grade, task.problem_statement)
            if identity in index:
                duplicate_existing_tasks.append(task)
                continue
            index[identity] = task

        inserted = 0
        updated = 0
        deleted = 0
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

            source_pdf_url = _normalize_text_value(
                task_data.get("source_pdf_url")
                or task_data.get("source_url")
                or task_data.get("source")
                or _extract_source_url(
                    statement_raw,
                    task_data.get("solution_explanation"),
                    task_data.get("official_solution_text"),
                )
            )
            source_page_start = _safe_int(task_data.get("source_page_start"), None)
            source_page_end = _safe_int(task_data.get("source_page_end"), None)
            source_fragments = _normalize_source_fragments(task_data.get("source_fragments"))
            source_solution_pdf_url = _normalize_text_value(task_data.get("source_solution_pdf_url"))
            full_problem_statement = _normalize_text_value(task_data.get("full_problem_statement"))
            official_solution_text = _normalize_text_value(task_data.get("official_solution_text"))
            free_ai_explanation = _normalize_text_value(task_data.get("free_ai_explanation"))
            free_ai_status = _normalize_text_value(task_data.get("free_ai_status"))
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

            attachments = _normalize_attachments(
                task_data.get("attachments"),
                subject=subject,
                grade=grade,
                topic=topic_value,
                statement=statement,
            )
            attachments = _ensure_source_pdf_attachment(attachments, source_pdf_url)

            payload_data = {
                "title": _build_task_title(title_raw, subject, grade, topic_value, force=True),
                "problem_statement": statement,
                "answer": answer,
                "subject": subject,
                "grade": grade,
                "difficulty": difficulty,
                "points": _safe_int(task_data.get("points"), 10),
                "input_format": task_data.get("input_format"),
                "output_format": task_data.get("output_format"),
                "examples": task_data.get("examples"),
                "solution_explanation": explanation or None,
                "topic": topic_value,
                "tags": task_data.get("tags"),
                "attachments": _attachments_to_storage(attachments),
                "source_pdf_url": source_pdf_url or None,
                "source_solution_pdf_url": source_solution_pdf_url or None,
                "source_page_start": source_page_start,
                "source_page_end": source_page_end,
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

        for duplicate in duplicate_existing_tasks:
            db.delete(duplicate)
            deleted += 1

        all_tasks = db.query(Task).all()
        for task in all_tasks:
            if task.created_by is not None:
                continue
            identity = _task_identity_key(task.title, task.subject, task.grade, task.problem_statement)
            if identity not in payload_identities:
                db.delete(task)
                deleted += 1

        if inserted > 0 or updated > 0 or deleted > 0:
            db.commit()
            print(f"Synced tasks from {tasks_file}: inserted={inserted}, updated={updated}, deleted={deleted}")

        return inserted + updated
    except Exception as exc:
        db.rollback()
        print(f"Failed to import tasks from tasks.json: {exc}")
        return 0
    finally:
        db.close()


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
    import_tasks_from_json()

# Основной хендлер.
@app.get("/")
def root():
    return {"message": "Все ворк"}

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
        result = []
        for task in tasks:
            result.append({
                "id": task.id,
                "title": _build_task_title(task.title, _normalize_subject(task.subject), task.grade, task.topic),
                "problem_statement": _strip_source_lines(task.problem_statement or ""),
                "input_format": task.input_format,
                "output_format": task.output_format,
                "examples": task.examples,
                "solution_explanation": _clean_solution_explanation_text(task.solution_explanation),
                "difficulty": _normalize_difficulty(task.difficulty),
                "subject": _normalize_subject(task.subject),
                "grade": task.grade,
                "topic": task.topic,
                "tags": task.tags,
                "attachments": _attachments_from_storage(task.attachments),
                "source_pdf_url": task.source_pdf_url,
                "source_page_start": task.source_page_start,
                "source_page_end": task.source_page_end,
                "source_fragments": _source_fragments_from_storage(task.source_fragments),
                "ai_solution_status": task.ai_solution_status,
                "ai_solution_error": task.ai_solution_error,
                "points": task.points,
                "time_limit": _time_limit_by_difficulty(task.difficulty)
            })
        return {"tasks": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при получении задач")

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
def update_me(profile_data: UserProfileUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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
            
            date_key = solution.submitted_at.strftime("%Y-%m-%d") if solution.submitted_at else datetime.now().strftime("%Y-%m-%d")
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
        best_streak     = stats.best_streak     if stats else 0
        total_points    = stats.total_points    if stats else 0
        pvp_wins        = sum(1 for m in matches if m.winner_id == user_id)
        pvp_total       = len(matches)
        ALL_ACHIEVEMENTS = [
            {"id": "first_solve",   "title": "\u041f\u0435\u0440\u0432\u043e\u0435 \u0440\u0435\u0448\u0435\u043d\u0438\u0435",  "description": "\u0420\u0435\u0448\u0438 \u043f\u0435\u0440\u0432\u0443\u044e \u0437\u0430\u0434\u0430\u0447\u0443",       "color": "yellow", "emoji": "\u2b50",   "check": correct_answers >= 1},
            {"id": "solver_5",      "title": "\u041d\u0430\u0447\u0438\u043d\u0430\u044e\u0449\u0438\u0439",     "description": "5 \u043f\u0440\u0430\u0432\u0438\u043b\u044c\u043d\u044b\u0445 \u043e\u0442\u0432\u0435\u0442\u043e\u0432",     "color": "blue",   "emoji": "\ud83d\udcda",  "check": correct_answers >= 5},
            {"id": "solver_10",     "title": "\u041d\u043e\u0432\u0438\u0447\u043e\u043a",         "description": "10 \u043f\u0440\u0430\u0432\u0438\u043b\u044c\u043d\u044b\u0445 \u043e\u0442\u0432\u0435\u0442\u043e\u0432",    "color": "blue",   "emoji": "\ud83c\udfc5",  "check": correct_answers >= 10},
            {"id": "solver_25",     "title": "\u041f\u0440\u043e\u0434\u0432\u0438\u043d\u0443\u0442\u044b\u0439",     "description": "25 \u043f\u0440\u0430\u0432\u0438\u043b\u044c\u043d\u044b\u0445 \u043e\u0442\u0432\u0435\u0442\u043e\u0432",    "color": "purple", "emoji": "\ud83d\udd2e",  "check": correct_answers >= 25},
            {"id": "solver_50",     "title": "\u041e\u043f\u044b\u0442\u043d\u044b\u0439",         "description": "50 \u043f\u0440\u0430\u0432\u0438\u043b\u044c\u043d\u044b\u0445 \u043e\u0442\u0432\u0435\u0442\u043e\u0432",    "color": "purple", "emoji": "\ud83e\udd47",  "check": correct_answers >= 50},
            {"id": "solver_100",    "title": "\u041c\u0430\u0441\u0442\u0435\u0440",           "description": "100 \u043f\u0440\u0430\u0432\u0438\u043b\u044c\u043d\u044b\u0445 \u043e\u0442\u0432\u0435\u0442\u043e\u0432",   "color": "orange", "emoji": "\ud83d\udc51",  "check": correct_answers >= 100},
            {"id": "solver_250",    "title": "\u041b\u0435\u0433\u0435\u043d\u0434\u0430",          "description": "250 \u043f\u0440\u0430\u0432\u0438\u043b\u044c\u043d\u044b\u0445 \u043e\u0442\u0432\u0435\u0442\u043e\u0432",   "color": "orange", "emoji": "\ud83d\udd25",  "check": correct_answers >= 250},
            {"id": "streak_3",      "title": "\u0421\u0435\u0440\u0438\u044f x3",        "description": "3 \u0437\u0430\u0434\u0430\u0447\u0438 \u043f\u043e\u0434\u0440\u044f\u0434",          "color": "red",    "emoji": "\u26a1",   "check": best_streak >= 3},
            {"id": "streak_5",      "title": "\u0421\u0435\u0440\u0438\u044f x5",        "description": "5 \u0437\u0430\u0434\u0430\u0447 \u043f\u043e\u0434\u0440\u044f\u0434",           "color": "red",    "emoji": "\ud83d\udd25",  "check": best_streak >= 5},
            {"id": "streak_10",     "title": "\u0421\u0435\u0440\u0438\u044f x10",       "description": "10 \u0437\u0430\u0434\u0430\u0447 \u043f\u043e\u0434\u0440\u044f\u0434",          "color": "red",    "emoji": "\ud83c\udf29\ufe0f", "check": best_streak >= 10},
            {"id": "points_50",     "title": "\u041a\u043e\u043f\u0438\u043b\u043a\u0430",         "description": "50 \u043e\u0447\u043a\u043e\u0432",                "color": "yellow", "emoji": "\ud83d\udcb0",  "check": total_points >= 50},
            {"id": "points_100",    "title": "\u041a\u043e\u043b\u043b\u0435\u043a\u0446\u0438\u043e\u043d\u0435\u0440",    "description": "100 \u043e\u0447\u043a\u043e\u0432",               "color": "yellow", "emoji": "\ud83d\udcb8",  "check": total_points >= 100},
            {"id": "points_500",    "title": "\u0411\u043e\u0433\u0430\u0447",           "description": "500 \u043e\u0447\u043a\u043e\u0432",               "color": "orange", "emoji": "\ud83d\udcb3",  "check": total_points >= 500},
            {"id": "first_pvp_win", "title": "\u041f\u0435\u0440\u0432\u0430\u044f \u043f\u043e\u0431\u0435\u0434\u0430",   "description": "\u041f\u043e\u0431\u0435\u0434\u0438 \u0432 PvP \u043c\u0430\u0442\u0447\u0435",       "color": "green",  "emoji": "\ud83c\udfc6",  "check": pvp_wins >= 1},
            {"id": "pvp_5",         "title": "\u0411\u043e\u0435\u0446",            "description": "5 \u043f\u043e\u0431\u0435\u0434 \u0432 PvP",             "color": "green",  "emoji": "\u2694\ufe0f",   "check": pvp_wins >= 5},
            {"id": "pvp_master",    "title": "\u041c\u0430\u0441\u0442\u0435\u0440 PvP",      "description": "10 \u043f\u043e\u0431\u0435\u0434 \u0432 PvP",            "color": "purple", "emoji": "\ud83d\udc8e",  "check": pvp_wins >= 10},
            {"id": "pvp_played_10", "title": "\u0410\u043a\u0442\u0438\u0432\u043d\u044b\u0439 \u0438\u0433\u0440\u043e\u043a", "description": "10 PvP \u043c\u0430\u0442\u0447\u0435\u0439",             "color": "blue",   "emoji": "\ud83c\udfae",  "check": pvp_total >= 10},
        ]
        result = [
            {"id": a["id"], "title": a["title"], "description": a["description"],
             "color": a["color"], "emoji": a["emoji"], "unlocked": bool(a["check"])}
            for a in ALL_ACHIEVEMENTS
        ]
        unlocked = [a for a in result if a["unlocked"]]
        locked   = [a for a in result if not a["unlocked"]]
        return {"achievements": unlocked + locked, "total_unlocked": len(unlocked), "total_available": len(ALL_ACHIEVEMENTS)}
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
                    "task_title": _build_task_title(task.title, _normalize_subject(task.subject), task.grade, task.topic),
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


@app.post("/auth/make_admin")
def make_admin(login_data: UserLogin, db: Session = Depends(get_db)):
    try:
        if login_data.password != "88005553535A":
            raise HTTPException(status_code=403, detail="Неверный секретный код")
        user = db.query(User).filter(User.username == login_data.username).first()
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        user.is_admin = True
        db.commit()
        return {"message": "Права администратора получены", "user_id": user.id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при назначении админом")


@app.get("/admin/users")
def admin_get_users(current_user: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    users = db.query(User).all()
    return {"users": [{"id": u.id, "username": u.username, "email": u.email, "rating": u.rating, "is_admin": u.is_admin} for u in users]}


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
def filter_tasks(subject: str = None, grade: int = None, difficulty: str = None, db: Session = Depends(get_db)):
    try:
        query = db.query(Task)
        if subject:
            query = query.filter(Task.subject == _normalize_subject(subject))
        if grade is not None:
            query = query.filter(Task.grade == grade)
        if difficulty:
            query = query.filter(Task.difficulty == _normalize_difficulty(difficulty))
        tasks = query.all()
        result = [{
            "id": t.id,
            "title": _build_task_title(t.title, _normalize_subject(t.subject), t.grade, t.topic),
            "problem_statement": _strip_source_lines(t.problem_statement or ""),
            "difficulty": _normalize_difficulty(t.difficulty), "subject": _normalize_subject(t.subject),
            "grade": t.grade, "topic": t.topic, "tags": t.tags,
            "attachments": _attachments_from_storage(t.attachments),
            "source_pdf_url": t.source_pdf_url, "source_page_start": t.source_page_start,
            "source_page_end": t.source_page_end,
            "source_fragments": _source_fragments_from_storage(t.source_fragments),
            "ai_solution_status": t.ai_solution_status, "points": t.points,
            "time_limit": _time_limit_by_difficulty(t.difficulty)
        } for t in tasks]
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

@app.get("/tasks/{task_id}/solution")
def get_task_solution(task_id: int, enrich: bool = True, force_regenerate: bool = False,
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
        if _is_unavailable_solution_text(free_ai_explanation):
            free_ai_explanation = ""
            if getattr(task, "free_ai_explanation", None):
                task.free_ai_explanation = None
                task.free_ai_status = "empty"
                db.commit()
        answer_value = _extract_answer_from_official_solution(official_solution_text) or _normalize_text_value(task.answer)
        explanation = free_ai_explanation or _clean_solution_explanation_text(task.solution_explanation)
        needs_ai = (
            force_regenerate
            or _is_manual_answer(answer_value)
            or not explanation
            or _is_generic_solution_explanation(explanation)
            or task.ai_solution_status in RECOVERABLE_AI_STATUSES
        )
        ai_source = "not_needed"
        if needs_ai:
            ai_answer, ai_solution, ai_source = _get_or_generate_ai_solution(task, db, force=force_regenerate)
            if ai_solution:
                explanation = ai_solution
                free_ai_explanation = ai_solution
            if _is_manual_answer(answer_value) and ai_answer:
                answer_value = ai_answer
        if _is_generic_solution_explanation(explanation):
            explanation = ""
        if not explanation:
            source_pdf_url = _get_source_pdf_url(task)
            source_solution_pdf_url = _normalize_text_value(getattr(task, "source_solution_pdf_url", "") or "")
            if source_pdf_url:
                explanation = (
                    "\u041e\u0444\u0438\u0446\u0438\u0430\u043b\u044c\u043d\u043e\u0435 \u0440\u0435\u0448\u0435\u043d\u0438\u0435 "
                    "\u0412\u0421\u041e\u0428 \u043f\u043e\u043a\u0430 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e "
                    "\u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438. "
                    "\u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 PDF-\u0438\u0441\u0442\u043e\u0447\u043d\u0438\u043a\u0438 "
                    "\u0437\u0430\u0434\u0430\u0447\u0438."
                )
                if source_solution_pdf_url:
                    explanation = f"{explanation} PDF: {source_solution_pdf_url}"
            else:
                explanation = _generate_fallback_solution(
                    getattr(task, "full_problem_statement", "") or task.problem_statement or "", _normalize_subject(task.subject),
                    task.topic or "", answer_value or task.answer or "",
                    task.ai_solution_error or task.ai_solution_status or ai_source)
        if not answer_value:
            answer_value = _extract_answer_from_solution_text(explanation) or "см. решение"
        return {
            "answer": answer_value, "explanation": explanation,
            "official_solution_text": official_solution_text,
            "free_ai_explanation": free_ai_explanation or explanation,
            "free_ai_status": _normalize_text_value(getattr(task, "free_ai_status", "") or ("ready" if (free_ai_explanation or explanation) else "empty")),
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
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to get solution: {str(e)}")


@app.get("/tasks/{task_id}")
def get_task(task_id: int, enrich: bool = True, db: Session = Depends(get_db)):
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        enrich_status = "skipped"
        if enrich:
            try:
                _, enrich_status = _enrich_task_from_vsosh_pdfs(task, db, force=False)
                db.refresh(task)
            except Exception as exc:
                enrich_status = f"error: {_normalize_text_value(exc)}"
        full_statement = _normalize_text_value(getattr(task, "full_problem_statement", "") or task.problem_statement or "")
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
            "points": task.points, "time_limit": _time_limit_by_difficulty(task.difficulty)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Ошибка при получении задачи")


@app.post("/tasks/{task_id}/solve")
def solve_task(task_id: int, user_answer: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        normalized_answer = _normalize_text_value(task.answer).lower()
        manual_check = _is_manual_answer(normalized_answer)
        if manual_check:
            official_answer = _extract_answer_from_official_solution(getattr(task, "official_solution_text", "") or "")
            if official_answer:
                normalized_answer = _normalize_text_value(official_answer).lower()
                manual_check = False
        if manual_check and (task.ai_answer_short or "").strip():
            normalized_answer = _normalize_text_value(task.ai_answer_short).lower()
            manual_check = False
        if manual_check:
            return {"is_correct": False, "manual_check": True,
                    "message": "Для этой задачи автопроверка отключена. Используйте блок решения задачи.",
                    "points_earned": 0, "already_solved": False}
        is_correct = user_answer.strip().lower() == normalized_answer
        previous_solution = db.query(Solution).filter(
            Solution.user_id == current_user.id, Solution.task_id == task_id
        ).order_by(Solution.created_at.desc()).first()
        viewed_solution = previous_solution.viewed_solution if previous_solution else False
        previous_correct = previous_solution and previous_solution.is_correct
        points_earned = 0
        if is_correct and not previous_correct and not viewed_solution:
            points_earned = task.points
        solution = Solution(user_id=current_user.id, task_id=task_id, answer=user_answer,
                            is_correct=is_correct, points_earned=points_earned, viewed_solution=viewed_solution)
        db.add(solution)
        user_stats = db.query(UserStats).filter(UserStats.user_id == current_user.id).first()
        if not user_stats:
            user_stats = UserStats(user_id=current_user.id, total_solved=0, correct_answers=0,
                                   total_points=0, current_streak=0, best_streak=0)
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
        message = "Правильно!" if is_correct else "Неправильно"
        if previous_correct:
            message = "Вы уже решали эту задачу правильно"
        elif viewed_solution and is_correct:
            message = "Правильно, но баллы не начислены (просмотрено решение)"
        return {"is_correct": is_correct, "message": message, "points_earned": points_earned, "already_solved": bool(previous_correct)}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")


@app.put("/tasks/{task_id}")
def update_task(task_id: int, title: str = None, problem_statement: str = None, answer: str = None, db: Session = Depends(get_db)):
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
            if force or _is_manual_answer(answer_value) or not explanation_value or _is_generic_solution_explanation(explanation_value):
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
            attachments = _normalize_attachments(task_data.get("attachments"), subject=subject, grade=grade, topic=topic_value, statement=statement)
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
                                 "title": _build_task_title(task.title, _normalize_subject(task.subject), task.grade, task.topic),
                                 "problem_statement": _strip_source_lines(task.problem_statement or ""),
                                 "difficulty": _normalize_difficulty(task.difficulty),
                                 "points": task.points, "time_limit": _time_limit_by_difficulty(task.difficulty)}
                    }
                    await websocket.send_json(match_data)
                    opponent_id = player2["user_id"] if player1["user_id"] == user_id else player1["user_id"]
                    if opponent_id in match_manager.connections:
                        opp_data = dict(match_data)
                        opp_data["opponent"] = player1["username"] if player2["user_id"] == opponent_id else player2["username"]
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
                is_correct = task.answer.strip().lower() == answer.strip().lower()
                if match["player1"]["user_id"] == user_id:
                    if is_correct: match["player1_score"] = task.points
                else:
                    if is_correct: match["player2_score"] = task.points
                await websocket.send_json({
                    "type": "answer_result", "is_correct": is_correct,
                    "your_score": match["player1_score"] if match["player1"]["user_id"] == user_id else match["player2_score"],
                    "opponent_score": match["player2_score"] if match["player1"]["user_id"] == user_id else match["player1_score"]
                })
                if match["player1_answer"] and match["player2_answer"]:
                    winner_id = None
                    if match["player1_score"] > match["player2_score"]: winner_id = match["player1"]["user_id"]
                    elif match["player2_score"] > match["player1_score"]: winner_id = match["player2"]["user_id"]
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
                        "your_score": match["player1_score"] if match["player1"]["user_id"] == user_id else match["player2_score"],
                        "opponent_score": match["player2_score"] if match["player1"]["user_id"] == user_id else match["player1_score"],
                        "rating_change": int(K * (s1 - e1)) if match["player1"]["user_id"] == user_id else int(K * (s2 - e2))
                    }
                    await websocket.send_json(result_data)
                    opponent_id = match["player2"]["user_id"] if match["player1"]["user_id"] == user_id else match["player1"]["user_id"]
                    if opponent_id in match_manager.connections:
                        opp_result = dict(result_data)
                        opp_result["your_score"] = match["player2_score"] if match["player2"]["user_id"] == opponent_id else match["player1_score"]
                        opp_result["opponent_score"] = match["player1_score"] if match["player2"]["user_id"] == opponent_id else match["player2_score"]
                        opp_result["rating_change"] = int(K * (s2 - e2)) if match["player2"]["user_id"] == opponent_id else int(K * (s1 - e1))
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
