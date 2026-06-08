---
id: SEC-READ-1
epic: EPIC-SEC
phase: 2
status: Done
severity: HIGH
terminal: Backend & Infra
complexity: low
depends_on: [SEC-AUTHZ-0]
bug_refs: [2]
---
# SEC-READ-1: Fechar os 5 read-IDORs residuais de gamificação

## Story
Como **plataforma Harven.AI**, quero **que os endpoints de LEITURA de gamificação (stats, atividades, conquistas, certificados, progresso de curso) só retornem dados do próprio usuário autenticado — ou de qualquer usuário quando o chamador for ADMIN/TEACHER**, para **impedir que um aluno minere pontos, conquistas, certificados, estatísticas e progresso de colegas apenas trocando o `user_id` do path**.

## Contexto (do bug sweep / debt de QA)
Sibling de leitura dos write-IDORs corrigidos em SEC-ADMIN-4 (bug #14). Cinco handlers `GET` em `backend/routes_admin.py` recebem `{user_id}` pelo **path** e só dependem de `get_current_user` (parâmetro nomeado `_user`, **nunca comparado** ao path). Qualquer aluno autenticado lê dados de qualquer `user_id` — escalação de privilégio horizontal somente-leitura.

Estes cinco endpoints estavam registrados em `backend/tests/security/scope_registry.py::KNOWN_UNREMEDIATED` como débito reconhecido (jamais silenciados), aguardando esta story de follow-up:

- `user_stats` — `GET /users/{user_id}/stats`
- `user_activities` — `GET /users/{user_id}/activities`
- `user_achievements` — `GET /users/{user_id}/achievements`
- `user_certificates` — `GET /users/{user_id}/certificates`
- `user_course_progress` — `GET /users/{user_id}/courses/{course_id}/progress`

O helper canônico `require_self_or_role` é entregue por SEC-AUTHZ-0 em `backend/authz.py` (esta story **consome**, não recria).

## Acceptance Criteria
- [x] Cada um dos cinco endpoints aplica `require_self_or_role(user_id, current_user, "ADMIN", "TEACHER")` importado de `authz.py`, **antes de qualquer leitura**.
- [x] Contrato de 3 outcomes por endpoint: (1) owner (path == token) lê o próprio → 2xx; (2) STUDENT cross-user → **403** sem dados de terceiros no corpo; (3) ADMIN/TEACHER → pode ler de outro usuário.
- [x] O parâmetro `_user` (proof-only de JWT) é renomeado para `current_user` e usado na decisão de ownership — sem `_user` sem comparação.
- [x] Ownership nunca derivada de campo do cliente — somente o `user_id` do path validado contra `current_user["id"]` pelo helper.
- [x] Os cinco endpoints saem de `KNOWN_UNREMEDIATED` e entram em `IN_SCOPE` como `OWNER_CHECKED` no `scope_registry.py` — o signature guard passa a exigir o owner-check.
- [x] Nenhum endpoint POST é tocado (já gateados na Fase 2 / SEC-ADMIN-4).

## Tasks / Subtasks
- [x] `user_stats`: `_user`→`current_user`; `require_self_or_role(...)` como primeiro statement.
- [x] `user_activities`: idem.
- [x] `user_achievements`: idem.
- [x] `user_certificates`: idem.
- [x] `user_course_progress`: idem.
- [x] `scope_registry.py`: mover as 5 entradas de `KNOWN_UNREMEDIATED` para `IN_SCOPE` (`OWNER_CHECKED`, bug_ref `14`); manter apenas o alias `notification_count` em `KNOWN_UNREMEDIATED`.
- [x] `backend/tests/security/test_idor_reads.py`: 3-outcome por endpoint, reusando `conftest` (não editado).
- [x] Suíte de segurança verde.

## Dev Notes
- **Arquivos:**
  - `backend/routes_admin.py` (handlers `user_stats` @1024, `user_activities` @1061, `user_achievements` @1155, `user_certificates` @1235, `user_course_progress` @1330; `require_self_or_role` já importado de `authz`)
  - `backend/tests/security/scope_registry.py` (mover 5 entradas)
  - `backend/tests/security/test_idor_reads.py` (novo)
  - `backend/authz.py` (helper `require_self_or_role` — consumir, não recriar)
- **Abordagem:** padrão idêntico ao `create_activity` (SEC-ADMIN-4): renomear `_user`→`current_user` e chamar `require_self_or_role(user_id, current_user, "ADMIN", "TEACHER")` antes de qualquer query. Os POST companheiros já estavam gateados.
- **Nota de harness:** o fake Supabase não implementa `.range()`; `user_activities` usa `.range()`, então o happy-path do owner/privilegiado é provado por "status != 403" (gate liberou, atinge a paginação não implementada), espelhando `TestNotificationsIDOR.test_list_owner_passes_the_gate`. Os demais retornam 2xx limpo (`.maybe_single()` / `.order().execute()`).

## Definition of Done
- [x] Cinco handlers GET com `require_self_or_role` antes da leitura.
- [x] `test_idor_reads.py` verde (3-outcome por endpoint).
- [x] `scope_registry`: 5 entradas promovidas a `IN_SCOPE`/`OWNER_CHECKED`; signature guard verde.
- [x] Sem regressão na suíte de segurança completa.
- [x] QA Gate: PASS ou CONCERNS. _(PASS — @qa 2026-06-05)_

## Dev Agent Record

**Agent:** Dex (@dev)

**Files changed:**
- `backend/routes_admin.py` — `user_stats`, `user_activities`, `user_achievements`, `user_certificates`, `user_course_progress`: `_user: dict = Depends(get_current_user)` → `current_user: dict = Depends(get_current_user)` + `require_self_or_role(user_id, current_user, "ADMIN", "TEACHER")` as the first statement (before any read). No POST handler touched. `routes_ai.py` / `ai_service.py` untouched (owned in parallel).
- `backend/tests/security/scope_registry.py` — moved the 5 gamification READ entries from `KNOWN_UNREMEDIATED` to `IN_SCOPE` as `OWNER_CHECKED` (bug_ref `14`); only the `notification_count` path alias remains in `KNOWN_UNREMEDIATED` (its canonical route is already owner-checked).
- `backend/tests/security/test_idor_reads.py` — new file, 20 tests (3-outcome per endpoint; reuses `conftest`, does not edit it).

**Summary:** All five read endpoints now derive the effective actor from `current_user["id"]` via the shared `require_self_or_role` helper (consumed, never recreated) before any query. A STUDENT reads only their own `user_id`; ADMIN/TEACHER may read others. The static signature guard now enforces these as `OWNER_CHECKED` (no longer acknowledged debt). IDS: REUSE — the helper, the conftest harness, the `idor_helpers` assertions, and the `_passes_gate` (permissive TestClient) pattern all reuse established Phase-2 infrastructure; nothing new invented.

**Test results:** `test_idor_reads.py` 20/20 pass. Full backend suite: 277 passed, 0 failed (was 257; +20 new read-IDOR tests).

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-05.

Verified in code (`routes_admin.py`) + `scope_registry.py`, not just docs. All five GET handlers — `user_stats` (@1025), `user_activities` (@1065), `user_achievements` (@1162), `user_certificates` (@1245), `user_course_progress` (@1347) — rename `_user`→`current_user` and call `require_self_or_role(user_id, current_user, "ADMIN", "TEACHER")` as the first statement, before any read. The helper is imported from `authz.py` (consumed, not recreated). Ownership is derived only from the path `user_id` validated against `current_user["id"]` — never a client body field. No POST handler touched.

`scope_registry.py`: all five entries are now in `IN_SCOPE` as `OWNER_CHECKED` (bug_ref 14); `KNOWN_UNREMEDIATED` retains only the `notification_count` path *alias* (canonical route already owner-checked). The static signature guard (`test_idor_signature_guard.py`, 35 tests) now enforces the owner-check on these — removing it would fail CI.

Tests: `test_idor_reads.py` 20/20 green. Assertions are strong, not false-green: cross-actor STUDENT asserts explicit `403` AND no third-party data in the body (`"total_points" not in resp.json()`, `"data" not in resp.json()`) — not a weak "not 500". The `.range()`-using `user_activities` happy path proves the gate via "status != 403" (documented harness limitation: the fake Supabase doesn't implement `.range()`), mirroring the established notifications pattern.

Full suite re-run by me in an ephemeral venv: **323 passed, 0 failed, 0 skipped/xfailed**.
