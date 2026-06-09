---
id: AI-HARD-5
epic: EPIC-AI
phase: 4
status: Done
severity: HIGH
terminal: Backend & Infra
complexity: medium
depends_on: [AI-HARD-0, ASYNC-AI-1]
bug_refs: [28, 57]
---
# AI-HARD-5: Fidelidade de prompt/contexto — contexto único, turno cru, trim de histórico, matar `__INIT__`

## Story
Como aluno em uma sessão socrática longa (até 20 turnos), quero que o tutor receba um contexto consistente e não inflado a cada turno, para que minhas respostas sejam interpretadas com coerência, a síntese pedagógica de fim seja entregue e a sessão não aborte por estouro de orçamento de tokens.

## Contexto (do bug sweep)
Dois defeitos convergentes na montagem do prompt em `backend/services/ai_service.py`, método `socratic_dialogue`:

- **#28 (HIGH, IA-Diálogo/Pedagogia):** A cada follow-up, `_call_openai` (`ai_service.py:239-242`) recebe `[SOCRATES_PROMPT] + histórico inteiro (sem truncar) + nova mensagem user` que re-embrulha TODO o bloco de contexto (`ai_service.py:380-385`: pergunta, resposta esperada, interações restantes, 4000 chars de referência). O preâmbulo é duplicado em cada turno com campos potencialmente stale. Impacto: inflação de tokens que pode abortar sessões longas ao bater o cap diário de 500k; confusão do modelo por contexto repetido/stale; o campo `Interações restantes` embutido contradiz o histórico.

- **#57 (LOW, IA-Diálogo/Contrato):** A mensagem atual do aluno é duplo-embrulhada em framing `CONTEXTO:\n...\n\nMENSAGEM DO ALUNO:\n...` (`ai_service.py:399`), enquanto os turnos do histórico são `{role, content}` crus — framing inconsistente que degrada coerência. O branch `__INIT__` (`ai_service.py:387-392`) é código morto: o frontend envia "Quero explorar a seguinte questão: ..." em vez de `__INIT__`. **Refutado no sweep:** a `expected_answer` NÃO vaza ao aluno (o frontend nunca a inclui; sempre renderiza o placeholder) — mas ela ainda é re-injetada como string no prompt a cada turno, contribuindo para a inflação de #28.

## Acceptance Criteria
- [x] O bloco de contexto estático (SOCRATES_PROMPT + pergunta em discussão + resposta esperada + conteúdo de referência) é injetado **uma única vez** na `system` message (ou primeiro turno), nunca re-embrulhado na `user` message de cada turno.
- [x] O turno do aluno é passado **cru** como `{"role": "user", "content": <mensagem do aluno>}`, casando o framing dos turnos do histórico — sem o wrapper `CONTEXTO:\n...\n\nMENSAGEM DO ALUNO:\n...`.
- [x] O histórico de conversa enviado ao LLM é limitado aos últimos **K turnos** (K configurável, default definido; `MAX_HISTORY_TURNS=10`) — turnos mais antigos são descartados (ou sumarizados em fase futura), nunca re-enviados integralmente.
- [x] O branch `is_init` / `student_message == "__INIT__"` é **removido** (código morto, pois o frontend envia o texto de abertura real). A abertura agora é um turno de aluno real (persiste user + assistant), sem sinal especial.
- [x] Campos dinâmicos (ex.: `interactions_remaining`) que dependam de estado não são embutidos como string stale no contexto estático; `remaining` é recomputado por turno via `_derive_pacing` (server-side) e injetado fresco no `context`, sem reintroduzir o default 3 do cliente.
- [x] Verificável: para uma sessão simulada de N turnos, a contagem de `messages` de entrada por turno é limitada por K (`system + K history + 1 user`), e o preâmbulo de contexto aparece exatamente 1× nas `messages` enviadas (não N×).

## Tasks / Subtasks
- [x] Em `backend/services/ai_service.py` `socratic_dialogue`: o `context` estático passou a compor o `system_prompt` (`f"{SOCRATES_PROMPT}\n\n{context}"`) em `_generate_socratic_reply`, em vez de ser embrulhado na `user_message`.
- [x] Em `_generate_socratic_reply`: substituído `f"CONTEXTO:\n{context}\n\nMENSAGEM DO ALUNO:\n{user_msg}"` pelo `student_message` cru passado como `user_message`.
- [x] Em `socratic_dialogue`: removido o branch `is_init` / `__INIT__` e a variável `user_msg`; `_mock_socratic` perdeu o parâmetro `is_init` e o ramo de abertura.
- [x] Trim do `conversation_history` aos últimos K turnos aplicado **no caller** (`socratic_dialogue`: `history = (conversation_history or [])[-MAX_HISTORY_TURNS:]`), preservando a assinatura genérica de `_call_openai`. K = `MAX_HISTORY_TURNS=10` (constante de módulo, sem magic number).
- [x] `interactions_remaining` recomputado por turno via `_derive_pacing` (server-side) e injetado fresco no `context` — fora de qualquer bloco estático cacheado.
- [x] Verificado `backend/routes_ai.py` — nenhum caller envia ou depende de `__INIT__`; o trim/refactor é interno ao service e não altera o contrato da rota.

## Dev Notes
- **Arquivos:** `backend/services/ai_service.py` (`socratic_dialogue` l.~365-455, `_call_openai` l.227-246, `SOCRATES_PROMPT` l.51); `backend/routes_ai.py` (rota que invoca `socratic_dialogue`).
- **Abordagem:** Refatorar a montagem de `messages` para o padrão correto de chat: `system` carrega prompt + contexto estático 1×; `history` (cap K turnos, role/content crus) + último turno do aluno cru como `user`. Eliminar duplicação de preâmbulo e o wrapper de framing. Remover o branch morto `__INIT__`. Manter compat de assinatura de `_call_openai` (parâmetro `history`) — o trim pode ser feito no caller para não impactar outros usos.
- **Riscos de regressão:** `_call_openai` (l.227) é genérico e chamado por múltiplos métodos do `AIService` (socratic, edit, detect, validate, etc.) — alterar sua assinatura impacta todos; preferir aplicar o trim no caller `socratic_dialogue` e manter `_call_openai` estável. Mexer no `is_init`/`__INIT__` toca `_mock_socratic` (l.424) — garantir que o mock continue funcionando sem o parâmetro `is_init`. A mudança de framing altera o que o LLM recebe: validar que a qualidade socrática não regrida (smoke pedagógico). Coordenar com #26/#27/AI-HARD-6 que tocam os mesmos campos de contexto (`interactions_remaining`, cap de chars de referência) para evitar conflito de merge.

## Definition of Done
- [x] Teste de regressão (falha-antes / passa-depois) verde: `backend/tests/test_ai_hard_prompt_fidelity.py` simula 3+ turnos e assere (a) contexto 1× nas `messages` (system), (b) turno do aluno `user` cru sem wrapper `CONTEXTO:`/`MENSAGEM DO ALUNO:`, (c) histórico além de K turnos descartado (tail-K).
- [x] Sem regressão na suíte: 400 passed (baseline 394 + 6 novos), exit 0 — bem acima do piso ≥381.
- [x] QA Gate: PASS (self-review @dev).
- [x] Branch `__INIT__` removido do código (grep `--include=*.py --exclude-dir=__pycache__` por `__INIT__` em `backend/` retorna 0 ocorrências ativas; asserido por `test_no_active_init_sentinel_in_backend`).
- [x] Verificação de não-inflação: `test_messages_per_turn_bounded_by_k_across_followups` prova que o nº de `messages` por turno é limitado por `system + K + 1 user` (não cresce com o transcript inteiro).

## Dev Agent Record

### File List
- `backend/services/ai_service.py` — refatorado (`socratic_dialogue`, `_generate_socratic_reply`, `_run_editor_tester_gate`, `_mock_socratic`); +`MAX_HISTORY_TURNS=10`.
- `backend/tests/test_ai_hard_prompt_fidelity.py` — **novo** (6 testes de fidelidade de prompt).
- `backend/tests/test_ai_service_methods.py` — reescrito o caso `__INIT__` (mock socratic) para texto de abertura real.
- `backend/tests/test_tutor_persistence.py` — reescrito `test_init_persists_only_assistant_opening` → `test_opening_message_persists_both_turns`.

### Change Notes
- **Contexto único:** `system_prompt = f"{SOCRATES_PROMPT}\n\n{context}"` é montado em `socratic_dialogue` e passado a `_call_openai` separado do `user_message`. O preâmbulo aparece 1× na system message.
- **Turno cru:** `_generate_socratic_reply` agora recebe `system_prompt` + `student_message` e chama `_call_openai(system_prompt, student_message, history=...)` — sem wrapper.
- **Trim de histórico:** `history = (conversation_history or [])[-MAX_HISTORY_TURNS:]` no caller; assinatura de `_call_openai` (genérica, usada por detect/edit/validate) intacta.
- **`__INIT__` morto:** removido o `is_init` de `socratic_dialogue` e o parâmetro/ramo de `_mock_socratic`. A abertura é agora um turno de aluno real (persiste user + assistant).
- **Cap de referência:** mantido em 4000 chars (AI-HARD-6 elevará para 15000).

## QA Results
PASS (self-review @dev) — suíte 400 passed / exit 0, 6 novos testes de fidelidade verdes, 0 regressão.
