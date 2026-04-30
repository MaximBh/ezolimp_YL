import json
from app.config import _safe_int
from app.utils.text import normalize_text_value as _normalize_text_value, first_sentence as _first_sentence


def _build_default_attachment(subject: str, grade, topic: str, statement: str):
    summary = _first_sentence(statement) or "См. полный текст условия."
    if len(summary) > 180:
        summary = f"{summary[:177]}..."
    return [{"type": "table", "title": "Сводка условия", "headers": ["Параметр", "Значение"], "rows": [
        ["Предмет", subject or "—"],
        ["Класс", str(grade) if grade is not None else "—"],
        ["Тема", topic or "общая тема"],
        ["Ключевая информация", summary],
    ]}]


def normalize_attachments(raw, subject: str, grade, topic: str, statement: str):
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
                normalized.append({"type": "table", "title": title or "Таблица",
                    "headers": [str(h) for h in headers],
                    "rows": [[str(c) for c in row] for row in rows if isinstance(row, list)]})
                continue
            if item_type == "image":
                image_url = str(item.get("image_url") or item.get("url") or "").strip()
                if image_url:
                    normalized.append({"type": "image", "title": title or "Иллюстрация",
                        "image_url": image_url, "caption": str(item.get("caption") or "").strip()})
                continue
            content = str(item.get("content") or item.get("text") or "").strip()
            if content:
                normalized.append({"type": "note", "title": title or "Материалы к задаче", "content": content})

    if not normalized:
        normalized = _build_default_attachment(subject, grade, topic, statement)
    return normalized


def attachments_to_storage(attachments) -> str:
    return json.dumps(attachments or [], ensure_ascii=False)


def attachments_from_storage(raw):
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


def ensure_source_pdf_attachment(attachments, source_pdf_url: str):
    source_url = str(source_pdf_url or "").strip()
    if not source_url:
        return attachments
    prepared = list(attachments or [])
    for item in prepared:
        if isinstance(item, dict) and str(item.get("type") or "").strip().lower() == "pdf":
            if str(item.get("pdf_url") or "").strip() == source_url:
                return prepared
    prepared.append({"type": "pdf", "title": "Оригинал условия (PDF)", "pdf_url": source_url})
    return prepared


def normalize_source_fragments(raw):
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

    def _safe_float(v):
        try:
            return None if v is None or v == "" else float(v)
        except (TypeError, ValueError):
            return None

    normalized = []
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            page = _safe_int(item.get("page"), None)
            width = _safe_float(item.get("width"))
            height = _safe_float(item.get("height"))
            if page is None or width is None or height is None:
                continue
            normalized.append({
                "page": page,
                "x": _safe_float(item.get("x")),
                "y": _safe_float(item.get("y")),
                "width": width, "height": height,
                "order_index": _safe_int(item.get("order_index"), len(normalized) + 1),
                "unit": str(item.get("unit") or "").strip().lower() or "pt",
            })

    if len(normalized) < 2:
        return normalized

    def _safe_float(v):
        try:
            return None if v is None or v == "" else float(v)
        except (TypeError, ValueError):
            return None

    metrics = []
    for fragment in normalized:
        if str(fragment.get("unit") or "pt").strip().lower() != "ratio":
            metrics.append(None)
            continue
        x = _safe_float(fragment.get("x"))
        y = _safe_float(fragment.get("y"))
        w = _safe_float(fragment.get("width"))
        h = _safe_float(fragment.get("height"))
        if any(v is None for v in (x, y, w, h)) or w <= 0 or h <= 0:
            metrics.append(None)
            continue
        metrics.append({"x": x, "y": y, "width": w, "height": h, "area": w * h})

    has_large = any(m and (m["area"] >= 0.30 or m["height"] >= 0.34) for m in metrics)

    def _is_header_noise(fragment, metric):
        if not metric or not has_large:
            return False
        return metric["y"] <= 0.30 and metric["width"] >= 0.55 and metric["height"] <= 0.26 and metric["area"] <= 0.24

    filtered = [f for f, m in zip(normalized, metrics) if not _is_header_noise(f, m)]
    if filtered and len(filtered) < len(normalized):
        for idx, fragment in enumerate(filtered, start=1):
            fragment["order_index"] = idx
        return filtered
    return normalized


def source_fragments_to_storage(fragments) -> str:
    return json.dumps(fragments or [], ensure_ascii=False)


def source_fragments_from_storage(raw):
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
