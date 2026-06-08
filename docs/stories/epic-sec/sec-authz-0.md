---
id: SEC-AUTHZ-0
epic: EPIC-SEC
phase: 2
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: low
depends_on: [SEC-ATO-3]
bug_refs: [2, 13]
---
# SEC-AUTHZ-0: Módulo authz.py + harness de teste IDOR

## Story
Como engenheiro de backend da plataforma Harven.AI, quero um módulo `authz.py` que centralize os helpers de verificação de propriedade (ownership) e de papel (role), acompanhado de um harness de teste que simula o cliente Supabase sem banco real, para que todas as stories de remediação de IDOR (SEC-CHAT-*, SEC-ADMIN-*, SEC-SCOPE-*) reusem a mesma barreira de autorização testável, eliminando a duplicação de lógica e a única falha sistêmica que hoje deixa registros educacionais de qualquer aluno expostos.

## Contexto (do bug sweep)
A camada de autorização da aplicação é **a única barreira** existente — não há nenhuma política RLS no schema e o cliente Supabase é único, compartilhado, com `SUPABASE_KEY` estática que decodifica para `service_role` (bypassa RLS). Essa barreira está ausente em praticamente toda a superfície de chat-sessions, prepare-export, notificações e gamificação.

- **Item #2 — IDOR massivo** (`backend/routes_ai.py:775-911, 934-965`): endpoints que recebem `session_id`/`user_id` por path/body só exigem JWT válido (`get_current_user`) e **nunca filtram por `current_user["id"]`**. `create_or_get_chat_session` ainda aceita `body.user_id` arbitrário (`uid = data.user_id or current_user["id"]`). Impacto: leitura/escrita cross-aluno de transcrições socráticas, injeção de mensagens forjadas, conclusão de sessão alheia, spoofing de `user_id`.
- **Item #13 — prepare-export sem checagem de propriedade** (`backend/routes_ai.py:295-405`): `ai_organizer_prepare_export` carrega `chat_sessions`, `chat_messages`, `users` (name+email) e contents via cliente service-role **sem verificar que a sessão pertence ao `current_user`**, expondo PII (nome, e-mail) e transcrições completas de outros alunos.

A direção de correção em ambos os itens converge para **dois primitivos reusáveis**: verificar `session.user_id == current_user["id"]` (com override TEACHER/ADMIN/INSTRUCTOR) e resolver `session_id` → 404 quando a row é nula, **antes** de qualquer enrichment ou mutação, nunca confiando em `user_id`/`content_id` vindos do body. Esta story entrega esses primitivos como base para todas as demais stories do EPIC-SEC Fase 2.

## Acceptance Criteria
- [x] Existe o módulo `backend/authz.py` como home canônica dos helpers de ownership/role (nenhuma duplicação dessa lógica nos routes).
- [x] `assert_owner_or_role(resource_owner_id, current_user, *roles)`: **dono autorizado passa** (resource_owner_id == current_user["id"] → retorna sem erro / não levanta); **ator cruzado recebe 403** quando STUDENT estranho e nenhuma leitura ou mutação ocorre (helper levanta `HTTPException(403)` antes de qualquer side-effect, pois é função pura que apenas decide); ADMIN, TEACHER e INSTRUCTOR são aceitos como override mesmo não sendo dono (case-insensitive no role).
- [x] `load_session_or_404(client, session_id)` retorna a row da sessão quando existe e **levanta `HTTPException(404)` em row nula** (resultado `.execute()` com `data` None/vazio).
- [x] **`body.user_id` nunca é confiado**: os helpers derivam o ator/dono da sessão carregada ou de `current_user`, jamais de um campo do body (a assinatura dos helpers não recebe `user_id` de body como fonte de verdade).
- [x] Helpers **sem acoplamento a `Depends`**: `assert_owner_or_role` e `load_session_or_404` são funções comuns (não dependências FastAPI), chamáveis de dentro de qualquer handler e testáveis isoladamente sem o stack do FastAPI.
- [x] Harness de teste fornece um **fake Supabase client** com chained builder (`.table().select().eq().maybe_single().execute()` etc.) **sem banco real**, parametrizável para retornar uma row, None, ou múltiplas rows — permitindo simular os 3 desfechos do IDOR.
- [x] Teste de IDOR cobre os 3 desfechos: (a) **dono autorizado passa**; (b) **ator cruzado (STUDENT estranho) recebe 403 e nenhuma leitura-mutação ocorre**; (c) **`body.user_id` nunca é confiado** (ator forjado no body é ignorado em favor da identidade autenticada / dono da row).
- [x] Teste de `load_session_or_404` cobre: row presente → retorna row; row nula → 404.

## Tasks / Subtasks
- [x] Criar `backend/authz.py` com `assert_owner_or_role(resource_owner_id, current_user, *roles)` reusando a semântica de `require_role` já existente em `backend/auth.py:53` (case-insensitive, conjunto de roles permitidos), mas como função pura sem `Depends`.
- [x] Implementar `load_session_or_404(client, session_id)` que executa `client.table("chat_sessions").select(...).eq("id", session_id).maybe_single().execute()` (espelhando o padrão de `get_current_user` em `backend/auth.py:47`) e levanta `HTTPException(404)` quando `res.data` é None.
- [x] Definir o conjunto canônico de roles privilegiados (`ADMIN`, `TEACHER`, `INSTRUCTOR`) como constante reusável em `authz.py` para uso consistente nas stories SEC-CHAT-* e SEC-ADMIN-*.
- [x] Criar harness de teste em `backend/tests/conftest.py` (ou `backend/tests/fakes.py`) com um `FakeSupabaseClient` que implementa o chained builder (`table`, `select`, `eq`, `maybe_single`, `single`, `execute`, `insert`, `update`) retornando dados configuráveis, sem DB real.
- [x] Criar `backend/tests/test_authz.py` com casos: dono passa; STUDENT cruzado → 403; ADMIN/TEACHER/INSTRUCTOR override → passa; `load_session_or_404` row presente vs None; e o caso "body.user_id forjado é ignorado".
- [x] Garantir que os helpers não importam nada de `routes_ai.py` (evitar import circular) — `authz.py` depende apenas de `fastapi.HTTPException` e do tipo do client.

## Dev Notes
- **Arquivos:**
  - Novo: `/Users/hugocapitelli/Dev/eximia/harven-ai-v2/backend/authz.py`
  - Novo: `/Users/hugocapitelli/Dev/eximia/harven-ai-v2/backend/tests/test_authz.py`
  - Novo/editar: `/Users/hugocapitelli/Dev/eximia/harven-ai-v2/backend/tests/conftest.py` (fake Supabase chained builder)
  - Referência (não modificar nesta story): `/Users/hugocapitelli/Dev/eximia/harven-ai-v2/backend/auth.py` (`get_current_user` em :33, `require_role` em :53) e os call sites em `/Users/hugocapitelli/Dev/eximia/harven-ai-v2/backend/routes_ai.py:295-405, 775-911, 934-965`.
- **Abordagem:** Extrair a decisão de autorização para funções puras. `require_role` já existe como dependência FastAPI (`auth.py:53-61`); `assert_owner_or_role` reaproveita a mesma checagem `role.upper() in allowed` mas adiciona o caminho "dono" (`resource_owner_id == current_user["id"]`) e roda **dentro** do handler (não como `Depends`), pois só após carregar a row sabemos quem é o dono. `load_session_or_404` espelha o padrão `.maybe_single().execute()` + checagem de `res.data is None` já usado em `get_current_user` (`auth.py:47-49`). O fake Supabase replica a fluência do SDK supabase-py para que os testes exercitem o caminho real de query sem rede/DB.
- **Riscos de regressão:** Esta story **só adiciona** um módulo novo e testes; não altera handlers existentes (a aplicação dos helpers acontece em SEC-CHAT-1..5, SEC-ADMIN-2..5 e SEC-SCOPE-1, todas `depends_on: SEC-AUTHZ-0`). Blast radius direto = zero sobre runtime atual. Risco a vigiar: a assinatura pública de `assert_owner_or_role` e `load_session_or_404` é contrato consumido por ~10 stories downstream — defini-la mal força retrabalho em cascata. Garantir nomes, ordem de parâmetros e semântica de exceção (403 vs 404) estáveis. `depends_on: SEC-ATO-3` (secret JWT corrigido) assegura que a identidade autenticada usada nos helpers já não é forjável.

## Definition of Done
- [x] Teste de regressão (falha-antes / passa-depois) verde
- [x] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS _(a preencher pelo @qa)_
- [x] `assert_owner_or_role` e `load_session_or_404` são funções sem `Depends`, importáveis isoladamente, com cobertura dos 3 desfechos IDOR (dono passa / cruzado 403 / body.user_id ignorado) e do 404 em row nula
- [x] Fake Supabase chained builder roda os testes sem nenhuma conexão a banco real
- [~] ~~Nenhum handler de produção foi modificado nesta story~~ — **DIVERGÊNCIA DELIBERADA** (ver Dev Agent Record): o briefing do Foundation determinou explicitamente "Wire ONE reference usage in routes_ai.py to prove the pattern". Aplicado o mínimo viável (anti-spoof em `create_or_get_chat_session`), preservando todo o fluxo legítimo.

## Dev Agent Record

**Status:** Ready for Review · **Agent:** Dex (@dev) · **Label:** foundation

### Files changed
- **Novo** `backend/authz.py` — módulo canônico de ownership/role. Helpers (todos funções puras, sem `Depends`):
  - `assert_owner_or_role(resource_owner_id, current_user, *allowed_roles)` — dono passa; role privilegiado (case-insensitive) faz override; senão `HTTPException(403)` antes de qualquer side-effect.
  - `require_self_or_role(path_user_id, current_user, *allowed_roles)` — wrapper para endpoints `/users/{user_id}/...` (delega a `assert_owner_or_role`).
  - `load_session_or_404(client, session_id)` — espelha `.maybe_single().execute()` de `auth.get_current_user`; retorna a row ou `HTTPException(404)`.
  - `assert_teacher_owns_discipline(discipline_id, current_user, repo)` — ADMIN bypassa; TEACHER/INSTRUCTOR escopado via `repo.get_teacher_discipline_ids()`; senão `403`.
  - Constantes `PRIVILEGED_ROLES` e `DISCIPLINE_PRIVILEGED_ROLES`. Importa apenas `fastapi.HTTPException` (zero acoplamento a `routes_ai.py`/`main.py` — sem ciclo).
- **Novo** `backend/tests/test_authz.py` — 21 testes unitários dos helpers (3 desfechos IDOR + 404 + override de role + escopo de disciplina), exercitando o fake sem DB.
- **Novo** `backend/tests/fakes.py` — `FakeSupabaseClient` (builder encadeado in-memory: `table/select/eq/order/limit/single/maybe_single/insert/update/delete/execute`, retorna `.data`/`.count`, log de mutações). Compartilhado com SEC-ADMIN-1.
- **Editado** `backend/tests/conftest.py` — estendido (Phase-1 preservado) com seed, fixtures e re-export do fake (ver SEC-ADMIN-1).
- **Editado** `backend/routes_ai.py` — reference usage: `import authz.assert_owner_or_role`; em `create_or_get_chat_session` o `uid` passou a derivar **somente** de `current_user["id"]` e um `data.user_id` divergente é barrado por `assert_owner_or_role(...)`; adicionado `except HTTPException: raise` para que o 403 não seja mascarado em 500 pelo handler genérico.

### Summary
Entrega os primitivos de autorização que ~10 stories downstream consomem por import (nunca redefinindo a lógica inline). O contrato de 3 desfechos é provado tanto em unidade (`test_authz.py`) quanto end-to-end na reference usage (`tests/security/test_harness_smoke.py`). A divergência do DoD "nenhum handler modificado" foi um override explícito do briefing do Foundation; o blast radius é mínimo e o fluxo legítimo (dono cria sua própria sessão; ADMIN/TEACHER override) foi preservado.

### Test results
- `cd backend && pytest` → **49 passed** (venv efêmero `--system-site-packages` + pytest/httpx, removido após o run; env Supabase vazio).
- Breakdown: `test_authz.py` 21 · `test_security_hotfix.py` (Phase-1, sem regressão) 21 · `tests/security/test_harness_smoke.py` 7.

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-04 (adversarial security review)

Cluster: **foundation (authz + harness)**.

`backend/authz.py` reviewed line-by-line and probed adversarially:
- `assert_owner_or_role` cannot be bypassed. The `None == None` ownership trap is correctly avoided (the owner path requires `resource_owner_id is not None AND actor_id is not None` before comparing). Verified: NULL owner + STUDENT → 403; no-id actor → 403; None/None → 403 (not a match); empty `allowed_roles` → no override → 403; role match is case/whitespace-insensitive.
- Fail-closed by construction: a row with NULL `user_id` falls through the owner path to the role check (a non-privileged actor is denied).
- `load_session_or_404` fails closed (404 on missing/None data) and returns the row so a single load serves existence + ownership; 404-not-403 correctly avoids existence disclosure.
- `require_self_or_role` and `assert_teacher_owns_discipline` derive identity strictly from `current_user["id"]`, never from path/body; ADMIN bypass + teacher discipline-set membership verified against `discipline_teachers`.
- Pure-decision contract holds: helpers only raise/return, no state read/mutation beyond the explicit loader — a denied actor produces no side-effect.

Harness (`conftest.py` / `fakes.py` / `idor_helpers.py`): in-process, no DB; mutation log enables "no-write-on-deny" proofs; unsupported chains raise `NotImplementedError` (loud, anti-false-green). No false-greens detected.

Tests: `test_authz.py` 21 passed; full suite **257 passed, 0 failed**.
