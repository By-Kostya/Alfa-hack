#!/usr/bin/env python3
"""Голос подбора в Docker: та же Qwen2.5-1.5B, квант Q4, только CPU.

MLX сюда не входит. Веса качаются в том при первом старте, около 1.1 ГБ.
Адаптер не подключается.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import voice  # noqa: E402

REPO = os.environ.get("QWEN_GGUF_REPO", "Qwen/Qwen2.5-1.5B-Instruct-GGUF")
FILE = os.environ.get("QWEN_GGUF_FILE", "qwen2.5-1.5b-instruct-q4_k_m.gguf")
MODEL_DIR = Path(os.environ.get("QWEN_MODEL_DIR", "/models"))
HOST = os.environ.get("QWEN_HOST", "0.0.0.0")
PORT = int(os.environ.get("QWEN_PORT", "8766"))

LLM = None


def threads() -> int:
    raw = os.environ.get("QWEN_THREADS", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    count = os.cpu_count() or 2
    return max(1, min(4, count))


def ensure_model() -> Path:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    target = MODEL_DIR / FILE
    if target.is_file() and target.stat().st_size > 1_000_000:
        return target
    from huggingface_hub import hf_hub_download

    print(f"качаю {REPO}/{FILE}, около 1.1 ГБ", flush=True)
    path = hf_hub_download(repo_id=REPO, filename=FILE, local_dir=str(MODEL_DIR))
    return Path(path)


def embed_text(text: str) -> list[float]:
    raw = LLM.embed(text[:1500])
    if raw and isinstance(raw[0], (list, tuple)):
        raw = raw[-1]
    return [float(value) for value in raw]


def generate_text(system: str, messages: list[dict], max_tokens: int) -> str:
    result = LLM.create_chat_completion(
        messages=[{"role": "system", "content": system}, *messages],
        max_tokens=max_tokens,
        temperature=0.2,
    )
    return result["choices"][0]["message"]["content"]


def main() -> None:
    global LLM
    from llama_cpp import Llama

    path = ensure_model()
    print(f"загружаю Qwen на CPU: {path.name}, потоков {threads()}", flush=True)
    LLM = Llama(
        model_path=str(path),
        n_ctx=2048,
        n_threads=threads(),
        n_gpu_layers=0,
        embedding=True,
        verbose=False,
    )
    voice.embed_text = embed_text
    voice.generate_text = generate_text
    try:
        voice.build_index()
    except Exception as exc:
        print(f"карточки не проиндексированы: {exc}", flush=True)
    voice.serve(HOST, PORT)


if __name__ == "__main__":
    main()
