$ErrorActionPreference = "Stop"

python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest

Push-Location frontend
try {
    pnpm lint
    pnpm typecheck
    pnpm build
}
finally {
    Pop-Location
}
