#!/usr/bin/env python3
import re
import json
import hashlib
import os
from pathlib import Path
from urllib.request import urlretrieve, Request, urlopen
from urllib.error import HTTPError, URLError
from typing import List, Dict, Optional
import pypdfium2 as pdfium
from PIL import Image

CACHE_DIR = Path(__file__).parent / "backend" / "cache"
PDF_CACHE = CACHE_DIR / "pdf_sources"
IMG_CACHE = CACHE_DIR / "task_crops"
TASKS_JSON = Path(__file__).parent / "tasks.json"

PDF_CACHE.mkdir(parents=True, exist_ok=True)
IMG_CACHE.mkdir(parents=True, exist_ok=True)

TASK_HEADER_RE = re.compile(r"^(?:Задач[аи]|Задани[ея])\s+(\d+)[.\s]", re.IGNORECASE)
ANSWER_RE = re.compile(r"^\s*(?:итоговый\s+)?[Оо]твет\s*[:\-]\s*(.+)$")
ANSWER_TRIM_RE = re.compile(r"\s+(?:[Рр]ешение|[Рр]азбор|solution)[.:\s]", re.IGNORECASE)
SUBTASK_RE = re.compile(r"^(\d+)\.(\d+)[.\s]")
VARIANT_RE = re.compile(r"^(?:Задач[аи]|Задани[ея])\s+(\d+)\.\s*Вариант\s+(\d+)\.", re.IGNORECASE)
HEADER_RE = re.compile(r"Всероссийская олимпиада|Школьный этап|ВСЕРОССИЙСКАЯ|МАТЕМАТИКА\.|Задания школьного этапа", re.IGNORECASE)
PADDING = 15


def download_pdf(url: str) -> Path:
    path = PDF_CACHE / f"{hashlib.sha256(url.encode()).hexdigest()}.pdf"
    if not path.exists():
        print(f"  Скачиваю: {url}")
        urlretrieve(url, path)
    return path


def _page_lines_with_coords(pdf_path: Path, page_idx: int) -> List[Dict]:
    pdf = pdfium.PdfDocument(pdf_path)
    page = pdf[page_idx]
    tp = page.get_textpage()
    n = tp.count_chars()
    lines, cur_chars, cur_y = [], [], None

    for i in range(n):
        box = tp.get_charbox(i, loose=True)
        char = tp.get_text_range(i, 1)
        y_mid = (box[1] + box[3]) / 2
        if cur_y is None:
            cur_y = y_mid
        if abs(y_mid - cur_y) > 4:
            if cur_chars:
                text = "".join(c for c, _ in cur_chars).strip()
                ys = [b[1] for _, b in cur_chars] + [b[3] for _, b in cur_chars]
                lines.append({"text": text, "y_bottom": min(ys), "y_top": max(ys)})
            cur_chars, cur_y = [], y_mid
        cur_chars.append((char, box))

    if cur_chars:
        text = "".join(c for c, _ in cur_chars).strip()
        ys = [b[1] for _, b in cur_chars] + [b[3] for _, b in cur_chars]
        lines.append({"text": text, "y_bottom": min(ys), "y_top": max(ys)})

    tp.close(); page.close(); pdf.close()
    return lines


def _collect_blocks(all_page_lines, start_page, start_li, end_page, end_li):
    result = []
    for p in sorted(all_page_lines.keys()):
        if p < start_page or p > end_page:
            continue
        lines = all_page_lines[p]
        if p == start_page and p == end_page:
            chunk = lines[start_li:end_li]
        elif p == start_page:
            chunk = lines[start_li:]
        elif p == end_page:
            chunk = lines[:end_li]
        else:
            chunk = lines
        for line in chunk:
            result.append((p, line))
    return result


def _blocks_to_segments(blocks):
    pages_used = {}
    for p, line in blocks:
        if p not in pages_used:
            pages_used[p] = {"y_bottom": line["y_bottom"], "y_top": line["y_top"]}
        else:
            pages_used[p]["y_bottom"] = min(pages_used[p]["y_bottom"], line["y_bottom"])
            pages_used[p]["y_top"] = max(pages_used[p]["y_top"], line["y_top"])
    return [{"page": p, "y_bottom": v["y_bottom"], "y_top": v["y_top"]} for p, v in sorted(pages_used.items())]


def _get_task_boundaries(pdf_path: Path) -> List[Dict]:
    pdf = pdfium.PdfDocument(pdf_path)
    n_pages = len(pdf)
    pdf.close()

    all_page_lines = {i: _page_lines_with_coords(pdf_path, i) for i in range(n_pages)}

    task_headers = []
    for page_idx in sorted(all_page_lines.keys()):
        for li, line in enumerate(all_page_lines[page_idx]):
            mv = VARIANT_RE.match(line["text"])
            if mv:
                num = int(mv.group(1))
                if 1 <= num <= 50:
                    task_headers.append((page_idx, li, num, int(mv.group(2))))
                continue
            m = TASK_HEADER_RE.match(line["text"])
            if m:
                num = int(m.group(1))
                if 1 <= num <= 50:
                    task_headers.append((page_idx, li, num, None))

    if not task_headers:
        return []

    result = []
    for idx, (start_page, start_li, task_num, variant_num) in enumerate(task_headers):
        if idx + 1 < len(task_headers):
            end_page, end_li, _, _ = task_headers[idx + 1]
        else:
            end_page = n_pages - 1
            end_li = len(all_page_lines[end_page])

        blocks = _collect_blocks(all_page_lines, start_page, start_li, end_page, end_li)
        blocks = [(p, l) for p, l in blocks
                  if l["text"] and not HEADER_RE.search(l["text"]) and not re.fullmatch(r"\d+", l["text"])]

        subtask_starts = []
        for bi, (p, line) in enumerate(blocks):
            m = SUBTASK_RE.match(line["text"])
            if m and int(m.group(1)) == task_num:
                subtask_starts.append((bi, int(m.group(2))))

        if len(subtask_starts) > 1:
            for si, (sb_start, sub_num) in enumerate(subtask_starts):
                sb_end = subtask_starts[si + 1][0] if si + 1 < len(subtask_starts) else len(blocks)
                sub_blocks = blocks[sb_start:sb_end]
                text = "\n".join(l["text"] for _, l in sub_blocks)
                segments = _blocks_to_segments(sub_blocks)
                if not segments:
                    continue

                if si + 1 < len(subtask_starts):
                    next_p, next_line = blocks[subtask_starts[si + 1][0]]
                    last_seg = segments[-1]
                    if next_p == last_seg["page"]:
                        last_seg["y_bottom"] = next_line["y_top"] - 2
                    else:
                        last_seg["y_bottom"] = 0

                result.append({
                    "number": task_num, "subtask": sub_num, "variant": variant_num,
                    "text": text, "segments": segments,
                    "start_page": segments[0]["page"], "end_page": segments[-1]["page"],
                })
        else:
            text = "\n".join(l["text"] for _, l in blocks)
            segments = _blocks_to_segments(blocks)
            if not segments:
                continue
            result.append({
                "number": task_num, "subtask": None, "variant": variant_num,
                "text": text, "segments": segments,
                "start_page": segments[0]["page"], "end_page": segments[-1]["page"],
            })

    return result


def _crop_task_image(pdf_path: Path, task: Dict, scale: float = 2.5) -> Optional[str]:
    pdf = pdfium.PdfDocument(pdf_path)
    parts = []

    for seg in task["segments"]:
        page = pdf[seg["page"]]
        page_h = page.get_height()
        pil_full = page.render(scale=scale).to_pil()
        pw, ph = pil_full.size

        top_px = max(0, int((page_h - (seg["y_top"] + PADDING)) * scale))
        bottom_px = min(ph, int((page_h - (seg["y_bottom"] - PADDING)) * scale))

        if bottom_px > top_px:
            parts.append(pil_full.crop((0, top_px, pw, bottom_px)))
        page.close()

    pdf.close()
    if not parts:
        return None

    result = Image.new("RGB", (max(p.width for p in parts), sum(p.height for p in parts)), (255, 255, 255))
    y_off = 0
    for part in parts:
        result.paste(part, (0, y_off))
        y_off += part.height

    unique = f"{pdf_path}{task['number']}{task.get('subtask','')}{task.get('variant','')}"
    key = hashlib.sha256(unique.encode()).hexdigest()[:16]
    n, sub, var = task['number'], task.get('subtask', ''), task.get('variant', '')
    suffix = f"_{sub}" if sub else (f"_v{var}" if var else "")
    img_name = f"task_{n}{suffix}_{key}.webp"
    (IMG_CACHE / img_name).parent.mkdir(parents=True, exist_ok=True)
    result.save(IMG_CACHE / img_name, format="WEBP", quality=90)
    return f"/static/task_crops/{img_name}"


def _extract_answer_from_text(text: str) -> str:
    for line in text.splitlines():
        m = ANSWER_RE.match(line)
        if m:
            raw = m.group(1)
            trimmed = ANSWER_TRIM_RE.split(raw, maxsplit=1)[0].strip().rstrip(".")
            if trimmed:
                return trimmed
    return ""


def parse_pdf(pdf_url: str, subject: str, grade: int, year: int = 2025, generate_ai: bool = False) -> List[Dict]:
    print(f"\n=== {subject} {grade} класс {year} ===")
    pdf_path = download_pdf(pdf_url)
    tasks = _get_task_boundaries(pdf_path)
    print(f"  Найдено задач: {len(tasks)}")

    result = []
    for task in tasks:
        n, sub, var = task["number"], task.get("subtask"), task.get("variant")
        label = f"{n} вариант {var}" if var else (f"{n}.{sub}" if sub else str(n))
        print(f"  Задача {label}...")

        img_url = _crop_task_image(pdf_path, task)
        difficulty, points = ("easy", 6) if n <= 7 else (("medium", 10) if n <= 14 else ("hard", 14))

        attachments = []
        if img_url:
            attachments.append({"type": "image", "title": f"Условие задачи {label}", "image_url": img_url, "caption": ""})

        answer = _extract_answer_from_text(task["text"])
        solution = {"answer": answer or "см. решение", "explanation": ""}
        if generate_ai:
            solution = _generate_solution(task["text"], subject, grade)

        title_suffix = f"task {n} variant {var}" if var else (f"task {n}.{sub}" if sub else f"task {n}")
        result.append({
            "title": f"VSOSH {year} {subject} grade {grade} {title_suffix}",
            "problem_statement": task["text"],
            "answer": solution["answer"],
            "subject": subject, "grade": grade,
            "difficulty": difficulty, "points": points,
            "solution_explanation": solution["explanation"],
            "topic": "VSOSH", "tags": "vsosh,official-task", "time_limit": 900,
            "source_pdf_url": pdf_url,
            "source_page_start": task["start_page"] + 1,
            "source_page_end": task["end_page"] + 1,
            "attachments": attachments,
        })

    return result


def _generate_solution(task_text: str, subject: str, grade: int) -> Dict[str, str]:
    provider = (os.getenv("LOCAL_LLM_PROVIDER", "").strip() or "ollama").lower()
    if provider in {"vllm", "openai", "openai_compat", "openai-compatible"}:
        provider = "openai_compat"
    else:
        provider = "ollama"

    try:
        system_prompt = "Ты решаешь школьные олимпиадные задачи. Давай чёткие пошаговые решения на русском языке."
        prompt = f"Реши олимпиадную задачу для {grade} класса по предмету \"{subject}\".\n\n{task_text}\n\nИтоговый ответ: [ответ]"
        if provider == "ollama":
            model = os.getenv("LOCAL_LLM_MODEL", "").strip() or os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct").strip() or "qwen2.5:7b-instruct"
            api_url = os.getenv("OLLAMA_API_URL", "").strip() or f"{(os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434').strip() or 'http://localhost:11434').rstrip('/')}/api/chat"
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 1024,
                },
            }
            headers = {"Content-Type": "application/json"}
        else:
            default_model = os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-7B-Instruct").strip() or "Qwen/Qwen2.5-7B-Instruct"
            model = os.getenv("LOCAL_LLM_MODEL", "").strip() or os.getenv("LOCAL_OPENAI_MODEL", default_model).strip() or default_model
            api_url = (
                os.getenv("LOCAL_OPENAI_API_URL", "").strip()
                or os.getenv("VLLM_API_URL", "").strip()
                or f"{(os.getenv('LOCAL_OPENAI_BASE_URL', '').strip() or os.getenv('VLLM_BASE_URL', '').strip() or 'http://localhost:8000/v1').rstrip('/')}/chat/completions"
            )
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 1024,
            }
            headers = {"Content-Type": "application/json"}
            api_key = os.getenv("LOCAL_OPENAI_API_KEY", "").strip() or os.getenv("VLLM_API_KEY", "").strip()
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

        req = Request(
            api_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(req, timeout=120) as resp:
                raw = resp.read()
        except HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="ignore")
            except Exception:
                pass
            raise RuntimeError(f"Local LLM HTTP {e.code}: {body or e.reason}") from e
        except URLError as e:
            raise RuntimeError(f"Local LLM request failed: {e}") from e

        parsed = json.loads(raw.decode("utf-8", errors="ignore"))
        if provider == "ollama":
            sol = ((parsed.get("message") or {}).get("content") or parsed.get("response") or "")
        else:
            choices = parsed.get("choices") or []
            if not choices:
                raise RuntimeError(f"OpenAI-compatible server returned no choices: {parsed}")
            sol = (choices[0].get("message") or {}).get("content", "")
            if isinstance(sol, list):
                chunks = []
                for part in sol:
                    if isinstance(part, dict):
                        chunks.append(str(part.get("text") or part.get("content") or ""))
                    else:
                        chunks.append(str(part))
                sol = "\n".join(chunk for chunk in chunks if chunk)
        sol = str(sol or "").strip()
        m = re.search(r"Итоговый ответ:\s*(.+)", sol, re.IGNORECASE)
        return {"answer": m.group(1).strip() if m else "see editorial", "explanation": sol}
    except Exception as e:
        print(f"  Local LLM ({provider}) ошибка: {e}")
        return {"answer": "see editorial", "explanation": ""}


def main():
    env_path = Path(__file__).parent / ".env.local"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    pdfs = [
        ("математика", 6, 2025, "https://xn--b1ayi3a.xn--l1afu.xn--p1ai/upload/files/Arhive_tasks/2025-26/school/math/tasks-math-6-sch-msk-25-26.pdf"),
        ("математика", 7, 2025, "https://xn--b1ayi3a.xn--l1afu.xn--p1ai/upload/files/Arhive_tasks/2025-26/school/math/tasks-math-7-sch-msk-25-26.pdf"),
    ]

    all_tasks = []
    for subject, grade, year, url in pdfs:
        try:
            all_tasks.extend(parse_pdf(url, subject, grade, year))
        except Exception as e:
            print(f"Ошибка {subject} {grade}: {e}")
            import traceback; traceback.print_exc()

    raw = TASKS_JSON.read_text(encoding="utf-8").strip() if TASKS_JSON.exists() else ""
    existing_tasks = json.loads(raw).get("tasks", []) if raw else []
    index = {t["title"]: i for i, t in enumerate(existing_tasks)}
    added, updated = 0, 0
    for t in all_tasks:
        if t["title"] in index:
            existing_tasks[index[t["title"]]] = t
            updated += 1
        else:
            existing_tasks.append(t)
            added += 1

    TASKS_JSON.write_text(json.dumps({"tasks": existing_tasks}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ Добавлено: {added}, обновлено: {updated}. Всего: {len(existing_tasks)}")


if __name__ == "__main__":
    main()
