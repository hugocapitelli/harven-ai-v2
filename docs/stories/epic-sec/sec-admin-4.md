---
id: SEC-ADMIN-4
epic: EPIC-SEC
phase: 2
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: medium
depends_on: [SEC-AUTHZ-0, SEC-ADMIN-1]
bug_refs: [14]
---
# SEC-ADMIN-4: IDOR em gamificação + integridade acadêmica

## Story
Como **plataforma Harven.AI responsável pela integridade acadêmica**, quero **que os endpoints de escrita de gamificação (atividades, achievements, certificados, conclusão de conteúdo) só escrevam para o usuário autenticado e validem pontos/elegibilidade no servidor**, para **impedir que qualquer aluno forje pontos, achievements ou certificados HARVEN-numerados para si ou para terceiros**.

## Contexto (do bug sweep)
Item #14 (`backend/routes_admin.py:1053-1100, 1134-1176, 1206-1246, 1297-1379`) — **IDOR em endpoints de escrita de gamificação**.

- `create_activity` (`:1053-1100`), `unlock_achievement` (`:1134-1176`), `issue_certificate` (`:1206-1246`) e `complete_content` (`:1297-1379`) recebem `{user_id}` pelo **path** e só dependem de `get_current_user` — o parâmetro é nomeado `_user` e **nunca é comparado** ao `user_id` do path. Qualquer aluno autenticado escreve em nome de qualquer `user_id`.
- `ActivityCreate.points` (`:80`) vem do cliente e é gravado direto (`:1068`, `:1079`) sem limite nem whitelist → manipulação arbitrária de pontos/leaderboard.
- `issue_certificate` (`:1206`) exige apenas `course_id` no body (`CertificateCreate`, `:96`); **não verifica matrícula nem conclusão** → certificado `HARVEN-AAAAMMDD-XXXXXXXX` (`:1229`) auto-emitido por qualquer aluno.
- `complete_content` (`:1362-1371`) registra atividade com `"points": 10` **hardcoded**, divergente de qualquer mapa central.
- O `service_role` da Supabase bypassa RLS, então a autorização **tem** de ser server-side na rota.

**Impacto:** comprometimento de integridade acadêmica — certificados forjados, achievements falsos, pontuação/leaderboard manipuláveis por qualquer aluno autenticado. Severidade CRITICAL.

## Acceptance Criteria
- [x] **Escrita self-service vincula-se ao chamador, nunca ao path:** em `create_activity`, `unlock_achievement`, `issue_certificate` e `complete_content`, a gravação usa `current_user["id"]` (via `_effective_write_target`) e o `{user_id}` do path/`body.user_id` **nunca é confiado** para escrita self-service.
- [x] **IDOR — dono autorizado passa:** chamador escrevendo para o próprio `user_id` (path == `current_user["id"]`) → 201/200 e a mutação ocorre normalmente.
- [x] **IDOR — ator cruzado bloqueado:** chamador sem papel ADMIN/TEACHER escrevendo para `user_id` ≠ `current_user["id"]` → **403** e **nenhuma escrita** em `user_activities`/`user_achievements`/`certificates`/`course_progress`/`user_stats`. ADMIN/TEACHER autorizados a operar para terceiros.
- [x] **`body.user_id`/path user_id nunca é confiado** como identidade de escrita em fluxo self-service — derivação sempre do token.
- [x] **Whitelist de pontos por `activity_type`:** `ActivityCreate.points` do cliente é **ignorado**; pontos derivam do mapa server-side `gamification_points.ACTIVITY_POINTS`; `activity_type` desconhecido → default seguro 0.
- [x] **`issue_certificate` exige elegibilidade:** não-admin só emite se `progress_percent >= 100` (server-side via `course_progress` do alvo); `< 100` → **403**; `>= 100` → **201**. ADMIN/TEACHER → **201** independente do progresso.
- [x] **`complete_content` usa o mesmo mapa de points** (`points_for("content_completed")`); hardcode `10` removido.
- [x] **Idempotência preservada:** `already_unlocked` / `already_issued` continuam funcionando após o gate (teste `test_unlock_achievement_idempotent`).

## Tasks / Subtasks
- [x] Criar mapa central de pontos em `backend/gamification_points.py` (`ACTIVITY_POINTS` + `points_for(activity_type) -> int`, default 0).
- [x] `create_activity`: `_user` → `current_user`; `assert_owner_or_role(user_id, current_user, "ADMIN", "TEACHER")` (403 cross-user); `body.points` substituído por `points_for(body.activity_type)`; `user_id` efetivo via `_effective_write_target`.
- [x] `unlock_achievement`: mesmo gate antes do dedup e do insert; grava no `target_user_id`.
- [x] `issue_certificate`: gate de autorização; para não-admin, lê `course_progress` do alvo+`course_id` e exige `progress_percent >= 100`, senão 403; ADMIN/TEACHER prossegue sem o check.
- [x] `complete_content`: gate aplicado; `"points": 10` substituído por `points_for("content_completed")`; grava no `target_user_id`.
- [x] Reusado `assert_owner_or_role` (authz.py) + checagem inline de role para a exceção ADMIN/TEACHER (self-service deriva do token).
- [x] 503 (tabelas ausentes) e idempotência preservados (try/except e early-returns intactos).

## Dev Notes
- **Arquivos:**
  - `backend/routes_admin.py` — handlers `create_activity` (`:1053`), `unlock_achievement` (`:1140`), `issue_certificate` (`:1207`), `complete_content` (`:1302`); schemas `ActivityCreate` (`:80`), `CertificateCreate` (`:96`); helper `require_role` (usado a partir de `:186`); dependência `get_current_user`.
  - (Opcional) `backend/gamification_points.py` — novo módulo para o mapa `activity_type → points` reusável.
- **Abordagem:** Derivar a identidade de escrita do token (`current_user["id"]`) e tratar o `{user_id}` do path como alvo apenas para ADMIN/TEACHER; comparar contra `current_user["id"]` e retornar 403 em cross-user no fluxo self-service. Mover pontos para mapa server-side único e referenciá-lo tanto em `create_activity` quanto em `complete_content`. Em `issue_certificate`, consultar `course_progress` (`:1262-1268` mostra o padrão de leitura) para verificar `progress_percent >= 100` antes de gerar o número `HARVEN-...`.
- **Riscos de regressão:**
  - **Blast radius:** todos os 4 endpoints são chamados pelo frontend de gamificação/conclusão de conteúdo. SF-3 (#24) depende de `SEC-ADMIN-4` e passará a chamar `completeContent(user.id, ...)` — alinhar o contrato (path user_id = próprio usuário).
  - **DATA-GAM-2** (#15, unlock idempotente) e **DATA-GAM-4** (#62, state machine de sessão) declaram `depends_on: SEC-ADMIN-4` — o gate de autorização precede a mudança de PK/idempotência; não alterar a forma do payload de unlock aqui além do gate.
  - Mudar pontos de `body.points` para whitelist pode alterar valores exibidos no leaderboard; comunicar que pontos client-supplied serão zerados/ignorados.
  - `depends_on` SEC-AUTHZ-0 (base de authz) e SEC-ADMIN-1 (gate de admin) devem estar mergeados para reuso de `require_role`/helpers de role.

## Definition of Done
- [x] Teste de regressão verde: (a) cross-user write → 403 e zero linhas escritas; (b) self write → 201; (c) `points` do cliente ignorado (whitelist); (d) `issue_certificate` não-admin `progress<100` → 403 e `>=100` → 201; (e) ADMIN/TEACHER → 201 sem o check; (f) `complete_content` grava pontos via mapa.
- [x] Sem regressão na suíte de segurança (105 testes verdes).
- [ ] QA Gate: PASS ou CONCERNS.
- [x] `gamification_points.ACTIVITY_POINTS` é a única fonte de verdade para pontos em `create_activity` e `complete_content` (sem hardcode duplicado).

## Dev Agent Record

**Agent:** Dex (@dev)
**Files changed:**
- `backend/gamification_points.py` — NEW. `ACTIVITY_POINTS` whitelist + `points_for()` (default 0 for unknown/forged types).
- `backend/routes_admin.py` — `_effective_write_target()` helper; `create_activity`, `unlock_achievement`, `issue_certificate`, `complete_content` gated with `assert_owner_or_role(user_id, current_user, "ADMIN", "TEACHER")`; all writes redirected to the token-derived target; `create_activity` ignores `body.points`; `complete_content` uses `points_for("content_completed")`; `issue_certificate` enforces `progress_percent >= 100` for non-privileged self-issuance.
- `backend/tests/security/test_idor_admin.py` — `TestGamificationIDOR` (14 tests).

**Summary:** Write identity always derives from the authenticated token for self-service; ADMIN/TEACHER may act on a path `user_id` cross-user. Points are server-decided (whitelist) so the leaderboard cannot be inflated by a forged body. Certificates require server-verified 100% completion for students; ADMIN/TEACHER may issue administratively. The 503 "tabelas ausentes" guards and `already_unlocked`/`already_issued` idempotency are preserved. `gamification_repo.py` was NOT modified (authz at the route edge).

**Test results:** `TestGamificationIDOR` 14/14 pass. Full backend suite: 105 passed, 0 failed.

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-04 (adversarial security review)

Cluster: **admin-writes** (SEC-ADMIN-4 — gamification write IDOR + academic integrity).

`create_activity`/`unlock_achievement`/`issue_certificate`/`complete_content` gate `assert_owner_or_role(user_id, current_user, "ADMIN", "TEACHER")` BEFORE any read/write, then resolve the write target via `_effective_write_target` (self-service writes always land on the token id; only ADMIN/TEACHER may redirect to a path `user_id`). **Self-issued certs are blocked**: a non-privileged actor needs server-verified `progress_percent >= 100` (`course_progress`), else 403 — verified (50% → 403 no cert, 100% → 201, ADMIN ignores progress). Points are server-decided via `gamification_points.points_for` (whitelist); `body.points=9999` is ignored → 10, unknown type → 0 (verified). Cross-user writes 403 with empty mutation log on user_activities/user_stats/certificates.

Tests: gamification IDOR suite green; full suite **257 passed, 0 failed**.
