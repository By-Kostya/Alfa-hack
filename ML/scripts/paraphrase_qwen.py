#!/usr/bin/env python3
"""Голос подбора на базовой Qwen2.5-1.5B-Instruct.

Адаптер экстрактора не подключается: модель не дообучена под этот чат.
Она получает JSON, который уже посчитала формула, и возвращает одну фразу.
Веса не меняются.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "models" / "extractor" / "base"
HOST = "127.0.0.1"
PORT = 8766

MODEL = None
TOKENIZER = None
GENERATE = None

INSTRUCTION = (
    "Перефразируй фразу сотрудника банка одной-двумя живыми фразами по-русски. "
    "Смысл остаётся тем же. Если во фразе есть вопрос, задай тот же вопрос и оставь знак вопроса. "
    "Вопрос «на что» не заменяй на «почему». "
    "Числа, ставку, сумму, срок и название продукта копируй как во фразе и не добавляй новых. "
    "Не говори слов JSON, модель, формула."
)


def model_id() -> str:
    if (LOCAL / "model.safetensors").is_file():
        return str(LOCAL)
    return "mlx-community/Qwen2.5-1.5B-Instruct-4bit"


def paraphrase(payload: str) -> str:
    prompt = TOKENIZER.apply_chat_template(
        [
            {"role": "system", "content": INSTRUCTION},
            {"role": "user", "content": payload},
        ],
        add_generation_prompt=True,
        tokenize=False,
    )
    text = GENERATE(MODEL, TOKENIZER, prompt=prompt, max_tokens=120, verbose=False)
    return str(text).strip()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/paraphrase":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or "0")
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            draft = body.get("draft")
            if not isinstance(draft, str) or not draft.strip():
                brief = body.get("brief")
                if not isinstance(brief, dict):
                    raise ValueError("brief")
                draft = json.dumps(brief, ensure_ascii=False)
            text = paraphrase(draft.strip())
        except Exception:
            self.send_error(400)
            return
        raw = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} {fmt % args}", flush=True)


def main() -> None:
    global MODEL, TOKENIZER, GENERATE
    from mlx_lm import generate, load

    GENERATE = generate
    chosen = model_id()
    print(f"загружаю базовую Qwen без адаптера: {chosen}", flush=True)
    MODEL, TOKENIZER = load(chosen)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"голос подбора http://{HOST}:{PORT}/paraphrase", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
