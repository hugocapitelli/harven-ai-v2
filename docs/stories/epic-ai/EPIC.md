---
id: EPIC-AI
title: AI Concurrency, Session Truth, LLM Contract Hardening & Token Budget
status: Draft
phases: [3, 4]
story_count: 23
---
# EPIC-AI: AI Concurrency, Session Truth, LLM Contract Hardening & Token Budget

## Objetivo

Tornar a camada de IA do tutor Harven correta sob concorrência, fiel ao servidor como fonte de verdade do diálogo, e resiliente a saídas malformadas do modelo — sem nunca crashar nem falhar de forma permissiva (fail-open).

Quatro frentes, distribuídas em duas fases:

- **Fase 3 — Concorrência & verdade de sessão (`async-llm-tts` gate + `tutor-persistence-pacing` keystone):**
  - Descongelar o event loop: migrar para `AsyncOpenAI` (ou `run_in_threadpool`) todas as chamadas LLM/TTS/Whisper hoje síncronas e bloqueantes (`ai_service.py`, ElevenLabs `convert()`, Whisper `transcriptions.create`, `reprocess_content`), num deploy de 1 worker uvicorn = 1 event loop.
  - Backend como fonte de verdade do diálogo socrático: persistir **ambos** os turnos (aluno + assistente) server-side, mais o opener do `startChat`, e derivar `interactions_remaining`/`is_final_interaction` da contagem persistida — não do campo do cliente.
  - Eliminar a race do create-or-get: `UNIQUE(user_id, content_id)` em `chat_sessions` + upsert/ON CONFLICT, com `TPP-2` como **dono único da rota** `create_or_get_chat_session`.

- **Fase 4 — Endurecimento de contrato LLM & durabilidade de budget (`ai-llm-contract-hardening` + `token-budget-durability`):**
  - Validar/coagir toda saída do modelo via modelos Pydantic de contrato (`AIDetectionResult`, `TesterVerdict`); `detect_ai_content` e `validate_response` nunca crasham nem fabricam veredito permissivo (sem `APPROVED` de erro, sem `0.3` silencioso).
  - Hardening de `_call_openai`: guards de `empty-choices` e `empty-content`; fidelidade de prompt/contexto (contexto único, turno cru, trim de histórico, matar `__INIT__`); surfaçar estado degraded/mock em vez de impersonar o tutor.
  - Tornar o budget de tokens durável: persistir atomicamente em Postgres (tabela `token_usage` já existente), remover o cache in-memory per-process, sobreviver a restart, e rastrear o gasto LLM+ElevenLabs do TTS com pre-check.

> **Gate duro (programa):** `ASYNC-AI` não tem dependências e **deve mergear primeiro**. Nenhuma edição no corpo de `ai_service.py` (`_call_openai`, `socratic_dialogue`, `detect_ai_content`, `edit_response`, `validate_response`) pode mergear antes do flip de assinatura de `ASYNC-AI-1`. Isso vincula a Fase 4 (hardening, token budget), `TPP-3/7` e o gamification-helper.

## Critérios de Saída (Exit Criteria)

- Todas as chamadas LLM/TTS/Whisper não-bloqueantes (`AsyncOpenAI` com `timeout` em non-mock, ou `run_in_threadpool` no closure ElevenLabs/Whisper); os 5 call sites de `_call_openai` em `await`; `reprocess_content` migrado; `_run_tts_job` (thread) recebe seu próprio cliente OpenAI **síncrono** (acoplamento crítico preservado).
- `/health` responde **<250ms** durante 2 diálogos lentos concorrentes e sob TTS/transcribe bloqueante.
- `/socrates/dialogue` persiste server-side o turno do aluno + o turno do assistente + o opener do `startChat`; `GET messages` e export incluem o turno do assistente.
- Pacing derivado server-side: `interactions_remaining`/`is_final_interaction`/`should_finalize` calculados da contagem persistida e **resistem a campo do cliente forjado**; a síntese de fechamento é alcançável numa sessão de 20 turnos.
- `chat_sessions` race-free: `UNIQUE(user_id, content_id)` (parcial WHERE content_id NOT NULL) + upsert/ON CONFLICT; create-or-get concorrente → 1 sessão, nunca 500; `body.user_id` ignorado; sessão `completed` não reabre.
- `detect_ai_content`/`validate_response` nunca crasham (sem TypeError/IndexError → 500) nem fazem fail-open: probability validada/clampada para `[0,1]`, verdict/confidence restritos ao enum; JSON malformado/exceção de transporte → `NEEDS_REVISION` + `degraded` (nunca `APPROVED` fabricado nem `0.3` silencioso).
- `_call_openai` resiliente: `choices=[]` → `AIServiceError` (não IndexError) nos 5 métodos; conteúdo vazio → retry + fallback socrático; estado degraded/mock surfaceado (`degraded:true`/`mock:true`), nunca impersonando o tutor.
- Budget de tokens persistido em Postgres (sem cache in-memory), com incremento atômico (ON CONFLICT), sobrevivendo a restart; budget ligado em editor/tester/analyst (metade-budget); gasto LLM+ElevenLabs do TTS rastreado com pre-check de budget antes da thread.

## Stories

| ID | Título | Fase | Terminal | Compl. | Depende de | Severidade |
|:--|:--|:--:|:--|:--:|:--|:--:|
| ASYNC-AI-1 | Migrar OpenAI para AsyncOpenAI (descongelar o event loop) | 3 | Backend & Infra | med | — | CRITICAL |
| ASYNC-AI-2 | Offload ElevenLabs TTS + Whisper do event loop | 3 | Backend & Infra | low | ASYNC-AI-1 | CRITICAL |
| ASYNC-AI-3 | Harness de teste async + testes de regressão de concorrência | 3 | Backend & Infra | med | — | CRITICAL |
| TPP-1 | Schema: UNIQUE(user_id,content_id) + RPCs de count atômico e upsert | 3 | Backend & Infra | med | — | CRITICAL |
| TPP-2 | create-or-get-session race-free (upsert + ignora body.user_id) — dono único da rota | 3 | Backend & Infra | med | TPP-1, SEC-AUTHZ-0 | CRITICAL |
| TPP-3 | Centralizar persistência + count atômico em chat_repo | 3 | Backend & Infra | med | TPP-1, ASYNC-AI-1 | CRITICAL |
| TPP-4 | Tipar initial_question + persistir ambos os turnos server-side | 3 | Backend & Infra | high | TPP-2, TPP-3, SEC-AUTHZ-0 | CRITICAL |
| TPP-5 | Derivação server-side de interactions_remaining + finalização | 3 | Backend & Infra | med | TPP-4 | CRITICAL |
| TPP-6 | Frontend: consumir pacing do servidor + parar de duplo-persistir turno do aluno | 3 | UX/UI & Design | med | TPP-4, TPP-5, MEDIA-2 | CRITICAL |
| TPP-7 | Encadear gate Editor→Tester atrás de flag | 3 | Backend & Infra | high | TPP-4, ASYNC-AI-1 | CRITICAL |
| AI-HARD-0 | Scaffold de teste + modelos Pydantic de contrato (AIDetectionResult, TesterVerdict) | 4 | Backend & Infra | low | — | HIGH |
| AI-HARD-1 | Detector contract hardening: probability validada + fallback heurístico | 4 | Backend & Infra | med | AI-HARD-0 | HIGH |
| AI-HARD-2 | Remover fail-open do Tester: nunca fabricar APPROVED | 4 | Backend & Infra | low | AI-HARD-0 | HIGH |
| AI-HARD-3 | Qualidade do detector heurístico: density-weighting + remover conectores PT-BR neutros | 4 | Backend & Infra | med | AI-HARD-0 | HIGH |
| AI-HARD-4 | Resiliência de _call_openai: guards empty-choices + empty-content | 4 | Backend & Infra | med | AI-HARD-0, ASYNC-AI-1 | HIGH |
| AI-HARD-5 | Fidelidade de prompt/contexto: contexto único, turno cru, trim de histórico, matar __INIT__ | 4 | Backend & Infra | med | AI-HARD-0, ASYNC-AI-1 | HIGH |
| AI-HARD-6 | Cap de contexto de referência + seam de retrieval | 4 | Backend & Infra | low | AI-HARD-5 | HIGH |
| AI-HARD-7 | Surfacear estado degraded/mock (não impersonar tutor) | 4 | Backend & Infra | low | AI-HARD-4 | HIGH |
| TKN-1 | Função Postgres atômica de incremento + índice (migração) | 4 | Backend & Infra | low | — | HIGH |
| TKN-2 | TokenUsageRepository sobre a tabela existente token_usage | 4 | Backend & Infra | low | TKN-1 | HIGH |
| TKN-3 | Persistir budget no AIService check/track + remover cache in-memory | 4 | Backend & Infra | med | TKN-2, ASYNC-AI-1 | HIGH |
| TKN-4 | Ligar budget em editor/tester/analyst (metade-budget de #12) | 4 | Backend & Infra | med | TKN-3 | HIGH |
| TKN-5 | Rastrear gasto LLM+ElevenLabs do TTS + pre-check de budget | 4 | Backend & Infra | med | TKN-3, ASYNC-AI-1 | HIGH |

## Sequência / Caminho Crítico interno

**Gate de tudo:** `ASYNC-AI-1` (flip de assinatura) precede toda edição no corpo de `ai_service.py`. `ASYNC-AI-2` segue `ASYNC-AI-1`; `ASYNC-AI-3` (harness) pode rodar em paralelo (sem deps) e é o que prova o fix de concorrência (#1).

**Keystone (cadeia mais longa do epic):**
```
TPP-1 → TPP-2 → TPP-4 → TPP-5 → TPP-6 (frontend)
   ‖        (TPP-3 entra em TPP-4, requer ASYNC-AI-1)
TPP-1 → TPP-3 → TPP-4
ASYNC-AI-1 ─┘            └→ TPP-7 (atrás de flag)
```
- `TPP-1` (schema/migração) destrava `TPP-2` e `TPP-3` em paralelo.
- `TPP-2` (dono único da rota create-or-get) + `TPP-3` (chat_repo, count atômico) convergem em `TPP-4` (persistir ambos os turnos) — o nó de maior complexidade (high).
- `TPP-5` (derivação server-side) depende de `TPP-4`; `TPP-6` (frontend) depende de `TPP-4/5` **e** de `MEDIA-2` (remove `@ts-nocheck` de `ChapterReader.tsx`).
- `TPP-7` (gate Editor→Tester atrás de flag) depende de `TPP-4` + `ASYNC-AI-1`.
- Dependências externas ao epic: `SEC-AUTHZ-0` (módulo `authz.py`) é pré-requisito de `TPP-2` e `TPP-4`.

**Fase 4 — hardening:**
```
AI-HARD-0 (scaffold + contratos Pydantic) → { AI-HARD-1, AI-HARD-2, AI-HARD-3 }
AI-HARD-0 + ASYNC-AI-1 → AI-HARD-4 → AI-HARD-7
AI-HARD-0 + ASYNC-AI-1 → AI-HARD-5 → AI-HARD-6
```
`AI-HARD-0` é o nó-raiz (contratos `AIDetectionResult`/`TesterVerdict`); 1/2/3 ramificam dele; 4 e 5 exigem também `ASYNC-AI-1` (tocam `_call_openai`); 6 segue 5; 7 segue 4.

**Fase 4 — token budget:**
```
TKN-1 → TKN-2 → TKN-3 → { TKN-4, TKN-5 }
                  ‖ ASYNC-AI-1 (para TKN-3 e TKN-5)
```
`TKN-3` (persistir + remover cache) é o nó central — exige `TKN-2` + `ASYNC-AI-1`; `TKN-4` (editor/tester/analyst) e `TKN-5` (TTS LLM+ElevenLabs) ramificam dele (`TKN-5` também toca `_call_openai`, requer `ASYNC-AI-1`).

**Caminho crítico do epic:** `ASYNC-AI-1` ‖ `(TPP-1 → TPP-2/TPP-3 → TPP-4 → TPP-5 → TPP-6)`. Deslize em `TPP-4` cascateia para `DATA-GAM-3`, `INT-MOODLE-4` e o frontend.

## Notas de Arquitetura

**Single-owner por região de arquivo (coordenação de conflito):**
- `ai_service.py` corpo dos 5 métodos (`_call_openai`, `socratic_dialogue`, `detect_ai_content`, `edit_response`, `validate_response`) → **`ASYNC-AI` faz o flip de assinatura primeiro**; `AI-HARD`, `TPP-7`, `TKN` e `DATA-GAM-3` editam **sobre** a versão async. Sem exceção a esse ordem.
- `routes_ai.py:776-810` (`create_or_get_chat_session`) → **dono único = `TPP-2`** (rewrite com upsert/ON CONFLICT, ignora `body.user_id`). `SEC-CHAT-2/3` e `DATA-GAM-4` **adicionam** hooks sobre o resultado, não reescrevem.
- `routes_ai.py:914-931` (`complete_chat_session`) → **shape dirigido por `TPP`**; `SEC-CHAT-3`, `DATA-GAM-3/4`, `INT-MOODLE-4` aplicam hooks aditivos.
- `ChapterReader.tsx` → **`MEDIA-2` remove `@ts-nocheck` primeiro**; `TPP-6` (e SF-1/2/3, POD frontend, CDC-8) rebaseiam por cima. É por isso que `TPP-6` depende de `MEDIA-2`.

**Decisão de concorrência (gate `async-llm-tts`):** deploy roda 1 worker uvicorn (`Dockerfile:12`, sem `--workers`) = 1 event loop. Chamadas síncronas (`OpenAI`, ElevenLabs `convert()`, Whisper) congelam `/health` e todos os requests concorrentes. Correção: `AsyncOpenAI(timeout=...)` no path non-mock + `await` nos 5 call sites; ElevenLabs/Whisper via `run_in_threadpool` (convert + join no closure). **Acoplamento crítico:** `_run_tts_job` roda numa thread separada e DEVE receber seu próprio cliente OpenAI **síncrono** — não compartilhar o `AsyncOpenAI` do event loop. `elevenlabs` pinado; timeout → 502/504; contratos de resposta inalterados. Fonte: BUG-SWEEP #1 (`ai_service.py`, `routes_ai.py`).

**Verdade de sessão server-side (keystone `tutor-persistence-pacing`):** hoje `socratic_dialogue` deriva `is_final_interaction`/`should_finalize` puramente do argumento `interactions_remaining` (default 3 do cliente, enviado só no 1º turno) e nunca persiste — a síntese de fim NUNCA dispara numa sessão de 20 turnos (BUG-SWEEP #26/#43/#57). Correção: persistir ambos os turnos via `chat_repo.persist_turn` (insere 1 row + incrementa contador atomicamente; incrementador único, sem duplo-count); `count_user_messages`; derivar pacing do count persistido; `should_finalize` só em `used >= MAX-1`. `initial_question` passa de `dict` sem schema para BaseModel com `text` requerido (faltando → 422) — BUG-SWEEP #46. Frontend para de chamar `addMessage('user')` (evita duplo-persistir) e consome `session_status`/`should_finalize` do servidor.

**Ordem de migrações (manuais, idempotentes, aditivas, antes do código; convenção `supabase/migrations/YYYYMMDD_*.sql`):**
1. **MIGRATION A** `20260603a_dedupe_backfill.sql` — dedup `(user_id,content_id)` em `chat_sessions` (keeper = mais mensagens, tiebreak `created_at`; reparenta `chat_messages`/`session_reviews`/`moodle_ratings`, deleta perdedoras). Verificar `GROUP BY ... HAVING count(*)>1 = 0` antes de prosseguir.
2. **MIGRATION B** `20260603b_unique_constraints.sql` (após A limpo) — `UNIQUE(user_id, content_id)` em `chat_sessions` (parcial `WHERE content_id NOT NULL`, `CREATE UNIQUE INDEX CONCURRENTLY`) + RPCs `increment_chat_session_messages` e `upsert_chat_session` (TPP-1).
3. **MIGRATION C** `20260603c_feature_flags.sql` — kill-switches em `system_settings`: `persist_tutor_turns_enabled` (false), `editor_tester_chain_enabled` (false) [além das demais do programa]. Freio existente `ai_tutor_enabled` serve como emergência durante a Fase 3.
4. **MIGRATION E** `20260603e_message_sequence.sql` — `chat_messages.sequence BIGINT` + backfill via `row_number() over (partition by session_id order by created_at, id)` (TPP-4).
5. **Token budget (mesma janela):** RPC atômico `increment_token_usage` (ON CONFLICT) + índice `(user_id, usage_date)` sobre a tabela **já existente** `token_usage` (`UNIQUE(user_id,usage_date)`) — TKN-1. **Sem migração de criação**: a tabela e o modelo `TokenUsage` (`models/integration.py:45-56`) existem mas nunca foram usados.

**Contratos Pydantic & fail-safe (cluster `ai-llm-contract-hardening`):**
- `AI-HARD-0` define `AIDetectionResult` e `TesterVerdict`: coerção (`'0.8'→0.8`), clamp (`1.5→1.0`), verdict fora do enum → `ValidationError`, `_parse_model_json` retorna `None` (não raise) em JSON inválido. As linhas que hoje usam `probability` verbatim (`ai_service.py:485-498, 504`) estão FORA do try/except — um `TypeError`/`None > 0.70` vira HTTP 500 (BUG-SWEEP #30). Correção move validação para dentro do contrato + heurística como fallback (não `0.3` silencioso).
- `validate_response` (Tester) usa hoje `except (json.JSONDecodeError, Exception)` retornando `{verdict: APPROVED, score: 0.80}` fabricado (BUG-SWEEP #32, `ai_service.py:615-633`) — fail-open. `AI-HARD-2`: parse/transporte → `NEEDS_REVISION` + `degraded` + log ERROR; `APPROVED` só com payload bem-formado; MOCK_MODE carrega `mock:true`.
- `_call_openai` assume `response.choices[0]` (BUG-SWEEP #55, `ai_service.py:257`) e retorna conteúdo possivelmente vazio (#56, `ai_service.py:404-410`). `AI-HARD-4`: `choices=[]` → `AIServiceError` nos 5 métodos; vazio → 1 retry + fallback socrático; nunca bolha em branco.
- Fidelidade de prompt (BUG-SWEEP #28/#57, `ai_service.py:387-402`): contexto re-embrulhado a cada turno enquanto o histórico é cru; branch `__INIT__` é código morto. `AI-HARD-5`: contexto 1× no system msg, turno do aluno cru, histórico ≤K turnos, matar `__INIT__`. `AI-HARD-6`: cap de contexto de referência 4000→15000 chars via `_select_reference_context` (BUG-SWEEP #27), com seam de retrieval (sem magic number).
- Estado degraded/mock (BUG-SWEEP #31, `ai_service.py:422-424, 593-604`): fallback canned impersona o tutor. `AI-HARD-7`: respostas mock/empty/unavailable carregam `degraded:true`+reason; `edit_response` mock com `mock:true`; WARN ao servir mock; aditivo (frontend não afetado).

**Durabilidade de budget (cluster `token-budget-durability`):** `_user_token_cache` é dict module-level perdido no restart; `db=` é aceito mas ignorado apesar da tabela `TokenUsage` existir; budget de editor/tester/analyst/TTS não rastreado (BUG-SWEEP #12, `ai_service.py:174, 207-221`). Correção: `TokenUsageRepository` estilo `BaseRepository` sobre a tabela existente (`get_today_usage`→0 se ausente, `add_usage` via RPC retorna novo total); `AIService.check/track` persiste no DB (check **fail-open só em erro de leitura**, track best-effort); editor/tester/analyst enforçam metade-budget no path real (usuário sobre cap → 503); TTS incrementa o ledger do iniciador (char-equivalent ElevenLabs rotulado/atrás de flag) com pre-check antes da thread.

**Testes & CI (gate BLOCKING):** harness async com `pytest-asyncio` + fake `AsyncOpenAI` configurável (nunca chama API real; network-deny fixture). O teste de concorrência (#1) **falha no código pré-fix e passa no fix** e cobre os 5 métodos (live-fake + MOCK_MODE) + o acoplamento sync-client de `_run_tts_job`. CI exige: não-bloqueante (#1) + persistência de ambos os turnos (#6) + pacing derivado server-side (#26/#43) + fail-safe detector/validator (#30/#31/#32/#55/#56) + conectores PT-BR não flagados (#29) verdes; `diff-cover ≥80%` em `ai_service.py` e nos handlers de chat/session de `routes_ai.py`.
