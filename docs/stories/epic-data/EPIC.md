---
id: EPIC-DATA
title: Data Integrity (Gamification/Score) + Moodle Export
status: Draft
phases: [4]
story_count: 8
---
# EPIC-DATA: Data Integrity (Gamification/Score) + Moodle Export

## Objetivo

Restaurar a integridade dos dados de gamificação e de pontuação, e tornar a exportação para o Moodle **veraz** — isto é, que o que o sistema reporta como exportado tenha de fato chegado ao LMS com os campos corretos.

Este epic cobre dois clusters de defeitos verificados (BUG-SWEEP-2026-06-03), todos de severidade HIGH:

- **`gamification-data-integrity`** — corrupção/colisão de PK em achievements (#15), `performance_score` lido por dashboards mas **nunca escrito** (#42), e máquina de status de sessão não idempotente que reabre terminais e mistura transcrições (#62, ramo `complete_chat_session`).
- **`moodle-export-integrity`** — mapeamento de campos falso em `prepare_moodle_export` (#41), `export_sessions_to_moodle` que marca sucesso **sem enviar nada** ao Moodle e queima a sessão para sempre (#11), rating webhook que insere rows com ids vazios sem validação (#62), e LTI que captura o outcome service URL mas **nunca escreve a nota de volta** (#62 / write-back morto).

Resultado pretendido: unlocks de achievement idempotentes e corretos por usuário; `performance_score` computado, clamped e persistido na borda de conclusão; `/complete` idempotente sem reabrir sessões terminais; export Moodle que mapeia `started_at`/`score.raw`/métricas de IA reais e só registra `moodle_export_id` após escrita remota confirmada; rating webhook validado antes do insert; e write-back de nota LTI assinado por OAuth1 na conclusão.

## Critérios de Saída (Exit Criteria)

- **Achievement unlock idempotente:** dois usuários distintos desbloqueando o mesmo achievement → ambos OK, `id`s distintos, sem 500; o mesmo usuário 2× → `already_unlocked`, **1 row**; concorrência → **1 row** garantida pelo índice único parcial `UNIQUE(user_id, achievement_key)`.
- **`performance_score` na borda completed:** `compute_performance_score` é função pura, clamp em `[0,100]`, `None` se sinal insuficiente; escrito **uma única vez** na transição para `completed`; dashboards (`admin_performance`, `dashboard_stats`, `discipline_students_stats`) passam a mostrar média > 0 para sessão pontuada; **gradebook inalterado** (continua computando de `session_reviews.rating` + overrides).
- **State machine de sessão:** `/complete` sobre sessão já `completed` → **no-op** sem recompute; transição proibida → **409**; `create_or_get` só reativa `abandoned`, `completed` → **nova sessão**; `get_session_by_content` resiste a múltiplas rows; score escrito **1× na borda**.
- **Mapeamento Moodle veraz:** `prepare_moodle_export` mapeia `created_at`→`started_at`, `performance_score`→`score.raw` (**null, não 0**, se ausente), e métricas de IA (`avg_ai_probability`/`flags_triggered`) de resultados de detecção reais **ou omitidas** — nunca `0.0`/`[]` hardcoded; ambos os callers de export recebem o shape corrigido.
- **Export que de fato envia:** `export_sessions_to_moodle` chama `create_portfolio_entry` por sessão; `moodle_export_id` é gravado **somente após write remoto confirmado**; falha → `records_failed` + `moodle_export_id` permanece NULL (retryable); sem mapping → `failed` com razão; status agregado `success`/`partial`/`failed`; `integration_logs` persiste os counts.
- **Rating webhook validado:** campos obrigatórios vazios → `rejected` **sem insert**; `rating` coerced e range-checked; falha de DB → status `error` (não `processed`); a rota reflete o non-success sem vazar a existência da sessão; **compõe com o HMAC de SEC-SCOPE-5**.
- **LTI launch + write-back:** tabela `lti_outcomes` com `UNIQUE(user_id, content_id)`; o launch persiste `outcome_service_url` + `result_sourcedid` + `consumer_key`; `post_lti_grade` assina **OAuth1** (vetor de assinatura conhecido validado) e faz POST `replaceResult` (Basic Outcomes) via `httpx`; `complete` dispara o write-back **não-bloqueante** com score normalizado `[0,1]`; score `null` → **skip honesto** (sem POST falso).

## Stories

| ID | Título | Fase | Terminal | Compl. | Depende de | Severidade |
|:--|:--|:--:|:--|:--:|:--|:--:|
| **DATA-GAM-1** | Migração + schema/ORM: coluna `achievement_key` + índice único por user | 4 | Backend & Infra | low | — | HIGH |
| **DATA-GAM-2** | Unlock de achievement idempotente: PK fresca + dedup por `achievement_key` | 4 | Backend & Infra | low | DATA-GAM-1, SEC-ADMIN-4 | HIGH |
| **DATA-GAM-3** | Computar + persistir `performance_score` na conclusão | 4 | Backend & Infra | med | TPP-4 | HIGH |
| **DATA-GAM-4** | State machine de status de sessão: complete idempotente + sem reabrir terminais | 4 | Backend & Infra | med | DATA-GAM-3, SEC-ADMIN-4 | HIGH |
| **INT-MOODLE-1** | Mapeamento de campos veraz em `prepare_moodle_export` | 4 | Backend & Infra | low | — | HIGH |
| **INT-MOODLE-2** | `export_sessions_to_moodle` envia de fato + status veraz | 4 | Backend & Infra | med | INT-MOODLE-1 | HIGH |
| **INT-MOODLE-3** | Validar payload do rating webhook antes do insert | 4 | Backend & Infra | low | — | HIGH |
| **INT-MOODLE-4** | Persistir handle LTI no launch + grade write-back na conclusão | 4 | Backend & Infra | high | INT-MOODLE-1, TPP-4 | HIGH |

## Sequência / Caminho Crítico interno

Todas as 8 stories são **Fase 4 / Backend & Infra**. Há dois subgrafos paralelizáveis dentro do epic, mais um keystone externo.

**Cluster gamification (cadeia mais longa):**
```
DATA-GAM-1 ──► DATA-GAM-2          (gamificação: schema → unlock idempotente)
TPP-4 ──► DATA-GAM-3 ──► DATA-GAM-4 (score: persistência de turnos → score → state machine)
```
- `DATA-GAM-1` (migração `achievement_key`) é gate de `DATA-GAM-2`; ambas dependem de **SEC-ADMIN-4** (vincular escritas ao `current_user`, fix do IDOR #14) para que `DATA-GAM-2`/`DATA-GAM-4` operem sobre a borda de autorização já corrigida.
- `DATA-GAM-3` é o nó mais sensível do cluster: depende de **TPP-4** (sequência/persistência de turnos), pois o cálculo de `performance_score` consome o histórico de turnos persistido. `DATA-GAM-4` (state machine) só fecha **depois** de `DATA-GAM-3`, porque a borda `completed` é onde o score é escrito 1×.

**Cluster moodle:**
```
INT-MOODLE-1 ──► INT-MOODLE-2
INT-MOODLE-1 ──► INT-MOODLE-4 (◄── também TPP-4)
INT-MOODLE-3  (independente — só compõe com SEC-SCOPE-5)
```
- `INT-MOODLE-1` (mapeamento veraz) é o gate dos dois consumidores de export real: `INT-MOODLE-2` (envio + status) e `INT-MOODLE-4` (write-back LTI). `INT-MOODLE-4` é a story de maior complexidade do epic e adiciona dependência em **TPP-4** (precisa do score consolidado para normalizar `[0,1]`).
- `INT-MOODLE-3` (validação do rating webhook) não tem dependência interna — pode ser feita a qualquer momento, mas **compõe com SEC-SCOPE-5** (HMAC) na mesma função `_handle_rating_submitted`.

**Keystone externo — TPP:** `DATA-GAM-3` e `INT-MOODLE-4` ambos dependem de **TPP-4**. Conforme o roadmap, **TPP é o keystone do programa** (4 consumidores downstream). Deslize em TPP cascateia direto para este epic — não iniciar `DATA-GAM-3`/`INT-MOODLE-4` antes de TPP-4 estar landado.

**Ordem recomendada de aterrissagem:**
1. `INT-MOODLE-1` e `INT-MOODLE-3` (sem deps internas, baixo risco) — podem rodar cedo, em paralelo com a chegada de SEC-ADMIN-4/TPP-4.
2. `DATA-GAM-1` → `DATA-GAM-2` (após SEC-ADMIN-4).
3. `DATA-GAM-3` (após TPP-4) → `DATA-GAM-4`.
4. `INT-MOODLE-2` (após INT-MOODLE-1).
5. `INT-MOODLE-4` (após INT-MOODLE-1 + TPP-4) — última, maior complexidade.

## Notas de Arquitetura

**Migrações de DB (aditivas, idempotentes, antes do código, convenção dated `supabase/migrations/YYYYMMDD_*.sql`):**
- **MIGRATION A** `20260603a_dedupe_backfill.sql` (sem DDL, **primeiro**) — entre outras tarefas, faz `backfill user_achievements.achievement_key = id` e prepara o dedup. Verificar `GROUP BY ... HAVING count(*) > 1 = 0` antes de prosseguir.
- **MIGRATION D** `20260603d_achievements_key.sql` — adiciona `user_achievements.achievement_key TEXT` + índice **parcial** `UNIQUE(user_id, achievement_key)` (DATA-GAM-1). `id` **continua sendo PK surrogate UUID** (`gen_random_uuid()::text`); a referência de catálogo migra para `achievement_key`. Pre-check de duplicatas antes do índice único.
- **MIGRATION E** `20260603e_message_sequence.sql` — `chat_messages.sequence BIGINT` + backfill por `row_number()` (TPP-4 / CDC-4). É a base que `DATA-GAM-3` (cálculo de score sobre turnos ordenados) e `INT-MOODLE-4` consomem indiretamente via TPP-4.
- **Outras na mesma janela:** tabela `lti_outcomes` (INT-MOODLE-4) com `UNIQUE(user_id, content_id)` — colunas `outcome_service_url`, `result_sourcedid`, `consumer_key`, `user_id`, `content_id`, timestamps.
- **Sem novas políticas RLS** — seria no-op com o cliente service_role (documentado no ADR SEC-CHAT-5). A barreira de autorização é a camada de aplicação (`authz.py`), não o RLS.

**Coordenação de conflito de arquivo (single-owner por região — crítico para este epic):**
- **`routes_ai.py:914-931` (complete)** — **dono: TPP** (define o shape). `DATA-GAM-3` (escrita do score), `DATA-GAM-4` (precondição de status / 409), `INT-MOODLE-4` (hook de write-back não-bloqueante) e `SEC-CHAT-3` adicionam **hooks aditivos** sobre o shape do TPP. Não reescrever a função; estender pontos de extensão.
- **`routes_ai.py:776-810` (create_or_get)** — **dono: TPP-2**. `DATA-GAM-4` adiciona a regra "só reativa `abandoned`, `completed` → nova sessão" como hook, sem reescrever a base.
- **`ai_service.py` corpo dos 5 métodos** — **dono: ASYNC-AI** (flip síncrono→async). `DATA-GAM-3` (cálculo de score) opera **sobre a versão async** — não tocar `ai_service.py` antes do gate ASYNC-AI. `prepare_moodle_export` (`ai_service.py:684-708`, alvo de INT-MOODLE-1) também vive aqui; coordenar a edição com o owner ASYNC-AI.
- **`_handle_rating_submitted` (`integration_service.py:479-497`)** — **dono: SEC-SCOPE-5** (HMAC) → **INT-MOODLE-3** (validação de payload). Os dois **compõem** na mesma função: HMAC primeiro (autenticidade), validação de campos depois (integridade). INT-MOODLE-3 rebaseia sobre o fix de SEC-SCOPE-5.
- **`integration_service.py:354-385` (export_sessions_to_moodle)** e **`:565-662` (LTI)** — escopo de INT-MOODLE-2 e INT-MOODLE-4 respectivamente; `MoodleClient.update_grade` já **existe** mas nunca é chamado — INT-MOODLE-4 implementa o caminho de chamada (`post_lti_grade` → OAuth1 → `replaceResult`).

**Decisões compartilhadas relevantes:**
- **`performance_score` ≠ gradebook:** o gradebook computa de `session_reviews.rating` + overrides e **não** lê `performance_score`. DATA-GAM-3 deve persistir o score **sem** alterar o caminho do gradebook (verificação de não-regressão obrigatória no QA gate).
- **Veracidade > completude no export:** quando um sinal de IA não existe, **omitir** o campo é preferível a emitir `0.0`/`[]`. O LMS deve receber `null` honesto em vez de zero enganoso (INT-MOODLE-1).
- **Idempotência por índice, não por leitura-antes-de-escrever:** tanto o unlock de achievement (DATA-GAM-2) quanto o `lti_outcomes` (INT-MOODLE-4) garantem unicidade via **índice único do banco** + `ON CONFLICT`, resistindo a concorrência — não confiar em check-then-insert na aplicação.
- **Write-back não-bloqueante:** o `replaceResult` LTI na conclusão **não pode bloquear** a resposta de `/complete`; score `null` → skip honesto, sem POST de placeholder.
