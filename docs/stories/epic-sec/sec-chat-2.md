---
id: SEC-CHAT-2
epic: EPIC-SEC
phase: 2
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: medium
depends_on: [SEC-AUTHZ-0]
bug_refs: [2, 13]
---
# SEC-CHAT-2: Ownership + remover spoof de user_id (create_or_get, add_session_message)

## Story
Como aluno da plataforma Harven.AI, quero que minhas sessões de chat e mensagens sejam vinculadas exclusivamente à minha identidade autenticada, para que nenhum outro usuário possa criar sessões em meu nome (spoofing) nem injetar mensagens forjadas em conversas que não são dele.

## Contexto (do bug sweep)
Itens #2 (IDOR massivo em sessões de chat) e #13 (`prepare-export`/organizer sem checagem de propriedade) do BUG-SWEEP-2026-06-03.md descrevem o mesmo padrão: o cliente Supabase é único e compartilhado, usa `SUPABASE_KEY` estática que decodifica para `service_role` (bypassa RLS), e **não há nenhuma política RLS no schema** — logo a aplicação é a única barreira de autorização, e ela está ausente.

Dois defeitos concretos no escopo desta story (`backend/routes_ai.py:775-911`):

- **Spoof de `user_id` em `create_or_get_chat_session` (`routes_ai.py:776-807`):** a linha `uid = data.user_id or current_user["id"]` (`routes_ai.py:782`) confia em `body.user_id` arbitrário. Qualquer aluno autenticado pode criar/reativar uma sessão sob a identidade de outro usuário, inclusive reativando sessões `completed`/`abandoned` alheias (`routes_ai.py:792-797`).
- **Injeção de mensagens em sessão estranha em `add_session_message` (`routes_ai.py:847-877`):** o handler resolve a sessão por `session_id` (`routes_ai.py:855-857`) e insere a mensagem **sem nunca comparar `session.user_id` com `current_user["id"]`**. Um aluno que enumere um `session_id` (UUID) injeta mensagens forjadas (`role`/`content`/`agent_type` arbitrários) na sessão socrática de outro aluno.

**Impacto:** quebra de integridade e confidencialidade de registros educacionais — spoofing de sessão sob outro `user_id` e injeção de mensagens forjadas em transcrições alheias. A correção de leitura/export (#13, `prepare-export`) é parte do cluster IDOR e dependente de SEC-AUTHZ-0; aqui o foco é o spoof de escrita (`create_or_get`) e a injeção (`add_session_message`).

## Acceptance Criteria
- [x] **Dono autorizado passa:** o próprio aluno autenticado cria/recupera sua sessão via `create_or_get_chat_session` e adiciona mensagens via `add_session_message` normalmente (fluxo atual de aluno legítimo preservado).
- [x] **`body.user_id` nunca é confiado:** `create_or_get_chat_session` vincula a sessão sempre a `current_user["id"]`; um `data.user_id` divergente de um STUDENT é rejeitado (403 — padrão SEC-AUTHZ-0). Mesmo que `body.user_id` aponte para outro usuário (caso ADMIN/privilegiado), a sessão criada/recuperada pertence ao autenticado, nunca ao valor forjado.
- [x] **Ator cruzado recebe 403 e nenhuma mutação ocorre:** em `add_session_message`, se `session.user_id != current_user["id"]` e o chamador não for instrutor/professor/admin, a requisição retorna **403** e **nenhuma** mensagem é inserida (verificação de propriedade ocorre ANTES do insert). Sessão inexistente continua retornando 404.
- [x] **Instrutor ainda adiciona:** usuário com `role` de instrutor/professor/admin continua podendo adicionar mensagens em qualquer sessão — comportamento explícito do escopo.
- [x] **Contador inalcançável por esta story:** `total_messages` permanece com a lógica de incremento atual. O defeito do contador é o item #40 e está **fora de escopo** — nenhuma mudança comportamental no incremento.

## Tasks / Subtasks
- [x] Em `create_or_get_chat_session`: `uid = current_user["id"]` é a única fonte de identidade; `data.user_id`, quando presente, passa pelo gate `assert_owner_or_role` (rejeita spoof de STUDENT com 403) e nunca define o dono da row. Campo `user_id` de `ChatSessionCreate` mantido para a semântica de override privilegiado, documentado como nunca-confiável-para-owner via comentário inline.
- [x] Em `add_session_message`: a sessão é carregada via `load_session_or_404` (select `*`, inclui `user_id`); após 404-check, `assert_owner_or_role(session.user_id, current_user, "ADMIN","TEACHER","INSTRUCTOR")` roda ANTES de montar/inserir `new_message`.
- [x] Reutilizar o helper de checagem de propriedade/role de SEC-AUTHZ-0 (`authz.assert_owner_or_role` / `load_session_or_404`) — sem duplicar lógica.
- [x] NÃO tocar na lógica de `total_messages` — escopo do #40 (apenas comentário de nota adicionado).
- [x] Adicionar testes de regressão cobrindo dono, ator cruzado e instrutor.

## Dev Notes
- **Arquivos:** `backend/routes_ai.py` (`create_or_get_chat_session` 776-807; `add_session_message` 847-877; modelo `ChatSessionCreate` ~115). Possível helper compartilhado de SEC-AUTHZ-0.
- **Abordagem:** (1) eliminar a fonte de spoof — derivar `uid` exclusivamente de `current_user["id"]`, descartando `body.user_id`; (2) impor ownership na escrita de mensagens — carregar `user_id` da sessão e gate por igualdade, com override de role (instrutor/professor/admin) via o mesmo mecanismo de SEC-AUTHZ-0. Como o cliente Supabase roda em `service_role` (bypassa RLS) e o schema não tem políticas RLS, a checagem em código é a única barreira — ela deve ocorrer ANTES de qualquer insert/update.
- **Riscos de regressão:** `create_or_get_chat_session` é **co-tocado** por TPP-2 (Fase 3, dono único — rewrite com ON CONFLICT upsert) e DATA-GAM-4 (Fase 4). Conforme nota do roadmap (`REMEDIATION-ROADMAP-2026-06-03.md:130`, `:329`), SEC-CHAT **adiciona** sobre o resultado do TPP-2, **não reescreve** o handler. Manter a mudança mínima e isolada (apenas a derivação de `uid`) para evitar conflito de merge com TPP-2. `add_session_message` é chamado pelo frontend do tutor a cada turno persistido — validar que o aluno legítimo não passa a receber 403 (a sessão precisa ter sido criada com o `user_id` correto, o que esta story garante). Depende de SEC-AUTHZ-0 (helper de ownership/role e padrão de gate cross-tenant).

## Definition of Done
- [x] Teste de regressão (falha-antes / passa-depois) verde: (a) `create_or_get` com `body.user_id` de terceiro não cria sessão do terceiro (spoof de STUDENT rejeitado 403; ADMIN cria sob a própria identidade); (b) `add_session_message` por ator cruzado retorna 403 e não insere; (c) instrutor/teacher adiciona com sucesso; (d) dono legítimo cria sessão e adiciona mensagem normalmente.
- [x] Sem regressão na suíte de segurança (cluster IDOR de sessões / SEC-AUTHZ-0).
- [ ] QA Gate: PASS ou CONCERNS.
- [x] Confirmado que `total_messages` permanece com o comportamento atual (nenhuma alteração no incremento — #40 intocado).
- [x] Campo `data.user_id` comprovadamente não influencia o dono da sessão em `create_or_get_chat_session` (verificado por teste — ADMIN com `user_id=STUDENT_B` resulta em row owned by ADMIN).

## Dev Agent Record

**Agent:** Dex (@dev) · **Date:** 2026-06-04

### Files changed
- `backend/routes_ai.py` — `create_or_get_chat_session` derives `uid` only from `current_user`; `add_session_message` loads the session via `load_session_or_404` and runs `assert_owner_or_role` before the insert.
- `backend/tests/security/test_idor_chat.py` — `TestCreateAndAddMessageOwnership` (7 tests).

### Summary
Spoof source removed (owner is always the authenticated user). Message injection closed: a non-owner enumerating a `session_id` gets 403 and zero inserts (verified via the fake's mutation log — `inserts == []`). `total_messages` increment left byte-for-byte unchanged (only a clarifying comment added). Note: `data.user_id` is retained on the model for the privileged-override path used by `create_or_get` but never sets the row owner.

### Test results
`58 passed` in `test_idor_chat.py`; full suite `163 passed`. Cross-actor add to `SESSION_A` by `STUDENT_B` → 403, message count unchanged; TEACHER add → 200.

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-04 (adversarial security review)

Cluster: **chat** (SEC-CHAT-2 — create_or_get + add_session_message ownership; user_id spoof removed).

`create_or_get_chat_session`: `uid` is now strictly `current_user["id"]`; the body `data.user_id` is no longer ORed in — if present it is run through `assert_owner_or_role`, so a STUDENT forging another id is rejected (403) and an ADMIN's spoof still yields a row owned by the ADMIN, never the forged id. `add_session_message`: ownership gate runs before the insert; a cross-actor enumeration inserts nothing (test asserts `inserts == []` and message count unchanged). Missing session → 404. Body-user-id-ignored contract verified via `assert_body_user_id_ignored`.

Tests: chat IDOR + happy-path suites green; full suite **257 passed, 0 failed**.
