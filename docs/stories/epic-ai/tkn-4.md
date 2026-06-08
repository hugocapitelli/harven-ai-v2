---
id: TKN-4
epic: EPIC-AI
phase: 4
status: Draft
severity: HIGH
terminal: Backend & Infra
complexity: medium
depends_on: [TKN-3]
bug_refs: [12]
---
# TKN-4: Ligar budget em editor/tester/analyst (metade-budget de #12)

## Story
Como operador da plataforma Harven.AI, quero que os três métodos de IA do tutor (editor, tester, analyst) enforcem e registrem consumo no rastreador de budget real em vez de usar um mock, para que o controle de custo por usuário deixe de ser ignorado silenciosamente e usuários que estourem o cap recebam 503 em vez de continuar gastando tokens sem limite.

## Contexto (do bug sweep)
Bug #12 (item TKN, metade-budget): existe um rastreador de budget de IA já implementado, porém os três métodos do serviço de tutor — o que edita/reescreve (editor), o que testa/avalia (tester) e o que analisa (analyst) — não estão ligados ao rastreador real. Eles operam contra um stub/mock que sempre retorna budget disponível (efetivamente `0` de consumo registrado), de modo que:
- O enforcement de cap por usuário nunca dispara — qualquer usuário pode chamar os três métodos indefinidamente.
- O consumo desses três caminhos nunca é contabilizado no rastreador, distorcendo qualquer leitura de custo agregado.
- Os call sites desses métodos não propagam o `user_id` autenticado nem o client autenticado, então mesmo que o enforcement fosse ligado, não haveria identidade para aplicar o cap.

A complementaridade com TKN-3 ("metade-budget"): TKN-3 estabelece o caminho/infra de budget que estes três métodos precisam consumir. Esta story (TKN-4) é a outra metade — conectar os três métodos a esse caminho real. Por isso `depends_on: [TKN-3]`.

Impacto: custo descontrolado (FinOps), inconsistência de métricas de consumo e ausência de proteção contra abuso/exhaustion nos caminhos de editor/tester/analyst do tutor de IA.

## Acceptance Criteria
- [ ] Os três métodos (editor, tester, analyst) chamam o rastreador de budget **real** (não o mock) tanto para **verificar** o cap antes de gastar quanto para **registrar** o consumo após gastar — verificável por inspeção de código e por log/registro persistido.
- [ ] Com o mock substituído, o consumo registrado pelos três métodos deixa de ser `0`: após uma chamada bem-sucedida de cada método, o rastreador real reflete consumo > 0 para o `user_id` correspondente.
- [ ] Todos os **call sites** dos três métodos passam o `user_id` autenticado e o client autenticado (derivados da sessão/token, nunca de `body.user_id`); nenhum call site fica chamando os métodos sem identidade.
- [ ] **Desfecho — dentro do cap:** usuário autenticado com budget disponível executa editor/tester/analyst com sucesso; consumo é registrado no rastreador real.
- [ ] **Desfecho — sobre o cap:** usuário autenticado cujo consumo já atingiu/excede o cap recebe **HTTP 503** ao chamar qualquer um dos três métodos, e **nenhum** gasto adicional de IA é realizado (a chamada ao modelo é bloqueada antes do consumo).
- [ ] **Identidade nunca confiada do body:** `body.user_id` (ou qualquer `user_id` vindo do payload) nunca é usado para determinar o cap; a identidade vem exclusivamente do contexto autenticado.
- [ ] O comportamento dos três métodos quando há budget disponível permanece funcionalmente idêntico ao anterior (sem regressão de saída).

## Tasks / Subtasks
- [ ] Localizar o serviço de tutor que expõe os métodos editor/tester/analyst e identificar a injeção atual do rastreador de budget (o stub/mock que retorna sempre disponível).
- [ ] Substituir a dependência mock pelo rastreador de budget real estabelecido em TKN-3, injetando o client autenticado necessário.
- [ ] Em cada um dos três métodos, adicionar/garantir: (1) **check** de cap por `user_id` antes da chamada ao modelo; (2) **registro** de consumo após a chamada ao modelo bem-sucedida.
- [ ] Quando o check indicar cap atingido/excedido, abortar antes de chamar o modelo e propagar erro que resulte em **HTTP 503** na borda (handler/rota).
- [ ] Atualizar a assinatura dos três métodos para receber `user_id` + client autenticado e ajustar **todos os call sites** (rotas/handlers/orquestradores que invocam editor/tester/analyst) para passar a identidade autenticada — removendo qualquer dependência de `body.user_id`.
- [ ] Garantir que a rota/handler mapeie a exceção de cap excedido para status **503** (e não 400/500 genérico).
- [ ] Escrever teste de regressão: (a) chamada dentro do cap → sucesso + consumo registrado > 0; (b) usuário sobre o cap → 503 + nenhum gasto de IA; (c) tentativa de injetar `body.user_id` distinto → ignorado, identidade autenticada prevalece.

## Dev Notes
- **Arquivos:** serviço de tutor de IA do backend (`harven-ai-v2`) que contém os métodos editor/tester/analyst; o módulo do rastreador de budget de IA (o real, alvo de TKN-3, hoje substituído por mock nestes três caminhos); as rotas/handlers que expõem esses três métodos (onde a sessão autenticada está disponível e onde o mapeamento para HTTP 503 deve ocorrer). Confirmar os paths exatos via grep pelos nomes dos três métodos e pela injeção do mock no momento da implementação.
- **Abordagem:** trocar a dependência mock pelo budget tracker real e padronizar o par check-antes / registra-depois nos três métodos, alinhado ao caminho criado em TKN-3. A identidade (`user_id` + client autenticado) flui da borda autenticada para os métodos; o body do request nunca é fonte de identidade. Cap excedido → exceção dedicada → mapeada para 503 no handler.
- **Riscos de regressão:** mudança na assinatura dos três métodos afeta TODOS os seus call sites (rotas e quaisquer orquestradores internos do tutor) — qualquer call site não atualizado quebra (d=1, WILL BREAK). Ligar o enforcement real pode passar a bloquear (503) usuários que antes nunca eram barrados — comportamento correto, mas observável em produção. O registro de consumo agora não-zero altera métricas/dashboards de custo. Depende de TKN-3 estar concluído (o caminho/infra de budget real deve existir e estar correto antes de conectar estes métodos).

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde
- [ ] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [ ] Mock confirmado removido dos três caminhos: consumo registrado no rastreador real é > 0 após uma chamada de cada método; usuário sobre o cap recebe 503 sem gasto adicional; nenhum call site usa `body.user_id` para identidade.

## QA Results
_(a preencher pelo @qa)_
