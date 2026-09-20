# Role 3 — backend, database, and integration

- Run: `20260920` (inferred from the current date; no team run configuration existed)
- Base: `main`
- Role branch: `work/20260920/role-3`
- Integration branch: `assemble/20260920`
- Current stage: roles 1, 3, 4, 5, and 2 assembled in the required order; role 4 analysis, role 5 edits/approvals, and role 2 UI are connected
- Latest integration commits: `9e3c9f8` (role 5 adapters), `489fa0b` (frontend API contract), `4121b80` (album session member response), `da25dfe` (role 2 runtime IDs), `ca76475` (role 5 approval fallback), `c0b60c0`/`63fcd04`/`09a0564` (role 4 follow-ups), `12a5f37` (role 2 detail regression)
- PR: #1 merged role 3 into `main` at `7375bc0`; Draft integration candidate #14 targets `main`
- Checks: Python 3.13.15; 196 pytest cases passed across backend, role 4 analysis/insights/face groups, role 5 editing, worker, API, storage, and infra preflight; frontend typecheck passed; Vitest 4 files/23 tests passed; Vite production build passed; npm audit reported 0 vulnerabilities; Python compileall, shell syntax, and diff checks passed; Alembic upgrade/downgrade/upgrade and `alembic check` previously passed on an empty SQLite test DB
- Remaining: dedicated PostgreSQL migration/concurrency verification, live AWS verification, browser API-mode E2E, EC2 deployment, and role 1 final review
- Blocked dependencies: PostgreSQL `_test` service and AWS resources are unavailable locally; live browser API flow and deployment require a running integrated environment
- Outstanding requests: #3 role 5 backend adapter and #6 role 2 API/runtime identifier work are integrated; #16 burst grouping is resolved in favor of `worker.recompute_bursts`
