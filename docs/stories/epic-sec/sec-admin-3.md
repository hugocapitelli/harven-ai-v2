---
id: SEC-ADMIN-3
epic: EPIC-SEC
phase: 2
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: medium
depends_on: [SEC-AUTHZ-0, SEC-ADMIN-1]
bug_refs: [16, 62]
---
# SEC-ADMIN-3: IDOR em notificações + criação restrita a ADMIN

## Story
Como responsável pela segurança da plataforma Harven.AI, quero que todos os endpoints de notificação imponham propriedade (dono ou ADMIN) e que a criação de notificações seja restrita a ADMIN/sistema, para impedir que qualquer aluno autenticado leia, suprima, altere ou injete notificações no feed de outro usuário.

## Contexto (do bug sweep)
Item #16 (`backend/routes_admin.py:665-746, 749-786`) — IDOR generalizado em toda a superfície de notificações. Os endpoints abaixo dependem apenas de `get_current_user` (autenticação), sem comparar o alvo ao chamador e sem role gate:

- `notification_count` (`routes_admin.py:667`) — lê contagem de não lidas de `{user_id}` arbitrário.
- `list_notifications` (`routes_admin.py:684`) — lista o conteúdo (título/mensagem/link) das notificações de `{user_id}` arbitrário → divulgação cross-usuário.
- `create_notification` (`routes_admin.py:723`) — aceita `body.user_id` arbitrário com `title`/`message`/`link` controlados pelo atacante → vetor de spam/phishing injetando entradas em qualquer feed.
- `mark_read` (`routes_admin.py:750`) — recebe `notification_id` por path, confere existência (404) mas NÃO verifica o `user_id` dono da row → marca como lida a notificação de outro usuário.
- `mark_all_read` (`routes_admin.py:763`) — marca todas as não lidas de `{user_id}` arbitrário como lidas → supressão do estado de notificações de outro usuário.
- `delete_notification` (`routes_admin.py:777`) — recebe `notification_id` por path, confere existência (404) mas NÃO verifica o dono → exclui a notificação de outro usuário.

Item #62 (`routes_admin.py:762-773`) — confirma `mark_all_read` como IDOR (o `remaining_unread` está correto, mas a operação opera sobre `user_id` arbitrário). Já coberto por #16.

**Impacto:** divulgação cross-usuário de conteúdo de notificações; supressão/alteração do estado de notificações alheias; injeção de spam/phishing (título/mensagem/link arbitrários) em qualquer feed. Explorável hoje, em produção, por qualquer aluno autenticado — não há RLS no schema, a autorização da aplicação é a única barreira e está ausente.

## Acceptance Criteria
- [x] **Leitura escopada por dono:** `notification_count` e `list_notifications` retornam 200 quando `{user_id}` == chamador (ou chamador é ADMIN); STUDENT estranho recebe **403** e nenhuma leitura cross-usuário ocorre (corpo não contém dados de terceiro).
- [x] **`mark_read` por propriedade da row:** busca o `user_id` da notificação e compara ao chamador; dono (ou ADMIN) marca → 200; ator cruzado → **403** sem mutação; `notification_id` inexistente → **404** (404 antes de 403 só quando a row não existe).
- [x] **`mark_all_read` escopado:** dono (ou ADMIN) → 200; `{user_id}` estranho → **403** e nenhuma row alheia é alterada.
- [x] **`delete_notification` por propriedade da row:** dono (ou ADMIN) deleta → 200; ator cruzado → **403** sem mutação; inexistente → **404**.
- [x] **Criação restrita:** `create_notification` exige role ADMIN — STUDENT → **403**; ADMIN → **201**; `body.user_id` é o alvo legítimo (criação é operação de ADMIN/sistema, nunca de aluno).
- [x] **`body.user_id` nunca é confiado em rota de aluno:** nenhum endpoint de leitura/mutação de notificação deriva autorização do corpo da requisição — o alvo vem do path e é validado contra o token; a criação só ocorre sob role gate ADMIN.
- [x] **Regressão funcional preservada:** `Layout` (sino de notificações do próprio usuário) continua listando/contando/marcando as **próprias** notificações; `AdminConsole` (criação de notificação por ADMIN) continua funcionando com 201.

## Tasks / Subtasks
- [x] Em `backend/routes_admin.py`, aplicar `require_self_or_role(user_id, current_user, "ADMIN")` (helper de SEC-AUTHZ-0; o nome canônico em `authz.py` é `require_self_or_role`, não `assert_self_or_role`) em `notification_count` e `list_notifications`; trocar `_user` por `current_user`.
- [x] Em `mark_read` e `delete_notification`: manter o select de existência (404), e ao encontrar a row, ler `user_id` da notificação e aplicar `assert_owner_or_role(row["user_id"], current_user, "ADMIN")` → 403 antes de mutar.
- [x] Em `mark_all_read`: aplicar `require_self_or_role(user_id, current_user, "ADMIN")` antes do update.
- [x] Em `create_notification`: trocar a dependência por `Depends(require_role("ADMIN"))` (helper existente em `backend/auth.py:53`), mantendo `status_code=201`.
- [x] Garantir que o select de `mark_read`/`delete` traga a coluna `user_id` (ajustado `.select("id")` → `.select("id, user_id")`).
- [x] Escrever testes de regressão IDOR em `backend/tests/security/test_idor_admin.py` (harness SEC-ADMIN-1, fake Supabase + seed): dono OK, ator cruzado 403 sem mutação, inexistente 404, STUDENT create 403, ADMIN create 201 — para os 6 endpoints.
- [~] Verificar no frontend que `Layout`/`AdminConsole` usam o `user_id` do token: fora do escopo desta task de backend (consumidores frontend não tocados); contrato preservado server-side (owner == self passa, create só sob ADMIN).

## Dev Notes
- **Arquivos:** `backend/routes_admin.py` (notificações, linhas ~665-786); `backend/auth.py` (`require_role`, linha 53 — já existe); `backend/authz.py` (helpers `assert_owner_or_role`, `assert_self_or_role`, `load_session_or_404` entregues por SEC-AUTHZ-0); `backend/repositories/notification_repo.py` (camada de dados — não precisa mudar, autorização fica na rota); `backend/tests/` (harness SEC-ADMIN-1). Consumidores frontend: `Layout` (sino do próprio usuário) e `AdminConsole` (criação por admin).
- **Abordagem:** Autorização na borda (rota), não no repositório. Para endpoints com `user_id` no path → `assert_self_or_role(user_id, current_user, "ADMIN")`. Para endpoints com `notification_id` no path (`mark_read`, `delete_notification`) → carregar a row primeiro (404 se ausente), depois validar propriedade pela coluna `user_id` da row (403 se cruzado). `create_notification` → role gate ADMIN via `require_role("ADMIN")`, reutilizando o helper existente já usado em `main.py`. Nenhuma decisão de autorização deriva de `body.user_id` em rota de aluno; o create é operação privilegiada. Ordem de checagem: existência (404) precede propriedade (403) apenas quando a row não existe — para alvos por `user_id`, o gate de propriedade vem direto.
- **Riscos de regressão:** Blast radius restrito ao bloco NOTIFICATIONS de `routes_admin.py`. Chamadores diretos: `Layout` (read/count/mark/mark-all do próprio usuário — preservado, pois `user_id` == self) e `AdminConsole` (create — preservado, pois admin passa o gate). Risco de regressão se o front enviar `user_id` divergente do token no sino (deve sempre usar o próprio id — confirmar). `mark_read`/`delete` agora exigem a coluna `user_id` no select; conferir que a tabela `notifications` a possui (sim — usada em todos os `.eq("user_id", ...)`). Mudança de `_user` para `current_user` é local às funções tocadas. SEC-ADMIN-4 (gamificação) é irmã mas independente.

## Definition of Done
- [x] Teste de regressão verde para os 6 endpoints: dono autorizado passa; ator cruzado recebe 403 sem leitura/mutação; inexistente recebe 404; STUDENT create → 403; ADMIN create → 201.
- [x] Sem regressão na suíte de segurança (suíte completa 105 testes, 0 falhas).
- [ ] QA Gate: PASS ou CONCERNS.
- [x] `create_notification` segue retornando 201 para ADMIN (teste `test_create_admin_passes`); fluxo do próprio usuário preservado (owner == self passa).

## Dev Agent Record

**Agent:** Dex (@dev)
**Files changed:**
- `backend/routes_admin.py` — imports (`authz` helpers); `notification_count`, `list_notifications`, `mark_all_read` → `require_self_or_role(user_id, current_user, "ADMIN")`; `mark_read`, `delete_notification` → select widened to `id, user_id` + `assert_owner_or_role(row["user_id"], current_user, "ADMIN")` after the 404 existence check; `create_notification` → `Depends(require_role("ADMIN"))`, kept 201. All `_user` params renamed to `current_user`.
- `backend/tests/security/test_idor_admin.py` — new `TestNotificationsIDOR` (15 tests).

**Summary:** Authorization moved to the route edge (no repo changes — `notification_repo.py` untouched). Ownership helpers imported from the shared `authz.py` (no inline/duplicated logic). `body.user_id` is only honoured inside the ADMIN-gated `create_notification`; every student-facing route derives the target from the path and validates it against the token.

**Test results:** `TestNotificationsIDOR` 15/15 pass. Full backend suite: 105 passed, 0 failed, 0 errors (ephemeral venv, removed after run).

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-04 (adversarial security review)

Cluster: **admin-writes** (SEC-ADMIN-3 — notifications IDOR).

`notification_count`/`list_notifications`/`mark_all_read` → `require_self_or_role(user_id, current_user, "ADMIN")` before any query. `mark_read`/`delete_notification` → select widened to `id, user_id`, existence-first (404) then `assert_owner_or_role(row.user_id, current_user, "ADMIN")` (403). `create_notification` → ADMIN-only (`require_role`), the only place a body `user_id` is legitimately a target. Verified: cross-actor count/list/mark/delete all 403 with no leak and no victim mutation (mutation log empty); STUDENT create → 403, nothing injected into the victim feed.

Tests: notifications IDOR suite green; full suite **257 passed, 0 failed**.
