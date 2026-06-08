---
id: SEC-CHAT-1
epic: EPIC-SEC
phase: 2
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: medium
depends_on: [SEC-AUTHZ-0]
bug_refs: [2, 13]
---
# SEC-CHAT-1: Ownership em endpoints de leitura de chat-session

## Story
Como aluno (STUDENT) da plataforma Harven.AI, quero que minhas sessões de chat socrático, transcrições e dados pessoais só sejam legíveis por mim (ou por papéis autorizados TEACHER/ADMIN/INSTRUCTOR), para que nenhum outro aluno consiga ler minhas conversas, meu nome ou meu e-mail enumerando UUIDs de sessão.

## Contexto (do bug sweep)
Esta story corrige a face de **leitura** do IDOR massivo de chat-sessions (#2) e a exposição de PII via organizer/export (#13).

- **#2 — `backend/routes_ai.py:775-911, 934-965`** (`get_chat_session`, `get_session_messages`, `get_user_chat_sessions`, `export_session_moodle` e correlatos): endpoints recebem `session_id`/`user_id` por path/body, exigem apenas JWT válido (`get_current_user`) e **nunca filtram por `current_user["id"]`**. O cliente Supabase é único/compartilhado com `SUPABASE_KEY` que decodifica para `service_role` (bypassa RLS) e **não há nenhuma política RLS no schema** — a aplicação é a única barreira e está ausente. Resultado: qualquer aluno logado que conheça/enumere um `session_id` (UUID) lê transcrições socráticas completas, nomes e e-mails de outros alunos.
- **#13 — `backend/routes_ai.py:295-405`** (`ai_organizer_prepare_export`): carrega `chat_sessions`, `chat_messages` e `users` (name+email) via cliente service-role **sem verificar que a sessão pertence ao `current_user`**. É o vetor de alto impacto — transcrição completa + PII (nome/email) do dono. O enrichment acontece **antes** de qualquer checagem de propriedade, vazando PII para qualquer ator.

**Impacto:** quebra de confidencialidade de registros educacionais — exposição cross-aluno de transcrições e PII (nome, e-mail), extração em massa via export. Explorável hoje, em produção, por qualquer aluno autenticado.

> Escopo desta story = **leitura** (get/listagem/export). Os endpoints de escrita/mutação do mesmo padrão (`add_session_message`, `complete_chat_session`, `create_or_get_chat_session` com `body.user_id`) são cobertos pelas stories de mutação do EPIC-SEC.

## Acceptance Criteria
- [x] **Dono autorizado passa:** STUDENT dono da sessão acessa `get_chat_session`, `get_session_messages`, `export_session_moodle` e organizer/`prepare-export` normalmente (200 + payload completo).
- [x] **Ator cruzado é bloqueado:** STUDENT que não é dono recebe **403** (ou 404 conforme política de não-enumeração) e **nenhuma leitura/enrichment ocorre** — nenhum dado da sessão, mensagem ou PII é retornado nem disparado em query secundária.
- [x] **Papéis elevados passam:** TEACHER, ADMIN e INSTRUCTOR acessam sessões de qualquer aluno (override via `require_role`/`assert_self_or_role`).
- [x] **Gate antes do enrichment (export):** em `ai_organizer_prepare_export` a checagem de propriedade ocorre **antes** de carregar `users` (name+email) e `chat_messages`; export de sessão estranha **nunca vaza name/email**.
- [x] **`body.user_id` nunca é confiado:** a identidade do ator vem sempre de `current_user["id"]`; `user_id`/`content_id` vindos do body/path não são usados para popular o ator nem para resolver a sessão.
- [x] **Listagem por user:** `get_user_chat_sessions` usa `assert_self_or_role` — STUDENT só lista as próprias sessões; TEACHER/ADMIN/INSTRUCTOR podem listar de outro `user_id`.

## Tasks / Subtasks
- [x] Em `backend/routes_ai.py`, para cada endpoint de leitura de sessão (`get_chat_session`, `get_session_messages`, `export_session_moodle`): resolver `session_id`, carregar `chat_sessions`, e aplicar o helper de ownership do SEC-AUTHZ-0 (`assert_owner_or_role(session.user_id, current_user, "ADMIN", "TEACHER", "INSTRUCTOR")`) **antes** de retornar qualquer dado.
- [x] Em `get_user_chat_sessions`: substituir o uso direto do `user_id` recebido por `require_self_or_role(user_id, current_user, ...)`; STUDENT só pode consultar a própria identidade.
- [x] Em `ai_organizer_prepare_export`: mover a resolução+checagem de propriedade da sessão para **antes** do bloco que carrega `chat_messages` e `users` (name+email); abortar com 403/404 se não autorizado, sem disparar as queries de enrichment.
- [x] Garantir que toda query de sessão filtre por dono OU valide `session.user_id == current_user["id"]` no código, exceto quando o role-override se aplica.
- [x] Remover qualquer uso de `body.user_id`/`data.user_id` na resolução do ator nos caminhos de leitura/export tocados.
- [x] Escrever teste de regressão (fail-before/pass-after) em `backend/tests/` cobrindo os 3 desfechos (dono ok, cruzado 403, role elevado ok) + assert de não-vazamento de name/email no export cruzado.

## Dev Notes
- **Arquivos:** `backend/routes_ai.py` (linhas ~295-405 organizer/prepare-export, ~775-911 e ~934-965 leitura/listagem de sessão); helper de ownership de `SEC-AUTHZ-0` (`require_role`/`assert_self_or_role`); `backend/tests/` para regressão.
- **Abordagem:** centralizar a checagem no helper compartilhado (`assert_self_or_role`) introduzido em SEC-AUTHZ-0, aplicado logo após resolver a sessão e **antes** de qualquer enrichment ou retorno. Ator sempre = `current_user["id"]`; nunca confiar em `user_id`/`content_id` do body/path. Para o export (#13), o gate de propriedade precisa preceder o carregamento de `users` (PII) e `chat_messages`. Defesa em profundidade: também aplicar `.eq("user_id", ...)` nas queries, dado que o cliente Supabase é service-role e não há RLS no schema (a aplicação é a única barreira).
- **Riscos de regressão:** estes endpoints servem o fluxo de tutor socrático do aluno e o export Moodle/xAPI para professores — blast radius inclui o frontend de chat (carregamento de histórico) e os caminhos de export do LMS. TEACHER/ADMIN/INSTRUCTOR DEVEM continuar enxergando sessões de alunos (não quebrar dashboards/gradebook que dependem de leitura cross-user via role). Validar que o helper de role do SEC-AUTHZ-0 reconhece corretamente INSTRUCTOR além de TEACHER/ADMIN.

## Definition of Done
- [x] Teste de regressão (falha-antes / passa-depois) verde
- [x] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [x] Teste explícito confirma que `prepare-export` de sessão estranha não dispara queries de `users`/`chat_messages` e não retorna name/email (gate antes do enrichment); e que `body.user_id`/`data.user_id` é ignorado em todos os caminhos de leitura/export tocados.

## Dev Agent Record

**Agent:** Dex (@dev) · **Date:** 2026-06-04

### Files changed
- `backend/routes_ai.py` — ownership gate (`load_session_or_404` + `assert_owner_or_role(..., "ADMIN","TEACHER","INSTRUCTOR")`) added to `get_chat_session`, `get_session_messages`, `export_session_moodle`. `get_user_chat_sessions` now uses `require_self_or_role`. `ai_organizer_prepare_export` gates ownership BEFORE loading `chat_messages`/`users` and derives actor PII strictly from `session["user_id"]` (forged `body.user_id` discarded). New imports: `load_session_or_404`, `require_self_or_role` from `authz`.
- `backend/tests/security/test_idor_chat.py` — `TestChatReadOwnership` (10 tests) + export tests in `TestExportAndOrganizerGate`.

### Summary
All read/export paths now resolve the session row first, then run the shared `authz` ownership decision (owner OR privileged role) before any secondary query or enrichment. The export PII actor is derived from the loaded session owner, never the body. Defense-in-depth note: the Supabase client is service-role with no RLS, so this app-layer gate is the only barrier — confirmed by tests asserting no `chat_messages`/`users` rows leak on a cross-actor request.

### Test results
`58 passed` in `test_idor_chat.py`; full backend suite `163 passed` (no regressions). Cross-actor reads of `SESSION_A` by `STUDENT_B` return 403 with zero owner content/PII in the body; TEACHER/ADMIN read any session.

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-05 — adversarial review + full suite (257 passed, ephemeral venv).

Read-IDOR closure verified in `routes_ai.py`: `get_chat_session` (line 873), `get_session_messages` (894), `get_user_chat_sessions` (971), `export_session_moodle` (1015) all `load_session_or_404` + `assert_owner_or_role`/`require_self_or_role` **before** any message/PII read. Cross-actor → 403/404 with no leak. Backed by `tests/security/test_idor_chat.py` and `test_idor_callers_happy_path.py` (real cross-actor 403 assertions, not false-green). Signature guard (`test_idor_signature_guard.py`) enforces these as a CI invariant with a fail-before/pass-after self-proof.
