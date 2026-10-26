#!/usr/bin/env python3
"""Голос подбора на Mac через MLX. В Docker эта сборка не используется.

Адаптер экстрактора не подключается. Веса не меняются.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import voice  # noqa: E402

LOCAL = ROOT / "models" / "extractor" / "base"
HOST = "127.0.0.1"
PORT = 8766

MODEL = None
TOKENIZER = None
GENERATE = None


def model_id() -> str:
    if (LOCAL / "model.safetensors").is_file():
        return str(LOCAL)
    return "mlx-community/Qwen2.5-1.5B-Instruct-4bit"


def embed_text(text: str) -> list[float]:
    import mlx.core as mx

    ids = list(TOKENIZER.encode(text))[:256]
    if not ids:
        ids = [0]
    hidden = MODEL.model(mx.array([ids]))
    mx.eval(hidden)
    last = hidden[0, -1]
    return [float(value) for value in last.tolist()]


def generate_text(system: str, messages: list[dict], max_tokens: int) -> str:
    prompt = TOKENIZER.apply_chat_template(
        [{"role": "system", "content": system}, *messages],
        add_generation_prompt=True,
        tokenize=False,
    )
    return str(GENERATE(MODEL, TOKENIZER, prompt=prompt, max_tokens=max_tokens, verbose=False))


def main() -> None:
    global MODEL, TOKENIZER, GENERATE
    from mlx_lm import generate, load

    GENERATE = generate
    chosen = model_id()
    print(f"загружаю базовую Qwen без адаптера: {chosen}", flush=True)
    MODEL, TOKENIZER = load(chosen)
    voice.embed_text = embed_text
    voice.generate_text = generate_text
    try:
        voice.build_index()
    except Exception as exc:
        print(f"карточки не проиндексированы: {exc}", flush=True)
    voice.serve(HOST, PORT)


if __name__ == "__main__":
    main()
