---
id: SEC-ADMIN-5
epic: EPIC-SEC
phase: 2
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: medium
depends_on: [SEC-AUTHZ-0, SEC-ADMIN-1]
bug_refs: [25]
---
# SEC-ADMIN-5: Authz no fluxo de Session Review (criar/ler/atualizar/responder)

## Story
Como plataforma Harven.AI, quero impor autorização correta em todo o fluxo de review de sessão (`create`, `get`, `update`, `reply`), para que apenas o dono da sessão possa responder seu próprio review, apenas professores/admins possam criar/editar/ler reviews de outros alunos, e nenhum usuário consiga adulterar dados cross-usuário.

## Contexto (do bug sweep)
Bug #25 — `backend/routes_admin.py:1610-1643` (`reply_review`), com os irmãos `create_review` (1501-1528), `get_review` (1552-1577) e `update_review` (1580-1607). Todo o quarteto de endpoints de Session Review está sem verificação de propriedade e sem role gate:

- **`reply_review` (1610-1643):** busca o review somente por `session_id` e grava `student_reply`/`status` sem nunca carregar a `chat_session` para comparar `session.user_id == current_user.id`. Qualquer usuário autenticado sobrescreve a resposta de outro aluno (coluna `student_reply` única, sem histórico) e a notificação ao professor sai atribuída ao usuário errado (usa `user['name']` do atacante).
- **`get_review` (1552-1577):** retorna qualquer review a qualquer usuário (param `_user` ignorado) — vaza `rating`/`feedback` privados do professor.
- **`update_review` (1580-1607):** deixa qualquer usuário mutar `rating`/`feedback` sem role gate (param `_user` ignorado).
- **`create_review` (1501-1528):** não aplica role gate (qualquer usuário cria review de qualquer sessão). Observação: `reviewer_id` já é setado a partir de `user["id"]` (linha 1522), o que é o comportamento correto e DEVE ser preservado — o servidor nunca confia em `reviewer_id`/`user_id` vindos do body.

**Impacto:** adulteração cross-usuário (aluno sobrescreve resposta de outro), leitura/edição do review privado do professor por qualquer aluno, e notificação atribuída ao ator errado. Severidade CRITICAL — qualquer usuário autenticado, sem condição.

## Acceptance Criteria
- [x] **`reply_review` — só dono da sessão:** carrega a `chat_session` por `session_id`; se `session.user_id != current_user.id` (e não ADMIN) retorna 403/404 e **nenhuma escrita** nem notificação ocorre. Dono responde com sucesso.
- [x] **`create_review` — só TEACHER/ADMIN:** `Depends(require_role("TEACHER", "ADMIN"))`; aluno comum recebe 403. `reviewer_id` continua derivado de `user["id"]` — body ignorado.
- [x] **`update_review` — só TEACHER/ADMIN:** gate `require_role("TEACHER", "ADMIN")`; aluno comum recebe 403 antes de qualquer mutação.
- [x] **`get_review` — dono da sessão OU TEACHER/ADMIN:** dono lê o próprio; TEACHER/ADMIN lê qualquer; aluno terceiro recebe 403/404 sem leitura.
- [x] **IDOR — três desfechos em `reply`/`update`:** (a) ator autorizado passa; (b) ator cruzado 403/404 sem leitura/mutação (DB inalterado, sem notificação espúria); (c) `reviewer_id` sempre do token.
- [x] **SessionReview do TEACHER intacto:** fluxo TEACHER cria → aluno dono responde (`pending_student` → `replied`) → TEACHER lê permanece funcional com notificações corretas.

## Tasks / Subtasks
- [x] `create_review`: `Depends(get_current_user)` → `Depends(require_role("TEACHER", "ADMIN"))`; mantido `reviewer_id = user["id"]`.
- [x] `get_review`: `_user`→`user`; carrega a `chat_session` (`select id, user_id`) e aplica `assert_owner_or_role(session.user_id, user, "TEACHER", "ADMIN")` antes de retornar o review.
- [x] `update_review`: gate `require_role("TEACHER", "ADMIN")`; aluno comum negado antes de qualquer `update`.
- [x] `reply_review`: carrega a `chat_session`; `assert_owner_or_role(session.user_id, user, "ADMIN")` antes de qualquer `update`/notificação; `row["reviewer_id"]` preservado como destinatário.
- [x] Ordem fail-closed: autorização ANTES de leitura sensível/escrita (gate precede o load do review e a notificação).
- [x] Teste de regressão cobrindo os AC dos 4 endpoints (`TestSessionReviewAuthz`).

## Dev Notes
- **Arquivos:** `backend/routes_admin.py` (`create_review` 1501-1549, `get_review` 1552-1577, `update_review` 1580-1607, `reply_review` 1610-1643). Helper de autorização: `backend/auth.py` (`get_current_user`, `require_role` — importados na linha 22).
- **Abordagem:**
  - **Role gate (create/update):** `require_role` existente aceita um único papel (uso atual `require_role("ADMIN")`). Para permitir TEACHER **ou** ADMIN, ou (a) estender/usar a variante multi-role provida por SEC-AUTHZ-0, ou (b) checar `user["role"] in {"TEACHER", "ADMIN"}` dentro do handler via `get_current_user`. Preferir o helper canônico introduzido em SEC-AUTHZ-0 para consistência cross-story.
  - **Ownership (reply/get):** padrão já presente em `create_review` para carregar a sessão — `client.table("chat_sessions").select("id, user_id").eq("id", session_id).maybe_single().execute()` — reaproveitar para comparar `session["user_id"] == user["id"]`.
  - **reviewer_id correto:** manter `reviewer_id = user["id"]` em `create_review` (1522) e o destinatário da notificação em `reply_review` = `row["reviewer_id"]` (1631) — nunca derivar de body.
  - Considerar (opcional, fora do escopo de segurança) append em vez de sobrescrever `student_reply`; segurança não depende disso, mas mitiga perda histórica.
- **Riscos de regressão:** os 4 endpoints são `/api/admin/chat-sessions/{session_id}/review[...]`. Blast radius: frontend que consome o fluxo de review (tela professor e tela aluno) — endurecer o role gate de `create`/`update` pode quebrar chamadas feitas por alunos que hoje funcionam indevidamente (comportamento desejado). Validar que o frontend professor envia token TEACHER/ADMIN e o aluno só chama `reply`/`get`. Depende de SEC-AUTHZ-0 (helper de role) e SEC-ADMIN-1 (padrão de gate admin já estabelecido).

## Definition of Done
- [x] Teste de regressão verde (10 testes em `TestSessionReviewAuthz`)
- [x] Sem regressão na suíte de segurança (105 testes verdes)
- [ ] QA Gate: PASS ou CONCERNS
- [x] Os 4 endpoints com autorização fail-closed, `reviewer_id` sempre do token, fluxo legítimo TEACHER→aluno→reply preservado

## Dev Agent Record

**Agent:** Dex (@dev)
**Files changed:**
- `backend/routes_admin.py` — `create_review` → `require_role("TEACHER", "ADMIN")` (kept `reviewer_id = user["id"]`); `update_review` → `require_role("TEACHER", "ADMIN")`; `get_review` → loads `chat_session` + `assert_owner_or_role(session.user_id, user, "TEACHER", "ADMIN")` before returning the private review; `reply_review` → loads `chat_session` + `assert_owner_or_role(session.user_id, user, "ADMIN")` before any update/notification, recipient stays `row["reviewer_id"]`.
- `backend/tests/security/test_idor_admin.py` — `TestSessionReviewAuthz` (10 tests).

**Summary:** The review quartet is now fail-closed. Authoring/editing is TEACHER/ADMIN-only; reading is owner-or-staff; replying is owner-only. A cross actor on `reply` causes no write and no spurious notification (the gate fires before both). `reviewer_id` is always the authenticated token — a forged `reviewer_id`/`user_id` in the body is proven ignored by `test_create_teacher_passes_reviewer_from_token`.

**Test results:** `TestSessionReviewAuthz` 10/10 pass. Full backend suite: 105 passed, 0 failed.

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-04 (adversarial security review)

Cluster: **admin-writes** (SEC-ADMIN-5 — session review authz quartet).

`create_review`/`update_review` → `require_role("TEACHER", "ADMIN")`; `reviewer_id` always from the token (forged body `reviewer_id`/`user_id` proven ignored). `get_review` → loads chat_session + `assert_owner_or_role(session.user_id, user, "TEACHER", "ADMIN")` before returning the private review (third student 403/404, no feedback leak). `reply_review` → owner-only gate before any update/notification, so a cross-actor reply writes nothing AND fires no spurious notification attributable to the attacker (verified — `student_reply` stays None, notifications mutation log empty).

Tests: session-review IDOR suite green; full suite **257 passed, 0 failed**.
