---
id: EPIC-CLEANUP
title: Contracts, Config & Cleanup
status: Draft
phases: [5]
story_count: 13
---
# EPIC-CLEANUP: Contracts, Config & Cleanup

## Objetivo

Remover contratos mortos ou divergentes, sanear a higiene de configuração e reparar os defeitos remanescentes de severidade LOW/MEDIUM. É a fase de fechamento do programa de remediação: baixo risco, sem novas superfícies de produto, e dependente das fases anteriores **apenas onde toca arquivos já alterados** por elas (`ChapterReader.tsx` via MEDIA-2; bloco de reset-token via SEC-ATO-3).

Concretamente, esta fase:

- **Reconcilia o contrato de role de mensagem** entre backend e frontend — hoje o schema inline aceita `role: str` sem enum (`routes_ai.py:122`) e o tipo TS modela só `'user'|'assistant'`, fazendo a mensagem de instrutor (`role:'instructor'`) persistir com role não modelado e renderizar com autor errado no reload (#46).
- **Corrige a tela de revisão do instrutor** — header nunca carrega porque `SessionReview` lê `msgs.session` de um endpoint que retorna array nu (#47), e mensagens de instrutor renderizam como 'IA' (#46).
- **Torna a ordenação de transcrição determinística** com coluna `sequence` monotônica e `order by (created_at, sequence)`, eliminando reordenação por empate de microssegundo (#62).
- **Endurece a junção de markdown** (`_clean_markdown`) para não fundir listas não-marcadas, headings e hífens literais (#62).
- **Deleta os schemas mortos** `schemas/ai.py` + `schemas/chat.py` (contract-drift hazard, OpenAPI vem dos modelos inline) com guard de CI contra ressurreição (#62).
- **Repara clientes frontend mortos/perigosos** — `ttsApi.generate` (query-params → JSON body, voice ElevenLabs válida) (#62) e `AbortController` no `send-message` do `ChapterReader` (#62).
- **Sanea config** — Sentry init env-driven e guarded (#48); `system_settings` singleton determinístico via id fixo + upsert (#45); reset-token DB-backed (hash sha256, single-use, rate-limited) sem regredir o fix #4 (#62/#4); boot-guard de env obrigatório em produção (#62); remoção de `favicon_url` inexistente + allowlist de colunas no save de settings (#62).

## Critérios de Saída (Exit Criteria)

- **Role enum reconciliado:** `POST /chat-sessions/{id}/messages` aceita `{user, assistant, instructor, system}`; qualquer outro valor → **422**; o tipo TS `ChatRole` é o **mesmo union**; callers existentes intactos.
- **Render de instrutor correto:** mensagem `instructor` no `SessionReview` renderiza com avatar/label próprio (não 'IA'), e o push otimista usa `role:'instructor'` (paridade com o valor persistido).
- **Header da revisão popula:** `student_name`, `content_title`, `created_at` carregam via fetch de sessão separado; `getMessages` continua retornando array nu; campos consistentes com as demais telas.
- **Ordenação determinística:** migração aditiva e backfillável; ordem `(created_at, sequence)` em list/detail/export; timestamps idênticos → ordem de inserção estável.
- **`_clean_markdown` conservador:** listas não-bullet não fazem merge; headings não fazem merge; word-wrap de PDF ainda junta; hífens literais preservados (golden-file tests).
- **Schemas mortos removidos:** `schemas/ai.py` e `schemas/chat.py` deletados; `__init__` importa limpo; app boota; OpenAPI inalterado; **grep guard de CI** contra ressurreição.
- **`ttsApi.generate` corrigido:** posta JSON body `{text, voice}` (sem params), sem default 'alloy'; demais métodos de `ttsApi` inalterados.
- **AbortController no send-message:** chamada LLM abortada no unmount; sem toast de erro após navegar; sem setState tardio; cancelamento de axios não vira toast.
- **Sentry guarded:** `init()` só com `SENTRY_DSN` não-vazio; sem DSN hardcoded; `backend/.env.example` documenta `SENTRY_DSN=`; nota ops para rotacionar o DSN exposto.
- **`system_settings` singleton:** lookup por id fixo + upsert `on_conflict`; 2 saves concorrentes → 1 row; migração colapsa duplicatas (mantém últimos valores) e é idempotente.
- **Reset-token DB-backed:** grava `token_hash` (sha256), single-use via flag `used`, rate-limit por conta; raw token nunca no body/log; sobrevive restart; **não regride o fix #4** (rebaseia sobre SEC-ATO-3).
- **Boot-guard de env:** `_validate_required_env` raise em produção se `SUPABASE_URL`/`KEY` vazios; no-op em dev; chamado no lifespan.
- **`favicon_url` removido:** retirado de `SETTINGS_URL_FIELDS`; `save_admin_settings` filtra chaves desconhecidas antes do UPDATE; colunas legítimas salvam; `SENSITIVE_FIELDS` intacto; sem 400 PostgREST de coluna inexistente.

**DoD da fase:** contratos de role reconciliados; ordenação determinística; schemas mortos removidos com CI guard; Sentry env-driven; settings singleton-safe; reset-token DB-backed sem regressão do #4; bugs LOW corrigidos; `@ts-nocheck` removido onde escondia bugs de contrato.

## Stories

| ID | Título | Fase | Terminal | Compl. | Depende de | Severidade |
|:--|:--|:--:|:--|:--:|:--|:--:|
| CDC-1 | Enum canônico de role de mensagem (backend schema + frontend type) (#46) | 5 | Backend & Infra + UX/UI | low | — | MEDIUM |
| CDC-2 | SessionReview: renderizar instrutor distinto + paridade de role otimista (#46) | 5 | UX/UI & Design | low | CDC-1 | MEDIUM |
| CDC-3 | SessionReview: carregar header via fetch de sessão separado (#47) | 5 | UX/UI & Design | med | — | MEDIUM |
| CDC-4 | Coluna `sequence` monotônica em chat_messages + order by (created_at, sequence) (#62) | 5 | Backend & Infra | med | — | MEDIUM |
| CDC-5 | `_clean_markdown` join conservador (#62) | 5 | Backend & Infra | med | — | MEDIUM |
| CDC-6 | Deletar `schemas/ai.py` + `schemas/chat.py` mortos e remover imports do `__init__` (#62) | 5 | Backend & Infra | low | — | MEDIUM |
| CDC-7 | Corrigir `ttsApi.generate` cliente morto para contrato JSON-body (#62) | 5 | UX/UI & Design | low | — | MEDIUM |
| CDC-8 | AbortController no send-message do ChapterReader (#62) | 5 | UX/UI & Design | med | MEDIA-2 | MEDIUM |
| CFG-1 | Sentry init env-driven e guarded (#48) | 5 | Backend & Infra | low | — | MEDIUM |
| CFG-2 | `system_settings` singleton determinístico via id fixo + upsert (#45) | 5 | Backend & Infra | med | — | MEDIUM |
| CFG-3 | Persistir reset-token (hashed, single-use, rate-limited) no DB (#62/#4) | 5 | Backend & Infra | med | SEC-ATO-3 | MEDIUM |
| CFG-4 | Boot-guard de env obrigatório em produção (#62) | 5 | Backend & Infra | low | — | MEDIUM |
| CFG-5 | Remover `favicon_url` inexistente + allowlist de colunas no save de settings (#62) | 5 | Backend & Infra | low | CFG-2 | MEDIUM |

> Cluster `contracts-dead-code-cleanup` (split Backend & Infra + UX/UI): CDC-1..8.
> Cluster `config-store-hygiene` (Backend & Infra): CFG-1..5.

## Sequência / Caminho Crítico interno

A maioria das stories é **independente e paralelizável** — esta é a fase de menor acoplamento do programa. Existem 4 arestas de dependência, duas internas ao epic e duas cross-epic:

```
Internas ao EPIC-CLEANUP:
  CDC-1 ──▶ CDC-2        (render de instrutor exige o enum canônico antes)
  CFG-2 ──▶ CFG-5        (allowlist de save de settings rebaseia sobre o singleton)

Cross-epic (must-land-first em outra fase):
  MEDIA-2 (EPIC-FRONT) ──▶ CDC-8    (AbortController rebaseia em ChapterReader sem @ts-nocheck)
  SEC-ATO-3 (EPIC-SEC Fase 1) ──▶ CFG-3   (reset-token DB rebaseia sem reintroduzir o leak #4)
```

**Cadeia mais longa interna:** trivial (1 aresta — `CDC-1 → CDC-2` e `CFG-2 → CFG-5`). Nenhum keystone interno.

**Independentes (podem rodar a qualquer momento, sem espera):** CDC-3, CDC-4, CDC-5, CDC-6, CDC-7, CFG-1, CFG-4.

**Ordem recomendada de execução por terminal:**

- **Backend & Infra:** CDC-1 (parte schema) → CDC-4, CDC-5, CDC-6, CFG-1, CFG-4 em paralelo; CFG-2 → CFG-5; CFG-3 só após SEC-ATO-3 ter pousado.
- **UX/UI & Design:** CDC-1 (parte tipo TS) em conjunto com Backend; CDC-2 após CDC-1; CDC-3 e CDC-7 independentes; CDC-8 só após MEDIA-2 ter pousado.

> **Gate externo:** CDC-8 e CFG-3 são os únicos bloqueados por fases anteriores. Se MEDIA-2/SEC-ATO-3 ainda não pousaram, executar todo o resto do epic primeiro e fechar essas duas por último.

## Notas de Arquitetura

**Epic cross-terminal — coordenação obrigatória (CDC TS + Python).** CDC-1 é a única story genuinamente bi-terminal: o **enum canônico de role** é a fonte única de verdade, materializada em dois lugares que devem ficar idênticos — pattern/enum no schema inline da rota (Backend & Infra) e o union `ChatRole` em TS (UX/UI & Design). O conjunto canônico é **`{user, assistant, instructor, system}`**. Definir o enum primeiro no backend (gera o 422), depois espelhar no TS; CDC-2 consome o tipo. Tratar como contrato compartilhado, não como duas edições independentes.

**Conflitos de arquivo (single-owner por região):**

| Arquivo / região | Dono único nesta fase | Coordenação |
|:--|:--|:--|
| `ChapterReader.tsx` | **MEDIA-2** (remove `@ts-nocheck` primeiro, EPIC-FRONT) | CDC-8 rebaseia sobre a versão type-checada; TPP-6, SF-1/2/3, POD frontend também rebaseiam |
| bloco reset-token `main.py:404-477` | **SEC-ATO-3** (EPIC-SEC Fase 1, remove o leak) | CDC-3/CFG-3 rebaseia; CFG-3 **não pode reintroduzir** o token no body/log (#4) |
| `main.py` lifespan | compartilhado | CFG-4 (`_validate_required_env`) coordena com SEC-ATO (JWT assert) + SEC-ROT (seed) — **3 inserts** no mesmo lifespan |
| `routes_admin.py` settings | **CFG-2** (singleton) → **CFG-5** (allowlist) | par ordenado; CFG-5 rebaseia sobre o lookup por id fixo |

**Ordem de migrações (convenção `supabase/migrations/YYYYMMDD_*.sql`, idempotentes, aditivas e antes do código):**

- **MIGRATION E** `20260603e_message_sequence.sql` — `chat_messages.sequence BIGINT` + backfill via `row_number() over (partition by session_id order by created_at, id)` (compartilhada TPP-4 / **CDC-4**). Se TPP-4 já a aplicou na Fase 3, CDC-4 só adiciona o `order by (created_at, sequence)` em list/detail/export.
- **`system_settings` singleton** (CFG-2) — colapsa duplicatas (keeper = mais antiga / últimos valores) **antes** do índice/constraint singleton; coordena com a MIGRATION B (`20260603b_unique_constraints.sql`, que TPP-1 também usa). Backfill antes da constraint.
- **`password_resets` token_hash** (CFG-3) — adiciona `token_hash` (sha256) + flag `used`; deprecia/remove o `token` plaintext. A tabela `password_resets` **já existe** (migração `20260519`); CFG-3 é forward-only sobre ela.

> **Sem novas políticas RLS** (no-op com client service_role — ver ADR SEC-CHAT-5). Migrações aplicadas manualmente no Supabase SQL Editor.

**Decisões compartilhadas e princípios:**

- **CI guards desta fase:** (1) grep guard contra ressurreição de `schemas/ai.py`/`schemas/chat.py` (CDC-6); (2) `tsc -b` deve passar — força remover `@ts-nocheck` e captura bugs de contrato no compilador (CDC-1/CDC-8 dependem disso). Coordenar com o job frontend do CI gate (`npm run build`).
- **Contract-drift vs runtime:** os schemas mortos (CDC-6) não quebram runtime — OpenAPI vem dos modelos **inline**. A deleção é higiene de manutenibilidade; validar que o boot do app e o OpenAPI gerado ficam inalterados.
- **Rollout atrás de flags (Fase 5 de alto risco):** itens comportamentais reusam o substrato `system_settings` (MIGRATION C). Backout primário é flip de flag (UPDATE DB instantâneo) ou redeploy da imagem anterior (SHA da Fase 0). Sentry DSN é write-only/skip-if-empty → rotacionar não quebra.
- **Não regredir o #4:** CFG-3 é a única story com risco de regressão de segurança séria. Todo o trabalho de reset-token deve preservar as garantias de SEC-ATO-3 (200 sem chave `token`, anti-enumeração, sem token em logs). Teste de regressão acompanha o fix.
