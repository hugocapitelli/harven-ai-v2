---
id: SEC-ADMIN-6
epic: EPIC-SEC
phase: 2
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: low
depends_on: [SEC-ADMIN-2, SEC-ADMIN-3, SEC-ADMIN-4, SEC-ADMIN-5]
bug_refs: [49, 16, 62, 14, 25, 2]
---
# SEC-ADMIN-6: Guard de regressão IDOR + meta signature check

## Story
Como engenheiro de plataforma responsável pela segurança do backend Harven.AI, quero um meta-teste de regressão que falhe automaticamente quando qualquer handler in-scope volte a expor o anti-pattern de IDOR (`get_current_user` recebido como `_user` e nunca comparado à identidade autenticada), para que as correções de autorização entregues em SEC-ADMIN-2..5 não regridam silenciosamente em PRs futuros e o risco de exposição cross-aluno fique travado por CI.

## Contexto (do bug sweep)
O eixo de segurança da plataforma é sistêmico: **a camada de autorização da aplicação é a única barreira (não há RLS no schema, e o cliente Supabase usa `SUPABASE_KEY` service_role que bypassa RLS)**. O sintoma comum nos 4 IDORs corrigidos é sempre o mesmo: o handler declara a dependência de auth apenas como prova de JWT válido — frequentemente nomeada `_user` para sinalizar "não usado" — e **nunca compara `current_user["id"]` ao `user_id`/owner do recurso**, nem aplica role gate, nem ignora `body.user_id`.

Defeitos que materializam o anti-pattern:
- **#49 — IDOR avatar** (`backend/main.py:1257` na faixa do upload; handler `POST /users/{user_id}/avatar`): só exige `get_current_user` e faz `user_repo.update(user_id, {...})` para o `user_id` arbitrário do path, sem comparar ao chamador (corrigido em SEC-ADMIN-2).
- **#16 — IDOR notificações** (`backend/routes_admin.py`, handlers de `notification_count`/`list`/`mark_all_read`/`mark_read`/`delete`/`create`, ~linhas 669–797 com param `_user: dict = Depends(get_current_user)`): aceitam `{user_id}` por path sem comparação e `create_notification` confia em `body.user_id` arbitrário (corrigido em SEC-ADMIN-3). Reforçado por `mark_all_read` IDOR em `routes_admin.py:762-773`.
- **#14 — IDOR gamificação** (`backend/routes_admin.py`, `create_activity`/`unlock_achievement`/`issue_certificate`/`complete_content`): "param chamado `_user`, nunca comparado"; pontos e certificado emitidos para qualquer `user_id` (corrigido em SEC-ADMIN-4). (#62 toca o mesmo cluster de status/idempotência.)
- **#25 — Authz session-review** (`backend/routes_admin.py:~340` cluster `reply_review`/`get_review`/`update_review`/`create_review`): a row da sessão nunca é carregada para comparar `user_id`, sem role gate (corrigido em SEC-ADMIN-5).
- **#2 — IDOR massivo de chat-sessions** (`backend/routes_ai.py`): mesma assinatura de defeito (`get_current_user` sem `.eq("user_id", ...)`; `create_or_get_chat_session` confia em `body.user_id`). É o exemplar canônico do anti-pattern e a razão de o guard precisar varrer toda a superfície in-scope, não só os 4 handlers já corrigidos.

**Impacto:** sem um guard automatizado, qualquer refactor ou novo endpoint pode reintroduzir leitura/mutação cross-aluno de transcrições, PII, notificações, pontos e certificados — explorável hoje por qualquer aluno autenticado. Este é o "fecho" da fase 2 do EPIC-SEC: transforma as correções pontuais em invariante de CI.

## Acceptance Criteria
- [x] **Meta-teste de assinatura (falha-antes / passa-depois):** um teste de introspecção varre os handlers FastAPI in-scope (chat-sessions em `routes_ai.py`, notificações/gamificação/session-review em `routes_admin.py`, avatar em `main.py`) e **FALHA** se algum deles mantiver `get_current_user` (incluindo a dependência ligada a um parâmetro nomeado `_user`) **sem** evidência de autorização — i.e., sem `require_role` na assinatura E sem que o corpo compare a identidade autenticada ao owner do recurso. O conjunto in-scope é declarado explicitamente (allowlist/registry de rotas), não inferido por heurística frágil.
- [x] **Detecção do anti-pattern `_user`:** um handler in-scope que receba `_user: dict = Depends(get_current_user)` e não compare a um `user_id`/owner faz o meta-teste falhar com mensagem acionável citando `arquivo:função`.
- [x] **Whitelist explícita de exceções legítimas:** rotas que de fato não precisam de comparação de owner (ex.: leituras de catálogo público ou já protegidas por `require_role`) são listadas numa allowlist versionada e comentada; o meta-teste só ignora o que está na allowlist (nada de skip silencioso).
- [x] **Happy-path dos 4 callers reais (regressão funcional, não só estática):** testes de comportamento confirmam que as correções de SEC-ADMIN-2..5 continuam permitindo os fluxos legítimos do frontend — para cada um, os 3 desfechos de IDOR:
  - [x] **Dono autorizado passa:** AccountSettings self-upload de avatar (próprio `user_id` → 200); Layout/AdminConsole lista/marca as próprias notificações (próprio → 200); gamificação self-service do aluno (próprio `user_id` → 200/201 conforme regra); SessionReview do dono/TEACHER (→ 200/201).
  - [x] **Ator cruzado é barrado e nenhuma leitura/mutação ocorre:** STUDENT operando sobre `user_id`/recurso de outro → **403**; recurso inexistente → **404**; em nenhum dos casos o repositório efetua leitura sensível (PII) ou escrita (update/insert) — verificado via fake Supabase (sem rede/DB real).
  - [x] **`body.user_id` nunca é confiado:** quando um body carrega `user_id`/owner arbitrário (ex.: `create_notification`, `create_or_get_chat_session`, escritas de gamificação), o handler usa **sempre** `current_user["id"]` (ou exige ADMIN/TEACHER via `require_role`), e o `user_id` do body é ignorado.
- [x] **Override de privilégio preservado:** ADMIN (e TEACHER onde aplicável) continua autorizado a operar sobre `user_id` de terceiros nos handlers que assim definem (ex.: avatar ADMIN → 200; create notification ADMIN → 201).
- [x] **Roda no CI:** o meta-teste + a suíte de happy-path executam no pipeline de CI (workflow GitHub Actions) e bloqueiam o merge em caso de falha; não dependem de rede nem de DB/Supabase real (usam o harness/fake de SEC-ADMIN-1).

## Tasks / Subtasks
- [x] Definir o **registry/allowlist de rotas in-scope** (módulo de teste, ex. `backend/tests/security/scope_registry.py`) listando os handlers de chat-session (`backend/routes_ai.py`), notificações + gamificação + session-review (`backend/routes_admin.py`) e avatar (`backend/main.py`), com a allowlist comentada de exceções legítimas.
- [x] Implementar o **meta-teste de assinatura** (ex. `backend/tests/security/test_idor_signature_guard.py`) usando introspecção das rotas FastAPI (`app.routes` / `inspect.signature`) para detectar `Depends(get_current_user)` ligado a parâmetro (`_user`/`current_user`) sem `require_role` e sem checagem de owner; mensagem de falha cita `arquivo:função`.
- [x] Implementar os **happy-path dos 4 callers** (ex. `backend/tests/security/test_idor_callers_happy_path.py`) cobrindo os 3 desfechos por handler, sobre o fake Supabase + TestClient do harness de SEC-ADMIN-1 (seed de 2 students/1 teacher/1 admin).
- [x] Adicionar os asserts de **`body.user_id` ignorado** para `create_notification`, `create_or_get_chat_session` e escritas de gamificação.
- [x] Criar/atualizar o **workflow de CI** (`.github/workflows/`) para rodar `pytest` (inclusive a suíte de segurança) em cada PR, falhando o build se o guard quebrar; garantir que não há dependência de rede/DB real.
- [x] Documentar no topo do meta-teste **como adicionar um novo handler ao escopo** (e quando usar a allowlist), para que novos endpoints entrem no guard por padrão.

## Dev Notes
- **Arquivos:**
  - Sob teste: `backend/routes_ai.py` (chat-sessions, #2), `backend/routes_admin.py` (notificações/gamificação/session-review — `_user: dict = Depends(get_current_user)` recorrente entre ~669 e ~1656; clusters #16/#14/#25), `backend/main.py` (avatar #49, `POST /users/{user_id}/avatar`), `backend/auth.py` (`get_current_user`, `require_role`).
  - Novos: `backend/tests/security/test_idor_signature_guard.py`, `backend/tests/security/test_idor_callers_happy_path.py`, `backend/tests/security/scope_registry.py`, `.github/workflows/ci.yml` (ou equivalente).
  - Reaproveita: harness/conftest + fake Supabase de **SEC-ADMIN-1** (que consome o conftest de SEC-ATO) — pré-requisito para TestClient sem rede/DB.
- **Abordagem:** duas camadas complementares. (1) **Guard estático por introspecção** — varre `app.routes`, inspeciona a assinatura de cada handler in-scope; reprova quem tem `Depends(get_current_user)` (em qualquer nome de param, incl. `_user`) e não tem nem `require_role` na cadeia de dependências nem checagem de owner. Como a checagem de owner está no corpo (difícil de provar 100% por estática), o guard usa o **registry explícito**: cada rota in-scope deve estar marcada como "protegida por owner-check", "protegida por role" ou estar na allowlist justificada — handlers in-scope não classificados reprovam. (2) **Guard comportamental** — os happy-path provam o efeito real (dono passa / cruzado 403-404 / body.user_id ignorado) via fake Supabase, fechando o gap que a estática não cobre.
- **Riscos de regressão:** o blast radius é o **CI inteiro** — um guard mal calibrado pode produzir falsos positivos e travar PRs legítimos (mitigar com allowlist clara e mensagens acionáveis) ou falsos negativos e dar falsa sensação de segurança (mitigar com a camada comportamental). Esta story **não altera código de produção** — só lê handlers e adiciona testes + CI; portanto não tem dependentes de runtime. Depende de SEC-ADMIN-2..5 já mergeados (os handlers precisam estar corrigidos para os testes passarem-depois) e de SEC-ADMIN-1 (harness). Frontend callers a preservar: AccountSettings (avatar self), Layout + AdminConsole (notificações), UI de gamificação self-service, SessionReview (TEACHER).

## Definition of Done
- [x] Teste de regressão (falha-antes / passa-depois) verde: o meta-teste falha se um `_user` sem comparação for (re)introduzido e passa com os handlers corrigidos. (Provado por `TestGuardCatchesRegressions` — synthetic app com handler revertido detectado como desprotegido.)
- [x] Sem regressão na suíte de segurança: SEC-ADMIN-2..5 e demais testes de EPIC-SEC continuam verdes. (Baseline 178 → 257 passed; 0 falhas.)
- [ ] QA Gate: PASS ou CONCERNS. _(a preencher pelo @qa)_
- [x] Os 4 callers reais (AccountSettings, Layout/AdminConsole, gamificação self-service, SessionReview) cobertos com os 3 desfechos de IDOR cada, sobre o fake Supabase de SEC-ADMIN-1.
- [x] Meta-teste + happy-path rodando no CI (GitHub Actions) e bloqueando merge em caso de falha, sem rede/DB real. (`.github/workflows/ci.yml`.)
- [x] Allowlist de exceções documentada e revisada; nenhum handler in-scope ignorado silenciosamente. (ALLOWLIST = socrates carve-out com `reason`; KNOWN_UNREMEDIATED lista explícita de débito residual.)

## Dev Agent Record

**Agent:** Dex (@dev) · **Date:** 2026-06-04 · **Label:** guards

### Files changed (all additive — ZERO production runtime code modified)
- **NEW** `backend/tests/security/scope_registry.py` — single source of truth: explicit in-scope route registry (24 entries) classified ROLE_GATED / OWNER_CHECKED / ALLOWLISTED; documented ALLOWLIST (socrates carve-out) + KNOWN_UNREMEDIATED list; `GUARDED_PATH_PREFIXES` + `in_guarded_family()`; import-time `_validate()`. Includes "how to add a handler / when to use the allowlist" docstring.
- **NEW** `backend/tests/security/test_idor_signature_guard.py` — the meta-test (30 tests): (A) registry completeness, (B) live wiring matches classification per entry, (C) `_user`-without-comparison anti-pattern detector (cites `module:handler`), (D) allowlist honesty, (E) fail-before/pass-after self-proof via synthetic app. Recognizes both authz-helper calls and query self-scoping (`.eq("user_id", current_user["id"])`) as valid owner checks.
- **NEW** `backend/tests/security/test_idor_callers_happy_path.py` — behavioural 3-outcome suite for the 4 frontend callers + chat-session canonical (22 tests), incl. `assert_body_user_id_ignored` for self-service writes and `create_or_get_chat_session`.
- **NEW** `backend/tests/security/__init__.py` — sys.path shim so sibling `scope_registry` imports top-level (no edit to shared `conftest.py`).
- **NEW** `.github/workflows/ci.yml` — runs `pytest tests/` on PR + push to main; no network/DB, no secrets; red suite blocks merge.

### Key decisions
- **[AUTO-DECISION]** Ownership-in-body can't be proven 100% statically → drove off the explicit registry (story's prescribed approach) and verify the live wiring + source delegation to `authz` helpers. Reason: avoids fragile static semantics while still failing on reverts.
- **[AUTO-DECISION]** Anti-drift sweep scoped to declared guarded path families, NOT app-wide. Reason: app-wide flagged every authenticated catalog read (`/courses`, `/disciplines`) — false positives that block legit PRs, a calibration risk the story explicitly warns against.
- **[FINDING for QA]** The family sweep surfaced pre-existing **read** IDORs not covered by SEC-ADMIN-2..5: `GET /users/{user_id}/{activities,achievements,certificates,stats}` and `GET /users/{user_id}/courses/{course_id}/progress` (gamification reads), plus `get_user/update_user/delete_user` user-CRUD — all `get_current_user` with neither role gate nor owner check. Recorded explicitly in `KNOWN_UNREMEDIATED` (with reasons) so the guard stays green today but the list cannot grow; recommend follow-up stories to remediate. NOT fixed here (out of SEC-ADMIN-6 scope = guard only; do not touch prod code).

### Test results (ephemeral venv, removed after)
- `test_idor_signature_guard.py`: **30 passed**
- `test_idor_callers_happy_path.py`: **22 passed**
- Full backend suite `pytest tests/`: **257 passed** (baseline before this story: 178).

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-04 (adversarial security review)

Cluster: **guards** (SEC-ADMIN-6 — static signature guard + behavioural happy-path).

The static guard (`test_idor_signature_guard` + `scope_registry`) is the anti-drift CI invariant: every in-scope route is classified ROLE_GATED/OWNER_CHECKED/ALLOWLISTED and the live FastAPI wiring is cross-checked; an unclassified route in a guarded family fails. **Not a false-green**: the guard ships self-proof tests (`test_reverted_handler_is_detected_as_unprotected`) that confirm it goes red when a handler reverts to the bare `get_current_user` anti-pattern. The Socrates carve-out is explicitly ALLOWLISTED with a reason. Behavioural happy-path suite proves runtime ownership semantics per caller.

**CONCERN (non-blocking, pre-existing debt — not introduced here):** `scope_registry.KNOWN_UNREMEDIATED` honestly records 5 live read-IDORs (`GET /users/{user_id}/activities|achievements|certificates|stats|courses/{course_id}/progress`) where any STUDENT can read another student's gamification data. These are acknowledged debt deferred to follow-up stories; the registry prevents the list from growing. Flagged here so the residual IDOR surface is visible at the gate.

Tests: signature-guard suite + happy-path green; full suite **257 passed, 0 failed**.
