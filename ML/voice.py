"""Общий голос подбора: /paraphrase и /answer.

Процесс сам подставляет генерацию и вектор. Здесь нет MLX и нет весов.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from rag import (
    apply_center,
    card_facts,
    center,
    declines,
    faithful,
    focus_product,
    grounded,
    load_chunks,
    mentions_question,
    offer_numbers,
    rank,
    refers_to_prior,
    supporting_sentences,
    wants_more,
)

ROOT = Path(__file__).resolve().parent
KNOWLEDGE = ROOT / "knowledge"

generate_text = None
embed_text = None
_lock = threading.Lock()

CHUNKS: list[dict] = []
VECTORS: list[list[float]] = []
CENTER: list[float] = []

INSTRUCTION = (
    "Перефразируй фразу сотрудника банка одной-двумя живыми фразами по-русски. "
    "Смысл остаётся тем же. Если во фразе есть вопрос, задай тот же вопрос и оставь знак вопроса. "
    "Вопрос «на что» не заменяй на «почему». "
    "Числа, ставку, сумму, срок и название продукта копируй как во фразе и не добавляй новых. "
    "Не говори слов JSON, модель, формула."
)

ANSWER_INSTRUCTION = (
    "Ответь на последнюю реплику одним-двумя предложениями по-русски и прямо по фрагменту. "
    "Недавний разговор нужен только чтобы понять, о каком продукте речь. "
    "Если во фрагменте есть ставка, срок, сумма или залог, перескажи этот факт. "
    "Числа копируй цифрами как во фрагменте и не добавляй новых. "
    "Фразу «нет данных» пиши только если фрагмент вообще не про этот вопрос. "
    "Не говори слов JSON, модель, формула."
)

REFUSAL_INSTRUCTION = (
    "Ты сотрудник банка. В карточках нет ответа на последнюю реплику. "
    "Напиши только отказ, одно предложение. Повтори тему вопроса и скажи, что в условиях кредита этого нет. "
    "Недавний разговор можно упомянуть, если он про кредит. "
    "Не описывай саму тему, не выдумывай факты и не отвечай из общих знаний. "
    "Пример: на вопрос «какая погода в Сочи?» ответ «Про погоду в Сочи в условиях кредита сказать не могу.» "
    "Не говори слов JSON, модель, формула."
)


def encode(text: str) -> list[float]:
    with _lock:
        return [float(value) for value in embed_text(text)]


def complete(system: str, messages: list[dict], max_tokens: int) -> str:
    with _lock:
        return str(generate_text(system, messages, max_tokens)).strip()


def build_index() -> None:
    global CHUNKS, VECTORS, CENTER
    CHUNKS = load_chunks(KNOWLEDGE)
    raw = [encode(chunk["text"]) for chunk in CHUNKS]
    if not raw:
        VECTORS = []
        CENTER = []
        return
    VECTORS, CENTER = center(raw)
    print(f"карточек продуктов: {len(CHUNKS)}", flush=True)


def read_history(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    turns = []
    for item in raw[-6:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        text = item.get("text")
        if role not in ("user", "assistant") or not isinstance(text, str):
            continue
        cleaned = text.strip()[:300]
        if cleaned:
            turns.append({"role": role, "text": cleaned})
    return turns


def dialogue(history: list[dict], question: str, preface: str = "") -> list[dict]:
    messages = [{"role": turn["role"], "content": turn["text"]} for turn in history]
    content = question if not preface else f"{preface}\n\nВопрос:\n{question}"
    messages.append({"role": "user", "content": content})
    return messages


def prior_user_lines(history: list[dict]) -> list[str]:
    return [turn["text"] for turn in history if turn["role"] == "user"][-2:]


def last_assistant_line(history: list[dict]) -> list[str]:
    return [turn["text"] for turn in history if turn["role"] == "assistant"][-1:]


def find_cards(question: str, history: list[dict]) -> tuple[str, list[dict]]:
    prior = prior_user_lines(history)
    spoken = last_assistant_line(history) if refers_to_prior(question) else []
    query = question
    if refers_to_prior(question) and (prior or spoken):
        query = "\n".join([*prior, *spoken, question])
    found = rank(query, CHUNKS, VECTORS, apply_center(encode(query), CENTER))
    if not found and query != question:
        query = question
        found = rank(query, CHUNKS, VECTORS, apply_center(encode(query), CENTER))
    anchor = "\n".join([*prior, *spoken])
    if anchor.strip():
        found = focus_product(found, anchor)
    return query, found


def topic_refusal(question: str) -> str:
    asked = " ".join(question.strip().rstrip("?").split())
    if len(asked) > 180:
        asked = asked[:180].rstrip()
    return f"Про «{asked}» в условиях кредита сказать не могу: в карточках этого нет."


def refuse(question: str, history: list[dict]) -> dict:
    allowed = "\n".join([question, *[turn["text"] for turn in history]])
    text = complete(REFUSAL_INSTRUCTION, dialogue(history, question), 80)
    print(f"rag отказ: {text}", flush=True)
    if declines(text) and mentions_question(text, question) and grounded(text, allowed):
        return {"status": "answer", "text": text, "from": "model"}
    return {"status": "answer", "text": topic_refusal(question), "from": "card"}


def answer(question: str, history: list[dict] | None = None) -> dict:
    if not CHUNKS or not CENTER:
        return {"status": "unavailable"}
    turns = history or []
    query, found = find_cards(question, turns)
    if not found:
        return refuse(question, turns)
    context = "\n\n".join(chunk["text"] for chunk in found)
    if wants_more(question):
        support = " ".join(card_facts(chunk) for chunk in found[:1])
    else:
        support = offer_numbers(question, found) or supporting_sentences(question, found)
    text = complete(
        ANSWER_INSTRUCTION,
        dialogue(turns, question, f"Фрагменты:\n{context}"),
        160,
    )
    print(f"rag ответ: {text}", flush=True)
    safe = "нет данных" not in text.lower() and grounded(text, context) and faithful(text, support)
    if safe:
        return {"status": "answer", "text": text, "from": "model"}
    if support and grounded(support, context):
        return {"status": "answer", "text": support, "from": "card"}
    if "нет данных" in text.lower():
        return refuse(question, turns)
    return {"status": "ungrounded"}


def paraphrase(payload: str) -> str:
    return complete(INSTRUCTION, [{"role": "user", "content": payload}], 120)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path != "/health":
            self.send_error(404)
            return
        if CHUNKS and CENTER and generate_text is not None:
            self._send(200, {"status": "ok"})
            return
        self._send(503, {"status": "error", "reason": "model"})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length") or "0")
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:
            self.send_error(400)
            return
        try:
            if path == "/paraphrase":
                draft = body.get("draft")
                if not isinstance(draft, str) or not draft.strip():
                    brief = body.get("brief")
                    if not isinstance(brief, dict):
                        raise ValueError("brief")
                    draft = json.dumps(brief, ensure_ascii=False)
                payload = {"text": paraphrase(draft.strip())}
            elif path == "/answer":
                question = body.get("question")
                if not isinstance(question, str) or not question.strip():
                    raise ValueError("question")
                payload = answer(question.strip(), read_history(body.get("history")))
            else:
                self.send_error(404)
                return
        except Exception:
            self.send_error(400)
            return
        self._send(200, payload)

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} {fmt % args}", flush=True)


def serve(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"голос подбора http://{host}:{port}/paraphrase", flush=True)
    print(f"ответы по карточкам http://{host}:{port}/answer", flush=True)
    server.serve_forever()
