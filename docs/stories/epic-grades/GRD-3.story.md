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

## Iteração 2 — bug real no teste ao vivo (loop refazer → trava)

**Sintoma:** clicar "Refazer sessao" → o kickoff do tutor aparecia → a UI voltava imediatamente
ao estado finalizado ("Sessao concluida", input bloqueado, contador 0/3, badge "Concluído"). Loop
morto: refazer → kickoff → trava → refazer.

**Causa raiz (nomeada):** `create_or_get_chat_session` (`backend/routes_ai.py`) resolvia a sessão
existente com um **`.maybe_single()` cru** sobre `(user_id, content_id)`. Depois de QUALQUER refazer
(ou de um fantasma GRD-2), esse par tem legitimamente ≥2 linhas (SEC-CHAT-3 mantém a `completed` ao
lado da nova tentativa). O `.maybe_single()` do supabase-py **levanta `PGRST116` em >1 linha** → o
endpoint dá 500 OU resolve uma linha `completed` ambígua, então o kickoff rodava contra uma sessão
FINALIZADA (`count_user_messages >= MAX` → `remaining=0`/`should_finalize=true`) e o painel voltava
a "concluída". O próprio código já sabia disso: `get_session_by_content` (mesmo arquivo, ~1558)
comenta *"A bare `.maybe_single()` would 500 on >1 row; order by newest and take one"* — mas o
`create_or_get` não seguia a mesma disciplina. Essa assimetria era o bug. (Cobre e supera a Nota 1
LOW do QA da iteração 1: o estado transitório apontado lá era uma faceta do mesmo problema de
resolução de sessão.)

**Fix (mínimo):** `create_or_get_chat_session` passa a resolver a sessão MAIS RECENTE com
`.order("created_at", desc=True).limit(1).maybe_single()`, espelhando `get_session_by_content`. Com
várias linhas a janela reduz a 1 (nunca levanta) e a newest (a nova tentativa ativa) é a avaliada.

**Prova no caminho real:** o fake `.maybe_single()` foi tornado FIEL ao supabase-py (levanta
`PGRST116` em >1 linha pós-limit/range); sem isso o teste não reproduziria o 500 real.
`test_restart_with_multiple_completed_rows_does_not_break` — com o código ANTIGO (bare maybe_single)
o fake levanta e o teste FALHA (vermelho reproduzido, provado revertendo o fix temporariamente); com
o fix passa. `test_restart_when_newest_is_active_resumes_not_duplicates` guarda a direção oposta
(newest ativa → resume, sem duplicar). Suíte inteira exit 0 (o `maybe_single` estrito não quebrou
nenhum consumidor existente).

**Revisão manual das 3 situações:** (1) primeira sessão: sem linha → cria ativa → kickoff persiste 1
turno → 2/3, input ativo; (2) sessão ativa: newest ativa → resume (getMessages, sem kickoff); (3)
refazer: newest completed → cria nova ativa distinta → kickoff → 2/3, input ativo, sem snap-back.

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

---

### Re-gate — Iteração 2 (@qa Quinn, 2026-07-15)

**Veredito final: PASS.** A causa raiz REAL do bug do Hugo (refazer → kickoff → snap-back para "Sessão
concluída" com input travado) estava no BACKEND, não no `ChapterReader`, e foi corrigida com o mínimo certo.
Suíte 618/0 estável em 2 runs, build exit 0. Um achado residual da mesma família (não corrigido, só
registrado, conforme a missão).

**Revisão explícita da minha Nota 1 LOW da iteração 1 — eu errei a atribuição de causa:**
Na it1 registrei como "benigno" o botão de rodapé aparecer em `remainingInteractions <= 0` com sessão
ainda `active`, supondo que o único efeito era o `createOrGet` devolver a mesma sessão. **A it2 mostra que
o mecanismo real do travamento era outro e não-benigno:** `create_or_get_chat_session` (`routes_ai.py:1433`)
usava `.maybe_single()` **cru** sobre `(user_id, content_id)`. Como esse par legitimamente tem ≥2 linhas
após um refazer ou um fantasma (SEC-CHAT-3 mantém a `completed` ao lado da nova) — fato agora documentado
também em `chat_repo.py:50-55` (`get_by_content_user`: "`(content_id, user_id)` is NOT unique") — o
supabase real levanta `PGRST116` em >1 linha, e o endpoint ou dava 500 ou resolvia uma linha `completed`
ambígua/velha. O kickoff então rodava numa sessão FINALIZADA (`count_user_messages >= MAX` → remaining 0 /
finalized) e a UI voltava para "Sessão concluída" com input travado: o loop morto que o Hugo reportou.
Ou seja, o snap-back que eu tratei como borda benigna tinha causa raiz backend real. O crédito é do dev por
rastreá-lo; registro a correção do meu julgamento anterior com franqueza (anti-resulting: minha it1 não era
"falso alarme", era diagnóstico incompleto que apontou o sintoma adjacente e errou a causa).

**Fix da it2 — mínimo, correto, simétrico:**
- `routes_ai.py:1433` — `.maybe_single()` → `.order("created_at", desc=True).limit(1).maybe_single()`. UMA
  linha. Alinha `create_or_get_chat_session` à MESMA disciplina que `get_session_by_content` (`:1575`) e o
  repo `get_by_content_user` já usavam. Assimetria (a causa raiz) eliminada.
- **Semântica SOC-1 intacta:** o fix só muda QUAL linha é lida no create-or-get (a mais recente, a nova
  ativa), não a escrita da pergunta. First-write-wins do `initial_question_text` preservado — a nova sessão
  grava sua própria pergunta na criação; uma `active` existente é resumida com a pergunta original
  (`test_restart_when_newest_is_active_resumes_not_duplicates`).
- **Fake fiel (`fakes.py:193-205`):** `maybe_single` agora levanta `PGRST116` quando `len(matched) > 1`,
  **após** a aplicação de `order`/`range`/`limit` (ordem verificada no `_QueryBuilder.execute`, linhas
  172→183→186→193). Logo: bare `.maybe_single()` + multi-row → raise (reproduz o bug); `.order().limit(1)`
  → 1 linha → passa. Isso dá ao fake o poder de REPROVAR o teste red, provando que o teste
  `test_restart_with_multiple_completed_rows_does_not_break` genuinamente falha sem o fix. Verificação robusta.

**Fake fiel pode mascarar/quebrar teste antigo que dependia do comportamento frouxo?**
Não. Rodei a suíte inteira 2× (618/0 em ambas, ordem aleatória e default). O `maybe_single` só passou a
levantar no caso `>1 linha`, que nenhum teste antigo exercitava sem `.limit(1)`/`.eq(id)` (as consultas por
`id`/chave única nunca retornam >1). O `test_maybe_single_none_regression.py` (zero-row → None) continua
verde. Nenhuma dependência do comportamento frouxo foi quebrada — o fake ficou MAIS fiel, não mais restrito
arbitrariamente.

**Gates (it2):** `pytest` → **618 passed, 0 failed** (2 runs, estável; +2 vs it1 pelos testes red/guard novos).
`test_restart_session.py` 4/4. `npm run build` → exit 0, zero TS.

### Achado residual — REGISTRO (não corrigido, mesma família do bug)

**Issue it2-1 — [MEDIA] `maybe_single` cru remanescente no fallback de race da MESMA função.**
`create_or_get_chat_session` tem, no caminho de fallback de unique-violation (`routes_ai.py:1394-1396`), um
`.maybe_single()` **ainda cru** sobre `(user_id, content_id)`:
```python
existing = client.table("chat_sessions").select("*").eq("user_id", uid).eq("content_id", content_id).maybe_single().execute()
```
Como o par NÃO é único (a própria premissa do fix da it2, corroborada por `chat_repo.py:51`), este re-read
de fallback pode encontrar ≥2 linhas e quebrar com `PGRST116` — reintroduzindo o mesmo defeito no caminho de
exceção. Mitigante: só dispara quando o `_create_chat_session_row` levanta (insert concorrente perdeu a
corrida), coincidindo com um par já multi-row — probabilidade baixa, por isso MEDIA e não ALTA, e por isso
não travou os testes atuais (nenhum exercita race + multi-row simultâneos). **Recomendação:** aplicar a
MESMA disciplina (`.order("created_at", desc=True).limit(1)`) nesse re-read, e cobrir com um teste de
"race-fallback com par multi-row". Fora do escopo mínimo desta iteração (o bug primário do Hugo está fechado);
registro para uma próxima passada. NÃO corrigi (missão: só auditar).

**Outros `maybe_single` de produção varridos — sem risco:** o restante das ~40 ocorrências consulta por
`id`/`ra`/`email`/`code`/`session_id` (chaves únicas ou pseudo-únicas, nunca `(user,content)` de sessão), ou
já usa `.order().limit(1)` (`routes_ai.py:1575`, `chat_repo.py:63/106`, `routes_admin.py:143` com `.limit(1)`).
O único par genuinamente NÃO-único que ainda está bare em produção é a linha 1394 acima.

### Ação recomendada (it2)

Aprovar (PASS). A causa raiz real do loop do Hugo foi corrigida com o mínimo simétrico, o fake ficou fiel
sem quebrar nada, a suíte é 618/0 estável e o build é verde. Recomendo abrir um follow-up leve para a Issue
it2-1 (o `maybe_single` cru gêmeo no fallback de race, linha 1394) — mesma família, não bloqueia o merge da
GRD-3.

## Iteração 3 — Issue it2-1 FECHADA (teto do loop, 3/3)

**Fix:** apliquei a mesma disciplina `.order("created_at", desc=True).limit(1).maybe_single()` no re-read do
fallback de race em `_upsert_chat_session_row` (`routes_ai.py`, ~1394-1401). Agora as TRÊS resoluções de
sessão por `(user_id, content_id)` em `routes_ai.py` são consistentes: main resolve (1438), race fallback
(1401) e `by-content` (1580). Nenhuma pode mais levantar `PGRST116` em par multi-row.

**Teste do branch:** `test_race_fallback_reread_with_multiple_rows_does_not_break` força o `except` do
fallback determinísticamente (chama `_upsert_chat_session_row` direto, com o par já multi-row e
`_create_chat_session_row` monkeypatchado para levantar — simulando o insert concorrente perdido) e assevera
que o re-read resolve a sessão MAIS RECENTE (`race-done-2`) sem quebrar. Red provado revertendo só a linha do
fallback para `maybe_single` cru → o fake fiel levanta `PGRST116` e o teste FALHA; com o fix, passa.

**Sweep confirmado (checagem de 1 min, task 3):** `grep` das ~40 ocorrências de `maybe_single` em
`routes_ai.py`/`routes_admin.py`/`main.py`. Todas as remanescentes consultam por chave única/pseudo-única
(`id`, `session_id` de review — SOC-1 garante 1 review/sessão via 409, `user_id` de `user_stats` — 1 linha/
usuário) ou já usam `.limit(1)`. O ÚNICO par genuinamente não-único (`chat_sessions` por `(user_id,
content_id)`) tinha exatamente as 2 leituras bare que a it2 (1438) e a it3 (1401) fecharam. **it2-1 era, de
fato, a última.** Issue FECHADA.

## File List

**Frontend**
- `frontend/src/views/courses/ChapterReader.tsx` (modificado) — estado `completedSession`,
  hidratação do caso `completed`, função `restartChat`, botão "Refazer sessao" no rodapé do
  chat finalizado e banner na seção Questões Socráticas.

**Backend**
- `backend/routes_ai.py` (modificado, **iterações 2 e 3**) — `create_or_get_chat_session` resolve a
  sessão mais recente via `.order("created_at", desc=True).limit(1).maybe_single()` em vez de
  `.maybe_single()` cru, corrigindo o 500/resolução-ambígua em `(user_id, content_id)` com ≥2 linhas
  (a causa do loop refazer→trava). **it3:** a MESMA disciplina aplicada ao re-read do fallback de race
  em `_upsert_chat_session_row` (o gêmeo remanescente, issue it2-1). As 3 leituras do par ficam consistentes.
- `backend/tests/test_restart_session.py` (novo, ampliado nas iterações 2 e 3) — 5 testes: restart de
  sessão fantasma (0 msgs, mesma pergunta) cria sessão nova distinta + preserva histórico;
  `by-content` resolve para a nova ativa; **múltiplas linhas completed não quebram o create-or-get**
  (red-provado); newest ativa → resume sem duplicar; **it3: race-fallback com par multi-row resolve a
  mais recente sem PGRST116** (branch do `except` forçado, red-provado).
- `backend/tests/fakes.py` (modificado, **iteração 2**) — `.maybe_single()` do fake tornado fiel ao
  supabase-py: levanta `PGRST116` em >1 linha (pós-limit/range), para o teste reproduzir o 500 real.

**SOC-1:** nenhum arquivo de produção da SOC-1 alterado nesta story; o contrato de pergunta
única/nova tentativa foi reusado como está. (A iteração 2 tocou `create_or_get_chat_session`, que é
o endpoint compartilhado de sessão, corrigindo a resolução de linha múltipla; não altera a semântica
de first-write-wins nem o lock da SOC-1, apenas troca `maybe_single` cru por newest+limit(1).)

## Change Log

| Data | Mudança | Autor |
|:---|:---|:---|
| 2026-07-15 | Story criada a partir de `docs/goals/GOAL-refazer-sessao.md`. "Refazer sessão" implementado no `ChapterReader` (frontend puro sobre o contrato de nova tentativa já existente do backend/SOC-1); 2 testes backend do fluxo de refazer (fantasma + histórico). Gates verdes (build exit 0, pytest exit 0). Status → InReview. | @dev (Dex) |
| 2026-07-15 | **Iteração 2 (bug ao vivo, loop refazer→trava):** causa raiz = `create_or_get_chat_session` usava `.maybe_single()` cru sobre `(user_id, content_id)`, que levanta `PGRST116` / resolve linha ambígua quando o par tem ≥2 sessões (pós-refazer / fantasma GRD-2), fazendo o kickoff rodar contra a sessão finalizada. Fix: resolver a newest via `.order().limit(1).maybe_single()` (espelha `by-content`). Fake `maybe_single` tornado fiel (levanta em >1 linha) p/ prova real; +2 testes (multi-row + newest-active). Suíte exit 0, build exit 0. | @dev (Dex) |
| 2026-07-15 | **Iteração 3 (teto do loop, issue it2-1 FECHADA):** o gêmeo do bug — `.maybe_single()` cru no re-read do fallback de race de `_upsert_chat_session_row` (~1394) — corrigido com a mesma disciplina `.order().limit(1)`. As 3 resoluções do par ficam consistentes. +1 teste do branch `except` (race + multi-row → resolve a mais recente sem PGRST116, red-provado forçando o fallback). Sweep de ~40 `maybe_single` confirmou que este era o último par não-único cru. Suíte exit 0. | @dev (Dex) |
