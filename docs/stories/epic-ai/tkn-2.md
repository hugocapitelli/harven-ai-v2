---
id: TKN-2
epic: EPIC-AI
phase: 4
status: Draft
severity: HIGH
terminal: Backend & Infra
complexity: low
depends_on: [TKN-1]
bug_refs: [12]
---
# TKN-2: TokenUsageRepository sobre a tabela existente token_usage

## Story
Como engenheiro de backend, quero um `TokenUsageRepository` no estilo `BaseRepository` que leia o consumo diário de tokens e o incremente atomicamente via RPC, para que o budget de tokens por usuário seja persistido na tabela `token_usage` (já existente, porém órfã) em vez de depender de um cache in-memory volátil.

## Contexto (do bug sweep)
Bug #12 (`backend/services/ai_service.py:174, 207-221`): o budget diário de tokens é mantido em `_user_token_cache`, um `dict` module-level. Isso causa três problemas concretos:
- O parâmetro `db=` é aceito em `check_token_budget`/`track_token_usage` mas **ignorado** — nenhuma persistência ocorre.
- O cache é perdido a cada restart do processo, zerando o consumo acumulado e permitindo estouro silencioso do limite diário.
- A tabela `token_usage` (`backend/models/integration.py:45-56`, classe `TokenUsage`, com `UniqueConstraint(user_id, usage_date)`) **existe mas nunca é usada**.

Esta story cria a camada de acesso a dados (`TokenUsageRepository`) que conecta o código à tabela existente, usando a RPC atômica `increment_token_usage` entregue por TKN-1. Não altera ainda o `AIService` — isso é escopo de TKN-3. O foco aqui é exclusivamente o repositório e seu contrato.

## Acceptance Criteria
- [ ] `TokenUsageRepository(client)` herda/segue o estilo de `backend/repositories/base.py` (construtor recebe `Client`, `table_name = "token_usage"`).
- [ ] `get_today_usage(user_id)` retorna o `tokens_used` da linha `(user_id, usage_date=hoje)`; **retorna `0` quando não há linha** para o dia (ausência == zero, nunca `None` nem exceção).
- [ ] `add_usage(user_id, tokens)` invoca a RPC `increment_token_usage` (de TKN-1) via `self.client.rpc("increment_token_usage", {...}).execute()` e **retorna o novo total** acumulado do dia.
- [ ] `add_usage` é atômico (delega o `ON CONFLICT` à RPC) — duas chamadas concorrentes para o mesmo `(user_id, hoje)` somam corretamente, sem perda de incremento.
- [ ] `add_usage` com `tokens <= 0` é no-op seguro (não escreve; retorna o total atual ou `0`).
- [ ] A data usada é sempre `date.today()` no servidor, formatada como `isoformat()`, consistente com o índice/constraint de TKN-1.

## Tasks / Subtasks
- [ ] Criar `backend/repositories/token_usage_repo.py` com a classe `TokenUsageRepository(BaseRepository)` apontando para a tabela `"token_usage"`.
- [ ] Implementar `get_today_usage(user_id: str) -> int`: `select("tokens_used")` com `eq("user_id", ...)` + `eq("usage_date", date.today().isoformat())` usando `.maybe_single()`; retornar `res.data["tokens_used"] if res.data else 0`.
- [ ] Implementar `add_usage(user_id: str, tokens: int) -> int`: guard `tokens <= 0`; chamar `self.client.rpc("increment_token_usage", {"p_user_id": user_id, "p_usage_date": date.today().isoformat(), "p_tokens": tokens}).execute()` e retornar o total devolvido pela RPC (confirmar nomes dos parâmetros contra a migração de TKN-1).
- [ ] Exportar a nova classe em `backend/repositories/__init__.py` no mesmo padrão dos demais repos.
- [ ] Escrever teste de regressão (ver Definition of Done) cobrindo ausência→0, incremento→novo total, e idempotência de `tokens<=0`.

## Dev Notes
- **Arquivos:**
  - Criar: `backend/repositories/token_usage_repo.py`
  - Editar: `backend/repositories/__init__.py` (export)
  - Referência de estilo: `backend/repositories/base.py` (assinatura `__init__(self, client: Client, table_name)`, uso de `.maybe_single().execute()` e `res.data`)
  - Modelo/tabela alvo: `backend/models/integration.py:45-56` (`TokenUsage`: colunas `user_id`, `usage_date`, `tokens_used`; `UniqueConstraint(user_id, usage_date)`)
  - Dependência: RPC `increment_token_usage` + índice `(user_id, usage_date)` criados em TKN-1.
- **Abordagem:** Repositório fino sobre o Supabase client (PostgREST + RPC). Leitura via `.table("token_usage").select("tokens_used").eq(...).maybe_single()`; escrita via `.rpc("increment_token_usage", params)` para garantir atomicidade no Postgres (a soma `ON CONFLICT` mora na RPC, não no Python). Nenhum estado in-memory. NÃO tocar em `ai_service.py` nesta story — a substituição do `_user_token_cache` e a fiação `check/track` ocorrem em TKN-3.
- **Riscos de regressão:** Blast radius baixo — arquivo novo, sem consumidores até TKN-3. O único acoplamento é o contrato da RPC de TKN-1 (nomes/ordem dos parâmetros e shape do retorno). Confirmar esse contrato antes de finalizar `add_usage`. O `_user_token_cache` em `ai_service.py:174,207-221` permanece intocado até TKN-3, então o comportamento atual do budget não muda nesta entrega.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde
- [ ] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [ ] `get_today_usage` retorna `0` (não `None`/exceção) para usuário sem consumo no dia, comprovado por teste
- [ ] `add_usage` retorna o novo total via RPC e é idempotente para `tokens<=0`, comprovado por teste
- [ ] Estilo alinhado a `BaseRepository`; classe exportada em `repositories/__init__.py`

## QA Results
_(a preencher pelo @qa)_
