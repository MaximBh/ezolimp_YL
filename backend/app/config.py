import os
import re
from pathlib import Path
from app.utils.text import _fix_mojibake_text, URL_RE


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
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))


_seen_env_paths: set = set()
_search_dirs = [
    Path(__file__).resolve().parents[2],
    Path(__file__).resolve().parents[1],
    Path.cwd(),
]
for _search_dir in _search_dirs:
    for _env_name in (".env.local", ".evn.local"):
        _candidate = (_search_dir / _env_name).resolve()
        _key = str(_candidate).lower()
        if _key in _seen_env_paths:
            continue
        _seen_env_paths.add(_key)
        _load_env_file(_candidate)


def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent
CACHE_DIR = BACKEND_DIR / "cache"
PDF_SOURCE_CACHE_DIR = CACHE_DIR / "pdf_sources"
PDF_FRAGMENT_CACHE_DIR = CACHE_DIR / "pdf_fragments"
TASK_CROPS_DIR = CACHE_DIR / "task_crops"

TIME_LIMIT_BY_DIFFICULTY = {"easy": 30, "medium": 60, "hard": 90}

SUBJECT_ALIASES = {
    "математика": "математика", "math": "математика",
    "информатика": "информатика", "informatics": "информатика",
    "физика": "физика", "physics": "физика",
    "химия": "химия", "chemistry": "химия",
    "биология": "биология", "biology": "биология",
    "английский": "английский", "английский язык": "английский", "english": "английский",
    "русский": "русский", "русский язык": "русский", "russian": "русский",
    "обществознание": "обществознание", "social studies": "обществознание",
    "право": "право", "law": "право",
    "история": "история", "history": "история",
    "география": "география", "geography": "география",
    "экология": "экология", "ecology": "экология",
    "литература": "литература", "literature": "литература",
    "робототехника": "робототехника", "robotics": "робототехника",
}

OLYMPIAD_ALIASES = {"VSOSH": "ВСОШ", "ВСОШ": "ВСОШ"}

SUPPORTED_SUBJECTS = [
    "математика", "информатика", "физика", "химия", "биология",
    "английский", "русский", "обществознание", "право", "история",
    "география", "экология", "литература", "робототехника",
]

BASE_SUBJECTS = ["математика", "информатика", "физика", "химия", "биология"]
NEW_SUBJECTS = [s for s in SUPPORTED_SUBJECTS if s not in BASE_SUBJECTS]

MONTHS_RU_GENITIVE = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
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

MANUAL_ANSWER_MARKERS = {"see editorial", "см. разбор", "см. решение", "n/a", "manual"}
RECOVERABLE_AI_STATUSES = ("", "empty", "error", "timeout", "unavailable", "failed", "model_not_found", "no_api_key", "invalid_api_key", "rate_limited", None)
NON_AUTORETRY_AI_STATUSES = ("timeout", "unavailable", "failed", "model_not_found", "no_api_key", "invalid_api_key")

ANSWER_LABEL_TOKEN_RE = r"[0-9a-z\u0430-\u044f\u0451]"
ANSWER_LABEL_VALUE_RE = re.compile(rf"({ANSWER_LABEL_TOKEN_RE})\)\s*(.+)", re.IGNORECASE)
ANSWER_GROUP_CHUNK_RE = re.compile(rf"({ANSWER_LABEL_TOKEN_RE})\s*(?:\)|-|:)\s*(.+)", re.IGNORECASE)
ANSWER_GROUP_MARK_RE = re.compile(rf"({ANSWER_LABEL_TOKEN_RE})\s*(?:\)|-|:)", re.IGNORECASE)
NEGATIVE_NUMBER_RE = re.compile(r"^-\d+(?:[.,]\d+)?$")
DECIMAL_NUMBER_RE = re.compile(r"^-?\d+(?:[.,]\d+)?$")
YEAR_RE = re.compile(r"(20\d{2})")
TASK_NUMBER_RE = re.compile(r"(?:task|задача)\s*(\d+)", re.IGNORECASE)
VARIANT_NUMBER_RE = re.compile(r"(?:variant|вариант)\s*(\d+)", re.IGNORECASE)
POINTS_MARKER_RE = re.compile(
    r"\b(\d{1,2})\s+балл(?:а|ов)?\s*\(\s*\d{1,2}\s+балл(?:а|ов)?\s*\)",
    re.IGNORECASE,
)
ANSWER_PREFIX_RE = re.compile(
    r"^\s*(?:(?:итоговый\s+)?ответ|final\s+answer)\s*[:\-]\s*",
    re.IGNORECASE,
)
ANSWER_NOISE_RE = re.compile(
    r"(?:\bрешение\b|\bразбор\b|\bкритери(?:й|я)\b|\b\d+\s*балл\w*\b|\bвсего\b[^\n\r]*\bбалл\w*\b|\bмаксимал\w*\s+балл\w*\b)",
    re.IGNORECASE,
)

ANSWER_HINT_SINGLE = "Введите один ответ. Например: 15 или пушкин."
ANSWER_HINT_LABEL_OR_VALUE = "Введите либо букву/номер варианта, либо сам ответ. Например: а или 1."
ANSWER_HINT_SERVICE_PREFIX = "Введите только сам ответ, без служебных символов. Например: 1."
ANSWER_HINT_NEGATIVE_NUMBER = "Введите число. Если оно отрицательное, обязательно укажите знак минус. Например: -5."
ANSWER_HINT_MULTI_LABEL_OR_VALUE = "Если ответов несколько, введите их слитно, без пробелов и разделителей, в правильном порядке. Например: аб, 13 или 257."
ANSWER_HINT_MULTI_VALUES = "Если ответов несколько, введите их слитно, без пробелов и разделителей, в правильном порядке. Например: аб, 13 или 257."
ANSWER_HINT_GROUPS = "Введите ответ в формате а:1,2,3;б:4,5. Например: а:1,2,3;б:4,5."
ANSWER_HINT_MANUAL = "Формат ответа уточняйте в блоке решения задачи."


def _normalize_difficulty(value) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in TIME_LIMIT_BY_DIFFICULTY else "easy"


def _time_limit_by_difficulty(value) -> int:
    return TIME_LIMIT_BY_DIFFICULTY[_normalize_difficulty(value)]


def _normalize_subject(value) -> str:
    subject = _fix_mojibake_text(str(value or "")).strip()
    if not subject:
        return "математика"
    return SUBJECT_ALIASES.get(subject.lower(), subject)


def _normalize_olympiad_name(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "Олимпиада"
    return OLYMPIAD_ALIASES.get(raw.upper(), raw)


def _extract_source_url(*texts):
    for text in texts:
        if not text:
            continue
        match = URL_RE.search(str(text))
        if match:
            return match.group(0).rstrip(".,);")
    return None


def _is_manual_answer(answer: str) -> bool:
    return str(answer or "").strip().lower() in MANUAL_ANSWER_MARKERS


def _synthetic_subjects_enabled() -> bool:
    return str(os.getenv("ENABLE_SYNTHETIC_SUBJECTS", "")).strip().lower() in {"1", "true", "yes", "on"}


def _import_ai_solutions_enabled() -> bool:
    return str(os.getenv("IMPORT_AI_SOLUTIONS", "")).strip().lower() in {"1", "true", "yes", "on"}


def _sync_tasks_on_startup_enabled() -> bool:
    return str(os.getenv("SYNC_TASKS_ON_STARTUP", "")).strip().lower() in {"1", "true", "yes", "on"}
