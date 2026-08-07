FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY backend ./backend
COPY modeling ./modeling
COPY data/contracts ./data/contracts
RUN pip install --no-cache-dir .

USER 65532
CMD ["python", "-m", "prem_engine_api.jobs.dispatcher"]
