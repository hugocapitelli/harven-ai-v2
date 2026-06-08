---
id: CFG-2
epic: EPIC-CLEANUP
phase: 5
status: Draft
severity: MEDIUM
terminal: Backend & Infra
complexity: medium
depends_on: []
bug_refs: [45]
---
# CFG-2: system_settings singleton determinístico via id fixo + upsert

## Story
Como engenheiro de backend responsável pela configuração da plataforma Harven.AI, quero que `system_settings` se comporte como um singleton real — lookup por um `id` fixo e gravação via `upsert` com `on_conflict` — para que saves concorrentes não produzam linhas duplicadas e a leitura de configuração seja sempre determinística, independentemente da ordem ou simultaneidade das gravações.

## Contexto (do bug sweep)
Item #45 (BUG-SWEEP-2026-06-03): a tabela `system_settings` é tratada como singleton implícito, mas não há garantia estrutural disso. O padrão atual de leitura é "pega a primeira linha que aparecer" e o save faz INSERT/UPDATE sem `id` determinístico nem `on_conflict`. Isso cria duas falhas concretas:

1. **Race de gravação:** dois saves concorrentes (ex.: dois admins salvando settings ao mesmo tempo, ou save + boot-time seed) inserem **duas linhas** em `system_settings`. A partir daí, leituras subsequentes podem retornar configurações diferentes dependendo de qual linha o PostgREST devolve primeiro — comportamento não determinístico em produção.
2. **Drift de configuração:** uma vez duplicada, a tabela acumula linhas órfãs; a "configuração efetiva" passa a depender de ordenação implícita do banco, e mutações via `save_admin_settings` podem atualizar a linha "errada", deixando valores stale visíveis.

São **6 callers** que dependem do singleton (leitura/escrita de settings: get/save admin settings, feature-flags/kill-switches lidos de `system_settings`, seed de boot e variantes de leitura interna). Todos partem da premissa "existe exatamente uma linha de settings" — premissa que hoje não é garantida.

## Acceptance Criteria
- [ ] `system_settings` passa a usar um **`id` fixo determinístico** (constante de aplicação, ex.: `SYSTEM_SETTINGS_SINGLETON_ID`) para o registro singleton; todo lookup de leitura filtra por esse `id` em vez de "primeira linha".
- [ ] Toda gravação de settings usa **`upsert` com `on_conflict` no `id` fixo** (não INSERT cego nem UPDATE-por-ordenação), de modo que a primeira gravação cria e as seguintes atualizam **a mesma linha**.
- [ ] **Concorrência:** dois saves concorrentes contra `system_settings` resultam em **exatamente 1 linha** na tabela (sem duplicata). Validado por teste de regressão que simula gravação concorrente / upsert repetido.
- [ ] **Migração de dedup:** uma migração colapsa quaisquer linhas duplicadas pré-existentes em uma única linha singleton, **mantendo os últimos valores** (registro mais recente por `created_at`/`updated_at` vence) e atribuindo a ela o `id` fixo. A migração é **idempotente** — rodar duas vezes não altera o estado nem falha.
- [ ] Os **6 callers** do singleton continuam funcionando sem alteração de contrato externo: leitura retorna a configuração efetiva (última gravada) e escrita persiste na linha singleton.
- [ ] Leitura de settings é determinística: após N saves (sequenciais ou concorrentes), qualquer leitura subsequente retorna o mesmo conjunto de valores (os últimos persistidos).

## Tasks / Subtasks
- [ ] Localizar a tabela/acessores de `system_settings` no backend (`backend/`) e mapear os **6 callers** (get admin settings, save admin settings, leitura de feature-flags/kill-switches, seed de boot e demais leituras internas) — confirmar lista exata com Grep por `system_settings`.
- [ ] Introduzir a constante `SYSTEM_SETTINGS_SINGLETON_ID` (id fixo) em local compartilhado e referenciá-la em todos os acessos.
- [ ] Refatorar a **leitura** do singleton para filtrar por `id == SYSTEM_SETTINGS_SINGLETON_ID` (`.eq("id", ...).single()` ou equivalente), removendo o padrão "primeira linha".
- [ ] Refatorar a **gravação** (`save_admin_settings` e seed) para `upsert(..., on_conflict="id")` com o `id` fixo no payload.
- [ ] Criar **MIGRATION B** (`20260603b_unique_constraints.sql`, conforme roadmap §Migrations) — bloco de dedup do singleton: colapsar duplicatas mantendo o registro mais recente, reatribuir/garantir o `id` fixo e (idealmente) reforçar a unicidade do singleton. Idempotente e seguro para reexecução.
- [ ] Garantir backfill **antes** da constraint: dedup `system_settings` precede qualquer reforço de unicidade (alinhado a §"Backfill antes de constraints" do roadmap).
- [ ] Escrever teste de regressão: (a) dois upserts concorrentes/repetidos → 1 linha; (b) leitura determinística após múltiplos saves; (c) migração idempotente (rodar 2x = mesmo estado).

## Dev Notes
- **Arquivos:**
  - `backend/` — módulo de serviço/acessores de `system_settings` (settings service / repository) e os 6 call sites; confirmar paths exatos via `grep -rn "system_settings" backend/`.
  - Migração SQL: `backend/migrations/20260603b_unique_constraints.sql` (MIGRATION B — compartilhada com TPP-1; **coordenar** o bloco de dedup/singleton de `system_settings` com o bloco de `chat_sessions`).
- **Abordagem:** Transformar o singleton implícito em singleton **explícito e estrutural**. Padrão: id fixo constante + `upsert on_conflict=id`. A leitura deixa de depender de ordenação do banco e passa a ser um lookup por chave determinística. A migração colapsa o passado (dedup, last-write-wins por timestamp) e a constraint/lógica de id fixo previne o futuro (sem novas duplicatas).
- **Riscos de regressão (blast radius):** todos os **6 callers** de `system_settings`. Em especial, os **kill-switches/feature-flags** definidos na MIGRATION C (`authz_enforcement_enabled`, `persist_tutor_turns_enabled`, etc.) vivem em `system_settings` — se a dedup escolher a linha errada, flags podem reverter para defaults inesperados; por isso o critério "mantém últimos valores" é load-bearing. CFG-5 depende desta story (allowlist de colunas no save), então manter a assinatura/contrato de `save_admin_settings` estável. A MIGRATION B é compartilhada com TPP-1 (singleton de chat_sessions) — não conflitar os dois blocos no mesmo arquivo.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: upserts concorrentes → 1 linha; leitura determinística; migração idempotente
- [ ] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [ ] Migração B executada em ambiente de staging confirmando dedup correto (linha única, últimos valores preservados) e reexecução sem efeito colateral
- [ ] Os 6 callers do singleton verificados como funcionais pós-refactor (leitura/escrita na linha singleton)

## QA Results
_(a preencher pelo @qa)_
