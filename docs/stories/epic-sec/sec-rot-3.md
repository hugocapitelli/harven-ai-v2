---
id: SEC-ROT-3
epic: EPIC-SEC
phase: 2
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: low
depends_on: [SEC-ROT-2]
bug_refs: [3, 22]
---
# SEC-ROT-3: force_logout rotaciona o segredo no DB (para de mutar .env) + invalida cache

## Story
Como administrador da plataforma Harven.AI, quero que a ação "Invalidar todos os tokens" (force logout) rotacione o segredo JWT no banco de dados em vez de reescrever o arquivo `.env`, para que a invalidação tenha efeito imediato sem restart e os tokens emitidos antes da rotação sejam genuinamente rejeitados.

## Contexto (do bug sweep)
Bug #3 / item #22 do BUG-SWEEP-2026-06-03.md (`backend/routes_admin.py:614-646`).

**O defeito concreto:** o endpoint `POST /admin/force-logout` gera `secrets.token_urlsafe(48)` e o escreve no arquivo `/app/backend/.env` (`routes_admin.py:623-639`), depois chama `config.get_settings.cache_clear()` (`:642-643`). Porém:
- O `docker-compose` injeta o segredo via `env_file: .env` como **variáveis de ambiente reais** e `main.py` chama `load_dotenv()` no boot.
- `pydantic-settings` ranqueia **env vars acima** do arquivo `.env`. Logo, reescrever o arquivo é **ignorado** em todo `get_settings()` subsequente.

**Impacto (CRITICAL):** a ação de segurança mais sensível do painel — invalidar todas as sessões após um comprometimento — é **inócua em produção**. Tokens supostamente revogados continuam válidos até o segredo de ambiente mudar (o que só ocorreria com um redeploy manual do `.env`). Além disso, há escrita em filesystem em runtime (frágil em diretório read-only / multi-worker). A correção canônica (BUG-SWEEP `:307`) é armazenar o segredo ativo no DB (`system_settings`) — exatamente o que SEC-ROT-1/2 prepararam — e fazer o `force_logout` rotacionar essa linha e invalidar o cache do provider.

## Acceptance Criteria
- [x] `force_logout` NÃO executa nenhum `open(...,"w")` / `f.writelines` / qualquer write em filesystem — todo o bloco de manipulação de `.env` foi removido. _(asseverado por tripwire em `test_force_logout_rotates_db_secret_and_no_fs_write`)_
- [x] `force_logout` gera `secrets.token_urlsafe(48)` e persiste em `system_settings.jwt_secret` + atualiza `system_settings.jwt_secret_rotated_at` (colunas criadas em SEC-ROT-1).
- [x] Após a gravação, o cache do provider (`invalidate_jwt_secret_cache()`) é invalidado imediatamente, de modo que a próxima requisição verifique tokens com o novo segredo sem aguardar o TTL.
- [x] **Pré-rotação rejeitado:** um token emitido ANTES do `force_logout` retorna **401** em endpoint protegido após a chamada, **sem restart**.
- [x] **Pós-rotação válido:** um login realizado APÓS o `force_logout` emite um token que valida normalmente (200).
- [x] Autorização preservada: o endpoint mantém `Depends(require_role("ADMIN"))` — não-admin recebe 403; sem token recebe 401.
- [x] Audit log preservado: a chamada `_log(client, f"Force logout executado por {admin['name']}", ..., log_type="security")` continua sendo emitida com o mesmo conteúdo.
- [x] Contrato frontend inalterado: `forceLogoutAll()` continua sendo `POST /admin/force-logout` sem corpo; rota, método, status 200 e shape de resposta (`{"message": "..."}`) preservados (nenhuma edição no frontend).

## Tasks / Subtasks
- [x] Em `backend/routes_admin.py`, removido o bloco de mutação de `.env` em `force_logout` (todo o `open(...,"w")`/`writelines`). O `import os` foi mantido — permanece usado por 20 outras ocorrências no arquivo (ex.: `os.path.isfile` em `delete_backup`).
- [x] Substituído por: `new_secret = secrets.token_urlsafe(48)` → `row = _get_or_create_settings(client)` → `client.table("system_settings").update({"jwt_secret": new_secret, "jwt_secret_rotated_at": datetime.now(timezone.utc).isoformat()}).eq("id", row["id"]).execute()` (alinhado ao padrão de update de `system_settings` já usado no arquivo via `_get_or_create_settings`).
- [x] Trocado `from config import get_settings as _gs; _gs.cache_clear()` por `invalidate_jwt_secret_cache()` (do `jwt_secret_provider`, mesmo módulo de `get_active_jwt_secret` — nome confirmado contra SEC-ROT-2).
- [x] Mantidos intactos `Depends(require_role("ADMIN"))`, o `_log(... log_type="security")` e o `return {"message": ...}`.
- [x] Adicionado teste de regressão cobrindo pré-rotação → 401 e pós-rotação → 200, mais tripwire de no-FS-write.
- [x] Verificado que `forceLogoutAll()` no frontend não requer mudança (contrato HTTP inalterado).

## Dev Notes
- **Arquivos:**
  - `backend/routes_admin.py` (alvo principal — `force_logout`, `:614-646`)
  - `backend/config.py` / provider de segredo JWT criado em SEC-ROT-1/2 (origem de `get_active_jwt_secret` e do helper de invalidação de cache)
  - `frontend/src/services/api.ts:221` (verificação de contrato — não editar)
  - Migration `20260603g_jwt_secret.sql` (SEC-ROT-1) define `system_settings.jwt_secret` / `jwt_secret_rotated_at`
- **Abordagem:** Esta story é o terceiro passo da cadeia de rotação de segredo. SEC-ROT-1 criou as colunas DB + provider com cache TTL; SEC-ROT-2 fez sign/verify lerem do provider. SEC-ROT-3 apenas troca a **origem da rotação**: de "escrever `.env` (ignorado pela precedência de env vars)" para "UPDATE em `system_settings` + invalidação de cache do provider". Como verify já lê do provider (SEC-ROT-2), atualizar a linha + invalidar cache faz tokens pré-rotação falharem na verificação de assinatura imediatamente (401), sem restart.
- **Riscos de regressão (blast radius):** O endpoint `POST /admin/force-logout` é chamado apenas por `forceLogoutAll()` (`api.ts:221`), usado em `frontend/src/views/admin/SystemSettings.tsx`. Como assinaturas e contrato HTTP não mudam, o frontend não é afetado. O risco real está no acoplamento com SEC-ROT-2: se o helper de invalidação de cache do provider tiver nome/assinatura diferente do assumido, a rotação não terá efeito imediato (cairia para invalidação só após o TTL) — confirmar o helper exato durante a implementação. O endpoint vizinho `clear-cache` (`:649-657`) ainda usa `get_settings.cache_clear()`; está fora de escopo desta story e não deve ser tocado.

## Definition of Done
- [x] Teste de regressão verde: token emitido antes de `force_logout` → 401 após a chamada; login posterior → 200 (`test_pre_rotation_token_rejected_post_rotation`).
- [x] Sem regressão na suíte de segurança (require_role/admin guards, auth normal de SEC-ROT-2 intacto; 178 passed).
- [ ] QA Gate: PASS ou CONCERNS _(a cargo do @qa)_.
- [x] Confirmado por teste (tripwire em `builtins.open`) que `force_logout` não executa nenhuma operação de write em filesystem.
- [x] Confirmado que o audit log `log_type="security"` continua sendo emitido e o contrato `forceLogoutAll()` permanece `POST /admin/force-logout` sem corpo.

## Dev Agent Record

**Agent:** Dex (@dev) · auth-infra · 2026-06-04

**Files changed:**
- `backend/routes_admin.py` — `force_logout` rewritten: removed the entire `.env` rewrite block (`open(...,"w")` / `writelines` / `os.path.join(... ".env")`) and the `get_settings.cache_clear()` call. New body: `secrets.token_urlsafe(48)` → `_get_or_create_settings(client)` → `update({jwt_secret, jwt_secret_rotated_at}).eq("id", row["id"])` → `invalidate_jwt_secret_cache()`. `require_role("ADMIN")` guard, `_log(..., log_type="security")`, and `{"message": ...}` response are unchanged. `import os` kept (still used by 20 other call sites in the file). Sibling `clear-cache` endpoint left untouched (out of scope).
- `backend/tests/security/test_jwt_rotation.py` — SEC-ROT-3 coverage: DB-rotation + no-FS-write tripwire + audit-log assertion; pre-rotation token → 401 / post-rotation login → 200.

**Summary:** Root cause of bug #22 closed. Force-logout now rotates the secret in `system_settings` (durable source of truth from SEC-ROT-1) and eagerly drops the provider cache, so since SEC-ROT-2 already verifies from that provider, every pre-rotation token fails signature verification on the next request — no restart, no filesystem write. The frontend contract (`POST /admin/force-logout`, no body, `{"message": ...}`) is unchanged. IDS: REUSED `_get_or_create_settings` (existing singleton-row helper) and `invalidate_jwt_secret_cache` (SEC-ROT-1); nothing redefined.

**Test results:** `pytest tests/` → **178 passed, 0 failed** (ephemeral venv, Python 3.14.3). The no-FS-write tripwire and pre/post-rotation 401/200 tests pass.

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-04 (adversarial security review)

Cluster: **jwt-rotation** (SEC-ROT-3 — force_logout rotates in DB, no FS write).

Root cause of bug #22 closed: `force_logout` no longer rewrites `.env` (inert under docker-compose env precedence). It now generates `secrets.token_urlsafe(48)`, updates `system_settings.jwt_secret` + `jwt_secret_rotated_at`, and eagerly calls `invalidate_jwt_secret_cache()`. **force_logout now actually invalidates tokens**: the end-to-end test proves a pre-rotation token → 401 after rotation AND a fresh login → 200, with no restart. A `builtins.open` tripwire confirms no `.env`/FS write occurs. Audit log (`log_type="security"`) and the `POST /admin/force-logout` no-body contract preserved. ADMIN-only gate intact.

Minor note (non-blocking): `force_logout` rotates the row from `_get_or_create_settings` (`.limit(1)`) and the provider also reads `.limit(1)` — consistent for the documented singleton `system_settings`. If multiple settings rows ever exist, both should be pinned to the same row id; harmless today.

Tests: SEC-ROT-3 (no-FS-write + pre/post-rotation 401/200) green; full suite **257 passed, 0 failed**.
