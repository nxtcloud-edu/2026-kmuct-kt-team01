# Role 3 — backend, database, and integration

- Run: `20260920` (inferred from the current date; no team run configuration existed)
- Base: `main`
- Role branch: `work/20260920/role-3`
- Integration branch: `assemble/20260920`
- Current stage: roles 1, 3, 4, 5, and 2 assembled in the required order; role 4 analysis, role 5 edits/approvals, and role 2 UI are connected
- Latest integration commits: `9e3c9f8` (role 5 adapters), `1f19b38` (role 2 UI head), `489fa0b` (frontend API contract)
- PR: #1 merged role 3 into `main` at `7375bc0`; Draft integration candidate #14 targets `main`
- Checks: Python 3.13.15; 165 pytest cases passed across backend, role 4 analysis, role 5 editing, worker, API, storage, and infra preflight; Node 24.21.0; frontend typecheck passed; Vitest 3 files/20 tests passed; Vite production build passed; npm audit reported 0 vulnerabilities; shell syntax and diff checks passed; Alembic upgrade/downgrade/upgrade and `alembic check` previously passed on an empty SQLite test DB
- Remaining: replace the role 2 UI's hard-coded `album-demo`/`m-1` runtime identifiers, dedicated PostgreSQL migration/concurrency verification, live AWS verification, browser API-mode E2E, EC2 deployment, and role 1 final review
- Blocked dependencies: PostgreSQL `_test` service and AWS resources are unavailable locally; actual browser API flow cannot be valid until role 2 threads the created/joined album and current member through the app
- Outstanding requests: #3 role 5 backend adapter can be marked APPLIED after this branch is pushed; #6 role 2 API request is implemented at `489fa0b`; role 2 needs a follow-up for runtime album/member state; #16 role 4 burst-dedup request is not yet reviewed
