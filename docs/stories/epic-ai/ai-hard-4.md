---
id: AI-HARD-4
epic: EPIC-AI
phase: 4
status: Done
severity: HIGH
terminal: Backend & Infra
complexity: medium
depends_on: [AI-HARD-0, ASYNC-AI-1]
bug_refs: [55, 56]
---
# AI-HARD-4: Resiliência de `_call_openai`: guards empty-choices + empty-content

## Story
Como aluno usando o tutor socrático, quero que o sistema degrade com elegância quando o modelo retorna uma completion vazia ou filtrada, para nunca ver um erro 500 nem uma bolha de tutor em branco — recebendo sempre algo a que possa responder.

## Contexto (do bug sweep)
Dois defeitos no caminho central de inferência, ambos em `backend/services/ai_service.py`:

- **#55 — `choices=[]` causa IndexError não tratado** (`ai_service.py:257`): `choice = response.choices[0]` não tem guarda. Content-filter, envelopes de erro ou gateways OpenAI-compatíveis podem retornar `choices=[]`. O IndexError resultante NÃO é um `AIServiceError`, então escapa do `except AIServiceError` de cada método público e propaga até a rota como 500 — sem fallback socrático. Os 5 métodos consumidores compartilham esse `_call_openai`: `generate_questions` (l.296), `socratic_dialogue` (l.397), `detect_ai_content` (l.480), `edit_response` (l.579) e `validate_response` (l.616). Impacto: com gateway OpenAI-compatível ou completion filtrada/vazia, o turno dá 500 e o aluno vê "Erro na resposta do tutor".

- **#56 — output vazio vira bolha em branco** (`ai_service.py:404-410`): `socratic_dialogue` retorna `result["content"]` (coalescido a `''` quando `None`, ver l.261) sem checar vazio/whitespace/curto demais, sem retry nem fallback. O frontend (`extractAiText`) aceita string vazia como mensagem válida e renderiza uma bolha de tutor em branco — sem nada para o aluno responder. Escopo reduzido: `has_question`/`is_final_interaction` nunca são lidos pelo frontend, então só o conteúdo vazio importa.

## Acceptance Criteria
- [x] Em `_call_openai`, quando `response.choices` é vazio/None, é lançado `AIServiceError("empty completion")` (NÃO IndexError) — verificável nos 5 métodos públicos que o consomem (`generate_questions`, `socratic_dialogue`, `detect_ai_content`, `edit_response`, `validate_response`), cada um caindo no seu `except AIServiceError` existente e retornando o fallback/degradação do método em vez de 500.
- [x] Em `socratic_dialogue`, quando o `content` retornado é vazio após `.strip()` (ou abaixo de um threshold mínimo definido), há exatamente 1 retry da chamada; se o retry ainda vier vazio, retorna-se um fallback socrático seguro (texto fixo com pergunta) em `response.content`.
- [x] Nunca é entregue ao frontend uma bolha de tutor em branco: o `content` em `{"response": {"content": ...}}` retornado por `socratic_dialogue` é sempre não-vazio (conteúdo do modelo OU fallback socrático).
- [x] A forma do retorno de sucesso permanece intacta — `{"response": {"content": ..., "has_question": ..., "is_final_interaction": ...}, "session_status": {...}, "analytics": {...}}` — nenhum consumidor a jusante quebra.
- [x] O fallback socrático e o caminho de empty-choices emitem log de WARN (degradação observável), sem vazar stack trace ao cliente.

## Tasks / Subtasks
- [x] `backend/services/ai_service.py` — em `_call_openai` (após `create()`, antes de `choice = response.choices[0]`): inserir guard `if not response.choices: raise AIServiceError("empty completion")` e logar WARN.
- [x] `backend/services/ai_service.py` — manter `choice.message.content or ""` mas garantir que a normalização de content vazio fique a cargo do chamador socrático (não silenciar no `_call_openai`).
- [x] `backend/services/ai_service.py` — em `socratic_dialogue`: após obter `content` de `_generate_socratic_reply`, se `not content.strip()`, executar 1 retry; se ainda vazio, definir `content = SOCRATIC_FALLBACK_CONTENT`. Logar WARN no caminho de retry e no de fallback.
- [x] `backend/services/ai_service.py` — definir a constante `SOCRATIC_FALLBACK_CONTENT` próxima a `SOCRATES_PROMPT` para reuso/teste.
- [x] Verificar que os demais 4 métodos já tratam `AIServiceError` no `except` e que o novo guard de empty-choices flui para esses handlers sem mudança adicional. Confirmado — nenhum ajuste extra necessário.
- [x] Adicionar testes de regressão (ver DoD).

## Dev Notes
- **Arquivos:** `backend/services/ai_service.py` (`_call_openai` l.227-269; `socratic_dialogue` l.367-...; consumidores: `generate_questions` l.275, `detect_ai_content` l.469, `edit_response` l.573, `validate_response` l.610; `AIServiceError` l.24; `SOCRATES_PROMPT` l.51).
- **Abordagem:** Defesa em duas camadas. (1) Empty-choices: normalizar a falha de protocolo em `AIServiceError` no ponto único `_call_openai`, reaproveitando os `except AIServiceError` já presentes em todos os 5 métodos — correção centralizada, mínima superfície. (2) Empty-content: tratar como recuperável especificamente em `socratic_dialogue` (único método cujo output vai direto para uma bolha de chat), com 1 retry + fallback determinístico, respeitando o limite de iteração (FinOps — máx 1 retry, sem loop). Não alterar o contrato de retorno nem os campos `has_question`/`is_final_interaction`.
- **Riscos de regressão:** `_call_openai` é o ponto único de inferência — tocá-lo afeta os 5 métodos públicos e suas rotas em `backend/routes_ai.py`. O guard de empty-choices só dispara em caminho de erro hoje não exercido (choices vazio), então o happy path permanece idêntico. O retry em `socratic_dialogue` adiciona no máximo 1 chamada extra ao OpenAI (custo + latência) apenas em turnos degradados. Depende de AI-HARD-0 (base de hardening do serviço) e ASYNC-AI-1 (cliente async) já aplicados — não reintroduzir o cliente síncrono nem o `await` bloqueante. Atenção a `track_token_usage` (l.403): em fallback sem retry bem-sucedido, decidir se contabiliza tokens (a chamada que veio vazia ainda consome tokens).

## Definition of Done
- [x] Teste de regressão (falha-antes / passa-depois) verde: (a) `_call_openai` com `response.choices == []` levanta `AIServiceError`, não IndexError; (b) `socratic_dialogue` com content vazio na 1ª chamada e válido no retry retorna o content do retry; (c) `socratic_dialogue` com content vazio em ambas as chamadas retorna o fallback socrático não-vazio.
- [x] Sem regressão na suíte de segurança. (suíte completa: 381 → 394 passed, +13, 0 falhas)
- [ ] QA Gate: PASS ou CONCERNS.
- [x] Confirmado que nenhuma resposta de `socratic_dialogue` retorna `content` vazio/whitespace ao frontend (asserção no teste) e que a estrutura `{response:{content,...}}` permanece inalterada.

## Dev Agent Record

### Implementação (@dev — Dex)
- **#55 (empty choices):** guard inserido em `_call_openai` (após `create()`, antes de `response.choices[0]`): `if not response.choices: logger.warning(...) + raise AIServiceError("empty completion")`. Centraliza a falha de protocolo no ponto único de inferência; os 5 métodos consumidores caem no seu `except AIServiceError` existente — `generate_questions`/`socratic_dialogue`/`edit_response` re-raise (route trata), `detect_ai_content` cai no heurístico, `validate_response` falha CLOSED para UNKNOWN/degraded. Nenhum IndexError escapa, nenhum 500.
- **#56 (empty content):** constante `SOCRATIC_FALLBACK_CONTENT` definida ao lado de `SOCRATES_PROMPT` (pergunta socrática genuína, não-vazia, com `?`). Em `socratic_dialogue`, após `_generate_socratic_reply`, se `not content.strip()` → 1 retry (máx 1, FinOps); se ainda vazio → `content = SOCRATIC_FALLBACK_CONTENT`. WARN em ambos os caminhos de degradação. Forma de retorno intacta; `has_question` deriva do `?` do fallback.
- **Não tocado:** montagem de prompt/context (AI-HARD-5), flags `degraded` (AI-HARD-7).

### Extensão do fake (`tests/fakes.py`)
O `FakeAsyncOpenAI` legado sempre retornava `choices` não-vazio e `content` fixo. Estendido com dois parâmetros:
- `empty_choices: bool` — toda completion carrega `choices=[]` (via `_FakeChatCompletion(empty_choices=True)`), exercitando o guard #55.
- `responses: list` — script per-call consumido em ordem (`_AsyncCompletions.create` usa `len(calls)-1` como índice, repetindo o último passo quando esgotado). Cada passo é uma string de content OU o sentinel `{"empty_choices": True}`. Permite "vazio-depois-válido" (1ª chamada `"   "`, 2ª válida → retry usa o retry, `calls==2`) e "ambos vazios" (`["", ""]` → fallback). Comportamento legado preservado: sem `responses`/`empty_choices`, retorna `response_text` fixo.

### Testes
- **Novo arquivo:** `backend/tests/test_ai_hard_resilience.py` — 13 testes.
  - #55: empty-choices → `AIServiceError` (não IndexError) + WARN; oracle de tipo; cada um dos 5 métodos degrada sem 500.
  - #56: vazio→1 retry usa retry (`calls==2`); ambos vazios→`content==SOCRATIC_FALLBACK_CONTENT` (não-vazio, com `?`, `has_question is True`); constante é pergunta real; `socratic` nunca retorna `content.strip()==""` em 3 caminhos; forma de retorno intacta; happy path sem retry (`calls==1`).
- **Suíte alvo:** `test_ai_hard_resilience.py` + `test_ai_service_methods.py` + `test_tutor_persistence.py` → 67 passed.
- **Suíte total:** 381 → **394 passed**, 0 falhas (zero regressão).

### File List
- `backend/services/ai_service.py` — guard empty-choices em `_call_openai`; constante `SOCRATIC_FALLBACK_CONTENT`; retry+fallback de content vazio em `socratic_dialogue`.
- `backend/tests/fakes.py` — `FakeAsyncOpenAI` estendido (`empty_choices`, `responses`) + `_FakeChatCompletion(empty_choices=...)`.
- `backend/tests/test_ai_hard_resilience.py` — novo (13 testes).
- `docs/stories/epic-ai/ai-hard-4.md` — status → Done, ACs/DoD, Dev Agent Record.

## QA Results
_(a preencher pelo @qa)_
