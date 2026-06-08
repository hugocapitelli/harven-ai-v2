---
id: AI-HARD-4
epic: EPIC-AI
phase: 4
status: Draft
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
- [ ] Em `_call_openai`, quando `response.choices` é vazio/None, é lançado `AIServiceError("empty completion")` (NÃO IndexError) — verificável nos 5 métodos públicos que o consomem (`generate_questions`, `socratic_dialogue`, `detect_ai_content`, `edit_response`, `validate_response`), cada um caindo no seu `except AIServiceError` existente e retornando o fallback/degradação do método em vez de 500.
- [ ] Em `socratic_dialogue`, quando o `content` retornado é vazio após `.strip()` (ou abaixo de um threshold mínimo definido), há exatamente 1 retry da chamada; se o retry ainda vier vazio, retorna-se um fallback socrático seguro (texto fixo com pergunta) em `response.content`.
- [ ] Nunca é entregue ao frontend uma bolha de tutor em branco: o `content` em `{"response": {"content": ...}}` retornado por `socratic_dialogue` é sempre não-vazio (conteúdo do modelo OU fallback socrático).
- [ ] A forma do retorno de sucesso permanece intacta — `{"response": {"content": ..., "has_question": ..., "is_final_interaction": ...}, "session_status": {...}, "analytics": {...}}` — nenhum consumidor a jusante quebra.
- [ ] O fallback socrático e o caminho de empty-choices emitem log de WARN (degradação observável), sem vazar stack trace ao cliente.

## Tasks / Subtasks
- [ ] `backend/services/ai_service.py` — em `_call_openai` (após l.254, antes de `choice = response.choices[0]` na l.257): inserir guard `if not response.choices: raise AIServiceError("empty completion")` e logar WARN.
- [ ] `backend/services/ai_service.py` — manter `choice.message.content or ""` (l.261) mas garantir que a normalização de content vazio fique a cargo do chamador socrático (não silenciar no `_call_openai`).
- [ ] `backend/services/ai_service.py` — em `socratic_dialogue` (bloco l.396-404): após obter `content = result["content"]`, se `not content.strip()` (ou < threshold), executar 1 retry de `self._call_openai(SOCRATES_PROMPT, ...)`; se ainda vazio, definir `content` = constante de fallback socrático (ex.: convite a reformular/aprofundar com uma pergunta). Logar WARN no caminho de fallback.
- [ ] `backend/services/ai_service.py` — definir a constante de fallback socrático próxima a `SOCRATES_PROMPT` (l.51) para reuso/teste.
- [ ] Verificar que os demais 4 métodos (`generate_questions`, `detect_ai_content`, `edit_response`, `validate_response`) já tratam `AIServiceError` no `except` (l.322, 480-bloco, 593, 622) e que o novo guard de empty-choices flui para esses handlers sem mudança adicional; ajustar apenas se algum método não envolver `_call_openai` em try/except.
- [ ] Adicionar testes de regressão (ver DoD).

## Dev Notes
- **Arquivos:** `backend/services/ai_service.py` (`_call_openai` l.227-269; `socratic_dialogue` l.367-...; consumidores: `generate_questions` l.275, `detect_ai_content` l.469, `edit_response` l.573, `validate_response` l.610; `AIServiceError` l.24; `SOCRATES_PROMPT` l.51).
- **Abordagem:** Defesa em duas camadas. (1) Empty-choices: normalizar a falha de protocolo em `AIServiceError` no ponto único `_call_openai`, reaproveitando os `except AIServiceError` já presentes em todos os 5 métodos — correção centralizada, mínima superfície. (2) Empty-content: tratar como recuperável especificamente em `socratic_dialogue` (único método cujo output vai direto para uma bolha de chat), com 1 retry + fallback determinístico, respeitando o limite de iteração (FinOps — máx 1 retry, sem loop). Não alterar o contrato de retorno nem os campos `has_question`/`is_final_interaction`.
- **Riscos de regressão:** `_call_openai` é o ponto único de inferência — tocá-lo afeta os 5 métodos públicos e suas rotas em `backend/routes_ai.py`. O guard de empty-choices só dispara em caminho de erro hoje não exercido (choices vazio), então o happy path permanece idêntico. O retry em `socratic_dialogue` adiciona no máximo 1 chamada extra ao OpenAI (custo + latência) apenas em turnos degradados. Depende de AI-HARD-0 (base de hardening do serviço) e ASYNC-AI-1 (cliente async) já aplicados — não reintroduzir o cliente síncrono nem o `await` bloqueante. Atenção a `track_token_usage` (l.403): em fallback sem retry bem-sucedido, decidir se contabiliza tokens (a chamada que veio vazia ainda consome tokens).

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: (a) `_call_openai` com `response.choices == []` levanta `AIServiceError`, não IndexError; (b) `socratic_dialogue` com content vazio na 1ª chamada e válido no retry retorna o content do retry; (c) `socratic_dialogue` com content vazio em ambas as chamadas retorna o fallback socrático não-vazio.
- [ ] Sem regressão na suíte de segurança.
- [ ] QA Gate: PASS ou CONCERNS.
- [ ] Confirmado que nenhuma resposta de `socratic_dialogue` retorna `content` vazio/whitespace ao frontend (asserção no teste) e que a estrutura `{response:{content,...}}` permanece inalterada.

## QA Results
_(a preencher pelo @qa)_
