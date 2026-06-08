---
id: TPP-6
epic: EPIC-AI
phase: 3
status: Done
severity: CRITICAL
terminal: UX/UI & Design
complexity: medium
depends_on: [TPP-4, TPP-5, MEDIA-2]
bug_refs: [26]
---
# TPP-6: Frontend — consumir pacing do servidor + parar de duplo-persistir turno do aluno

## Story
Como aluno em sessão de tutoria socrática, quero que o pacing (interações restantes), a finalização e a síntese de fechamento venham do servidor, para que o tutor pare corretamente ao fim da sessão e me entregue a síntese pedagógica — sem que minha mensagem seja contada/persistida duas vezes.

## Contexto (do bug sweep)
Bug #26 — `interactions_remaining` nunca persistido; frontend só envia no 1º turno → backend usa default em todos os follow-ups.
Evidência no frontend (`frontend/src/views/courses/ChapterReader.tsx`):
- `:314-315` — o cliente deriva o pacing **localmente**: `interactionsUsed = chatMessages.filter(m => m.role === 'user').length` e `remainingInteractions = MAX_INTERACTIONS - interactionsUsed`. Não há fonte da verdade no servidor.
- `:354` — no início envia `interactions_remaining: 20` (hardcoded), e nos follow-ups (`:396-402`) **omite** o campo, deixando o backend cair no default (3). Como 3 > 1, as condições de finalização (`<= 1`) nunca disparam; a síntese socrática de fim **nunca** é entregue numa sessão real de 20 turnos.
- `:395` — `sendMessage` chama `chatSessionsApi.addMessage(sessionId, { role: 'user', content })` ANTES de `aiApi.socraticDialogue`. Após TPP-4 (servidor persiste **ambos** os turnos), esse `addMessage('user')` é uma **segunda** persistência do mesmo turno do aluno → duplo-count e mensagens duplicadas no GET/export.
- `:356-364, :403-410` — a UI monta as bolhas só a partir do retorno da IA; o retorno `session_status`/`should_finalize` da rota socrática **nunca é consumido** (badge `:1085-1088` e gate de input `:383,:1142` usam contagem local, não o estado do servidor).
- `:1` — o arquivo está sob `@ts-nocheck` (removido por MEDIA-2, dependência desta story), mascarando erros de tipo nas mudanças.

Impacto (correto, não é síntese prematura): lógica de finalização server-side fica morta, pacing dessincronizado entre cliente e servidor, e a síntese pedagógica de fechamento (feature core) é silenciosamente anulada.

## Acceptance Criteria
- [x] `sendMessage` NÃO chama mais `chatSessionsApi.addMessage(sessionId, {role:'user',...})`; o turno do aluno é persistido **exclusivamente** server-side (TPP-4) — elimina o duplo-count (N, não 2N).
- [x] O pacing exibido (badge) e o gate de input derivam de `sessionStatus` (server `session_status`), com a contagem local apenas como fallback otimista antes da 1ª resposta do servidor.
- [x] O cliente para de hardcodar `interactions_remaining: 20` no start e de omiti-lo nos follow-ups: o campo não é mais enviado (servidor deriva — TPP-5).
- [x] Quando o servidor sinaliza `should_finalize`, a UI desabilita o input e exibe o aviso de sessão concluída; a síntese de fechamento é a última bolha do assistente (já renderizada a partir de `chatMessages`).
- [x] Otimismo de UI preservado: a bolha do aluno aparece imediatamente (estado local); contagem/finalize vêm do servidor (`setSessionStatus(extractSessionStatus(...))`).
- [~] `@ts-nocheck`: MEDIA-2 (dependência, dono do pragma) ainda não rodou — o pragma foi MANTIDO. As mudanças desta story são type-clean (verificado removendo o pragma temporariamente: 0 erros novos; o único erro remanescente, linha ~232 `Question[]`, é pré-existente e de escopo MEDIA-2). Ver Dev Agent Record.

## Tasks / Subtasks
- [ ] Em `ChapterReader.tsx:382-416` (`sendMessage`): remover a linha `:395` (`chatSessionsApi.addMessage(... role:'user' ...)`); manter apenas a chamada otimista a `setChatMessages` para a bolha do aluno e a chamada `aiApi.socraticDialogue` (`:396-402`).
- [ ] Em `:349-355` e `:396-402`: parar de enviar `interactions_remaining: 20` no start; alinhar o payload ao contrato pós-TPP-4/TPP-5 (servidor deriva o pacing). Conferir o tipo de `socraticDialogue` na camada de api (`frontend/src/.../api` / `aiApi`).
- [ ] Consumir `session_status` (e `should_finalize`/`interactions_remaining` vivos) do retorno de `socraticDialogue` em start (`:349`) e follow-up (`:396`); guardar em estado React dedicado (ex.: `sessionStatus`) em vez de derivar `interactionsUsed` de `chatMessages` (`:314-315`).
- [ ] Trocar `remainingInteractions` (`:315`) e `interactionsUsed` (`:314`) para refletir o estado do servidor; atualizar badge (`:1085-1088`) e gate (`:383`, `:1142`) para usar essa fonte.
- [ ] Ao detectar finalização do servidor: renderizar a síntese de fechamento como última bolha de assistente e desabilitar input/envio.
- [ ] Confirmar que MEDIA-2 já removeu `@ts-nocheck` (`:1`); ajustar tipos das respostas socráticas conforme o novo contrato e garantir `tsc`/build limpos.

## Dev Notes
- **Arquivos:** `frontend/src/views/courses/ChapterReader.tsx` (chat socrático: `startChat` ~`:340-380`, `sendMessage` `:382-416`, derivação de pacing `:314-315`, badge `:1085-1088`, gate `:383`/`:1142`); camada de API `aiApi.socraticDialogue` e `chatSessionsApi` (tipos do contrato pós-TPP-4/5).
- **Abordagem:** mover a fonte da verdade de pacing/finalização do cliente para o servidor. (1) Eliminar a dupla persistência removendo `addMessage('user')` agora que TPP-4 persiste ambos os turnos server-side. (2) Substituir a contagem local de turnos por `session_status` retornado (TPP-5). (3) Renderizar a síntese de fechamento ao `should_finalize`. UI otimista para a bolha do aluno, mas contagem/finalize sempre do servidor.
- **Riscos de regressão:** o badge de interações restantes (`:1085-1088`) e o gate de envio (`:383`, `:1142`) hoje dependem de `remainingInteractions` local — mudar a fonte afeta diretamente quando o input bloqueia. Tocar `sendMessage` afeta todo o fluxo de chat do `ChapterReader` (único consumidor do tutor socrático). Depende de TPP-4 (servidor persiste ambos os turnos — sem isso, remover `addMessage` perderia o turno do aluno) e TPP-5 (servidor deriva `interactions_remaining` e `should_finalize`); MEDIA-2 deve ter removido `@ts-nocheck` antes (rebase declarado no roadmap `:337`). Coordenação cross-terminal: backend (Backend & Infra) dono de TPP-4/5; este card é UX/UI & Design.

## Definition of Done
- [x] N turnos persistem N mensagens de aluno (não 2N) — `addMessage('user')` removido; backend é a fonte única (TPP-4). Badge/finalize seguem `session_status`.
- [x] Sem regressão na suíte de segurança (backend 323 verdes; payload socrático ownership-scoped pelo `current_user`).
- [x] QA Gate: PASS ou CONCERNS.
- [~] `@ts-nocheck` mantido (MEDIA-2 pendente); mudanças desta story são type-clean (0 erros novos). Síntese de fechamento renderiza como última bolha quando `should_finalize` (sem síntese prematura — derivada server-side em TPP-5).

## Dev Agent Record

**Agent:** Dex (@dev) · **Date:** 2026-06-05 · **Status:** Ready for Review

**Files changed:**
- `frontend/src/views/courses/ChapterReader.tsx`:
  - New `sessionStatus` state + `extractSessionStatus()` helper (parses server `session_status`).
  - `remainingInteractions`/`sessionFinalized` now derive from `sessionStatus` (server), local count only as pre-server fallback.
  - `startChat`: removed hardcoded `interactions_remaining: 20`; resets + adopts server `session_status`.
  - `sendMessage`: **removed** `chatSessionsApi.addMessage(sessionId, {role:'user'})` (double-persist); stopped sending `interactions_remaining`; adopts server `session_status`; gate also blocks when `sessionFinalized`.
  - Input gate renders a "Sessao concluida" notice (closing-synthesis state) when `sessionFinalized`.

**Notes / decisions:**
- `[AUTO-DECISION]` `@ts-nocheck` left in place (MEDIA-2 owns its removal and hasn't run). Verified by temporarily deleting line 1 and running `tsc --noEmit`: my edits add **zero** new type errors; the one remaining error (~line 232, `Question[]` setState) is pre-existing and out of TPP-6 scope. Reason: removing the pragma now would surface unrelated pre-existing errors and break `tsc -b` build, which is MEDIA-2's job.
- `aiApi.socraticDialogue` is typed `(data: Record<string, unknown>)`, so omitting `interactions_remaining` is valid.

**Tests:** frontend has no unit test runner (vite + tsc only). Verified type-cleanliness of the diff as above. Backend contract these consume is covered by TPP-4/TPP-5 tests (`session_status` shape, both turns persisted).

## QA Results

**Gate: CONCERNS** — @qa (Quinn), 2026-06-05 (re-review after delivery; supersedes the earlier FAIL, which predated the merge).

Verified `frontend/src/views/courses/ChapterReader.tsx` IS now in `git diff` and the changes match the AC:
- `sendMessage` no longer calls `chatSessionsApi.addMessage(sessionId, {role:'user'})` — the student turn is persisted exclusively server-side (TPP-4), eliminating the double-count (N, not 2N).
- New `sessionStatus` state + `extractSessionStatus()` helper; `remainingInteractions`/`sessionFinalized` derive from server `session_status`, with local count only as a pre-server optimistic fallback.
- `startChat` no longer hardcodes `interactions_remaining: 20`; the field is no longer sent on follow-ups (server derives — TPP-5).
- Input gate renders a "Sessao concluida" notice and blocks input when `sessionFinalized`.

Why CONCERNS (not PASS): this is a frontend story with **no automated test coverage** — the repo has no JS/TS test runner (vite + tsc only), so the 323-test backend suite does not exercise this file. Verification rests on diff review + the dev's manual `tsc --noEmit` check, which I could not re-run here (frontend toolchain out of this backend QA scope). Additionally, `@ts-nocheck` is still present on line 1 (the dev correctly deferred its removal to MEDIA-2, the pragma owner — documented `[AUTO-DECISION]`), so `tsc -b` is not yet enforcing types on this file in CI. The backend contract these changes consume (`session_status` shape, both-turns persistence) IS fully covered by TPP-4/TPP-5 (PASS). Recommend: a frontend test harness + MEDIA-2 `@ts-nocheck` removal as the follow-up to lift this to PASS. No functional blocker found.
