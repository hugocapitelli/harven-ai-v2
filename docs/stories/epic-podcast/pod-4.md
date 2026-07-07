---
id: POD-4
epic: EPIC-PODCAST
phase: 4
status: InReview
severity: HIGH
terminal: Backend & Infra
complexity: medium
depends_on: [POD-2]
bug_refs: [35, 58, 59]
---
# POD-4: Timeouts + dedup por (content_id, audio_type) + cap de concorrência por user

## Story
Como aluno que solicita geração de áudio (podcast/resumo/explicação) na Harven.AI, quero que chamadas externas travadas sejam abortadas por timeout e que múltiplos cliques no mesmo conteúdo não disparem sínteses duplicadas, para que eu não desperdice quota de TTS/LLM, não pague por gerações órfãs e não veja erros silenciosos quando a persistência falha.

## Contexto (do bug sweep)
O endpoint `POST /api/ai/audio/generate-from-content` (`backend/routes_ai.py:599-634`) cria um `job_id` aleatório a cada submit e dispara uma thread daemon (`_run_tts_job`) sem qualquer deduplicação ou cap. Três defeitos verificados convergem aqui:

- **#35 — Falha de persistência engolida (`backend/routes_ai.py:577-583`):** o UPDATE de `contents.audio_url` está em `try/except` que só loga `logger.warning`. Se o UPDATE falhar (rede/outage), o job ainda reporta `status="done"` com `audio_url`, mas a row nunca é atualizada — áudio órfão no disco, irrecuperável pelo read path. LLM+TTS pagos, resultado perdido na próxima carga.
- **#58 — Leitura destrutiva no status (`backend/routes_ai.py:643-646`):** `audio_job_status` faz `_tts_jobs.pop(job_id, None)` na primeira leitura terminal (`done`/`error`). Uma resposta `done` em voo derrubada por race → segunda poll/retry retorna 404 → toast de erro espúrio numa geração possivelmente bem-sucedida.
- **#59 — Vazamento de memória no dict (`backend/routes_ai.py:522-646`):** o único cleanup é o pop destrutivo. Se o cliente nunca lê o status terminal (timeout do frontend de 90s, navegação, browser fechado), a entrada `done`/`error` fica em `_tts_jobs` indefinidamente — sem TTL, sem cap de tamanho. O modo de falha mais comum é exatamente o que vaza.

Contexto adicional relevante (mesmo arquivo): as chamadas `el_client.text_to_speech.convert(...)` (`:557-562`) e `svc.client.chat.completions.create(...)` (`:533, :543`) são bloqueantes em thread daemon **sem timeout** — a base da AC "chamada travada abortada por timeout → job error".

## Acceptance Criteria
- [ ] **Timeout em chamadas externas:** as chamadas LLM (`chat.completions.create`) e TTS (`text_to_speech.convert`) em `_run_tts_job` têm timeout explícito; quando uma chamada trava além do limite, a thread aborta e o job termina em `status="error"` com `detail` descritivo (não fica em `processing` para sempre).
- [ ] **Dedup por (content_id, audio_type):** dois submits do **mesmo** `content_id` + mesmo `audio_type` enquanto há job em voo retornam o **mesmo `job_id`** e disparam **apenas 1 síntese** (uma única thread, uma única chamada TTS).
- [ ] **Type diferente não é bloqueado:** submit de `(content_id, "summary")` e `(content_id, "podcast")` simultâneos geram `job_id` distintos e duas sínteses independentes — a chave de dedup é o par `(content_id, audio_type)`, não só `content_id`.
- [ ] **Cap de concorrência por user:** existe um limite de jobs TTS em voo por usuário; ao exceder, o submit retorna erro claro (HTTP 429 com `detail`) em vez de spawnar mais threads sem cap.
- [ ] **#35 — persistência falha = job error:** se o UPDATE de `contents.audio_url` falhar, o job NÃO reporta `done` silenciosamente — ou termina em `error`, ou retorna flag `persisted=false` (decidir em Dev Notes), com retry da persistência antes de desistir.
- [ ] **#58 — status não-destrutivo:** `audio_job_status` não faz `pop` na leitura; duas polls consecutivas após `done` retornam o mesmo payload terminal; no 404 (job ausente) cai para `contents.audio_url` daquele `content_id` quando disponível.
- [ ] **#59 — sem vazamento:** jobs terminais expiram por TTL (`created_at` por job + sweep/check-on-access); o dict `_tts_jobs` não cresce indefinidamente para jobs nunca pollados.

## Tasks / Subtasks
- [ ] Em `_run_tts_job` (`backend/routes_ai.py:526-596`), adicionar timeout às chamadas OpenAI (`svc.client.chat.completions.create`, linhas 533/543) e ElevenLabs (`el_client.text_to_speech.convert`, linha 557); converter estouro de timeout em `_tts_jobs[job_id] = {"status": "error", "detail": ...}`.
- [ ] Introduzir índice de dedup em voo: mapa `(content_id, audio_type) -> job_id` (ex.: `_tts_inflight`). Em `audio_generate_from_content` (`:599-634`), antes de gerar `job_id`, consultar o índice; se houver job ativo para a chave, retornar o `job_id` existente sem spawnar thread.
- [ ] Limpar a entrada do índice de dedup ao final de `_run_tts_job` (sucesso e erro) para liberar a chave `(content_id, audio_type)`.
- [ ] Implementar cap por user: contador de jobs em voo por `current_user['id']`; ao exceder o limite configurável, levantar `HTTPException(status_code=429, ...)` antes de iniciar a thread.
- [ ] #35: em `_run_tts_job` (`:577-583`), tratar falha do UPDATE com retry; se persistir falhando, marcar job como `error` (ou setar `persisted=false` no payload terminal) em vez de `done` limpo.
- [ ] #58: em `audio_job_status` (`:637-646`), remover o `_tts_jobs.pop(...)`; em job ausente, tentar fallback a `contents.audio_url` via `ContentRepository` antes de 404.
- [ ] #59: registrar `created_at` por job em `_tts_jobs`; adicionar sweep por TTL (check-on-access em `audio_job_status` + varredura periódica) e cap de tamanho do dict.
- [ ] Adicionar teste de regressão (ver Definition of Done) cobrindo timeout→error, dedup mesmo type, type diferente não-bloqueado, cap por user, status idempotente e TTL.

## Dev Notes
- **Arquivos:** `backend/routes_ai.py` (job store `_tts_jobs` :522-523; worker `_run_tts_job` :526-596; submit `audio_generate_from_content` :599-634; status `audio_job_status` :637-646). Leitura/fallback via `repositories.ContentRepository` (`get_by_id` / coluna `contents.audio_url`).
- **Abordagem:** estado in-memory permanece (alinhado a esta fase; persistência completa do lifecycle no Postgres é escopo de TTSJOB-2, que `depends_on` POD-4). Acrescentar: (1) timeouts nas duas chamadas externas dentro do worker; (2) índice `(content_id, audio_type) -> job_id` para dedup em voo + retorno idempotente do mesmo `job_id`; (3) contador por user para cap de concorrência (HTTP 429); (4) substituir leitura destrutiva por TTL + sweep e fallback a `contents.audio_url`; (5) elevar falha de persistência (#35) de warning para erro do job com retry. Decisão a registrar pelo @dev: `error` duro vs. `persisted=false` para #35 — preferir `persisted=false` no payload + retry para não invalidar áudio já gerado, mantendo o read path consistente.
- **Riscos de regressão:** blast radius restrito ao módulo TTS de `backend/routes_ai.py`. Consumidores: o frontend que faz POST em `/api/ai/audio/generate-from-content` e poll em `/api/ai/audio/status/{job_id}` (o polling do frontend espera ~90s; o cap por user pode mudar o comportamento de retry — coordenar mensagem 429). Mudar status de destrutivo para idempotente (#58) altera contrato de leitura — verificar que o frontend não dependia do 404 pós-leitura. O índice de dedup compartilhado entre threads exige acesso protegido por lock (processo single-worker, mas thread daemon concorrente). Não tocar no read path de `contents.audio_url` além do fallback de leitura. Dependência: POD-2 deve estar concluída antes (sequência do roadmap).

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde cobrindo: (a) timeout em chamada externa → job `error`; (b) 2 submits mesmo `(content_id, audio_type)` → mesmo `job_id` e 1 única chamada TTS (mockada); (c) `(content_id, type_A)` + `(content_id, type_B)` → 2 jobs distintos; (d) cap por user excedido → HTTP 429; (e) 2 polls após `done` retornam payload idêntico (não-destrutivo); (f) job além do TTL é varrido de `_tts_jobs`.
- [ ] Sem regressão na suíte de segurança (ownership/IDOR de #60 permanece intacto; este escopo não relaxa autorização do status).
- [ ] QA Gate: PASS ou CONCERNS
- [ ] Falha de persistência de `audio_url` (#35) não resulta mais em job `done` silencioso — verificado por teste (UPDATE forçado a falhar → `persisted=false` ou `error`, com retry).

## QA Results
_(a preencher pelo @qa)_
