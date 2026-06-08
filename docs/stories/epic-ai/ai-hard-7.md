---
id: AI-HARD-7
epic: EPIC-AI
phase: 4
status: Draft
severity: HIGH
terminal: Backend & Infra
complexity: low
depends_on: [AI-HARD-4]
bug_refs: [31]
---
# AI-HARD-7: Surfacear estado degraded/mock (não impersonar tutor)

## Story
Como instrutor/operador da plataforma Harven.AI, quero que respostas geradas em modo mock/degradado carreguem uma flag explícita (`degraded:true` + razão / `mock:true`) e gerem um WARN no log, para que eu saiba quando o tutor socrático NÃO está entregando valor real (key malconfigurada no deploy) em vez de o sistema impersonar um tutor funcional de forma invisível ao aluno e ao instrutor.

## Contexto (do bug sweep)
Item #31 do BUG-SWEEP — `backend/services/ai_service.py:422-424, 593-604`.

`socratic_dialogue` só captura `AIServiceError` contendo `'MOCK_MODE'` para acionar o fallback canned (`_mock_socratic`, l.422-424). Quando o serviço sobe em mock mode (API key ausente/placeholder no startup), `_mock_socratic` (l.427-463) retorna prompts hardcoded chapter-agnostic que ignoram completamente a `student_message` e a lição — e ainda assim a resposta é entregue ao aluno com a MESMA estrutura de uma resposta real (`response.content`, `analytics.model_used="mock"` é o único sinal, enterrado em analytics e nunca surfaçado ao chamador como flag de topo).

Em `edit_response`, o branch mock (l.593-604) retorna o texto do orientador **inalterado** (`edited_text: orientador_response`) rotulando-o como editado — `model_used="mock"`, mas sem flag explícita `mock:true` no nível esperado pelo consumidor.

**Impacto:** se a key estiver malconfigurada no deploy, alunos recebem filler genérico que ignora o input e a lição — o tutor *parece* funcionar mas não entrega valor socrático, e isso é **invisível** tanto ao aluno quanto ao instrutor. Não há WARN no log no momento em que se serve mock, então a degradação passa despercebida em produção.

**Gatilho corrigido (escopo):** a degradação só ocorre em **mock_mode no startup** (key ausente/placeholder). Falha de quota/rede em runtime NÃO entra aqui — essa continua virando 500/503 (tratada por AI-HARD-4). Esta story NÃO altera o comportamento de erro de runtime.

## Acceptance Criteria
- [ ] Respostas servidas em estado degradado (mock no startup, empty-choices/empty-content tratados por AI-HARD-4 quando caem em fallback socrático) carregam um campo de topo `degraded: true` acompanhado de `reason` (string descritiva: ex. `"mock_mode_no_api_key"`, `"empty_content_fallback"`).
- [ ] `socratic_dialogue` em mock (`_mock_socratic`) retorna o payload existente acrescido de `degraded: true` + `reason` no nível de topo, sem remover/renomear nenhum campo atual (`response.content`, `session_status`, `analytics`).
- [ ] `edit_response` em mock retorna o payload existente acrescido de `mock: true` (e `degraded: true` + `reason`) no nível de topo; `edited_text` permanece o texto do orientador inalterado, mas agora explicitamente sinalizado como não-editado.
- [ ] Sempre que uma resposta mock/degradada é servida, um log `WARN` é emitido (logger do `ai_service`) identificando o método (`socratic_dialogue`/`edit_response`) e a razão.
- [ ] A mudança é **puramente aditiva**: nenhum campo existente é removido, renomeado ou alterado em tipo. O frontend não é tocado e continua funcionando sem alteração (campos novos são ignorados se não consumidos).
- [ ] Quando o serviço opera normalmente (key válida, resposta real do OpenAI), `degraded`/`mock` NÃO aparecem como `true` (ausentes ou `false`), e nenhum WARN de degradação é emitido.
- [ ] Falha de quota/rede em runtime continua virando exceção/erro HTTP (não é mascarada como degraded — fora de escopo desta story, comportamento de AI-HARD-4 preservado).

## Tasks / Subtasks
- [ ] Em `backend/services/ai_service.py`, no retorno de `_mock_socratic` (l.447-463), adicionar `degraded: True` e `reason: "mock_mode_no_api_key"` no dict de topo, preservando `response`/`session_status`/`analytics` intactos.
- [ ] No branch mock de `edit_response` (l.594-603), adicionar `mock: True`, `degraded: True` e `reason: "mock_mode_no_api_key"` ao dict retornado, mantendo `edited_text=orientador_response` e demais campos.
- [ ] Emitir `logger.warning(...)` no ponto em que cada fallback mock é servido (em `socratic_dialogue` l.422-424 antes/ao chamar `_mock_socratic`, e no branch mock de `edit_response` l.593-604), incluindo método e razão.
- [ ] Alinhar a `reason`/flag de fallback socrático introduzido por AI-HARD-4 (diálogo vazio → fallback socrático) para também carregar `degraded:true`+`reason` consistente (ex. `"empty_content_fallback"`), reusando o mesmo contrato de campos.
- [ ] Garantir que o caminho de sucesso (resposta real) NÃO injeta `degraded/mock` (ou injeta `false`), confirmando ausência de WARN.

## Dev Notes
- **Arquivos:** `backend/services/ai_service.py` (métodos `socratic_dialogue` ~l.422-425, `_mock_socratic` l.427-463, `edit_response` mock branch l.593-604). Sem alteração em frontend.
- **Abordagem:** mudança aditiva e cirúrgica. O sinal de degradação hoje existe apenas implicitamente em `analytics.model_used == "mock"`. Promover isso a um contrato explícito de topo (`degraded:true`+`reason`; `mock:true` para edit) e adicionar observabilidade (`WARN`). Reusar/estender o contrato de fallback de AI-HARD-4 (que já introduz fallback socrático para diálogo vazio) para manter um único formato de flag de degradação em todos os caminhos.
- **Riscos de regressão:** baixo. Blast radius = consumidores das respostas de `socratic_dialogue` e `edit_response` — as rotas em `backend/routes_ai.py` e, transitivamente, o frontend do tutor. Como a mudança é estritamente aditiva (novos campos de topo), nenhum consumidor existente quebra; o risco é apenas se algum serializador/validação de resposta rejeitar campos extras (verificar que os response models/Pydantic em `routes_ai.py` não usam `extra="forbid"`). Não alterar shape de `response.content` nem `edited_text` — frontend depende deles.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: teste que sobe o serviço em mock mode, chama `socratic_dialogue` e `edit_response`, e asserta `degraded is True` + `reason` presente (e `mock is True` no edit) — falhava antes do fix (campos inexistentes).
- [ ] Teste confirma que no caminho de sucesso (mock desligado) `degraded`/`mock` não são `true` e nenhum WARN de degradação é logado.
- [ ] Teste confirma que um WARN é emitido ao servir cada resposta mock.
- [ ] Sem regressão na suíte de segurança.
- [ ] QA Gate: PASS ou CONCERNS.
- [ ] Verificado manualmente que o frontend do tutor continua renderizando normalmente com os campos novos presentes (aditivo, não-disruptivo).

## QA Results
_(a preencher pelo @qa)_
