FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY backend ./backend
COPY modeling ./modeling
COPY data/contracts ./data/contracts
COPY artifacts/models/goals/goals-v1-156511483a94/model.joblib \
    ./artifacts/models/goals/goals-v1-156511483a94/model.joblib
COPY artifacts/models/match-statistics/detailed-statistics-v1-42e73adec486/model.joblib \
    ./artifacts/models/match-statistics/detailed-statistics-v1-42e73adec486/model.joblib
RUN pip install --no-cache-dir .

USER 65532
CMD ["python", "-m", "prem_engine_api.jobs.dispatcher"]
