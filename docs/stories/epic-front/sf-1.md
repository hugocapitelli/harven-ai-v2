---
id: SF-1
epic: EPIC-FRONT
phase: 4
status: Draft
severity: HIGH
terminal: UX/UI & Design
complexity: low
depends_on: [MEDIA-2]
bug_refs: [21]
---
# SF-1: Resetar estado local do chat no close (re-habilitar botões socráticos)

## Story
Como aluno do Harven.AI consumindo um conteúdo, quero que o painel do tutor IA volte ao estado inicial quando eu o fecho, para poder selecionar qualquer pergunta socrática novamente e iniciar um novo diálogo sem precisar recarregar a página.

## Contexto (do bug sweep)
Item #21 (HIGH) — `frontend/src/views/courses/ChapterReader.tsx:1090-1095, 913-914, 333-337`.

O botão de fechar do chat executa apenas `setChatOpen(false)` inline; ele nunca reseta `selectedQuestion`, `sessionId` nem `chatMessages`. Os botões de pergunta socrática são gateados por `!selectedQuestion && startChat(...)` (handler de clique) e por `disabled={Boolean(selectedQuestion && selectedQuestion !== q.question)}`. Como `selectedQuestion` permanece setado após o primeiro fechamento, todos os demais botões ficam `disabled` permanentemente e o botão original vira no-op.

**Impacto:** Toda vez que o aluno abre e fecha o painel de chat (dentro do ciclo de vida do mount do componente), perde acesso ao tutor IA pelo resto da visualização do conteúdo — sem motivo visível e recuperável apenas navegando para fora/reload. Defeito de regressão funcional que silencia uma feature central de aprendizagem.

## Acceptance Criteria
- [ ] Ao fechar o painel de chat, o estado local é resetado: `chatOpen=false`, `selectedQuestion=null`, `sessionId=null`, `chatMessages=[]` (não mais um `setChatOpen(false)` inline isolado).
- [ ] Após abrir e fechar o chat uma ou mais vezes, todos os botões de pergunta socrática voltam a ficar habilitados (`disabled=false`) — nenhum botão permanece travado.
- [ ] Clicar em qualquer pergunta socrática após um fechamento inicia um novo diálogo (novo `sessionId`/nova sessão via `startChat`), e não um no-op.
- [ ] O gate de seleção (`disabled={Boolean(selectedQuestion && selectedQuestion !== q.question)}`) só bloqueia outros botões enquanto há um diálogo ativo aberto, e libera assim que o painel é fechado.
- [ ] Não há mais nenhuma chamada `setChatOpen(false)` inline que feche o painel sem passar pelo handler de reset.
- [ ] Reabrir o chat e selecionar uma pergunta diferente da anterior funciona sem reload da página.

## Tasks / Subtasks
- [ ] Em `frontend/src/views/courses/ChapterReader.tsx`, criar/centralizar um handler `closeChat` (ou `handleCloseChat`) que faça `setChatOpen(false); setSelectedQuestion(null); setSessionId(null); setChatMessages([])`.
- [ ] Substituir a chamada inline `setChatOpen(false)` do botão de fechar (≈linhas 1090-1095) pelo novo `closeChat`.
- [ ] Auditar o arquivo por outras ocorrências de `setChatOpen(false)` inline e roteá-las pelo handler único de reset (ou confirmar que não devem resetar estado, justificando).
- [ ] Revisar o gate dos botões socráticos (≈linhas 913-914 e 333-337) garantindo que o reset de `selectedQuestion` re-habilita todos os botões; ajustar a condição `disabled` se necessário para depender também de `chatOpen`.
- [ ] Validar manualmente o fluxo abrir → fechar → selecionar outra pergunta → novo diálogo, sem reload.

## Dev Notes
- **Arquivos:** `frontend/src/views/courses/ChapterReader.tsx` (linhas relevantes: 1090-1095 botão close, 913-914 e 333-337 gating dos botões socráticos).
- **Abordagem:** Centralizar o teardown do chat em um único handler de close que limpa `selectedQuestion`, `sessionId` e `chatMessages` além de `chatOpen`. Como o gating depende de `selectedQuestion`, o reset desse estado é suficiente para re-habilitar os botões; opcionalmente endurecer o `disabled` para também considerar `chatOpen` como guarda explícita. Mudança puramente client-side, sem alteração de contrato de API.
- **Riscos de regressão:** Blast radius restrito ao componente `ChapterReader.tsx` (estado local do painel de chat). Verificar que limpar `chatMessages`/`sessionId` no close não interfere com qualquer persistência de sessão pendente (`startChat`/`chatSessionsApi`). Esta story depende de **MEDIA-2** (remoção do `@ts-nocheck` em `ChapterReader.tsx`), que deve rebaseiar primeiro; SF-2/SF-3 e POD frontend também tocam este arquivo, então coordenar ordem de merge para evitar conflito.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde
- [ ] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [ ] Reproduzido manualmente o cenário do bug #21 (abrir/fechar/reselecionar) confirmando que os botões socráticos permanecem funcionais sem reload, e nenhum `setChatOpen(false)` inline órfão restou no arquivo.

## QA Results
_(a preencher pelo @qa)_
