FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /service
COPY pyproject.toml ./
COPY app ./app
COPY models ./models
RUN pip install --no-cache-dir .

EXPOSE 8000
ENV PORT=8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
