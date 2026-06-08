---
id: SEC-ADMIN-1
epic: EPIC-SEC
phase: 2
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: medium
depends_on: [SEC-ATO-3]
bug_refs: [49, 16, 62, 14, 25]
---
# SEC-ADMIN-1: Bootstrap harness de teste backend (pytest + TestClient + fake Supabase)

## Story
Como engenheiro de backend responsável pela trilha de segurança do EPIC-SEC, quero um harness de teste backend executável (pytest + FastAPI `TestClient` + fake do cliente Supabase com builder encadeado + seed de fixtures), para que as Stories de remediação de IDOR/role-gate do cluster `idor-admin-writes` (SEC-ADMIN-2..5) tenham um leito de regressão "falha-antes / passa-depois" sem rede nem banco real.

## Contexto (do bug sweep)
O cluster `idor-admin-writes` agrupa vulnerabilidades de IDOR e role-gate ausente que precisam de testes de regressão para serem fechadas com segurança — e hoje **não há harness de teste no backend** (`backend/` não possui diretório `tests/` nem `conftest.py`; única dependência de teste é implícita). As Stories que dependem deste harness corrigem:

- **#49 — IDOR de avatar** (`backend/main.py`, endpoint de upload/leitura de avatar): um STUDENT pode acessar/escrever o avatar de outro `user_id` (corrigido por SEC-ADMIN-2).
- **#16 — IDOR notificações + criação aberta** (`backend/main.py`, endpoints de notificação): read/count/mark/delete cross-user e criação sem gate de ADMIN (corrigido por SEC-ADMIN-3).
- **#62 — criação de notificação só ADMIN** (`backend/main.py`): endpoint de create aceita STUDENT (corrigido por SEC-ADMIN-3).
- **#14 — IDOR gamificação + integrity** (`backend/main.py`, gamificação/certificados): writes cross-user e `points`/`certificate` confiando no cliente (corrigido por SEC-ADMIN-4).
- **#25 — authz session-review** (`backend/main.py` / reviews): reply/create/update/get sem ownership e sem role-gate TEACHER/ADMIN (corrigido por SEC-ADMIN-5).

Impacto: sem harness, qualquer fix de IDOR é mergeado sem prova de regressão; o blast radius de SEC-ADMIN-2..5 toca `main.py` (endpoints públicos consumidos por `AccountSettings`, `Layout`, `AdminConsole`, `SessionReview` no frontend) e exige verificação dos três desfechos de IDOR de forma repetível.

Decisão de arquitetura (roadmap §2.0): o **`conftest.py` é criado uma única vez por SEC-ATO** (Fase 1, primeiro a tocar `backend/tests/`) e é o **dono da fixture `FakeSupabaseClient`**. Esta Story **consome** esse conftest, **não** o recria — apenas estende o harness com pytest discovery, app/TestClient, override de `get_supabase`/`get_current_user` e o seed de dados compartilhado.

## Acceptance Criteria
- [x] `pytest` executa a partir de `backend/` e descobre automaticamente os testes em `backend/tests/` (config de discovery: `pyproject.toml`/`pytest.ini` com `testpaths`/`python_files`, ou layout padrão que o pytest reconhece sem flags).
- [x] A suíte **importa** a fixture `FakeSupabaseClient` do `conftest.py` criado por SEC-ATO (não duplica a classe); se SEC-ATO ainda não tiver materializado o conftest, esta Story o cria como stub mínimo apenas na seção de fixture compartilhada — sem reivindicar ownership — e documenta o ponto de merge. _(O conftest de SEC-ATO já existia — esta Story o **estendeu** sem clobber; a classe `FakeSupabaseClient` foi materializada em `fakes.py` por SEC-AUTHZ-0/SEC-ADMIN-1 como Foundation e re-exportada pelo conftest.)_
- [x] O `FakeSupabaseClient` suporta o **chained builder** equivalente ao `supabase.Client` usado no código real: `client.table(name).select(...).eq(col, val).single().execute()` e as cadeias de escrita `.insert(...).execute()`, `.update(...).eq(...).execute()`, `.delete().eq(...).execute()`, retornando um objeto com atributo `.data` (lista ou registro) compatível com o consumo em `main.py`.
- [x] O fake é injetável via `app.dependency_overrides[get_supabase]` e o usuário autenticado via `app.dependency_overrides[get_current_user]`, permitindo simular STUDENT/TEACHER/ADMIN sem JWT real.
- [x] **Seed determinístico** carregado no fake antes de cada teste: **2 students + 1 teacher + 1 admin**, mais registros relacionados em `chat_sessions`, `notifications`, `reviews` e `course_progress` (com `user_id` apontando para os usuários semeados, permitindo testar dono vs. ator cruzado).
- [x] **Sem rede e sem DB real:** nenhum teste cria `create_client` real, abre socket, lê/escreve `test.db` ou requer `SUPABASE_URL`/`SUPABASE_KEY`; rodar com variáveis de ambiente vazias deve passar.
- [x] Helpers de IDOR reutilizáveis disponíveis para SEC-ADMIN-2..5 cobrindo os **3 desfechos** que cada IDOR fix deverá exercitar: (a) **dono autorizado passa** (200/201); (b) **ator cruzado recebe 403/404 e nenhuma leitura/mutação ocorre** (o fake registra que nenhuma escrita foi aplicada à linha alheia); (c) **`body.user_id` nunca é confiado** (helper que constrói payload com `user_id` adulterado e assert de que o ator efetivo deriva do usuário autenticado, não do body).
- [x] Existe ao menos **1 smoke test verde** provando o harness (ex.: `GET /health` ou equivalente via `TestClient`) e **1 teste-sentinela** demonstrando o padrão dono-vs-ator-cruzado sobre uma fixture semeada.

## Tasks / Subtasks
- [x] Criar `backend/tests/` com `__init__.py` (se necessário) e garantir discovery: adicionar `[tool.pytest.ini_options]` em `backend/pyproject.toml` (ou `backend/pytest.ini`) com `testpaths = ["tests"]`, `python_files = "test_*.py"`.
- [x] Adicionar `pytest`, `httpx` (necessário para `fastapi.testclient.TestClient`) e dependências de teste a `backend/requirements.txt` (ou `requirements-dev.txt`), fixando versões. _(Usado `requirements-dev.txt` separado — o `Dockerfile` instala `requirements.txt` em produção; `httpx==0.28.1` já estava pinado lá.)_
- [x] Em `backend/tests/conftest.py` (dono SEC-ATO — **coordenar merge**): garantir/estender a fixture `FakeSupabaseClient` com o builder encadeado espelhando `database.py:3-18` (`create_client`/`get_supabase`); se ausente, materializar stub mínimo e marcar `# OWNER: SEC-ATO`. _(Estendido sem clobber; fake em `fakes.py`, re-exportado pelo conftest.)_
- [x] Adicionar fixture `app` que importa o app FastAPI de `backend/main.py` e aplica `app.dependency_overrides[get_supabase]` para o fake.
- [x] Adicionar fixture `client` (`TestClient(app)`) e fixtures `as_student`/`as_teacher`/`as_admin` que sobrescrevem `get_current_user` (de `backend/auth.py`). _(Adicionado também `as_other_student` para o ator cruzado.)_
- [x] Adicionar fixture `seed` que popula o `FakeSupabaseClient` com 2 students/1 teacher/1 admin + `chat_sessions`/`notifications`/`reviews`/`course_progress`, com IDs estáveis exportados como constantes para reuso em SEC-ADMIN-2..5.
- [x] Adicionar helpers em `backend/tests/idor_helpers.py` (ou no conftest): `assert_owner_passes`, `assert_cross_actor_forbidden_no_mutation`, `assert_body_user_id_ignored`.
- [x] Escrever `backend/tests/test_harness_smoke.py`: smoke test do app + 1 teste-sentinela do padrão IDOR sobre `notifications` semeadas. _(Materializado em `backend/tests/security/test_harness_smoke.py`.)_
- [x] Rodar `cd backend && pytest -q` com env vazio e confirmar verde sem rede/DB.

## Dev Notes
- **Arquivos:**
  - Cria/estende: `backend/tests/conftest.py` (dono SEC-ATO — consumir, não reivindicar), `backend/tests/__init__.py`, `backend/tests/idor_helpers.py`, `backend/tests/test_harness_smoke.py`, `backend/pyproject.toml` (ou `backend/pytest.ini`), `backend/requirements.txt`.
  - Importa de (não modifica): `backend/main.py` (app FastAPI; endpoints de avatar/notificações/gamificação/reviews em `main.py`), `backend/database.py:3-18` (`create_client`, `get_supabase`), `backend/auth.py` (`get_current_user`, `require_role`).
- **Abordagem:** Harness puramente in-process. O `FakeSupabaseClient` é um duble de `supabase.Client` que armazena tabelas como dicts em memória e expõe um builder fluente que acumula filtros (`.eq`) e termina em `.execute()` retornando `SimpleNamespace(data=...)`, replicando o contrato consumido em `main.py`/`routes_admin.py`/`routes_ai.py`. Injeção via `app.dependency_overrides` evita tocar código de produção. O ator é simulado sobrescrevendo `get_current_user`, isolando authz do JWT. O seed compartilhado dá a SEC-ADMIN-2..5 os pares dono/estranho necessários para os 3 desfechos de IDOR. Nenhum `pytest` flag obrigatória — discovery via config.
- **Riscos de regressão:** Esta Story **não altera código de produção** — risco de regressão funcional é nulo. Riscos de coordenação: (1) **colisão de ownership do `conftest.py` com SEC-ATO** — `depends_on: [SEC-ATO-3]` força a ordem; se SEC-ATO ainda não criou a fixture, materializar stub mínimo e sinalizar merge, jamais duplicar `FakeSupabaseClient`. (2) Adicionar deps de teste a `requirements.txt` pode impactar build do `Dockerfile` se este instalar `requirements.txt` em produção — preferir `requirements-dev.txt` separado se o `Dockerfile` for sensível. (3) O fake builder precisa cobrir exatamente as cadeias usadas pelos consumidores reais (`.single()`, `.maybe_single()` se houver, `.order()`, `.limit()`); cadeias não suportadas devem falhar explícito (`NotImplementedError`) para não mascarar gaps.

## Definition of Done
- [x] Teste de regressão (falha-antes / passa-depois) verde — smoke + sentinela IDOR rodando via `pytest` sem rede/DB
- [x] Sem regressão na suíte de segurança — `pytest -q` verde com env vazio (Phase-1: 21/21). Nota: a única edição de produção é a reference usage de SEC-AUTHZ-0 (override de briefing), não desta Story — este harness é puramente in-process.
- [ ] QA Gate: PASS ou CONCERNS _(a preencher pelo @qa)_
- [x] `FakeSupabaseClient` (builder encadeado) importado do conftest, não duplicado; seed de 2 students/1 teacher/1 admin + chat_sessions/notifications/reviews/course_progress disponível como fixture
- [x] Helpers dos 3 desfechos de IDOR (dono passa / ator cruzado 403-404 sem mutação / `body.user_id` ignorado) prontos e consumíveis por SEC-ADMIN-2..5
- [x] Discovery do pytest documentada (config) e deps de teste fixadas em requirements

## Dev Agent Record

**Status:** Ready for Review · **Agent:** Dex (@dev) · **Label:** foundation

### Files changed
- **Novo** `backend/tests/fakes.py` — `FakeSupabaseClient`: duble in-memory de `supabase.Client`. Builder fluente (`table/select/eq/order/limit/single/maybe_single/insert/update/delete/execute`), `.execute()` retorna `SimpleNamespace(data=..., count=...)`. Cadeias não suportadas levantam `NotImplementedError` (não mascaram gaps). Mantém `client.mutations` (log de escritas) para provar "nenhuma mutação na linha alheia". Compartilhado com SEC-AUTHZ-0.
- **Editado** `backend/tests/conftest.py` — **estendido** (Phase-1 de SEC-ATO 100% preservado): re-export de `FakeSupabaseClient`; seed determinístico (`make_seed_tables`: 2 students + 1 teacher + 1 admin + `chat_sessions`/`chat_messages`/`notifications`/`reviews`/`course_progress`/`disciplines`/`discipline_teachers`/`discipline_students`) com IDs estáveis exportados como constantes; fixtures `fake_supabase`/`seed`, `app` (override de `get_supabase` via `dependency_overrides` **e** monkeypatch de `database.get_supabase` para o `/health` que chama direto), `client` (`TestClient`), `as_student`/`as_other_student`/`as_teacher`/`as_admin` (override de `get_current_user`). Também adiciona `TESTS_DIR` ao `sys.path` para imports top-level dos helpers irmãos.
- **Novo** `backend/tests/idor_helpers.py` — `assert_owner_passes`, `assert_cross_actor_forbidden_no_mutation` (inspeciona `fake.mutations` + filtros por `id`), `assert_body_user_id_ignored` (constrói payload com `user_id` forjado e exige que o ator efetivo derive do autenticado, ou 403/404).
- **Novo** `backend/tests/__init__.py`, `backend/tests/security/__init__.py` — pacote `tests/security/`.
- **Novo** `backend/tests/security/test_harness_smoke.py` — smoke (`/health` via fake), seed-queryable, write-chains-audited, sentinela dono-vs-ator-cruzado sobre `notifications`, e 3 testes da reference usage (owner passa / forged body.user_id barrado / ADMIN override).
- **Novo** `backend/pyproject.toml` — `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `python_files=test_*.py`, `addopts=-q`).
- **Novo** `backend/requirements-dev.txt` — `pytest==8.3.4` (+ `-r requirements.txt`); separado para não enviar pytest à imagem de produção.

### Summary
Leito de regressão in-process (sem rede/DB) para o cluster `idor-admin-writes`. SEC-ADMIN-2..5 consomem o seed, as fixtures de ator e os 3 helpers de desfecho sem reimplementar nada. `conftest.py` + `authz.py` + `fakes.py` + `idor_helpers.py` ficam estáveis para todos os consumidores. Nenhuma alteração em código de produção nesta Story (o fake é injetado por override/monkeypatch).

### Test results
- `cd backend && pytest` → **49 passed** (venv efêmero `--system-site-packages` + pytest/httpx, removido após o run; `SUPABASE_URL`/`SUPABASE_KEY`/`JWT_SECRET_KEY`/`ENVIRONMENT` desabilitadas para provar "env vazio").
- Breakdown: `tests/security/test_harness_smoke.py` 7 · `test_authz.py` 21 · `test_security_hotfix.py` (Phase-1, sem regressão) 21.
- Warnings observados (21) são deprecations do ambiente Python 3.14 / Sentry / pydantic-v1, não do código entregue.

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-04 (adversarial security review)

Cluster: **foundation/harness** (SEC-ADMIN-1 — IDOR test harness extension of conftest).

Harness reviewed: `FakeSupabaseClient` records every write to `.mutations` (enables "no-write-on-deny" proofs) and raises `NotImplementedError` on unsupported chains — a missing capability fails loudly rather than masking an IDOR. Deterministic seed (2 students/teacher/admin + related rows) and `as_*` actor overrides are the stable contract consumed by SEC-ADMIN-2..5 and the chat suite. The 21 warnings are Python-3.14/Sentry/pydantic-v1 deprecations, not from delivered code. No false-green vectors in the harness.

Tests: full suite **257 passed, 0 failed**.
