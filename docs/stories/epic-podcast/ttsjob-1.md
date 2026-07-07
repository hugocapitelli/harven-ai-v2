---
id: TTSJOB-1
epic: EPIC-PODCAST
phase: 4
status: InReview
severity: HIGH
terminal: Backend & Infra
complexity: low
depends_on: []
bug_refs: [34, 58, 59]
---
# TTSJOB-1: Migração tabela `tts_jobs` durável + `TtsJobRepository`

## Story
Como engenheiro de backend do Harven.AI, quero uma tabela `tts_jobs` durável no banco com `user_id NOT NULL` (FK) e um `TtsJobRepository` com leitura por dono e varredura de expirados, para que o ciclo de vida dos jobs de TTS/podcast sobreviva a reinícios do processo, seja consultável por dono e tenha base segura para enforçar ownership e TTL — eliminando o estado volátil em memória que perde jobs e impede auditoria.

## Contexto (do bug sweep)
Os defeitos #34, #58 e #59 (BUG-SWEEP-2026-06-03.md) descrevem que o estado dos jobs de TTS/podcast vive apenas em memória (dicionário/fila no processo do backend), sem persistência durável. Consequências verificadas:
- **#34 — Perda de estado em restart:** ao reiniciar o worker/processo, todos os jobs `processing`/`pending` são perdidos; o cliente fica em polling eterno sem nunca receber `done`/`error`, e não há registro do que aconteceu.
- **#58 — Ausência de vínculo de dono persistido:** sem `user_id` durável associado ao job, não é possível enforçar ownership na leitura (base para o IDOR coberto em TTSJOB-2 / item #60). Qualquer ator pode, no estado atual, consultar status por `content_id` sem checagem de dono.
- **#59 — Sem limpeza de jobs antigos:** registros terminais (`done`/`error`) nunca são varridos, e jobs `processing` ficam pendurados indefinidamente sem mecanismo de expiração — não há TTL nem coleta de lixo.

Esta story corrige a **fundação de dados**: cria a tabela durável e o repositório. O enforcement de ownership e a transição de lifecycle (parar o pop destrutivo, semear/atualizar rows) são feitos na story dependente TTSJOB-2.

## Acceptance Criteria
- [ ] Migration `20260603f_tts_jobs.sql` cria a tabela `tts_jobs` com as colunas: `id` (PK), `content_id`, `user_id NOT NULL` com FK para a tabela de usuários (`ON DELETE CASCADE`), `audio_type` com `CHECK` no conjunto de valores válidos (ex.: `tts`, `podcast`), `status` (default `processing`), `audio_url`, `error`, `duration_estimate`, `created_at` (default now), `updated_at` (default now).
- [ ] Índices criados para os padrões de consulta: índice em `(content_id, user_id)` (leitura por dono), índice em `status` (varredura de expirados/terminais) e índice em `created_at`/`updated_at` (TTL).
- [ ] A tabela **NÃO** possui RLS habilitada (enforcement de ownership é feito na camada de aplicação via repositório/serviço, conforme padrão do roadmap "sem RLS").
- [ ] `TtsJobRepository.get_for_content(content_id, user_id)` retorna o job apenas quando `content_id` **e** `user_id` casam; nunca filtra somente por `content_id`. (IDOR — três desfechos:)
  - [ ] Dono autorizado: chamada com o `user_id` real do dono retorna o job correspondente.
  - [ ] Ator cruzado: chamada com `user_id` diferente do dono retorna `None`/vazio (nenhuma row vazada) — não há leitura nem mutação de dado de outro usuário.
  - [ ] `user_id` nunca é derivado de `body`/payload do cliente: o repositório só aceita `user_id` como argumento explícito vindo da identidade autenticada; não há caminho que confie em `body.user_id`.
- [ ] `TtsJobRepository.sweep_expired(...)` remove/expira apenas jobs em estado **terminal** (`done`/`error`) que ultrapassaram o TTL; **nunca** toca em jobs `processing` (verificável: um job `processing` antigo permanece após o sweep).
- [ ] As operações de escrita do repositório (`upsert`/criação) são **idempotentes**: aplicar a migration duas vezes é seguro (`IF NOT EXISTS`/guard) e semear o mesmo job duas vezes não cria duplicata nem corrompe estado.

## Tasks / Subtasks
- [ ] Criar a migration `backend/migrations/20260603f_tts_jobs.sql` (ou diretório de migrations equivalente do projeto) com `CREATE TABLE IF NOT EXISTS tts_jobs (...)`, constraint `CHECK` em `audio_type`, FK `user_id` → usuários `ON DELETE CASCADE`, e os três índices (`(content_id, user_id)`, `status`, `created_at`).
- [ ] Implementar `TtsJobRepository` em `backend/app/repositories/tts_job_repository.py` (ou caminho de repositórios equivalente):
  - [ ] `get_for_content(content_id, user_id)` — SELECT com `WHERE content_id = :content_id AND user_id = :user_id`.
  - [ ] `sweep_expired(now, ttl)` — DELETE/UPDATE `WHERE status IN ('done','error') AND updated_at < (now - ttl)`; garantir que `processing` está excluído da cláusula.
  - [ ] método de criação/`upsert` idempotente (semear row `processing`) para consumo pela TTSJOB-2.
- [ ] Registrar a migration no runner/lista de migrations do backend para que rode no boot/CI.
- [ ] Escrever teste de regressão (ver Definition of Done) cobrindo os três desfechos de IDOR de `get_for_content`, o `sweep_expired` que preserva `processing`, e a idempotência da migration/criação.

## Dev Notes
- **Arquivos:**
  - `backend/migrations/20260603f_tts_jobs.sql` (nova migration — nome conforme item 6 do roadmap)
  - `backend/app/repositories/tts_job_repository.py` (novo repositório — ajustar ao layout real de repositórios do projeto)
  - Runner/registry de migrations do backend (registrar a nova migration)
  - Testes: `backend/tests/test_tts_job_repository.py` (novo)
- **Abordagem:** Esta story é puramente de **fundação de persistência** — cria schema durável + camada de acesso, sem alterar ainda os endpoints/worker que hoje usam estado em memória. Schema com `user_id NOT NULL` FK garante integridade referencial; ausência de RLS é deliberada (enforcement na aplicação). O repositório encapsula as duas regras críticas: leitura sempre escopada por `(content_id, user_id)` e sweep restrito a estados terminais. Idempotência via `IF NOT EXISTS` na migration e `upsert`/guard na criação.
- **Riscos de regressão:** Blast radius baixo nesta story — nenhum caller existente passa a depender do repositório ainda (a substituição do estado em memória ocorre em TTSJOB-2). Riscos a vigiar: (1) o `CHECK` de `audio_type` deve cobrir todos os valores que o worker de TTS/podcast realmente emite, senão inserts da TTSJOB-2 falharão; (2) a FK `user_id` exige que a tabela de usuários referenciada esteja correta para o ambiente; (3) índices/constraint não devem colidir com objetos pré-existentes (usar nomes únicos + `IF NOT EXISTS`). Confirmar a coluna/tabela de usuários alvo da FK contra o schema real antes de aplicar.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde
- [ ] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [ ] Migration aplica de forma idempotente (rodar 2x sem erro); `get_for_content` rejeita ator cruzado (retorna vazio) e nunca confia em `body.user_id`; `sweep_expired` preserva jobs `processing` e remove apenas terminais expirados — todos cobertos por teste automatizado.

## QA Results
_(a preencher pelo @qa)_
