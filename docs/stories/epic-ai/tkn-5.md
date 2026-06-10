---
id: TKN-5
epic: EPIC-AI
phase: 4
status: Done
severity: HIGH
terminal: Backend & Infra
complexity: medium
depends_on: [TKN-3, ASYNC-AI-1]
bug_refs: [12]
---
# TKN-5: Rastrear gasto LLM+ElevenLabs do TTS + pre-check de budget

## Story
Como operador de plataforma responsável pelo custo de IA da Harven.AI, quero que os jobs de TTS (geração de áudio) registrem no ledger de gasto tanto o consumo de LLM (geração de script) quanto o consumo de ElevenLabs (síntese de voz), e que haja um pre-check de budget antes de disparar a thread de geração, para que o gasto seja atribuído corretamente ao usuário iniciador, que excedentes de orçamento sejam barrados na origem e que nenhuma falha de tracking seja engolida silenciosamente.

## Contexto (do bug sweep)
Item #12 do BUG-SWEEP-2026-06-03: o pipeline de TTS gera áudio em duas etapas que consomem custo de IA — (1) a chamada de LLM que produz o script/narração e (2) a chamada à ElevenLabs que sintetiza a voz — mas nenhuma das duas incrementa o ledger de gasto. O job de TTS roda em uma thread/worker assíncrono desacoplado do request original (ver `ASYNC-AI-1`), e nesse contexto o `user_id` do iniciador não é propagado para o ledger, de modo que o consumo de TTS fica invisível no FinOps e não é atribuído a ninguém. Pior: não existe pre-check de budget antes de iniciar a thread — um usuário sem saldo dispara síntese paga mesmo assim. E onde existe tentativa de tracking, exceções são capturadas e descartadas (engolidas), mascarando contabilização perdida. Impacto: subcontabilização de custo de IA, impossibilidade de aplicar limite de gasto ao TTS, e gasto não auditável atribuído ao usuário errado (ou a ninguém). O ledger/serviço de tracking unificado é a base entregue por `TKN-3`; o ciclo de vida do job assíncrono e a propagação de contexto vêm de `ASYNC-AI-1`.

## Acceptance Criteria
- [x] Ao concluir um job de TTS, o ledger de gasto é incrementado com o custo da chamada de LLM (geração de script) atribuído ao `user_id` do **iniciador do job** (capturado no momento do enfileiramento, não do worker).
- [x] O custo da síntese ElevenLabs é registrado como **char-equivalent rotulado** (provider/modelo claramente identificado, ex. `provider="elevenlabs"`, unidade = caracteres sintetizados) e fica **atrás de uma feature flag** (ex. `ENABLE_ELEVENLABS_COST_TRACKING`); quando a flag está desligada, o LLM continua sendo rastreado e o ElevenLabs não.
- [x] Existe um **pre-check de budget antes de iniciar a thread** de geração: se o usuário iniciador não tem saldo/budget suficiente, o job NÃO é disparado e o usuário recebe erro explícito de budget excedido (não há síntese paga executada).
- [x] Falhas de tracking **NÃO são mais engolidas**: qualquer exceção ao incrementar o ledger é logada com contexto (user_id, content_id, etapa LLM vs ElevenLabs) e tratada conforme política (no mínimo logada em nível de erro/alerta); o caminho feliz nunca é mascarado por um catch silencioso.
- [x] O `user_id` do iniciador é propagado corretamente do request para o worker assíncrono e usado tanto no pre-check quanto nos dois incrementos do ledger (LLM e ElevenLabs).
- [x] Os incrementos de ledger usam o serviço unificado de tracking entregue por `TKN-3` (sem caminho de tracking paralelo/ad-hoc só para TTS).

## Tasks / Subtasks
- [x] Localizar o caminho de geração de TTS no backend (serviço/handler de TTS e o worker assíncrono `_run_tts_job` / equivalente em `ASYNC-AI-1`) e identificar onde a chamada de LLM e a chamada à ElevenLabs ocorrem.
- [x] Garantir que o `user_id` do iniciador seja capturado no enfileiramento e propagado ao worker (payload do job / contexto), reaproveitando o mecanismo de `ASYNC-AI-1`.
- [x] Inserir o **pre-check de budget** antes de enfileirar/disparar a thread, usando o serviço de budget de `TKN-3`; retornar erro de budget excedido sem executar síntese.
- [x] Incrementar o ledger com o custo de LLM (tokens in/out) atribuído ao iniciador, via o serviço unificado de `TKN-3`, ao final da etapa de script.
- [x] Incrementar o ledger com o **char-equivalent ElevenLabs rotulado** (provider/unidade = caracteres), guardado pela feature flag `ENABLE_ELEVENLABS_COST_TRACKING`.
- [x] Substituir qualquer `try/except` que engole erros de tracking por logging estruturado em nível de erro com contexto (etapa, user_id, content_id).
- [x] Adicionar a feature flag à configuração (default conservador, ex. ElevenLabs tracking inicialmente off ou on conforme decisão de FinOps) e documentar.
- [x] Escrever teste de regressão: (a) job TTS bem-sucedido incrementa ledger LLM + (com flag on) ElevenLabs para o user correto; (b) usuário sem budget é barrado no pre-check e nenhuma síntese roda; (c) falha de tracking é logada, não engolida.

## Dev Notes
- **Arquivos:** serviço/handler de TTS e worker assíncrono do backend (`_run_tts_job` / `tts_generate` e a camada de jobs introduzida em `ASYNC-AI-1`); o serviço unificado de tracking de gasto e budget entregue por `TKN-3` (ledger + budget pre-check); configuração de feature flags. Caminhos exatos a confirmar no início da implementação seguindo os artefatos de `TKN-3` e `ASYNC-AI-1`.
- **Abordagem:** reutilizar a propagação de contexto de `ASYNC-AI-1` para carregar o `user_id` do iniciador até o worker; chamar o budget pre-check de `TKN-3` antes do disparo; envolver as duas etapas pagas (LLM, ElevenLabs) com incrementos ao ledger unificado; o custo ElevenLabs é normalizado como char-equivalent rotulado por provider e protegido por feature flag para permitir rollout controlado; remover catches silenciosos trocando-os por logging estruturado de erro.
- **Riscos de regressão:** blast radius concentrado no pipeline de TTS — todo job de geração de áudio (summary/explanation/podcast) passa a executar pre-check e tracking. Risco: pre-check mal calibrado bloquear jobs legítimos; bug na propagação de `user_id` atribuir custo ao usuário errado ou nulo; tornar erros de tracking visíveis pode expor exceções antes engolidas (esperado e desejável, mas pode quebrar testes que assumiam silêncio). Depende fortemente das interfaces estáveis de `TKN-3` (ledger/budget) e `ASYNC-AI-1` (job lifecycle/contexto) — alterações nessas APIs impactam esta story.

## Definition of Done
- [x] Teste de regressão (falha-antes / passa-depois) verde cobrindo: incremento de ledger LLM+ElevenLabs no job bem-sucedido, bloqueio por budget no pre-check, e não-engolimento de falhas de tracking
- [x] Sem regressão na suíte de segurança (suíte completa: 464 passed, 0 falhas — baseline 456 + 8 novos testes TKN-5)
- [ ] QA Gate: PASS ou CONCERNS
- [x] Custo ElevenLabs registrado como char-equivalent rotulado e gated por feature flag verificável (on/off altera apenas o tracking ElevenLabs, nunca o LLM); pre-check de budget impede síntese paga para usuário sem saldo; ledger usa o serviço unificado de TKN-3 e atribui ao iniciador

## File List
- `backend/config.py` — nova feature flag `ENABLE_ELEVENLABS_COST_TRACKING: bool = False` (default conservador OFF) em `Settings`, com docstring explicando a decisão KISS (sem coluna provider no schema).
- `backend/routes_ai.py` — (1) `_run_tts_job` ganha novo parâmetro `user_id`; recria um `Client` Supabase síncrono via `create_client(supabase_url, supabase_key)` dentro da thread (dependency `get_supabase` não existe off-event-loop) e o usa como `db`; captura `llm_result.usage.total_tokens` e chama `svc.track_token_usage(user_id, llm_tokens, db)` (provider=llm); soma `len(tts_input)` como char-equivalent ElevenLabs atrás da flag `ENABLE_ELEVENLABS_COST_TRACKING` via o MESMO `track_token_usage` (provider=elevenlabs); cada incremento envolto em `try/except` que LOGA em ERROR com contexto (job_id, user_id, content_id, provider) sem mascarar o caminho feliz; persistência de `audio_url` reusa o `db` recriado. (2) Handler `audio_generate_from_content` faz pre-check `await run_in_threadpool(svc.check_token_budget, user_id, client)` ANTES do `Thread.start()` — `AIServiceError` → HTTP 503; propaga `user_id=current_user["id"]` como último arg do Thread.
- `backend/tests/test_tts_budget.py` — NOVO. 8 testes cobrindo as 4 ACs (sucesso LLM+ElevenLabs flag-on, acumulação atômica, flag-off só LLM, podcast sem tracking, falha de tracking LLM e ElevenLabs logada não engolida, pre-check 503 sem thread, within-cap dispatcha thread com user_id propagado).
- `docs/stories/epic-ai/tkn-5.md` — status → Done, ACs/Tasks/DoD marcados, File List.

## Dev Agent Record
**Rótulo de provider (decisão de design):** a tabela `token_usage` tem somente `tokens_used` (int), sem coluna `provider`. Seguindo KISS e a diretiva da story, NÃO foi criada migração de schema. O char-equivalent ElevenLabs (`len(tts_input)`) é somado no MESMO contador diário `tokens_used` via o mesmo `track_token_usage`/`TokenUsageRepository` de TKN-3. A desambiguação `provider='llm'` vs `provider='elevenlabs'` vive exclusivamente no LOG estruturado (`logger.info`/`logger.error` com `provider=...`, `user_id=...`, `content_id=...`), não no schema. Os testes (c) verificam que a falha de tracking de cada etapa carrega o rótulo de provider correto no log.
