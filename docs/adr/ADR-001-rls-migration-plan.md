# ADR-001 — RLS Migration Plan (Row-Level Security activation path)

| Field        | Value |
|--------------|-------|
| **Status**   | Accepted — *records the current architecture and governs future authz decisions* |
| **Date**     | 2026-06-04 |
| **Authors**  | Backend & Infra terminal (EPIC-SEC Fase 2) |
| **Story**    | SEC-CHAT-5 (doc-only) |
| **Supersedes** | — |
| **Related**  | SEC-AUTHZ-0 (application authz helpers), SEC-CHAT-* / SEC-ADMIN-* / SEC-SCOPE-* (IDOR remediations), [REMEDIATION-ROADMAP-2026-06-03.md](../REMEDIATION-ROADMAP-2026-06-03.md) §5 (migration convention, line 343), [BUG-SWEEP-2026-06-03.md](../BUG-SWEEP-2026-06-03.md) (#2, #18) |

---

## 1. Context

Harven.AI is a FastAPI + Supabase application. **The application authorization
layer is the *only* isolation barrier between users/tenants — there is no
Row-Level Security (RLS) policy on any table in the schema.** Two facts from the
bug sweep make this load-bearing:

- **Bug #2 (generalized IDOR in chat-sessions)** — `BUG-SWEEP-2026-06-03.md`
  lines 39–45. Handlers that take a `session_id` / `user_id` by path or body
  only proved a valid JWT (`get_current_user`) and never filtered by
  `current_user["id"]`. The recommended long-term fix is recorded verbatim:
  *"RLS com cliente Supabase por-usuário"* (line 45).
- **Bug #18 (IDOR in gamification)** — `BUG-SWEEP-2026-06-03.md` line 197:
  *"O service_role bypassa RLS"* — confirming the same systemic mechanism.

### Why RLS would be a **no-op today**

The Supabase client is **single, global, and built with the static
`SUPABASE_KEY`, which decodes to the `service_role` JWT — and `service_role`
bypasses every RLS policy by construction.**

Evidence in code (current line numbers):

```text
backend/database.py:5     SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
backend/database.py:10-11 if SUPABASE_URL and SUPABASE_KEY:
                              supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
backend/database.py:14    def get_supabase() -> Client:  # every call site reuses this one privileged client
```

Configuration surface:

```text
backend/config.py:20-21   SUPABASE_URL: str = ""
                          SUPABASE_KEY: str = ""        # service_role key
backend/config.py:28      JWT_SECRET_KEY: str = "change-me-in-production"   # app JWT, not the DB role key
```

Because **every** query in `backend/routes_ai.py`, `backend/routes_admin.py`,
and `backend/main.py` flows through this one `service_role` connection, Postgres
runs each statement with RLS disabled. Adding `CREATE POLICY ...` to the schema
would therefore have **zero runtime effect** — a dangerous form of security
theater (a reviewer could believe the data is isolated when it is not).

---

## 2. Decision

1. **Do NOT add RLS policies while the client is `service_role`.** They are
   inert (no-op) and create a false sense of safety. This is the binding rule
   already referenced by the migration convention in
   `REMEDIATION-ROADMAP-2026-06-03.md` line 343
   (*"Sem novas políticas RLS … documentado em ADR SEC-CHAT-5"*). This ADR is
   that document.
2. **Treat the SEC-AUTHZ-0 application authorization helpers as the effective,
   *temporary* barrier — a hotfix that has shipped, not the target
   architecture.** (See §5.)
3. **Adopt the target architecture: a per-request Supabase client signed with
   the authenticated user's JWT**, so Postgres `auth.uid()` reflects the real
   user and RLS policies become enforceable. (See §4.)

---

## 3. Target tables (will require RLS at migration time)

When the per-request-JWT client lands, the following ownership-bearing tables
need RLS, keyed on the listed ownership predicate. Derived from the live route
queries in `routes_ai.py` / `routes_admin.py` / `main.py`.

| Table                | Ownership predicate (RLS `USING`)                          | Notes |
|----------------------|------------------------------------------------------------|-------|
| `chat_sessions`      | `user_id = auth.uid()`                                      | Bug #2 core; TEACHER/ADMIN override. |
| `chat_messages`      | `session_id IN (SELECT id FROM chat_sessions WHERE user_id = auth.uid())` | Owned transitively via the session. |
| `session_reviews`    | session owner reads; `reviewer_id = auth.uid()` for authoring | Bug #25; create/update is TEACHER/ADMIN. |
| `notifications`      | `user_id = auth.uid()`                                      | Bug #16; create is ADMIN/system. |
| `user_activities`    | `user_id = auth.uid()`                                      | Bug #14 (gamification). |
| `user_achievements`  | `user_id = auth.uid()`                                      | Bug #14. |
| `certificates`       | `user_id = auth.uid()`                                      | Bug #14. |
| `user_stats`         | `user_id = auth.uid()`                                      | Bug #14 (also residual read IDOR — see SEC-ADMIN-6 KNOWN_UNREMEDIATED). |
| `course_progress`    | `user_id = auth.uid()`                                      | Bug #14; certificate eligibility. |
| `users`              | `id = auth.uid()` for self-service fields (e.g. `avatar_url`) | Bug #49; admin override for management. |

> The exact policy DDL is deferred to the migration story. Discipline-scoped
> tables (`disciplines`, `discipline_students`, `discipline_teachers`,
> `grade_overrides`) follow a teacher-scoping predicate rather than a flat
> `user_id` and will be specified alongside the teacher-scoping helper
> (`assert_teacher_owns_discipline`).

---

## 4. Migration path — per-request Supabase client with the user's JWT

**Today (global service_role):**

```text
request ──> get_supabase() ──> single service_role client ──> Postgres (RLS bypassed)
```

**Target (per-request JWT):**

```text
request (Bearer <user JWT>)
   └─> build a Supabase client bound to that access_token
         └─> Postgres sees auth.uid() = the user
               └─> RLS policies enforce ownership in the database
```

Concrete steps (sequenced; each is its own story when scheduled):

1. **Introduce a per-request client factory.** Replace the global
   `database.get_supabase()` singleton with a dependency that creates/configures
   a client carrying the caller's `access_token` (so PostgREST forwards it and
   `auth.uid()` resolves to the user). Keep the service_role client available
   only for genuine system/admin operations (webhooks, migrations, ADMIN tools).
2. **Add RLS policies** to the §3 tables, `user_id = auth.uid()` (and the
   transitive/teacher-scoped variants) — *only after* step 1, never before.
3. **Privilege override.** TEACHER/ADMIN cross-user access continues to be
   expressed at the application layer (or via role-aware policies / a service
   client reserved for privileged paths). The override semantics must match the
   current helpers exactly: ADMIN platform-wide; TEACHER scoped to owned
   disciplines; INSTRUCTOR where applicable.
4. **Retire the redundant inline filters** only once RLS is proven to enforce
   the same predicate (defense-in-depth: keep both during transition).

---

## 5. Current hotfix — SEC-AUTHZ-0 application authz helpers (shipped)

Until step 1 above lands, the **only** thing standing between a logged-in
student and another student's data is the application layer. The SEC-AUTHZ-0
helpers in `backend/authz.py` are that barrier and are **already shipped**:

- `assert_owner_or_role(resource_owner_id, current_user, *roles)` — owner or
  privileged role; deny otherwise.
- `require_self_or_role(path_user_id, current_user, *roles)` — `/users/{user_id}`
  shape.
- `load_session_or_404(client, session_id)` — load-then-check (404 hides
  existence).
- `assert_teacher_owns_discipline(...)` — teacher → discipline scoping.

**Governance rules while the client is `service_role`:**

- These helpers are a **hotfix, not the final architecture.** Do **not** remove
  them believing RLS covers the case — RLS is inert today.
- **Do not add RLS policies** — they are no-op and misleading (§2.1).
- Every IDOR-prone handler **must** call one of these helpers (or self-scope its
  query to `current_user["id"]`). This is enforced in CI by the SEC-ADMIN-6
  signature guard and the SEC-SCOPE-7 role-contract drift test.

---

## 6. Expected authorization outcome (must hold before AND after migration)

For any query touching an ownership-bearing row, aligned with SEC-AUTHZ-0:

1. **Authorized owner passes** (2xx).
2. **Cross-user / cross-tenant actor is rejected** (403, or 404 when disclosing
   existence would leak) **and no read or mutation of the victim's row occurs.**
3. **`body.user_id` (or any client-supplied identity) is NEVER trusted** — the
   effective actor is always derived from the authenticated JWT
   (`current_user["id"]`). This directly addresses the
   `create_or_get_chat_session` finding `uid = data.user_id or current_user["id"]`
   (bug #2): the body value must be ignored (or, for privileged roles, only
   honored after an explicit authorization check).

Post-migration these become enforced in **two** layers (app helpers + RLS),
which is the desired defense-in-depth end state.

---

## 7. Consequences

**Positive**
- Removes a governance trap: no one can ship inert RLS or prematurely delete the
  app-layer barrier.
- Defines a concrete, sequenced path to database-enforced isolation.
- Makes the temporary-vs-target distinction explicit and auditable.

**Negative / costs**
- Until step 1 lands, a single missed `assert_owner_or_role` re-opens an IDOR;
  the SEC-ADMIN-6 / SEC-SCOPE-7 CI guards mitigate this but cannot replace RLS.
- The per-request-JWT client is a non-trivial change (connection/identity
  handling, privileged-path carve-outs, RLS authoring + backfill).

---

## 8. Cross-references

- **Roadmap:** `REMEDIATION-ROADMAP-2026-06-03.md` §5 (line 343) → this ADR
  (bidirectional: the roadmap forbids new RLS *"documentado em ADR SEC-CHAT-5"*;
  this ADR is SEC-CHAT-5).
- **Bug sweep:** `BUG-SWEEP-2026-06-03.md` #2 (lines 39–45), #18 (line 197).
- **Story:** SEC-AUTHZ-0 (helpers), SEC-CHAT-* / SEC-ADMIN-* / SEC-SCOPE-*
  (handler remediations consuming `backend/authz.py`).
- **CI guards:** SEC-ADMIN-6 (`backend/tests/security/test_idor_signature_guard.py`
  + `scope_registry.py`), SEC-SCOPE-7
  (`backend/tests/test_sec_scope_contract.py`).
