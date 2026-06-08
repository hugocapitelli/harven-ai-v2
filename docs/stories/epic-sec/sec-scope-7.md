---
id: SEC-SCOPE-7
epic: EPIC-SEC
phase: 2
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: low
depends_on: [SEC-SCOPE-1, SEC-SCOPE-2, SEC-SCOPE-3, SEC-SCOPE-4]
bug_refs: [12]
---
# SEC-SCOPE-7: Contract test de min-role + suíte de regressão negativa

## Story
Como engenheiro de segurança da plataforma Harven.AI, quero um contract test que mapeie cada endpoint sensível ao seu `min-role` esperado e uma suíte de regressão negativa, para que qualquer reversão dos gates SEC-SCOPE (ou um endpoint novo deixado sem gate) quebre o build no CI antes de chegar à produção.

## Contexto (do bug sweep)
O item #12 (`backend/routes_ai.py:145-292, 408-418`) expôs que os endpoints de AI authoring (`ai_creator_generate`, `ai_socrates_dialogue`, `ai_analyst_detect`, `ai_editor_edit`, `ai_tester_validate`, organizer) só exigiam `get_current_user`, sem `require_role` — inconsistente com `reprocess_content` (`routes_ai.py:653-654`), que já usava `require_role`. Crucialmente, `ai_editor_edit` (`:261-262`) e `ai_tester_validate` (`:278-279`) chamavam `edit_response`/`validate_response` sem `user_id` e sem `check_token_budget` (LLM real sem throttle), e `GET /api/ai/estimate-cost` (`:408-409`) não tinha dependência de auth alguma.

As stories SEC-SCOPE-1..4 corrigiram esses gates pontualmente (authoring TEACHER/ADMIN, estimate-cost autenticado, stats/sessions/gradebook escopados a professor, `/integrations/status` ADMIN). Porém duas fragilidades sistêmicas permanecem sem cobertura: (a) o **carve-out crítico** de `POST /api/ai/socrates/dialogue` (`routes_ai.py:219-220`), que DEVE permanecer acessível a `STUDENT` (é o tutor do aluno) e nunca pode ser elevado a TEACHER/ADMIN por engano; (b) nada impede que um futuro refactor reverta silenciosamente qualquer um dos gates ou suba um endpoint AI novo sem `require_role`. Esta story converte o conhecimento de "qual endpoint exige qual role" em um teste de contrato versionado e em uma suíte de regressão negativa que falha o build se o gate for revertido.

## Acceptance Criteria
- [x] Existe um mapa de contrato explícito (estrutura de dados em teste, ex. `EXPECTED_MIN_ROLE`) que associa cada endpoint sensível em escopo SEC-SCOPE ao seu `min-role`: authoring (`/api/ai/creator/generate`, `/api/ai/creator/suggest-chapters`, `/api/ai/analyst/detect`, `/api/ai/editor/edit`, `/api/ai/tester/validate`, `/api/ai/organizer/*`) → TEACHER; `/api/ai/estimate-cost` → autenticado (qualquer role); `/integrations/status` → ADMIN; stats/sessions/gradebook (SEC-SCOPE-1/2) → TEACHER escopado.
- [x] **Carve-out STUDENT guardado explicitamente:** teste positivo afirma que `POST /api/ai/socrates/dialogue` retorna 200 para `STUDENT` (tutor do aluno preservado) e teste negativo afirma que NÃO está atrás de `require_role(TEACHER/ADMIN)`; o teste falha se `socrates/dialogue` passar a rejeitar STUDENT.
- [x] Suíte de **regressão negativa:** para cada endpoint authoring + `estimate-cost` + `/integrations/status`, um `STUDENT` autenticado recebe 403 (e anônimo em `/integrations/status` recebe 401/403); nenhum efeito colateral (geração LLM, leitura de pricing/config, escrita) ocorre na chamada negada.
- [x] **Meta-test de drift:** o teste inspeciona as dependências reais de cada rota (via `app.routes`/`route.dependant`) e falha se um endpoint do mapa não tiver mais o gate esperado (gate revertido) OU se um endpoint AI authoring novo for adicionado sem aparecer no mapa (cobertura obrigatória).
- [x] A suíte roda no CI (mesmo runner do `SEC-ADMIN-6` meta-test e `SEC-SCOPE-5/6`) e **quebra o build** quando qualquer gate SEC-SCOPE for revertido; verde antes da reversão (regressão simulada falha o teste).

## Tasks / Subtasks
- [x] Criar `backend/tests/test_sec_scope_contract.py` consumindo o harness/conftest de `SEC-ADMIN-1` (pytest + TestClient + fake Supabase, seed de 2 students/1 teacher/1 admin).
- [x] Declarar o mapa de contrato `EXPECTED_MIN_ROLE` cobrindo os endpoints listados nos AC, com `socrates/dialogue` marcado como `STUDENT` (carve-out) e `estimate-cost` como `AUTHENTICATED`/autenticado.
- [x] Escrever testes positivos: TEACHER/ADMIN → 200/202 nos authoring; STUDENT → 200 em `/api/ai/socrates/dialogue`; usuário autenticado → 200 em `/api/ai/estimate-cost`; ADMIN → 200 em `/integrations/status`.
- [x] Escrever testes negativos: STUDENT → 403 em authoring + `estimate-cost` (pós SEC-SCOPE-3); anônimo/STUDENT → 401/403 em `/integrations/status` (pós SEC-SCOPE-4); assertar que nenhuma chamada a `AIService` / leitura de pricing ocorre (mock/spy).
- [x] Implementar o meta-test de drift: iterar `main.app.routes` (incluindo as rotas de `routes_ai.py`/`routes_admin.py`), extrair as `Depends(require_role(...))` de `route.dependant`, comparar com `EXPECTED_MIN_ROLE` e falhar em divergência ou em endpoint authoring não-mapeado.
- [x] Registrar a invocação da suíte no pipeline de CI junto às demais suítes de segurança (`SEC-ADMIN-6`, `SEC-SCOPE-5/6`).

## Dev Notes
- **Arquivos:** `backend/tests/test_sec_scope_contract.py` (novo); referência de produção `backend/routes_ai.py` (rotas `:133-418`, gate `:653-654`), `backend/routes_admin.py` (stats/sessions/gradebook); harness `backend/tests/conftest.py` (de SEC-ADMIN-1); helper `require_role` (de SEC-AUTHZ-0) e `assert_teacher_owns_discipline` (de SEC-SCOPE-1).
- **Abordagem:** Contract test data-driven + meta-test de introspecção de rotas. O mapa `EXPECTED_MIN_ROLE` é a fonte única de verdade do "min-role por endpoint"; testes positivos/negativos exercem o comportamento HTTP e o meta-test garante que a *implementação* não divergiu do mapa (anti-drift, análogo ao anti-pattern `_user` checado em SEC-ADMIN-6). O carve-out de `socrates/dialogue=STUDENT` é teste de primeira classe — protege o tutor do aluno contra elevação acidental.
- **Riscos de regressão:** Story de teste puro — não toca código de produção, blast radius de runtime = zero. Risco de manutenção: o meta-test passa a ser gate de CI, então qualquer endpoint AI authoring novo precisará ser adicionado a `EXPECTED_MIN_ROLE` (intencional). Depende de SEC-SCOPE-1..4 já terem mergeado os gates reais — se rodado antes, os testes negativos falham legitimamente (sinal correto). Reusa o fake Supabase de SEC-ADMIN-1; mudanças no shape do fake podem exigir ajuste de seed.

## Definition of Done
- [x] Teste de regressão (falha-antes / passa-depois) verde: simular reversão de um gate (ex. remover `require_role` de `ai_creator_generate`) faz o meta-test/negativo falhar; com os gates de SEC-SCOPE-1..4 aplicados, a suíte passa. (Provado por `TestDriftDetectorSelfProof` — synthetic app com gate revertido → `_require_role_sets` vazio = drift detectado.)
- [x] Sem regressão na suíte de segurança (SEC-ADMIN-6, SEC-SCOPE-5/6 continuam verdes). (Full suite 257 passed.)
- [ ] QA Gate: PASS ou CONCERNS. _(a preencher pelo @qa)_
- [x] Carve-out `POST /api/ai/socrates/dialogue` = STUDENT explicitamente afirmado (positivo) e protegido contra elevação (negativo), e o build quebra se qualquer gate SEC-SCOPE for revertido.

## Dev Agent Record

**Agent:** Dex (@dev) · **Date:** 2026-06-04 · **Label:** guards

### Files changed (all additive — ZERO production runtime code modified)
- **NEW** `backend/tests/test_sec_scope_contract.py` (27 tests) — `EXPECTED_MIN_ROLE` contract map (authoring→TEACHER, estimate-cost→TEACHER per live SEC-SCOPE-3 gate, integrations/status→ADMIN, socrates→STUDENT carve-out); `TestPositiveContract`, `TestNegativeRegression` (incl. AIService spy proving no side effect on denied calls), `TestRoleContractDrift` (extracts the `allowed` role-set from each `require_role` closure via `route.dependant` and compares to the map; flags reverted gates and unmapped authoring siblings), `TestDriftDetectorSelfProof` (fail-before/pass-after via synthetic app).
- **(shared)** CI workflow `.github/workflows/ci.yml` runs this suite alongside the SEC-ADMIN-6 guard (added under SEC-ADMIN-6; covers `tests/` wholesale).

### Key decisions
- **[AUTO-DECISION]** `estimate-cost` is mapped TEACHER (not generic AUTHENTICATED): the live SEC-SCOPE-3 gate is `require_role("ADMIN","TEACHER","INSTRUCTOR")` and the existing behavioural tests assert STUDENT→403 there. The `AUTHENTICATED` sentinel is retained in the map vocabulary for future broad-auth endpoints. Reason: the contract must reflect the actual shipped gate, not the AC's looser wording.
- **[AUTO-DECISION]** Drift detector reads `require_role`'s captured `allowed` set from the dependency closure (`co_freevars`/`__closure__`) — exact min-role verification, not just presence. Reason: catches a *widened* gate (e.g. STUDENT accidentally added) as well as a removed one.
- Socrates carve-out protected at TWO levels: a live positive/negative behavioural test AND `test_socrates_carveout_is_explicitly_student` asserting the contract map itself keeps it STUDENT.

### Test results (ephemeral venv, removed after)
- `test_sec_scope_contract.py`: **27 passed**
- Full backend suite `pytest tests/`: **257 passed**.

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-04 (adversarial security review)

Cluster: **guards** (SEC-SCOPE-7 — scope-contract drift detector).

The drift detector (`test_sec_scope_contract.py`) is the anti-regression invariant for the role-gates: it reads each route's `require_role` allowed-set from the dependency closure (`__closure__`/`co_freevars`) — so it catches a *widened* gate (e.g. STUDENT accidentally added) as well as a removed one. **Not a false-green**: it ships self-proof tests (`test_detects_correct_teacher_gate` / `test_detects_reverted_open_gate`) proving it flags a reverted open gate. The Socrates carve-out is protected at two levels (live behavioural test + contract-map assertion keeping it STUDENT-reachable). The `[AUTO-DECISION]` closure-introspection approach is sound.

Tests: scope-contract suite (27) green; full suite **257 passed, 0 failed**.
