import hashlib
import json
import re
from pathlib import Path
from urllib.request import urlretrieve, Request, urlopen

from app.config import (
    _safe_int, PROJECT_ROOT, PDF_SOURCE_CACHE_DIR, PDF_FRAGMENT_CACHE_DIR,
    TASK_CROPS_DIR, POINTS_MARKER_RE,
)
from app.utils.text import (
    normalize_text_value as _normalize_text_value,
    strip_source_lines as _strip_source_lines,
    simplify_text_for_search as _simplify_text_for_search,
)
from app.utils.attachments import (
    attachments_from_storage as _attachments_from_storage,
    normalize_source_fragments as _normalize_source_fragments,
    source_fragments_from_storage as _source_fragments_from_storage,
)
from app.config import _extract_source_url


def ensure_cache_dirs():
    PDF_SOURCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    PDF_FRAGMENT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    TASK_CROPS_DIR.mkdir(parents=True, exist_ok=True)


def source_pdf_cache_path(source_url: str) -> Path:
    from urllib.parse import urlparse
    parsed = urlparse(source_url)
    suffix = Path(parsed.path or "").suffix.lower()
    if suffix != ".pdf":
        suffix = ".pdf"
    key = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
    return PDF_SOURCE_CACHE_DIR / f"{key}{suffix}"


def get_source_pdf_url(task) -> str:
    direct = _normalize_text_value(task.source_pdf_url or "")
    if direct:
        return direct
    for item in _attachments_from_storage(task.attachments):
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "").strip().lower() != "pdf":
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


def ensure_local_pdf_path(source_url: str) -> Path:
    ensure_cache_dirs()
    normalized_url = str(source_url or "").strip()
    if not normalized_url:
        raise RuntimeError("source_pdf_url is empty")
    if normalized_url.startswith("http://") or normalized_url.startswith("https://"):
        cache_path = source_pdf_cache_path(normalized_url)
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


def url_exists(url: str) -> bool:
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
                if 200 <= getattr(response, "status", 200) < 400:
                    return True
        except Exception:
            continue
    return False


def normalize_visual_fragment(fragment: dict, page_width: float, page_height: float):
    try:
        x = float(fragment.get("x"))
        y = float(fragment.get("y"))
        width = float(fragment.get("width"))
        height = float(fragment.get("height"))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    unit = str(fragment.get("unit") or "pt").strip().lower()
    is_ratio = unit in {"ratio", "relative", "norm"} or (x <= 1.0 and y <= 1.0 and width <= 1.0 and height <= 1.0)
    if is_ratio:
        left, top, right, bottom = x, y, x + width, y + height
    else:
        if page_width <= 0 or page_height <= 0:
            return None
        left = x / page_width
        top = y / page_height
        right = (x + width) / page_width
        bottom = (y + height) / page_height
    left, top = max(0.0, min(1.0, left)), max(0.0, min(1.0, top))
    right, bottom = max(0.0, min(1.0, right)), max(0.0, min(1.0, bottom))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def infer_page_index_from_statement(pdf_doc, statement: str) -> int:
    snippet = _strip_source_lines(statement or "")
    if not snippet:
        return 0
    anchor = _simplify_text_for_search(snippet[:220])
    if not anchor:
        return 0
    for page_index in range(len(pdf_doc)):
        page = pdf_doc[page_index]
        text_page = page.get_textpage()
        page_text = text_page.get_text_range() or ""
        text_page.close()
        page.close()
        normalized = _simplify_text_for_search(page_text)
        if not normalized:
            continue
        for length in (80, 60, 40, 30, 20):
            if len(anchor) >= length and anchor[:length] in normalized:
                return page_index
    return 0


def build_chunk_search_queries(chunk_text: str) -> list:
    text = _normalize_text_value(chunk_text or "")
    if not text:
        return []
    text = re.sub(r"^\s*(?:№\s*\d+)\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"^\s*\d{1,2}\s+балл(?:а|ов)?\s*\(\s*\d{1,2}\s+балл(?:а|ов)?\s*\)\s*",
        "", text, flags=re.IGNORECASE,
    )
    words = [w for w in re.split(r"\s+", text) if w]
    if len(words) < 4:
        return []
    candidates = []
    for size in (20, 16, 12, 10, 8):
        if len(words) >= size:
            candidates.append(" ".join(words[:size]))
    if not candidates:
        candidates.append(" ".join(words[:min(len(words), 8)]))
    seen = set()
    unique = []
    for c in candidates:
        if c.lower() not in seen:
            seen.add(c.lower())
            unique.append(c)
    return unique


def bbox_ratio_from_char_range(text_page, start_index: int, count: int, page_width: float, page_height: float):
    if page_width <= 0 or page_height <= 0 or start_index < 0 or count <= 0:
        return None
    try:
        max_chars = int(text_page.count_chars())
    except Exception:
        return None
    if start_index >= max_chars:
        return None
    end_index = min(start_index + count, max_chars)
    left = right = top = bottom = None
    for char_idx in range(start_index, end_index):
        try:
            x0, y0, x1, y1 = text_page.get_charbox(char_idx)
        except Exception:
            continue
        cl, cr = min(float(x0), float(x1)), max(float(x0), float(x1))
        cb, ct = min(float(y0), float(y1)), max(float(y0), float(y1))
        if cr <= cl or ct <= cb:
            continue
        left = cl if left is None else min(left, cl)
        right = cr if right is None else max(right, cr)
        top = ct if top is None else max(top, ct)
        bottom = cb if bottom is None else min(bottom, cb)
    if any(v is None for v in (left, right, top, bottom)):
        return None
    rl = max(0.0, min(1.0, left / page_width))
    rr = max(0.0, min(1.0, right / page_width))
    rt = max(0.0, min(1.0, 1.0 - (top / page_height)))
    rb = max(0.0, min(1.0, 1.0 - (bottom / page_height)))
    if rr <= rl or rb <= rt:
        return None
    return rl, rt, rr, rb


def find_fragment_for_chunk_in_pdf(local_pdf_path: Path, chunk_text: str, page_start: int = None, page_end: int = None):
    try:
        import pypdfium2 as pdfium
    except Exception:
        return []
    queries = build_chunk_search_queries(chunk_text)
    if not queries:
        return []
    try:
        pdf_doc = pdfium.PdfDocument(str(local_pdf_path))
    except Exception:
        return []
    try:
        total_pages = len(pdf_doc)
        if total_pages <= 0:
            return []
        start = max(1, _safe_int(page_start, 1) or 1)
        end = min(total_pages, max(start, _safe_int(page_end, total_pages) or total_pages))
        best = None
        for page_num in range(start, end + 1):
            page = pdf_doc[page_num - 1]
            text_page = page.get_textpage()
            try:
                page_width, page_height = page.get_size()
                for query in queries:
                    searcher = text_page.search(query, match_case=False)
                    try:
                        hit = searcher.get_next()
                        while hit:
                            start_idx, count = hit
                            bbox = bbox_ratio_from_char_range(text_page, int(start_idx), int(count), page_width, page_height)
                            if bbox:
                                l, t, r, b = bbox
                                score = (len(query), (r - l) * (b - t))
                                if best is None or score > best["score"]:
                                    best = {"score": score, "page": page_num, "x": l, "y": t, "width": r - l, "height": b - t}
                            hit = searcher.get_next()
                    finally:
                        searcher.close()
            finally:
                text_page.close()
                page.close()
        if not best:
            return []
        chunk_len = len(_normalize_text_value(chunk_text or ""))
        l = max(0.0, best["x"] - 0.01)
        r = min(1.0, best["x"] + best["width"] + 0.01)
        t = max(0.0, best["y"] - 0.008)
        growth = min(0.24, 0.03 + (chunk_len / 2200.0))
        b = min(1.0, best["y"] + best["height"] + growth)
        if b <= t:
            t = best["y"]
            b = min(1.0, best["y"] + max(best["height"], 0.04))
        return [{"page": best["page"], "x": l, "y": t, "width": r - l, "height": b - t, "unit": "ratio", "order_index": 1}]
    finally:
        pdf_doc.close()


def build_fallback_fragments(task, pdf_doc):
    page_count = len(pdf_doc)
    if page_count <= 0:
        return []
    if task.source_page_start and task.source_page_start > 0:
        start_page = min(task.source_page_start, page_count)
    else:
        start_page = infer_page_index_from_statement(pdf_doc, task.problem_statement or "") + 1
        if start_page <= 0:
            start_page = 1
    end_page = start_page
    if task.source_page_end and task.source_page_end >= start_page:
        end_page = min(task.source_page_end, page_count)
    fragments = []
    for idx, page in enumerate(range(start_page, end_page + 1), start=1):
        fragments.append({"page": page, "x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0, "unit": "ratio", "order_index": idx})
    return fragments


def render_task_fragments(task):
    source_url = get_source_pdf_url(task)
    if not source_url:
        return {"available": False, "reason": "no_source_pdf", "images": []}
    try:
        local_pdf_path = ensure_local_pdf_path(source_url)
    except Exception as exc:
        return {"available": False, "reason": "source_pdf_unavailable", "error": str(exc), "images": [], "source_pdf_url": source_url}
    try:
        import pypdfium2 as pdfium
    except Exception:
        return {"available": False, "reason": "pdf_renderer_not_installed", "images": [], "source_pdf_url": source_url}
    try:
        pdf_doc = pdfium.PdfDocument(str(local_pdf_path))
    except Exception as exc:
        return {"available": False, "reason": "pdf_open_failed", "error": str(exc), "images": [], "source_pdf_url": source_url}
    try:
        source_fragments = _source_fragments_from_storage(task.source_fragments)
        fragments = _normalize_source_fragments(source_fragments)
        visual_mode = "bbox" if fragments else "page_fallback"
        if not fragments:
            fragments = build_fallback_fragments(task, pdf_doc)
        if not fragments:
            return {"available": False, "reason": "no_fragments", "images": [], "source_pdf_url": source_url}

        ensure_cache_dirs()
        images = []
        stats = local_pdf_path.stat()
        pdf_fingerprint = f"{local_pdf_path.resolve()}:{stats.st_mtime_ns}:{stats.st_size}"

        for fragment in sorted(fragments, key=lambda f: f.get("order_index", 0)):
            page_num = _safe_int(fragment.get("page"), None)
            if page_num is None or page_num < 1 or page_num > len(pdf_doc):
                continue
            page = pdf_doc[page_num - 1]
            page_width, page_height = page.get_size()
            bbox = normalize_visual_fragment(fragment, page_width, page_height)
            if not bbox:
                page.close()
                continue
            left, top, right, bottom = bbox
            render_scale = 2.2
            cache_key = hashlib.sha256(
                json.dumps({"task_id": task.id, "pdf": pdf_fingerprint, "page": page_num,
                            "bbox": [left, top, right, bottom], "scale": render_scale}, sort_keys=True).encode("utf-8")
            ).hexdigest()
            cache_path = PDF_FRAGMENT_CACHE_DIR / f"{cache_key}.webp"
            if not cache_path.exists():
                pil_img = page.render(scale=render_scale).to_pil()
                page.close()
                img_w, img_h = pil_img.size
                cropped = pil_img.crop((int(round(left * img_w)), int(round(top * img_h)),
                                        int(round(right * img_w)), int(round(bottom * img_h))))
                cropped.save(cache_path, format="WEBP", quality=90, method=6)
            else:
                page.close()
            images.append({"url": f"/tasks/fragments/{cache_path.name}", "page": page_num,
                           "order_index": _safe_int(fragment.get("order_index"), len(images) + 1)})
        return {"available": bool(images), "reason": "ok" if images else "render_empty",
                "visual_mode": visual_mode, "source_pdf_url": source_url, "images": images}
    finally:
        pdf_doc.close()


def split_statement_by_points_markers(statement: str) -> list:
    text = _normalize_text_value(statement or "")
    if len(text) < 900:
        return [text] if text else []
    markers = list(POINTS_MARKER_RE.finditer(text))
    if len(markers) < 2:
        return [text] if text else []
    boundaries = [0] + [m.start(0) for m in markers[1:]] + [len(text)]
    chunks = [text[boundaries[i]:boundaries[i + 1]].strip() for i in range(len(boundaries) - 1)]
    chunks = [c for c in chunks if len(c) >= 80]
    return chunks if len(chunks) >= 2 else ([text] if text else [])
