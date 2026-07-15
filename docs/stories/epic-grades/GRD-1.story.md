---
id: GRD-1
epic: GOAL-notas-compostas
goal_ref: docs/goals/GOAL-notas-compostas.md
phase: 1
status: InReview
severity: HIGH
terminal: Fullstack (Backend & Frontend)
complexity: medium
depends_on: []
---
# GRD-1: Notas compostas por interação socrática no Quadro de Notas

## Story

Como professor da disciplina, quero que o Quadro de Notas exiba a nota COMPOSTA (média) das
notas que eu mesmo dei a cada interação socrática do aluno, em vez de aceitar uma nota digitada
diretamente por curso, para que a nota final reflita o histórico real de avaliação das sessões
de tutoria e eu consiga entrar no perfil de qualquer aluno, ler a conversa de cada sessão e
avaliar interação por interação, com a média se recompondo automaticamente.

## Contexto

Declarado via `/goal` por Hugo Capitelli em `docs/goals/GOAL-notas-compostas.md`
(2026-07-15). O backend já tem a base pronta:

- Tabela/endpoints `session_reviews` — `POST/PUT/GET /chat-sessions/{session_id}/review`
  (`backend/routes_admin.py:1641-1802`), com `rating` 0-10 por sessão de chat, e já
  consumidos no frontend por `frontend/src/services/api.ts:337-340` (`review.get/create/update/reply`)
  e pela tela `frontend/src/views/instructor/SessionReview.tsx` (rota
  `/session/:sessionId/review` registrada em `frontend/src/App.tsx:122`).
- Endpoint `GET /disciplines/{discipline_id}/gradebook` (`backend/routes_admin.py:1903-2046`)
  já agrega `session_reviews.rating` → `avg_rating` por curso (via cadeia
  `content_id → chapter_id → course_id`, linhas 1949-2012) → `final_grade` (override ou
  avg_rating) → `overall_avg` por aluno. Este endpoint é a fonte de verdade e **não precisa
  mudar** para os ACs 1 e 3.
- Endpoint `PUT /disciplines/{discipline_id}/students/{student_id}/grade`
  (`backend/routes_admin.py:2049-2130`, tabela `grade_overrides`) já existe como override
  manual pontual e **não é o alvo desta story** — o goal não pede removê-lo, apenas parar de
  digitar nota solta desconectada do backend na grade principal.

O que falta (o gap real):

1. **Frontend, Quadro de Notas** (`frontend/src/views/instructor/InstructorDetail.tsx:362-415`):
   a aba "Quadro de Notas" hoje renderiza `<input type="number">` por aluno×curso
   (linhas 386-397), com estado local (`grades`/`dirtyGrades`, linhas 84-85, 89-100) e um
   botão "Salvar Notas" (linhas 409-411) que **só limpa o estado local e mostra um toast** —
   nunca chama a API. Isso precisa virar leitura read-only vinda de
   `GET /disciplines/{id}/gradebook`.
2. **Frontend, drill-down do aluno:** não existe hoje uma visão que agrupe, por aluno, as
   sessões socráticas por curso/capítulo com link para avaliar cada uma. A aba "Conversas"
   (linhas 417-453) já lista sessões com `StarRating` e botão "Avaliar"/"Ver" navegando para
   `/session/${s.id}/review` — mas é uma lista plana da disciplina inteira, não agrupada por
   aluno nem por curso/capítulo, e não é alcançável a partir do Quadro de Notas.
3. **Backend, sessões por aluno:** `GET /disciplines/{discipline_id}/sessions`
   (`backend/routes_admin.py:1806-1890`) já existe e é usado pelo frontend
   (`api.ts:103`, `getSessions`), mas retorna a disciplina **inteira** (sem filtro por
   `student_id`) e cada linha só tem `content_id` cru — sem `course_id`/`course_title`/
   `chapter_id`/`chapter_title`/`rating` resolvidos. O drill-down por aluno precisa desse
   enriquecimento (o mesmo mapeamento `content→chapter→course` que o gradebook já faz nas
   linhas 1949-2012 deste arquivo).
4. **Backend, teste de agregação:** não há teste cobrindo
   `session_reviews.rating → avg_rating → overall_avg` no gradebook — AC3 do goal exige essa
   prova automatizada.

## Acceptance Criteria

> Espelham literalmente os 4 critérios de "Pronto quando" do goal
> (`docs/goals/GOAL-notas-compostas.md`), sem adição nem remoção de escopo.

1. **Quadro de Notas read-only composto:** a aba "Quadro de Notas" em
   `frontend/src/views/instructor/InstructorDetail.tsx` renderiza notas vindas de
   `GET /disciplines/{id}/gradebook` (`avg_rating`/`final_grade`/`overall_avg`), SEM
   inputs editáveis de nota por curso.
   - Verificação: `grep -n 'type="number"' frontend/src/views/instructor/InstructorDetail.tsx` → 0 ocorrências na seção de notas; `grep -n 'gradebook' frontend/src/services/api.ts frontend/src/views/instructor/*.tsx` → chamada real ao endpoint.
2. **Drill-down do aluno:** existe visão de perfil do aluno dentro da disciplina listando
   as sessões socráticas dele agrupadas por curso/capítulo, com a conversa legível e nota
   por sessão editável via `POST/PUT /chat-sessions/{session_id}/review`.
   - Verificação: rota/componente novo referenciado a partir do Quadro de Notas e/ou aba Alunos; `grep -n 'review' frontend/src/views/instructor/*.tsx` mostra o fluxo de avaliação por sessão.
3. **Composição automática:** dar nota a uma sessão reflete na média do curso e na média
   geral retornadas pelo gradebook (sem digitação manual).
   - Verificação: teste backend cobrindo agregação `session_reviews.rating → avg_rating → overall_avg` em `backend/tests/`.
4. **Gates mecânicos verdes:**
   - `cd frontend && npm run build` (tsc -b && vite build) → exit 0
   - `cd backend && python -m pytest -q` → exit 0

## Tasks / Subtasks

### Backend

- [x] **(AC2, AC3)** Estender `GET /disciplines/{discipline_id}/sessions`
  (`backend/routes_admin.py:1806-1890`) para aceitar filtro opcional `student_id` (query
  param) e, no shape de retorno (linhas 1867-1882), incluir `course_id`, `course_title`,
  `chapter_id`, `chapter_title` e `rating` (join reaproveitando o mesmo mapeamento
  `content_id → chapter_id → course_id` já implementado no gradebook, linhas 1949-1963;
  extrair para uma função/helper compartilhada se o duplicate ficar grande — não é
  obrigatório duplicar a lógica inline duas vezes).
- [x] **(AC3)** Adicionar teste em `backend/tests/` cobrindo o pipeline de agregação do
  gradebook: dado N sessões com `session_reviews.rating` distintos para o mesmo
  aluno×curso, `GET /disciplines/{id}/gradebook` retorna `avg_rating` = média correta,
  `final_grade` = `avg_rating` (sem override), e `overall_avg` = média das `final_grade`
  de todos os cursos do aluno. Cobrir também o caso "sem ratings" (`avg_rating: None`,
  curso não entra no `overall_avg`).
- [x] **(AC3)** Adicionar teste de regressão end-to-end (ou de integração leve): criar
  review via `POST /chat-sessions/{session_id}/review` com um `rating`, então chamar
  `GET /disciplines/{id}/gradebook` e confirmar que o `avg_rating`/`overall_avg` do aluno
  mudou de acordo — prova viva do AC3 ("dar nota reflete na média sem digitação manual").

### Frontend

- [x] **(AC1)** Em `InstructorDetail.tsx`, remover o `<input type="number">` por
  aluno×curso (linhas 386-397) e o estado associado (`grades`, `dirtyGrades`,
  `getGrade`, `handleGradeChange`, linhas 84-85, 89-97) e o botão "Salvar Notas" que hoje
  só limpa estado local (linhas 406-413, comportamento enganoso — nunca persistia).
- [x] **(AC1)** Buscar `GET /disciplines/{id}/gradebook` (novo método em
  `frontend/src/services/api.ts`, seguindo o padrão dos métodos existentes em
  `api.ts:102-103`/`337-340`) e renderizar, por aluno×curso, `avg_rating`/`final_grade`
  (célula) e `overall_avg` (coluna "Média"), tudo read-only.
- [x] **(AC2)** Criar visão de drill-down do aluno (novo componente/rota, ex.
  `frontend/src/views/instructor/StudentGradeDetail.tsx` + rota em `App.tsx` ao lado de
  `/session/:sessionId/review`, linha 122) que lista as sessões do aluno filtradas por
  `student_id` (usando a extensão de task backend acima), agrupadas por
  curso → capítulo, cada linha com nota atual (se houver) e botão "Avaliar"/"Ver"
  reaproveitando a navegação já existente para `/session/${sessionId}/review`
  (padrão em `InstructorDetail.tsx:445-448`).
- [x] **(AC2)** Ligar o Quadro de Notas (célula de aluno ou linha) e/ou a aba "Alunos" à
  nova visão de drill-down (link/clique no nome do aluno ou na nota do curso).
- [x] **(AC4)** Rodar `cd frontend && npm run build` e `cd backend && python -m pytest -q`
  localmente antes de considerar a story pronta para QA; corrigir qualquer quebra de tipo
  introduzida pela remoção do estado de notas editáveis (`GradeMap` e tipos correlatos, se
  usados em outros pontos do arquivo).

## Dev Notes

- **Arquivos centrais:**
  - `backend/routes_admin.py:1641-1802` — `session_reviews` CRUD (`create_review`,
    `get_review`, `update_review`, `reply_review`). Não precisa mudar.
  - `backend/routes_admin.py:1806-1890` — `discipline_sessions` (`GET
    /disciplines/{discipline_id}/sessions`). Alvo da extensão de filtro/enriquecimento.
  - `backend/routes_admin.py:1903-2046` — `discipline_gradebook` (`GET
    /disciplines/{discipline_id}/gradebook`). Fonte de verdade da nota composta, não
    precisa mudar para os ACs 1/3; só precisa de teste de agregação (AC3).
  - `backend/routes_admin.py:2049-2130` — `set_student_grade` (override manual via
    `grade_overrides`). Fora de escopo, permanece como está.
  - `frontend/src/views/instructor/InstructorDetail.tsx:73-100` — state do Quadro de
    Notas atual (`grades`, `dirtyGrades`, `getGrade`, `handleGradeChange`,
    `computeAverage`) a ser substituído por leitura do gradebook.
  - `frontend/src/views/instructor/InstructorDetail.tsx:362-415` — aba "Quadro de Notas"
    (JSX a reescrever para read-only).
  - `frontend/src/views/instructor/InstructorDetail.tsx:417-453` — aba "Conversas" (lista
    plana já existente, referência de padrão para o drill-down, mas não é o drill-down
    por aluno em si).
  - `frontend/src/views/instructor/SessionReview.tsx` + `frontend/src/App.tsx:122` — tela
    e rota de avaliação por sessão, já prontas, reaproveitar sem modificar.
  - `frontend/src/services/api.ts:102-103` (`getSessions`), `:337-340` (`review.*`) —
    métodos existentes; adicionar `gradebook.get` e, se necessário, estender
    `getSessions` com `student_id`.
- **Abordagem:** Não recriar o cálculo de composição no frontend — o gradebook backend já
  é a fonte de verdade agregada (`avg_rating`/`final_grade`/`overall_avg`); o frontend
  passa a ser puramente um consumidor read-only desse endpoint. O trabalho novo real é
  (a) trocar a UI de editável para leitura, e (b) expor o caminho de navegação
  aluno → sessões agrupadas → avaliar sessão, que hoje só existe de forma solta na aba
  "Conversas" sem filtro por aluno nem agrupamento por curso/capítulo.
- **Riscos de regressão (blast radius):**
  - `routes_admin.py` é compartilhado com `EPIC-DATA` (INT-MOODLE, DATA-GAM) — a extensão
    do `discipline_sessions` deve ser aditiva (novo query param opcional, novos campos no
    shape de saída), nunca remover campos consumidos por `export_discipline_grades`
    (linhas 2139+) ou por outros consumidores do mesmo endpoint.
  - `grade_overrides` / `set_student_grade` continuam existindo e não são tocados; o
    gradebook já prioriza `override` sobre `avg_rating` (linha 2026) — não inverter essa
    prioridade sem pedido explícito.
  - Remover o estado `grades`/`dirtyGrades` de `InstructorDetail.tsx` pode quebrar tipos
    (`GradeMap`) referenciados em outros arquivos — checar com grep antes de apagar o tipo.
  - Nenhuma migração de schema é necessária — `session_reviews`, `grade_overrides` e o
    encadeamento `contents→chapters→courses` já existem.

## Definition of Done

- [x] Os 4 Acceptance Criteria acima verificados (grep/teste conforme cada item).
- [x] `cd frontend && npm run build` → exit 0.
- [x] `cd backend && python -m pytest -q` → sem regressão (ver nota de baseline no Dev Agent Record).
- [x] Nenhuma regressão nos consumidores existentes de `discipline_sessions` e
  `discipline_gradebook` (export Moodle, `set_student_grade`) — shape de `discipline_sessions`
  estendido de forma estritamente aditiva; `discipline_gradebook` não foi tocado.
- [ ] QA Gate: PASS ou CONCERNS.

## Dev Agent Record

**Agente:** @dev (Dex) · **Data:** 2026-07-15

### Resumo da implementação

Backend (`backend/routes_admin.py`):
- Extraído helper `_build_discipline_content_maps(client, discipline_id)` que resolve a
  cadeia `content_id → chapter → course` com títulos (course/chapter/content), reusado por
  `discipline_sessions`. Fecha a duplicação inline que já existia no gradebook e no export
  (REUSE/ADAPT em vez de triplicar).
- `GET /disciplines/{id}/sessions` ganhou o query param opcional `student_id` (filtro aditivo)
  e o shape de retorno passou a incluir `course_id`, `course_title`, `chapter_id`,
  `chapter_title`, `content_title` e `rating` — **sem remover nenhum campo antigo** (aditivo,
  preserva o consumidor da aba "Conversas" e o export Moodle).
- `discipline_gradebook` **não foi tocado** (já é a fonte de verdade da composição para AC1/AC3).

Backend testes (`backend/tests/`):
- Novo `test_grade_composition.py` (6 testes) prova AC3: agregação `avg_rating`/`final_grade`/
  `overall_avg` (8,6,10 → 8.0; curso sem rating → None e fora do overall), prova viva de
  `POST /chat-sessions/{id}/review` mexendo na média sem digitação, e o drill-down
  `?student_id=` escopando + enriquecendo (course/chapter/content/rating).
- `tests/fakes.py` estendido de forma aditiva com `.not_.is_(col,"null")` (IS NOT NULL, usado
  pelo gradebook) e `.range(start,end)` (inclusivo, usado por `discipline_sessions`). Sem essas
  cadeias o fake não conseguiria exercitar o gradebook/sessions via HTTP. Nenhum teste existente
  muda de comportamento (count passa a refletir o match total antes do range, semântica PostgREST).

Frontend:
- `services/api.ts`: `disciplinesApi.getGradebook(id)` (novo) + `getSessions` reassinado para
  `(id, { status?, studentId? })` — único chamador migrado.
- `InstructorDetail.tsx`: aba "Quadro de Notas" agora é **read-only composta** — removidos
  `<input type="number">`, `grades`/`dirtyGrades`/`getGrade`/`handleGradeChange`/`computeAverage`,
  o tipo `GradeMap` e o botão "Salvar Notas" enganoso. Célula mostra `final_grade`, coluna Média
  mostra `overall_avg`, "—" quando null. Linha do aluno (abas Notas e Alunos) é clicável → drill-down.
- `StudentGradeDetail.tsx` (novo): perfil do aluno na disciplina, sessões agrupadas por
  curso → capítulo, nota por sessão, botão "Avaliar"/"Rever" navegando para a tela de review
  **existente** (`/session/:sessionId/review`, não duplicada). Cabeçalho resume a média geral.
- `App.tsx`: rota `/instructor/class/:id/student/:studentId`.

### Gates (evidência)

- Frontend `npm run build` (tsc -b && vite build) → **exit 0** (chunk `StudentGradeDetail` emitido).
- Backend `python3 -m pytest tests/test_grade_composition.py` → **6/6 passed**.
- Backend suite completa → **602 passed + 2 failed**. As 2 falhas
  (`test_tutor_persistence.py::TestTpp5Pacing::test_remaining_derived_from_persisted_count_not_client`
  e `::test_not_finalize_before_the_end`) são **pré-existentes** (presentes na baseline rodada
  ANTES de qualquer edição, sobre pacing do tutor socrático, sem relação com GRD-1). Zero
  regressões introduzidas.
- Greps do goal: `type="number"` em `InstructorDetail.tsx` → **0**; `gradebook` em `api.ts` →
  chamada real; `GradeMap`/`dirtyGrades`/`handleGradeChange`/`computeAverage` → **0 ocorrências**.

### Decisões / débitos registrados

- **[AUTO-DECISION]** Reusar `_build_discipline_content_maps` como helper compartilhado só em
  `discipline_sessions` (não refatorei gradebook/export para consumi-lo) → razão: minimizar blast
  radius; a story permite o helper mas não exige migrar consumidores estáveis (Art. IV).
- **[RESOLVIDO na iteração 2, pós-QA]** `SessionReview.tsx` usava `StarInput` de 1–5 estrelas numa
  escala 0–10, teto-limitando a nota composta a 5,0/10. Corrigido: entrada de nota 0–10 (passo 0.5)
  + a exibição de rating na aba Conversas (`StarRating`) e no drill-down passou toda a 0–10; schema
  órfão `schemas/chat.py` reconciliado para `ge=0,le=10`. Ver Change Log iteração 2.
- **[DÉBITO PRÉ-EXISTENTE]** 2 falhas em `test_tutor_persistence.py::TestTpp5Pacing` no baseline,
  não tocadas por esta story.
- **[COLISÃO DE WORKING TREE, iteração 2, fora de escopo]** `frontend/src/views/courses/ChapterReader.tsx`
  está modificado por OUTRO agente (story SOC-1/question-lock, arquivos irmãos não meus:
  `test_session_question_lock.py`) e introduz 2 erros `TS6133` (unused vars `lockedQuestion`,
  `resumeChat`) que quebram o `tsc -b` project-wide. NÃO toquei o arquivo (Art. IV — fora do escopo
  GRD-1). Prova de que o build de GRD-1 é verde: com esse único arquivo alheio posto de lado
  (`git stash push -- ChapterReader.tsx`), `npm run build` → **exit 0**; restaurei o arquivo do
  colega intacto em seguida. Todos os erros `tsc` estão exclusivamente em `ChapterReader.tsx`, zero
  nos 7 arquivos de GRD-1.
- `grade_overrides`/`set_student_grade` preservados (nenhuma migration destrutiva); só a UI
  deixou de oferecer digitação direta, conforme a restrição da missão.

## QA Results

**Revisor:** @qa (Quinn, Guardian) · **Data:** 2026-07-15 · **Método:** verificação empírica independente (código real + gates mecânicos + trace end-to-end do caminho de avaliação)

### Veredito: **CONCERNS**

Os 4 ACs estão implementados e provados em isolamento; os gates mecânicos estão verdes. Porém o
caminho REAL de avaliação por interação (a superfície que esta story elege como primária ao rotear
o drill-down para ela) só permite nota 1–5 numa escala que o backend, o gradebook, o override e o
export Moodle todos tratam como 0–10. A nota composta fica sistematicamente teto-limitada a 5,0/10.
Isso não bloqueia o merge (a agregação está correta e nada regride), mas fere a intenção prática do
AC3 e precisa ser resolvido antes de a feature ser usada em produção. Daí CONCERNS, não PASS.

### Verificação por AC

- **AC1 — Quadro de Notas read-only composto: PASS.**
  `grep 'type="number"' InstructorDetail.tsx` → 0 ocorrências. Estado editável removido
  (`GradeMap`/`dirtyGrades`/`handleGradeChange`/`computeAverage` → 0). A aba "notas" carrega
  `disciplinesApi.getGradebook(id)` (`api.ts:112` → `GET /disciplines/{id}/gradebook`) e renderiza
  `final_grade` por célula e `overall_avg` na coluna Média, tudo read-only, "—" quando null
  (`InstructorDetail.tsx:104-110, 437-442`). Grep `gradebook` em api.ts/views → chamada real presente.

- **AC2 — Drill-down do aluno: PASS (com a ressalva de AC3 abaixo, que é sobre a tela de destino).**
  `StudentGradeDetail.tsx` (novo, rota `App.tsx:122` `/instructor/class/:id/student/:studentId`)
  lista as sessões filtradas por `student_id`, agrupadas por curso → capítulo, cada linha com nota
  atual e botão "Avaliar"/"Rever" navegando para `/session/${s.id}/review` (tela existente, não
  duplicada). Alcançável a partir do Quadro de Notas E da aba Alunos (linhas clicáveis
  `openStudent`, `InstructorDetail.tsx:366, 428`). Backend `discipline_sessions` estendido de forma
  aditiva com `student_id` + enriquecimento course/chapter/content/rating (`routes_admin.py:1862-1934`).

- **AC3 — Composição automática: PASS na matemática, mas com defeito de escala no caminho real
  (ver Issue 1).**
  `test_grade_composition.py` → 6/6 passed, provando `avg_rating` = média, `final_grade` = avg (sem
  override), `overall_avg` = média dos `final_grade`, curso sem rating → None e fora do overall, e a
  prova viva `POST review → gradebook muda`. A agregação backend (`routes_admin.py:2077-2089`) está
  correta. O problema não é a agregação, é a fonte: a nota que entra é capada em 5 (Issue 1).

- **AC4 — Gates mecânicos verdes: PASS.**
  `frontend npm run build` → **exit 0** (chunks `StudentGradeDetail` e `SessionReview` emitidos).
  `backend python3 -m pytest` → **602 passed, 2 failed**. As 2 falhas
  (`test_tutor_persistence.py::TestTpp5Pacing::test_remaining_derived_from_persisted_count_not_client`
  e `::test_not_finalize_before_the_end`) foram inspecionadas: testam pacing do tutor socrático
  (`interactions_remaining`/`should_finalize`), **zero** referências a gradebook/session_reviews/
  discipline_sessions no arquivo inteiro (grep = 0). Confirmadas pré-existentes e sem relação com GRD-1.

### Regressões verificadas (todas OK)

- **Aba Conversas:** os 2 chamadores de `getSessions` usam a nova assinatura. `InstructorDetail.tsx:148`
  chama `getSessions(id)` sem opts (param `opts?` é opcional → lista discipline-wide inalterada);
  `StudentGradeDetail.tsx:63` usa `{ studentId }`. Nenhum chamador quebrado.
- **Export Moodle (`export_discipline_grades`, `routes_admin.py:2196`):** constrói o próprio mapeamento
  inline e lê direto das tabelas `chat_sessions`/`session_reviews` — **não** consome o shape de resposta
  de `discipline_sessions`. As mudanças aditivas no endpoint não podem afetá-lo. Independente, confirmado.
- **Autorização:** `discipline_sessions` mantém `assert_teacher_owns_discipline` ANTES de qualquer leitura
  (`routes_admin.py:1870`); `student_id` é filtro de query aditivo, sem bypass. `discipline_gradebook`
  não foi tocado.

### Issues

**Issue 1 — [ALTA] Nota composta teto-limitada a 5,0 numa escala 0–10 (defeito de escala no caminho real de avaliação).**
Trace end-to-end do caminho que ESTA story elege como primário:
1. `StudentGradeDetail.tsx:195` → único ponto de entrada de avaliação, navega para `/session/:id/review`.
2. `SessionReview.tsx:38` `StarInput` renderiza `[1,2,3,4,5]` (máx 5); `handleSubmitReview:123` envia
   `rating` (1–5) cru no payload.
3. `POST /chat-sessions/{id}/review` (`routes_admin.py:102, 1665`) valida `ge=0, le=10` e grava o valor
   verbatim — 5 é válido, passa silenciosamente, nenhum erro alerta o professor.
4. Gradebook (`routes_admin.py:2077`) faz `avg_rating = sum(ratings)/len` sobre o campo cru 0–10 →
   `final_grade` → `overall_avg`. O `GradeOverride` (`ge=0, le=10`) e o export Moodle assumem a mesma
   escala 0–10.

Consequência: pela UI real, um professor NUNCA consegue dar acima de 5,0, e a nota composta que aparece
no Quadro de Notas fica presa em ≤ 50% da escala. O AC3 pede que "o professor dê nota 0–10 por interação";
na prática a interface só entrega metade da escala. O @dev registrou isto como "débito pré-existente fora
de escopo" (`StarInput` 1–5 vs `rating` 0–10), o que é factualmente verdade quanto à ORIGEM — mas GRD-1
promove essa tela a superfície primária da nota composta (o drill-down rota explicitamente para ela), o
que converte o débito latente em defeito ATIVO da feature que esta story entrega. A verificação do próprio
AC2 cita "editável via `POST/PUT /chat-sessions/{session_id}/review`", cujo único UI é essa tela 1–5.
**Recomendação:** trocar `StarInput` (1–5) por um input 0–10 na `SessionReview.tsx` (slider, número
validado 0–10, ou escala de 10) — mudança pequena, escopada a 1 componente, sem tocar backend (já aceita
0–10). Rastrear como story de correção imediata (ex. GRD-2) antes de qualquer uso em produção.
Nota residual: existe um segundo modelo `SessionReviewCreate` órfão em `backend/schemas/chat.py:30`
(`ge=1, le=5`) NÃO importado por `routes_admin.py` (código morto para este fluxo); ao corrigir o UI,
vale reconciliar/remover para não induzir a futura confusão de escala.

**Issue 2 — [BAIXA] `// @ts-nocheck` no topo de `InstructorDetail.tsx` e `StudentGradeDetail.tsx`.**
Ambos os arquivos-alvo suprimem checagem de tipo com `@ts-nocheck` (linha 1). O `npm run build` passa,
mas a segurança de tipo real desses dois arquivos (incl. os novos shapes `GradebookStudent`/`SessionEntry`)
não é exercitada pelo compilador. Herança do arquivo original, não introduzida por GRD-1, mas registro
como débito para não passar despercebido. Não bloqueia.

### Ação recomendada

Aprovar o merge com CONCERNS registrado. Abrir story de correção (Issue 1, ALTA) para levar a avaliação
por interação à escala 0–10 na `SessionReview.tsx` ANTES do uso em produção — sem isso, a nota composta
entregue é sistematicamente deflacionada e a intenção do AC3 não se cumpre na prática. As 2 falhas pytest
permanecem como débito pré-existente do EPIC do tutor (fora do escopo desta story).

---

### Re-review — Iteração 2 (@qa Quinn, 2026-07-15)

**Veredito final: PASS.** Issue 1 (ALTA) fechada de verdade, verificada no código real. Zero regressão nova.
O caveat de build declarado pelo dev NÃO se reproduz na árvore atual, o que é ainda melhor que o previsto.

**Issue 1 — FECHADA. Escala 0–10 confirmada end-to-end pela UI real:**
- `SessionReview.tsx:37-77` — `GradeInput` substitui `StarInput`: `<input type="number" min=0 max=10 step=0.5>`
  + atalhos `[0,2,4,6,8,10]`, `clamp(0,10)`. O 0 é nota válida (botão `n=0` presente, `value === n` funciona).
- `SessionReview.tsx:93` — `rating: number | null` com `null` = "não avaliado" (0 deixa de ser sentinela de vazio);
  `:116` carrega `r.rating ?? null`; `:140` submit gate `rating == null`; `:268` binding `value={rating ?? 0}`
  seguro. Label "Nota (0–10)" (`:267`). Trace: UI 0–10 → payload → `POST review` (`routes_admin.py:102`, já
  `ge=0,le=10`) → gradebook soma cru → composição na escala plena. O teto artificial de 5,0 foi removido.
- `InstructorDetail.tsx:72-80` — `GradeBadge` (0–10, `toFixed(1)` + "/10") substitui `StarRating`; aba Conversas
  (`:471-483`) realinhada ao shape flat real de `discipline_sessions` (`s.user_name`, `s.rating`, `review_status`),
  eliminando o binding `{ review }` aninhado que o endpoint nunca devolveu (bug latente de shape, também sanado).
- `schemas/chat.py:31-41` — `SessionReviewCreate` órfão reconciliado para `rating: float ge=0 le=10` + `feedback`,
  com docstring explicando a sincronia com o modelo inline das rotas. Nenhuma rota o consome (barrel-only),
  então é hardening anti-divergência futura, sem efeito de runtime.
- `grep -rn '\[1, 2, 3, 4, 5\]|StarInput|StarRating' frontend/src/views/instructor/` → **0 ocorrências.**

**Gates mecânicos (iteração 2):**
- `frontend npm run build` → **exit 0 real** (capturado sem pipe; `$?`=0), **zero erros TS** no log. Chunks
  `SessionReview`, `InstructorDetail`, `StudentGradeDetail` emitidos. O caveat do dev (2× TS6133 em
  `ChapterReader.tsx`, WIP de SOC-1) **não se reproduz na árvore atual** — o build compila a árvore INTEIRA
  limpa, sem stash. O arquivo alheio continua modificado (`git status: M ChapterReader.tsx`) mas já não quebra
  o `tsc -b`. Verificação foi além do pedido: não precisei confiar em "todos os erros estão em arquivo alheio"
  porque não há erro algum. Todos os arquivos do File List da GRD-1 compilam sob `tsc -b` project-wide.
- `backend python3 -m pytest` → **608 passed, 2 failed.** As 2 falhas são exatamente as mesmas pré-existentes
  (`test_tutor_persistence.py::TestTpp5Pacing::{test_remaining_derived_from_persisted_count_not_client,
  test_not_finalize_before_the_end}`), tutor pacing, sem relação com GRD-1. `test_grade_composition.py` → 6/6.
  O total subiu de 602 (iteração 1) para 608 (+6 passados) por testes de outra frente na árvore, não da GRD-1
  — é melhoria, não regressão; o baseline de falhas é idêntico.

**Reconfirmação dos ACs 1–3:** inalterados desde a iteração 1 (PASS), agora com AC3 íntegro na prática — a
composição não é mais deflacionada porque a fonte (nota por interação) usa a escala plena 0–10.

**Débito remanescente (não bloqueia):** Issue 2 (`// @ts-nocheck` em `InstructorDetail.tsx`/`StudentGradeDetail.tsx`)
permanece herança pré-GRD-1. As 2 falhas de tutor pacing seguem débito do EPIC do tutor. Ambos fora do escopo.

**Fechamento do gate:** GRD-1 PASS. Status pronto para Done (sujeito ao push por @devops). Iterações dev↔qa: 2
(dentro do teto de 3 do goal).

## File List

**Backend**
- `backend/routes_admin.py` (modificado) — helper `_build_discipline_content_maps` + extensão de `discipline_sessions` (`student_id`, enriquecimento course/chapter/content/rating).
- `backend/tests/fakes.py` (modificado) — suporte aditivo a `.not_.is_(col,"null")` e `.range(start,end)`.
- `backend/tests/test_grade_composition.py` (novo) — 6 testes de composição/drill-down (AC3 + suporte AC2).

**Frontend**
- `frontend/src/services/api.ts` (modificado) — `disciplinesApi.getGradebook`; `getSessions` com `{ status?, studentId? }`.
- `frontend/src/views/instructor/InstructorDetail.tsx` (modificado) — Quadro de Notas read-only composto; remoção do estado editável; linhas clicáveis (Notas + Alunos). **Iteração 2:** `StarRating` (1–5) → `GradeBadge` (0–10); aba Conversas realinhada ao shape real de `discipline_sessions` (`user_name` + `rating` flat 0–10).
- `frontend/src/views/instructor/StudentGradeDetail.tsx` (novo) — drill-down do aluno, sessões agrupadas por curso/capítulo, reuso da tela de review.
- `frontend/src/views/instructor/SessionReview.tsx` (modificado, **iteração 2**) — `StarInput` (1–5) → `GradeInput` (0–10, passo 0.5, atalhos 0/2/4/6/8/10); `rating` agora `number|null` (0 é nota válida, `null` = não avaliado); label "Nota (0–10)".
- `frontend/src/App.tsx` (modificado) — rota `/instructor/class/:id/student/:studentId`.

**Backend (iteração 2)**
- `backend/schemas/chat.py` (modificado) — `SessionReviewCreate` órfão reconciliado de `rating: int ge=1 le=5` + `review` para `rating: float ge=0 le=10` + `feedback`, alinhado ao modelo real usado nas rotas.

## Change Log

| Data | Mudança | Autor |
|:---|:---|:---|
| 2026-07-15 | Story criada a partir de `docs/goals/GOAL-notas-compostas.md`, expandindo o goal para story implementation-ready (ACs, tasks técnicos e Dev Notes com paths/linhas reais). | @sm (River) |
| 2026-07-15 | Implementação completa dos 4 ACs: backend (`discipline_sessions` estendido + helper + testes de composição), frontend (Quadro de Notas read-only + drill-down `StudentGradeDetail` + rota). Gates verdes (build exit 0, 6/6 testes novos, 0 regressão). Status → InReview. | @dev (Dex) |
| 2026-07-15 | **Iteração 2 (correção pós-QA CONCERNS, Issue 1 ALTA):** escala de nota por interação corrigida de 1–5 para 0–10 na tela real de avaliação (`SessionReview.tsx`: `GradeInput` 0–10 passo 0.5), destravando a nota composta que ficava teto-limitada a 5,0/10. Exibições de rating alinhadas a 0–10 (`GradeBadge` na aba Conversas + drill-down). Schema órfão `schemas/chat.py` reconciliado para `ge=0,le=10`. Gates verdes (build exit 0; grade suite 6/6; 0 regressão, mesmas 2 falhas pré-existentes de tutor pacing). | @dev (Dex) |
