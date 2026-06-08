---
id: CDC-1
epic: EPIC-CLEANUP
phase: 5
status: Draft
severity: MEDIUM
terminal: Backend & Infra & UX/UI & Design
complexity: low
depends_on: []
bug_refs: [46]
---
# CDC-1: Enum canônico de role de mensagem (backend schema + frontend type)

## Story
Como desenvolvedor backend e frontend do Harven.AI, quero um conjunto canônico e único de valores de `role` para mensagens de chat — `{user, assistant, instructor, system}` — validado no schema do backend e espelhado no tipo TypeScript do frontend, para que o contrato de papéis de mensagem seja consistente entre as camadas, rejeite valores inválidos com 422 e elimine a divergência que faz mensagens de instrutor serem tratadas incorretamente.

## Contexto (do bug sweep)
O defeito #46 reporta um contrato de `role` divergente entre backend e frontend para mensagens de sessão de chat. O endpoint `POST /chat-sessions/{id}/messages` aceitava o campo `role` sem um enum restritivo no schema Pydantic, permitindo que valores fora do conjunto canônico passassem silenciosamente, enquanto o frontend operava com uma noção de papéis incompatível — em particular, mensagens de instrutor não tinham um valor de `role` próprio reconhecido em ambas as pontas. A consequência prática (detalhada em CDC-2, dependente desta story) é que a mensagem do instrutor é renderizada como se fosse da "IA" (assistant), perdendo a distinção de autor. Esta story estabelece o enum canônico de quatro valores `{user, assistant, instructor, system}` como fonte da verdade no schema do backend e o tipo `ChatRole` equivalente no frontend, sem quebrar os callers existentes que já enviam `user`/`assistant`.

## Acceptance Criteria
- [ ] O schema Pydantic do payload de criação de mensagem em `POST /chat-sessions/{id}/messages` valida `role` contra o enum canônico `{user, assistant, instructor, system}`.
- [ ] Um `POST` com `role` dentro do conjunto canônico (ex.: `instructor`) é aceito (2xx) e persistido com o valor exato.
- [ ] Um `POST` com `role` fora do conjunto canônico (ex.: `bot`, `tutor`, string vazia, `null`, ou qualquer outro valor) retorna **422 Unprocessable Entity** e a mensagem NÃO é persistida.
- [ ] O tipo TypeScript `ChatRole` no frontend é exatamente o union `'user' | 'assistant' | 'instructor' | 'system'` (mesmo conjunto, mesma grafia que o backend).
- [ ] Callers existentes que enviam `role: 'user'` e `role: 'assistant'` continuam funcionando sem alteração de comportamento (regressão nula).
- [ ] OpenAPI/schema gerado expõe o enum de `role` (documentação do contrato refletida).

## Tasks / Subtasks
- [ ] Backend: localizar o schema Pydantic do payload de criação de mensagem usado por `POST /chat-sessions/{id}/messages` (em `backend/app/schemas/` — provável `chat_session.py`/`chat_sessions.py` ou módulo equivalente do router de chat-sessions) e trocar o campo `role: str` por um `Enum`/`Literal` canônico `MessageRole = {user, assistant, instructor, system}`.
- [ ] Backend: garantir que o enum seja a fonte única — exportá-lo do módulo de schemas e reaproveitá-lo em qualquer ponto que hoje compare/atribua `role` por string literal solta.
- [ ] Backend: confirmar que o handler do router de chat-sessions persiste o `role` validado sem normalização extra (ex.: sem lowercasing silencioso que mascararia valores inválidos).
- [ ] Frontend: localizar e definir/atualizar o tipo `ChatRole` (em `frontend/src/types/` ou no módulo de tipos de chat — ex.: `chat.ts`/`chatSession.ts`) para o union de quatro valores, e referenciar `ChatRole` nas interfaces de mensagem existentes.
- [ ] Frontend: substituir quaisquer literais soltas de `role` por usos do tipo `ChatRole` nos callers de envio de mensagem, sem alterar a semântica de `user`/`assistant`.
- [ ] Teste de regressão backend: caso feliz (`instructor` → 2xx, persistido) + caso negativo (`bot`/`""`/inválido → 422, não persistido) + casos legados (`user`, `assistant` → 2xx).

## Dev Notes
- **Arquivos:**
  - Backend: schema Pydantic do payload de mensagem do router de chat-sessions, em `backend/app/schemas/` (provável `chat_session.py` ou equivalente); router em `backend/app/routers/` (endpoint `POST /chat-sessions/{id}/messages`).
  - Frontend: tipo `ChatRole` em `frontend/src/types/` (módulo de tipos de chat) e callers de envio em componentes/serviços de chat-session (ex.: `SessionReview` e serviço de API de chat).
- **Abordagem:** Introduzir um único enum canônico no backend (`Enum`/`Literal` Pydantic) como fonte da verdade do contrato; espelhar manualmente o mesmo union em `ChatRole` no TypeScript. A mudança é aditiva no contrato (adiciona `instructor`/`system` ao conjunto reconhecido) e endurecedora na validação (passa a rejeitar valores fora do conjunto com 422). Não alterar a forma do payload nem nomes de campos.
- **Riscos de regressão:** Blast radius baixo. (1) Qualquer caller backend/serviço de teste que hoje envie um `role` fora de `{user, assistant, instructor, system}` passará a receber 422 — verificar fixtures/seeds e chamadas internas. (2) O endpoint `POST /chat-sessions/{id}/messages` é a superfície tocada; consumidores diretos: o frontend de sessão de chat (`SessionReview` e serviço de API). (3) No frontend, restringir `ChatRole` pode gerar erros de tipo em pontos que atribuíam strings arbitrárias a `role` — esses pontos devem ser reconciliados para os quatro valores canônicos. (4) Esta story é dependência de **CDC-2** (render distinto do instrutor + paridade otimista); manter a grafia exata `instructor` evita retrabalho lá.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: `role` inválido → 422 e não-persistência; `instructor`/`system`/`user`/`assistant` → 2xx persistido.
- [ ] Sem regressão na suíte de segurança (validação de payload não afrouxa autorização nem expõe novos campos).
- [ ] QA Gate: PASS ou CONCERNS.
- [ ] Backend e frontend usam o MESMO conjunto canônico de valores (paridade verificada: enum Pydantic ≡ union `ChatRole`); OpenAPI reflete o enum; callers legados de `user`/`assistant` intactos.

## QA Results
_(a preencher pelo @qa)_
