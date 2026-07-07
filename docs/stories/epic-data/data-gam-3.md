---
id: DATA-GAM-3
epic: EPIC-DATA
phase: 4
status: InReview
severity: HIGH
terminal: Backend & Infra
complexity: medium
depends_on: [TPP-4]
bug_refs: [42]
---
# DATA-GAM-3: Computar + persistir performance_score na conclusão

## Story
Como aluno e como professor/admin que acompanham o progresso, quero que o `performance_score` da sessão de tutoria seja efetivamente computado e persistido quando a sessão é concluída, para que os dashboards de gamificação e progresso exibam médias e pontuações reais em vez de zero.

## Contexto (do bug sweep)
Item #42 do bug sweep: o campo `performance_score` da sessão de tutoria nunca é populado na borda de conclusão. O endpoint `complete_chat_session` (`routes_ai.py:914-931`) finaliza a sessão (marca `status='completed'`, grava `completed_at`) mas não calcula nem grava um score de desempenho. Como consequência, todas as sessões concluídas têm `performance_score` nulo/zero, e os dashboards de gamificação e progresso que agregam esse campo exibem **média 0** mesmo para sessões em que o aluno efetivamente respondeu e interagiu. O sinal de desempenho dos turnos persistidos (via TPP-4) existe no banco, mas não é consolidado em um score na conclusão. Isso degrada a percepção de valor da feature de tutoria sem impactar a nota oficial (gradebook), que é calculada por outro caminho.

Dependência: **TPP-4** garante a persistência completa dos turnos (perguntas, respostas, correção/avaliação por turno). Sem os turnos persistidos de forma confiável, não há sinal suficiente para computar o score. Por isso esta story consome os dados já gravados por TPP-4 na borda completed.

## Acceptance Criteria
- [ ] Existe uma função **pura** `compute_performance_score(turns)` (sem I/O, sem acesso a DB, sem efeitos colaterais) que recebe os turnos/sinais da sessão e retorna o score.
- [ ] O score retornado é sempre **clampado em [0, 100]** (qualquer valor calculado abaixo de 0 vira 0; acima de 100 vira 100).
- [ ] Quando o sinal é **insuficiente** (sessão sem turnos avaliáveis / sem dados suficientes para pontuar), a função retorna **`None`** — nunca 0 forçado, para não poluir a média com falsos zeros.
- [ ] A borda de conclusão `complete_chat_session` (`routes_ai.py:914-931`) chama `compute_performance_score` e **persiste** o resultado no campo `performance_score` da sessão quando o valor não é `None`.
- [ ] Após concluir uma sessão pontuável, os **dashboards de gamificação/progresso exibem média > 0** para essa sessão (verificável de ponta a ponta: concluir sessão com turnos avaliados → consultar dashboard → média da sessão > 0).
- [ ] O **gradebook permanece inalterado** — nenhuma alteração na nota oficial nem no caminho de cálculo do gradebook; `performance_score` é métrica de gamificação/progresso, não nota.
- [ ] O score é gravado **uma única vez** na borda completed (sem recomputar em chamadas idempotentes; alinhado com a state machine de DATA-GAM-4, que dependerá desta story).
- [ ] A computação é resiliente: falha ao calcular o score **não** impede a conclusão da sessão (a conclusão é a operação primária; o score é aditivo).

## Tasks / Subtasks
- [ ] Implementar `compute_performance_score(turns)` como função pura no módulo de domínio/serviço de tutoria (ex.: junto ao `ai_service.py` ou um módulo `scoring.py` dedicado), definindo a heurística de pontuação a partir dos sinais de turno persistidos por TPP-4 (acertos/avaliação por turno).
- [ ] Garantir clamp explícito `max(0, min(100, score))` e retorno `None` quando `not turns` ou nenhum turno tem sinal avaliável.
- [ ] Em `routes_ai.py:914-931` (`complete_chat_session`), na borda de conclusão, carregar os turnos persistidos da sessão, chamar `compute_performance_score` e atribuir/persistir `performance_score` quando o resultado não for `None`. Aplicar como **hook aditivo** sobre a versão produzida por TPP (conforme nota de sequenciamento do roadmap, `routes_ai.py:914-931` tem TPP como shape e DATA-GAM-3/4 como hooks aditivos).
- [ ] Confirmar que o caminho do gradebook não lê/escreve `performance_score` (verificar que continua independente).
- [ ] Testes unitários da função pura: turnos sem sinal → `None`; sessão perfeita → 100 (clamp no teto); sessão ruim → não-negativo (clamp no piso); valores intermediários determinísticos.
- [ ] Teste de integração da borda completed: concluir sessão pontuável grava `performance_score` no DB; concluir sessão sem sinal mantém `None`; segunda chamada de `/complete` não recomputa.

## Dev Notes
- **Arquivos:**
  - `routes_ai.py` — `complete_chat_session` (linhas ~914-931), borda de conclusão da sessão.
  - `ai_service.py` (ou novo `scoring.py` no mesmo pacote de serviço) — local da função pura `compute_performance_score`.
  - Modelo/tabela de sessão de tutoria — campo `performance_score` (persistência).
- **Abordagem:** Separar **cálculo puro** (testável, sem I/O) da **persistência** (na rota). A função recebe os turnos/sinais já carregados, retorna `int|float|None`. A rota orquestra: carrega turnos persistidos por TPP-4 → computa → persiste se não-`None` → conclui sessão. Tratar exceção do cálculo de forma defensiva para não bloquear a conclusão.
- **Riscos de regressão (blast radius):**
  - `routes_ai.py:914-931` é **alta-contenção**: editado por SEC-CHAT-3, DATA-GAM-3/4 e INT-MOODLE-4, e tem shape definido por **TPP**. Aplicar esta story como hook **aditivo** sobre a versão TPP — não reescrever a borda, apenas inserir computar+persistir score.
  - `ai_service.py` (corpo dos 5 métodos) é tocado por **ASYNC-AI** (flip async); se DATA-GAM-3 incidir sobre `ai_service.py`, aplicar sobre a versão async para evitar conflito.
  - **DATA-GAM-4** depende desta story (idempotência do complete + score 1× na borda); garantir que o ponto de gravação seja único e idempotente para não duplicar/recomputar.
  - Dashboards de gamificação/progresso passam a exibir valores reais — validar que não havia hardcode de 0 nem fallback que mascarasse o campo.
  - **Não** tocar no caminho do gradebook (nota oficial) — confirmar isolamento.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: antes, sessão concluída tem `performance_score` nulo/0; depois, sessão pontuável tem score em (0,100] persistido e dashboard com média > 0.
- [ ] Sem regressão na suíte de segurança (autorização da rota de conclusão preservada; nenhuma leitura/escrita cross-tenant introduzida).
- [ ] QA Gate: PASS ou CONCERNS
- [ ] `compute_performance_score` é pura (sem I/O), com clamp [0,100] e retorno `None` para sinal insuficiente, coberta por testes unitários determinísticos.
- [ ] Gradebook verificadamente inalterado (nota oficial e seu caminho de cálculo não dependem de `performance_score`).
- [ ] Score gravado exatamente uma vez na borda completed; segunda conclusão não recomputa (compatível com DATA-GAM-4).

## QA Results
_(a preencher pelo @qa)_
