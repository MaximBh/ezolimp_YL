import re
from app.utils.text import normalize_text_value as _normalize_text_value
from app.config import (
    ANSWER_LABEL_TOKEN_RE, ANSWER_LABEL_VALUE_RE, ANSWER_GROUP_CHUNK_RE, ANSWER_GROUP_MARK_RE,
    NEGATIVE_NUMBER_RE, DECIMAL_NUMBER_RE, ANSWER_PREFIX_RE, ANSWER_NOISE_RE,
    ANSWER_HINT_SINGLE, ANSWER_HINT_LABEL_OR_VALUE, ANSWER_HINT_SERVICE_PREFIX,
    ANSWER_HINT_NEGATIVE_NUMBER, ANSWER_HINT_MULTI_LABEL_OR_VALUE, ANSWER_HINT_MULTI_VALUES,
    ANSWER_HINT_GROUPS, ANSWER_HINT_MANUAL,
    MANUAL_ANSWER_MARKERS,
)


def normalize_answer_token(value: str) -> str:
    normalized = _normalize_text_value(value).lower().replace("ё", "е")
    return re.sub(r"\s+", " ", normalized).strip()


def normalize_compact_answer_token(value: str) -> str:
    return re.sub(r"[\s,;:]+", "", normalize_answer_token(value))


def is_negative_number_answer(value: str) -> bool:
    return bool(NEGATIVE_NUMBER_RE.fullmatch(normalize_answer_token(value).replace(" ", "")))


def looks_like_meaningful_answer(value: str) -> bool:
    return bool(re.search(r"[0-9a-zа-яё]", normalize_answer_token(value)))


def is_compact_submission(value: str) -> bool:
    normalized = normalize_answer_token(value)
    if not normalized:
        return False
    return not bool(re.search(r"[\s,;:()\-\u2013\u2014]", normalized))


def parse_label_answer_pair(value: str):
    normalized = normalize_answer_token(value)
    if ";" in normalized:
        return None
    match = ANSWER_LABEL_VALUE_RE.fullmatch(normalized)
    if not match:
        return None
    label = match.group(1)
    answer = match.group(2).strip()
    if re.search(rf"{ANSWER_LABEL_TOKEN_RE}\)\s*", answer, flags=re.IGNORECASE):
        return None
    compact_answer = normalize_compact_answer_token(answer)
    if not label or len(label) != 1 or not compact_answer:
        return None
    return label, compact_answer


def split_top_level_group_chunks(value: str):
    normalized = normalize_answer_token(value)
    if not normalized:
        return []
    normalized = re.sub(r"\s*;\s*", ";", normalized)
    parts = [chunk.strip() for chunk in normalized.split(";") if chunk.strip()]
    if len(parts) > 1:
        return parts
    matches = list(ANSWER_GROUP_MARK_RE.finditer(normalized))
    if len(matches) >= 2:
        result = []
        for idx, match in enumerate(matches):
            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(normalized)
            chunk = normalized[start:end].strip(" ;,")
            if chunk:
                result.append(chunk)
        return result
    return [normalized]


def parse_group_chunk(chunk: str):
    normalized = normalize_answer_token(chunk)
    match = ANSWER_GROUP_CHUNK_RE.fullmatch(normalized)
    if not match:
        return None
    key = match.group(1)
    raw_values = match.group(2).strip()
    values = [normalize_compact_answer_token(item) for item in re.split(r"\s*,\s*", raw_values)]
    values = [v for v in values if v]
    if not values:
        return None
    return key, values


def parse_grouped_answer(value: str):
    chunks = split_top_level_group_chunks(value)
    if not chunks:
        return None
    parsed = [parse_group_chunk(chunk) for chunk in chunks]
    if any(item is None for item in parsed):
        return None
    return parsed if parsed else None


def normalize_group_answer(value: str, sort_group_values: bool = False) -> str:
    parsed = parse_grouped_answer(value)
    if not parsed or len(parsed) < 2:
        return ""
    if not any(len(values) > 1 for _, values in parsed):
        return ""
    groups = []
    for key, values in parsed:
        normalized_values = sorted(values) if sort_group_values else values
        groups.append(f"{key}:{','.join(normalized_values)}")
    return ";".join(groups)


def is_multi_answer(value: str) -> bool:
    normalized = normalize_answer_token(value)
    if not normalized:
        return False
    grouped = parse_grouped_answer(normalized)
    if grouped is not None and len(grouped) >= 2 and any(len(values) > 1 for _, values in grouped):
        return True
    if ";" in normalized:
        return True
    compact_no_spaces = normalized.replace(" ", "")
    if "," in normalized and not DECIMAL_NUMBER_RE.fullmatch(compact_no_spaces):
        return True
    return len(split_top_level_group_chunks(normalized)) > 1


def split_multiple_answer_parts(value: str):
    normalized = normalize_answer_token(value)
    if ";" in normalized:
        parts = [p.strip() for p in normalized.split(";") if p.strip()]
        return parts if len(parts) > 1 else []
    if "," in normalized:
        if DECIMAL_NUMBER_RE.fullmatch(normalized.replace(" ", "")):
            return []
        parts = [p.strip() for p in normalized.split(",") if p.strip()]
        return parts if len(parts) > 1 else []
    chunks = split_top_level_group_chunks(normalized)
    return chunks if len(chunks) > 1 else []


def parse_multi_answer(value: str):
    normalized = normalize_answer_token(value)
    if not normalized:
        return {"kind": "multiple_values", "value": ""}
    parts = [p.strip() for p in re.split(r"\s*;\s*", normalized) if p.strip()]
    if len(parts) == 1:
        if "," in normalized and not DECIMAL_NUMBER_RE.fullmatch(normalized.replace(" ", "")):
            parts = [p.strip() for p in re.split(r"\s*,\s*", normalized) if p.strip()]
    if len(parts) == 1:
        parts = split_multiple_answer_parts(normalized)
    parsed_labeled = []
    all_labeled_single = True
    for part in parts:
        item = parse_group_chunk(part)
        if not item or len(item[1]) != 1:
            all_labeled_single = False
            break
        parsed_labeled.append((item[0], item[1][0]))
    if all_labeled_single and parsed_labeled:
        labels = "".join(label for label, _ in parsed_labeled)
        values = "".join(v for _, v in parsed_labeled)
        return {"kind": "multiple_label_pairs", "labels": labels, "values": values}
    values = [normalize_compact_answer_token(p) for p in parts]
    return {"kind": "multiple_values", "value": "".join(v for v in values if v)}


def extract_answer_without_service_prefix(value: str) -> str:
    normalized = normalize_answer_token(value).lstrip()
    if not normalized:
        return ""
    if is_negative_number_answer(normalized):
        return ""
    if parse_label_answer_pair(normalized):
        return ""
    if len(normalized) >= 2 and not normalized[0].isalnum():
        return normalize_compact_answer_token(normalized[1:])
    return ""


def build_answer_check_profile(reference_answer: str):
    reference = normalize_answer_token(reference_answer)
    if not reference:
        return {"kind": "single", "value": "", "hint": ANSWER_HINT_SINGLE}
    if is_negative_number_answer(reference):
        return {"kind": "negative_number", "value": reference.replace(" ", ""), "hint": ANSWER_HINT_NEGATIVE_NUMBER}
    label_pair = parse_label_answer_pair(reference)
    if label_pair:
        label, value = label_pair
        return {"kind": "label_pair", "label": label, "value": value, "hint": ANSWER_HINT_LABEL_OR_VALUE}
    normalized_groups = normalize_group_answer(reference)
    if normalized_groups:
        return {"kind": "groups", "value": normalized_groups, "groups": parse_grouped_answer(reference) or [], "hint": ANSWER_HINT_GROUPS}
    if is_multi_answer(reference):
        parsed = parse_multi_answer(reference)
        if parsed.get("kind") == "multiple_label_pairs":
            return {"kind": "multiple_label_pairs", "labels": parsed.get("labels", ""), "values": parsed.get("values", ""), "hint": ANSWER_HINT_MULTI_LABEL_OR_VALUE}
        return {"kind": "multiple_values", "value": parsed.get("value", ""), "hint": ANSWER_HINT_MULTI_VALUES}
    value_without_prefix = extract_answer_without_service_prefix(reference)
    if value_without_prefix:
        return {"kind": "service_prefix", "value": value_without_prefix, "hint": ANSWER_HINT_SERVICE_PREFIX}
    return {"kind": "single", "value": reference, "hint": ANSWER_HINT_SINGLE}


def check_user_answer_against_reference(user_answer: str, reference_answer: str):
    profile = build_answer_check_profile(reference_answer)
    user_normalized = normalize_answer_token(user_answer)
    user_compact = normalize_compact_answer_token(user_answer)
    kind = profile.get("kind", "single")
    if kind == "negative_number":
        is_correct = user_normalized.replace(" ", "") == profile.get("value", "")
    elif kind == "label_pair":
        is_correct = user_compact == profile.get("label", "") or user_compact == profile.get("value", "")
    elif kind == "groups":
        user_grouped = parse_grouped_answer(user_normalized)
        correct_grouped = profile.get("groups", []) or []
        if not user_grouped or len(user_grouped) != len(correct_grouped):
            is_correct = False
        else:
            is_correct = all(
                ck == uk and sorted(cv) == sorted(uv)
                for (ck, cv), (uk, uv) in zip(correct_grouped, user_grouped)
            )
    elif kind == "multiple_label_pairs":
        is_correct = is_compact_submission(user_answer) and user_compact in {profile.get("labels", ""), profile.get("values", "")}
    elif kind == "multiple_values":
        is_correct = is_compact_submission(user_answer) and user_compact == profile.get("value", "")
    elif kind == "service_prefix":
        is_correct = user_compact == profile.get("value", "")
    else:
        is_correct = user_normalized == profile.get("value", "")
    return {"is_correct": bool(is_correct), "kind": kind, "hint": profile.get("hint", ANSWER_HINT_SINGLE)}


def answer_input_hint_for_reference(reference_answer: str) -> str:
    return build_answer_check_profile(reference_answer).get("hint", ANSWER_HINT_SINGLE)


def clean_reference_answer_text(value: str) -> str:
    text = _normalize_text_value(value or "")
    if not text:
        return ""
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = ANSWER_PREFIX_RE.sub("", text)
    text = re.sub(r"^\s*(?:\u2022|•)\s*", "", text)
    noise_match = ANSWER_NOISE_RE.search(text)
    if noise_match:
        text = text[:noise_match.start()].strip()
    text = ANSWER_PREFIX_RE.sub("", text)
    text = re.sub(r"^\s*(?:\u2022|•)\s*", "", text)
    if any(marker in text for marker in ("✓", "✔", "☑", "•")):
        text = re.sub(r"[✓✔☑•]+", ",", text)
        text = re.sub(r"\s*,\s*", ",", text)
    return re.sub(r"\s+", " ", text).strip(" ,;.-")


def build_answer_check_status(user_answer: str, reference_answer: str):
    clean_reference = clean_reference_answer_text(reference_answer or "")
    if not clean_reference:
        return {"status": "unavailable", "is_correct": None, "hint": ANSWER_HINT_SINGLE, "reference": ""}
    result = check_user_answer_against_reference(user_answer, clean_reference)
    return {
        "status": "correct" if result.get("is_correct") else "incorrect",
        "is_correct": bool(result.get("is_correct")),
        "hint": result.get("hint", ANSWER_HINT_SINGLE),
        "reference": clean_reference,
    }
