---
id: SF-2
epic: EPIC-FRONT
phase: 4
status: InReview
severity: HIGH
terminal: UX/UI & Design
complexity: low
depends_on: [MEDIA-2]
bug_refs: [23]
---
# SF-2: Rotear 'Reprocessar IA' pelo axios compartilhado com token correto

## Story
Como professor (TEACHER) ou administrador (ADMIN) gerenciando conteúdo do curso, quero que o botão "Reprocessar IA" chame o backend pela mesma camada axios autenticada usada pelo restante do app, para que o reprocessamento de conteúdo funcione com o token de sessão válido em vez de falhar silenciosamente por `Authorization` ausente/incorreto.

## Contexto (do bug sweep)
Item #23 — O acionador de "Reprocessar IA" no frontend não usa o cliente axios compartilhado (que injeta automaticamente o `Authorization: Bearer <token>` via interceptor). Em vez disso, ele faz uma chamada `fetch` manual lendo o token de `sessionStorage.getItem('access_token')`. Esse token ou está desatualizado, ou vazio, ou armazenado sob chave divergente da fonte de verdade da sessão (o token real é mantido/renovado pela camada axios/`authApi`), de modo que a requisição chega ao backend sem credencial válida. Resultado: o endpoint de reprocessamento responde 401/403 e o usuário TEACHER/ADMIN — que deveria ter permissão — vê falha ou nenhuma ação, com os três desfechos de UI (success / empty / error) intactos no código mas nunca exercitados pelo caminho de sucesso real. A correção é canalizar a chamada por `aiApi.reprocessContent`, que posta em `/api/ai/reprocess-content` através do axios compartilhado, eliminando o `fetch` manual e a leitura de `sessionStorage`.

## Acceptance Criteria
- [ ] Existe (ou é criado) um método `aiApi.reprocessContent(...)` que posta em `/api/ai/reprocess-content` usando a instância axios compartilhada do app (a mesma que aplica o interceptor de `Authorization`).
- [ ] O handler do botão "Reprocessar IA" chama `aiApi.reprocessContent(...)`; nenhuma chamada `fetch` direta permanece nesse fluxo.
- [ ] Nenhuma referência a `sessionStorage.getItem('access_token')` (nem leitura/montagem manual de header `Authorization`) permanece no fluxo de reprocessamento — o token vem exclusivamente do interceptor axios.
- [ ] Um usuário autenticado com role TEACHER ou ADMIN consegue reprocessar conteúdo com sucesso (a requisição chega ao backend com o token correto e retorna 2xx).
- [ ] Os três branches de UI são preservados e funcionam: **success** (reprocessamento aceito → feedback de sucesso), **empty** (resposta sem conteúdo a reprocessar → estado vazio tratado), **error** (falha → toast/mensagem de erro, sem quebrar a tela).
- [ ] Nenhuma regressão visual ou comportamental nos demais botões/ações da tela de conteúdo.

## Tasks / Subtasks
- [ ] Localizar o componente/handler atual de "Reprocessar IA" no frontend (`frontend/src/`) que usa `fetch` + `sessionStorage.getItem('access_token')`.
- [ ] Confirmar/criar o método `reprocessContent` no objeto `aiApi` (provável `frontend/src/services/api.ts` ou `frontend/src/api/ai.ts`), postando em `/api/ai/reprocess-content` via a instância axios compartilhada (sem header `Authorization` manual — deixar o interceptor injetar).
- [ ] Substituir o `fetch` manual no handler por `await aiApi.reprocessContent(...)`, passando o mesmo payload (id de conteúdo/parâmetros) que a chamada antiga enviava.
- [ ] Remover a leitura de `sessionStorage.getItem('access_token')` e qualquer montagem manual de headers nesse fluxo.
- [ ] Mapear o resultado de `aiApi.reprocessContent` para os branches existentes success/empty/error (preservar mensagens/toasts e estados de loading atuais).
- [ ] Validar manualmente como TEACHER e como ADMIN que o reprocessamento conclui com sucesso e que os três branches disparam corretamente conforme a resposta.

## Dev Notes
- **Arquivos:** componente da tela de conteúdo/gerenciamento que renderiza o botão "Reprocessar IA" (em `frontend/src/`); camada de serviço `aiApi` (provável `frontend/src/services/api.ts` ou `frontend/src/api/ai.ts`); instância axios compartilhada com interceptor de auth (provável `frontend/src/services/http.ts` / `axios` config). Endpoint backend já existente: `POST /api/ai/reprocess-content`.
- **Abordagem:** trocar o `fetch` manual por chamada via `aiApi.reprocessContent`, que reaproveita a instância axios compartilhada cujo interceptor injeta o `Authorization` a partir da fonte de verdade da sessão. Eliminar a dependência de `sessionStorage.getItem('access_token')`, que era a causa raiz do token incorreto/ausente. Manter inalterada a estrutura dos três branches de UI (success/empty/error) — apenas a origem da chamada muda.
- **Riscos de regressão:** blast radius baixo e localizado ao fluxo de reprocessamento. Verificar que (a) o payload enviado a `/api/ai/reprocess-content` permanece idêntico ao que o `fetch` enviava (mesmos campos/nomes), evitando 422 no backend; (b) o tratamento de erro do axios (que lança em status não-2xx) seja capturado pelo branch `error` — diferente do `fetch`, que não lança em 4xx/5xx; (c) `depends_on: MEDIA-2` — confirmar que a camada axios/serviço de mídia tocada em MEDIA-2 já está estável antes de mesclar, para não conflitar com a instância compartilhada.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde
- [ ] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [ ] Grep no fluxo de reprocessamento confirma zero ocorrências de `fetch(` e de `sessionStorage.getItem('access_token')`; chamada passa por `aiApi.reprocessContent` → `/api/ai/reprocess-content`; smoke manual TEACHER e ADMIN com sucesso e os três branches (success/empty/error) exercitados.

## QA Results
_(a preencher pelo @qa)_
