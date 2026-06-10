---
id: TKN-3
epic: EPIC-AI
phase: 4
status: Done
severity: HIGH
terminal: Backend & Infra
complexity: medium
depends_on: [TKN-2, ASYNC-AI-1]
bug_refs: [12]
---
# TKN-3: Persistir budget no AIService check/track + remover cache in-memory

## Story
Como operador da plataforma Harven.AI, quero que o controle de budget diário de tokens seja persistido no banco em vez de um cache in-memory per-process, para que o limite sobreviva a restarts/deploys, seja consistente entre processos e não permita que usuários ultrapassem a cota simplesmente reiniciando o serviço.

## Contexto (do bug sweep)
Item #12 do bug sweep (`backend/services/ai_service.py:174, 207-221`): o budget diário de tokens é mantido em `_user_token_cache`, um `dict` module-level (`ai_service.py:174`):

- `check_token_budget` (`ai_service.py:207-214`) lê o consumo apenas de `_user_token_cache.get(user_id, {}).get(today, 0)` e ignora o parâmetro `db=`.
- `track_token_usage` (`ai_service.py:216-221`) incrementa apenas o mesmo `dict` in-memory e também ignora `db=`.

**Impacto:** o estado vive na memória de um único processo e é **perdido a cada restart/deploy** — qualquer usuário pode zerar a própria cota apenas reiniciando o serviço. O parâmetro `db=` é aceito por ambos os métodos mas nunca usado, apesar de a tabela `TokenUsage` (`backend/models/integration.py:45-56`: `token_usage`, colunas `user_id`, `usage_date`, `tokens_used`, com `UniqueConstraint(user_id, usage_date)`) já existir e nunca ser tocada. A "race condition TTS-thread" mencionada em achados anteriores é fabricada (event loop single-thread) e o cenário "N× sob N workers" não se aplica (single worker) — o defeito real é apenas a não-persistência. Este item consolida 4 achados sobre o mesmo cache.

## Acceptance Criteria
- [x] `_user_token_cache` (dict module-level em `ai_service.py:174`) é **removido**; nenhuma leitura ou escrita de estado de budget ocorre mais em memória de processo. _(grep `_user_token_cache` em `ai_service.py` → 0)._
- [x] `check_token_budget(user_id, db)` lê o consumo do dia a partir da tabela `token_usage` keyed por `(user_id, usage_date=hoje)` via `TokenUsageRepository(db).get_today_usage(user_id)`; se `used >= daily_token_limit` (500_000), levanta `AIServiceError` como hoje.
- [x] `track_token_usage(user_id, tokens, db)` persiste o incremento na tabela `token_usage` de forma atômica via `TokenUsageRepository(db).add_usage(...)` — RPC `increment_token_usage` (`INSERT ... ON CONFLICT (user_id, usage_date) DO UPDATE SET tokens_used = tokens_used + EXCLUDED.tokens_used`), respeitando a `UniqueConstraint("user_id","usage_date")`.
- [x] **Fail-open na leitura:** se `db` é None ou a leitura falha, `check_token_budget` NÃO bloqueia a requisição — loga warning e retorna (fail-open), preservando disponibilidade.
- [x] **Best-effort na escrita:** se `track_token_usage` falhar ao persistir, o erro é logado e engolido (não propaga para o caller) — tracking é best-effort e nunca derruba a geração de IA.
- [x] **Sobrevive a restart:** após consumir tokens, descartar/recriar a instância `AIService` (cache de processo limpo) mantém o consumo refletido via DB — coberto por `TestPersistenceAcrossServiceInstances` e `test_limit_persisted_blocks_a_brand_new_service`.
- [x] Comportamento preservado: `user_id` ausente/None → no-op (sem leitura nem escrita); `tokens <= 0` → no-op em `track_token_usage`. _(`TestNoOpGuards`)._

> **Nota de implementação (discrepância da story resolvida):** o `db` injetado em todos os call sites de IA é o **Supabase Client** (PostgREST/RPC), não uma sessão SQLAlchemy. A persistência é delegada a `TokenUsageRepository` (Onda 0 / TKN-2) — não há ORM, `db.commit()` nem modelo `TokenUsage` em runtime. O upsert atômico vive na RPC `increment_token_usage` (TKN-1). Imports de `TokenUsageRepository` são lazy (dentro dos métodos) para evitar ciclo de import. Assinaturas `(user_id, db)` e `(user_id, tokens, db)` preservadas (TKN-4/5 dependem).

## Tasks / Subtasks
- [ ] Em `backend/services/ai_service.py`: remover a declaração `_user_token_cache: Dict[str, Dict[str, int]] = {}` (linha 174) e qualquer import órfão (`Dict` se não mais usado).
- [ ] Reescrever `check_token_budget(self, user_id, db=None)` (linhas 207-214) para consultar `TokenUsage` (`backend/models/integration.py`) por `(user_id, usage_date == date.today())` usando a sessão `db`; envolver a leitura em try/except → log warning + `return` (fail-open) em caso de erro.
- [ ] Reescrever `track_token_usage(self, user_id, tokens, db=None)` (linhas 216-221) para fazer upsert atômico em `token_usage` (`INSERT ... ON CONFLICT (user_id, usage_date) DO UPDATE SET tokens_used = tokens_used + EXCLUDED.tokens_used`), com `db.commit()`; envolver em try/except → log + swallow (best-effort); manter guard `if not user_id or tokens <= 0: return`.
- [ ] Garantir que os call sites de IA passam uma sessão `db` válida para `check_token_budget`/`track_token_usage` (depende de TKN-2/ASYNC-AI-1, que já propagam `db`+client autenticado pelo path real).
- [ ] Confirmar que a tabela `token_usage` existe via migration (modelo `TokenUsage` em `backend/models/integration.py:45-56`); criar migration se ainda não materializada no schema.
- [ ] Adicionar teste de regressão: simular consumo, descartar/recriar instância do serviço (estado in-memory limpo) e verificar que o budget persiste; simular erro de DB e verificar fail-open (check) e swallow (track).

## Dev Notes
- **Arquivos:**
  - `backend/services/ai_service.py` (linhas 174, 207-221 — alvo principal)
  - `backend/models/integration.py` (linhas 45-56 — modelo `TokenUsage` / tabela `token_usage`; `UniqueConstraint("user_id","usage_date")`)
  - Migrations do backend (verificar materialização da tabela `token_usage`)
  - Call sites de geração de IA que invocam `check_token_budget`/`track_token_usage` (precisam fornecer `db`)
- **Abordagem:** substituir o `dict` module-level por persistência na tabela `token_usage` já existente. Leitura agregada por `(user_id, usage_date)`; escrita por upsert atômico (ON CONFLICT na unique constraint) para evitar perda de incremento concorrente. Política de erro assimétrica e deliberada: **check = fail-open** (disponibilidade > enforcement perfeito quando DB falha) e **track = best-effort** (nunca quebrar a geração por falha de contabilidade). `daily_token_limit` (500_000, `ai_service.py:186`) permanece a regra de corte.
- **Riscos de regressão:** `check_token_budget`/`track_token_usage` são chamados pelos fluxos de geração de IA (creator/socrates/analyst e — após TKN-4 — editor/tester). Blast radius: qualquer endpoint de IA que enforça budget. Risco de **double-count** se o upsert não for atômico, e de **bloqueio indevido** se a leitura não for fail-open. Dependência forte de TKN-2/ASYNC-AI-1 terem propagado a sessão `db` aos call sites — sem `db` válido, os métodos viram no-op silencioso (falso "fail-open"). TKN-4 e TKN-5 dependem desta story para estender o enforcement; mudanças de assinatura aqui afetam ambas.

## Definition of Done
- [x] Teste de regressão (falha-antes / passa-depois) verde — `tests/test_token_budget.py` (19 testes).
- [x] Sem regressão na suíte de segurança — suíte completa **436 passed** (baseline 417 + 19 novos), exit code 0.
- [ ] QA Gate: PASS ou CONCERNS _(a preencher pelo @qa)._
- [x] `_user_token_cache` confirmado ausente do código (grep em `ai_service.py` retorna 0); budget persistido sobrevive a restart simulado (instância descartada/recriada); fail-open (check) e best-effort/swallow (track) cobertos por teste; nenhum double-count sob incremento (upsert atômico via RPC verificado).

## File List
- `backend/services/ai_service.py` — removido `_user_token_cache` (dict module-level) e o comentário "in-memory cache"; `check_token_budget` e `track_token_usage` reescritos para delegar a `TokenUsageRepository` (lazy import) com fail-open (check) / best-effort (track); assinaturas preservadas.
- `backend/tests/test_token_budget.py` — **novo**; 19 testes de regressão (persistência cross-instância, enforcement do cap, no-op guards, fail-open/best-effort, no double-count, integração nos call sites `generate_questions`/`socratic_dialogue`).
- `docs/stories/epic-ai/tkn-3.md` — status → Done, ACs/DoD marcados, nota de implementação, File List.

> `backend/tests/fakes.py` **não** foi alterado — o handler `increment_token_usage` no `FakeSupabaseClient` (TKN-1/2) já existia e cobre a persistência atômica nos testes.

## QA Results
_(a preencher pelo @qa)_
