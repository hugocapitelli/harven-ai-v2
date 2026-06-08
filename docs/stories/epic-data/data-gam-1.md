---
id: DATA-GAM-1
epic: EPIC-DATA
phase: 4
status: Draft
severity: HIGH
terminal: Backend & Infra
complexity: low
depends_on: []
bug_refs: [15]
---
# DATA-GAM-1: Migração + schema/ORM — coluna achievement_key + índice único por user

## Story
Como engenheiro de plataforma, quero adicionar uma coluna `achievement_key` à tabela `user_achievements` (com backfill a partir do `id` atual) e criar um índice parcial UNIQUE por `(user_id, achievement_key)`, mantendo `id` como PK surrogate UUID, para que o unlock de achievement deixe de colidir na primary key e cada usuário possa desbloquear o mesmo achievement de catálogo de forma independente e idempotente.

## Contexto (do bug sweep)
Item #15 (`backend/routes_admin.py:1140-1176`, schema em `backend/supabase_schema.sql:236`) — **Achievement unlock colide na primary key**.

`unlock_achievement` insere a row usando `id=achievement_id` (o id do catálogo) junto com `user_id`. Porém `user_achievements.id` é a PRIMARY KEY (`supabase_schema.sql:236`). O dedup atual é por-usuário (`.eq('user_id').eq('id')`), então para um segundo usuário (que não possui essa row) o fluxo prossegue e tenta inserir `id=achievement_id` novamente → violação de unicidade da PK → HTTP 500.

**Impacto:** Apenas o primeiro usuário consegue desbloquear um dado achievement; todos os demais crasham com 500. Na prática, os achievements são globais de uso único, quebrando completamente a gamificação para a base de alunos.

Esta story (DATA-GAM-1) corrige a **camada de dados** — cria a coluna de referência de catálogo separada (`achievement_key`) e o índice de unicidade correto `(user_id, achievement_key)`, libertando `id` para ser um UUID surrogate. A correção do **repositório/serviço** (gerar UUID fresco, dedup por `achievement_key`, idempotência no insert) é tratada na DATA-GAM-2, que depende desta.

## Acceptance Criteria
- [ ] Existe a migration `20260603d_achievements_key.sql` adicionando a coluna `achievement_key TEXT` à tabela `user_achievements`.
- [ ] Backfill: para todas as rows existentes, `achievement_key` é populado com o valor atual de `id` (`UPDATE ... SET achievement_key = id WHERE achievement_key IS NULL`), preservando os desbloqueios já registrados.
- [ ] `achievement_key` torna-se `NOT NULL` após o backfill (ou via default + constraint validada), garantindo que toda row futura tenha a referência de catálogo.
- [ ] Criado índice parcial `UNIQUE (user_id, achievement_key)` (ex.: `CREATE UNIQUE INDEX IF NOT EXISTS uq_user_achievements_user_key ON user_achievements (user_id, achievement_key) WHERE achievement_key IS NOT NULL`), garantindo dedup por usuário+catálogo e suportando ON CONFLICT.
- [ ] `id` permanece a PRIMARY KEY surrogate do tipo UUID — nenhuma alteração na PK; a unicidade de catálogo deixa de depender do `id`.
- [ ] **Pré-check de duplicatas antes de criar o índice:** a migration detecta pares `(user_id, achievement_key)` duplicados pré-existentes (query de verificação) e ou (a) falha com mensagem clara se houver, ou (b) deduplica de forma determinística (mantém a row mais antiga por `created_at`/`id`) antes de criar o UNIQUE — comportamento documentado na própria migration.
- [ ] **Idempotência:** rodar a migration duas vezes seguidas não causa erro — uso de `IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS` / `CREATE UNIQUE INDEX IF NOT EXISTS` e backfill guardado por `WHERE achievement_key IS NULL`.
- [ ] O schema canônico (`backend/supabase_schema.sql`) e o modelo ORM correspondente refletem a nova coluna e o índice, de modo que um deploy limpo (banco do zero) produza a mesma estrutura da migration incremental.

## Tasks / Subtasks
- [ ] Criar `backend/migrations/20260603d_achievements_key.sql` (ou diretório de migrations equivalente do projeto) com, em ordem: pré-check de duplicatas → `ALTER TABLE user_achievements ADD COLUMN IF NOT EXISTS achievement_key TEXT` → backfill `UPDATE user_achievements SET achievement_key = id WHERE achievement_key IS NULL` → `SET NOT NULL`/constraint → `CREATE UNIQUE INDEX IF NOT EXISTS uq_user_achievements_user_key ON user_achievements (user_id, achievement_key) WHERE achievement_key IS NOT NULL`.
- [ ] Implementar o pré-check de duplicatas na migration: `SELECT user_id, achievement_key, count(*) FROM user_achievements GROUP BY 1,2 HAVING count(*) > 1` — abortar com erro descritivo ou deduplicar mantendo o registro mais antigo, conforme decisão documentada no cabeçalho do SQL.
- [ ] Atualizar `backend/supabase_schema.sql` (linha ~236, definição de `user_achievements`) para incluir `achievement_key TEXT NOT NULL` e o índice UNIQUE parcial, mantendo `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`.
- [ ] Atualizar o modelo/ORM correspondente a `user_achievements` (Pydantic/repo schema usado em `backend/routes_admin.py`) para incluir o campo `achievement_key`, deixando o caminho pronto para a DATA-GAM-2 consumir.
- [ ] Registrar a migration na lista mestra de migrations do roadmap (MIGRATION D) e validar que ela aparece na ordem correta de execução.
- [ ] Validar localmente: aplicar a migration sobre um snapshot com dados → conferir backfill, índice criado e idempotência (segunda execução sem erro).

## Dev Notes
- **Arquivos:**
  - `backend/migrations/20260603d_achievements_key.sql` (novo — MIGRATION D).
  - `backend/supabase_schema.sql` (~linha 236, tabela `user_achievements`).
  - Modelo/ORM de `user_achievements` consumido por `backend/routes_admin.py:1140-1176` (`unlock_achievement`).
- **Abordagem:** Separar a referência de catálogo (`achievement_key`) da chave física da row (`id` UUID surrogate). O índice parcial `UNIQUE (user_id, achievement_key)` passa a ser o único garantidor de "um achievement por usuário", em vez de sobrecarregar o `id`. Backfill `achievement_key = id` preserva o histórico, pois hoje `id` carrega justamente o id de catálogo. Toda a migration é escrita defensivamente (idempotente + pré-check de duplicatas) porque será aplicada em produção sobre dados já existentes.
- **Riscos de regressão:**
  - Esta story é puramente de schema/dados; o comportamento de runtime de `unlock_achievement` **não** é corrigido aqui (continua usando `id=achievement_id`) — a correção de código é a DATA-GAM-2, que tem `depends_on: DATA-GAM-1`. Aplicar esta migration sem a DATA-GAM-2 não piora o estado atual, mas não resolve sozinha o 500.
  - O `SET NOT NULL` em `achievement_key` falhará se o backfill não cobrir todas as rows — garantir que o backfill rode antes e que não haja `id` nulo (não há, pois é PK).
  - Se houver duplicatas históricas `(user_id, achievement_key)` (improvável dado o bug, mas possível via inserts manuais), a criação do UNIQUE falha — daí o pré-check obrigatório.
  - Blast radius: qualquer leitura de `user_achievements` (dashboards, stats, leaderboard) — apenas adiciona coluna, não remove/renomeia, então leituras existentes permanecem válidas.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: cenário de schema validando que após a migration dois usuários distintos podem ter o mesmo `achievement_key` sem colisão, e que o mesmo `(user_id, achievement_key)` é rejeitado pelo índice UNIQUE.
- [ ] Sem regressão na suíte de segurança.
- [ ] QA Gate: PASS ou CONCERNS.
- [ ] Migration confirmadamente idempotente (segunda execução sem erro) e com pré-check de duplicatas executado; `backend/supabase_schema.sql` e ORM atualizados de forma consistente com a migration; `id` mantido como PK UUID surrogate.

## QA Results
_(a preencher pelo @qa)_
