---
id: CDC-2
epic: EPIC-CLEANUP
phase: 5
status: Draft
severity: MEDIUM
terminal: UX/UI & Design
complexity: low
depends_on: [CDC-1]
bug_refs: [46]
---
# CDC-2: SessionReview — renderizar instrutor distinto + paridade de role otimista

## Story
Como instrutor revisando a sessão de um aluno, quero que minhas mensagens apareçam com um autor e rótulo próprios (não como "IA") tanto no envio quanto após o reload, para que a revisão socrática mostre com clareza quem disse o quê e eu confie no histórico da conversa.

## Contexto (do bug sweep)
**Bug #46 (Contrato)** — `frontend/src/views/instructor/SessionReview.tsx:143`.

O instrutor persiste a mensagem com `role: 'instructor'`. O schema inline do backend (`backend/.../routes_ai.py:122`) aceita `role: str` sem enum, então a gravação passa. Porém o tipo TypeScript `ChatMessage` modela apenas `'user' | 'assistant'`; no reload, o branch de render `else`/não-`'user'` atribui erroneamente a mensagem do instrutor à IA (avatar/label "IA"). Pior, a mensagem otimista local é empurrada no estado como `'assistant'`, divergindo do valor `'instructor'` efetivamente persistido — ou seja, a tela mostra um autor no envio e outro no reload.

**Importante:** isso **não** propaga para chamada LLM inválida — o history usado pelo modelo vem do estado in-memory, não do `getMessages`. O defeito é puramente de contrato de role + renderização de autor.

**Impacto:** mensagens de instrutor renderizam com autor errado ("IA") no reload e há divergência otimista↔persistido, minando a confiança do instrutor na tela de revisão.

## Acceptance Criteria
- [ ] O conjunto de roles é canônico entre frontend e backend: o tipo TS `ChatMessage` reconhece `'instructor'` (estendendo o union `'user' | 'assistant' | 'instructor'`) e o schema da rota em `routes_ai.py:122` valida o role contra esse conjunto (enum/pattern), rejeitando roles fora dele.
- [ ] No envio, a mensagem otimista local é empurrada com `role: 'instructor'` (paridade exata com o que será persistido — nunca mais `'assistant'`).
- [ ] No reload (via `getMessages`), uma mensagem `role:'instructor'` renderiza com avatar/label próprio do instrutor (ex.: nome/iniciais do instrutor ou rótulo "Instrutor"), **distinto** do avatar/label "IA" usado por `'assistant'` e do avatar do aluno usado por `'user'`.
- [ ] O branch de render `else`/não-`'user'` deixa de tratar qualquer não-`'user'` como IA: a atribuição de autor passa a ser explícita por role (`user` → aluno, `assistant` → IA, `instructor` → instrutor).
- [ ] Paridade otimista↔persistido verificada: a mesma mensagem do instrutor exibe o mesmo autor/label antes e depois do reload (sem "flip" de IA para instrutor).
- [ ] Mensagens de aluno (`'user'`) e de IA (`'assistant'`) continuam renderizando exatamente como antes (sem regressão visual).

## Tasks / Subtasks
- [ ] Em `frontend/src/views/instructor/SessionReview.tsx:143`: garantir que o push otimista use `role: 'instructor'` (remover o hardcode/coerção para `'assistant'`).
- [ ] Localizar e estender o tipo `ChatMessage` (definição TS de role da conversa) para incluir `'instructor'` no union de roles.
- [ ] Ajustar o branch de renderização em `SessionReview.tsx` para mapear autor/avatar/label por role explícito (`user`/`assistant`/`instructor`), eliminando o catch-all que joga não-`'user'` em "IA".
- [ ] Definir o avatar/label do instrutor (reaproveitar dados de sessão/instrutor já disponíveis na tela ou um rótulo "Instrutor" consistente com o design system).
- [ ] No backend `routes_ai.py:122`: trocar `role: str` por validação canônica (enum/pattern) do conjunto `user|assistant|instructor`, mantendo compatibilidade com as gravações existentes.
- [ ] Teste de regressão de UI (render por role) cobrindo o reload de uma sessão com mensagem de instrutor → autor "Instrutor", não "IA".

## Dev Notes
- **Arquivos:**
  - `frontend/src/views/instructor/SessionReview.tsx` (push otimista linha ~143; branch de render de autor/avatar)
  - Tipo `ChatMessage` (definição do union de role da conversa no frontend)
  - `backend/.../routes_ai.py` (schema inline da rota, ~linha 122)
- **Abordagem:** reconciliar o contrato de role em três pontos — (1) tipo TS `ChatMessage` passa a reconhecer `'instructor'`; (2) render por role explícito em vez de `else`→IA; (3) schema da rota valida role canônico. O push otimista deve espelhar o valor persistido (`'instructor'`), eliminando a divergência envio↔reload.
- **Riscos de regressão:** o branch de render de autor é compartilhado por todas as mensagens da tela de revisão — qualquer mudança no mapeamento de autor afeta a exibição de `user` e `assistant` também; validar que aluno e IA continuam corretos. O endpoint da rota é gravado por outros fluxos de chat — endurecer o role para enum não pode quebrar gravações `'user'`/`'assistant'` legítimas. Depende de **CDC-1** (reconciliação de role já iniciada); não tocar a montagem do history para o LLM (vem do estado in-memory, fora do escopo). Não há impacto em chamada LLM (confirmado no bug sweep).

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: reload de sessão com mensagem de instrutor renderiza autor "Instrutor", não "IA".
- [ ] Sem regressão na suíte de segurança.
- [ ] QA Gate: PASS ou CONCERNS.
- [ ] Conjunto de roles canônico entre tipo TS e schema da rota; render por role explícito; paridade otimista↔persistido confirmada; mensagens de aluno e IA inalteradas.

## QA Results
_(a preencher pelo @qa)_
