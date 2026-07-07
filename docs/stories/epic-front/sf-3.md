---
id: SF-3
epic: EPIC-FRONT
phase: 4
status: InReview
severity: HIGH
terminal: UX/UI & Design
complexity: medium
depends_on: [SEC-ADMIN-4, MEDIA-2, SF-1]
bug_refs: [24]
---
# SF-3: Ligar conclusão de conteúdo a progress/cert/session-complete por-user

## Story
Como aluno da Harven.AI, quero que ao clicar em "Concluir" um conteúdo o meu progresso seja registrado de forma confiável vinculado ao **meu** `user.id`, para que minha trilha avance, a sessão de chat seja fechada corretamente e eu veja um indicador visual de "Concluído" não-reclicável — sem que a ausência de tabelas opcionais no banco quebre minha experiência.

## Contexto (do bug sweep)
Item #24 do bug sweep: o fluxo de conclusão de conteúdo no frontend está desalinhado da camada de progresso/certificado por-usuário. O botão "Concluir" hoje não persiste o progresso de forma consistente por `user.id` e não fecha a sessão de chat associada, deixando o sintoma de que **"alunos nunca recebem progresso/certificado"** parcialmente aberto.

Pontos verificados:
- A ação de conclusão não chama `completeContent(user.id, ...)` de forma canônica e/ou chama `contentsApi.update({ completed })` indevidamente — `contents` é metadado de catálogo (compartilhado), não estado por-aluno; gravar `completed` ali contamina o conteúdo para todos os usuários e é o caminho errado para progresso.
- A sessão de chat não é finalizada via `chatSessionsApi.complete`, deixando sessões abertas penduradas.
- Quando as tabelas opcionais de progresso/certificado **não existem** (backend responde **503**), o frontend trata como erro duro e bloqueia a UX, em vez de aplicar **soft-success** (a conclusão visual deve prosseguir, com o backend degradando graciosamente).
- Não há feedback visual idempotente: após concluir, o botão deveria virar **badge "Concluído"** não-reclicável; hoje permanece clicável, permitindo dupla submissão.

Roadmap (linha 272): SF-3 deve fazer `'Concluir'` chamar `completeContent(user.id,...)` + `chatSessionsApi.complete`; **não** chamar `contentsApi.update({completed})`; tratar 503 como soft-success; em sucesso renderizar badge "Concluído" não-reclicável; certificado **adiado/documentado**.

Roadmap (linha 428): a emissão de certificado na conclusão de **curso** (`issueCertificate`) é **deliberadamente fora de escopo** desta Story ("course-completion detection out of scope"); SEC-ADMIN-4 (idor-admin-writes) endurece o endpoint mas nenhuma Story o liga ao fluxo end-to-end. Aceito como **follow-up documentado** — esta Story fecha a conclusão de **conteúdo** por-usuário, não a emissão de certificado de curso.

## Acceptance Criteria
- [ ] O clique em "Concluir" chama `completeContent(user.id, ...)` com o `user.id` derivado da sessão autenticada (nunca de `props`/estado mutável da UI), persistindo progresso por-aluno.
- [ ] O clique em "Concluir" chama `chatSessionsApi.complete` para a sessão de chat associada ao conteúdo, fechando a sessão.
- [ ] A ação **não** chama `contentsApi.update({ completed })` — confirmar por busca que essa chamada foi removida do caminho de conclusão (catálogo de conteúdo permanece imutável por essa ação).
- [ ] Quando o backend responde **503** (tabelas de progresso/certificado ausentes), o frontend aplica **soft-success**: a UI conclui visualmente (badge "Concluído") sem exibir erro bloqueante; um log/telemetria de degradação graciosa é registrado para diagnóstico.
- [ ] Em **sucesso (2xx)**, o botão "Concluir" é substituído por **badge "Concluído"** em estado não-reclicável (desabilitado/sem handler), prevenindo dupla submissão.
- [ ] **Idempotência de UI:** reentrar no conteúdo já concluído exibe o badge "Concluído" diretamente, sem reabilitar o botão.
- [ ] **Isolamento por-usuário (autorização):**
  - dono autorizado (o próprio aluno autenticado) conclui seu conteúdo e tem o progresso gravado com sucesso;
  - ator cruzado (tentando concluir em nome de outro `user_id`) recebe **403/404** e **nenhuma leitura-mutação ocorre** no progresso da vítima;
  - `body.user_id` (ou qualquer `user_id` vindo do cliente) **nunca é confiado** — o `user.id` usado é sempre o da sessão autenticada no servidor.
- [ ] Emissão de **certificado de curso** (`issueCertificate`) permanece **fora de escopo** e está explicitamente documentada como follow-up nesta Story e no roadmap (linha 428).

## Tasks / Subtasks
- [ ] Localizar o handler de "Concluir" no componente de visualização/leitura de conteúdo do frontend (provável `apps/web` — componente de conteúdo/lição) e mapear as chamadas atuais de API que dispara.
- [ ] Remover a chamada a `contentsApi.update({ completed })` do caminho de conclusão.
- [ ] Implementar a chamada canônica `completeContent(user.id, contentId, ...)` usando `user.id` da sessão autenticada (hook/contexto de auth), nunca de props.
- [ ] Adicionar a chamada `chatSessionsApi.complete(sessionId)` para a sessão de chat associada ao conteúdo.
- [ ] Implementar o tratamento de **503 → soft-success**: capturar o status, prosseguir com a transição visual para "Concluído" e registrar telemetria de degradação (sem `throw`/toast de erro bloqueante).
- [ ] Implementar o estado de UI **badge "Concluído"** não-reclicável: trocar o botão por badge em sucesso e em reentrada de conteúdo já concluído (derivado do progresso por-usuário).
- [ ] Garantir que `body.user_id` não seja enviado pelo cliente; confirmar que o backend (endpoint endurecido por SEC-ADMIN-4) ignora qualquer `user_id` do body e usa o da sessão.
- [ ] Adicionar/atualizar comentário e nota de escopo deixando claro que `issueCertificate` (conclusão de curso) é follow-up documentado.

## Dev Notes
- **Arquivos:**
  - Frontend (UX/UI): componente do leitor/visualizador de conteúdo em `apps/web` (handler de "Concluir") — confirmar caminho exato via grep por `completeContent`, `contentsApi.update`, `chatSessionsApi.complete` no repo.
  - Camada de API client do frontend: módulo que expõe `completeContent`, `chatSessionsApi.complete`, `contentsApi.update` (provável `apps/web/.../lib/api` ou similar).
  - Backend: endpoint de progresso/conclusão endurecido por **SEC-ADMIN-4** (idor-admin-writes) — fonte de verdade do `user.id` e responsável pelo 503 quando tabelas ausentes.
- **Abordagem:** centralizar a conclusão em `completeContent(user.id, ...)` (progresso por-aluno) + `chatSessionsApi.complete` (fechamento de sessão), removendo a mutação indevida de catálogo via `contentsApi.update`. Tratar 503 como degradação graciosa (soft-success) na UI. Estado visual idempotente derivado do progresso real do usuário, não de flag local volátil. Certificado de curso fica como follow-up.
- **Riscos de regressão / blast radius:**
  - Componentes/telas que dependiam do efeito colateral de `contentsApi.update({ completed })` para refletir conclusão — devem passar a ler o progresso por-usuário; verificar listagens de trilha/curso que mostravam "concluído" via flag de catálogo.
  - Fluxo de sessão de chat: chamar `chatSessionsApi.complete` pode afetar telas que listam sessões abertas — validar que não fecha sessão errada.
  - Depende de **SF-1** (estado/auth de frontend), **MEDIA-2** e **SEC-ADMIN-4** (endpoint de escrita endurecido) já aplicados; sem eles o `user.id` confiável e o endpoint seguro não estão garantidos.
  - O soft-success em 503 não deve mascarar erros reais (4xx/5xx ≠ 503) — manter tratamento de erro normal para outros status.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: cobre (a) "Concluir" chama `completeContent(user.id)` + `chatSessionsApi.complete` e **não** chama `contentsApi.update`; (b) 503 → soft-success com badge "Concluído"; (c) badge não-reclicável após sucesso e em reentrada.
- [ ] Sem regressão na suíte de segurança: ator cruzado recebe 403/404 e nenhuma mutação no progresso da vítima; `body.user_id` ignorado pelo servidor.
- [ ] QA Gate: PASS ou CONCERNS
- [ ] `issueCertificate` (conclusão de curso) documentado como follow-up out-of-scope nesta Story e referenciado ao roadmap (linha 428); nenhum acoplamento acidental introduzido a esse fluxo.

## QA Results
_(a preencher pelo @qa)_
