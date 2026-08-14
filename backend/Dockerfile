FROM python:3.12-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

COPY requirements.lock pyproject.toml README.md ./
COPY backend ./backend
COPY modeling ./modeling

RUN python -m pip install --prefix=/install -r requirements.lock \
    && python -m pip install --prefix=/install --no-deps .


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/usr/local/bin:$PATH

WORKDIR /app

COPY --from=build /install /usr/local
COPY alembic.ini ./
COPY backend/migrations ./backend/migrations
COPY data/mappings ./data/mappings
COPY artifacts/models/goals/goals-v1-156511483a94/model.joblib \
    ./artifacts/models/goals/goals-v1-156511483a94/model.joblib
COPY artifacts/models/match-statistics/detailed-statistics-v1-42e73adec486/model.joblib \
    ./artifacts/models/match-statistics/detailed-statistics-v1-42e73adec486/model.joblib

RUN mkdir -p /app/data/raw /app/artifacts/local \
    && chown -R 65532:65532 /app/data /app/artifacts

USER 65532:65532

EXPOSE 8000

CMD ["uvicorn", "prem_engine_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
