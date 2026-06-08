---
id: EPIC-PODCAST
title: Podcast/TTS Pipeline + Durable TTS Job Store
status: Draft
phases: [4]
story_count: 10
---
# EPIC-PODCAST: Podcast/TTS Pipeline + Durable TTS Job Store

## Objetivo

Restaurar a feature flagship de **podcast conversacional** e tornar o **TTS job store durável**, transformando o pipeline de áudio de "dump de texto cru truncado" em um diálogo de ~10 min real, persistido de forma autoritativa e resiliente a restart.

Hoje (`backend/routes_ai.py:523-646`) `_run_tts_job` só tem branches LLM para `summary` e `explanation` — **não existe branch `podcast`** (apesar de o valor ser válido no regex `^(podcast|summary|explanation)$` e exposto no botão `ChapterReader.tsx:34`). Para `podcast`, o `tts_input` permanece o `body` cru (HTML residual), incondicionalmente truncado por `tts_input = tts_input[:5000]`, sem nenhuma chamada LLM. O job ainda reporta `done`, mascarando o descasamento e tornando a promessa de "~10 min" impossível (~5000 chars ≈ 5 min).

O job store é um `dict` module-global (`_tts_jobs`) com lifecycle em `threading.Thread`, leitura **destrutiva** (`pop` no primeiro `done`/`error`), sem dono registrado (`audio_job_status` não checa propriedade — #60), recriando um cliente Supabase **por job** e **engolindo** a falha de persistência de `audio_url` em try/except que só loga warning (`done` fantasma + áudio órfão). Restart/redeploy descarta jobs em voo → 404 + ~90s de timeout no frontend.

Este Epic produz scripts de podcast conversacionais a partir do corpo **completo** do capítulo com chunking sentence-aware (matando o cap silencioso de 5000), persiste `audio_url` de forma autoritativa via cliente Supabase **compartilhado** e roteia o áudio via `StorageService`, mapeia áudio **por estilo** (corrigindo o reload summary-only), e migra o job store para uma tabela `tts_jobs` durável com ownership, TTL, dedup, cap de concorrência e pollers resilientes.

> **Flag-gated:** todo o pipeline novo vive atrás de `podcast_pipeline_enabled` (default false) e `tts_jobs_persisted_enabled` (default false) em `system_settings`, permitindo reverter sem redeploy no ambiente single-worker EasyPanel.

## Critérios de Saída (Exit Criteria)

1. **Script conversacional chunked** — `audio_type='podcast'` gera, via LLM, um script conversacional de ~10 min (≥1200 palavras) a partir do corpo **completo** do capítulo (HTML-stripped); `chunk_text` segmenta em pedaços ≤5000 chars **sentence-aware** sem perda; **nenhum** truncamento silencioso de 5000 chars sobrevive.
2. **MP3 único cobrindo narração completa** — capítulo >10k chars → **um único MP3 válido** que decodifica com duração ~= soma dos chunks, cobrindo a narração inteira; `summary`/`explanation` regression-pinned (sem regressão de comportamento).
3. **`audio_url` autoritativo** — falha de UPDATE após retries → job `error` (ou `persisted=false`), **nunca** `done` fantasma; sem cliente Supabase recriado por job (reuso do cliente compartilhado); frontend mostra **erro** (não success toast) se não persistido.
4. **Áudio via StorageService** — MP3 roteado pelo `StorageService` (object storage atrás de flag default-off + retenção local-FS com sweep TTL); `audio_url` é string estável que sobrevive a redeploy quando object storage ligado; reader lida com URL relativa/absoluta.
5. **Recarga por estilo** — podcast recarrega no **slot podcast** (não summary); múltiplos estilos (summary/explanation/podcast) **coexistem** sem sobrescrever; sem regressão para `audio_url` legado. **Inclui migração `contents.audio_type`** (gap do review, dono = POD-6).
6. **Job store durável + ownership** — TTS jobs **sobrevivem a restart** via tabela `tts_jobs` + fallback `contents.audio_url`; POST semeia row `processing` com `user_id`; status idempotente (2 polls iguais retornam o mesmo); acesso cross-user retorna **404** (ownership-enforced, dono de #60); **TTL sweep só em estados terminais** (`done`/`error`), nunca em `processing`.
7. **Dedup + cap de concorrência** — 2 submits do mesmo `(content_id, audio_type)` → **mesmo `job_id`, 1 síntese**; `audio_type` diferente NÃO é bloqueado; chamada travada abortada por **timeout** → job `error`; **cap de concorrência por user**.
8. **Pollers resilientes** — 1º poll em `t=0` (sem sleep inicial); budget nomeado maior (~5 min) alinhado ao pior caso; no timeout re-fetch de `content.audio_url` (sucesso se presente) e seta o **style correto**; **404 transiente** único no meio não colapsa o poll; 404 **persistente** → fallback `content.audio_url`; `setGeneratingTts(null)` no `finally`.

## Stories

| ID | Título | Fase | Terminal | Compl. | Depende de | Severidade |
|:--|:--|:--:|:--|:--:|:--|:--:|
| POD-1 | Branch de podcast + chunking sentence-aware (matar o cap silencioso de 5000) | 4 | Backend & Infra | med | — | HIGH |
| POD-2 | Wire chunk-and-concatenate em `_run_tts_job` e `tts_generate` sync | 4 | Backend & Infra | med | POD-1 | HIGH |
| POD-3 | Persistência de `audio_url` autoritativa + reuso do cliente Supabase compartilhado | 4 | Backend & Infra | low | POD-2 | HIGH |
| POD-4 | Timeouts + dedup por `(content_id, audio_type)` + cap de concorrência por user | 4 | Backend & Infra | med | POD-2 | HIGH |
| POD-5 | Rotear áudio via StorageService (object storage + retenção local-FS) | 4 | Backend & Infra | med | POD-3 | HIGH |
| POD-6 | Persistir/recuperar áudio por estilo (corrigir mapping summary-only no reload) | 4 | Backend & Infra | low | POD-3 | HIGH |
| TTSJOB-1 | Migração tabela `tts_jobs` durável + `TtsJobRepository` | 4 | Backend & Infra | low | — | HIGH |
| TTSJOB-2 | Persistir lifecycle do job no DB; parar pop destrutivo; enforçar ownership + TTL (dono de #60) | 4 | Backend & Infra | med | TTSJOB-1, POD-4 | HIGH |
| TTSJOB-3 | Poller TTS: poll imediato, budget maior, fallback `content.audio_url` no timeout | 4 | UX/UI & Design | low | TTSJOB-2 | HIGH |
| TTSJOB-4 | Poller TTS resiliente a 404 transiente / restart durante polling | 4 | UX/UI & Design | low | TTSJOB-3 | HIGH |

## Sequência / Caminho Crítico interno

Duas raízes paralelas que convergem em TTSJOB-2, depois drenam para o frontend:

```
POD-1 ──► POD-2 ──┬──► POD-3 ──┬──► POD-5
                  │            └──► POD-6
                  └──► POD-4 ──────────────┐
                                           ▼
TTSJOB-1 ─────────────────────────► TTSJOB-2 ──► TTSJOB-3 ──► TTSJOB-4
```

- **Raiz A (síntese — POD):** `POD-1 → POD-2 → {POD-3 → (POD-5 ∥ POD-6), POD-4}`. POD-1 (branch podcast + `chunk_text`) é o gargalo de entrada — sem ele POD-2 não tem o que concatenar. POD-3 (persistência autoritativa) é o fork que habilita POD-5 (StorageService) e POD-6 (mapping por estilo) em paralelo.
- **Raiz B (job store — TTSJOB):** `TTSJOB-1 → TTSJOB-2 → TTSJOB-3 → TTSJOB-4`. TTSJOB-1 (migração + repo) não tem dependência e pode começar imediatamente, em paralelo a POD-1.
- **Ponto de convergência crítico:** **TTSJOB-2** depende de **TTSJOB-1 E POD-4** — porque o lifecycle persistido no DB precisa do dedup/timeout/cap já estabelecidos no dict antes de migrar `dict → tabela`. TTSJOB-2 é o dono de #60 (ownership) e do corte do pop destrutivo.
- **Cauda frontend (UX/UI & Design):** TTSJOB-3 e TTSJOB-4 são sequenciais e só começam após TTSJOB-2 estabilizar o contrato de status (idempotência + fallback + 404 semântico). Coordenação cross-terminal obrigatória aqui.

**Ordem de execução recomendada:** `[POD-1 ∥ TTSJOB-1]` → `POD-2` → `[POD-3 ∥ POD-4]` → `[POD-5 ∥ POD-6 ∥ TTSJOB-2(após POD-4)]` → `TTSJOB-3` → `TTSJOB-4`.

## Notas de Arquitetura

### Hotspot coordenado — `routes_ai.py:523-646` (par ordenado POD → TTSJOB)
A região `_tts_jobs` / `_run_tts_job` / `audio_job_status` é **single-owner por fase**: **POD** é dono na fase de síntese (branch podcast, chunk-and-concatenate, persistência autoritativa, dedup/timeout/cap **sobre o dict**); depois **TTSJOB** re-home o estado `dict → tabela tts_jobs`. TTSJOB **re-home o dedup** introduzido por POD-4 para o repositório, e **TTSJOB-2 é o dono de #60** (ownership). Editar fora dessa ordem causa conflito de merge e perda de dedup. Não tocar a região em duas branches simultâneas — POD fecha primeiro, TTSJOB rebaseia.

### Gate de concorrência — ASYNC-AI-1 (dependência externa, fora deste Epic)
A migração para `AsyncOpenAI` (Fase 3, `async-llm-tts`) é o **gate de toda edição em `ai_service.py`**. O risco #1 do QA: o swap para `AsyncOpenAI` quebra os `.create()` **síncronos** dentro da thread de `_run_tts_job` se a thread não receber um cliente síncrono próprio (podcast/summary áudio quebra silenciosamente). As chamadas LLM dentro de `_run_tts_job` devem usar um cliente **síncrono** dedicado na thread (ou rodar via `run_in_threadpool` no caminho async), nunca o `AsyncOpenAI` compartilhado. Verificar este ponto antes de POD-1 mergear.

### Cliente Supabase compartilhado (POD-3) — não há RLS
O schema **não tem RLS**; o cliente Supabase é `service_role` e há **um único cliente compartilhado**. POD-3 deve **eliminar** o `from supabase import create_client; sb = create_client(...)` recriado por job (`routes_ai.py:582-588`) e reutilizar o cliente injetado / a `StorageService`. A persistência de `audio_url` precisa ser **autoritativa**: falha de UPDATE após retries vira job `error` (ou flag `persisted=false`), nunca `done` fantasma. Autorização é 100% camada de aplicação — TTSJOB-2 impõe ownership no nível da rota (404 cross-user), não via RLS.

### Roteamento de áudio — StorageService (POD-5)
POD-5 roteia o MP3 pelo `StorageService` em vez de gravar direto no `UPLOAD_DIR`. Object storage entregue **atrás de flag default-off** (#36 dormant aceitável em single-worker); durabilidade multi-réplica fica dormente até a flag ligar. Fallback local-FS + sweep TTL para crescimento ilimitado de disco. O `audio_url` permanece string; o reader lida com URL relativa e absoluta. Nota correlata: `delete_file` (#61) usa `lstrip` com char-set em vez de prefixo — se POD-5 tocar `storage_service.py`, corrigir para `removeprefix('/uploads/')` + guarda de traversal (resolve + assert dentro de `base_dir`).

### Migrações de DB — aditivas, idempotentes, antes do código
Convenção `supabase/migrations/YYYYMMDD_*.sql`, aplicadas **manualmente** no Supabase SQL Editor, **idempotentes** (`IF NOT EXISTS`, `ON CONFLICT`, `gen_random_uuid()::text`), **aditivas e antes do código consumidor**. **Sem novas políticas RLS** (no-op com client service_role — ADR SEC-CHAT-5). Duas migrações pertencem a este Epic:
- **MIGRATION F** `20260603f_tts_jobs.sql` — tabela `tts_jobs` (`id`, `content_id`, `user_id` NOT NULL FK, `audio_type` CHECK, `status`, `audio_url`, `error`, `duration_estimate`, `created_at`, `updated_at`; índices) — **dono TTSJOB-1**. `tts_jobs` é **forward-only** (sem backfill).
- **`contents.audio_type`** (mesma janela) — coluna que destrava o mapping por estilo — **dono POD-6**. Sem ela POD-6 não entrega (gap do review resolvido neste roadmap).

`TtsJobRepository` (TTSJOB-1) expõe `get_for_content` (dedup lookup) + `sweep_expired` (**só estados terminais `done`/`error`, nunca `processing`**) e deve ser **idempotente**.

### Feature flags (substrato `system_settings` existente)
- `podcast_pipeline_enabled` (default **false**) — gate do branch podcast + chunking (POD-*).
- `tts_jobs_persisted_enabled` (default **false**) — gate do job store durável (TTSJOB-*).

Ambos default-off para permitir merge incremental sem ativar comportamento de alto risco. Flip via `system_settings` reverte sem redeploy (realidade single-worker EasyPanel: cada deploy é swap de container com breve indisponibilidade).

### Realidade de deploy — single-worker EasyPanel
Um único worker uvicorn (sem `--workers`, sem replicas), `restart: unless-stopped`. O bug cross-worker do `_tts_jobs` **não se manifesta hoje**, mas restart/redeploy limpa jobs em voo → 404 + ~90s de timeout no frontend (o `audio_url` final É persistido em `contents.audio_url`, então o áudio não se perde — só o handshake de polling falha). Por isso o par TTSJOB-2 (persistência + fallback `contents.audio_url`) + TTSJOB-3/4 (pollers resilientes) é o que fecha o sintoma observável.

### Coordenação cross-terminal — frontend `ChapterReader.tsx`
`ChapterReader.tsx` é **single-owner = MEDIA-2** (remove `@ts-nocheck` primeiro); TPP-6, SF-1/2/3, **POD frontend (TTSJOB-3/4)** e CDC-8 **rebaseiam** sobre essa base. TTSJOB-3/4 vivem no terminal **UX/UI & Design** mas dependem do contrato de status estabilizado por TTSJOB-2 (Backend & Infra) — coordenação obrigatória entre os dois terminais antes de fechar a cauda. Migrações de DB e CI são **Backend & Infra**; `@devops` é exclusivo para push/PR/deploy/MCP.

### Defeitos verificados endereçados (BUG-SWEEP-2026-06-03)
#8 (podcast = dump cru, sem branch LLM), #33 (`tts_input[:5000]` silencioso), #34 (job store in-memory perde no restart), #35 (cliente Supabase per-job + falha de persistência engolida → `done` fantasma), #36 (MP3 local sem retention/cleanup), #37/#39 (sem timeout na thread + poller desiste em 90s), #38 (poll com sleep inicial + budget 90s curto), #58 (pop destrutivo no primeiro `done`/`error`), #59 (jobs órfãos vazam no dict), #60 (`audio_job_status` sem ownership check), #61 (`delete_file` `lstrip` char-set — correlato, se POD-5 tocar `storage_service.py`), e o mapping summary-only no reload (`ChapterReader.tsx:219-224`).
