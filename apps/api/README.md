# HyMail API

FastAPI local service for HyMail.

## Development

    uv python install 3.12
    uv sync
    uv run ruff check .
    uv run pytest
    uv run uvicorn hymail_api.main:app --reload --host 127.0.0.1 --port 8000