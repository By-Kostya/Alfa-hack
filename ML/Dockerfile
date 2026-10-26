FROM python:3.12-slim-bookworm AS build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
ENV CMAKE_ARGS="-DGGML_NATIVE=OFF" \
    CMAKE_BUILD_PARALLEL_LEVEL=4
RUN pip install --no-cache-dir --upgrade pip \
    && pip wheel --no-cache-dir -r requirements.txt -w /wheels \
        --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu

FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY rag.py voice.py ./
COPY knowledge ./knowledge
COPY scripts/serve_cpu.py ./scripts/serve_cpu.py

ENV QWEN_HOST=0.0.0.0 \
    QWEN_PORT=8766 \
    QWEN_MODEL_DIR=/models \
    HF_HUB_DISABLE_TELEMETRY=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8766

CMD ["python", "-u", "scripts/serve_cpu.py"]
