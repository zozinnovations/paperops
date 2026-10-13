FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    WHISPER_DIR=/models
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

RUN useradd --create-home paperops && mkdir -p /models /app/cache && chown paperops /models /app/cache
USER paperops

# Bake the Whisper model into the image so the container starts without downloading it
ARG WHISPER_MODEL=small.en
ENV WHISPER_MODEL=${WHISPER_MODEL}
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('${WHISPER_MODEL}', device='cpu', compute_type='int8', download_root='/models')"
# the model is in the image: never contact the Hugging Face hub at runtime
ENV HF_HUB_OFFLINE=1

COPY app ./app
COPY data ./data
COPY samples ./samples
COPY replay ./replay

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
