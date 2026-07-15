---
id: GRD-5
epic: GOAL-resume-500
goal_ref: docs/goals/GOAL-resume-500.md
type: bug-fix
status: InReview
severity: HIGH
terminal: Backend
---
# GRD-5: 500 no resume do chat (GET messages / by-content)

## Sintoma (console do browser, build de produção)

`Chat resume error: AxiosError 500` no recurso `messages` (2x), vindo do `ChapterReader`. O aluno
não consegue retomar/abrir a sessão. O caminho é a hidratação do capítulo → `by-content` → GET
messages.

## Causa raiz (nomeada)

**`supabase-py` / `postgrest` 2.28.x retorna `None` (o objeto de resposta INTEIRO, não
`_Result(data=None)`) de `.maybe_single().execute()` quando ZERO linhas casam.** Precedente REAL neste
repo: commit `5847a60` (ontem) corrigiu exatamente isso em `BaseRepository.get_by_id` — mesmo 500 na
geração de áudio. O pin é `supabase>=2.0.0` (não travado), e a produção do Hugo, após o rebuild, subiu
com a 2.28.x.

O endpoint do resume `GET /chat-sessions/by-content/{content_id}` (`routes_ai.py`
`get_session_by_content`) lia `session = result.data` **sem guarda**. Quando o aluno NÃO tem sessão
para aquele conteúdo (o caso comum ao abrir um capítulo fresco), `result` é `None` →
`None.data` → `AttributeError` → **HTTP 500**, em vez do 404 pretendido. O frontend faz
`byContent(...).catch(() => null)` esperando 404 = "sem sessão"; um 500 não é tratado assim e vira o
`Chat resume error: 500`.

**Por que os fixes it2/it3 (GRD-3) NÃO causaram e NÃO estavam protegidos disso:** eles trocaram
`maybe_single` cru por `.order().limit(1).maybe_single()` para resolver o multi-row (PGRST116), mas a
leitura de `.data` do `by-content` já existia crua ANTES deles — o rebuild só expôs o 500 do zero-row
porque a versão nova da lib mudou a semântica de "0 linhas" de `data=None` para `None`.

**O fake mascarava o bug:** `FakeSupabaseClient.maybe_single` retornava `_Result(data=None)` em 0
linhas, então a suíte não reproduzia o 500. Tornei o fake fiel (0 linhas → `execute()` retorna `None`,
como a 2.28.x). Rodando a suíte com o fake fiel, os pontos que quebraram são exatamente os `.data`
crus de produção — os candidatos a 500.

**Outros sites com o mesmo anti-pattern (varredura, protegidos junto):** além do `by-content`, o fake
fiel revelou 500 reais em `routes_admin.py`:
- `unlock_achievement` (L1261): `if existing_res.data` — a 1ª conquista de um usuário não tem linha → 500.
- `issue_certificate` (L1356): idem, o 1º certificado de um curso → 500.
E um risco secundário em `export_session_moodle` (`routes_ai.py`, `user_result.data` de um dono deletado).
Todos protegidos com o padrão do `5847a60` (`res.data if res is not None else None` ou o idiom
`... .execute() or type("_R", (), {"data": None})()` já usado neste arquivo). Os demais `.maybe_single()`
do caminho de resume (`load_session_or_404`, `create_or_get` resolve/fallback) JÁ eram guardados
(`getattr(res,"data",None)` / `if result`).

> **Correção pós-QA (it2):** a afirmação da it1 de que a varredura estava completa era FALSA — o QA
> achou 2 sites que escaparam (fora do caminho de resume, mas do mesmo anti-pattern), um deles crítico.
> Fechados na iteração 2 abaixo. A varredura agora cobre auth + password reset + o pin da lib.

## Fix

- `routes_ai.py` `get_session_by_content`: `session = result.data if result is not None else None`
  (o caso vazio agora dá 404, como o frontend espera).
- `routes_ai.py` `export_session_moodle`: `user_data = user_result.data if user_result is not None else None`.
- `routes_admin.py` `unlock_achievement` e `issue_certificate`: `.execute() or type("_R",(),{"data":None})()`.
- `tests/fakes.py`: `.maybe_single().execute()` fiel — 0 linhas → `None` (não `_Result(data=None)`).
- `tests/security/test_harness_smoke.py`: asserção atualizada ao contrato fiel (`missing is None`).

## Acceptance Criteria

1. Causa raiz nomeada (semântica 2.28.x, precedente `5847a60`) — acima.
2. Teste vermelho→verde reproduzindo o 500 do resume (fake fiel ao `None`).
3. Resume (`by-content` → messages) não 500a em nenhum estado legítimo: sem sessão, sessão nova,
   multi-row, completed.
4. `pytest` exit 0.

## Tasks

- [x] Fake `maybe_single` fiel no 0-linhas (`None`, como 2.28.x).
- [x] Rodar suíte com fake fiel → localizar os `.data` crus (by-content + 3 em routes_admin/moodle).
- [x] Teste vermelho do 500 do resume (`test_resume_no_500.py`) + fix None-guard (padrão `5847a60`).
- [x] Varrer/proteger os outros `.maybe_single()` do caminho de resume.
- [x] `pytest` exit 0.

## QA Results

**Revisor:** @qa (Quinn, Guardian) · **Data:** 2026-07-15 · **Método:** auditoria empírica independente (diff + grep adversarial de TODOS os `.maybe_single().execute()` de produção + inspeção sítio a sítio + pytest)

### Veredito: **CONCERNS**

O bug do Hugo (resume 500) está corrigido de verdade, com None-guard no padrão do repo (`5847a60`),
teste vermelho→verde, 404 correto no caso vazio, e os 3 sites irmãos citados protegidos. Gates verdes
(629/0). **Mas a varredura declarada como completa NÃO é:** o grep adversarial de todos os
`.maybe_single().execute()` de produção revelou **2 sites remanescentes com `.data` cru não-guardado que
a suíte NÃO exercita** — um deles no `auth.py` (`get_current_user`, o caminho de TODA request
autenticada). São da MESMA família do bug do Hugo, latentes para o próximo cenário de 0-linhas na 2.28.x.
Como o objetivo primário (destravar o Hugo) está cumprido e provado, isto não é FAIL — mas a incompletude
da varredura + um gap crítico impedem o PASS limpo.

### Verificação por AC / item da tarefa

- **AC1/AC2 — Causa raiz + teste vermelho→verde: PASS.**
  Causa raiz correta e alinhada ao precedente `5847a60` (supabase-py/postgrest 2.28.x → `.maybe_single().
  execute()` devolve `None`, não `_Result(data=None)`, em 0 linhas). O fake foi tornado fiel
  (`fakes.py`: 0 linhas → `None`), que é o que dava à suíte o poder de reproduzir o 500 antes do fix.

- **AC3 — Resume não 500a em estado legítimo: PASS (para o caminho do resume).**
  `get_session_by_content` (`routes_ai.py:1586`): `session = result.data if result is not None else None`
  → `if not session: raise 404`. O caso vazio vira **404** (não 200-null que confundiria o frontend), que
  é o que `byContent(...).catch(() => null)` espera. `test_resume_no_500.py` cobre os 4 estados: sem
  sessão (404), com sessão (200), multi-row (newest 200, sem PGRST116), messages de sessão inexistente
  (404). Fecha a rubrica item 3 para o caminho do resume.

- **AC4 — Gates: PASS.**
  `pytest` → **629 passed, 0 failed** (+4 resume vs baseline 625). `test_resume_no_500.py` 4/4.

- **Padrão do repo: PASS.** Dois idioms, ambos do precedente `5847a60`: guard explícito
  (`x if x is not None else None`) em `routes_ai.py`; idiom-sentinela (`.execute() or type("_R",(),
  {"data":None})()`) em `routes_admin.py` — este último já usado neste arquivo, consistente.

### Item 4 (o achado do gate) — sites de produção NÃO cobertos (falso-verde por falta de teste)

Rodei o grep de TODOS os `.maybe_single().execute()` de produção e inspecionei sítio a sítio como cada um
lê `.data`. A maioria está segura: `routes_ai.py:439-465` (bloco de enriquecimento) usa `if x and x.data`
(curto-circuita o None); `routes_admin.py:1557/1609` usam o idiom-sentinela; os repositórios (`base.py`
etc.) já foram guardados no `5847a60`. **Dois escaparam da varredura:**

**Issue GRD5-1 — [ALTA] `auth.py:56` (`get_current_user`) lê `res.data` cru.**
```python
res = client.table("users").select("*").eq("id", user_id).maybe_single().execute()
if res.data is None:   # se res É None (0 linhas na 2.28.x) → res.data levanta AttributeError → 500
```
`get_current_user` (`auth.py:38`) é a dependency de autenticação de praticamente todo endpoint protegido.
Cenário real: um token JWT ainda válido cujo `user_id` foi deletado do banco → 0 linhas → `res` é `None`
→ `res.data` crasha ANTES do `is None` ser avaliado → **HTTP 500 em vez do 401 pretendido**, no caminho
de TODA request autenticada. Nenhum teste exercita isso (os testes mockam o user via
`dependency_overrides`, que bypassa a query real). Mesma família do bug do Hugo, mais crítico que os
certificados que a story protegeu. **Fix (1 linha, padrão do repo):** `if res is None or res.data is None:`.

**Issue GRD5-2 — [MÉDIA] `main.py:472` (password reset) lê `res.data` cru.**
```python
res = client.table("users").select("id, email").eq("email", body.email).maybe_single().execute()
if res.data:   # email inexistente → 0 linhas → res None → res.data AttributeError → 500
```
Fluxo de recuperação de senha (acessível sem auth): um email não cadastrado → 500 em vez de silenciosamente
não emitir token. Não coberto pela suíte. **Fix:** `if res is not None and res.data:`.

Ambos são exatamente o anti-pattern que o fake fiel foi criado para expor — mas só quebram sob 0 linhas, e
nenhum teste os aciona com esse estado, então passam "verdes" por ausência de teste, não por correção.

### Item 5 — pin do supabase (risco residual, concordo)

**Issue GRD5-3 — [MÉDIA, não bloqueante] `supabase>=2.0.0` solto (`backend/requirements.txt:3`).**
Este pin frouxo foi exatamente o que deixou a 2.28.x entrar no rebuild e mudar a semântica de 0-linhas,
disparando toda esta classe de 500. Recomendo pin exato (`supabase==2.28.x` da versão validada) ou range
restrito (`>=2.28,<2.29`), para que um próximo rebuild não introduza outra mudança de contrato silenciosa.
Não bloqueia o merge do fix, mas sem isso a superfície de risco de "rebuild muda semântica" permanece aberta.

### Ação recomendada

**CONCERNS — libere o fix do RESUME (destrava o Hugo agora), mas trate a varredura como incompleta.** O
código do resume em si é correto, testado e pode ir a produção imediatamente para desbloquear o Hugo. Porém:
recomendo FORTEMENTE incluir a Issue GRD5-1 (`auth.py`, ALTA — 500 em todo request autenticado quando o
user some) no MESMO commit, já que é 1 linha, mesma família, e o rebuild que quebrou o resume também
exporia isso. GRD5-2 (password reset) e GRD5-3 (pin) podem ser follow-up curto. A story afirma ter varrido
e protegido "todos" os sites irmãos — o grep prova que 2 ficaram de fora; corrija a alegação ou feche os 2.
Se o coordenador optar por commitar só o resume pela urgência, que seja com a ciência explícita de que
`auth.py:56` continua um 500 latente da mesma classe.

## Iteração 2 — 3 issues do QA FECHADAS

Todas do mesmo anti-pattern (`.maybe_single().execute()` → `None` em 0 linhas, 2.28.x). A alegação de
"varredura completa" da it1 foi corrigida (era falsa).

**GRD5-1 [ALTA] `auth.get_current_user` (`auth.py:56`):** `if res.data is None:` crashava quando `res`
era `None` — token VÁLIDO cujo `sub` aponta para usuário DELETADO dava 500 em TODO endpoint protegido, em
vez de 401. Fix: `if res is None or res.data is None:`. **Impacto:** era o pior da classe — afetava toda a
superfície autenticada. Teste `test_valid_token_for_missing_user_is_401` exercita a dependency REAL (token
JWT genuíno assinado com o secret semeado, sem override de `get_current_user`) → 401; red-provado (500).

**GRD5-2 [MÉDIA] `main.request_password_reset` (`main.py:472`):** email inexistente → `res` `None` →
`res.data` crashava 500. Além do 500, o status 500-vs-200 vazaria existência de conta (quebra o
anti-enumeration). Fix: `if res is not None and res.data:` — o email inexistente cai no MESMO 200 neutro.
Teste: reset de email desconhecido = 200 neutro (sem token, sem id), idêntico ao de email conhecido;
red-provado.

**GRD5-3 [MÉDIA] pin do supabase (`requirements.txt`):** `supabase>=2.0.0` solto deixou a 2.28.x entrar no
rebuild (a versão instalada aqui é 2.28.2). O código + guardas agora ASSUMEM a semântica None-em-0-linhas
da 2.28.x. Pin restrito para `supabase>=2.28,<3`: trava a semântica assumida (piso) e impede um major (3.x)
de re-mudar o contrato silenciosamente (teto). Estilo consistente com os ranges já presentes no arquivo
(`sentry-sdk[fastapi]>=2.0.0`, `pymupdf4llm>=1.27.0`).

**Achado de test-infra (documentado):** o teste de GRD5-1 falhava só no full-run (verde isolado) por
**vazamento de `dependency_overrides`** — as fixtures `as_student`/`as_admin` instalam override de
`get_current_user` no `main.app` (singleton) e NÃO o removem, então ele vazava para o meu teto que precisa
da dependency REAL. Fixture autouse do meu arquivo faz `pop` do override + invalida o cache module-level do
JWT secret (as suítes de rotação o mutam), garantindo determinismo por ordem. (Não toquei o `conftest` para
não afetar outras suítes; o pop é local ao meu arquivo.)

## File List

**Backend**
- `backend/routes_ai.py` (modificado) — None-guard em `get_session_by_content` (resume, o 500 do Hugo)
  e em `export_session_moodle`.
- `backend/routes_admin.py` (modificado) — None-guard (idiom `or type(...)`) em `unlock_achievement`
  e `issue_certificate` (mesmo anti-pattern, revelado pelo fake fiel).
- `backend/tests/fakes.py` (modificado) — `.maybe_single().execute()` fiel à 2.28.x: 0 linhas → `None`.
- `backend/tests/test_resume_no_500.py` (novo) — 4 testes: by-content sem sessão = 404 (red-provado
  = 500 antes do fix); com sessão = 200; multi-row = newest 200; messages de sessão inexistente = 404.
- `backend/tests/security/test_harness_smoke.py` (modificado) — asserção do zero-row atualizada ao
  contrato fiel (`missing is None`).

**Backend (iteração 2)**
- `backend/auth.py` (modificado) — None-guard em `get_current_user` (GRD5-1: token válido de usuário
  deletado = 401, não 500 em toda a superfície autenticada).
- `backend/main.py` (modificado) — None-guard em `request_password_reset` (GRD5-2: email inexistente =
  200 neutro, sem 500 nem vazamento de existência).
- `backend/requirements.txt` (modificado) — pin `supabase>=2.28,<3` (GRD5-3).
- `backend/tests/test_deleted_user_no_500.py` (novo) — 4 testes: token de usuário deletado = 401
  (red-provado = 500), token de usuário existente ainda funciona, reset de email desconhecido/conhecido =
  200 neutro idêntico (anti-enumeration). Fixture local pop do override + refresh do cache JWT.

**SOC-1 / GRD-3:** nenhum comportamento de produção da SOC-1/GRD-3 alterado; só adicionadas guardas
None defensivas nos `.data` crus (o `.order().limit(1)` dos fixes GRD-3 permanece).

## Change Log

| Data | Mudança | Autor |
|:---|:---|:---|
| 2026-07-15 | Story de bug fix. Causa raiz = `.maybe_single().execute()` retorna `None` em 0 linhas no supabase-py 2.28.x (precedente `5847a60`); `get_session_by_content` (resume) lia `result.data` cru → 500. Fake tornado fiel ao `None`, revelando +3 sites (unlock_achievement, issue_certificate, moodle). Todos protegidos com None-guard. Teste red→green (`test_resume_no_500.py`). Suíte exit 0. Status → InReview. | @dev (Dex) |
| 2026-07-15 | **Iteração 2 (3 issues do QA fechadas):** GRD5-1 [ALTA] `auth.get_current_user` (token de usuário deletado dava 500 em toda superfície autenticada → 401); GRD5-2 [MÉDIA] `main.request_password_reset` (email inexistente 500 + vazamento de existência → 200 neutro); GRD5-3 [MÉDIA] pin `supabase>=2.28,<3` (a 2.0.0 solto deixou a 2.28.x entrar). Testes red→green nas 2 primeiras (`test_deleted_user_no_500.py`). Corrigida a alegação falsa de "varredura completa" da it1. Achado: vazamento de `dependency_overrides` do conftest tratado localmente. Suíte exit 0 (estável, 2 runs). | @dev (Dex) |
