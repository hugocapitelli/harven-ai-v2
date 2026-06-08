---
id: DATA-GAM-4
epic: EPIC-DATA
phase: 4
status: Draft
severity: HIGH
terminal: Backend & Infra
complexity: medium
depends_on: [DATA-GAM-3, SEC-ADMIN-4]
bug_refs: [62]
---
# DATA-GAM-4: State machine de status de sessão — complete idempotente + sem reabrir terminais

## Story
Como aluno (e como sistema de gamificação), quero que o status de uma sessão de chat siga uma máquina de estados estrita — onde `/complete` é idempotente, transições proibidas são rejeitadas e sessões já concluídas nunca são reabertas — para que o score seja contabilizado exatamente uma vez por sessão e o progresso/pontuação do aluno não seja corrompido por chamadas repetidas, concorrentes ou fora de ordem.

## Contexto (do bug sweep)
Item #62 do bug sweep: o ciclo de vida da sessão de chat/tutor não é governado por uma máquina de estados explícita, o que gera três classes de defeito que se compõem:

1. **`/complete` não-idempotente (recompute em estado terminal):** o endpoint de conclusão (`routes_ai.py`, handler de `complete_chat_session` / `/complete`) recalcula o score e reaplica efeitos de gamificação a cada chamada, mesmo quando a sessão já está em `completed`. Chamadas duplicadas (retry de rede, double-click, replay) somam pontos múltiplas vezes — o score é contabilizado N vezes em vez de 1× na borda de transição `in_progress → completed`.

2. **`create_or_get_chat_session` reabre terminais:** em `routes_ai.py:776-810`, a função de obtenção/criação de sessão por conteúdo retorna a sessão existente independentemente do status. Quando a sessão existente está em `completed` (ou `abandoned` tratado de forma genérica), ela é "reaberta" e reutilizada, permitindo nova conclusão e novo crédito de pontos sobre uma sessão que já estava finalizada. O comportamento correto é: só `abandoned` deve ser reativado; `completed` deve forçar a criação de uma **nova** sessão.

3. **`get_session_by_content` frágil a múltiplas rows:** a busca de sessão por conteúdo assume no máximo uma linha (ex.: `.single()` / `[0]`), mas o banco pode conter várias sessões para o mesmo `(user_id, content_id)` — exatamente o resíduo deixado por reaberturas e por ausência de constraint. Quando há múltiplas rows, a query quebra ou seleciona uma linha arbitrária, tornando o resultado não-determinístico.

> Dependências: **DATA-GAM-3** estabelece a base de unicidade/dedup de score por sessão (a borda onde o ponto é creditado 1×); **SEC-ADMIN-4** consolida a autorização/ownership dos endpoints de sessão. Esta story constrói a máquina de estados **sobre** ambas, sem reescrever a base de pontuação nem a base de auth.
>
> Coordenação de ownership de arquivo (roadmap, linha 130/329): `create_or_get_chat_session` (`routes_ai.py:776-810`) tem **dono único = TPP-2** (rewrite com `ON CONFLICT` upsert). DATA-GAM-4 **adiciona** os hooks de máquina de estados sobre o resultado de TPP-2 — **não reescreve** a função. Confirmar que TPP-2 já foi mergeado antes de editar.

## Acceptance Criteria
- [ ] **complete idempotente (no-op em terminal):** chamar `/complete` numa sessão que já está em `completed` retorna sucesso (ou 200/204 idempotente) **sem** recalcular score, **sem** reaplicar gamificação e **sem** efeitos colaterais. O score final permanece idêntico ao da primeira conclusão.
- [ ] **score 1× na borda:** o crédito de pontos ocorre exatamente uma vez, na transição `in_progress → completed`. N chamadas a `/complete` (sequenciais ou concorrentes) sobre a mesma sessão resultam em exatamente 1 crédito (validar contra a base de dedup de DATA-GAM-3).
- [ ] **transição proibida → 409:** qualquer transição que viole a máquina de estados (ex.: `completed → in_progress`, `abandoned → completed` sem reativação válida, ou estado inexistente) retorna **HTTP 409 Conflict** com mensagem clara, sem mutar o estado.
- [ ] **create_or_get só reativa `abandoned`:** ao chamar `create_or_get` para um `(user_id, content_id)`:
  - sessão existente `abandoned` → **reativada** (volta a `in_progress`), reutilizando a row;
  - sessão existente `completed` → **NÃO** é reaberta; cria-se uma **nova** sessão `in_progress`;
  - sessão existente `in_progress` → retorna a própria sessão ativa (idempotente).
- [ ] **get_session_by_content resiste a múltiplas rows:** com 2+ sessões para o mesmo `(user_id, content_id)`, a busca **não quebra** e retorna deterministicamente a sessão correta (ex.: a mais recente `in_progress`, com tie-break por `created_at`/`updated_at`), nunca uma row arbitrária e nunca exceção não tratada.
- [ ] **autorização preservada (herdada de SEC-ADMIN-4):** dono autorizado da sessão executa as transições normalmente; ator cruzado (sessão de outro usuário) recebe **403/404** e **nenhuma leitura-mutação** de estado ocorre; o `user_id` jamais é lido do body — sempre do contexto autenticado (`current_user`).
- [ ] **concorrência segura:** duas chamadas `/complete` simultâneas sobre a mesma sessão não geram double-credit nem estado inconsistente (proteção via transição condicional no UPDATE / `WHERE status = 'in_progress'` ou lock de linha).

## Tasks / Subtasks
- [ ] **Confirmar dependências mergeadas:** verificar no repo que TPP-2 (rewrite de `create_or_get_chat_session`), DATA-GAM-3 (dedup de score) e SEC-ADMIN-4 (ownership) já estão em `main`/branch base antes de iniciar.
- [ ] **Definir a state machine explicitamente** em `backend/app/routes_ai.py` (ou módulo de domínio correspondente, ex.: `services/sessions.py` se existir): estados `in_progress`, `completed`, `abandoned`; transições permitidas e tabela de transições proibidas. Centralizar a validação numa função `validate_transition(current, target) -> bool`.
- [ ] **Tornar `/complete` idempotente:** no handler de conclusão (`complete_chat_session` em `routes_ai.py`), adicionar guarda: se `session.status == 'completed'` → retornar no-op (sem recompute, sem regrade, sem crédito). Mover o crédito de score para dentro do bloco condicional da transição `in_progress → completed`.
- [ ] **UPDATE condicional para concorrência:** aplicar a transição de status com cláusula `WHERE status = 'in_progress'` (UPDATE atômico) e creditar o score apenas se o UPDATE afetou 1 linha — garantindo single-credit sob concorrência (alinhado à dedup de DATA-GAM-3).
- [ ] **Transições proibidas → 409:** em todos os endpoints que mutam status (complete, abandon, e quaisquer outros), validar via `validate_transition` e levantar `HTTPException(status_code=409)` quando a transição não for permitida.
- [ ] **Hooks de reativação em `create_or_get_chat_session` (`routes_ai.py:776-810`):** sobre o resultado de TPP-2, ramificar por status: `abandoned` → reativar (UPDATE para `in_progress`); `completed` → criar nova sessão; `in_progress` → retornar existente. NÃO reescrever a base do upsert de TPP-2.
- [ ] **Robustez de `get_session_by_content`:** trocar `.single()`/indexação ingênua por busca ordenada (`order_by` determinístico) + limit, ou agregação que tolere múltiplas rows, retornando a sessão alvo de forma estável.
- [ ] **Aplicar guarda de ownership** (de SEC-ADMIN-4) em todos os handlers tocados: `user_id` do `current_user`, nunca do body; sessão de outro usuário → 403/404 antes de qualquer mutação.
- [ ] **Testes de regressão** (ver Definition of Done) cobrindo idempotência, 409, reativação seletiva, múltiplas rows e concorrência.

## Dev Notes
- **Arquivos:**
  - `backend/app/routes_ai.py` — handler `/complete` (`complete_chat_session`) e `create_or_get_chat_session` (`routes_ai.py:776-810`), `get_session_by_content`.
  - Módulo de domínio/serviço de sessões, se existir (ex.: `backend/app/services/sessions.py`); caso contrário, centralizar a state machine numa função-helper no próprio `routes_ai.py`.
  - Camada de gamificação/score (a base de dedup vem de DATA-GAM-3 — reutilizar, não duplicar).
- **Abordagem:** introduzir uma máquina de estados explícita (`in_progress | completed | abandoned`) com tabela de transições permitidas; tornar `/complete` idempotente por guarda de estado terminal; garantir single-credit por UPDATE atômico condicional (`WHERE status='in_progress'`) + dedup de DATA-GAM-3; reativação seletiva apenas de `abandoned` no `create_or_get` (sobre o upsert de TPP-2); leitura de sessão por conteúdo tolerante a múltiplas rows com ordenação determinística. Toda mutação herda a guarda de ownership de SEC-ADMIN-4 (user do contexto autenticado, nunca do body).
- **Riscos de regressão (blast radius):**
  - **Dono de arquivo compartilhado:** `create_or_get_chat_session` (`routes_ai.py:776-810`) é editado por TPP-2 (dono), SEC-CHAT-2/3 e DATA-GAM-4. Merge fora de ordem pode desfazer o upsert de TPP-2 ou os hooks de auth de SEC-CHAT. **Editar por último / rebase sobre TPP-2 + SEC-CHAT antes do commit.**
  - **Fluxo de gamificação/score:** mudar a borda de crédito pode regredir a pontuação de alunos — validar contra DATA-GAM-3. Risco de undercounting se a guarda terminal for cedo demais, ou de double-credit se o UPDATE não for atômico.
  - **Quem chama o código tocado:** o frontend do tutor/chat que invoca `/complete` (possíveis retries) e o fluxo de início de sessão (`create_or_get`). Verificar que reativar só `abandoned` não quebra a UX de "retomar conversa" — `completed` agora abre sessão nova (comportamento intencional).
  - **Múltiplas rows legadas:** dados existentes podem já conter sessões duplicadas por `(user_id, content_id)` (resíduo do bug). A robustez de `get_session_by_content` deve tolerar esse legado sem migration obrigatória, mas registrar/observar para limpeza futura.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde, cobrindo: (a) `/complete` 2× → score creditado 1×; (b) `/complete` em `completed` → no-op sem recompute; (c) transição proibida → 409; (d) `create_or_get` reativa `abandoned` mas cria nova sessão quando `completed`; (e) `get_session_by_content` com múltiplas rows retorna deterministicamente; (f) concorrência: 2 `/complete` simultâneos → 1 crédito.
- [ ] Sem regressão na suíte de segurança (ownership de SEC-ADMIN-4 mantido: ator cruzado → 403/404, `user_id` nunca do body).
- [ ] QA Gate: PASS ou CONCERNS.
- [ ] Máquina de estados documentada (transições permitidas/proibidas) inline no código e/ou em comentário/docstring; coordenação de ownership de `routes_ai.py:776-810` confirmada com TPP-2 e SEC-CHAT antes do merge.

## QA Results
_(a preencher pelo @qa)_
