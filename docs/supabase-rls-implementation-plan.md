# Implementation Plan: Supabase RLS Evaluation

**Status:** proposal, not yet implemented (reviewed 2026-07-08 — see `with check` fix in
Part D, pooler note in Part B, rollback switch in Part D, test-fixture clarification in Part F)
**Date:** 2026-07-08

## Goal

Migrate the database layer to Supabase Postgres and turn on **Row-Level Security (RLS)** as a
second, database-enforced layer of Client isolation, on top of the `client_id` filtering the
app already does. Full narrative and rationale live in
[`apps/docs/src/content/docs/supabase-rls-poc.mdx`](../apps/docs/src/content/docs/supabase-rls-poc.mdx);
this document is the working checklist referred to during implementation, not the pitch.

Scope is deliberately narrow: prove RLS works against the real schema and the real
`search_docs` hot path, using the smallest possible auth model. Admin UI, end-user accounts,
and production migration off self-hosted Postgres are explicitly **not** part of this plan.

## Decisions (locked)

- **Local dev runs the Supabase CLI stack (`supabase start`), alongside
  `infra/docker-compose.yml`, not a hosted dev project.** The Access Token Hook needs GoTrue
  (Supabase's Auth service) running to fire at all; plain `pgvector/pgvector:pg16`, what the
  current `db` service runs, has no Auth service. A hosted project would work too, but trades
  container weight for network latency on every local request — not worth it for a dev loop
  that today is a local socket.
- **Auth is one Supabase Auth account per Client, not per human.** `client_id` lives in that
  account's `user_metadata`. A Custom Access Token Hook (a Postgres function GoTrue calls at
  token-mint time) copies it into the JWT's claims. This is real Supabase Auth, not a
  hand-signed stand-in, but it's still the smallest version that gives a policy something to
  check — no end-user accounts yet.
- **Two new Postgres roles, not one.** Request traffic connects as the non-superuser
  `authenticated` role (RLS applies). The CLI ingestion path (`app.cli ingest --client`) keeps
  its own `service_role` credential (RLS bypass), mirroring how it already takes `--client` as
  a trusted argument today. This is a deliberate boundary, not an oversight — see Part D.
- **RLS goes live only after the auth model is already issuing real claims.** Enabling
  policies before the Access Token Hook works end-to-end doesn't error; every query returns
  zero rows for every Client at once, because `current_setting('request.jwt.claims')` is null.
  Part C must be verified working in isolation before Part D runs.
- **Schema does not move.** Supabase is vanilla Postgres plus pgvector. The existing Alembic
  migration (`0001_initial_schema.py`) and `apps/api/app/models.py` are portable as-is.

## Anatomy reference (state today)

- **Connection:** `apps/api/app/database.py` and `apps/api/alembic/env.py` both default to
  `postgresql+asyncpg://postgres:postgres@localhost:5432/configent` — Postgres superuser,
  which would make RLS a silent no-op if left unchanged.
- **Isolation today:** every table with a `client_id` column is filtered by app code that has
  always been correct but is never checked: `apps/api/app/retrieval/search.py`
  (`.where(Chunk.client_id == client_id)`), `apps/api/app/ingest.py`, and the routers.
- **Client binding today:** `client_id` is a trusted, unverified path param
  (`/c/{client_id}/chat` in `apps/api/app/routers/clients.py`). No session, no signature,
  nothing a policy could key off.
- **No auth exists anywhere in the app.** No JWT library in `apps/api/pyproject.toml`, no auth
  middleware, no `conftest.py` in `apps/api/tests/` (tests import `AsyncSessionLocal` directly
  and inherit the superuser connection).
- **Tables carrying `client_id` directly:** `clients`, `documents`, `chunks`, `conversations`,
  `eval_runs`. Scoped via `conversation_id` join instead: `messages`, `traces`.

---

## Part A — Supabase project setup

1. **Create the Supabase project** (or run `supabase init` for the local CLI stack).
2. **Enable pgvector:** `create extension if not exists vector;` — same statement
   `db/init.sql` already runs against the current Docker `db` service; Supabase ships pgvector
   but it isn't on by default.
3. **Run `supabase start`** to bring up Postgres, GoTrue, and Studio locally, alongside the
   existing `infra/docker-compose.yml` (don't remove the `db` service yet — see Part F).
4. **Capture connection strings** for both roles needed in Part B: `authenticated` and
   `service_role`. Supabase ships `anon`/`authenticated`/`service_role` by default; Configent
   doesn't create these roles, only grants them table privileges in Part D.

## Part B — Roles and connections

1. **Grant table privileges** to `authenticated` (SELECT/INSERT/UPDATE/DELETE on all
   `client_id`-scoped tables) and confirm `service_role` retains its RLS-bypass default.
2. **Update `apps/api/app/database.py`** to read the `authenticated`-role connection string
   for request traffic (env var, not hardcoded). **If that connection string points at
   Supabase's pooler (pgbouncer, transaction mode) rather than Postgres directly**, asyncpg's
   default use of server-side prepared statements is known to break under transaction-mode
   pooling (`prepared statement "..." already exists` / "does not exist" errors, since
   pgbouncer can route consecutive queries to different backend connections). Either pass
   `connect_args={"statement_cache_size": 0}` to `create_async_engine` for this connection, or
   use the pooler's session-mode port / connect directly to Postgres for the `authenticated`
   role. Decide this here, in Part B, not as an afterthought in Part G — it changes what
   connection string Part G3 is even validating.
3. **Update `apps/api/app/cli.py`** to use its own `service_role` credential, separate from
   `database.py`'s engine — it currently builds its own engine directly from `DATABASE_URL`,
   so this is a targeted change, not a shared-code refactor.
4. **Update `apps/api/alembic/env.py`** to point at the Supabase connection string so
   `0001_initial_schema.py` can run against it unchanged, proving schema parity before any
   RLS-specific migration is written.
5. **Add JWT library** to `apps/api/pyproject.toml` (`pyjwt` or equivalent) — no JWT
   verification package exists in the project today.

## Part C — Auth model (must work before Part D)

1. **Provision one Supabase Auth account per Client** (starting with `acme-fab`), with
   `client_id` set in that account's `user_metadata`.
2. **Write and deploy the Custom Access Token Hook** — a Postgres function that reads
   `user_metadata.client_id` and copies it into the JWT's claims — and register it in the
   Supabase project's Auth settings.
3. **Verify in isolation, with no RLS policies active yet:** log in as the `acme-fab` account,
   decode the returned JWT, confirm the `client_id` claim is present and correct. This step
   has to pass before Part D starts, per the locked ordering decision above.
4. **Add a FastAPI dependency** in `apps/api/app/routers/clients.py` that verifies the JWT on
   `/c/{client_id}/chat` and `/chat/stream`, and issues `SET LOCAL request.jwt.claims` inside
   the same transaction as the query — replacing the currently-unchecked `client_id` path
   param with a claim the database will independently check once Part D lands.

## Part D — RLS policies

1. **New Alembic migration** adding `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` plus a
   `create policy` for each table. **Every policy needs both `using` and `with check`** — a
   bare `using` clause only gates which existing rows are visible for `SELECT`/`UPDATE`/
   `DELETE`; without `with check`, an `UPDATE` can still rewrite a row's `client_id` to a
   *different* tenant (the old row satisfies `using`, and nothing validates the new row), and
   `INSERT` isn't checked by `using` at all — the table would accept an insert for any
   `client_id`, RLS or not. This is the actual isolation guarantee this evaluation is meant to
   prove, so getting it wrong here defeats the point silently (no error, just a hole):
     - Direct `client_id` compare (same shape for all): `clients`, `documents`, `chunks`,
       `conversations`, `eval_runs`.
       ```sql
       create policy client_isolation on chunks
         using (client_id = current_setting('request.jwt.claims', true)::json->>'client_id')
         with check (client_id = current_setting('request.jwt.claims', true)::json->>'client_id');
       ```
     - `EXISTS`-join shape (no `client_id` column of their own): `messages`, `traces`.
       ```sql
       create policy client_isolation on messages
         using (exists (
           select 1 from conversations c
           where c.id = messages.conversation_id
             and c.client_id = current_setting('request.jwt.claims', true)::json->>'client_id'
         ))
         with check (exists (
           select 1 from conversations c
           where c.id = messages.conversation_id
             and c.client_id = current_setting('request.jwt.claims', true)::json->>'client_id'
         ));
       ```
2. **Apply only after Part C is verified working end-to-end** (see the locked ordering
   decision — this is the one step in this plan that can silently break everything if run out
   of order).
3. **No changes needed** to `apps/api/app/ingest.py` or `apps/api/app/retrieval/search.py`;
   both already filter by `client_id`, so RLS makes that filter mandatory instead of trusted.
4. **Have a rollback switch ready before flipping this on**: `ALTER TABLE ... DISABLE ROW
   LEVEL SECURITY` per table (or a single down-migration) that can be run without waiting on a
   redeploy, since Part G's negative-test demo and the HNSW check both assume the app stays
   reachable while things are being debugged live.

## Part E — CLI boundary (deliberate, not deferred)

1. **Confirm `app.cli ingest --client` runs on `service_role`**, bypassing RLS by design — it
   already takes `--client` as a trusted argument today, so this mirrors current behavior.
2. **Document the boundary explicitly** wherever the CLI is referenced: it stays a second,
   unguarded write path into the same tables RLS proves are isolated for request traffic. Not
   a gap to close in this evaluation, but not something to let go unstated either.

## Part F — Local dev and test infra

1. **Keep `infra/docker-compose.yml`'s `db` service** for anything that doesn't need the auth
   path (fast unit tests, non-RLS work); don't rip it out.
2. **Add a `conftest.py`** to `apps/api/tests/` providing a non-superuser, claim-aware
   fixture — today every test imports `AsyncSessionLocal` directly and inherits the superuser
   connection, which would pass even if a policy were broken. This fixture does not need to go
   through a real GoTrue login per test (too slow, and couples every RLS test to Auth being
   up) — it can connect as `authenticated` and issue `SET LOCAL request.jwt.claims` directly
   with a synthetic claim, since what's under test is the policy, not the token-minting path
   (Part C already covers that in isolation).
3. **Point RLS-specific integration tests** at the Supabase CLI stack from Part A.
4. **Confirm `DEV_CONFIG_RELOAD`-style hot reload still works** against the new stack — it's a
   client-config reload loop, not a DB concern, but worth a smoke check once the connection
   target changes.

## Part G — Validation

1. **Run the negative-test demo:** authenticate as `acme-fab`, run `search_docs` with the
   app's `WHERE client_id` clause intact, confirm results; drop the clause, run again, confirm
   the result is unchanged because RLS is now doing the filtering.
2. **Run `EXPLAIN ANALYZE`** on a representative `search_docs` query to confirm which plan
   Postgres picks under RLS: `client_id`-first (loses the `ix_chunks_embedding_hnsw` HNSW
   index, falls back to a sequential scan) or HNSW-first (risks fewer than `k` results if too
   many top matches belong to other Clients). If the planner drops the HNSW index, try
   `SET LOCAL hnsw.iterative_scan` (pgvector ≥0.7).
3. **Confirm `SET LOCAL` survives Supabase's connection pooler** (pgbouncer, transaction
   mode) — if claims don't stick, the app may need a session-mode connection string instead.
4. **Confirm the Access Token Hook's refresh behavior:** does it re-run on token refresh, or
   only at initial sign-in? If `user_metadata.client_id` changes, does an already-issued
   session pick it up, or does it need a forced re-login?

---

## Execution order

A (project + pgvector + local stack) → B (roles, connections, JWT dependency, schema parity)
→ C (auth model, verified in isolation) → D (RLS policies, only after C passes) → E (confirm
CLI boundary) → F (local/test infra) → G (validation, including the negative-test demo and the
HNSW `EXPLAIN ANALYZE` check).

The hard gate is C → D: nothing in D should run until a real login through C returns a JWT
with the correct `client_id` claim.
