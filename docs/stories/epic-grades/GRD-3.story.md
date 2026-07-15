---
id: GRD-3
epic: GOAL-refazer-sessao
goal_ref: docs/goals/GOAL-refazer-sessao.md
type: feature (destrava caso vivo)
status: InReview
severity: HIGH
terminal: Frontend (backend já suporta nova tentativa)
---
# GRD-3: Refazer sessão socrática (destravar aluno de sessão concluída)

## Sintoma (caso vivo do Hugo, IAA-2026)

Não existe botão de refazer a sessão socrática. Com uma sessão `completed` (inclusive as
fantasmas legadas com 0 interações — ver GRD-2) e/ou o flag `tutorDone` sujo no localStorage,
o painel do Tutor Socrático mostra "Sessão concluída" e o aluno fica SEM caminho para
fazer/refazer as perguntas. Ele fica trancado.

## Causa (por que trancava)

Duas superfícies do `ChapterReader.tsx` fechavam a saída:
1. **Rodapé do chat** (`~1588`): quando `sessionFinalized || remainingInteractions <= 0`,
   renderizava só o texto "Sessao concluida. Veja a sintese..." — um beco sem saída, sem ação.
2. **Botões das perguntas** só reaparecem limpos quando `activeSession=null` E `lockedQuestion=null`.
   A hidratação (`by-content`) já deixava `activeSession=null` para sessão `completed` (SOC-1
   AC4), mas o flag `tutorDone` do localStorage (setado no fim do ataque anterior) mantinha o
   painel com cara de finalizado, e não havia nenhum affordance explícito de "recomeçar".

## Decisões (interação com SOC-1 / backend)

- **Backend NÃO tocado.** O caminho "nova tentativa após completed" já existe e é testado
  (SOC-1 AC4, `test_session_question_lock.py::test_completed_then_new_question_creates_distinct_session`):
  `POST /chat-sessions` com a sessão mais recente `completed` cai em `_create_chat_session_row`
  e cria uma NOVA linha `active` (SEC-CHAT-3), preservando a `completed`. "Refazer" é pura
  orquestração de frontend sobre esse contrato.
- **SOC-1 respeitado.** A pergunta é fixa por conteúdo. Na nova tentativa, reuso a
  `initial_question_text` da sessão concluída (capturada na hidratação como `completedSession`)
  — NÃO invento pergunta nova. Se a concluída não tiver pergunta (legada/fantasma sem questão),
  o fluxo cai para a lista de perguntas desbloqueada, o aluno escolhe. First-write-wins da SOC-1
  segue intacto (a nova sessão grava sua própria pergunta na criação).
- **Guarda GRD-2 respeitado.** A nova sessão nasce `active` com 0 mensagens; ela só vira
  `completed` de novo depois de interação real (guarda server-side de GRD-2). Sem risco de
  novo fantasma.
- **Histórico preservado.** A sessão concluída (inclusive a fantasma) NÃO é deletada — sobrevive
  no store e continua visível ao professor no drill-down GRD-1. A nova sessão aparece após
  interação.

## Como funciona (UX)

Quando a sessão mais recente do conteúdo é `completed`, "Refazer sessao" aparece em dois lugares
coerentes:
1. **No rodapé do chat aberto finalizado:** ao lado da mensagem "Sessão concluída", um botão
   "Refazer sessao" (mesma pergunta fixa da sessão atual).
2. **Na seção Questões Socráticas com o chat fechado:** um banner "Sessão anterior concluída"
   com botão "Refazer sessao".

Ao clicar: limpa `tutorDone` (estado + localStorage `harven_socratic_done:{user}:{content}`),
limpa `activeSession`/`completedSession`/`selectedQuestion`/`sessionStatus`/mensagens, e chama
`startChat(perguntaFixa)` → o backend cria uma sessão nova e o chat abre pronto com o kickoff do
tutor. O aluno interage normalmente; a nota (GRD-1) volta a compor pela nova sessão.

## Acceptance Criteria (espelham o goal)

1. **Botão "Refazer sessão"** presente quando a sessão do conteúdo está `completed`; inicia
   nova sessão, limpa o estado local do conteúdo e abre o chat pronto para interagir.
2. **Sessão fantasma não tranca:** conteúdo cuja única sessão é `completed`-0-msgs permite
   refazer normalmente.
3. **Avaliação preserva histórico:** sessões anteriores continuam visíveis ao professor;
   a nova aparece após interação.
4. **Gates:** `npm run build` exit 0; `pytest` sem regressão.

## Tasks

- [x] Entender o painel do tutor + interação `tutorDone`/`completed`/pergunta única (SOC-1).
- [x] Estado `completedSession` hidratado no load para lembrar a sessão concluída + sua pergunta.
- [x] `restartChat`: limpa `tutorDone`/estados e delega a `startChat` (nova sessão via backend).
- [x] UI "Refazer sessao" no rodapé do chat finalizado + banner na seção de perguntas.
- [x] Teste backend do fluxo de refazer (fantasma 0-msgs + mesma pergunta → nova sessão, histórico preservado).
- [x] `npm run build` + `pytest`.

## QA Results

**Revisor:** @qa (Quinn, Guardian) · **Data:** 2026-07-15 · **Método:** auditoria empírica independente (diff real do `ChapterReader.tsx` + trace do restart/hidratação + testes de contrato backend + pytest + build)

### Veredito: **PASS**

Feature frontend-only bem-orquestrada sobre um contrato de backend já existente e testado (nova tentativa
SEC-CHAT-3 / SOC-1). O botão aparece nos 2 pontos, o restart limpa tudo que trancava, a pergunta fixa é
reusada, o fallback é gracioso, o guarda GRD-2 não é contornado e não há regressão no fluxo normal. Uma
nota LOW sobre um estado transitório benigno, não bloqueante.

### Verificação por AC

- **AC1 — Botão "Refazer sessão" + restart + chat pronto: PASS.**
  Dois pontos coerentes no `ChapterReader.tsx`: (a) banner "Sessão anterior concluída" na seção de perguntas
  quando `completedSession && !activeSession && !chatOpen` (linha ~1366); (b) botão no rodapé do chat
  finalizado (linha ~1685), substituindo o beco sem saída "Sessao concluida" que antes não tinha ação.
  `restartChat` (linha ~620) limpa TUDO que trancava: `setTutorDone(false)` + `localStorage.removeItem(tutorDoneKey)`
  (a flag `harven_socratic_done:{user}:{content}`, def. linha 466), `setCompletedSession(null)`,
  `setActiveSession(null)`, `setSelectedQuestion(null)`, `setSessionStatus(null)`, `setChatMessages([])`. Depois
  delega a `startChat` (linha 558) → `chatSessionsApi.createOrGet` (linha 567), que com a sessão mais recente
  `completed` cria uma NOVA linha `active` (SEC-CHAT-3), abrindo o chat pronto.

- **AC2 — Sessão fantasma não tranca: PASS.**
  A hidratação ganhou o ramo `completed` (linha ~314): seta `activeSession=null` (destrava os botões de
  pergunta) e lembra `completedSession` com a `initialQuestionText`. Funciona para o fantasma
  `completed`-0-msgs igual a uma conclusão real — o botão de refazer independe de `total_messages`.
  `test_restart_session.py::test_restart_phantom_completed_zero_turns_spawns_new_session` prova: refazer
  um fantasma (completed, 0 msgs, mesma pergunta fixa) gera nova sessão `active` distinta, com a pergunta
  reusada (`initial_question_text == "PERGUNTA FIXA"`), e o fantasma **sobrevive** no store.

- **AC3 — Avaliação preserva histórico: PASS.**
  A sessão concluída NÃO é deletada — o teste acima confirma `len(rows) == 2` com `["active","completed"]`,
  o fantasma preservado. `test_by_content_returns_the_new_active_after_restart` prova que `by-content`
  (mais recente) resolve para a nova `active` após o refazer, então o painel re-hidrata destravado. Como
  o `GET /disciplines/{id}/sessions` (GRD-1) não filtra por status/total_messages (revisado no gate GRD-2)
  e a avaliação pede `perPage:100` (GRD-2), as sessões anteriores seguem visíveis ao professor; a nova
  aparece após interação.

- **AC4 — Gates: PASS.**
  `backend python3 -m pytest` → **616 passed, 0 failed** (subiu de 614 pelos 2 testes novos de restart;
  suíte inteira estável, zero falha). `test_restart_session.py` 2/2, `test_session_question_lock.py` 6/6
  (8/8 juntos). `frontend npm run build` → **exit 0, zero erros TS**.

### Guarda GRD-2 NÃO contornado (verificado)

O `restartChat` não completa nada — delega a `startChat`/`createOrGet`, que cria a nova sessão `active`
com 0 mensagens. Ela só volta a `completed` passando pelo guarda server-side de GRD-2
(`complete_chat_session`, `count_user_messages > 0`), que esta story NÃO toca. Os testes de restart
asseveram `status == "active"` na nova sessão. Nenhum risco de novo fantasma.

### Sem regressão no fluxo normal (verificado por leitura do diff)

A hidratação passou a ter 3 ramos: `active` (seta `activeSession`, adiciona `setCompletedSession(null)`,
aditivo), `completed` (novo, seta `completedSession`), `else` (ambos null). O banner só aparece com
`completedSession && !activeSession && !chatOpen` — invisível numa primeira sessão (`completedSession=null`)
ou numa sessão ativa (`activeSession≠null`). Backend de produção intocado; nenhum arquivo da SOC-1 alterado.
O contrato de nova tentativa foi reusado, não reinventado.

### Issues / Notas

**Nota 1 — [LOW, não bloqueante] Botão de rodapé também aparece no estado transitório `remainingInteractions <= 0` com sessão ainda `active`.**
O botão do rodapé é renderizado quando `sessionFinalized || remainingInteractions <= 0` (linha 1671).
No caso `remainingInteractions <= 0` mas a sessão ainda `active` (o `complete` server-side não disparou
naquele instante), clicar "Refazer" chama `createOrGet` que, com a sessão mais recente ainda `active`,
retorna a MESMA sessão (contrato create-or-get: nova linha só após `completed`), não uma nova — o "refazer"
não recomeçaria de fato nesse estado efêmero. **Por que é benigno e não bloqueia:** para chegar a
`remainingInteractions <= 0` é preciso ter havido interação real do aluno (o pacing server-side só
decrementa com turnos `role='user'` persistidos), então (a) não há risco de fantasma — a sessão tem
interação e será completada legitimamente pelo guarda GRD-2, e (b) o caso vivo do Hugo e o alvo da story
é `completed`, onde o `createOrGet` corretamente cria nova. É uma imperfeição teórica de um estado
transitório, não do fluxo primário. **Recomendação (futura, opcional):** condicionar o botão do rodapé a
`completedSession != null` (ou disparar o `complete` antes do restart quando a sessão está esgotada mas
ainda `active`), para o "Refazer" sempre gerar uma nova sessão. Fora do escopo mínimo desta story.

### Ação recomendada

Aprovar (PASS). Os 4 ACs cumpridos, contrato de backend reusado sem tocar produção, guarda GRD-2
preservado, suíte 616/0, build verde, zero regressão. A Nota 1 é um refinamento futuro opcional de um
estado de borda benigno, não uma condição de merge.

## File List

**Frontend**
- `frontend/src/views/courses/ChapterReader.tsx` (modificado) — estado `completedSession`,
  hidratação do caso `completed`, função `restartChat`, botão "Refazer sessao" no rodapé do
  chat finalizado e banner na seção Questões Socráticas.

**Backend**
- `backend/tests/test_restart_session.py` (novo) — 2 testes: restart de sessão fantasma
  (completed, 0 msgs, mesma pergunta) cria sessão nova distinta + preserva histórico;
  `by-content` resolve para a nova sessão ativa após refazer. **Nenhum código de produção
  backend tocado** (o contrato de nova tentativa já existia — SOC-1 AC4).

**SOC-1:** nenhum arquivo de produção da SOC-1 alterado; o contrato de pergunta única/nova
tentativa foi reusado como está.

## Change Log

| Data | Mudança | Autor |
|:---|:---|:---|
| 2026-07-15 | Story criada a partir de `docs/goals/GOAL-refazer-sessao.md`. "Refazer sessão" implementado no `ChapterReader` (frontend puro sobre o contrato de nova tentativa já existente do backend/SOC-1); 2 testes backend do fluxo de refazer (fantasma + histórico). Gates verdes (build exit 0, pytest exit 0). Status → InReview. | @dev (Dex) |
