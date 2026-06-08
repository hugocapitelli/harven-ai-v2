---
id: SEC-ROT-2
epic: EPIC-SEC
phase: 2
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: low
depends_on: [SEC-ROT-1]
bug_refs: [3]
---
# SEC-ROT-2: Sign/verify a partir do provider DB + seed no startup

## Story
Como engenheiro de Backend & Infra, quero que `create_access_token` e `get_current_user` assinem e validem JWTs a partir do segredo ativo lido do provider DB (`get_active_jwt_secret()`), com o `lifespan` semeando a linha do segredo no startup, para que a plataforma deixe de depender de um secret estático carregado de env var (passível de cair no default fraco `change-me-in-production`) e fique pronta para a rotação dinâmica sem restart (SEC-ROT-3), sem alterar o comportamento de autenticação dos usuários nem as assinaturas das ~96 chamadas existentes.

## Contexto (do bug sweep)
Item #3 do bug sweep — "Secret de assinatura JWT default `change-me-in-production` permite forjar tokens" (Segurança, CRITICAL).

- `backend/config.py:15` declara `JWT_SECRET_KEY: str = "change-me-in-production"` como default literal, **sem guarda de startup**. Se a env var correta não for setada (provável, pois o `.env.example` documenta nomes ERRADOS — `JWT_SECRET`/`SUPABASE_ANON_KEY` em vez dos lidos pelo código `JWT_SECRET_KEY`/`SUPABASE_KEY`), todos os tokens são assinados com um secret público conhecido.
- `backend/auth.py:30` — `create_access_token` faz `jwt.encode(payload, settings.JWT_SECRET_KEY, ...)`, lendo o secret diretamente de `get_settings()` (acoplado ao env, fail-open).
- `backend/auth.py:40` — `get_current_user` faz `jwt.decode(credentials.credentials, settings.JWT_SECRET_KEY, ...)`, idem.
- `backend/main.py:286-291` — `lifespan` atualmente só loga e chama `_ensure_grade_overrides_table()`; não semeia o segredo JWT no DB.

**Impacto:** bypass total de autenticação — um atacante forja um token válido para qualquer `user_id` conhecido (account takeover trivial). Esta story (SEC-ROT-2) consome o provider entregue por SEC-ROT-1 e move a fonte do segredo de assinatura/verificação do env estático para o DB, removendo o fail-open na trilha de sign/verify e habilitando a rotação dinâmica.

## Acceptance Criteria
- [x] `create_access_token` (`backend/auth.py:26-30`) assina o JWT usando `get_active_jwt_secret()` em vez de `settings.JWT_SECRET_KEY` direto.
- [x] `get_current_user` (`backend/auth.py:33-50`) valida/decodifica o JWT usando `get_active_jwt_secret()` em vez de `settings.JWT_SECRET_KEY` direto.
- [x] O `lifespan` (`backend/main.py:287`) semeia a linha do segredo no DB no startup (idempotente: se `system_settings.jwt_secret` já existir, não sobrescreve; se NULL, semeia a partir do bootstrap env `settings.JWT_SECRET_KEY`), reaproveitando o provider de SEC-ROT-1.
- [x] **Auth normal inalterado:** login → emissão de token → uso do token em rota protegida → 200 continua funcionando exatamente como antes (mesmo claims `sub`/`role`/`exp`/`iat`, mesmo algoritmo `settings.JWT_ALGORITHM`).
- [x] **Round-trip consistente:** um token emitido com `get_active_jwt_secret()` é aceito por `get_current_user` na mesma instância sem restart; um token assinado com um secret diferente do ativo é rejeitado com 401.
- [x] **Assinaturas de função intactas:** `create_access_token(user_id, role)` e `get_current_user(credentials, client)` mantêm exatamente as mesmas assinaturas e tipos de retorno — os ~96 call sites existentes não precisam de nenhuma alteração.
- [x] **Fail-closed preservado (herdado de SEC-ROT-1):** em erro de DB ao obter o segredo, o provider faz fallback para `settings.JWT_SECRET_KEY` (nunca para um default fraco hardcoded), e a story não reintroduz fail-open.
- [x] Nenhum segredo plaintext novo é exposto em log, resposta de API ou schema além do já definido em SEC-ROT-1.

## Tasks / Subtasks
- [x] Em `backend/auth.py`: importar `get_active_jwt_secret` e trocar `settings.JWT_SECRET_KEY` por `get_active_jwt_secret(get_supabase())` na linha de `jwt.encode` de `create_access_token`, mantendo `algorithm=settings.JWT_ALGORITHM`. _(create_access_token não recebe client; usa o singleton `database.get_supabase()` para não alterar a assinatura)_
- [x] Em `backend/auth.py`: trocar `settings.JWT_SECRET_KEY` por `get_active_jwt_secret(client)` na linha de `jwt.decode` de `get_current_user` (usa o `client` já injetado via `Depends`), mantendo `algorithms=[settings.JWT_ALGORITHM]` e todo o tratamento de `JWTError`/`sub` ausente intacto.
- [x] Em `backend/main.py`: no `lifespan`, antes do `yield`, chamar `seed_jwt_secret(get_supabase())` via helper `_seed_jwt_secret_on_startup()`, idempotente e tolerante a falha de DB (loga e segue; sign/verify cai no fallback fail-closed sem derrubar o boot).
- [x] Verificar que nenhum call site precisa mudar: assinaturas de `create_access_token(user_id, role)` e `get_current_user(credentials, client)` inalteradas; suíte completa (178 testes) verde sem editar call sites.
- [x] Confirmar que `backend/config.py:JWT_SECRET_KEY` permanece como bootstrap env (seed/fallback), não mais como fonte direta de sign/verify.
- [x] Garantir que `routes_admin.py` (rotação via `.env`) NÃO foi alterado nesta story — alterado apenas em SEC-ROT-3.

## Dev Notes
- **Arquivos:** `backend/auth.py` (linhas 26-30 `create_access_token`, 33-50 `get_current_user`), `backend/main.py` (linhas 286-291 `lifespan`), `backend/config.py:15` (bootstrap env, inalterado em comportamento), provider `get_active_jwt_secret()` entregue por SEC-ROT-1.
- **Abordagem:** substituição cirúrgica do source do segredo — duas linhas de `auth.py` (`jwt.encode`/`jwt.decode`) passam a chamar `get_active_jwt_secret()`; o `lifespan` ganha um passo de seed idempotente. O algoritmo (`settings.JWT_ALGORITHM`), os claims (`sub`/`role`/`exp`/`iat`), a expiração (`settings.JWT_EXPIRATION_HOURS`) e todo o fluxo de exceções permanecem idênticos. Nenhuma assinatura de função muda, então os ~96 call sites (rotas com `Depends(get_current_user)` + emissão de token em login/registro) ficam preservados.
- **Riscos de regressão / blast radius:** `get_current_user` é dependência transitiva de praticamente toda rota protegida (chat, admin, grades, sessions) via `Depends(...)` e `require_role(...)`; `create_access_token` é chamado nos endpoints de login/registro. Um erro aqui derruba autenticação global. Mitigações: (1) manter assinatura/retorno idênticos; (2) garantir round-trip emit→verify na mesma instância antes de merge; (3) confiar no fail-closed do provider de SEC-ROT-1 (fallback para `settings.JWT_SECRET_KEY`, nunca default fraco) em falha de DB; (4) cache TTL do provider (SEC-ROT-1, default 30s) evita martelar o DB a cada decode. Risco secundário: ordem de boot — o seed deve rodar dentro do `lifespan` (DB já disponível), não em import-time.

## Definition of Done
- [x] Teste de regressão (falha-antes / passa-depois) verde: token emitido por `create_access_token` é aceito por `get_current_user` lendo do provider DB (`test_token_roundtrip_via_provider`); token assinado com secret divergente do ativo → 401 (`test_token_signed_with_other_secret_is_rejected`).
- [x] Sem regressão na suíte de segurança (IDOR sweep + override-de-instrutor + min-role continuam verdes; 178 passed).
- [ ] QA Gate: PASS ou CONCERNS _(a cargo do @qa)_.
- [x] Confirmado que as assinaturas de `create_access_token` e `get_current_user` não mudaram e que os ~96 call sites compilam/rodam sem edição.
- [x] Confirmado que o `lifespan` semeia a linha do segredo de forma idempotente no startup e tolera falha de DB sem derrubar o boot (fail-closed via fallback de SEC-ROT-1).
- [x] Confirmado que esta story não toca a rotação via `.env` (`routes_admin.py`) — escopo reservado para SEC-ROT-3.

## Dev Agent Record

**Agent:** Dex (@dev) · auth-infra · 2026-06-04

**Files changed:**
- `backend/auth.py` — `import get_active_jwt_secret`; `create_access_token` signs with `get_active_jwt_secret(get_supabase())`; `get_current_user` verifies with `get_active_jwt_secret(client)` (the already-injected `Depends(get_supabase)` client). Algorithm, claims, expiry, and the `JWTError`/missing-`sub` handling are byte-for-byte unchanged. Function signatures preserved.
- `backend/main.py` — added `_seed_jwt_secret_on_startup()` and call it inside `lifespan` before `yield` (after `_ensure_grade_overrides_table()`); it seeds via `seed_jwt_secret(get_supabase())`, idempotent and DB-failure-tolerant (logs and proceeds). The Phase-1 boot guard in `config.py` is untouched and still runs.
- `backend/tests/security/test_jwt_rotation.py` — SEC-ROT-2 round-trip + divergent-secret-401 coverage.

**Summary:** Sign/verify now source the secret from the DB-backed provider instead of the static env var, removing the fail-open on the auth trail and enabling dynamic rotation. The bootstrap env var remains only as seed/fallback. No call site changed: a single `database.get_supabase()` call inside `create_access_token` keeps `(user_id, role)` intact, and `get_current_user` reuses its injected client. Round-trip emit→verify holds in-process; a token under a divergent secret → 401. IDS: REUSED `database.get_supabase` singleton and the SEC-ROT-1 provider; no new helpers redefined.

**Test results:** `pytest tests/` → **178 passed, 0 failed** (ephemeral venv, Python 3.14.3). Pre-existing auth/IDOR suites unchanged; no call-site edits required.

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-04 (adversarial security review)

Cluster: **jwt-rotation** (SEC-ROT-2 — sign/verify via provider + startup seed).

`create_access_token` signs with `get_active_jwt_secret(get_supabase())`; `get_current_user` verifies with the provider using its already-injected `Depends(get_supabase)` client — algorithm/claims/expiry/`JWTError` handling byte-for-byte unchanged, signatures preserved (no call-site churn). Round-trip emit→verify holds; a token under a divergent secret → 401 (verified). **Phase-1 boot guard NOT broken**: the `config.py` validator is untouched and still aborts production boot on a weak secret — confirmed by `test_security_hotfix.py` (`test_boot_fail_closed_in_production_with_weak_secret`, `test_boot_succeeds_in_production_with_strong_secret`, `test_forged_token_with_default_is_rejected_under_strong_secret` all green). Normal login path intact. `lifespan` seed is idempotent and DB-failure-tolerant (logs and proceeds, fail-closed fallback).

Tests: full suite **257 passed, 0 failed** (incl. 21 Phase-1 hotfix tests).
