# Keitaro Campaign Editor

A local web app for creating Keitaro campaigns and editing the offers inside their flows,
with a staged **fetch → edit → push** workflow, share pinning, and recovery of offers that
were removed directly in Keitaro.

> Status: scaffolding. Full setup, migration and run instructions will land here.

## Requirements

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Access to a Keitaro tracker and an Admin API key

## Configuration

```bash
cp .env.example .env   # then fill in KEITARO_BASE_URL and KEITARO_API_KEY
```

`.env` is gitignored; the API key is only ever read by the backend.

## Run (backend)

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
# check connectivity: http://127.0.0.1:8000/api/keitaro/ping
```

## Tests

```bash
cd backend && uv run pytest
```

## License

Proprietary — all rights reserved. See [LICENSE](LICENSE).
