---
id: SOC-1
epic: GOAL-pergunta-unica
goal_ref: docs/goals/GOAL-pergunta-unica.md
phase: 1
status: Done
severity: HIGH
terminal: Fullstack (Backend & Frontend)
complexity: medium
depends_on: []
---
# SOC-1: Pergunta socrática única e retomável por conteúdo

## Story

Como aluno, ao iniciar a sessão socrática numa das "Perguntas para Reflexão" de um capítulo,
quero que essa escolha seja definitiva enquanto a sessão estiver ativa, com as demais
perguntas bloqueadas mesmo depois de fechar o chat ou recarregar a página, e que a pergunta
escolhida passe a oferecer "Retomar Sessão" reabrindo a mesma conversa com o histórico, para
que o diálogo com o tutor não se fragmente em perguntas misturadas na mesma sessão.

## Contexto

Declarado via `/goal` por Hugo Capitelli em `docs/goals/GOAL-pergunta-unica.md`
(2026-07-15, com screenshot da visão do aluno). O backend já tem a base pronta:

- `POST /chat-sessions` é create-or-get race-free por `(user_id, content_id)`
  (`backend/routes_ai.py:1366`, TPP-2 + SEC-CHAT-3: `active` é retomada como está,
  `abandoned` reativa, `completed` cai para criação de sessão nova de nova tentativa).
- `GET /chat-sessions/by-content/{content_id}` (`backend/routes_ai.py:1502`) devolve a
  sessão mais recente do usuário para o conteúdo (404 se não houver).
- `GET /chat-sessions/{session_id}/messages` (`backend/routes_ai.py:1444`) devolve o
  histórico persistido server-side (TPP-4/TPP-5).
- O client frontend já expõe tudo isso: `chatSessionsApi.byContent` e
  `chatSessionsApi.getMessages` (`frontend/src/services/api.ts:322-331`), hoje sem uso no
  `ChapterReader`.

O que falta (o gap real):

1. **Schema:** `chat_sessions` (migração `supabase/migrations/20260414_init.sql:122-132`)
   não tem coluna para a pergunta escolhida. A escolha vive só no estado local
   `selectedQuestion` do `ChapterReader`.
2. **Backend:** `POST /chat-sessions` não recebe nem persiste a pergunta; nenhum endpoint
   devolve qual pergunta pertence à sessão.
3. **Frontend (`frontend/src/views/courses/ChapterReader.tsx`):**
   - `startChat` (linha ~501) chama `createOrGet` sem a pergunta.
   - Os botões das perguntas (linhas ~1216-1236) são gated por `selectedQuestion` local.
   - `closeChat` (linha ~492, bug #21/H3) reseta `selectedQuestion` e re-habilita TODOS os
     botões, exatamente o comportamento que este goal reverte parcialmente: o teardown do
     modal continua, mas o bloqueio das outras perguntas passa a ser durável (derivado da
     sessão persistida, não do estado do modal).
   - Não há hidratação no load: após reload, tudo aparece liberado e um novo `startChat`
     com outra pergunta reusa a MESMA sessão ativa, misturando diálogos.

## Acceptance Criteria

> Espelham literalmente os 5 critérios de "Pronto quando" do goal
> (`docs/goals/GOAL-pergunta-unica.md`), sem adição nem remoção de escopo.

1. **Pergunta persistida na sessão:** migração aditiva cria
   `chat_sessions.initial_question_text` (TEXT, nullable); `POST /chat-sessions` aceita o
   campo opcional, grava na criação e NUNCA sobrescreve valor não-nulo em resume (first
   write wins; a resposta devolve sempre a pergunta armazenada).
   - Verificação: `grep -rn 'initial_question_text' supabase/migrations/ backend/routes_ai.py`; teste backend prova gravação e não-sobrescrita.
2. **Bloqueio durável no frontend:** no load do capítulo com perguntas, `ChapterReader`
   hidrata via `chatSessionsApi.byContent(contentId)`; se existe sessão `active`, as outras
   perguntas ficam `disabled` e a escolhida exibe "Retomar Sessão". `closeChat` NÃO volta a
   liberar as outras perguntas enquanto a sessão estiver `active`.
   - Verificação: `grep -n 'byContent' frontend/src/views/courses/ChapterReader.tsx`; `grep -n 'Retomar' frontend/src/views/courses/ChapterReader.tsx`.
3. **Retomada com histórico:** "Retomar Sessão" reabre a sessão existente carregando as
   mensagens via `getMessages`, sem repetir o kickoff socrático e sem criar sessão nova.
   - Verificação: `grep -n 'getMessages' frontend/src/views/courses/ChapterReader.tsx`; leitura do fluxo confirma kickoff só em sessão recém-criada.
4. **Nova tentativa após completed:** com a sessão mais recente `completed`, as perguntas
   voltam habilitadas e iniciar outra pergunta cria sessão nova com a nova
   `initial_question_text` (SEC-CHAT-3 preservado).
   - Verificação: teste backend cobrindo completed → nova sessão com pergunta diferente.
5. **Gates mecânicos verdes:**
   - `cd frontend && npm run build` → exit 0
   - `cd backend && python -m pytest -q` → exit 0

## Tasks / Subtasks

### Backend

- [x] **(AC1)** Migração aditiva `supabase/migrations/20260715000000_chat_session_initial_question.sql`:
  `ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS initial_question_text TEXT;`
  (migração ANTES do código que a consome, padrão do repo).
- [x] **(AC1)** Em `backend/routes_ai.py`, estender `ChatSessionCreate` com
  `initial_question_text: str | None = None` e propagar em
  `_create_chat_session_row`/`_upsert_chat_session_row` (criação grava o valor).
- [x] **(AC1)** No branch de resume do `create_or_get_chat_session` (~linha 1388): se a
  sessão existente tem `initial_question_text` não-nulo, devolver como está (nunca
  sobrescrever); se for NULL (sessão legada) e o request trouxer texto, fazer backfill
  único. `abandoned` reativada segue a mesma regra.
- [x] **(AC1, AC4)** Testes novos em `backend/tests/test_session_question_lock.py`:
  (a) criação persiste a pergunta e a devolve; (b) create-or-get de novo com pergunta
  DIFERENTE devolve a mesma sessão com a pergunta ORIGINAL intacta; (c) `by-content`
  devolve `initial_question_text`; (d) sessão `completed` + novo create com outra pergunta
  cria sessão nova com a nova pergunta.

### Frontend (`frontend/src/views/courses/ChapterReader.tsx`)

- [x] **(AC2)** Novo estado `activeSession` hidratado no load (junto do
  `Promise.all` de content/questions, linha ~281): `chatSessionsApi.byContent(contentId)`
  com 404 tratado como "sem sessão". Sessão `active` → derivar a pergunta travada de
  `initial_question_text`; `completed` → tudo liberado (nova tentativa).
- [x] **(AC2)** Gating dos botões (linhas ~1216-1236) passa a usar o lock durável
  (sessão ativa persistida) em vez de só `selectedQuestion` local: outras perguntas
  `disabled`, a escolhida exibe "Retomar Sessão" quando o chat está fechado.
- [x] **(AC2)** `closeChat` (linha ~492) continua fazendo o teardown do modal, mas NÃO
  limpa o lock durável (o comentário do bug #21/H3 deve ser atualizado para registrar a
  mudança de contrato).
- [x] **(AC1)** `startChat` envia `initial_question_text: questionText` no
  `createOrGet` e adota a pergunta retornada pelo servidor como fonte de verdade.
- [x] **(AC3)** Novo fluxo `resumeChat`: abre o modal, chama `getMessages(sessionId)` e
  renderiza o histórico; NÃO dispara o kickoff `aiApi.socraticDialogue("Quero explorar...")`
  (kickoff só quando a sessão acabou de ser criada). Pacing/finalização seguem sendo
  adotados do servidor no próximo turno (TPP-5/TPP-6).
- [x] **(AC5)** `npm run build` e `pytest -q` verdes.

## Dev Notes

- `by-content` devolve a sessão MAIS RECENTE (DATA-GAM-3): se ela for `completed`, o
  contrato de nova tentativa se aplica; não assumir unicidade de linha por conteúdo.
- Não tocar no motor socrático (`routes_ai.py` socratic route, TPP-*): o goal é de
  seleção/retomada de sessão, não de pacing.
- O carve-out SEC-SCOPE-3 (tutor preservado) e a suíte IDOR não podem regredir.

## Change Log

| Data | Mudança | Autor |
|:---|:---|:---|
| 2026-07-15 | Story criada a partir do GOAL-pergunta-unica (declarado por Hugo via /goal). | J.A.R.V.I.S. |
| 2026-07-15 | Implementação completa (loop iter 1), QA adversarial PASS, status Done. NÃO commitado (aguarda @devops + autorização Hugo). | @dev + @qa via J.A.R.V.I.S. |

## Dev Agent Record

- **Loop:** GOAL-pergunta-unica, iteração 1/3, PASS direto.
- **Coder:** @dev (subagente isolado). **Revisor:** @qa adversarial (provas reproduzidas independentemente).
- **Arquivos:** `supabase/migrations/20260715000000_chat_session_initial_question.sql` (nova), `backend/schemas/chat.py`, `backend/routes_ai.py` (`_ensure_initial_question`, first-write-wins nos 3 branches + RPC/fallback), `backend/tests/test_session_question_lock.py` (nova, 6 testes), `frontend/src/views/courses/ChapterReader.tsx` (hidratação byContent, lock durável, resumeChat com getMessages), `frontend/src/services/api.ts`.
- **Gates:** pytest 610 passed / 0 failed · `npm run build` exit 0.
- **Desvio documentado:** `backend/tests/test_tutor_persistence.py` (2 oracles TPP-5 re-alinhados ao contrato MAX_INTERACTIONS=3 do commit 9c47d11; falha pré-existente confirmada no HEAD limpo, sem tocar código de produção do pacing).
- **Follow-ups (não-bloqueantes, QA MEDIUM/LOW):** (1) teste dedicado do branch `abandoned` reativado preservando a pergunta original; (2) gating por texto da pergunta é ambíguo se duas perguntas forem idênticas (improvável).

## QA Results

**Gate: PASS** (2026-07-15, @qa adversarial). 5/5 critérios da rubrica com evidência literal; 7 hunts adversariais (first-write-wins nos branches, durabilidade pós-reload, kickoff isolado, completed libera nova tentativa, 404 tratado, testes com oracle real, sem regressão SEC-CHAT-3/IDOR/TPP). 2 achados MEDIUM não-bloqueantes registrados acima.
