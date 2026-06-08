---
id: SEC-ATO-1
epic: EPIC-SEC
phase: 1
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: low
depends_on: []
bug_refs: [3]
---
# SEC-ATO-1: Reconciliar nomes de variáveis nos dois `.env.example`

## Story
Como operador de deploy (DevOps/infra), quero que os dois `.env.example` documentem exatamente os nomes de variáveis que o backend realmente lê, para que seguir o template verbatim configure um boot seguro em vez de deixar segredos críticos no default fail-open.

## Contexto (do bug sweep)
O backend lê `SUPABASE_KEY` e `JWT_SECRET_KEY` (`backend/config.py:12` e `backend/config.py:15`; `backend/database.py:6` lê `SUPABASE_KEY` via `os.getenv`), mas os templates documentam nomes ERRADOS:

- `.env.example:11-12` (raiz) → `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY` (nenhum dos dois é lido pelo código).
- `.env.example:15` (raiz) → `JWT_SECRET` (o código lê `JWT_SECRET_KEY`).
- `backend/.env.example:1` → `DATABASE_URL` (variável-fantasma, nunca lida), e o arquivo NÃO documenta `SUPABASE_URL`/`SUPABASE_KEY`.

Como apontado no bug sweep (BUG-SWEEP-2026-06-03.md:50-58), seguir o `.env.example` verbatim deixa `JWT_SECRET_KEY` ausente → todos os tokens são assinados com o default literal público `"change-me-in-production"` (`config.py:15`), que é fail-open por design. Esta é a raiz documental que habilita o cluster crítico de segredos (SEC-ATO-2 depende desta story). Escopo desta story: **docs-only** — apenas os dois `.env.example`. O boot-guard fail-closed e a remediação de `force_logout` (#22) são tratados em SEC-ATO-2; aqui apenas documentamos a expectativa em comentário.

## Acceptance Criteria
- [x] `.env.example` (raiz) usa `SUPABASE_KEY` (não `SUPABASE_ANON_KEY` nem `SUPABASE_SERVICE_ROLE_KEY`).
- [x] `.env.example` (raiz) usa `JWT_SECRET_KEY` (não `JWT_SECRET`).
- [x] `backend/.env.example` documenta `SUPABASE_URL` e `SUPABASE_KEY`, e remove `DATABASE_URL` (nome-fantasma que o código não lê).
- [x] Ambos os arquivos usam os nomes exatamente como em `config.py:11/12/15` e `database.py:5/6`: `SUPABASE_URL`, `SUPABASE_KEY`, `JWT_SECRET_KEY`.
- [x] Zero ocorrência de `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `JWT_SECRET` (sem sufixo `_KEY`) ou `DATABASE_URL` em qualquer um dos dois `.env.example` (verificável por grep).
- [x] Comentário ao lado de `JWT_SECRET_KEY` documenta o requisito de ≥32 caracteres e a existência do boot-guard fail-closed em produção (entregue por SEC-ATO-2).
- [x] Nenhum arquivo de código (`config.py`, `database.py`, etc.) é alterado — mudança restrita aos dois templates.

## Tasks / Subtasks
- [x] Editar `/Users/hugocapitelli/Dev/eximia/harven-ai-v2/.env.example`: renomear `SUPABASE_ANON_KEY` (linha 11) e remover/colapsar `SUPABASE_SERVICE_ROLE_KEY` (linha 12) para uma única `SUPABASE_KEY`, alinhada a `config.py:12`.
- [x] Editar a mesma raiz: renomear `JWT_SECRET` (linha 15) → `JWT_SECRET_KEY`, alinhada a `config.py:15`.
- [x] Editar `/Users/hugocapitelli/Dev/eximia/harven-ai-v2/backend/.env.example`: remover `DATABASE_URL` (linha 1, fantasma) e adicionar `SUPABASE_URL` + `SUPABASE_KEY` (lidos em `database.py:5-6`).
- [x] Adicionar comentário acima de `JWT_SECRET_KEY` em ambos os arquivos: requisito ≥32 chars + nota de que produção falha o boot com default/segredo fraco (boot-guard — SEC-ATO-2).
- [x] Verificar consistência: confirmar que todo nome nos `.env.example` corresponde a um campo de `Settings` em `backend/config.py` ou a um `os.getenv` real (ex.: `database.py`).

## Dev Notes
- **Arquivos:** `/Users/hugocapitelli/Dev/eximia/harven-ai-v2/.env.example` (raiz, linhas 9-15), `/Users/hugocapitelli/Dev/eximia/harven-ai-v2/backend/.env.example` (linhas 1-2). Referência de verdade: `backend/config.py:11-15` (`SUPABASE_URL`, `SUPABASE_KEY`, `JWT_SECRET_KEY`) e `backend/database.py:5-6` (`os.getenv("SUPABASE_URL")`, `os.getenv("SUPABASE_KEY")`).
- **Abordagem:** Substituição textual nos dois templates para casar 1:1 com os nomes que pydantic-settings (`config.py`) e `os.getenv` (`database.py`) leem. `pydantic-settings` faz match por nome de campo case-insensitive — portanto nomes errados resultam em string vazia/default silencioso, não em erro. Por isso a correção é documental mas crítica: ela é a precondição para o boot-guard de SEC-ATO-2 ter um template coerente para o operador seguir.
- **Riscos de regressão:** Blast radius praticamente nulo em runtime — `.env.example` não é carregado por nenhum processo (apenas `.env` real é lido via `env_file=".env"` em `config.py:8` e `load_dotenv()` no boot). Risco real é humano: um operador que tinha um `.env` derivado do template antigo (com `SUPABASE_ANON_KEY`/`JWT_SECRET`) continuará quebrado até renomear o `.env` real — documentar isso no comentário/PR. Consumidor downstream: SEC-ATO-2 (boot-guard) assume os nomes reconciliados aqui.

## Definition of Done
- [x] Teste de regressão (falha-antes / passa-depois) verde: asserção/grep automatizado que falha se qualquer `.env.example` contiver `SUPABASE_ANON_KEY|SUPABASE_SERVICE_ROLE_KEY|JWT_SECRET(?!_KEY)|DATABASE_URL`, e que confirma presença de `SUPABASE_KEY` e `JWT_SECRET_KEY` em ambos.
- [x] Sem regressão na suíte de segurança (`backend/tests/test_security_hotfix.py`).
- [x] QA Gate: PASS. _(verificado por @qa — 2026-06-04)_
- [x] Todo nome de variável nos dois `.env.example` mapeia para um campo de `Settings` (`config.py`) ou um `os.getenv` real; comentário de ≥32 chars + boot-guard presente ao lado de `JWT_SECRET_KEY`; nenhum arquivo de código alterado.

## Dev Agent Record

**Agente:** @dev (Dex) · **Data:** 2026-06-04

**Arquivos modificados:**
- `.env.example` (raiz) — `SUPABASE_ANON_KEY`+`SUPABASE_SERVICE_ROLE_KEY` colapsados em `SUPABASE_KEY`; `JWT_SECRET` → `JWT_SECRET_KEY`; comentário ≥32 chars + boot-guard.
- `backend/.env.example` — `DATABASE_URL` (fantasma) removido; `SUPABASE_URL` + `SUPABASE_KEY` adicionados; comentário ≥32 chars + boot-guard.

**Resumo da implementação:** Edits docs-only nos dois templates para casar 1:1 com os nomes lidos por `config.py` (`SUPABASE_URL`/`SUPABASE_KEY`/`JWT_SECRET_KEY`) e `database.py` (`os.getenv("SUPABASE_URL"/"SUPABASE_KEY")`). Nenhum arquivo de código alterado nesta story. IDS: REUSE dos comentários canônicos de JWT em ambos os arquivos.

**Testes:** `backend/tests/test_security_hotfix.py::test_env_example_*` (4 casos parametrizados: zero nomes proibidos + presença dos 3 nomes reais nos dois arquivos). Resultado: **21 passed** na suíte completa (`python -m pytest tests/ -v`). Verificação por grep confirmada: 0 ocorrências de `SUPABASE_ANON_KEY|SUPABASE_SERVICE_ROLE_KEY|JWT_SECRET(?!_KEY)|DATABASE_URL`.

## QA Results

**Revisor:** @qa (Quinn) · **Data:** 2026-06-04 · **Veredito: PASS**

### Verificação de AC (cada um provado pelo código/grep)
- **AC1/AC2/AC4 (raiz):** `.env.example:10` → `SUPABASE_KEY=your-supabase-key`; `:16` → `JWT_SECRET_KEY=...`. Os dois antigos (`SUPABASE_ANON_KEY`+`SUPABASE_SERVICE_ROLE_KEY`) colapsados em um único `SUPABASE_KEY`. ✅
- **AC3 (backend):** `backend/.env.example` agora documenta `SUPABASE_URL` + `SUPABASE_KEY` e o fantasma `DATABASE_URL` foi removido. ✅
- **AC4 (nomes batem com o código):** Confirmado contra `config.py:20-21` (`SUPABASE_URL`/`SUPABASE_KEY`), `config.py:24` (`JWT_SECRET_KEY`) e `database.py:5-6` (`os.getenv("SUPABASE_URL")`/`os.getenv("SUPABASE_KEY")`). 1:1. ✅
- **AC5 (zero ocorrência proibida):** `grep -rnE "SUPABASE_ANON_KEY|SUPABASE_SERVICE_ROLE_KEY|DATABASE_URL|JWT_SECRET([^_]|$)"` nos dois arquivos → **exit 1 (zero matches)**. `grep -cE "^SUPABASE_URL=|^SUPABASE_KEY=|^JWT_SECRET_KEY="` → **3/3 em cada arquivo**. ✅
- **AC6 (comentário ≥32 chars + boot-guard):** Presente acima de `JWT_SECRET_KEY` em ambos os arquivos. ✅
- **AC7 (nenhum código alterado):** Diff confina-se aos dois `.env.example`. ✅

### Testes
4 testes parametrizados (`test_env_example_has_no_forbidden_names` × 2, `test_env_example_has_required_names` × 2) — executados em venv QA isolado. Cobrem ausência de nomes proibidos (incl. detecção de `JWT_SECRET` sem `_KEY` por parsing de chave, não substring) e presença dos 3 nomes reais. Sem falso-verde detectado.

### Regressão
Blast radius runtime nulo — `.env.example` não é lido por nenhum processo (`config.py` lê `.env` real). Risco residual é humano (operador com `.env` derivado do template antigo), já documentado nos Dev Notes. Sem efeito colateral.

### Observação (não-bloqueante)
Discrepância de rastreabilidade: `bug_refs: [22]` no frontmatter, mas a implementação real desta story endereça a raiz documental do cluster de secrets (#3). #22 (precedência de env var no `force_logout`) **não** é corrigido aqui nem em nenhuma das 3 stories — corretamente, pois está fora de escopo (deferido). Recomendo ajustar o `bug_refs` para `[3]` numa próxima limpeza. Não impacta a correção de segurança.
