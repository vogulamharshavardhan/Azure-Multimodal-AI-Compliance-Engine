FROM python:3.14-slim

ARG DENO_VERSION=2.9.8
ARG TARGETARCH

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_LINK_MODE=copy \
    DENO_DIR=/tmp/deno

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    case "${TARGETARCH:-amd64}" in \
      amd64) deno_arch="x86_64"; deno_sha256="e890975bc2549807bbcc0b584ffafda72cc7c93349dd99c80483dd784f6c4609" ;; \
      arm64) deno_arch="aarch64"; deno_sha256="d49596c20b9788cf8f5d8ddf644103d4bde56ed239753f0bdb92ba9361d51905" ;; \
      *) echo "Unsupported Deno architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/deno-${deno_arch}-unknown-linux-gnu.zip" -o /tmp/deno.zip; \
    echo "${deno_sha256}  /tmp/deno.zip" | sha256sum -c -; \
    unzip -q /tmp/deno.zip -d /tmp/deno-bin; \
    install -m 0755 /tmp/deno-bin/deno /usr/local/bin/deno; \
    rm -rf /tmp/deno.zip /tmp/deno-bin

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml uv.lock .python-version ./

RUN uv sync --python /usr/local/bin/python3.14 --frozen --no-dev --no-install-project \
    && chmod -R a+rX /app/.venv

COPY backend ./backend
COPY main.py README.md .env.example ./

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/logs \
    && chown -R appuser:appuser /app \
    && chmod -R a+rX /app/.venv

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD /app/.venv/bin/python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

CMD ["/app/.venv/bin/uvicorn", "backend.src.api.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
