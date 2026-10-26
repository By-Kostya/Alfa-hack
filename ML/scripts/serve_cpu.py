#!/usr/bin/env python3
"""Голос подбора в Docker: та же Qwen2.5-1.5B, квант Q4, только CPU.

MLX сюда не входит. Веса качаются в том при первом старте, около 1.1 ГБ.
Адаптер не подключается.
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
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


def megabytes(size: int) -> str:
    return f"{size / (1024 * 1024):.0f}"


def progress_line(done: int, total: int) -> str:
    if total > 0:
        return f"Qwen ещё качается, контейнер не готов: {megabytes(done)} / {megabytes(total)} МБ"
    return f"Qwen ещё качается, контейнер не готов: скачано {megabytes(done)} МБ"


def download_model(url: str, dest: Path) -> None:
    partial = dest.with_name(dest.name + ".partial")
    have = partial.stat().st_size if partial.is_file() else 0
    headers = {"User-Agent": "alfa-credit-qwen"}
    if have:
        headers["Range"] = f"bytes={have}-"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        status = getattr(response, "status", 200)
        if status == 200:
            have = 0
            mode = "wb"
        else:
            mode = "ab"
        incoming = int(response.headers.get("Content-Length") or "0")
        span = response.headers.get("Content-Range") or ""
        if "/" in span and span.rsplit("/", 1)[-1].isdigit():
            total = int(span.rsplit("/", 1)[-1])
        elif status == 206:
            total = incoming + have
        else:
            total = incoming
        print(progress_line(have, total), flush=True)
        mark = have
        with partial.open(mode) as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                have += len(chunk)
                if have - mark >= 32 * 1024 * 1024:
                    mark = have
                    print(progress_line(have, total), flush=True)
    partial.replace(dest)


def ensure_model() -> Path:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    target = MODEL_DIR / FILE
    if target.is_file() and target.stat().st_size > 1_000_000:
        print("Qwen уже скачана. Гружу модель в память, контейнер ещё не готов.", flush=True)
        return target
    from huggingface_hub import hf_hub_url

    url = hf_hub_url(REPO, FILE)
    print("Qwen ещё качается, контейнер не готов. Первый запуск, около 1.1 ГБ.", flush=True)
    last_error: Exception | None = None
    for _attempt in range(4):
        try:
            download_model(url, target)
            break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            print("Qwen ещё качается, контейнер не готов: связь оборвалась, качаю дальше.", flush=True)
    else:
        raise RuntimeError("не удалось скачать Qwen") from last_error
    print(
        f"Qwen скачана: {megabytes(target.stat().st_size)} МБ. Гружу модель в память, контейнер ещё не готов.",
        flush=True,
    )
    return target


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
    print("Qwen готова, контейнер поднят.", flush=True)
    voice.serve(HOST, PORT)


if __name__ == "__main__":
    main()
