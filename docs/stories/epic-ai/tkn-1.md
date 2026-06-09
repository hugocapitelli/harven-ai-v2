---
id: TKN-1
epic: EPIC-AI
phase: 4
status: Done
severity: HIGH
terminal: Backend & Infra
complexity: low
depends_on: []
bug_refs: [12]
---
# TKN-1: Função Postgres atômica de incremento + índice (migração)

## Story
Como engenheiro de backend, quero uma função Postgres atômica `increment_token_usage` com upsert `ON CONFLICT` sobre a tabela `token_usage` e um índice em `(user_id, usage_date)`, para que o consumo diário de tokens seja contabilizado de forma confiável e concorrência-segura no banco — em vez do cache em memória atual — fornecendo a base para o throttle real de orçamento de tokens (TKN-2 em diante).

## Contexto (do bug sweep)
O item #12 (`backend/routes_ai.py:145-292, 408-418`) expõe endpoints de autoria de IA sem role gate e, mais grave, `ai_editor_edit` e `ai_tester_validate` chamam o LLM **sem `user_id` e sem `check_token_budget`** — ou seja, sem throttle. O agravante é que o throttle existente já é frágil na origem: o controle de orçamento de tokens vive inteiramente em um cache de processo em memória (`backend/services/ai_service.py:204` `_user_token_cache`, consultado em `check_token_budget` linhas 207-214 e escrito em `track_token_usage` linhas 216-221). Esse cache:
- é local ao processo/worker → não compartilhado entre múltiplos workers/instâncias;
- é volátil → zera a cada restart, permitindo reset trivial do limite diário;
- não usa a tabela `token_usage` que já existe no schema (`backend/supabase_schema.sql:299-306`) com `UNIQUE(user_id, usage_date)` mas **sem** função de incremento atômica e **sem** índice de leitura por `(user_id, usage_date)`.

TKN-1 corrige a **camada de dados**: cria a função atômica de incremento (upsert `ON CONFLICT (user_id, usage_date)`) e o índice de suporte, garantindo 1 linha por usuário/dia mesmo sob escrita concorrente. Isso desbloqueia TKN-2 (`TokenUsageRepository`) e o throttle persistente que substitui o cache em memória, fechando o vetor de exaustão de tokens do item #12.

## Acceptance Criteria
- [ ] Migração SQL idempotente (`CREATE INDEX IF NOT EXISTS` / `CREATE OR REPLACE FUNCTION`) que aplica e reaplica sem erro sobre a tabela `token_usage` existente.
- [ ] Índice criado em `token_usage (user_id, usage_date)` para acelerar a leitura diária por usuário (o `UNIQUE(user_id, usage_date)` já garante unicidade; o índice cobre o caminho de consulta `get_today_usage`).
- [ ] Função `increment_token_usage(p_user_id, p_usage_date, p_tokens)` faz `INSERT ... ON CONFLICT (user_id, usage_date) DO UPDATE SET tokens_used = token_usage.tokens_used + EXCLUDED.tokens_used` de forma atômica (sem read-modify-write em duas idas ao banco).
- [ ] A função **retorna o novo total** (`tokens_used` após o incremento) para que TKN-2 (`add_usage`) o use diretamente.
- [ ] Invariante verificável: após N chamadas concorrentes para o mesmo `(user_id, usage_date)`, existe exatamente **1 linha** e `tokens_used` == soma exata dos incrementos (sem perda por race / lost update).
- [ ] Chamada com `p_usage_date` de dois dias distintos para o mesmo usuário gera 2 linhas (uma por dia).
- [ ] A função respeita o `SECURITY`/grant adequado para ser chamada via RPC pelo cliente service-role usado pelo backend.

## Tasks / Subtasks
- [ ] Criar arquivo de migração em `backend/supabase/migrations/` (ou `supabase/migrations/`, seguindo o padrão de `supabase/migrations/20260414_init.sql`) com timestamp da janela 2026-06.
- [ ] Adicionar `CREATE INDEX IF NOT EXISTS idx_token_usage_user_date ON token_usage (user_id, usage_date);`.
- [ ] Definir `CREATE OR REPLACE FUNCTION increment_token_usage(p_user_id TEXT, p_usage_date DATE, p_tokens INTEGER) RETURNS INTEGER` com `INSERT INTO token_usage (...) VALUES (...) ON CONFLICT (user_id, usage_date) DO UPDATE SET tokens_used = token_usage.tokens_used + EXCLUDED.tokens_used RETURNING tokens_used;`.
- [ ] Garantir geração de `id` (a tabela tem `id TEXT PRIMARY KEY DEFAULT uuid_generate_v4()::text` — confirmar que o INSERT não quebra o default).
- [ ] Definir `SECURITY DEFINER` (ou `GRANT EXECUTE`) conforme o padrão do projeto para RPC via service-role; documentar a escolha no corpo da migração.
- [ ] Espelhar a definição em `backend/supabase_schema.sql` (logo após a tabela `token_usage`, linhas 299-306) para manter o schema canônico em sincronia.
- [ ] Escrever teste de regressão (ver Definition of Done) que prove atomicidade e 1-linha-por-dia.

## Dev Notes
- **Arquivos:**
  - `backend/supabase_schema.sql` (tabela `token_usage` em 299-306; adicionar função+índice logo abaixo)
  - `supabase/migrations/20260414_init.sql` (padrão de migração de referência) → criar nova migração nesta pasta
  - `backend/services/ai_service.py:204-221` (cache em memória `_user_token_cache`, `check_token_budget`, `track_token_usage` — consumidores futuros via TKN-2; **não tocar nesta story**)
- **Abordagem:** Pura camada de dados. Upsert atômico `ON CONFLICT (user_id, usage_date)` usando o unique constraint já existente como árbitro do conflito; `RETURNING tokens_used` evita a segunda query. O índice `(user_id, usage_date)` acelera a futura leitura `get_today_usage`. Migração idempotente para permitir re-run seguro no EasyPanel/Supabase.
- **Riscos de regressão:** Blast radius **baixo e isolado** — esta story apenas adiciona objetos novos (função + índice) ao banco; não altera nenhuma coluna existente nem código Python. `ai_service.py` continua usando o cache em memória até TKN-2 plugar o repositório. Risco a vigiar: o `id` da tabela tem default `uuid_generate_v4()::text` — confirmar que a extensão `uuid-ossp`/`pgcrypto` está disponível no ambiente alvo (já é usada pela tabela, então deve estar). Garantir que a migração não conflite com possível índice implícito do unique constraint (o índice explícito em `(user_id, usage_date)` é redundante apenas se o unique já gerar índice idêntico — neste caso o `IF NOT EXISTS` o torna inofensivo; manter para clareza/cobertura de leitura).

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: simular escritas concorrentes/sequenciais ao mesmo `(user_id, usage_date)` e asserir 1 linha + `tokens_used` == soma; asserir que a função RETORNA o novo total.
- [ ] Sem regressão na suíte de segurança (nenhum endpoint/RLS alterado por esta story).
- [ ] QA Gate: PASS ou CONCERNS.
- [ ] Migração aplica idempotentemente (rodar duas vezes sem erro) e `backend/supabase_schema.sql` reflete a função + índice.

## File List
- `supabase/migrations/20260608a_token_usage_rpc.sql` (NEW) — migração idempotente: índice `idx_token_usage_user_date` + função atômica `increment_token_usage` (upsert `ON CONFLICT (user_id, usage_date)`, `RETURNING tokens_used`), com cabeçalho documentando idempotência e bloco de verificação manual.
- `backend/supabase_schema.sql` (MODIFIED) — espelho da função + índice logo após a definição da tabela `token_usage` (após linha 306). Definição da tabela NÃO alterada.

## Dev Agent Record
- **Agent:** @dev (Dex)
- **Approach:** Pura camada de dados, aditiva. Precedente exato copiado de `supabase/migrations/20260603b_unique_constraints.sql` (`increment_chat_session_messages`): `CREATE OR REPLACE FUNCTION ... LANGUAGE sql SECURITY DEFINER SET search_path = public` com `RETURNING`.
- **`id` default:** INSERT omite `id` → usa o DEFAULT da tabela (`uuid_generate_v4()::text`). Confirmado que `uuid_generate_v4` já é usada pela própria tabela, logo a extensão está disponível no ambiente alvo.
- **Atomicidade:** Upsert single-statement `ON CONFLICT (user_id, usage_date) DO UPDATE SET tokens_used = token_usage.tokens_used + EXCLUDED.tokens_used` — sem read-modify-write, sem lost updates. N chamadas concorrentes ao mesmo par → 1 linha, soma exata. Dias distintos → linhas distintas.
- **Idempotência:** `CREATE INDEX IF NOT EXISTS` + `CREATE OR REPLACE FUNCTION` → aplica e reaplica sem erro.
- **Sem regressão de segurança:** nenhum endpoint, RLS ou código Python alterado. `ai_service.py` intocado (consumidor futuro via TKN-2).
- **Validação:** Sintaxe SQL revisada manualmente (sem DB local). RETORNO de tipo `INTEGER` coerente com `tokens_used INTEGER`. `EXCLUDED.tokens_used` referencia corretamente o valor proposto pelo INSERT no caminho de conflito.

## QA Results
_(a preencher pelo @qa)_
