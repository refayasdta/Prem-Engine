FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

COPY pyproject.toml README.md ./
COPY backend ./backend
COPY modeling ./modeling
RUN pip install --no-cache-dir .

USER 65532
CMD ["sh", "-c", "uvicorn prem_engine_api.main:app --host 0.0.0.0 --port ${PORT}"]
