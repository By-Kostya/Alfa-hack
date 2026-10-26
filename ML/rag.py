"""Поиск фрагментов по карточкам продуктов.

Вопрос кодируется тем же вектором, что и карточки. Фрагмент без общих слов
темы не считается найденным: модели его не отдают.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

_STOP = {
    "какая", "какой", "какие", "какое", "сколько", "зачем", "почему",
    "можно", "нужно", "нужен", "нужна", "нужны", "этот", "эта", "это",
    "для", "что", "как", "или", "при", "под", "про", "есть", "ли",
    "над", "между", "если", "только", "уже", "ещё", "еще", "вас",
    "вам", "меня", "мне", "мой", "моя", "мое", "моё", "ваш", "ваша",
    "такой", "такая", "такие", "очень", "просто", "вообще", "скажите",
    "подскажите", "расскажите", "поясните", "пожалуйста",
}
_SUFFIXES = (
    "иями", "ами", "ями", "ого", "ему", "ыми", "ими",
    "ах", "ях", "ов", "ев", "ам", "ям", "ом", "ем",
    "ой", "ий", "ый", "ая", "ое", "ие", "ые", "ия",
    "а", "я", "ы", "и", "у", "ю", "е", "о",
)


def stem(word: str) -> str:
    for suffix in _SUFFIXES:
        if len(word) - len(suffix) >= 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def content_stems(text: str) -> set[str]:
    words = re.findall(r"[а-яё]{4,}", text.lower().replace("ё", "е"))
    found = set(re.findall(r"\d{2,}", text))
    for word in words:
        if word in _STOP:
            continue
        found.add(stem(word))
    return found


def load_chunks(directory: Path) -> list[dict]:
    chunks: list[dict] = []
    for path in sorted(directory.glob("*.md")):
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            continue
        parts = re.split(r"\n(?=## )", raw)
        for part in parts:
            text = part.strip()
            if not text:
                continue
            title = text.splitlines()[0].lstrip("# ").strip()
            chunks.append({
                "source": path.name,
                "title": title,
                "text": text,
                "stems": content_stems(text),
            })
    return chunks


def cosine(left: list[float], right: list[float]) -> float:
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for a, b in zip(left, right):
        dot += a * b
        left_norm += a * a
        right_norm += b * b
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / math.sqrt(left_norm * right_norm)


def center(vectors: list[list[float]]) -> tuple[list[list[float]], list[float]]:
    width = len(vectors[0])
    mean = [sum(vector[index] for vector in vectors) / len(vectors) for index in range(width)]
    centered = [[value - mean[index] for index, value in enumerate(vector)] for vector in vectors]
    return centered, mean


def apply_center(vector: list[float], mean: list[float]) -> list[float]:
    return [value - shift for value, shift in zip(vector, mean)]


def numbers_in(text: str) -> set[int]:
    compact = re.sub(r"(?<=\d)\s+(?=\d)", "", text)
    return {int(item) for item in re.findall(r"\d+", compact)}


_DENIALS = ("не спраш", "не обяз", "не дают", "недоступ", "не счита", "не запраш")


def contradicts(answer: str, support: str) -> bool:
    if not support:
        return False
    lowered_support = support.lower()
    lowered_answer = answer.lower()
    return any(part in lowered_support and part not in lowered_answer for part in _DENIALS)


def covers(answer: str, sentence: str) -> bool:
    stems = content_stems(sentence)
    if len(stems) < 2:
        return True
    overlap = shared_topics(stems, content_stems(answer))
    return overlap >= max(2, len(stems) // 3)


def faithful(answer: str, support: str) -> bool:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", support) if len(part.strip()) >= 20]
    if not sentences or not covers(answer, sentences[0]):
        return False
    return not any(contradicts(answer, sentence) for sentence in sentences)


def supporting_sentences(question: str, chunks: list[dict], limit: int = 2) -> str:
    stems = content_stems(question)
    asked_numbers = numbers_in(question)
    ranked: list[tuple[tuple[int, int], str]] = []
    for chunk in chunks:
        plain = re.sub(r"^#+\s+.*$", "", chunk["text"], flags=re.M)
        for sentence in re.split(r"(?<=[.!?])\s+", plain):
            cleaned = sentence.strip()
            if len(cleaned) < 20:
                continue
            lexical = shared_topics(stems, content_stems(cleaned))
            numeric = len(asked_numbers & numbers_in(cleaned))
            if lexical or numeric:
                ranked.append(((numeric, lexical), cleaned))
    if not ranked:
        return ""
    ranked.sort(key=lambda item: item[0], reverse=True)
    best = ranked[0][0]
    picked: list[str] = []
    for score, sentence in ranked:
        if score != best or sentence in picked:
            continue
        picked.append(sentence)
        if len(picked) >= limit:
            break
    asked = question.lower()
    if len(picked) > 1 and not any(word in asked for word in ("залог", "срок", "лет", "можно")):
        without_denial = [sentence for sentence in picked if not any(part in sentence.lower() for part in _DENIALS)]
        if without_denial:
            picked = without_denial
    return " ".join(picked)


def offer_numbers(question: str, chunks: list[dict]) -> str:
    asked = question.lower()
    if "ставк" in asked:
        markers = ("ставк", "сумма от")
    elif "срок" in asked and "лет" not in asked:
        markers = ("срок",)
    else:
        return ""
    picked: list[str] = []
    specific = [chunk for chunk in chunks if not chunk["source"].startswith("00-")]
    for chunk in (specific[:1] or chunks[:1]):
        plain = re.sub(r"^#+\s+.*$", "", chunk["text"], flags=re.M)
        for sentence in re.split(r"(?<=[.!?])\s+", plain):
            cleaned = sentence.strip()
            if len(cleaned) < 12:
                continue
            lowered = cleaned.lower()
            if any(marker in lowered for marker in markers) and cleaned not in picked:
                picked.append(cleaned)
            if len(picked) >= 3:
                return " ".join(picked)
    return " ".join(picked)


_DECLINE = (
    "не могу", "не подскаж", "не отвеч", "не знаю", "нет информац", "нет данных",
    "не наш", "этого нет", "такого нет", "нет сведен", "не относ", "не про",
    "не вижу", "не содержит", "не указан", "нет в ", "нет ответ", "не встреч",
)


def declines(text: str) -> bool:
    lowered = text.lower().replace("ё", "е")
    return any(part in lowered for part in _DECLINE)


def mentions_question(answer: str, question: str) -> bool:
    asked = content_stems(question)
    if not asked:
        return True
    return shared_topics(asked, content_stems(answer)) >= 1


_GENERIC = {
    "кредит", "ставк", "срок", "сумм", "рубл", "месяц", "годов",
    "анкет", "продукт", "выручк", "решен", "счита", "деньг",
}


def is_follow_up(question: str) -> bool:
    raw = question.lower().replace("ё", "е").strip()
    if not raw or len(raw) > 48:
        return False
    return raw.startswith(("а ", "и ", "тогда", "еще", "по нему", "у него", "у нее"))


def refers_to_prior(question: str) -> bool:
    raw = question.lower().replace("ё", "е").strip()
    if not raw:
        return False
    if raw.startswith(("а ", "и ", "тогда", "еще", "по нему", "у него", "у нее")):
        return True
    return any(part in raw for part in (
        "этот", "этого", "этому", "него", "нему", "нее", "ней",
        "подробн", "еще", "расскаж", "про него", "по нему", "об этом",
    ))


def wants_more(question: str) -> bool:
    raw = question.lower().replace("ё", "е")
    return any(part in raw for part in ("еще", "подробн", "расскаж", "что можешь", "что знаешь"))


def focus_product(chunks: list[dict], prior_text: str) -> list[dict]:
    if len(chunks) < 2 or not prior_text.strip():
        return chunks
    anchor = content_stems(prior_text) - _GENERIC
    if not anchor:
        return chunks
    specific = [chunk for chunk in chunks if not chunk["source"].startswith("00-")]
    scored = [
        (shared_topics(anchor, chunk["stems"]), chunk)
        for chunk in specific
    ]
    pointed = [(score, chunk) for score, chunk in scored if score]
    if not pointed:
        return specific or chunks
    best = max(score for score, _chunk in pointed)
    return [chunk for score, chunk in pointed if score == best]


def card_facts(chunk: dict, limit: int = 6) -> str:
    plain = re.sub(r"^#+\s+.*$", "", chunk["text"], flags=re.M)
    sentences = []
    for sentence in re.split(r"(?<=[.!?])\s+", plain):
        cleaned = sentence.strip()
        if len(cleaned) >= 12:
            sentences.append(cleaned)
        if len(sentences) >= limit:
            break
    return " ".join(sentences)


def grounded(answer: str, context: str) -> bool:
    cleaned = answer.strip()
    if not cleaned or len(cleaned) < 20 or len(cleaned) > 500:
        return False
    lowered = cleaned.lower()
    if "json" in lowered or "{" in cleaned:
        return False
    return numbers_in(cleaned).issubset(numbers_in(context))


def shared_topics(left: set[str], right: set[str]) -> int:
    count = 0
    for word in left:
        for other in right:
            if word == other or (
                len(word) >= 5 and len(other) >= 5 and (word.startswith(other) or other.startswith(word))
            ):
                count += 1
                break
    return count


def rank(question: str, chunks: list[dict], vectors: list[list[float]], query: list[float], limit: int = 2) -> list[dict]:
    stems = content_stems(question)
    if not stems or len(vectors) != len(chunks) or not query:
        return []
    ranked = []
    for chunk, vector in zip(chunks, vectors):
        overlap = shared_topics(stems, chunk["stems"])
        if overlap == 0:
            continue
        ranked.append((overlap, cosine(query, vector), chunk))
    if not ranked:
        return []
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best = ranked[0][0]
    return [chunk for overlap, _score, chunk in ranked if overlap == best][:limit]
