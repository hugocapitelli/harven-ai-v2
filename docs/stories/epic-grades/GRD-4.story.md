---
id: GRD-4
epic: GOAL-limite-interacoes
goal_ref: docs/goals/GOAL-limite-interacoes.md
type: bug-fix
status: InReview
severity: HIGH
terminal: Fullstack (Backend primário; Frontend 1 flag)
---
# GRD-4: Limite de interações consumido pelo kickoff do tutor

## Sintoma (screenshot do Hugo, IAA-2026, 1_Aula_Inaugural.pdf, questão 1)

Ao iniciar a sessão socrática, o kickoff do tutor chega e o limite se esgota na hora: contador
**0/3**, "Sessao concluida", input bloqueado, badge Concluído — sem o aluno mandar UMA mensagem.
Todo clique em iniciar repete.

## Frente A — Ambiente (veredito explícito)

**O backend que o Hugo roda está servindo CÓDIGO VELHO — os fixes it2/it3 da GRD-3 NÃO estão nele.**

Provas:
- `git log`: GRD-2 (`bd79ad7`) e GRD-3 (`0aa409c`) estão commitados, MAS o commit GRD-3 só levou o
  **frontend** (botão "Refazer"). `git show HEAD:backend/routes_ai.py | grep 'limit(1).maybe_single'`
  → só a linha 1565 (`by-content`, que já era correta). As correções it2 (resolve principal) e it3
  (fallback de race) do `create_or_get_chat_session` estão **UNCOMMITTED** no working tree
  (`git diff HEAD -- backend/routes_ai.py` = 17 inserções não commitadas).
- Não há processo do backend nesta máquina (`docker`/`podman`/`colima` ausentes, nada em
  `uvicorn`, porta 8000 sem listener, `curl localhost:8000/health` vazio). O `VITE_API_URL` aponta
  `http://localhost:8000` (dev) / `https://api.harven.eximiaventures.com.br` (prod). O backend do
  Hugo roda no deploy dele (Docker/EasyPanel), a partir do **`docker-compose.yml` → serviço
  `backend` → `build: Dockerfile`**, que **assa o código na imagem** (sem volume de código). Logo,
  código novo só entra com **rebuild**.

**Consequência:** o loop it2/it3 (kickoff caindo numa sessão `completed` estável → `used>=MAX` →
0/3) continua vivo para o Hugo mesmo depois dos nossos fixes, porque a imagem dele é velha.

**Comando de rebuild/restart (Frente A) — a rodar no host do backend do Hugo, após commit+deploy do
código:**
```bash
# no diretório do projeto no servidor (com docker compose)
docker compose build backend && docker compose up -d backend
# (ou, no EasyPanel: acionar "Rebuild"/"Deploy" do serviço backend após o push)
```
> Isto NÃO é fix de código — é operação de deploy. Depende de o código (GRD-2/3/4) ser commitado e
> deployado por @devops. Enquanto a imagem não for reconstruída, o backend do Hugo ignora todos os
> fixes recentes.

## Frente B — Semântica do limite (bug de produto, independente da Frente A)

**Causa raiz (nomeada):** o **kickoff** — o gatilho de abertura do tutor — era contado como turno do
aluno. O `startChat` do frontend envia `student_message: "Quero explorar a seguinte questão: {q}"`
apenas para o modelo produzir a PRIMEIRA pergunta. O backend (`ai_service.socratic_dialogue`,
~linha 807) persistia essa string como `role='user'` e a contava (`count_user_messages`), então uma
sessão RECÉM-CRIADA já lia `used=1` → `remaining=2` (o aluno perde silenciosamente 1 interação: mostra
2/3 em vez de 3/3). Combinado com o bug it2/it3 (Frente A, backend velho), o kickoff caía numa sessão
`completed` estável com `used>=MAX` → `remaining=0` → 0/3 "concluída". O comentário AI-HARD-5 no código
(*"every inbound message is a genuine student turn"*) estava factualmente errado para o kickoff.

- Como `remaining`/`should_finalize` nascem: `_derive_pacing(used)` — `remaining = MAX - used`,
  `should_finalize = used >= MAX-1`. `used = count_user_messages(session_id)` (só `role='user'`,
  correto). O defeito NÃO era contar assistant nem `total_messages`; era **persistir o kickoff como
  user turn**.
- Qual session_id as contagens usam (item 2 do diagnóstico): pós-`create_or_get`, o frontend usa o
  `sid` retornado e o passa ao kickoff — a contagem é da sessão certa. O 0/3 imediato vinha do
  kickoff-conta-turno (Frente B) e/ou da resolução de sessão errada do backend velho (Frente A),
  não de contar a sessão errada no path novo.
- Frontend: o `{remaining}/{MAX}` e o rodapé "Sessao concluida" derivam do `session_status` do
  payload do backend (`extractSessionStatus`), não de contagem local. Corrigir o backend corrige a UI.

**Fix (mínimo, opt-in e retrocompatível):** `socratic_dialogue` ganha `is_kickoff: bool = False`.
Quando `True`, NÃO persiste o gatilho como turno do aluno (pula o persist de `role='user'`); a resposta
do tutor ainda é persistida, então a pergunta de abertura fica no transcript e o pacing começa em
`used=0` → `remaining=MAX`, não finalizado. `SocraticDialogueRequest` ganha `is_kickoff` (default
False → clientes antigos e turnos reais inalterados). O `startChat` do frontend envia
`is_kickoff: true` só no kickoff; o `sendMessage` (turno real) não.

## Acceptance Criteria

1. **Causa raiz + veredito de ambiente** documentados (acima).
2. **Kickoff não consome limite:** sessão recém-criada + kickoff → `remaining == MAX`,
   `should_finalize == false`, e NENHUM turno `role='user'` persistido pelo kickoff.
   - Verificação: teste pytest (red→green).
3. **Turno real conta normalmente:** a primeira resposta genuína do aluno (sem `is_kickoff`) →
   `remaining == MAX-1`; contrato antigo preservado para todo caller existente.
4. **Gates:** `pytest` sem regressão; `npm run build` exit 0 (frontend tocado).

## Tasks

- [x] Frente A: veredito do ambiente (backend velho, rebuild necessário) + comando.
- [x] Frente B: causa raiz nomeada (kickoff contado como user turn).
- [x] Teste vermelho→verde: kickoff não consome limite / não persiste user turn; turno real conta.
- [x] Fix: `is_kickoff` no service + request + `startChat`.
- [x] `pytest` + `npm run build`.

## QA Results

**Revisor:** @qa (Quinn, Guardian) · **Data:** 2026-07-15 · **Método:** auditoria empírica independente (diff real + probe de abuso executado + gates + verificação independente da Frente A)

### Veredito: **CONCERNS**

O bug do Hugo é corrigido de verdade (a Frente B fecha o consumo indevido do kickoff no fluxo honesto,
gates verdes, retrocompatível) e a Frente A está corretamente diagnosticada e por mim confirmada
(backend velho, deploy). Mas a implementação introduz um **furo de integridade acadêmica real e por mim
PROVADO empiricamente**: o gate `is_kickoff` é controlado 100% pelo cliente, sem validação server-side, e
um aluno pode marcá-lo `true` em TODA mensagem para conversar ilimitadamente com o tutor sem consumir
limite — e ainda sem deixar rastro no histórico do professor. Não é FAIL (o objetivo primário funciona,
sem regressão), mas não pode ser PASS limpo enquanto essa superfície não for guardada. Daí CONCERNS com
uma issue HIGH e mitigação precisa.

### Verificação por AC

- **AC1 — Causa raiz + veredito de ambiente: PASS.**
  Frente A confirmada INDEPENDENTEMENTE por mim: `git show HEAD:backend/routes_ai.py | grep 'limit(1)'` →
  só a linha 1565 (`by-content`, já correta no HEAD); os fixes it2/it3 do `create_or_get_chat_session`
  (working tree linhas 1407, 1444) **e** o `is_kickoff` (`ai_service.py`) estão **UNCOMMITTED**
  (`git diff HEAD` = 43 inserções em 2 arquivos). `docker` ausente nesta máquina, porta 8000 sem listener.
  Diagnóstico do dev correto: o backend do Hugo serve imagem Docker velha; os fixes não estão nem
  commitados → nenhum deploy os tem. Frente A é operação de deploy (commit → rebuild), não código.
  (Bônus: o diff da GRD-4 CARREGA junto os fixes GRD-3 it2/it3, incluindo o `maybe_single` gêmeo do
  fallback de race na linha 1407 que eu havia registrado como Issue it2-1 residual na GRD-3 — agora
  corrigido com `.order().limit(1)`. Bom.)

- **AC2 — Kickoff não consome limite: PASS (fluxo honesto).**
  `ai_service.py:816` `if not is_kickoff:` pula a persistência do turno do aluno no kickoff; o pacing
  deriva de `count_user_messages` (linha 833) → `used=0` → `remaining=MAX`, `should_finalize=False`.
  `test_kickoff_no_limit.py::test_kickoff_leaves_full_limit_and_does_not_finalize` e
  `::test_kickoff_persists_only_the_assistant_turn` provam `remaining==MAX`, `roles==["assistant"]`,
  `count_user_messages==0`. A resposta do tutor persiste incondicionalmente (linha 946-954), então a
  pergunta de abertura fica no transcript e aparece na avaliação do professor (GRD-1 íntegra).

- **AC3 — Turno real conta normalmente: PASS.**
  `test_first_real_answer_after_kickoff_counts_one` e `test_real_turn_default_still_counts_regression`
  provam que sem `is_kickoff` (default False) o turno conta (`remaining==MAX-1`, `roles==["assistant","user"]`).
  Frontend: `is_kickoff:true` só na chamada de `startChat` (`ChapterReader.tsx:592`); o `sendMessage`
  (turno real, linha 723) NÃO o envia → default false. Contrato antigo preservado para todo caller.

- **AC4 — Gates: PASS.**
  `pytest` → **623 passed, 0 failed** (+4 kickoff vs baseline 619). `test_kickoff_no_limit.py` 4/4.
  `npm run build` → exit 0, zero TS.

### Issue HIGH — furo de integridade acadêmica (PROVADO)

**Issue GRD4-1 — [ALTA] `is_kickoff` é controlado pelo cliente sem guarda server-side → burla do limite + evasão de auditoria.**
O gate `if not is_kickoff:` (`ai_service.py:816`) confia cegamente num campo do request body
(`SocraticDialogueRequest.is_kickoff`, `routes_ai.py:115`). NÃO há nenhuma verificação server-side de que
o kickoff é legítimo (i.e., de que a sessão está de fato vazia). **Provei empiricamente** (probe QA rodado
e removido, não deixei lixo na árvore): um aluno que chame `POST` do socratic dialogue com `is_kickoff:true`
em 6 mensagens SUBSTANTIVAS consecutivas → `count_user_messages=0`, `remaining=3` (nunca decrementa),
`should_finalize=False`. Ou seja:
1. **Burla do limite acadêmico:** conversa ILIMITADA com o tutor, driblando o teto de 3 interações que é a
   regra pedagógica da feature.
2. **Evasão de auditoria:** no ramo kickoff o turno do aluno NÃO é persistido (só o assistant), então as
   respostas dele (disfarçadas de kickoff) não aparecem no histórico do professor (GRD-1) — ele recebe
   orientação do tutor sem rastro avaliável.
O front honesto só manda `is_kickoff:true` uma vez, mas a segurança não pode depender do cliente ser
honesto — a API é acessível diretamente por qualquer aluno autenticado. Os 4 testes cobrem só o caminho
feliz (um kickoff); nenhum testa `is_kickoff` repetido, o que é sintoma da ausência da guarda.
**Mitigação (precisa, barata, backend já tem os dados):** aceitar `is_kickoff=True` como efetivo APENAS
quando a sessão está genuinamente vazia — `count_user_messages(session_id) == 0` (ou `total_messages == 0`).
Se a sessão já tem turnos e chega `is_kickoff=True`, tratar como turno real (persistir e contar) ou rejeitar.
Assim o kickoff só "não conta" na abertura genuína, e qualquer tentativa de reusá-lo vira turno normal. Um
teste de abuso (`is_kickoff` repetido → limite decrementa a partir do 2º) deve acompanhar a guarda.

### Ação recomendada

**NEEDS_WORK / CONCERNS.** O fix resolve o bug do Hugo e não regride nada, mas abre uma superfície de
integridade acadêmica que precisa de guarda server-side ANTES de ir a produção (a API é diretamente
acessível ao aluno). Recomendo iteração 2: adicionar a guarda `count_user_messages == 0` no ramo kickoff +
teste de abuso. A Frente A (deploy/rebuild) permanece com @devops após commit — enquanto a imagem do Hugo
não for reconstruída com GRD-2/3/4, o backend dele ignora todos os fixes (inclusive este). Nada aqui é
bloqueio de merge do CÓDIGO da Frente B em si, mas o merge não deve ser tratado como "pronto para produção"
sem a guarda da Issue GRD4-1.

## Iteração 2 — Issue GRD4-1 [ALTA] FECHADA (guarda server-side anti-abuso)

**Problema (provado pelo QA):** `is_kickoff` é 100% controlado pelo cliente. Um aluno chamando a API
direta com `is_kickoff=true` em TODA mensagem (a) conversava ilimitado (`remaining` nunca decrementava)
e (b) NENHUMA resposta dele persistia — evadindo o transcript/avaliação do professor. Furo de
integridade acadêmica.

**Fix (guarda server-side):** `is_kickoff` só é honrado numa sessão genuinamente FRESCA. O gate roda no
`socratic_dialogue` antes de decidir persistir.

**Correção da mitigação literal (importante):** a instrução era "honrar só quando
`count_user_messages == 0`". Isso é **insuficiente e foi provado empiricamente**: um kickoff honrado
persiste ZERO turnos de aluno, então um `is_kickoff` replicado continuaria lendo
`count_user_messages == 0` e seria honrado para sempre (bypass persistiria). O sinal correto de "a
sessão já começou?" é o TRANSCRIPT TOTAL: após o primeiro kickoff honrado, a resposta de abertura do
tutor (persistida como `assistant`) torna o transcript não-vazio. Guarda final:
`effective_kickoff = is_kickoff and len(get_session_messages(session_id)) == 0`. Da 2ª mensagem em
diante — mesmo com a flag — a mensagem é tratada como turno real: persistida e contada. `should_finalize`
volta a funcionar. (A contagem `used` é lida uma vez e reusada no pacing, sem double-read.)

**Teste de abuso red→green:** `TestKickoffAbuseGuard` (2 testes): N mensagens substantivas seguidas com
`is_kickoff=True` → só a 1ª (sessão vazia) é kickoff; da 2ª em diante persiste como user e decrementa
`remaining`; após MAX turnos reais `should_finalize=True`; e as 3 respostas abusivas TODAS persistem
(sem evasão de histórico). RED provado contra o código da it1 (`assert 0 == 3` user msgs — as respostas
sumiam). Verde com a guarda. Os 4 testes originais de kickoff seguem verdes (kickoff legítimo intacto).

---

### Re-gate QA — Iteração 2 (@qa Quinn, 2026-07-15)

**Veredito final: PASS.** A Issue GRD4-1 [ALTA] está fechada de verdade, verificada empiricamente por mim.
O furo que provei na it1 não se reproduz mais. Suíte 625/0, sem regressão. Libera o pacote GRD-3 it2/it3 +
GRD-4 it1/it2 para commit+push.

**A guarda fecha o replay — reconfirmado por probe independente:** o MESMO probe que na it1 provou o abuso
(6 mensagens `is_kickoff=True` → `count=0, remaining=3`, conversa ilimitada) agora dá, com a guarda,
`count_user_messages=5, remaining=0, user_msgs_persisted=5, should_finalize=True`. Só o 1º kickoff (sessão
de transcript vazio) é honrado; os 5 replays viram turnos reais (persistidos E contados). Probe rodado
dentro de `tests/` para o conftest resolver, e removido em seguida — sem lixo na árvore.

**Revisão explícita da minha mitigação da it1 — eu estava errado, o dev acertou:**
Na it1 propus `count_user_messages(session_id) == 0` como guarda. **Concordo, com franqueza, que era
insuficiente.** O dev provou o furo da minha própria proposta: um kickoff honrado persiste ZERO turnos de
aluno, então `count_user_messages` fica em 0 para sempre — um replay de `is_kickoff=True` continuaria lendo
`count==0` e seria honrado eternamente, deixando o furo aberto. O sinal correto de "a sessão já começou?" é
o **transcript TOTAL** (`len(get_session_messages) == 0`), porque a resposta do tutor ao 1º kickoff persiste
como `assistant` (linha ~940) e torna o transcript não-vazio. A partir daí qualquer mensagem — mesmo
flagueada `is_kickoff` — é turno real. Diagnóstico afiado; o gate existe para pegar exatamente isto, e pegou
inclusive contra a minha proposta. Anti-resulting: minha it1 estava certa em EXIGIR a guarda e em provar o
furo, e errada no MECANISMO da guarda — registro os dois lados.

**Os 2 testes de abuso cobrem ambos os vetores que levantei:**
- `test_repeated_is_kickoff_only_honored_on_empty_session`: replay até passar do limite → 1º honrado, demais
  contam (`count == i`), `remaining` clampa em 0, `should_finalize=True` após MAX. Fecha a **burla de limite**.
- `test_abuse_persists_every_answer_no_history_evasion`: 3 respostas abusivas com `is_kickoff=True` → todas
  persistem como `user` (`len(user_msgs) == 3`). Fecha a **evasão de histórico** (o professor vê tudo).

**Vetores de julgamento independente pedidos (ambos avaliados, severidade real baixa):**

- **Race de dois kickoffs simultâneos em sessão vazia — [LOW, não bloqueante].** Dois requests concorrentes
  no instante de criação podem ambos ler `transcript` vazio → ambos `effective_kickoff=True` → ambos pulam a
  contagem. Efeito máximo: 1 turno a mais não-contado (o aluno ganha no máximo +1 folga de limite), NÃO
  conversa ilimitada. Exige disparo concorrente na janela mínima de criação da sessão. Comparado ao furo
  original (ilimitado), é impacto desprezível. Registro como nota, não bloqueia. (Fechamento rigoroso seria
  uma unique/idempotência no persist do 1º turno, refinamento futuro.)

- **Fallback defensivo em falha de leitura do DB — [LOW-MÉDIA, não bloqueante].** Se `count_user_messages`/
  `get_session_messages` levantam (linha 848), `used` cai no default client-supplied
  (`max(0, MAX - interactions_remaining)`) e o turno não persiste. Em tese, sob DB falhando na leitura, um
  atacante mandando `interactions_remaining=20` leria `used=0` e não consumiria. **Por que não bloqueia:**
  (a) só ocorre com o DB FALHANDO na leitura — cenário de degradação de infra que já compromete a
  plataforma inteira, não um caminho explorável em operação normal; (b) é o MESMO contrato legado
  best-effort de pacing pré-GRD-4 (`pragma: no cover - persistence is best-effort` é herança), não uma
  regressão introduzida aqui; (c) o atacante não ganha nada que o caminho sem-sessão legado já não
  permitisse. **Recomendação (refinamento futuro, opcional):** fail-closed — em falha de leitura, tratar
  como turno real e NÃO honrar o kickoff (nega em vez de degradar permissivo). Fora do escopo do bug fix.

**Gates (it2):** `pytest` → **625 passed, 0 failed** (+2 abuso vs it1 623). `test_kickoff_no_limit.py` 6/6
(4 originais + 2 abuso). (Frontend não mudou na it2; build já era exit 0 na it1.)

### Ação recomendada (it2)

**PASS.** O furo de integridade acadêmica está fechado com a guarda correta (transcript total, não meu
`count==0`), os dois vetores testados, a suíte 625/0 sem regressão, e os dois riscos residuais que avaliei
são LOW de operação-anormal, não furos exploráveis sob uso normal. **Libero o pacote GRD-3 it2/it3 +
GRD-4 it1/it2 para commit+push por @devops.** Lembrete operacional (não-bloqueante): a Frente A só se
materializa quando @devops fizer o rebuild/redeploy da imagem do backend do Hugo — enquanto a imagem velha
rodar, nenhum destes fixes chega ao ambiente dele.

## File List

**Backend**
- `backend/services/ai_service.py` (modificado, it1 + **it2**) — `socratic_dialogue(is_kickoff=False)`:
  pula a persistência do turno do aluno quando é kickoff (não conta contra o limite). **it2 (GRD4-1):**
  guarda server-side — só honra o kickoff se o transcript estiver vazio (`get_session_messages == 0`);
  senão trata como turno real (persiste + conta). `used` lido uma vez e reusado no pacing.
- `backend/routes_ai.py` (modificado) — `SocraticDialogueRequest.is_kickoff` (default False) +
  propagação para o service.
- `backend/tests/test_kickoff_no_limit.py` (novo, ampliado na it2) — 6 testes: kickoff não finaliza /
  persiste só o assistant / turno real conta / regressão do default (it1, red-provado revertendo o gate);
  **+ `TestKickoffAbuseGuard` (2 testes) — replay abusivo de `is_kickoff` só honra a 1ª vez, decrementa
  daí em diante, finaliza, e persiste toda resposta (sem evasão de histórico); red-provado** (`assert
  0==3`) contra o código da it1.
- `backend/tests/test_tutor_persistence.py` (modificado) — docstring de
  `test_opening_message_persists_both_turns` atualizada ao contrato GRD-4 (o path default sem
  `is_kickoff` permanece inalterado; o kickoff é coberto no arquivo novo).

**Frontend**
- `frontend/src/views/courses/ChapterReader.tsx` (modificado) — `startChat` envia `is_kickoff: true`
  na chamada de kickoff.

**SOC-1:** nenhum arquivo de produção da SOC-1 alterado; o motor socrático não teve o pacing
reescrito (só a semântica de "o que conta como turno" no kickoff).

## Change Log

| Data | Mudança | Autor |
|:---|:---|:---|
| 2026-07-15 | Story de bug fix criada a partir de `docs/goals/GOAL-limite-interacoes.md`. Frente A: veredito = backend do Hugo serve código velho (fixes it2/it3 uncommitted; imagem Docker sem rebuild), comando de rebuild registrado. Frente B: causa raiz = kickoff persistido/contado como turno do aluno; fix `is_kickoff` (opt-in, retrocompatível) no service+request+startChat. Teste red→green (`test_kickoff_no_limit.py`, 4 testes). Gates verdes (pytest exit 0, build exit 0). Status → InReview. | @dev (Dex) |
| 2026-07-15 | **Iteração 2 (Issue GRD4-1 [ALTA] FECHADA):** guarda server-side contra abuso de `is_kickoff` (client-controlled). Só honra o kickoff em sessão de transcript vazio (`get_session_messages == 0`) — a mitigação literal `count_user_messages==0` era insuficiente (kickoff persiste 0 user turns → replay leria 0 p/ sempre), provado empiricamente; sinal correto = transcript total. Replay abusivo vira turno real (persiste + conta), `should_finalize` restaurado, sem evasão de histórico. +2 testes de abuso red→green. Suíte exit 0. | @dev (Dex) |
