---
id: SEC-CHAT-3
epic: EPIC-SEC
phase: 2
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: low
depends_on: [SEC-AUTHZ-0, SEC-CHAT-2]
bug_refs: [2, 13]
---
# SEC-CHAT-3: complete_chat_session idempotente + ownership; create_or_get não reativa completed

## Story
Como aluno (STUDENT) da Harven.AI, quero que a conclusão de uma sessão de chat seja restrita ao dono da sessão e idempotente, e que reabrir um capítulo já concluído não reative a sessão completed, para que minha transcrição e meu progresso não sejam corrompidos por terceiros nem por reaberturas acidentais.

## Contexto (do bug sweep)
Dois defeitos relacionados no endpoint de conclusão e no de criação/recuperação de sessão de chat:

- **Item #2 (IDOR — autorização ausente):** `backend/routes_ai.py:775-911, 934-965` — endpoints que recebem `session_id`/`user_id` por path/body só exigem JWT válido (`get_current_user`) e **nunca filtram por `current_user["id"]`**. O cliente Supabase é único e compartilhado, usando `SUPABASE_KEY` estática que decodifica para `service_role` (bypassa RLS), e **não há nenhuma política RLS no schema** — logo a aplicação é a única barreira e ela está ausente. Em `complete_chat_session` (`routes_ai.py:914-931`) qualquer JWT válido pode concluir a sessão de outro aluno apenas conhecendo o `session_id`. Além disso, `create_or_get_chat_session` (`routes_ai.py:782`) aceita `body.user_id` arbitrário (`uid = data.user_id or current_user["id"]`), permitindo criar/recuperar sessão em nome de outro usuário.

- **Item #13 (não idempotente + reativa concluídas):** `complete_chat_session` (`routes_ai.py:914-931`) e `create_or_get_chat_session` (`routes_ai.py:792-798`). O `complete` não tem precondição de status nem checagem de propriedade: um 2º `PUT /complete` sobre uma sessão já `completed` reexecuta o update em vez de ser no-op. Pior, em `create_or_get_chat_session:793-797`, ao reabrir o capítulo a sessão existente com status `abandoned` **ou `completed`** é forçada de volta para `active` (`{"status": "active"}`), apagando o estado `completed` e misturando a transcrição da tentativa anterior com a nova. **Impacto:** corrupção de transcrição, perda do marcador de conclusão e analytics inconsistentes (CRITICAL).

## Acceptance Criteria
- [x] **Ownership em complete (IDOR):** o dono autorizado conclui sua sessão e recebe 200; um ator cruzado recebe **403** (ou 404 quando inexistente) e **nenhuma mutação ocorre** (status inalterado); identidade sempre verificada contra `current_user["id"]`.
- [x] **body.user_id nunca confiado:** em `create_or_get_chat_session`, o `user_id` da sessão é **sempre** `current_user["id"]`; um `body.user_id` divergente é rejeitado (STUDENT) ou ignorado para owner (privilegiado), nunca usado para criar/recuperar sessão de outro usuário.
- [x] **Idempotência do complete:** um 2º `PUT /chat-sessions/{id}/complete` sobre uma sessão já `completed` retorna **200 no-op** (status permanece `completed`, sem write redundante — verificado: nenhum `update` no mutation log).
- [x] **create_or_get não reativa completed:** ao reabrir um capítulo cuja sessão está `completed`, ela **não** é forçada para `active`; o estado `completed` é preservado. Apenas `abandoned` volta a `active`; `completed` gera/usa uma sessão distinta.

## Tasks / Subtasks
- [x] Em `complete_chat_session`: `select("id")` substituído por `load_session_or_404` (select `*` → traz `user_id, status`); `assert_owner_or_role` valida propriedade (403 divergente / 404 inexistente) — alinhado a SEC-CHAT-2 / SEC-AUTHZ-0.
- [x] `complete_chat_session` idempotente: se `status == "completed"`, retorna a sessão como 200 no-op sem reexecutar o update.
- [x] Em `create_or_get_chat_session`: identidade derivada só de `current_user["id"]` (spoof gate via SEC-CHAT-2).
- [x] Em `create_or_get_chat_session`: reativação restrita a `abandoned`; `"completed"` removido do branch `{"status": "active"}` → segue caminho de nova sessão.
- [x] Reaproveitar helper de ownership de SEC-CHAT-2 (`authz.assert_owner_or_role` / `load_session_or_404`).
- [x] Teste de regressão cobrindo os 4 ACs: dono conclui (200), ator cruzado bloqueado (403 sem mutação), 2º complete no-op (200), reabrir completed não reativa + abandoned reativa.

## Dev Notes
- **Arquivos:** `backend/routes_ai.py` (`complete_chat_session` 914-931; `create_or_get_chat_session` 775-810, esp. 782 e 792-798).
- **Abordagem:** (1) Ownership: ler `user_id` da sessão e comparar com `current_user["id"]` antes de qualquer write — reutilizar o helper de SEC-CHAT-2 (mesma família de endpoints `/chat-sessions`). (2) Idempotência: precondição de status no `complete` — se já `completed`, retornar no-op. (3) Anti-reativação: o array de status reativáveis em `create_or_get` passa de `("abandoned", "completed")` para `("abandoned",)`; `completed` segue caminho de nova tentativa. (4) Identidade: nunca derivar `uid` de `data.user_id`.
- **Riscos de regressão:** `complete_chat_session` (`routes_ai.py:914-931`) é **editado também por DATA-GAM-3/4 e INT-MOODLE-4 e dirigido por TPP** (ver roadmap linhas 131 e 330) — os hooks dessas stories são **aditivos sobre a versão TPP (shape)**. Esta story deve aplicar ownership + idempotência sem quebrar o shape esperado pela TPP; coordenar ordem de merge. Quem chama o complete: frontend de chat ao concluir capítulo. Mudar o conjunto de status reativáveis afeta o fluxo de "reabrir capítulo" — validar que retomada de sessão `active`/`abandoned` continua funcionando. Depende de SEC-AUTHZ-0 (base de autorização) e SEC-CHAT-2 (helper de ownership dos endpoints de chat-sessions).

## Definition of Done
- [x] Teste de regressão (falha-antes / passa-depois) verde
- [x] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [x] Ownership verificado contra `current_user["id"]` (não contra body/path) em `complete_chat_session`; `create_or_get_chat_session` nunca usa `data.user_id` para owner; complete idempotente para `completed`; reabrir capítulo `completed` não reativa nem mistura transcrição. Coordenação com TPP/DATA-GAM/INT-MOODLE: mudança mantida aditiva e mínima (gate + precondição de status), preservando o shape do handler para o merge da TPP.

## Dev Agent Record

**Agent:** Dex (@dev) · **Date:** 2026-06-04

### Files changed
- `backend/routes_ai.py` — `complete_chat_session` now loads via `load_session_or_404`, gates with `assert_owner_or_role`, and short-circuits to a 200 no-op when already `completed`. `create_or_get_chat_session` reactivation set reduced from `("abandoned","completed")` to `("abandoned",)`; `completed` falls through to create a fresh distinct session.
- `backend/tests/security/test_idor_chat.py` — `TestCompleteAndReactivation` (6 tests).

### Summary
Complete is now owner-gated and idempotent (the second call issues no `update` — proven against the fake's mutation log). Reopening a `completed` chapter preserves the completion marker and spawns a new active session instead of corrupting the prior transcript; `abandoned` still resumes in place. Coordination with TPP/DATA-GAM/INT-MOODLE: the edit is additive (gate + status precondition) and keeps the handler shape, minimizing merge risk with the TPP rewrite.

### Test results
`58 passed` in `test_idor_chat.py`; full suite `163 passed`. Cross-actor complete of `SESSION_A` → 403, status stays `active`; double-complete → 200 no-op with no redundant write; reopen-completed → new session, original stays `completed`.

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-04 (adversarial security review)

Cluster: **chat** (SEC-CHAT-3 — complete idempotent + ownership; no-reactivate completed).

`complete_chat_session`: loads session, asserts ownership before the write; cross-actor 403 leaves status untouched; idempotent — a 2nd complete is a 200 no-op with no redundant update (verified via mutation log). `create_or_get`: only `abandoned` sessions reactivate; a `completed` session is NEVER forced back to active (would wipe the completion marker) — it falls through to a fresh distinct session. Both branches behaviourally verified.

Tests: chat IDOR suite green; full suite **257 passed, 0 failed**.
