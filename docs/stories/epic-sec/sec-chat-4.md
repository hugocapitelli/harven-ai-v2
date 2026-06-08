---
id: SEC-CHAT-4
epic: EPIC-SEC
phase: 2
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: medium
depends_on: [SEC-AUTHZ-0]
bug_refs: [2, 13]
---
# SEC-CHAT-4: Gate organizer/session + prepare-export; derivar ator da sessão (não do body)

## Story
Como aluno autenticado da Harven.AI, quero que apenas o dono da sessão (ou TEACHER/ADMIN) consiga preparar o export e consultar o status de uma sessão de chat, e que o ator (`user_name`/`user_email`) seja derivado sempre do dono real da sessão, para que minha transcrição socrática completa e meus dados pessoais (nome, e-mail) não possam ser extraídos por terceiros nem falsificados via corpo da requisição.

## Contexto (do bug sweep)
Itens #2 e #13 do BUG-SWEEP-2026-06-03.md. O endpoint `ai_organizer_prepare_export` (`backend/routes_ai.py:334-405`) carrega `chat_sessions`, `chat_messages` e `users` (name+email) via cliente service-role (que bypassa RLS) sem nunca verificar que a sessão pertence ao `current_user`. Pior: o ator é populado a partir do corpo da requisição — `user_id = enriched.get("user_id") or current_user.get("id")` (`backend/routes_ai.py:361`) — confiando no `user_id` enviado pelo cliente antes de cair no usuário autenticado. Isso permite que qualquer usuário autenticado, passando um `session_id` arbitrário, faça extração em massa de transcrições completas + PII (nome, e-mail) de outros alunos (`backend/routes_ai.py:344-368`, vetor de alto impacto descrito no item #13, linha 184). O endpoint `ai_organizer_session` com `action="get_session_status"` (`backend/routes_ai.py:295-326`) também resolve `session_id` arbitrário sem checagem de propriedade, vazando status + contagem de mensagens (IDOR de menor severidade, mesmo item #13). O `export_session_moodle` (`backend/routes_ai.py:934-965`) compartilha o mesmo defeito de ausência de gate de propriedade e deve ser corrigido de forma consistente.

## Acceptance Criteria
- [x] **Dono autorizado passa:** `POST /api/ai/organizer/prepare-export` retorna 200 com transcrição/PII do dono legítimo (preservado; alcançável por TEACHER/ADMIN/INSTRUCTOR após o role-gate do SEC-SCOPE-3).
- [x] **Ator cruzado é bloqueado:** `prepare-export` com `session_id` de OUTRO usuário não vaza nada — STUDENT é bloqueado já no role-gate (SEC-SCOPE-3, 403); para o caso privilegiado, a derivação por `session.user_id` garante que nenhum PII forjado aparece.
- [x] **`body.user_id` nunca é confiado:** o ator (`user_name`/`user_email`) é resolvido de `session["user_id"]`; `enriched["user_id"]` é sobrescrito pelo dono da sessão, descartando qualquer `body.user_id` forjado.
- [x] `get_session_status` (`ai_organizer_session`) só enriquece status/contagem após gate de propriedade (`load_session_or_404` + `assert_owner_or_role`); caso contrário 403/404 sem vazar status nem `total_messages`.
- [x] `export_session_moodle` aplica o mesmo gate antes de carregar mensagens e PII.
- [x] TEACHER/ADMIN mantêm acesso legítimo (override de role no gate de propriedade).
- [x] Mensagens de erro e logs não vazam PII nem confirmam existência de sessões alheias (404/403 padronizado; HTTPException re-raised, não mascarada em 500).

## Tasks / Subtasks
- [x] Usar o helper de autorização de sessão de SEC-AUTHZ-0 (`load_session_or_404` + `assert_owner_or_role(..., "ADMIN","TEACHER","INSTRUCTOR")`) em cada handler.
- [x] `ai_organizer_prepare_export`: gate ANTES de carregar `chat_messages`/`users`; ator derivado de `session["user_id"]`, `enriched["user_id"]` sobrescrito (body.user_id descartado).
- [x] `ai_organizer_session` action `get_session_status`: gate antes de ler `chat_sessions`/`chat_messages`; 403/404 quando não for do ator.
- [x] `export_session_moodle`: mesmo gate de propriedade antes de carregar mensagens e info de usuário.
- [x] Testes de regressão cobrindo dono OK, ator cruzado bloqueado e `body.user_id` ignorado para prepare-export; gate para get_session_status e export-moodle.

> **Nota de coordenação (SEC-SCOPE-3 × SEC-CHAT-4):** os endpoints organizer (`session`, `prepare-export`) recebem o role-gate de SEC-SCOPE-3 (`require_role("ADMIN","TEACHER","INSTRUCTOR")`) — logo um STUDENT nunca alcança o gate de propriedade. A defesa do CHAT-4 (derivar ator de `session["user_id"]`, gate antes do enrichment) protege contra um ator privilegiado exportando via `body.user_id` forjado e contra leitura de sessão alheia por papel sem override. `export_session_moodle` permanece `get_current_user` (alcançável pelo aluno dono) com gate de propriedade.

## Dev Notes
- **Arquivos:** `backend/routes_ai.py` (`ai_organizer_session` 295-326, `ai_organizer_prepare_export` 334-405, `export_session_moodle` 934-965); testes em `backend/tests/`.
- **Abordagem:** Inserir verificação de propriedade da sessão (dono ou TEACHER/ADMIN) como primeiro passo de cada handler, reaproveitando o helper de SEC-AUTHZ-0. Substituir a derivação do ator baseada em `body.user_id` por derivação a partir de `session["user_id"]` carregado do DB. O cliente continua service-role (bypassa RLS), portanto a autorização DEVE ser explícita no application layer. Padronizar 403 vs 404 para não vazar existência de sessões alheias.
- **Riscos de regressão:** Blast radius nos chamadores frontend de `/api/ai/organizer/prepare-export`, `/api/ai/organizer/session` (`get_session_status`) e `/chat-sessions/{id}/export-moodle`. Verificar se o frontend envia `user_id`/`content_id` no body do prepare-export hoje — ao parar de confiar nesses campos, exports legítimos devem continuar funcionando (ator vem da sessão). Depende de SEC-AUTHZ-0 (helper/contrato de autorização) já em vigor para evitar duplicação. Confirmar que TEACHER/ADMIN não regridem.

## Definition of Done
- [x] Teste de regressão (falha-antes / passa-depois) verde
- [x] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [x] Verificado por teste que prepare-export de `session_id` alheio não vaza transcrição/`user_name`/`user_email` (STUDENT bloqueado no role-gate; ator sempre do dono da sessão); `body.user_id` divergente é ignorado (ADMIN/TEACHER com `user_id` forjado → PII do dono real, nunca do valor forjado).

## Dev Agent Record

**Agent:** Dex (@dev) · **Date:** 2026-06-04

### Files changed
- `backend/routes_ai.py` — `ai_organizer_prepare_export` and `ai_organizer_session(get_session_status)` gate ownership (`load_session_or_404` + `assert_owner_or_role`) before any enrichment; export actor derived strictly from `session["user_id"]` with `enriched["user_id"]` overwritten. `export_session_moodle` gated identically. Both organizer handlers re-raise `HTTPException` so 403/404 is never masked as 500.
- `backend/tests/security/test_idor_chat.py` — `TestExportAndOrganizerGate` (export-moodle owner/cross-actor, prepare-export student-blocked/teacher-actor-from-session/admin-cross, organizer get_session_status).

### Summary
PII leakage vector closed: prepare-export resolves and authorizes the session before touching `chat_messages`/`users`, and the export identity is the session owner, never `body.user_id`. STUDENT is blocked at the SEC-SCOPE-3 role gate before reaching the organizer; a privileged actor passing a forged `body.user_id` still gets the real owner's PII (the forged value is discarded). `export_session_moodle` stays student-reachable for the owner but gated for cross-actors.

### Test results
`58 passed` in `test_idor_chat.py`; full suite `163 passed`. Cross-actor export-moodle → 403 with no `hello from A`/Student A email/name in the body; teacher prepare-export with `user_id=STUDENT_B` → 200 and no Student B PII leaks.

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-04 (adversarial security review)

Cluster: **chat** (SEC-CHAT-4 — organizer/session status + prepare-export; actor from session, not body).

`ai_organizer_session` (get_session_status): ownership gate (`load_session_or_404` + `assert_owner_or_role`) runs before status/total_messages are exposed; `HTTPException` re-raised so 403/404 is never masked as 500. `ai_organizer_prepare_export`: ownership gate runs BEFORE chat_messages + users (PII) load; export actor (`user_name`/`user_email`) is derived strictly from `session_row.user_id`, and a forged `body.user_id` is dropped. Tests confirm forged STUDENT_B PII never appears. Both endpoints additionally role-gated by SEC-SCOPE-3 (STUDENT→403).

Tests: chat IDOR suite green; full suite **257 passed, 0 failed**.
