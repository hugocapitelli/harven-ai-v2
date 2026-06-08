---
id: TTSJOB-2
epic: EPIC-PODCAST
phase: 4
status: Draft
severity: HIGH
terminal: Backend & Infra
complexity: medium
depends_on: [TTSJOB-1, POD-4]
bug_refs: [60, 34]
---
# TTSJOB-2: Persistir lifecycle do job no DB; parar pop destrutivo; enforcar ownership + TTL (dono de #60)

## Story
Como aluno que solicita a geração de áudio (TTS) de um conteúdo, quero que o estado do meu job de síntese seja persistido no banco e consultável de forma estável e segura, para que o status sobreviva a restarts do backend, não seja destruído na primeira leitura e nunca seja exposto/manipulado por outro usuário.

## Contexto (do bug sweep)
Itens de bug cobertos: **#60** (dono desta Story) e **#34**.

- **#60 — Estado de job de TTS em dict em memória + pop destrutivo + sem ownership/TTL.** Em `backend/app/routes_ai.py` (≈linhas 523–646: `_tts_jobs`, `_run_tts_job`, `audio_job_status`), o lifecycle do job de síntese é guardado num dicionário de processo (`_tts_jobs`). Três defeitos compostos:
  1. **Volatilidade:** o dict vive no processo. Qualquer restart/redeploy do backend perde todos os jobs em andamento — o poller do front fica órfão sem nunca receber `done`/`error`.
  2. **Pop destrutivo:** a leitura de status (`audio_job_status`) faz `pop`/remoção da entrada, então o **segundo poll** do mesmo job não encontra a row e degrada para erro/404 mesmo quando a geração concluiu com sucesso. Isso quebra a idempotência esperada (dois polls iguais devem retornar o mesmo status).
  3. **Sem ownership:** o handler de status devolve o estado de qualquer `job_id` sem checar o dono, configurando **IDOR** — um usuário consegue inspecionar (e impactar, via pop) o job de outro. Não há TTL: jobs nunca-terminados acumulam memória indefinidamente.
- **#34 — `user_id` derivado de input não confiável.** No caminho de criação/consulta o `user_id` é (ou pode ser) lido do corpo/parâmetro da requisição em vez do contexto autenticado, permitindo que o ator forje a propriedade do job. A fonte de verdade do `user_id` deve ser **exclusivamente** o token autenticado (`request.state` / dependency de auth), nunca `body.user_id`.

**Impacto:** geração de áudio que "some" após restart, polls subsequentes falhando após sucesso real, e vazamento/manipulação cross-user do estado de jobs.

**Pré-requisitos já entregues nas dependências:**
- **TTSJOB-1** cria a tabela `tts_jobs` (migração `20260603f_tts_jobs.sql`: `id, content_id, user_id NOT NULL, audio_type CHECK, status, audio_url, error, duration_estimate, created_at, updated_at` + índices) e o repositório de acesso.
- **POD-4** entrega o pipeline de síntese (`_run_tts_job`) já ordenado para esta Story re-homar o dedup de #60 (par ordenado POD → TTSJOB conforme tabela de arquivos compartilhados do roadmap).

## Acceptance Criteria
- [ ] **Semear na criação:** o endpoint POST que dispara o TTS insere uma row em `tts_jobs` com `status = 'processing'` e `user_id` derivado **somente** do contexto autenticado, antes de iniciar o trabalho assíncrono.
- [ ] **Atualização de lifecycle:** `_run_tts_job` atualiza a row para `status = 'done'` (com `audio_url`/`duration_estimate`) em caso de sucesso e `status = 'error'` (com `error`) em caso de falha — nunca deixa o job preso em `'processing'` após terminar.
- [ ] **Status idempotente (não destrutivo):** `audio_job_status` faz **leitura** da row sem `pop`/delete; **dois polls iguais consecutivos retornam o mesmo status** (sem degradar para 404 após o primeiro).
- [ ] **Fallback de row ausente:** se a row de job não existir (ex.: job de antes da migração, ou já coletado por TTL) mas o conteúdo já tiver `contents.audio_url`, o status responde **sucesso** apontando para esse `audio_url` em vez de erro.
- [ ] **IDOR — dono autorizado passa:** o `user_id` autenticado dono do job consulta `audio_job_status` e recebe o estado real do seu job.
- [ ] **IDOR — ator cruzado bloqueado:** um `user_id` diferente do dono recebe **404** (preferido sobre 403 para não vazar existência do job) e **nenhuma leitura-mutação ocorre** — o job permanece intacto e o status do dono não é afetado.
- [ ] **IDOR — body nunca confiado:** `body.user_id`/parâmetro de requisição **nunca** é usado para definir ou checar a propriedade do job; o ownership vem exclusivamente do token autenticado.
- [ ] **TTL só em terminais:** a coleta/expiração por TTL remove apenas jobs em estado **terminal** (`done`/`error`) já vencidos; jobs em `processing` nunca são coletados por TTL.
- [ ] **Sobrevive a restart:** com a row persistida em `tts_jobs`, reiniciar o backend no meio da geração não perde o estado — o poller volta a obter `processing` e depois `done`/`error`.

## Tasks / Subtasks
- [ ] Em `backend/app/routes_ai.py`, no endpoint POST de criação de TTS: substituir a inserção em `_tts_jobs` (dict) por `INSERT` na tabela `tts_jobs` via repositório de TTSJOB-1, com `status='processing'`, `content_id`, `audio_type` e `user_id` lido de `request.state`/dependency de auth.
- [ ] Garantir que **nenhum** caminho leia `user_id` de `body`/query para ownership (corrige #34); remover qualquer referência a `body.user_id` no fluxo de TTS.
- [ ] Refatorar `_run_tts_job` (≈523–646) para fazer `UPDATE` da row (`done` + `audio_url`/`duration_estimate`, ou `error` + mensagem) ao invés de mutar o dict; tratar exceção para sempre fechar o job num estado terminal.
- [ ] Reescrever `audio_job_status` para `SELECT` por `id` **com filtro `user_id = <auth>`**: removendo o `pop`/delete (idempotência), retornando 404 quando a row não pertence ao requisitante (IDOR), e implementando o fallback `contents.audio_url` quando a row está ausente.
- [ ] Implementar coleta TTL (consulta/cron leve ou checagem on-read) que só expira rows em `done`/`error` mais antigas que o limite; documentar o limite escolhido.
- [ ] Remover o dict global `_tts_jobs` (e seus acessos remanescentes) após migrar todos os call sites; manter compatibilidade do shape de resposta consumido pelo poller (TTSJOB-3/TTSJOB-4).
- [ ] Respeitar o kill-switch `tts_jobs_persisted_enabled` (MIGRATION C `20260603c_feature_flags.sql`, default `false`): quando desligado, manter o comportamento legado; quando ligado, usar a persistência.

## Dev Notes
- **Arquivos:**
  - `backend/app/routes_ai.py` (≈523–646: `_tts_jobs`, `_run_tts_job`, `audio_job_status` e o endpoint POST de criação de TTS)
  - Repositório/acesso a `tts_jobs` entregue por **TTSJOB-1** (tabela criada em `supabase/migrations/20260603f_tts_jobs.sql`)
  - Tabela `contents` (campo `audio_url`, populado por POD-6) para o fallback
  - Flag `tts_jobs_persisted_enabled` em `system_settings` (`supabase/migrations/20260603c_feature_flags.sql`)
- **Abordagem:** mover o lifecycle do job de um dict de processo para a tabela `tts_jobs` (forward-only, já existente via TTSJOB-1). POST semeia `processing` com `user_id` autenticado; `_run_tts_job` faz `UPDATE` para `done`/`error`; `audio_job_status` faz `SELECT` filtrado por dono, sem efeitos colaterais, com fallback para `contents.audio_url` e TTL apenas sobre estados terminais. Ownership e o conjunto de chaves vêm sempre do contexto autenticado (corrige #34), nunca do payload.
- **Riscos de regressão (blast radius):**
  - **Poller do front (TTSJOB-3, TTSJOB-4):** consomem o shape de `audio_job_status`. A mudança de pop-destrutivo → leitura idempotente é justamente o que TTSJOB-3/4 esperam, mas o **formato JSON** da resposta deve permanecer compatível (campos `status`/`audio_url`/`error`).
  - **POD (síntese):** par ordenado POD → TTSJOB; `_run_tts_job` é tocado por ambos — esta Story é dona do dedup de #60, então evitar reintroduzir lógica em memória.
  - **Endpoint POST de criação:** alteração no contrato de quem fornece `user_id` (deixa de aceitar `body.user_id`); confirmar que nenhum cliente legítimo dependia disso.
  - **Remoção do dict `_tts_jobs`:** qualquer outro acesso ao global no módulo precisa ser migrado para não quebrar import/uso residual.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: (a) dois polls consecutivos retornam o mesmo status sem 404 após sucesso; (b) restart simulado mantém o estado do job; (c) ator cruzado recebe 404 e o job do dono permanece intacto.
- [ ] Sem regressão na suíte de segurança (especialmente testes de IDOR/ownership e de que `body.user_id` é ignorado).
- [ ] QA Gate: PASS ou CONCERNS
- [ ] Dict `_tts_jobs` removido do módulo e nenhum caminho de TTS lê `user_id` de input não confiável; TTL comprovadamente só expira jobs terminais; fallback `contents.audio_url` verificado quando a row está ausente.

## QA Results
_(a preencher pelo @qa)_
