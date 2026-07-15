---
id: GRD-2
epic: GOAL-sessao-fantasma
goal_ref: docs/goals/GOAL-sessao-fantasma.md
type: bug-fix
status: InReview
severity: HIGH
terminal: Fullstack (Backend primário; Frontend secundário)
---
# GRD-2: Sessão fantasma — concluída sem interação e invisível na avaliação

## Sintoma (bug report do Hugo, screenshot)

Disciplina IAA-2026, aluno Jeferson (JE):
1. Painel "Tutor Socrático" mostra **0/3** interações (apenas a mensagem de abertura do
   tutor, nenhuma resposta do aluno), badge **"Concluído"** e rodapé "Sessao concluida.
   Veja a sintese de fechamento acima." → a sessão foi marcada `completed` com **zero
   interação real do aluno**.
2. Na avaliação do professor (drill-down GRD-1 / aba Conversas) essa sessão **não aparece**.

## Causa raiz (documentada ANTES do fix — first-move rule)

**Sintoma 1 — completar sessão sem interação.** O endpoint `PUT /chat-sessions/{id}/complete`
(`backend/routes_ai.py:1591` `complete_chat_session`) só tinha dois gates: ownership e
idempotência. Ele flipa **qualquer** sessão `active` → `completed` incondicionalmente, sem
verificar se houve interação real do aluno. A criação de sessão está correta
(`_create_chat_session_row`/`create_or_get_chat_session`: sempre nasce `active`,
`total_messages=0`), e o pacing server-side também (`_derive_pacing`:
`should_finalize = used >= MAX-1`, nunca verdadeiro em 0 turnos). O buraco é exclusivamente
no `complete`:
- O gate de conclusão no frontend (`ChapterReader.tsx:481` `tutorPending`) libera o botão
  "Concluir" quando `tutorDone === true`, e `tutorDone` é um flag **persistido em
  localStorage** (`harven_socratic_done:{user}:{content}`, linhas 448-479) setado quando um
  ataque ANTERIOR ao mesmo conteúdo chegou a `interactions_remaining <= 0`.
- Ao revisitar o conteúdo, o `startChat` cria uma sessão NOVA (fresca, 0 mensagens, `active`
  — SEC-CHAT-3 permite "nova tentativa" após completed). Mas o `tutorDone` do localStorage
  ainda é `1` → `tutorPending=false` → "Concluir" habilitado → `markComplete`
  (`ChapterReader.tsx:869`) chama `chatSessionsApi.complete(sessãoNova)` → **a sessão nova, com
  só a mensagem de abertura, é marcada `completed` a 0/3**. Sessão fantasma.
- Sem guarda server-side, o backend obedece cegamente. A correção correta é **server-side**
  (autoridade da regra vive no banco/rota, não numa flag de localStorage do cliente): a rota
  `complete` só marca `completed` se houver ≥1 mensagem real do aluno
  (`ChatRepository.count_user_messages(session_id) > 0`). Sem interação, retorna a sessão como
  está (não vira completed) — o frontend deixa de conseguir criar o fantasma mesmo com o
  localStorage sujo.

**Sintoma 2 — sessão some da avaliação.** O nosso `GET /disciplines/{id}/sessions` (GRD-1,
`routes_admin.py:1855+`) **não filtra por status nem por `total_messages`** — uma sessão
`completed` com 0 mensagens, desde que tenha `content_id` mapeável a um curso da disciplina,
aparece normalmente. A invisibilidade vem de **paginação**: o endpoint tem
`per_page=20` default e o consumidor de avaliação (`StudentGradeDetail.tsx` e a aba
"Conversas" em `InstructorDetail.tsx`) chama `getSessions` **sem paginar** e só lê a primeira
página via `unwrapList`. Um aluno com >20 sessões (várias tentativas por conteúdo, cada
"nova tentativa" cria uma linha nova — SEC-CHAT-3) tem as sessões mais antigas silenciosamente
fora da página 1. Como o drill-down é escopado por `student_id`, o teto de 20 é atingível na
prática por um aluno ativo, e a sessão procurada some. Correção: o consumidor de avaliação
pede um `per_page` alto (o professor precisa ver TODAS as sessões do aluno para avaliar),
garantindo que nenhuma interação fique fora do alcance da nota.

## Fix (escopo mínimo)

1. **Backend, guarda de conclusão** (`routes_ai.py` `complete_chat_session`): antes de flipar
   para `completed`, exigir `count_user_messages(session_id) > 0`. Zero interação real →
   retorna a sessão intacta (`active`), nunca `completed`. Ownership/idempotência preservados.
2. **Frontend, avaliação sem truncamento** (`api.ts` `getSessions` + `StudentGradeDetail.tsx`):
   o drill-down do professor pede `per_page` alto para não perder sessões além da página 1.

## Arquivos da SOC-1 tocados

**Nenhum.** A causa raiz NÃO está na WIP da SOC-1 (pergunta única / lock): a SOC-1
(`create_or_get_chat_session`, `_ensure_initial_question`) está correta — cria sessão `active`
com 0 mensagens e first-write-wins da pergunta. O defeito é anterior à SOC-1, no
`complete_chat_session` (gate ausente) combinado com o flag de localStorage do frontend. O fix
toca `complete_chat_session` (não é código da SOC-1) e o frontend de avaliação (GRD-1).

## Acceptance Criteria

1. **Sem completar fantasma:** `PUT /chat-sessions/{id}/complete` numa sessão sem nenhuma
   mensagem `role='user'` NÃO marca `completed` — a sessão permanece `active`.
   - Verificação: teste pytest vermelho→verde.
2. **Sessão completa com interação real ainda completa:** o caminho legítimo (≥1 turno do
   aluno) continua marcando `completed` e computando `performance_score` como antes.
   - Verificação: teste pytest de não-regressão.
3. **Visível na avaliação:** uma sessão do aluno (qualquer status, inclusive `completed` com
   poucas mensagens) aparece na listagem `GET /disciplines/{id}/sessions?student_id=...`
   mesmo além dos 20 primeiros registros.
   - Verificação: teste pytest cobrindo a listagem com >20 sessões.
4. **Gates:** `pytest` sem regressão (2 falhas pré-existentes de tutor pacing toleradas);
   `npm run build` exit 0 (frontend tocado).

## Tasks

- [x] **(causa raiz)** Diagnóstico documentado acima (backend `complete` sem guarda + flag de
  localStorage; invisibilidade por paginação, não por filtro de status).
- [x] **(AC1/AC2, teste vermelho primeiro)** Teste pytest: completar sessão 0-turnos NÃO vira
  `completed`; completar com ≥1 turno vira `completed`.
- [x] **(AC3)** Teste pytest: sessão do aluno visível na avaliação além da página 1.
- [x] **(AC1)** Guarda server-side em `complete_chat_session`.
- [x] **(AC3)** Avaliação (`getSessions` no drill-down) pede `per_page` alto.
- [x] **(AC4)** `pytest` + `npm run build`.

## Dev Agent Record

**Agente:** @dev (Dex) · **Data:** 2026-07-15 · **Tipo:** bug fix (first-move rule: teste vermelho→verde)

### Sequência

1. Diagnóstico: `git log` mostra GRD-1 (`ee3b090`) e SOC-1 (`4bf1f12`) já commitados — a WIP da SOC-1 que o coordenador citou está no HEAD, não solta no working tree. Li o fluxo de criação (`create_or_get_chat_session`, correto), pacing (`_derive_pacing`, correto) e conclusão (`complete_chat_session`, **defeituoso: sem guarda de interação**). Causa raiz confirmada NÃO ser da SOC-1.
2. **Teste vermelho primeiro** (`test_phantom_session.py`): `F...` — o teste de "0 turnos não completa" falhou provando o bug; os outros 3 passaram (completa legítimo funciona; sessão low-message é listada; endpoint devolve tudo com `per_page` alto → invisibilidade é paginação do consumidor, não filtro do endpoint).
3. Fix mínimo: guarda server-side em `complete_chat_session` (`count_user_messages > 0`); consumidor de avaliação pede `per_page: 100`.
4. Verde: 4/4 phantom tests passam.

### Colisão semântica reconciliada (documentada)

Meu guarda quebrou `test_gam_score_completion.py::test_completing_session_with_no_student_signal_leaves_score_null` — esse teste DATA-GAM-3 semeava uma sessão **só com turno do tutor (0 turnos do aluno)** e afirmava que ela COMPLETA com score null. Essa premissa é exatamente o bug que a GRD-2 corrige (completar sem interação). Reconciliei o teste: o caso "score null honesto" agora usa um turno REAL do aluno com conteúdo vazio (`"   "`) — a interação existe (passa o guarda de conclusão), mas `compute_performance_score` retorna `None` (conteúdo não-substantivo, `scoring.py:138-140`). Assim o contrato DATA-GAM (null honesto, nunca 0 forçado) e o guarda GRD-2 coexistem. Não toquei `scoring.py` nem o motor.

### Achado colateral (bônus, não regressão)

As 2 falhas de `test_tutor_persistence.py::TestTpp5Pacing` que eu vinha registrando como "pré-existentes toleradas" eram **poluição de ordem entre testes** (passam em isolamento e o full-run agora dá exit 0). A suíte inteira está verde, não só "2 toleradas".

### Gates

- Backend `pytest` (suíte completa) → **exit 0** (2 runs, estável); `test_phantom_session.py` 4/4; `test_gam_score_completion.py` 4/4.
- Frontend `npm run build` → **exit 0**.

## QA Results

**Revisor:** @qa (Quinn, Guardian) · **Data:** 2026-07-15 · **Método:** auditoria empírica independente (código real + teste vermelho→verde + pytest 2× + build + trace da resposta ao cliente)

### Veredito: **PASS**

Bug fix correto, mínimo e provado. A first-move rule (teste vermelho→verde) foi cumprida de verdade,
a causa raiz está no lugar certo (server-side, não na flag de localStorage), a reconciliação do
DATA-GAM foi bem-julgada (não afrouxou o contrato), e a suíte inteira está estável em exit 0.
Uma nota informativa sobre UX silenciosa e uma sobre dados legados, nenhuma bloqueante.

### Verificação por AC

- **AC1 — Sem completar fantasma: PASS.**
  `complete_chat_session` (`routes_ai.py:1618-1625`) chama `ChatRepository.count_user_messages(session_id)`
  ANTES de flipar status; se `<= 0`, retorna a sessão intacta (`status: "active"`), sem qualquer write.
  `count_user_messages` (`chat_repo.py:127-140`) conta `role='user'` on-read (`.eq("role","user")`), nunca
  confia em `total_messages`. Teste `test_complete_with_zero_user_turns_does_not_complete` prova que a
  sessão permanece `active`. Ownership (`:1601`) e idempotência (`:1609-1610`, completed → no-op 200)
  preservados. Score só computa DEPOIS do guarda passar (`:1635+`).

- **AC2 — Conclusão legítima ainda completa: PASS.**
  `test_complete_with_real_interaction_still_completes`: com ≥1 turno `role='user'`, a sessão vira
  `completed`. `test_gam_score_completion.py::test_completing_scorable_session_persists_score` confirma que
  o `performance_score` continua computado e persistido no mesmo edge (0 < score ≤ 100). Idempotência e
  não-recompute reprovados por `test_second_complete_does_not_recompute_score` (nenhum re-write no 2º complete).

- **AC3 — Visível na avaliação: PASS.**
  `test_completed_low_message_session_is_listed` prova que o endpoint NÃO filtra por status/total_messages
  (uma sessão `completed` com poucas mensagens aparece). `test_older_session_beyond_page_one_still_returned`
  prova a causa real da invisibilidade: com 26 sessões, a página default (`per_page=20`) esconde a fantasma
  (mais antiga), e `per_page=100` a revela — confirmando que a correção é do CONSUMIDOR, não do endpoint.
  Ambos os consumidores migrados: `StudentGradeDetail.tsx:65` (`{ studentId, perPage: 100 }`) e a aba
  Conversas em `InstructorDetail.tsx:150` (`{ perPage: 100 }`); `api.ts:106-110` mapeia `perPage → per_page`.

- **AC4 — Gates: PASS.**
  `backend python3 -m pytest` rodado **2 vezes** (ordem aleatória e default) → **614 passed, 0 failed** em
  ambas, estável. `test_phantom_session.py` 4/4, `test_gam_score_completion.py` 4/4 (8/8 juntos).
  `frontend npm run build` → **exit 0, zero erros TS**.

### Achado colateral confirmado (bônus, não regressão)

O dev alegou que as 2 falhas de `TestTpp5Pacing` que eu vinha registrando como "pré-existentes toleradas"
eram **poluição de ordem entre testes**, não falha real. **Confirmado empiricamente:** `TestTpp5Pacing`
isolado → 4/4; full-run (2×, ordens diferentes) → 614 passed, 0 failed. A suíte inteira está verde de
verdade agora, não "612 + 2 toleradas". Correção honesta de um ruído que eu havia herdado das iterações
anteriores.

### Reconciliação DATA-GAM (julgada, não afrouxou o contrato)

`test_gam_score_completion.py::test_completing_session_with_no_student_signal_leaves_score_null` foi
reescrito: antes semeava uma sessão **só com turno do tutor (0 turnos do aluno)** afirmando que ela
COMPLETA com score null — mas essa premissa É exatamente o bug que a GRD-2 corrige (completar sem
interação). O caso agora usa um turno REAL do aluno com conteúdo vazio (`"   "`): a interação existe
(passa o guarda de conclusão, `count_user_messages`=1), mas `compute_performance_score` retorna None
(conteúdo não-substantivo). **O contrato DATA-GAM permanece protegido** — "null honesto, nunca 0 forçado"
continua asseverado; o que mudou foi a premissa que codificava o próprio bug. `scoring.py` e o motor não
foram tocados. Julgamento correto: sem essa reescrita, o teste antigo estaria eternizando o defeito.

### Issues / Notas

**Nota 1 — [INFORMATIVA, não bloqueante] UX silenciosa no caso recusado.**
Quando o guarda recusa a conclusão (`user_turns <= 0`), a rota devolve **HTTP 200 com o corpo da sessão
`active`** — não é erro, mas também não há campo explícito tipo `completed: false` ou mensagem sinalizando
"não completei". O cliente que não reler `status` no corpo pode exibir sucesso silencioso. Aceitável para
o escopo do bug fix (o objetivo era impedir o fantasma, e ele é impedido), e o frontend já perdeu a
capacidade de criar o fantasma mesmo com localStorage sujo. Registro para consideração futura: se o botão
"Concluir" ficar habilitado numa sessão 0-turno, o clique agora não faz nada visível — vale um toast
"conclua após interagir" numa próxima iteração de UX, fora do escopo desta story.

**Nota 2 — [INFORMATIVA] Dados legados (sessões fantasma já persistidas).**
Sessões fantasma que JÁ existem no banco (`completed`, 0 msgs de aluno, ex. a do Jeferson do screenshot)
continuam `completed` — o fix impede NOVAS, não limpa as antigas. Com `perPage:100` elas ficam agora
VISÍVEIS na avaliação (comportamento correto: nenhuma interação fora do alcance da nota), mas o professor
verá uma sessão "concluída" a 0/3. Não há migration de limpeza nesta story, e corretamente não deveria
haver sem pedido explícito (Art. IV — sem invenção de escopo). Registro para o Senhor decidir se quer um
script pontual de saneamento (`UPDATE chat_sessions SET status='active' WHERE status='completed' AND
<sem role='user'>`). Não bloqueia a GRD-2.

### Ação recomendada

Aprovar (PASS). O bug fix cumpre os 4 ACs, a first-move rule foi respeitada, a suíte está estável em
614/0, o build é verde e nenhuma regressão foi introduzida. As duas notas são informativas para decisão
futura do Senhor, não condições de merge.

## File List

**Backend**
- `backend/routes_ai.py` (modificado) — guarda de interação em `complete_chat_session`: sem `role='user'` turn, não marca `completed`.
- `backend/tests/test_phantom_session.py` (novo) — 4 testes (2 símbolos): não-completa 0-turnos, completa legítimo, visível low-message, visível além da página 1.
- `backend/tests/test_gam_score_completion.py` (modificado) — reconciliado o caso "null score" para usar turno de aluno vazio (respeitando o novo guarda de conclusão).

**Frontend**
- `frontend/src/services/api.ts` (modificado) — `getSessions` aceita `perPage`.
- `frontend/src/views/instructor/StudentGradeDetail.tsx` (modificado) — drill-down pede `perPage: 100`.
- `frontend/src/views/instructor/InstructorDetail.tsx` (modificado) — aba Conversas pede `perPage: 100`.

**SOC-1:** nenhum arquivo da SOC-1 tocado (causa raiz não era dela).

## Change Log

| Data | Mudança | Autor |
|:---|:---|:---|
| 2026-07-15 | Story de bug fix criada a partir de `docs/goals/GOAL-sessao-fantasma.md`. Causa raiz documentada (backend `complete_chat_session` sem guarda de interação + flag de localStorage do frontend; invisibilidade por paginação). | @dev (Dex) |
| 2026-07-15 | Fix implementado: guarda server-side de interação em `complete_chat_session` (sem turno do aluno → não completa); consumidor de avaliação pede `per_page` alto (frontend). Teste vermelho→verde (`test_phantom_session.py` 4/4). Teste DATA-GAM-3 reconciliado ao novo contrato. Suíte backend exit 0, build frontend exit 0. Status → InReview. | @dev (Dex) |
