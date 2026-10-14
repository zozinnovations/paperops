FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    WHISPER_DIR=/models
WORKDIR /app

# Security: install the latest Debian security patches of the base image, keep no package lists
RUN apt-get update \
 && apt-get upgrade -y \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install -r requirements.txt

# Security: run as an unprivileged user with a fixed UID and no login shell.
# Only /models (filled at build time) and /app/cache are writable for it; the app code stays root-owned/read-only.
RUN groupadd --system --gid 10001 paperops \
 && useradd --system --uid 10001 --gid paperops --create-home --shell /usr/sbin/nologin paperops \
 && mkdir -p /models /app/cache \
 && chown paperops:paperops /models /app/cache
USER paperops

# Bake the Whisper model into the image so the container starts without downloading it
ARG WHISPER_MODEL=base.en
ENV WHISPER_MODEL=${WHISPER_MODEL}
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('${WHISPER_MODEL}', device='cpu', compute_type='int8', download_root='/models')"
# the model is in the image: never contact the Hugging Face hub at runtime
ENV HF_HUB_OFFLINE=1

COPY app ./app
COPY data ./data
COPY samples ./samples
COPY replay ./replay

# the port to listen on (container platforms set $PORT)
ENV PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health', timeout=4)"
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips '*'"]
