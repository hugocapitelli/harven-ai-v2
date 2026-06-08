---
id: SEC-ATO-2
epic: EPIC-SEC
phase: 1
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: low
depends_on: [SEC-ATO-1]
bug_refs: [3]
---
# SEC-ATO-2: Guard fail-closed para JWT_SECRET_KEY

## Story
Como operador de infraestrutura da Harven.AI, quero que o backend recuse o boot em produção quando `JWT_SECRET_KEY` for um default público, vazio ou fraco, para que tokens de autenticação nunca sejam assinados com um segredo conhecido e o ambiente falhe de forma segura (fail-closed) em vez de subir vulnerável.

## Contexto (do bug sweep)
Item de bug #3 (CRITICAL) do BUG-SWEEP-2026-06-03.md:

- `backend/config.py:15` define `JWT_SECRET_KEY: str = "change-me-in-production"` — um default literal, sem nenhum guarda de startup.
- `backend/auth.py:30` usa esse segredo em `jwt.encode(...)` e `backend/auth.py:40` em `jwt.decode(...)`. Logo, se a env var estiver ausente, **todos os tokens são assinados e validados com um secret público conhecido**.
- A ausência da env é **provável**: o `.env.example` (raiz e `backend/.env.example`) documenta nomes ERRADOS (`SUPABASE_ANON_KEY` / `JWT_SECRET`) em vez dos lidos pelo código (`SUPABASE_KEY` / `JWT_SECRET_KEY`), aumentando a chance de o operador nunca definir a var correta.
- **Impacto:** account takeover trivial — qualquer atacante que conheça o default forja tokens válidos para qualquer usuário/admin. Junto do item #4 (token de reset no corpo), é a falha de takeover mais imediata do sistema.

**Direção de correção (roadmap, linha 59):** Em `ENVIRONMENT==production`, blacklist `{'', 'change-me-in-production', 'your-secret-key-here'}` ou segredo com `<32` chars → `RuntimeError` no boot; segredo forte → boot normal; token forjado com default → 401; non-prod loga WARNING; aceita qualquer segredo forte (não quebra `force_logout`).

## Acceptance Criteria
- [x] Em `ENVIRONMENT=production`, se `JWT_SECRET_KEY` estiver na blacklist `{'', 'change-me-in-production', 'your-secret-key-here'}` → o boot levanta `RuntimeError` (fail-closed), aplicação não sobe.
- [x] Em `ENVIRONMENT=production`, se `len(JWT_SECRET_KEY) < 32` → o boot levanta `RuntimeError` (fail-closed).
- [x] Em `ENVIRONMENT=production`, com `JWT_SECRET_KEY` forte (não-blacklist e `>= 32` chars) → boot normal, sem exceção.
- [x] Um token forjado/assinado com o default `"change-me-in-production"` é rejeitado com **401** (não há produção rodando com esse secret, pois o boot teria falhado).
- [x] Em ambiente não-produção (`ENVIRONMENT != production`), secret fraco/default → apenas registra **WARNING** no log; boot prossegue normalmente (não quebra DX local).
- [x] A validação aceita **qualquer** segredo forte arbitrário — não restringe formato além de blacklist + tamanho mínimo — garantindo que o `force_logout` (item #4 / SEC-ATO-1), que rotaciona o secret para um valor forte novo, continue passando no guard.
- [x] A reconciliação dos nomes em `.env.example` (raiz e `backend/`) usa os nomes reais lidos pelo código: `SUPABASE_KEY`, `JWT_SECRET_KEY`.

## Tasks / Subtasks
- [x] Em `backend/config.py`, adicionar validação fail-closed do `JWT_SECRET_KEY` em função do `ENVIRONMENT`:
  - [x] Definir constante de blacklist `WEAK_JWT_SECRETS = {"", "change-me-in-production", "your-secret-key-here"}`.
  - [x] Implementar a checagem via `pydantic.model_validator(mode="after")` na classe `Settings` (linha 7) ou em uma função `_validate_jwt_secret(settings)` chamada por `get_settings()` (linha 32). Em prod: `raise RuntimeError(...)` se secret na blacklist ou `len < 32`. Em não-prod: `logging.warning(...)`.
  - [x] Mensagem de erro acionável (orienta a definir `JWT_SECRET_KEY` com `>=32` chars, ex.: via `openssl rand -hex 32`).
- [x] Garantir que `get_settings()` (com `@lru_cache`, linha 31-33) dispare a validação no primeiro acesso — o `settings = get_settings()` em `backend/main.py:294` (antes do `app = FastAPI(...)`, linha 298) força o guard no boot. Confirmar que isso roda no caminho de inicialização do lifespan (`main.py:286-294`).
- [x] Reconciliar nomes em `/Users/hugocapitelli/Dev/eximia/harven-ai-v2/.env.example` (raiz) e `/Users/hugocapitelli/Dev/eximia/harven-ai-v2/backend/.env.example` para `SUPABASE_KEY` e `JWT_SECRET_KEY`, removendo duplicatas/legados (`SUPABASE_ANON_KEY`, `JWT_SECRET`). _(entregue em SEC-ATO-1)_
- [x] Escrever teste de regressão (pytest) cobrindo: prod+blacklist → `RuntimeError`; prod+`<32` → `RuntimeError`; prod+secret forte → sem exceção; non-prod+fraco → WARNING + sem exceção; token forjado com default → 401 (via `auth.py` decode).

## Dev Notes
- **Arquivos:**
  - `/Users/hugocapitelli/Dev/eximia/harven-ai-v2/backend/config.py` (Settings linha 7; `JWT_SECRET_KEY` linha 15; `ENVIRONMENT` linha 25; `get_settings()` linha 31-33)
  - `/Users/hugocapitelli/Dev/eximia/harven-ai-v2/backend/auth.py` (`jwt.encode` linha 30; `jwt.decode` linha 40)
  - `/Users/hugocapitelli/Dev/eximia/harven-ai-v2/backend/main.py` (`load_dotenv()` linha 10; lifespan linha 286-287; `settings = get_settings()` linha 294)
  - `/Users/hugocapitelli/Dev/eximia/harven-ai-v2/backend/.env.example` e `/Users/hugocapitelli/Dev/eximia/harven-ai-v2/.env.example`
- **Abordagem:** Validação centralizada em `config.Settings` via `model_validator(mode="after")` (pydantic v2 — projeto usa `pydantic_settings`). O guard lê `ENVIRONMENT`: em prod aplica blacklist + `len < 32` e `raise RuntimeError`; fora de prod apenas `logging.warning`. Não introduzir nova lógica em `auth.py` — o 401 para token forjado é consequência natural de prod nunca rodar com o default (boot teria falhado). Aceitar qualquer segredo forte preserva compatibilidade com SEC-ATO-1/`force_logout`, que troca o secret em runtime.
- **Riscos de regressão:**
  - `get_settings()` é chamado em `auth.py` (assinatura/verificação de TODOS os tokens), `main.py:294` (boot) e `routes_admin.py` (`force_logout` reescreve `JWT_SECRET_KEY=` em `routes_admin.py:633`). Blast radius = caminho de autenticação inteiro + boot.
  - Cuidado com `@lru_cache` em `get_settings()`: a validação ocorre na primeira instanciação; SEC-ATO-1 já lida com `cache_clear()` na rotação. Garantir que após `cache_clear()` o novo secret forte ainda passe no guard (não falhar pós-rotação).
  - **Depende de SEC-ATO-1** (precedência de env var no `force_logout`) — o guard não deve invalidar a correção da rotação de secret feita lá.
  - Não acionar o guard em testes/dev locais que rodem com secret fraco (CI deve setar `ENVIRONMENT` explicitamente).

## Definition of Done
- [x] Teste de regressão (falha-antes / passa-depois) verde
- [x] Sem regressão na suíte de segurança
- [x] QA Gate: PASS _(verificado por @qa — 2026-06-04)_
- [x] Boot em produção comprovadamente fail-closed (RuntimeError) para os 4 casos de secret inválido (vazio, `change-me-in-production`, `your-secret-key-here`, `<32` chars) e boot normal com secret forte, sem quebrar `force_logout` (SEC-ATO-1); `.env.example` raiz e `backend/` reconciliados para `SUPABASE_KEY`/`JWT_SECRET_KEY`.

## Dev Agent Record

**Agente:** @dev (Dex) · **Data:** 2026-06-04

**Arquivos modificados:**
- `backend/config.py` — adicionado `import logging`, `from pydantic import model_validator`, constantes `WEAK_JWT_SECRETS` + `MIN_JWT_SECRET_LENGTH`, e o validador `Settings._validate_jwt_secret` (`@model_validator(mode="after")`). (Também adicionado o campo `RESET_TOKEN_DEBUG` para SEC-ATO-3.)
- `.env.example` / `backend/.env.example` — reconciliação dos nomes (entregue em SEC-ATO-1).

**Resumo da implementação:** Guard centralizado em `config.Settings` via pydantic v2 `model_validator(mode="after")`. Lê o `ENVIRONMENT` da própria instância: em produção, secret na blacklist OU `< 32` chars → `RuntimeError` com mensagem acionável (`openssl rand -hex 32`); fora de produção → `logging.warning` e boot prossegue. O guard dispara no boot via `settings = get_settings()` em `main.py:294` (module-load, antes do `app = FastAPI(...)`). `auth.py` intocado — o 401 para token forjado é consequência natural (prod nunca roda com o default). Compatível com `force_logout` (`routes_admin.py:623`), que rotaciona para `secrets.token_urlsafe(48)` (~64 chars, fora da blacklist) + `cache_clear()` → o validador re-roda e aprova o novo secret forte. IDS: ADAPT de `config.Settings` (extensão, sem novo arquivo).

**Testes:** `test_validator_accepts_strong_secret_in_production`, `test_validator_rejects_weak_secret_in_production` (4 casos: vazio/2 defaults/`short`), `test_validator_rejects_31_char_secret_in_production`, `test_validator_accepts_exactly_32_chars_in_production`, `test_validator_only_warns_outside_production`, `test_boot_fail_closed_in_production_with_weak_secret`, `test_boot_succeeds_in_production_with_strong_secret`, `test_forged_token_with_default_is_rejected_under_strong_secret`. Resultado: **21 passed** (`python -m pytest tests/ -v`).

## QA Results

**Revisor:** @qa (Quinn) · **Data:** 2026-06-04 · **Veredito: PASS**

### Verificação de AC + tentativas de furar a correção
- **AC1/AC2 (fail-closed em prod):** `config.py:42-65` — `@model_validator(mode="after")` levanta `RuntimeError` quando `ENVIRONMENT==production` e secret na blacklist OU `len < 32`. Confirmado por `test_validator_rejects_weak_secret_in_production` (4 casos: vazio/2 defaults/`short`) + `test_validator_rejects_31_char_secret_in_production`. ✅
- **AC3 (boot normal com secret forte):** `test_validator_accepts_strong_secret_in_production` + `test_boot_succeeds_in_production_with_strong_secret`. ✅
- **AC4 (token forjado com default → 401):** `test_forged_token_with_default_is_rejected_under_strong_secret` prova `jwt.decode(forged, STRONG_SECRET)` → `JWTError`; `auth.py:44-45` converte `JWTError` em HTTP 401. A garantia depende do boot-guard (prod nunca roda com o default), o que é verdade. ✅
- **AC5 (non-prod só WARNING):** `test_validator_only_warns_outside_production` (4 casos) — boot prossegue, `logging.warning` emitido. ✅
- **AC6 (aceita qualquer secret forte → não quebra `force_logout`):** `config.py:54` valida apenas blacklist + tamanho, sem restrição de formato. **Verifiquei adversarialmente:** `Settings(JWT_SECRET_KEY=secrets.token_urlsafe(48), ENVIRONMENT="production")` (64 chars) → **aceito**. A rotação do `force_logout` (`routes_admin.py:623`) sobrevive ao guard. ✅
- **AC7 (`.env.example` reconciliado):** entregue/verificado em SEC-ATO-1. ✅

### Probes adversariais próprias (além dos testes do dev)
1. **Boot real fail-closed:** `settings = get_settings()` em `main.py:294` roda em module-load, **antes** de `app = FastAPI(...)` (`:298`). Importar `main` em prod com default → `RuntimeError`, uvicorn não sobe. Confirmado.
2. **Boundary 31 vs 32:** 31 chars rejeitado, exatamente 32 aceito — fronteira correta (`len(secret) < MIN_JWT_SECRET_LENGTH`, `MIN=32`). ✅
3. **`force_logout` pós-rotação:** secret rotacionado de 64 chars passa o validador re-rodado após `cache_clear()`. ✅

### Regressão
- Default de `JWT_SECRET_KEY` em `config.py:24` permanece `"change-me-in-production"` — **intencional e seguro**: em prod o guard intercepta; em dev vira WARNING (preserva DX). Login normal, `auth.py` e a suíte completa (21/21) passam.
- `force_logout` (#22) **não regride** — o guard é compatível com a rotação. Importante: este story **não** corrige o root cause de #22 (precedência env var > arquivo `.env`), e corretamente não o reivindica — está deferido. O escopo "não quebrar force_logout" foi cumprido.

### Qualidade dos testes
Cobertura sólida dos caminhos críticos, incl. boundary 31/32 e o caso boot real (não só o validador isolado). Sem falso-verde: os testes de rejeição usam `pytest.raises(RuntimeError)`, falhariam se o guard fosse removido. Nenhum gap material.

### Re-verificação Fase 2 (2026-06-04) — @qa (Quinn)
O boot guard desta story **continua intacto** após o trabalho de rotação JWT (SEC-ROT-1/2/3). Confirmado: `config.py` validator não foi tocado; `test_boot_fail_closed_in_production_with_weak_secret` e `test_boot_succeeds_in_production_with_strong_secret` permanecem verdes na suíte completa (**257 passed**). A migração de sign/verify para o provider DB (SEC-ROT-2) preserva o comportamento fail-closed: secret fraco → boot abortado em prod; rotação via `force_logout` gera secret forte que passa o guard. Nenhuma regressão. **PASS mantido.**
