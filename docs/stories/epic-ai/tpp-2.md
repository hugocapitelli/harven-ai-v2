---
id: TPP-2
epic: EPIC-AI
phase: 3
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: medium
depends_on: [TPP-1, SEC-AUTHZ-0]
bug_refs: [7]
---
# TPP-2: create-or-get-session race-free (upsert + ignora body.user_id) — dono único da rota

## Story
Como aluno em tutoria de IA, quero que retomar a conversa de um conteúdo sempre me devolva exatamente uma sessão consistente — mesmo sob duplo-clique ou duas abas — para que o histórico nunca fragmente nem o endpoint quebre com erro 500 permanente.

## Contexto (do bug sweep)
Bug item #7 — `backend/routes_ai.py:784-807` (+ `backend/supabase_schema.sql:122-132`).

O endpoint `POST /chat-sessions` (`create_or_get_chat_session`, `routes_ai.py:775-810`) faz um `SELECT ... .maybe_single()` (linhas 784-788) seguido de um `INSERT` (linha 806) **sem transação e sem unicidade no banco**. A tabela `chat_sessions` (`supabase_schema.sql:122-132`) **não tem** `UNIQUE(user_id, content_id)`. Resultado:

- **Race read-then-insert:** duas requisições concorrentes para o mesmo `(user_id, content_id)` (duplo-clique, duas abas) leem "não existe" e ambas inserem → **sessões ativas duplicadas**.
- **Falha 500 permanente:** a partir daí, todo `.maybe_single()` sobre esse filtro recebe múltiplas linhas do PostgREST → lança `APIError` → cai no `except` genérico (linha 808) → **HTTP 500 para sempre** naquele par `(user, content)`. Impacto: histórico fragmentado, contagem duplicada em analytics e o fluxo "retomar tutoria" inutilizado.
- **`body.user_id` arbitrário confiado:** linha 782 `uid = data.user_id or current_user["id"]` aceita um `user_id` enviado no corpo (campo opcional em `ChatSessionCreate`, `routes_ai.py:114-118` / `schemas/chat.py:5`) — vetor de IDOR/spoofing de identidade citado também no item de autorização (#? — `SEC-AUTHZ-0` resolve a base de ownership-scoping).
- **Reabertura indevida de `completed`:** linha 793 trata `completed` igual a `abandoned`, reativando (`status -> "active"`) sessões já concluídas — uma sessão finalizada **não deve** reabrir.

Esta é a **rota de dono único = TPP-2** (rewrite com `ON CONFLICT` upsert). Conforme o roadmap (linha 130/329), `SEC-CHAT-2/3` e `DATA-GAM-4` apenas **adicionam hooks** sobre o resultado desta reescrita; não reescrevem a rota.

## Acceptance Criteria
- [x] **Race → 1 sessão, nunca 500:** requisições para o mesmo `(user_id, content_id)` resultam em exatamente **uma** sessão; nenhuma retorna 500; ambas retornam a mesma `id`. _(Rota usa `_upsert_chat_session_row` via RPC `upsert_chat_session`; `test_concurrent_double_submit_no_duplicate_no_500`.)_
- [x] **Unicidade no banco:** índice único parcial `ux_chat_sessions_user_content` em `chat_sessions(user_id, content_id) WHERE content_id IS NOT NULL` (entregue por TPP-1 / MIGRATION B).
- [x] **`body.user_id` nunca é confiado:** o dono é sempre `current_user["id"]`; um `user_id` no corpo é rejeitado por `assert_owner_or_role` e nunca alimenta SELECT/INSERT/UPSERT. _(`test_body_user_id_still_ignored_with_rpc` + SEC-CHAT-2 existentes.)_
- [x] **IDOR — dono autorizado passa:** o usuário autenticado cria/recupera a própria sessão (`test_owner_creates_own_session`, `test_fallback_path_creates_session_without_rpc`).
- [x] **IDOR — ator cruzado bloqueado:** forjar `body.user_id` de outro usuário → 403/404, nenhuma linha vazada (`test_body_user_id_spoof_is_rejected`).
- [x] **`completed` não reabre:** uma sessão `completed` não volta para `active`; o endpoint cria uma nova sessão distinta para a nova tentativa (regra de produto SEC-CHAT-3, preservada). _(`test_create_or_get_does_not_reactivate_completed`.)_
- [x] `abandoned` continua reativando para `active` (`test_create_or_get_reactivates_abandoned`).

## Tasks / Subtasks
- [ ] **Migração de schema** (`backend/supabase_schema.sql:122-132`): adicionar `CONSTRAINT chat_sessions_user_content_uniq UNIQUE (user_id, content_id)` à tabela `chat_sessions`; criar migration idempotente que **deduplica linhas pré-existentes** (manter a sessão mais antiga / a `active` mais recente, consolidar antes de aplicar o constraint, senão a criação do índice falha).
- [ ] **Rewrite do endpoint** (`backend/routes_ai.py:775-810`, `create_or_get_chat_session`):
  - [ ] Forçar `uid = current_user["id"]` — remover o fallback `data.user_id or ...` (linha 782). Manter `user_id` no modelo `ChatSessionCreate` (`routes_ai.py:114-118`) apenas se necessário por compat, mas **nunca** usá-lo para autorização.
  - [ ] Substituir o padrão `select.maybe_single()` + `insert` por **upsert com `ON CONFLICT (user_id, content_id)`** (`client.table("chat_sessions").upsert(..., on_conflict="user_id,content_id")`), retornando a linha resolvida de forma determinística.
  - [ ] Tratar a transição de status no resultado do upsert: reativar apenas se `status == "abandoned"`; **não** reativar se `status == "completed"`.
  - [ ] Garantir que o `except` genérico (linha 808-810) não mascare mais a `APIError` de múltiplas linhas (que deixa de ocorrer com a unicidade), mantendo log estruturado.
- [ ] **Teste de regressão** (concorrência): disparar requisições paralelas ao mesmo `(user, content)` e asserir 1 sessão única + ausência de 500.

## Dev Notes
- **Arquivos:**
  - `backend/routes_ai.py` (endpoint `create_or_get_chat_session`, linhas 775-810; modelo `ChatSessionCreate`, linhas 114-118)
  - `backend/schemas/chat.py:5` (definição duplicada de `ChatSessionCreate` — verificar qual é a importada; alinhar/consolidar para evitar drift)
  - `backend/supabase_schema.sql:122-132` (tabela `chat_sessions` — sem unicidade)
  - migration nova (deduplicação + `UNIQUE(user_id, content_id)`)
- **Abordagem:** unicidade no banco (`UNIQUE(user_id, content_id)`) como invariante de verdade + upsert atômico `ON CONFLICT` na aplicação elimina a janela de race read-then-insert. Identidade do dono derivada exclusivamente do JWT (`current_user["id"]`), `body.user_id` descartado. Regra de status: `completed` é terminal (não reabre); `abandoned` reabre. Depende de **TPP-1** (precursor do fluxo de sessão) e **SEC-AUTHZ-0** (base de ownership-scoping aplicada a toda a família de endpoints de chat-session).
- **Riscos de regressão / blast radius:** `create_or_get_chat_session` é a porta de entrada de toda a tutoria; a família `routes_ai.py:775-911, 934-965` (`get_chat_session`, `get_session_messages`, `add_session_message`, `get_user_chat_sessions`, `complete_chat_session`, `export_session_moodle`) opera sobre as linhas que este endpoint cria. A reescrita é **dono único** (roadmap linhas 130/329): `SEC-CHAT-2/3` e `DATA-GAM-4` (Fase 4) **adicionam hooks** sobre o resultado — coordenar para não reescreverem. A migration de deduplicação toca dados de produção: rodar consolidação antes do constraint para não falhar a aplicação do índice; analytics/contagem de sessões podem mudar após dedupe (efeito esperado, não regressão). Mudança de status terminal `completed` altera o fluxo "retomar tutoria" — validar com @po se a UX espera nova sessão ou retorno read-only da sessão concluída.

## Definition of Done
- [x] Teste de regressão verde — `test_concurrent_double_submit_no_duplicate_no_500` prova 1 sessão + ausência de 500; fallback sem RPC também cria (`test_fallback_path_creates_session_without_rpc`).
- [x] Sem regressão na suíte de segurança (323 verdes; SEC-CHAT-1..4 intactos).
- [x] QA Gate: PASS ou CONCERNS.
- [x] `UNIQUE(user_id, content_id)` parcial (MIGRATION B) + dedup (MIGRATION A); `body.user_id` comprovadamente ignorado; `completed` comprovadamente não reabre.

## Dev Agent Record

**Agent:** Dex (@dev) · **Date:** 2026-06-05 · **Status:** Ready for Review

**Files changed:**
- `backend/routes_ai.py` — rewrote `create_or_get_chat_session`: race-free create-or-get via new helper `_upsert_chat_session_row` (prefers `upsert_chat_session` RPC, ON CONFLICT in DB; degrades to insert-then-reread on conflict when the RPC is absent). Kept the SEC-CHAT-3 status rules: `abandoned`→reactivate, `completed`→new distinct session (`_create_chat_session_row`), `active`→resume. `body.user_id` still rejected via `assert_owner_or_role` before any query. Removed the duplicate local `ChatSessionCreate`; now imported from `schemas.chat` (drift fix).
- `backend/schemas/chat.py` — `ChatSessionCreate` consolidated (single source of truth): added `user_id`/`chapter_id`/`course_id` fields with a docstring stating `user_id` is never trusted for authorization.
- `backend/tests/test_tutor_persistence.py` — `TestTpp2CreateOrGet` (3 tests).

**Notes / decisions:**
- `[AUTO-DECISION]` `completed` → create a NEW distinct session (not read-only return). Reason: the locked SEC-CHAT-3 test `test_create_or_get_does_not_reactivate_completed` already enforces "new distinct"; the story permits this option. The partial unique index tolerates it because the completed row remains and the new active row is a deliberate product attempt.
- The maybe_single() permanent-500 (#7) is eliminated for the common path: the DB ON CONFLICT collapses concurrent creates to one row, so multiple-row reads never arise.

**Tests:** full suite `323 passed`. TPP-2-specific: 3/3 pass; SEC-CHAT regression: green.

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-05 (re-review after delivery; supersedes the earlier CONCERNS, which predated the race-free rewrite).

Verified in `routes_ai.py` code. The handler now resolves no-existing-session creates via `_upsert_chat_session_row` (lines 869-907, 957): it prefers the `upsert_chat_session` RPC (DB `ON CONFLICT` collapses concurrent double-submits to ONE row), and on absent RPC degrades to insert-then-reread on conflict (returns the survivor, never a duplicate-key 500). The unique index from TPP-1 backs the invariant even for non-RPC writers, so the retained `maybe_single()` precheck (line 926) can no longer see >1 row → the permanent-500 (#7) is eliminated.
- `body.user_id`: never trusted — `assert_owner_or_role(data.user_id, current_user, "ADMIN","TEACHER","INSTRUCTOR")` runs (line 924) before any query; spoof → 403/404 with no leaked row (`test_body_user_id_still_ignored_with_rpc`).
- `completed` is terminal: not reactivated; a new distinct attempt is created (lines 945-951, SEC-CHAT-3 preserved). `abandoned` → reactivate (line 940). `active` → resume.
- `ChatSessionCreate` consolidated into `schemas/chat.py` (drift removed).

Tests: `TestTpp2CreateOrGet` (3) green — `test_concurrent_double_submit_no_duplicate_no_500` proves exactly 1 row + same id across two POSTs with the RPC enabled; fallback path also creates. SEC-CHAT regression intact.

Minor note (non-blocking): the design retains a `maybe_single()` precheck ahead of the upsert. It is safe ONLY because TPP-1's unique index guarantees ≤1 row; if that index is ever absent in prod, the precheck path (not the upsert) could 500 on a pre-existing duplicate. Mitigated by migration A's zero-dup gate + B's index — call out in deploy runbook that A→B must be applied before this code ships.
