---
id: CDC-4
epic: EPIC-CLEANUP
phase: 5
status: Draft
severity: MEDIUM
terminal: Backend & Infra
complexity: medium
depends_on: []
bug_refs: [62]
---
# CDC-4: Coluna `sequence` monotônica em chat_messages + order by (created_at, sequence)

## Story
Como instrutor/aluno que lê e exporta a transcrição de uma sessão de chat socrático, quero que as mensagens sejam ordenadas de forma determinística, para que a conversa nunca apareça reordenada quando dois turnos compartilham o mesmo `created_at` (empate de microssegundo entre user/instrutor/assistente).

## Contexto (do bug sweep)
Item de bug **#62** (achado de ordenação de mensagens), referência direta em `backend/.../chat_repo.py:47-55`:

> **Ordenação de mensagens só por `created_at` sem tiebreaker** (`chat_repo.py:47-55`): sem sequência/ordinal; empates de microssegundo entre mensagens user/instrutor podem reordenar a transcrição/export. **Correção:** coluna de sequência (BIGSERIAL) e ordenar por `(created_at, sequence)`.

**Defeito concreto:** a leitura de mensagens em `chat_repo.py:47-55` faz `.order("created_at")` sem critério de desempate. Quando dois INSERTs caem no mesmo timestamp (alta concorrência, ou turnos gravados na mesma chamada), o banco devolve as linhas em ordem **arbitrária** (não há ordem garantida sem `ORDER BY` total). 

**Impacto:** a transcrição renderizada (list/detail), a tela de revisão do instrutor e, criticamente, o **export para Moodle** (#6/#11/#41 dependem da fidelidade da transcrição) podem inverter pergunta/resposta ou trocar a ordem de turnos consecutivos. É um defeito de **determinismo de leitura**, não de perda de dado — a correção é aditiva e backfillável conforme a Migration E (`20260603e_message_sequence.sql`) descrita no roadmap.

## Acceptance Criteria
- [ ] Migração **aditiva e backfillável** adiciona `chat_messages.sequence BIGINT` (Migration E `20260603e_message_sequence.sql`); backfill via `row_number() over (partition by session_id order by created_at, id)` antes de qualquer ordenação depender da coluna.
- [ ] Toda nova mensagem inserida recebe `sequence` monotonicamente crescente por sessão (BIGSERIAL/sequência ou cálculo `max(sequence)+1` por `session_id` no INSERT) — sem buracos que quebrem a ordem relativa.
- [ ] Leitura em `chat_repo.py:47-55` passa a ordenar por **`(created_at, sequence)`** (ordem total), eliminando ambiguidade de empate.
- [ ] **Ordem determinística em list/detail/export:** dada a mesma sessão, list (transcrição), detail (revisão do instrutor) e export Moodle devolvem **exatamente a mesma sequência** de turnos em execuções repetidas.
- [ ] **Timestamps idênticos → ordem de inserção estável:** duas mensagens com `created_at` igual aparecem na ordem em que foram inseridas (a de menor `sequence` primeiro), de forma repetível.
- [ ] Migração é idempotente (re-rodar não duplica coluna nem reescreve sequências já corretas) e não regride dados existentes (linhas antigas recebem `sequence` consistente com sua ordem cronológica atual via window function).
- [ ] Nenhuma regressão na persistência de ambos os turnos (#6): os dois turnos (user + assistente) continuam gravados e agora com `sequence` distinto e crescente.

## Tasks / Subtasks
- [ ] Criar migração `backend/migrations/20260603e_message_sequence.sql`: `ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS sequence BIGINT;` (aditiva, nullable inicialmente).
- [ ] Backfill na mesma migração: `UPDATE chat_messages SET sequence = sub.rn FROM (SELECT id, row_number() over (partition by session_id order by created_at, id) AS rn FROM chat_messages) sub WHERE chat_messages.id = sub.id AND chat_messages.sequence IS NULL;`
- [ ] Adicionar índice de leitura: `CREATE INDEX IF NOT EXISTS idx_chat_messages_session_order ON chat_messages (session_id, created_at, sequence);`
- [ ] No write-path do repositório de mensagens (INSERT em `chat_repo.py`): popular `sequence` por sessão (calcular `coalesce(max(sequence),0)+1` filtrado por `session_id`, ou usar sequência dedicada) garantindo monotonicidade.
- [ ] Em `chat_repo.py:47-55`: trocar `.order("created_at")` por ordenação total `.order("created_at").order("sequence")` (ou equivalente `(created_at, sequence)`).
- [ ] Verificar consumidores de leitura que renderizam transcrição: detail/revisão do instrutor e `prepare_moodle_export` — confirmar que herdam a ordenação do repositório (não reordenam por conta própria).
- [ ] Documentar a coluna no schema/migration index e na nota de rollout (forward-only do ponto de vista do write-path).

## Dev Notes
- **Arquivos:**
  - `backend/.../chat_repo.py` (leitura `:47-55` + write-path de INSERT de mensagem)
  - `backend/migrations/20260603e_message_sequence.sql` (nova — Migration E)
  - Consumidores de transcrição: detail/revisão do instrutor e `prepare_moodle_export` (export Moodle)
- **Abordagem:** Migração aditiva → backfill via `row_number() over (partition by session_id order by created_at, id)` ANTES de ordenar por `sequence` (regra do roadmap: "backfill antes de constraints"). Write-path passa a atribuir `sequence` monotônico por `session_id`. Leitura usa ordem total `(created_at, sequence)` para desempate determinístico. Sem `NOT NULL`/constraint dura nesta story (mantém aditiva e backfillável); a coluna apenas adiciona um tiebreaker estável.
- **Riscos de regressão / blast radius:**
  - A query de leitura em `chat_repo.py:47-55` alimenta **3 superfícies**: transcrição na tela do aluno, tela de revisão do instrutor e export Moodle. Mudar o `ORDER BY` afeta as três simultaneamente — por isso o AC exige paridade de ordem entre list/detail/export.
  - Interação com a persistência de turnos (#6): o write-path agora escreve um campo a mais; garantir que ambos os turnos continuem gravados e que `sequence` não colida na mesma sessão.
  - Coordenação de arquivo: este cluster (`cleanup`) toca `chat_repo.py`; evitar conflito com clusters que tocam `routes_ai.py` (TPP-4 é o dono da Migration E no roadmap — alinhar para não duplicar a migração). Nesta story, single-owner da região de leitura/ordenação de `chat_repo.py`.
  - A migração é segura para tabelas grandes (UPDATE com window em batch único pode ser pesado): se necessário, executar em janela de baixo tráfego conforme o plano de rollout da Fase 5.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: inserir 2+ mensagens com `created_at` **idêntico** numa sessão e provar que a leitura retorna ordem de inserção estável e repetível (antes: ordem arbitrária; depois: determinística por `(created_at, sequence)`).
- [ ] Sem regressão na suíte de segurança (suíte IDOR/auth 100%, sem skips).
- [ ] QA Gate: PASS ou CONCERNS.
- [ ] Migração `20260603e_message_sequence.sql` aplica de forma aditiva e idempotente; backfill via window function preenche todas as linhas existentes; re-run não duplica coluna nem reescreve sequências.
- [ ] Teste de paridade list/detail/export: a mesma sessão produz a mesma sequência de turnos nas três superfícies (incl. `prepare_moodle_export`), sem regredir a persistência de ambos os turnos (#6).

## QA Results
_(a preencher pelo @qa)_
