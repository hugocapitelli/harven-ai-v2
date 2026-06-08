<!-- Gerado por J.A.R.V.I.S. — arquitetura de remediação 2026-06-03 · 23 agentes · 6 epics · 108 stories · 5 fases -->

# Roadmap Mestre de Remediação — Plataforma Tutor Harven.AI

> Backend: `harven-ai-v2/backend`
> Frontend: `harven-ai-v2/frontend`
> Documento executável como Epics + Stories (vocabulário SDC). IDs de Story foram **renomeados/namespaced por Epic** para eliminar as colisões de ID detectadas no review (vários clusters reusavam `SEC-1`, `AI-1`, `TTS-1`).

---

## 1. Sumário Executivo

A remediação ataca um sistema com **uma única barreira de autorização (a camada de aplicação — não há RLS, o cliente Supabase é `service_role`)**, um **event loop único** congelado por chamadas LLM/TTS síncronas, e features pedagógicas quebradas de ponta a ponta (podcast, extração de arquivos, render de mídia, export Moodle, fluxo do aluno). A estratégia é **incremental, security-first e test-guarded**: primeiro neutralizar os vetores de account-takeover triviais (token de reset vazado, segredo JWT default forjável), depois fechar a superfície sistêmica de IDOR/role-gates, em seguida destravar a concorrência (LLM assíncrono) e tornar o backend a fonte de verdade do diálogo socrático, depois restaurar features pedagógicas e integridade de dados, e por fim limpar contratos mortos e higiene de config. Tudo respeita a realidade **single-worker EasyPanel** (cada deploy é um swap de container com breve indisponibilidade; migrações são manuais, aditivas e aplicadas **antes** do código que as consome), com **kill-switches em `system_settings`** para reverter comportamento de alto risco sem redeploy.

| Fase | Nome | Foco | Epics | Stories | Severidade máx. |
|:--|:--|:--|:--|:--:|:--:|
| **0** | Pre-flight | Snapshot DB, verificação de env, tag de imagem | — | 0 | — |
| **1** | Account-Takeover Hotfix | Credenciais forjáveis/vazadas | EPIC-SEC (parcial) | 3 | CRITICAL |
| **2** | Authorization Foundation | IDOR + role gates + teacher scoping + force-logout | EPIC-SEC | 31 | CRITICAL |
| **3** | AI Concurrency & Session Truth | LLM não-bloqueante + persistência server-side do tutor | EPIC-AI (parcial) | 10 | CRITICAL |
| **4** | AI/Podcast/File & Data Integrity | Podcast/TTS, extração de arquivos, mídia, Moodle, gamificação, LLM hardening, token budget, fluxo aluno | EPIC-PODCAST, EPIC-FILES, EPIC-DATA, EPIC-AI (resto), EPIC-FRONT | 51 | CRITICAL→HIGH |
| **5** | Contracts, Config & Cleanup | Contratos mortos, config hygiene, correções LOW | EPIC-CLEANUP | 13 | MEDIUM |

**Total: 5 fases · 6 Epics · 108 stories.**

---

## 2. Princípios de Remediação

1. **Incremental & shippable** — cada Story entrega seu fix + seu teste de regressão (falha-antes/passa-depois) ou não faz merge. Nada de big-bang.
2. **Security-first** — a camada de aplicação é a **única** barreira (sem RLS). Toda Story de IDOR prova 3 desfechos: dono autorizado passa; ator cruzado recebe 403/404 **e nenhuma leitura/mutação ocorre**; `body.user_id` nunca é confiado como identidade.
3. **Test-guarded** — o ecossistema **não tem testes hoje** (zero pytest/vitest/CI). A Suíte de Regressão de Segurança é blocking no CI; uma Story que pula seu teste não passa o QA Gate.
4. **Realidade single-worker** — Dockerfile sem `--workers` (um event loop), `restart: unless-stopped`, `env_file: .env` (env vars têm precedência sobre `.env` — raiz do bug #22), bind-mount `./uploads` persiste entre restarts. Cada deploy é uma indisponibilidade breve; **migrações aditivas vão antes do código**.
5. **App-layer-authz agora → RLS depois** — RLS hoje seria no-op (cliente `service_role` compartilhado). Os helpers de ownership na camada de app são o hotfix shippable; a migração para client por-request-JWT + políticas RLS é defense-in-depth documentada em ADR, **fora de escopo** deste roadmap.

---

## 3. Roadmap por Fase

### FASE 0 — Pre-flight (sem deploy)

**Goal:** garantir reversibilidade antes de qualquer mudança.
**Exit criteria:** snapshot do Supabase restaurável validado; SHA da imagem atual tagueado no EasyPanel para rollback instantâneo; `printenv` no container confirma `SUPABASE_KEY` + `JWT_SECRET_KEY` setados com segredo ≥32 chars (NÃO `change-me-in-production`, NÃO os nomes errados do `.env.example`).

> **Gate duro:** o guard de boot fail-closed da Fase 1 recusa subir se o env estiver mal-setado. A verificação de env da Fase 0 é pré-condição obrigatória.

---

### FASE 1 — Account-Takeover Hotfix · **EPIC-SEC** (parcial)

**Goal:** eliminar os vetores de takeover triviais e de maior blast-radius. Edits minúsculos, near-zero structural risk.
**Exit criteria:** token de reset nunca sai do servidor (sem body, sem log); backend recusa boot em produção com `JWT_SECRET_KEY` vazio/default/<32 chars; `.env.example` (raiz + backend) usam os nomes reais (`SUPABASE_KEY`, `JWT_SECRET_KEY`); token assinado com o default não valida.

**Cluster:** `account-takeover-hotfix` → **Backend & Infra**.

| Story | Título | Terminal | Compl. | Depende de | AC chave |
|:--|:--|:--|:--:|:--|:--|
| **SEC-ATO-1** | Reconciliar nomes de variáveis nos dois `.env.example` | Backend & Infra | low | — | Ambos usam `SUPABASE_KEY` e `JWT_SECRET_KEY` exatamente como em `config.py:12/15` e `database.py:6`; zero referência a `SUPABASE_ANON_KEY`/`SUPABASE_SERVICE_ROLE_KEY`/`JWT_SECRET`/`DATABASE_URL`; comentário documentando ≥32 chars e boot-guard. Docs-only. |
| **SEC-ATO-2** | Guard fail-closed para `JWT_SECRET_KEY` | Backend & Infra | low | SEC-ATO-1 | Em `ENVIRONMENT=production`, blacklist `{'', 'change-me-in-production', 'your-secret-key-here'}` ou <32 chars → `RuntimeError` no boot; segredo forte → boot normal; token forjado com default → 401; non-prod loga WARNING; aceita qualquer segredo forte (não quebra `force_logout`). |
| **SEC-ATO-3** | Parar de vazar o token de reset no body e nos logs | Backend & Infra | low | — | `POST /auth/request-reset` retorna 200 sem chave `token` (existente e inexistente, mensagem idêntica, anti-enumeração); token nunca em logs; `RESET_TOKEN_DEBUG` só em dev. |

**DoD da fase:** testes em `backend/tests/test_security_hotfix.py` (validador, boot fail-closed, forja JWT rejeitada, ausência do token no body/log) verdes; **@devops confirma `JWT_SECRET_KEY` forte no `.env` de produção e valida boot em staging antes do deploy.** Pre-deploy checklist obrigatório (guard é fail-closed: deploy recusará boot se env estiver fraco).

> **Conflito de arquivo (review):** `SEC-ATO-3` mexe no bloco de reset-token em `main.py:404-477`. A Story `CFG-3` (Fase 5) substitui o dict in-memory pela tabela `password_resets` (hash/single-use/rate-limit) — `CFG-3` **rebaseia sobre SEC-ATO-3 e não pode reintroduzir o leak**. A tabela `password_resets` já existe (migração `20260519`).

---

### FASE 2 — Authorization Foundation · **EPIC-SEC**

**Goal:** fechar a superfície sistêmica de IDOR/role-gates em chat-sessions, notificações, gamificação, gradebook/grade override, discipline stats, reviews, avatar, AI-authoring, status/cost/integration-status, webhook/LTI. Tornar ownership (`.eq user_id` / load-and-compare) + `require_role` o padrão uniforme; teacher-scoping por disciplina.
**Exit criteria:** todo endpoint que aceita `session_id`/`user_id`/`notification_id`/`discipline_id`/`job_id` filtra por `current_user["id"]` ou carrega a linha e compara ownership (com override TEACHER/ADMIN); `body.user_id` nunca é o ator; AI-authoring + estimate-cost + integrations/status são role-gated; gradebook/stats de professor escopados às disciplinas próprias; tentativas cross-user retornam 403/404.

**Clusters:** `idor-chat-sessions`, `idor-admin-writes`, `teacher-scoping-and-readgates`, `force-logout-secret-rotation` → todos **Backend & Infra**.

#### 2.0 — Fundação compartilhada (decisão de arquitetura, do review)

> **DECISÃO RECONCILIADA (resolve 3 conflitos do review):**
> - **Módulo único de authz:** criar `backend/authz.py` como **lar canônico** de TODOS os helpers de ownership/role: `load_session_or_404`, `assert_owner_or_role`, `assert_self_or_role`, `require_self_or_role`, `assert_notification_owner`, `assert_teacher_owns_discipline`. `idor-admin-writes` e `teacher-scoping` **consomem** daqui, não recriam em `auth.py`. (`auth.py` mantém só `get_current_user`/`require_role`.)
> - **`audio_job_status` ownership (#60):** removido do escopo de `idor-chat-sessions`; é de propriedade exclusiva de `tts-job-store-lifecycle` (Fase 4), que detém o shape final de storage do job.
> - **`conftest.py`:** criado **uma vez** por `SEC-ATO` (Fase 1, primeiro a tocar `backend/tests/`); é o dono da fixture `FakeSupabaseClient`. Todas as demais Stories de teste a importam.

| Story | Título | Terminal | Compl. | Depende de | AC chave |
|:--|:--|:--|:--:|:--|:--|
| **SEC-AUTHZ-0** | Módulo `authz.py` + harness de teste IDOR | Backend & Infra | low | EPIC-SEC Fase 1 | `assert_owner_or_role` permite dono e ADMIN/TEACHER/INSTRUCTOR, 403 para STUDENT estranho; `load_session_or_404` 404 em row nula; helpers sem acoplamento a `Depends`; fake Supabase client (chained builder) sem DB real. |

#### 2.1 — IDOR chat-sessions (`idor-chat-sessions`) — `routes_ai.py`

| Story | Título | Terminal | Compl. | Depende de | AC chave |
|:--|:--|:--|:--:|:--|:--|
| **SEC-CHAT-1** | Ownership em endpoints de leitura (get_chat_session, get_session_messages, get_user_chat_sessions, export_session_moodle) | Backend & Infra | med | SEC-AUTHZ-0 | STUDENT estranho → 403; dono e TEACHER/ADMIN/INSTRUCTOR → ok; export não vaza name/email de sessão estranha (gate antes do enrichment); `assert_self_or_role` na listagem por user. |
| **SEC-CHAT-2** | Ownership + remover spoof de `user_id` (create_or_get, add_session_message) | Backend & Infra | med | SEC-AUTHZ-0 | create_or_get ignora `body.user_id` (sessão sempre do autenticado); add_session_message rejeita injeção em sessão estranha (403); instrutor (`role:'instructor'`) ainda adiciona; contador inalterado (#40 fora de escopo). |
| **SEC-CHAT-3** | `complete_chat_session` idempotente + ownership; create_or_get não reativa `completed` | Backend & Infra | low | SEC-AUTHZ-0, SEC-CHAT-2 | STUDENT estranho não completa (403); 2º `/complete` em sessão completed → 200 no-op; reabrir capítulo completed não reativa. |
| **SEC-CHAT-4** | Gate organizer/session + prepare-export; derivar ator da sessão (não do body) | Backend & Infra | med | SEC-AUTHZ-0 | prepare-export com session_id estranho → 403 sem vazar PII; `user_id` populado de `session.user_id`, nunca do body. |
| **SEC-CHAT-5** | ADR plano de migração RLS (doc only) | Backend & Infra | low | SEC-AUTHZ-0 | ADR explica por que RLS hoje é no-op (client service_role); lista tabelas-alvo + caminho client-por-request-JWT; marca helpers como hotfix shipped. |

#### 2.2 — IDOR admin writes (`idor-admin-writes`) — `routes_admin.py` + `main.py`

| Story | Título | Terminal | Compl. | Depende de | AC chave |
|:--|:--|:--|:--:|:--|:--|
| **SEC-ADMIN-1** | Bootstrap harness de teste backend (pytest + TestClient + fake Supabase) — **consome conftest de SEC-ATO** | Backend & Infra | med | — | pytest descobre `tests/`; fake suporta chained builder; seed de 2 students/1 teacher/1 admin + chat_sessions/notifications/reviews/course_progress; sem rede/DB real. |
| **SEC-ADMIN-2** | IDOR de avatar (`main.py` #49) | Backend & Infra | low | SEC-AUTHZ-0, SEC-ADMIN-1 | Student em outro user_id → 403; próprio → 200; ADMIN qualquer → 200; AccountSettings self-upload intacto. |
| **SEC-ADMIN-3** | IDOR notificações + criação só ADMIN (#16, #62) | Backend & Infra | med | SEC-AUTHZ-0, SEC-ADMIN-1 | read/count/mark-all/mark/delete cross-user → 403; missing → 404; create → 403 STUDENT / 201 ADMIN; Layout (próprio) e AdminConsole (admin) intactos. |
| **SEC-ADMIN-4** | IDOR gamificação + integrity (#14) | Backend & Infra | med | SEC-AUTHZ-0, SEC-ADMIN-1 | writes cross-user → 403; `ActivityCreate.points` derivado de whitelist por `activity_type` (cliente ignorado); `issue_certificate` 403 se `progress_percent<100` (não-admin) / 201 se ≥100 ou ADMIN/TEACHER; `complete_content` usa o mesmo mapa de points (sem hardcode 10). |
| **SEC-ADMIN-5** | Authz session-review (#25) | Backend & Infra | med | SEC-AUTHZ-0, SEC-ADMIN-1 | reply só dono da sessão; create/update só TEACHER/ADMIN; get → dono ou TEACHER/ADMIN; SessionReview (TEACHER) intacto; reviewer_id correto. |
| **SEC-ADMIN-6** | Guard de regressão IDOR + meta signature check | Backend & Infra | low | SEC-ADMIN-2..5 | meta-test falha se algum handler in-scope mantém `get_current_user` sem comparação (`_user` anti-pattern); happy-path dos 4 callers reais; roda no CI. |

#### 2.3 — Teacher scoping + read gates (`teacher-scoping-and-readgates`) — `routes_ai.py` + `routes_admin.py` + `integration_service.py`

| Story | Título | Terminal | Compl. | Depende de | AC chave |
|:--|:--|:--|:--:|:--|:--|
| **SEC-SCOPE-1** | Helper teacher→disciplina + role gates em stats/sessions (#18) | Backend & Infra | med | SEC-AUTHZ-0 (helper `assert_teacher_owns_discipline`) | STUDENT → 403 nos 3 endpoints; TEACHER vinculado → 200, não vinculado → 403; ADMIN qualquer; 404 de disciplina preservado. |
| **SEC-SCOPE-2** | Escopar gradebook read + grade override às disciplinas do professor (#17) | Backend & Infra | low | SEC-SCOPE-1 | TEACHER não vinculado → 403 em GET e PUT, `grade_overrides` inalterado; vinculado/ADMIN → 200. |
| **SEC-SCOPE-3** | Role-gate endpoints de AI authoring + estimate-cost; **preservar tutor do aluno** (#12) | Backend & Infra | low | — | STUDENT → 403 em authoring + estimate-cost; **STUDENT → 200 em `/socrates/dialogue` (carve-out crítico)**; TEACHER/ADMIN → 200. |
| **SEC-SCOPE-4** | Role-gate `GET /integrations/status` (#44) | Backend & Infra | low | — | Anônimo → 401/403; STUDENT → 403; ADMIN → 200. |
| **SEC-SCOPE-5** | HMAC shared-secret no webhook Moodle (#19) | Backend & Infra | med | — | Sem/assinatura inválida → 401, sem insert; assinatura válida + payload válido → 200 e 1 linha; campos faltando → sem insert; prod sem secret → 401 (fail-closed), non-prod loga warning na release de graça. |
| **SEC-SCOPE-6** | LTI launch role + credential hardening (#20) | Backend & Infra | low | — | `roles=administrator` nunca vira ADMIN; senha auto-criada não verifica contra RA/user_id; `LTI_AUTO_CREATE_USERS` default false; instructor→TEACHER / learner→STUDENT mantidos. |
| **SEC-SCOPE-7** | Contract test de min-role + suíte de regressão negativa | Backend & Infra | low | SEC-SCOPE-1..4 | mapeia cada endpoint ao min-role esperado; guarda explicitamente `socrates/dialogue=STUDENT`; falha o build se qualquer gate SEC-SCOPE for revertido. |

#### 2.4 — Force-logout secret rotation (`force-logout-secret-rotation`) — DB-backed JWT secret

| Story | Título | Terminal | Compl. | Depende de | AC chave |
|:--|:--|:--|:--:|:--|:--|
| **SEC-ROT-1** | Colunas DB do segredo JWT em `system_settings` + provider com cache TTL | Backend & Infra | med | EPIC-SEC Fase 1 | `system_settings.jwt_secret`/`jwt_secret_rotated_at` (nullable); `get_active_jwt_secret()` lê DB, semeia do bootstrap env se NULL; cache TTL (default 30s); fail-closed para `settings.JWT_SECRET_KEY` (nunca default fraco) em erro de DB; nenhum segredo plaintext no schema. |
| **SEC-ROT-2** | Sign/verify a partir do provider DB + seed no startup | Backend & Infra | low | SEC-ROT-1 | `create_access_token` e `get_current_user` usam `get_active_jwt_secret()`; `lifespan` semeia a linha; auth normal inalterado; assinaturas de função intactas (~96 call sites preservados). |
| **SEC-ROT-3** | `force_logout` rotaciona o segredo no DB (para de mutar `.env`) + invalida cache | Backend & Infra | low | SEC-ROT-2 | nenhum write em filesystem; grava `token_urlsafe(48)` + `rotated_at` e invalida cache; tokens pré-rotação rejeitados (401) sem restart; pós-rotação validam; `require_role('ADMIN')` mantido; audit log mantido; contrato frontend `forceLogoutAll()` inalterado. |

**DoD da fase:** "IDOR sweep" parametrizado + override-de-instrutor verdes; contract test de min-role no CI; `SEC-ROT` prova que `force_logout` não toca `.env` e tokens antigos morrem; staging single-worker confirma `/app/.env` byte-idêntico antes/depois do force-logout.

> **Conflitos de arquivo coordenados (review):**
> - `create_or_get_chat_session` (`routes_ai.py:776-810`) é editado por SEC-CHAT-2/3, **TPP-2** (Fase 3) e **DATA-GAM-4** (Fase 4). **Dono único = TPP-2** (rewrite com ON CONFLICT upsert); SEC-CHAT e GAM **adicionam** sobre o resultado, não reescrevem.
> - `complete_chat_session` (`routes_ai.py:914-931`) é editado por SEC-CHAT-3, **DATA-GAM-3/4**, **INT-MOODLE-4**, e dirigido por **TPP**. Hooks aditivos sobre a versão TPP.
> - `_handle_rating_submitted` co-editado por SEC-SCOPE-5 (HMAC) e **INT-MOODLE-3** (validação). HMAC primeiro, validação por cima.

---

### FASE 3 — AI Concurrency & Server-Side Session Truth · **EPIC-AI** (parcial)

**Goal:** parar de congelar o event loop com chamadas síncronas OpenAI/ElevenLabs/Whisper; tornar o backend a fonte de verdade do diálogo socrático (persistir ambos os turnos, derivar `interactions_remaining` server-side, endurecer create-or-get contra a race).
**Exit criteria:** todas as chamadas LLM/TTS não-bloqueantes (AsyncOpenAI ou run_in_threadpool); `/socrates/dialogue` persiste turno do aluno + do assistente + opener do startChat server-side; `interactions_remaining`/`is_final_interaction` derivados do count persistido; `chat_sessions` tem `UNIQUE(user_id, content_id)` + upsert/ON CONFLICT.

**Clusters:** `async-llm-tts` (gate), `tutor-persistence-pacing` → **Backend & Infra** (com 1 Story frontend).

> **GATE DURO (review):** `async-llm-tts` (ASYNC-AI) **não tem dependências e deve mergear primeiro**. Nenhuma edição no corpo de `ai_service.py` (`_call_openai`, `socratic_dialogue`, `detect_ai_content`, `edit_response`, `validate_response`) pode mergear antes de ASYNC-AI ter feito o flip de assinatura. Isso vale para EPIC-AI hardening (Fase 4), TPP, token-budget e gamification-helper.

#### 3.1 — Async LLM/TTS (`async-llm-tts`)

| Story | Título | Terminal | Compl. | Depende de | AC chave |
|:--|:--|:--|:--:|:--|:--|
| **ASYNC-AI-1** | Migrar OpenAI para `AsyncOpenAI` (descongelar o event loop) | Backend & Infra | med | — | `AsyncOpenAI(timeout=...)` em non-mock; `_call_openai` `async`/`await`; `await` nos 5 call sites; `reprocess_content` migrado; **`_run_tts_job` (thread) recebe cliente OpenAI síncrono próprio** (acoplamento crítico); job ainda chega a 'done'; `/health` <250ms durante diálogo lento. |
| **ASYNC-AI-2** | Offload ElevenLabs TTS + Whisper do event loop | Backend & Infra | low | ASYNC-AI-1 | `convert` + join no closure dentro de `run_in_threadpool`; Whisper via AsyncOpenAI ou threadpool; `elevenlabs` pinado; `/health` responsivo sob TTS/transcribe bloqueante; contratos de resposta inalterados; timeout → 502/504. |
| **ASYNC-AI-3** | Harness de teste async + testes de regressão de concorrência | Backend & Infra | med | — | pytest-asyncio; fake AsyncOpenAI configurável; teste de concorrência **falha no código pré-fix e passa no fix**; cobre 5 métodos (live-fake + MOCK_MODE); cobre acoplamento sync-client de `_run_tts_job`; roda headless no CI. |

#### 3.2 — Tutor persistence & pacing (`tutor-persistence-pacing`) — **keystone**

| Story | Título | Terminal | Compl. | Depende de | AC chave |
|:--|:--|:--|:--:|:--|:--|
| **TPP-1** | Schema: `UNIQUE(user_id,content_id)` + RPCs de count atômico & upsert | Backend & Infra | med | — | migração idempotente, dedup antes da constraint; `UNIQUE(user_id,content_id)`; RPCs `increment_chat_session_messages` + `upsert_chat_session`; sem perda de dados (mensagens reparentadas). |
| **TPP-2** | create-or-get-session race-free (upsert + ignora `body.user_id`) — **dono único da rota** | Backend & Infra | med | TPP-1, SEC-AUTHZ-0 | concorrente → 1 sessão, nunca 500; `body.user_id` ignorado; sessões `completed` não reabrem. |
| **TPP-3** | Centralizar persistência + count atômico em `chat_repo` | Backend & Infra | med | TPP-1, ASYNC-AI-1 | `persist_turn` insere 1 row + incrementa atomicamente; `add_session_message` roteia por `persist_turn` (incrementador único); `count_user_messages`; I/O não-bloqueante. |
| **TPP-4** | Tipar `initial_question` + persistir ambos os turnos server-side | Backend & Infra | high | TPP-2, TPP-3, SEC-AUTHZ-0 | ambos os turnos persistem; GET messages + export incluem assistente; `initial_question.text` faltando → 422; queries ownership-scoped (sem novo IDOR). |
| **TPP-5** | Derivação server-side de `interactions_remaining` + finalização | Backend & Infra | med | TPP-4 | independe do campo do cliente; `should_finalize` só em `used>=MAX-1`; síntese de fechamento alcançável em sessão de 20 turnos. |
| **TPP-6** | Frontend: consumir pacing do servidor + parar de duplo-persistir turno do aluno | UX/UI & Design | med | TPP-4, TPP-5, **MEDIA-2** | remove `addMessage('user')` do cliente; badge/finalize via `session_status`; síntese renderiza no fim; sem duplo-count. |
| **TPP-7** | Encadear gate Editor→Tester atrás de flag | Backend & Infra | high | TPP-4, ASYNC-AI-1 | flag off = inalterado; on = REJECTED regenera 1×; falha do Tester nunca bloqueia o aluno. |

**DoD da fase:** round-trip de turno persiste **ambos** os turnos (guard #6); concorrência prova 1 sessão sem 500 (#7) e count atômico (#40); pacing derivado server-side resiste a campo do cliente forjado (#26); IDOR não reintroduzido (test cross-user 403/404).

> **Edge faltante corrigido (review):** TPP-6 (frontend) **também depende de MEDIA-2** (que remove `@ts-nocheck` de `ChapterReader.tsx`), além de TPP-4/5.

---

### FASE 4 — AI/Podcast/File Features & Data Integrity

**Goal:** restaurar features pedagógicas/conteúdo (podcast, extração, render de mídia, export Moodle, fluxo de conclusão, performance score), endurecer contratos LLM, e tornar o TTS job store durável. Banda maior-mas-incremental.
**Exit criteria:** podcast com script conversacional real (TTS chunked, sem cap silencioso de 5000 chars); extração `.pptx`/`.doc` funciona ou é rejeitada com erro surfaceado; vídeo/áudio/imagem renderizam via contrato normalizado; Moodle export envia de fato e mapeia campos reais; fluxo do aluno escreve progress/points/certificates/session-complete; `detect_ai_content`/`validate_response` não crasham nem fail-open; `performance_score` computado e persistido; TTS jobs sobrevivem a restart com timeouts/retenção/ownership.

#### 4.A — **EPIC-AI** (resto): hardening de contratos LLM + token budget

**Cluster `ai-llm-contract-hardening`** → **Backend & Infra** (gate: ASYNC-AI).

| Story | Título | Terminal | Compl. | Depende de | AC chave |
|:--|:--|:--|:--:|:--|:--|
| **AI-HARD-0** | Scaffold de teste + modelos Pydantic de contrato (AIDetectionResult, TesterVerdict) | Backend & Infra | low | — | coerce `'0.8'→0.8`, clamp `1.5→1.0`; verdict fora do enum → ValidationError; `_parse_model_json` retorna None (não raise) em JSON inválido. |
| **AI-HARD-1** | Detector contract hardening: probability validada + fallback heurístico (#30) | Backend & Infra | med | AI-HARD-0 | probability string/null/fora-de-range nunca 500; missing → heurística (não 0.3 silencioso); verdict/confidence sempre no enum; response_model superset. |
| **AI-HARD-2** | Remover fail-open do Tester: nunca fabricar APPROVED (#32) | Backend & Infra | low | AI-HARD-0 | JSON malformado → NEEDS_REVISION; exceção de transporte → NEEDS_REVISION + degraded + ERROR log; APPROVED só com payload bem-formado; MOCK_MODE com `mock:true`. |
| **AI-HARD-3** | Qualidade do detector heurístico: density-weighting + remover conectores PT-BR neutros (#29) | Backend & Infra | med | AI-HARD-0 | ensaio humano PT-BR com conectores <0.70 (sem flag); texto cliché-denso pontua mais; score por densidade, não contagem; contribuição limitada. |
| **AI-HARD-4** | Resiliência de `_call_openai`: guards empty-choices + empty-content (#55, #56) | Backend & Infra | med | AI-HARD-0, ASYNC-AI-1 | `choices=[]` → AIServiceError (não IndexError) nos 5 métodos; diálogo vazio → 1 retry + fallback socrático; nunca bolha em branco; resposta `{response:{content}}` intacta. |
| **AI-HARD-5** | Fidelidade de prompt/contexto: contexto único, turno cru, trim de histórico, matar `__INIT__` (#28, #57) | Backend & Infra | med | AI-HARD-0, ASYNC-AI-1 | contexto 1× no system msg; turno do aluno cru; histórico ≤K turnos; `__INIT__` removido. |
| **AI-HARD-6** | Cap de contexto de referência + seam de retrieval (#27) | Backend & Infra | low | AI-HARD-5 | até 15000 chars (não 4000); via `_select_reference_context`; sem magic number. |
| **AI-HARD-7** | Surfacear estado degraded/mock (não impersonar tutor) (#31) | Backend & Infra | low | AI-HARD-4 | respostas mock/empty/unavailable carregam `degraded:true`+reason; edit_response mock com `mock:true`; WARN quando serve mock; frontend não afetado (aditivo). |

**Cluster `token-budget-durability`** → **Backend & Infra** (gate: ASYNC-AI).

| Story | Título | Terminal | Compl. | Depende de | AC chave |
|:--|:--|:--|:--:|:--|:--|
| **TKN-1** | Função Postgres atômica de incremento + índice (migração) | Backend & Infra | low | — | índice `(user_id, usage_date)`; `increment_token_usage` ON CONFLICT atômico; 1 linha por user/dia. |
| **TKN-2** | `TokenUsageRepository` sobre a tabela existente `token_usage` | Backend & Infra | low | TKN-1 | `get_today_usage`→0 se ausente; `add_usage` via RPC retorna novo total; estilo BaseRepository. |
| **TKN-3** | Persistir budget no AIService check/track + remover cache in-memory | Backend & Infra | med | TKN-2, ASYNC-AI-1 | `_user_token_cache` removido; check fail-open em erro de leitura; track best-effort; sobrevive restart. |
| **TKN-4** | Ligar budget em editor/tester/analyst (metade-budget de #12) | Backend & Infra | med | TKN-3 | 3 métodos enforçam + registram no path real; mock → 0; call sites passam `user_id`+client autenticado; usuário sobre cap → 503. |
| **TKN-5** | Rastrear gasto LLM+ElevenLabs do TTS + pre-check de budget | Backend & Infra | med | TKN-3, ASYNC-AI-1 | jobs TTS incrementam ledger do iniciador; char-equivalent ElevenLabs rotulado/atrás de flag; pre-check antes da thread; falhas de tracking engolidas. |

#### 4.B — **EPIC-PODCAST**: podcast/TTS + job store durável

**Cluster `podcast-tts-pipeline`** → **Backend & Infra**.

| Story | Título | Terminal | Compl. | Depende de | AC chave |
|:--|:--|:--|:--:|:--|:--|
| **POD-1** | Branch de podcast + chunking sentence-aware (matar o cap silencioso de 5000) | Backend & Infra | med | — | `audio_type='podcast'` gera script conversacional ~10min (≥1200 palavras) do corpo completo HTML-stripped; `chunk_text` ≤5000 sem perda; duração do narração completa; nenhum truncamento silencioso. |
| **POD-2** | Wire chunk-and-concatenate em `_run_tts_job` e `tts_generate` sync | Backend & Infra | med | POD-1 | capítulo >10k → MP3 único válido cobrindo narração completa; summary/explanation regression-pinned; MP3 decodifica com duração ~= soma. |
| **POD-3** | Persistência de `audio_url` autoritativa + reuso do cliente Supabase compartilhado | Backend & Infra | low | POD-2 | falha de UPDATE após retries → error/persisted=false (nunca 'done' fantasma); sem cliente Supabase por-job; frontend mostra erro (não success toast) se não persistido. |
| **POD-4** | Timeouts + dedup por `(content_id,audio_type)` + cap de concorrência por user | Backend & Infra | med | POD-2 | chamada travada abortada por timeout → job error; 2 submits do mesmo content+type → mesmo job_id, 1 síntese; type diferente NÃO bloqueado; cap por user. |
| **POD-5** | Rotear áudio via StorageService (object storage + retenção local-FS) | Backend & Infra | med | POD-3 | object storage → URL estável que sobrevive redeploy; fallback local + sweep TTL; `audio_url` string; reader lida com URL relativa/absoluta. |
| **POD-6** | Persistir/recuperar áudio por estilo (corrigir mapping summary-only no reload) | Backend & Infra | low | POD-3 | **inclui migração que adiciona `contents.audio_type`** (gap do review); podcast recarrega no slot podcast; múltiplos estilos coexistem; sem regressão para `audio_url` legado. |

**Cluster `tts-job-store-lifecycle`** → **Backend & Infra** + **UX/UI & Design** (split).

| Story | Título | Terminal | Compl. | Depende de | AC chave |
|:--|:--|:--|:--:|:--|:--|
| **TTSJOB-1** | Migração tabela `tts_jobs` durável + `TtsJobRepository` | Backend & Infra | low | — | tabela com user_id NOT NULL FK, índices, sem RLS; repo com `get_for_content`+`sweep_expired` (só terminais, nunca 'processing'); idempotente. |
| **TTSJOB-2** | Persistir lifecycle do job no DB; parar pop destrutivo; enforçar ownership + TTL (**dono de #60**) | Backend & Infra | med | TTSJOB-1, POD-4 | POST semeia row 'processing' com user_id; `_run_tts_job` atualiza done/error; status idempotente (2 polls iguais); fallback `contents.audio_url` se row ausente; 404 cross-user; TTL só terminais; sobrevive restart. |
| **TTSJOB-3** | Poller TTS: poll imediato, budget maior, fallback `content.audio_url` no timeout | UX/UI & Design | low | TTSJOB-2 | 1º poll em t=0; budget nomeado (~5min); na exaustão re-fetch content + sucesso se `audio_url`; seta o style correto; `setGeneratingTts(null)` no finally. |
| **TTSJOB-4** | Poller TTS resiliente a 404 transiente / restart durante polling | UX/UI & Design | low | TTSJOB-3 | 404 único no meio não colapsa; 404 persistente → fallback `content.audio_url`; erros transientes tolerados N vezes; status exposto para distinguir 404. |

#### 4.C — **EPIC-FILES**: extração de arquivos

**Cluster `file-extraction`** → **Backend & Infra** + **UX/UI & Design** (1 Story). Sem dependências de fases anteriores — **paralelizável**.

| Story | Título | Terminal | Compl. | Depende de | AC chave |
|:--|:--|:--|:--:|:--|:--|
| **FILE-1** | Resultado de extração estruturado + suporte `.pptx` + rejeição explícita `.doc` (#9, #51, #52) | Backend & Infra | med | — | `extract()` retorna status `{ok,empty,unsupported,failed}`; `.pptx` via python-pptx → ok; `.doc` → unsupported com detalhe acionável; PDF escaneado → empty; exceção → failed (sem crash); `extract_text()` mantém `Optional[str]` para callers legados. |
| **FILE-2** | Validação magic-byte + dispatch por tipo detectado no upload (#52, #53) | Backend & Infra | med | FILE-1 | PDF/DOCX/PPTX rotulado errado → 400/415 (sem mojibake); txt/md/csv/html sem magic → fallback por extensão; dispatch no tipo detectado; `filetype` pinado; nosniff nos servidos. |
| **FILE-3** | Buffer de upload single-read + ValueError→400/413 + reconciliar allowlists (#50, #54) | Backend & Infra | med | FILE-1 | lê arquivo 1×; `save_file_from_bytes` + `save_file` delega; extensão inválida → 400, oversize → 413 (não 500); allowlists reconciliadas; demais callers de save_file intactos. |
| **FILE-4** | Surfacear `extraction_status` na resposta + UI de erro gracioso (#51) | UX/UI & Design | low | FILE-1, FILE-3 | resposta inclui `extraction_status`(+detail); `body` só se ok; mídia sempre salva; `handleUpload` mostra warning não-bloqueante em non-ok e avança; `result.id` intacto. |
| **FILE-5** | Corrigir corrupção de path em `delete_file` + guard de traversal (#61) | Backend & Infra | low | — | `removeprefix` em vez de `lstrip`; path resolvido dentro de `base_dir`; traversal `../` rejeitado (False, sem unlink). |

#### 4.D — **EPIC-DATA**: integridade de dados (gamificação/score) + Moodle export

**Cluster `gamification-data-integrity`** → **Backend & Infra**.

| Story | Título | Terminal | Compl. | Depende de | AC chave |
|:--|:--|:--|:--:|:--|:--|
| **DATA-GAM-1** | Migração + schema/ORM: coluna `achievement_key` + índice único por user | Backend & Infra | low | — | `achievement_key TEXT` + backfill `=id`; índice parcial `UNIQUE(user_id, achievement_key)`; idempotente; `id` continua PK surrogate UUID; pre-check de duplicatas. |
| **DATA-GAM-2** | Unlock de achievement idempotente: PK fresca + dedup por `achievement_key` (#15) | Backend & Infra | low | DATA-GAM-1, SEC-ADMIN-4 | 2 users distintos no mesmo achievement → ambos ok, ids distintos, sem 500; 2× mesmo user → already_unlocked, 1 row; concorrente → 1 row via índice; repo atualizado. |
| **DATA-GAM-3** | Computar + persistir `performance_score` na conclusão (#42) | Backend & Infra | med | **TPP** (persistência de turnos) | `compute_performance_score` puro, clamp [0,100], None se sinal insuficiente; escreve na borda completed; dashboards mostram média >0 para sessão pontuada; gradebook inalterado. |
| **DATA-GAM-4** | State machine de status de sessão: complete idempotente + sem reabrir terminais (#62) | Backend & Infra | med | DATA-GAM-3, SEC-ADMIN-4 | `/complete` em completed → no-op sem recompute; transição proibida → 409; create_or_get só reativa 'abandoned', completed → nova sessão; `get_session_by_content` resiste a múltiplas rows; score 1× na borda. |

**Cluster `moodle-export-integrity`** → **Backend & Infra**.

| Story | Título | Terminal | Compl. | Depende de | AC chave |
|:--|:--|:--|:--:|:--|:--|
| **INT-MOODLE-1** | Mapeamento de campos veraz em `prepare_moodle_export` (#41) | Backend & Infra | low | — | `started_at`←started_at/created_at; `score.raw`←performance_score (null, não 0, se ausente); métricas AI de detecção real ou omitidas (nunca 0.0/[] hardcoded); ambos callers recebem shape corrigido. |
| **INT-MOODLE-2** | `export_sessions_to_moodle` envia de fato + status veraz (#11) | Backend & Infra | med | INT-MOODLE-1 | `create_portfolio_entry` chamado por sessão; `moodle_export_id` só após write remoto confirmado; falha → records_failed + id NULL (retryable); sem mapping → failed com razão; status success/partial/failed; `integration_logs` persiste counts. |
| **INT-MOODLE-3** | Validar payload do rating webhook antes do insert (#62) | Backend & Infra | low | — | campos vazios → rejected sem insert; rating coerced/range-checked; falha de DB → error (não 'processed'); rota reflete non-success sem vazar existência da sessão; **compõe com HMAC de SEC-SCOPE-5**. |
| **INT-MOODLE-4** | Persistir handle LTI no launch + grade write-back na conclusão (#62) | Backend & Infra | high | INT-MOODLE-1, **TPP** | tabela `lti_outcomes` com unique `(user_id, content_id)`; launch persiste outcome_service_url+result_sourcedid+consumer_key; `post_lti_grade` assina OAuth1 (vetor conhecido), POST replaceResult via httpx; complete dispara write-back não-bloqueante com score normalizado [0,1]; score null → skip honesto. |

#### 4.E — **EPIC-FRONT**: contratos de leitura + fluxo do aluno

**Cluster `media-read-contract`** → **UX/UI & Design**. Sem deps — **gate frontend** (remove `@ts-nocheck`).

| Story | Título | Terminal | Compl. | Depende de | AC chave |
|:--|:--|:--|:--:|:--|:--|
| **MEDIA-1** | Adapter de contrato de leitura de conteúdo + wire no API client | UX/UI & Design | low | — | `normalizeContent` mapeia `content_type`→`type` (lower e legado upper), `media_url`→`file_url`, preserva body/audio_url, alias `extracted_text`←body; aplicado em `contentsApi.get/list`; tipo `Content` com IMAGE+audio_url; null-safe. |
| **MEDIA-2** | Renderizar vídeo/áudio/imagem no ChapterReader + remover `@ts-nocheck` | UX/UI & Design | med | MEDIA-1 | VIDEO/AUDIO/IMAGE renderizam via `file_url`; badge IMAGE; áudio salvo não rotulado como 'summary'; `@ts-nocheck` removido e arquivo type-checa. |
| **MEDIA-3** | Renderizar mídia no ContentRevision (instrutor) + remover `@ts-nocheck` | UX/UI & Design | low | MEDIA-1 | bloco de mídia renderiza video/audio/img/iframe; IMAGE como img; `body` (sem fallback extracted_text); `@ts-nocheck` removido. |
| **MEDIA-4** | Corrigir badges/ícones de tipo em ChapterDetail e CourseDetails | UX/UI & Design | low | MEDIA-1 | CONTENT_TYPE_META resolve real (não fallback TEXT); IMAGE adicionado; ícone reflete tipo; sem leitura de raw content_type/media_url. |

**Cluster `student-flow-frontend`** → **UX/UI & Design**.

| Story | Título | Terminal | Compl. | Depende de | AC chave |
|:--|:--|:--|:--:|:--|:--|
| **SF-1** | Resetar estado local do chat no close (re-habilitar botões socráticos) (#21) | UX/UI & Design | low | MEDIA-2 | close limpa selectedQuestion/sessionId/chatMessages; botões re-habilitam; nova pergunta inicia novo diálogo; sem inline `setChatOpen(false)`. |
| **SF-2** | Rotear 'Reprocessar IA' pelo axios compartilhado com token correto (#23) | UX/UI & Design | low | MEDIA-2 | `aiApi.reprocessContent` posta `/api/ai/reprocess-content`; sem `sessionStorage.getItem('access_token')`, sem `fetch`; TEACHER/ADMIN sucede; branches success/empty/error preservados. |
| **SF-3** | Ligar conclusão de conteúdo a progress/cert/session-complete por-user (#24) | UX/UI & Design | med | SEC-ADMIN-4, MEDIA-2, SF-1 | 'Concluir' chama `completeContent(user.id,...)` + `chatSessionsApi.complete`; não chama `contentsApi.update({completed})`; 503 (tabelas ausentes) = soft-success; sucesso → badge Concluído (não reclicável); certificado adiado/documentado. |

**DoD da fase (todos os Epics):** podcast produz script conversacional chunked (#8/#33); extração `.pptx`/`.doc` com status surfaceado (#9/#51); mídia renderiza (#10); export Moodle envia + mapeia campos reais (#11/#41); fluxo de conclusão escreve progresso/points/session-complete (#24); detector/validator não crasham nem fail-open (#30/#32); `performance_score` persistido (#42); TTS jobs duráveis (#34).

---

### FASE 5 — Contracts, Config & Cleanup · **EPIC-CLEANUP**

**Goal:** remover contratos mortos/divergentes, corrigir higiene de config, reparar bugs LOW. Baixo risco, depende de fases anteriores só onde toca arquivos já alterados.
**Exit criteria:** contratos frontend/backend reconciliados ou código morto deletado; Sentry lê `SENTRY_DSN` e é guarded; settings/reset-token DB-backed e singleton-safe; bugs LOW corrigidos; `@ts-nocheck` removido onde escondia bugs de contrato.

**Cluster `contracts-dead-code-cleanup`** → **Backend & Infra** + **UX/UI & Design** (split).

| Story | Título | Terminal | Compl. | Depende de | AC chave |
|:--|:--|:--|:--:|:--|:--|
| **CDC-1** | Enum canônico de role de mensagem (backend schema + frontend type) (#46) | Backend & Infra + UX/UI | low | — | `POST /chat-sessions/{id}/messages` aceita `{user,assistant,instructor,system}`, outro → 422; tipo TS `ChatRole` mesmo union; callers existentes intactos. |
| **CDC-2** | SessionReview: renderizar instrutor distinto + paridade de role otimista (#46) | UX/UI & Design | low | CDC-1 | mensagem instructor com avatar/label próprio (não 'IA'); push otimista `role:'instructor'`. |
| **CDC-3** | SessionReview: carregar header via fetch de sessão separado (#47) | UX/UI & Design | med | — | header (student_name/content_title/created_at) popula; `getMessages` continua array nu; campos via session row consistentes com outras telas. |
| **CDC-4** | Coluna `sequence` monotônica em chat_messages + order by (created_at, sequence) (#62) | Backend & Infra | med | — | migração aditiva backfillável; ordem determinística em list/detail/export; timestamps idênticos → ordem de inserção estável. |
| **CDC-5** | `_clean_markdown` join conservador (#62) | Backend & Infra | med | — | listas não-bullet não merge; headings não merge; word-wrap PDF ainda junta; hífens literais preservados (golden-file tests). |
| **CDC-6** | Deletar `schemas/ai.py` + `schemas/chat.py` mortos e remover imports do `__init__` (#62) | Backend & Infra | low | — | arquivos deletados; `__init__` importa limpo; app boota; OpenAPI inalterado; CI grep guard contra ressurreição. |
| **CDC-7** | Corrigir `ttsApi.generate` cliente morto para contrato JSON-body (#62) | UX/UI & Design | low | — | posta body JSON `{text, voice}` (sem params); sem default 'alloy'; demais ttsApi inalterados. |
| **CDC-8** | AbortController no send-message do ChapterReader (#62) | UX/UI & Design | med | MEDIA-2 | chamada LLM abortada no unmount; sem toast de erro após navegar; sem setState tardio; cancelamento axios não vira toast. |

**Cluster `config-store-hygiene`** → **Backend & Infra**.

| Story | Título | Terminal | Compl. | Depende de | AC chave |
|:--|:--|:--|:--:|:--|:--|
| **CFG-1** | Sentry init env-driven e guarded (#48) | Backend & Infra | low | — | init só com `SENTRY_DSN` não-vazio; sem DSN hardcoded; `backend/.env.example` documenta `SENTRY_DSN=`; init acima do app; nota ops para rotacionar DSN exposto. |
| **CFG-2** | `system_settings` singleton determinístico via id fixo + upsert (#45) | Backend & Infra | med | — | lookup por id fixo + upsert on_conflict; 2 saves concorrentes → 1 row; migração colapsa duplicatas (mantém últimos valores), idempotente; 6 callers no singleton. |
| **CFG-3** | Persistir reset-token (hashed, single-use, rate-limited) no DB (#62/#4) | Backend & Infra | med | **EPIC-SEC Fase 1 (SEC-ATO-3)** | grava `token_hash` (sha256), single-use via flag `used`, rate-limit por conta; raw token nunca no body/log; migração adiciona `token_hash` e remove/deprecia `token` plaintext; sobrevive restart; **não regride o fix #4**. |
| **CFG-4** | Boot-guard de env obrigatório em produção (#62) | Backend & Infra | low | — | `_validate_required_env` raise em prod se SUPABASE_URL/KEY vazios; no-op em dev; chamado no lifespan; check de força de JWT delegado a SEC-ATO-2. |
| **CFG-5** | Remover `favicon_url` inexistente + allowlist de colunas no save de settings (#62) | Backend & Infra | low | CFG-2 | `favicon_url` removido de SETTINGS_URL_FIELDS; `save_admin_settings` filtra chaves desconhecidas antes do UPDATE; colunas legítimas salvam; SENSITIVE_FIELDS intacto; sem 400 PostgREST de coluna inexistente. |

**DoD da fase:** contratos de role reconciliados; ordenação determinística; schemas mortos removidos com CI guard; Sentry env-driven; settings singleton-safe; reset-token DB-backed sem regressão do #4.

---

## 4. Caminho Crítico & Dependências

**Caminho crítico (cadeia de dependência mais longa):**
```
SEC-ATO (Fase 1) → SEC-AUTHZ-0/SEC-CHAT (Fase 2) → TPP (Fase 3) → DATA-GAM-3 → INT-MOODLE → (export verídico)
        ‖ paralelo (gate)
ASYNC-AI (Fase 3, sem deps) → { AI-HARD | TPP-3/7 | TKN | POD }
```

**Cadeia mínima must-land-first:**
`SEC-ATO-1 → SEC-ATO-2/3` · `ASYNC-AI-1` · `SEC-AUTHZ-0` · `TPP-1 → TPP-2 → TPP-3 → TPP-4 → TPP-5` · `MEDIA-1 → MEDIA-2`.

> **TPP é o keystone do programa** (4 consumidores downstream: DATA-GAM, INT-MOODLE, e está em ambas as cadeias). Atribuir ao reviewer mais sênior; deslize aqui cascateia para 4 clusters.
> **ASYNC-AI é o gate de TODA edição em `ai_service.py`.**

**Coordenação de conflito de arquivo (single-owner por região):**

| Arquivo / região | Dono único | Demais clusters |
|:--|:--|:--|
| `routes_ai.py:776-810` create_or_get | **TPP-2** | SEC-CHAT-2/3, DATA-GAM-4 adicionam hooks |
| `routes_ai.py:914-931` complete | **TPP** (shape) | SEC-CHAT-3, DATA-GAM-3/4, INT-MOODLE-4 hooks aditivos |
| `routes_ai.py:523-646` _tts_jobs/_run_tts_job/audio_job_status | **POD** (síntese) → **TTSJOB** (dict→tabela) | par ordenado; TTSJOB re-home dedup do POD; TTSJOB-2 dono de #60 |
| `ai_service.py` corpo dos 5 métodos | **ASYNC-AI** (flip) | AI-HARD/TPP-7/TKN/DATA-GAM-3 sobre versão async |
| `auth.py` vs `authz.py` | **`authz.py`** (novo, todos os helpers) | SEC-* consomem, não recriam |
| `backend/tests/conftest.py` | **SEC-ATO** (1º) | demais importam fixture `FakeSupabaseClient` |
| `_handle_rating_submitted` | **SEC-SCOPE-5** (HMAC) → **INT-MOODLE-3** (validação) | compõem |
| `main.py` lifespan | SEC-ATO (JWT assert) + CFG-4 (`_validate_required_env`) + SEC-ROT (seed) | coordenar 3 inserts |
| `ChapterReader.tsx` | **MEDIA-2** (remove `@ts-nocheck` primeiro) | TPP-6, SF-1/2/3, POD frontend, CDC-8 rebaseiam |

---

## 5. Migrações de Banco & Backfill

> Convenção: `supabase/migrations/YYYYMMDD_*.sql`, aplicadas **manualmente** no Supabase SQL Editor, **idempotentes** (`IF NOT EXISTS`, `ON CONFLICT`, `gen_random_uuid()::text`), **aditivas e antes do código**. **Sem novas políticas RLS** (seria no-op com client service_role — documentado em ADR SEC-CHAT-5: [`docs/adr/ADR-001-rls-migration-plan.md`](adr/ADR-001-rls-migration-plan.md)). Para mesma data (20260603), usar sufixo lexical `_01_`, `_02_`. Forçar `gamification` a abandonar `backend/migrations/0002_*` e usar a convenção dated.

**Ordem obrigatória:**

1. **MIGRATION A** `20260603a_dedupe_backfill.sql` (DATA, primeiro, sem DDL) — colapsar duplicatas `(user_id,content_id)` em chat_sessions (reparentar chat_messages/session_reviews/moodle_ratings, deletar perdedoras); manter `system_settings` mais antiga; backfill `user_achievements.achievement_key = id`. **Verificar `GROUP BY ... HAVING count(*)>1 = 0` antes de prosseguir.**
2. **MIGRATION B** `20260603b_unique_constraints.sql` (após A limpo) — `UNIQUE(user_id, content_id)` em chat_sessions (parcial WHERE content_id NOT NULL, `CREATE UNIQUE INDEX CONCURRENTLY`); singleton em `system_settings` (TPP-1, CFG-2).
3. **MIGRATION C** `20260603c_feature_flags.sql` — kill-switches em `system_settings`: `authz_enforcement_enabled` (true), `persist_tutor_turns_enabled` (false), `podcast_pipeline_enabled` (false), `tts_jobs_persisted_enabled` (false), `editor_tester_chain_enabled` (false).
4. **MIGRATION D** `20260603d_achievements_key.sql` — `user_achievements.achievement_key` + índice `UNIQUE(user_id, achievement_key)` (DATA-GAM-1).
5. **MIGRATION E** `20260603e_message_sequence.sql` — `chat_messages.sequence BIGINT` + backfill via `row_number() over (partition by session_id order by created_at, id)` (TPP-4 / CDC-4).
6. **MIGRATION F** `20260603f_tts_jobs.sql` — tabela `tts_jobs` (id, content_id, user_id NOT NULL, audio_type CHECK, status, audio_url, error, duration_estimate, created_at, updated_at; índices) (TTSJOB-1).
7. **MIGRATION G** `20260603g_jwt_secret.sql` — `system_settings.jwt_secret`/`jwt_secret_rotated_at` (SEC-ROT-1).
8. **Outras (mesma janela):** `contents.audio_type` (POD-6), `lti_outcomes` (INT-MOODLE-4), `token_usage` increment RPC + índice (TKN-1), `password_resets` token_hash (CFG-3), settings singleton (CFG-2).

**Backfill antes de constraints:** dedup chat_sessions (keeper = mais mensagens, tiebreak created_at) antes do índice único; dedup system_settings antes do singleton; `achievement_key=id` antes do índice; `sequence` via window antes de ordenar por ela. `performance_score` histórico fica NULL (analytics já coalescem). `tts_jobs`/`token_usage`/`password_resets`(hash) são forward-only.

**Tabelas já existentes (sem migração de criação):** `token_usage` (`UNIQUE(user_id,usage_date)`), `password_resets` (migração `20260519`).

---

## 6. Plano de Testes & CI Gate

**Estado atual:** ZERO infra de teste (sem pytest/vitest/playwright/MSW/CI). Único artefato é `backend/test.db` stale (inutilizado).

**Setup:**
- Backend (Backend & Infra): pytest + pytest-asyncio + httpx TestClient + pytest-cov; `FakeSupabaseClient` (chained builder sobre dicts in-memory) injetado via `app.dependency_overrides[get_supabase]` + monkeypatch de `database.supabase`; fixtures `as_user(id, role)` mantêm `require_role` **real**; seed students A/B + TEACHER + ADMIN; LLM/TTS nunca chamam APIs reais (monkeypatch `_call_openai`/clients).
- Frontend (UX/UI & Design): Vitest + Testing Library + jsdom + MSW; reuso do alias `@→src`.
- E2E: Playwright contra stack dockerizada seedada, trace-on-failure.

**Suíte de Regressão de Segurança (BLOCKING, 100%, zero skips):** princípio — app é a única barreira (sem RLS). Cada teste IDOR prova 3 desfechos (dono ok / cruzado 403-404 sem read-mutate / `body.user_id` ignorado). Cobre: chat-sessions (#2/#13), notificações (#16), gamificação (#14/#15 incl. PK-collision sem 500), gradebook/stats (#17/#18), reviews (#25), avatar (#49), auth/secret (#3/#4/#19/#20/#44/#12). **Tabela parametrizada `idor_matrix`** — novo endpoint user-scoped exige nova linha ou o job falha (presence check).

**Testes AI/pipeline:** event-loop não bloqueia sob 2 diálogos concorrentes (#1); persistência de ambos os turnos (#6); pacing derivado server-side (#26/#43); fail-safe detector/validator (#30/#31/#32/#55/#56); conectores PT-BR não flagados (#29); contexto não truncado/re-wrapped (#27/#28/#57).

**Testes file/podcast:** extração estruturada `.pptx`/`.doc` (#9/#51/#52); magic-byte (#52/#53); ValueError→400/413 (#54); single-read (#50); `delete_file` path (#61); branch de podcast chama LLM antes do TTS + chunked (#8/#33); job durável/sobrevive restart (#34/#35/#58/#59); poller imediato + fallback (#38/#39).

**E2E smoke (7 passos + IDOR negativo):** login (token key `harven-access-token`, #23) → abrir capítulo (player de mídia renderiza, #10) → chat socrático + close/reopen botões funcionam (#21) → reload com turnos do assistente persistidos (#6) → gerar podcast sem falso timeout (#8/#38) → conclusão move stats (#24) → export Moodle com turnos+started_at+score (#6/#11/#41); + negativo: segundo aluno não abre sessão de A (403/404).

**CI Gate (`.github/workflows/ci.yml`, 3 jobs, PR bloqueado):**
1. **backend** (py3.11): `pytest --cov`; **gates duros:** suíte de segurança 100% sem skips; testes não-bloqueante (#1) + persistência (#6); `diff-cover ≥80%` em arquivos alterados (`auth.py`, handlers de chat/session em `routes_ai.py`, notif/gamif/gradebook em `routes_admin.py`, `ai_service.py`).
2. **frontend** (node 22 LTS): `npm run build` (`tsc -b` deve passar — força remover `@ts-nocheck`, pegando o #10 no compilador); Vitest com cobertura.
3. **e2e smoke** (PR + nightly, merge-blocking): docker compose stack seedada (LLM/TTS fakes); smoke de 7 passos + IDOR negativo verdes.

**Política:** nenhuma chamada de rede real (OpenAI/ElevenLabs/Moodle/Supabase) no CI (network-deny fixture); cada PR de remediação envia fix + teste de regressão juntos.

---

## 7. Plano de Rollout & Backout

**6 fases de deploy** (uma por fase do roadmap), cada deploy = swap de container EasyPanel (~30s de indisponibilidade, single-worker, sem blue/green).

**Sequenciamento:** migrações forward-compatible **antes** do código. Constraints únicas só **após** backfill/dedup provar zero violações. Fases 4/5 de alto risco atrás de kill-switches (MIGRATION C).

**Verificação por fase:** Fase 0 (snapshot restaurável + env confirmado + SHA tagueado); Fase 1 (boot ok = JWT guard passou; reset sem token no body/log; staging recusa boot com env vazio); Fase 2 (índices presentes; STUDENT-A bloqueado de B em todos os recursos; TEACHER fora-de-disciplina 403; webhook sem HMAC 401; flip `authz_enforcement_enabled=false` reverte; re-enable); Fase 3 (2 diálogos lentos concorrentes mantêm `/health`; double-click create-or-get → 1 row; GET messages retorna ambos os turnos); Fase 4 (podcast conversacional real; restart mid-TTS recupera via `tts_jobs`/`contents.audio_url`; mídia renderiza; conclusão atualiza progress; export Moodle com campos populados + write real); Fase 5 (role enum reconciliado; ordenação determinística; Sentry env-driven).

**Backout por camada:**
1. **Código:** redeploy da imagem anterior (SHA da Fase 0) — swap único ~30s; cada fase mergeia separada, reverte só o deploy ofensor.
2. **Comportamental sem redeploy (caminho rápido primário):** Fases 4/5 atrás de flags `system_settings` (MIGRATION C) — ADMIN flipa flag (UPDATE DB, instantâneo). `authz_enforcement_enabled` é o kill-switch master do sweep de IDOR.
3. **Schema:** todas as migrações aditivas/forward-compatible → rollback de código não exige drop. Se um índice único quebrar insert, `DROP INDEX CONCURRENTLY`.
4. **Dados:** única migração destrutiva é o dedup (MIGRATION A) — guardada pelo snapshot da Fase 0.
5. **JWT guard (#3):** fail-closed — se bloquear boot por env, **corrigir env e reiniciar** (não reverter o guard).
6. **Sentry DSN (#48):** DSN write-only — rotacionar não quebra; DSN errado = Sentry silencioso (skip-if-empty), seguro.

**Flags de feature (reusam substrato `system_settings` existente):** `authz_enforcement_enabled`, `persist_tutor_turns_enabled`, `podcast_pipeline_enabled`, `tts_jobs_persisted_enabled`, `editor_tester_chain_enabled`. `ai_tutor_enabled` existente = freio de emergência durante a Fase 3 (async).

---

## 8. Matriz de Terminais Maestri

| Epic | Terminal primário | Stories backend | Stories frontend |
|:--|:--|:--|:--|
| **EPIC-SEC** (Fases 1-2) | Backend & Infra | SEC-ATO-1/2/3, SEC-AUTHZ-0, SEC-CHAT-1..5, SEC-ADMIN-1..6, SEC-SCOPE-1..7, SEC-ROT-1/2/3 | — |
| **EPIC-AI** (Fases 3-4) | Backend & Infra | ASYNC-AI-1/2/3, TPP-1..5/7, AI-HARD-0..7, TKN-1..5 | TPP-6 (UX/UI) |
| **EPIC-PODCAST** (Fase 4) | Backend & Infra + UX/UI | POD-1..6, TTSJOB-1/2 | TTSJOB-3/4 (UX/UI) |
| **EPIC-FILES** (Fase 4) | Backend & Infra | FILE-1/2/3/5 | FILE-4 (UX/UI) |
| **EPIC-DATA** (Fase 4) | Backend & Infra | DATA-GAM-1..4, INT-MOODLE-1..4 | — |
| **EPIC-FRONT** (Fase 4) | UX/UI & Design | — | MEDIA-1..4, SF-1/2/3 |
| **EPIC-CLEANUP** (Fase 5) | Backend & Infra + UX/UI | CDC-1(parte)/4/5/6, CFG-1..5 | CDC-1(parte)/2/3/7/8 |

**Clusters cross-terminal (coordenação obrigatória):** TPP (TPP-6 frontend), EPIC-PODCAST (TTSJOB-3/4 frontend), EPIC-FILES (FILE-4 frontend), EPIC-CLEANUP (CDC TS+Python). Migrações de DB e infra de CI são **Backend & Infra**; `@devops` exclusivo para push/PR/deploy/MCP.

---

## 9. Gaps & Riscos Abertos

**Gaps (do review):**
1. **`contents.audio_type` faltante** — POD-6 e o deferral de media-read precisam da coluna mas nenhum cluster a adicionava. **Resolvido neste roadmap:** migração de `contents.audio_type` movida para o escopo de **POD-6**. Sem ela, POD-6 não entrega.
2. **Certificado na conclusão de curso (#24)** — SF-3 deliberadamente NÃO liga `issueCertificate` ("course-completion detection out of scope"); idor-admin-writes endurece o endpoint mas nenhuma Story o liga ao fluxo end-to-end. **Aceito como follow-up documentado** — o sintoma "alunos nunca recebem certificado" fica parcialmente fechado.
3. **#50 concurrency-limit half** — FILE-3 cobre single-read + cap de 50MB; o limite de uploads grandes concorrentes não é projetado. Cobertura parcial.
4. **#36 object storage dormant** — POD-5 entrega o backend de object storage **atrás de flag default-off**; durabilidade multi-réplica fica dormente até a flag ser ligada (aceitável em single-worker).

**Riscos abertos:**
- **Carve-out do tutor socrático (SEC-SCOPE-3):** o erro mais perigoso a evitar — gatear `ai_socrates_dialogue` derruba o tutor de TODOS os alunos. Teste de regressão dedicado (STUDENT → 200) é blocking.
- **Migration A (dedup) destrutiva** — falha de constraint se houver duplicatas pré-existentes do #7; mitigada por dedup + verify + snapshot Fase 0.
- **TPP keystone** — 4 consumidores; deslize cascateia. Reviewer sênior + base estável antes de DATA-GAM/INT-MOODLE.
- **Acoplamento `_run_tts_job` (ASYNC-AI-1)** — swap para AsyncOpenAI quebra os `.create()` síncronos na thread se a thread não receber um cliente síncrono próprio; #1 item de verificação do QA (podcast/summary áudio quebra silenciosamente).
- **Convenção de DB write async** — TPP assume wrapper `run_in_threadpool` para writes Supabase síncronos "consistente com async-llm-tts", mas ASYNC-AI escolheu AsyncOpenAI (só threadpool para ElevenLabs/Whisper). Quem adicionar o 1º write awaited (TPP) **deve definir o wrapper de DB**; TKN reusa.
- **Boot-guard fail-closed (#3/CFG-4)** — recusa boot se env incompleto; validar env do EasyPanel antes do merge para não virar outage.
- **RLS não introduzido** — a barreira permanece 100% na camada de app. Um endpoint user-scoped não coberto fica totalmente explorável; o `idor_matrix` presence-check é a rede de regressão permanente.
