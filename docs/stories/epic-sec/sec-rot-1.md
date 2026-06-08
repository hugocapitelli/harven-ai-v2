---
id: SEC-ROT-1
epic: EPIC-SEC
phase: 2
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: medium
depends_on: [SEC-ATO-2]
bug_refs: [3, 22]
---
# SEC-ROT-1: Colunas DB do segredo JWT em system_settings + provider com cache TTL

## Story
Como engenheiro de plataforma da Harven.AI, quero que o segredo de assinatura JWT viva no banco (`system_settings`) e seja lido por um provider com cache TTL e fail-closed, para que a rotação de segredo (force_logout) realmente invalide tokens e nenhum deploy assine tokens com um secret default público conhecido.

## Contexto (do bug sweep)
Dois defeitos verificados convergem para a mesma raiz — o segredo JWT é estático e preso à env var, sem fonte de verdade durável e rotacionável:

- **Bug #3** (`backend/config.py:15`, template em `.env.example:11-15`): `JWT_SECRET_KEY: str = "change-me-in-production"` tem default literal público, sem guarda de startup. Como o `.env.example` documenta nomes ERRADOS (`SUPABASE_ANON_KEY`/`JWT_SECRET` em vez dos lidos pelo código, `SUPABASE_KEY`/`JWT_SECRET_KEY`), qualquer deploy que siga o template verbatim assina todos os tokens com um secret público conhecido → **bypass total de autenticação** (atacante forja token para qualquer `user_id`). É fail-open por design.
- **Bug #22** (`backend/routes_admin.py:614-646`): a ação "invalidar todos os tokens" reescreve `JWT_SECRET_KEY` no `/app/.env` e chama `get_settings.cache_clear()`. Mas docker-compose injeta via `env_file: .env` como variáveis de ambiente reais e `main.py` chama `load_dotenv()` no boot; pydantic-settings ranqueia env vars ACIMA do arquivo `.env`, então a reescrita é **silenciosamente ignorada** em todo `get_settings()`. Admin acredita que matou as sessões, mas tokens continuam válidos até o restart do container.

Esta story estabelece a infraestrutura de dados e o provider (não altera ainda os call sites de sign/verify — isso é SEC-ROT-2): colunas DB, leitura/seed do segredo, cache TTL e fail-closed.

## Acceptance Criteria
- [x] Migration G (`supabase/migrations/20260603g_jwt_secret.sql`) adiciona `system_settings.jwt_secret TEXT NULL` e `system_settings.jwt_secret_rotated_at TIMESTAMPTZ NULL`, ambas **nullable**, sem valor default plaintext gravado no schema.
- [x] Existe `get_active_jwt_secret()` que lê o segredo da linha de `system_settings` no DB.
- [x] Quando `system_settings.jwt_secret` é NULL, o provider **semeia** a coluna a partir do valor de bootstrap em `settings.JWT_SECRET_KEY` (env) e persiste, setando `jwt_secret_rotated_at`; chamadas subsequentes leem do DB.
- [x] O provider mantém um **cache em memória com TTL** (default 30s) para evitar uma query por requisição; após o TTL o valor é relido do DB (de modo que uma rotação via `force_logout` propague em ≤ TTL).
- [x] **Fail-closed:** em erro de leitura do DB, `get_active_jwt_secret()` faz fallback para `settings.JWT_SECRET_KEY` (bootstrap) e NUNCA retorna um secret default fraco/vazio (`''`, `change-me-in-production`, ou < 32 chars); se o bootstrap também for fraco, levanta exceção em vez de assinar com secret público.
- [x] Schema final não contém nenhum segredo plaintext literal (nem o default `change-me-in-production`) — o valor só existe em runtime via seed.
- [x] Assinaturas de `create_access_token`/`get_current_user` permanecem intactas nesta story (a migração dos call sites é SEC-ROT-2); nenhum comportamento de auth muda ainda para o usuário final.

## Tasks / Subtasks
- [x] Criar `supabase/migrations/20260603g_jwt_secret.sql`: `ALTER TABLE system_settings ADD COLUMN jwt_secret TEXT, ADD COLUMN jwt_secret_rotated_at TIMESTAMPTZ;` (ambas nullable, sem default plaintext). _(usei `ADD COLUMN IF NOT EXISTS` para idempotência da migração)_
- [x] Criar o provider de segredo (`backend/jwt_secret_provider.py`) com `get_active_jwt_secret(client) -> str` reutilizando `get_supabase` / `database.get_supabase`.
- [x] Implementar leitura da linha `system_settings` (singleton) → coluna `jwt_secret`.
- [x] Implementar seed-on-NULL: se `jwt_secret` é NULL, gravar `settings.JWT_SECRET_KEY` na coluna + `jwt_secret_rotated_at = now()`, então retornar (cria a linha singleton se ausente).
- [x] Implementar cache em memória com TTL configurável (`JWT_SECRET_CACHE_TTL`, default 30) — armazena `(secret, fetched_at_monotonic)`, invalida após TTL; thread-safe via lock.
- [x] Implementar validação fail-closed: rejeitar `''`, `change-me-in-production` e secrets < 32 chars (reusa `config.WEAK_JWT_SECRETS` / `MIN_JWT_SECRET_LENGTH` do Fase-1); fallback para bootstrap env em erro de DB; `WeakJWTSecretError` se nem o bootstrap for válido.
- [x] Adicionar `JWT_SECRET_CACHE_TTL: int = 30` em `backend/config.py` (sem tocar nas demais settings).
- [x] Adicionar teste de regressão (ver DoD).

## Dev Notes
- **Arquivos:**
  - `supabase/migrations/20260603g_jwt_secret.sql` (novo — Migration G)
  - `backend/jwt_secret_provider.py` (novo) ou nova função em `backend/auth.py`
  - `backend/config.py` (linha 15: `JWT_SECRET_KEY`; adicionar `JWT_SECRET_CACHE_TTL`)
  - `backend/database.py` (`get_supabase` — reuso do client)
  - Schema base: `backend/supabase_schema.sql` (referência da tabela `system_settings`)
- **Abordagem:** O segredo JWT passa a ter o DB como fonte de verdade durável. `get_active_jwt_secret()` lê `system_settings.jwt_secret`; em NULL semeia do env de bootstrap (`settings.JWT_SECRET_KEY`) e persiste. Um cache de processo com TTL (30s) evita uma query por requisição mas garante que uma rotação (force_logout, SEC-ROT-3) propague em ≤ TTL — corrigindo a raiz do bug #22 (precedência de env var sobre `.env`). O fail-closed garante que nenhum deploy assine com secret público (bug #3): em erro de DB usamos o bootstrap; se o bootstrap for fraco, levantamos exceção em vez de degradar para o default. **Nenhum segredo plaintext fica no schema** — a coluna nasce NULL e é semeada em runtime.
- **Riscos de regressão:** Esta story NÃO altera ainda `create_access_token` (`backend/auth.py:26-30`) nem `get_current_user` (`backend/auth.py:33-40`) — ambos continuam usando `settings.JWT_SECRET_KEY` direto; a troca para o provider é SEC-ROT-2 (~96 call sites preservados). Blast radius desta story limita-se a: (1) schema de `system_settings` (nova coluna nullable, aditiva, sem impacto em queries existentes); (2) `config.py` (nova setting com default, aditiva); (3) novo módulo do provider (sem importadores até SEC-ROT-2). Dependência **SEC-ATO-2** deve estar mergeada antes (reconciliação de `.env.example` / nomes de env var) para que o bootstrap `JWT_SECRET_KEY` seja lido corretamente. Cuidado para a query de seed ser idempotente (não sobrescrever um segredo já presente) e atômica o suficiente para não duplicar seeds sob concorrência no primeiro boot.

## Definition of Done
- [x] Teste de regressão (falha-antes / passa-depois) verde
- [x] Sem regressão na suíte de segurança (178 passed)
- [ ] QA Gate: PASS ou CONCERNS _(a cargo do @qa)_
- [x] Teste: `get_active_jwt_secret()` semeia do bootstrap quando coluna é NULL e persiste (`jwt_secret_rotated_at` setado) — `test_seed_on_null_persists_and_stamps_rotated_at`, `test_seed_creates_row_when_settings_absent`
- [x] Teste: segunda chamada dentro do TTL não consulta o DB (usa cache); após TTL relê — `test_cache_hit_within_ttl_does_not_query_db`, `test_cache_expiry_rereads_db`
- [x] Teste: erro de DB → fallback para bootstrap válido; bootstrap fraco/`change-me-in-production`/< 32 chars → exceção — `test_db_error_falls_back_to_strong_bootstrap`, `test_db_error_with_weak_bootstrap_raises`, `test_short_bootstrap_raises`
- [x] Verificação: schema (migration + `supabase_schema.sql`) não contém nenhum segredo plaintext literal

## Dev Agent Record

**Agent:** Dex (@dev) · auth-infra · 2026-06-04

**Files changed:**
- `supabase/migrations/20260603g_jwt_secret.sql` (new) — adds `jwt_secret TEXT` + `jwt_secret_rotated_at TIMESTAMPTZ` (both nullable, no plaintext default; `IF NOT EXISTS` for idempotency).
- `backend/jwt_secret_provider.py` (new) — `get_active_jwt_secret(client)`, `seed_jwt_secret(client)`, `invalidate_jwt_secret_cache()`, `WeakJWTSecretError`. DB-as-source-of-truth with seed-on-NULL, process-local TTL cache (thread-safe), and fail-closed validation reusing `config.WEAK_JWT_SECRETS` / `MIN_JWT_SECRET_LENGTH`.
- `backend/config.py` — added `JWT_SECRET_CACHE_TTL: int = 30` (additive; no change to existing settings or the Phase-1 boot validator).
- `backend/tests/conftest.py` — extended the shared seed (additively) with a `system_settings` singleton row (`jwt_secret=None` to exercise seed-on-NULL) + empty `system_logs`.
- `backend/tests/security/test_jwt_rotation.py` (new) — provider unit coverage (SEC-ROT-1 section, 8 tests).

**Summary:** The JWT signing secret now has the DB as durable source of truth. Provider reads `system_settings.jwt_secret`; on NULL it seeds from the bootstrap env (`settings.JWT_SECRET_KEY`), persists, and stamps `jwt_secret_rotated_at`. A 30s TTL cache avoids a query-per-request while letting a rotation propagate within ≤ TTL. Fail-closed: DB error → strong-bootstrap fallback; weak/empty/short secret → `WeakJWTSecretError` (never a public default). No plaintext secret in the schema. `create_access_token`/`get_current_user` signatures untouched in this story (consumed in SEC-ROT-2). IDS: REUSED `config.WEAK_JWT_SECRETS`/`MIN_JWT_SECRET_LENGTH` and the `system_settings` singleton pattern; CREATED the provider module (story-mandated).

**Test results:** `pytest tests/` → **178 passed, 0 failed** (ephemeral venv, Python 3.14.3). The 8 SEC-ROT-1 provider tests pass; full pre-existing suite green (no regression).

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-04 (adversarial security review)

Cluster: **jwt-rotation** (SEC-ROT-1 — DB-backed secret provider).

`jwt_secret_provider.py` reviewed: DB (`system_settings.jwt_secret`) is the durable source of truth; seed-on-NULL persists from the strong bootstrap and stamps `jwt_secret_rotated_at`; thread-safe TTL cache (30s) avoids per-request queries. Fail-closed verified: DB error → strong-bootstrap fallback (not cached); weak/empty/`change-me-in-production`/<32-char → `WeakJWTSecretError`, never a public default; a DB value that is somehow weak also raises. Seed is idempotent (only on NULL) so concurrent first-boots don't clobber. No plaintext secret in the migration. Reuses `config.WEAK_JWT_SECRETS`/`MIN_JWT_SECRET_LENGTH` (single source of truth).

Tests: `test_jwt_rotation.py` SEC-ROT-1 section green; full suite **257 passed, 0 failed**.
