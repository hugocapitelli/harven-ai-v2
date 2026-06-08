---
id: AI-HARD-5
epic: EPIC-AI
phase: 4
status: Draft
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
- [ ] O bloco de contexto estático (SOCRATES_PROMPT + pergunta em discussão + resposta esperada + conteúdo de referência) é injetado **uma única vez** na `system` message (ou primeiro turno), nunca re-embrulhado na `user` message de cada turno.
- [ ] O turno do aluno é passado **cru** como `{"role": "user", "content": <mensagem do aluno>}`, casando o framing dos turnos do histórico — sem o wrapper `CONTEXTO:\n...\n\nMENSAGEM DO ALUNO:\n...`.
- [ ] O histórico de conversa enviado ao LLM é limitado aos últimos **K turnos** (K configurável, default definido; sugestão K=10) — turnos mais antigos são descartados (ou sumarizados em fase futura), nunca re-enviados integralmente.
- [ ] O branch `is_init` / `student_message == "__INIT__"` (`ai_service.py:387-392`) é **removido** (código morto, pois o frontend envia o texto de abertura real). Se a abertura precisar de tratamento, ele é redesenhado para o sinal real do frontend — não para `__INIT__`.
- [ ] Campos dinâmicos (ex.: `interactions_remaining`) que dependam de estado não são embutidos como string stale no contexto estático; quando necessários ao modelo, são recomputados com precisão por turno (alinhar com AI-HARD/ASYNC já mesclados, sem reintroduzir o default 3 do cliente).
- [ ] Verificável: para uma sessão simulada de N turnos, a contagem de tokens de entrada por turno cresce no máximo linearmente com o tamanho do histórico cap (K), e o preâmbulo de contexto aparece exatamente 1× nas `messages` enviadas (não N×).

## Tasks / Subtasks
- [ ] Em `backend/services/ai_service.py` `socratic_dialogue` (l.380-402): mover o `context` estático (l.380-385) para o `system_prompt` (combinar com `SOCRATES_PROMPT`) em vez de embrulhar na `user_message`.
- [ ] Em `socratic_dialogue` (l.399): substituir `f"CONTEXTO:\n{context}\n\nMENSAGEM DO ALUNO:\n{user_msg}"` por o `student_message` cru passado como `user_message`.
- [ ] Em `socratic_dialogue` (l.387-392): remover o branch `is_init` / `__INIT__` e a variável `user_msg`; ajustar a chamada `_call_openai` e qualquer uso de `is_init` (ex.: `_mock_socratic` na l.424) para não depender mais de `__INIT__`.
- [ ] Em `_call_openai` (`ai_service.py:227-242`) OU em `socratic_dialogue` antes de chamar: aplicar trim do `conversation_history` aos últimos K turnos antes de `messages.extend(history)` (l.240-241). Introduzir K como constante/configuração nomeada (sem magic number).
- [ ] Recomputar/posicionar campos dinâmicos (`interactions_remaining`) fora do bloco estático, alinhado ao que ASYNC-AI-1 / AI-HARD-0 deixaram server-side.
- [ ] Verificar `backend/routes_ai.py` (rota `socratic_dialogue`) para confirmar que nenhum caller ainda envia ou depende de `__INIT__`.

## Dev Notes
- **Arquivos:** `backend/services/ai_service.py` (`socratic_dialogue` l.~365-455, `_call_openai` l.227-246, `SOCRATES_PROMPT` l.51); `backend/routes_ai.py` (rota que invoca `socratic_dialogue`).
- **Abordagem:** Refatorar a montagem de `messages` para o padrão correto de chat: `system` carrega prompt + contexto estático 1×; `history` (cap K turnos, role/content crus) + último turno do aluno cru como `user`. Eliminar duplicação de preâmbulo e o wrapper de framing. Remover o branch morto `__INIT__`. Manter compat de assinatura de `_call_openai` (parâmetro `history`) — o trim pode ser feito no caller para não impactar outros usos.
- **Riscos de regressão:** `_call_openai` (l.227) é genérico e chamado por múltiplos métodos do `AIService` (socratic, edit, detect, validate, etc.) — alterar sua assinatura impacta todos; preferir aplicar o trim no caller `socratic_dialogue` e manter `_call_openai` estável. Mexer no `is_init`/`__INIT__` toca `_mock_socratic` (l.424) — garantir que o mock continue funcionando sem o parâmetro `is_init`. A mudança de framing altera o que o LLM recebe: validar que a qualidade socrática não regrida (smoke pedagógico). Coordenar com #26/#27/AI-HARD-6 que tocam os mesmos campos de contexto (`interactions_remaining`, cap de chars de referência) para evitar conflito de merge.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: simular 3+ turnos e asserir que (a) o bloco de contexto aparece 1× nas `messages`, (b) o turno do aluno é `user` cru sem wrapper `CONTEXTO:`, (c) histórico além de K turnos é descartado.
- [ ] Sem regressão na suíte de segurança.
- [ ] QA Gate: PASS ou CONCERNS.
- [ ] Branch `__INIT__` removido do código (grep por `__INIT__` em `backend/` retorna 0 ocorrências ativas).
- [ ] Verificação de não-inflação: tokens de entrada por turno não crescem além do cap de histórico K (medição em teste ou log).

## QA Results
_(a preencher pelo @qa)_
