# Backend integration notes

This branch exposes the confirmed `/api` paths through FastAPI. Run the database
migration before starting either process:

```bash
alembic upgrade head
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
python -m backend.app.worker
```

Configuration is environment-only; copy `.env.example` locally and do not commit
secrets. `STORAGE_BACKEND=local` is the development default. Deployment uses
`STORAGE_BACKEND=s3`, `AWS_REGION=us-east-1`, and the EC2 instance role credential
chain. No access key is accepted by application settings.

The live contract is available at `/openapi.json`. Role 4 should add
`backend/app/analysis.py` with `validate_reference` and `analyze` using the confirmed
signatures. Until then reference indexing returns `503 ANALYSIS_UNAVAILABLE`, and the
worker marks queued photos failed rather than claiming analysis succeeded. Role 5
edit and approval routes currently return `501 FEATURE_NOT_CONNECTED` after access
checks. Mock results used by tests always carry `provider=contract-fixture` and
`mode=mock`.

Local validation currently uses an isolated SQLite database because no PostgreSQL
test service is available in this workspace. PostgreSQL migration and concurrency
behavior (`FOR UPDATE SKIP LOCKED`) still require verification against a dedicated
`_test` database before integration.
