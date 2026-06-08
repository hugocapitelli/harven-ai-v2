---
id: SEC-SCOPE-3
epic: EPIC-SEC
phase: 2
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: low
depends_on: []
bug_refs: [12]
---
# SEC-SCOPE-3: Role-gate AI authoring + estimate-cost; preservar tutor do aluno

## Story
Como administrador da plataforma Harven.AI, quero que os endpoints de autoria por IA (creator, analyst, editor, tester, organizer) e o `estimate-cost` exijam papel TEACHER/ADMIN, mantendo o tutor socrático (`/socrates/dialogue`) acessível a alunos, para impedir abuso de custo/exaustão de tokens e divulgação de configuração de pricing por contas de aluno — sem derrubar a experiência de tutoria de TODOS os alunos.

## Contexto (do bug sweep)
Item #12 — `backend/routes_ai.py:145-292, 408-418`.

Os endpoints de autoria por IA (`ai_creator_generate` em `routes_ai.py:145`, `ai_analyst_detect` em `:243`, `ai_editor_edit` em `:261`, `ai_tester_validate` em `:278`, organizer em `:295`/`:334`) exigem apenas `get_current_user` — qualquer aluno logado os acessa. Isso é inconsistente com o padrão já estabelecido em `reprocess_content` (`routes_ai.py:653-657`), que corretamente usa `require_role("ADMIN", "TEACHER", "INSTRUCTOR")`.

Crucialmente, `ai_editor_edit` e `ai_tester_validate` chamam `edit_response`/`validate_response` **sem `user_id` e sem `check_token_budget`** — são endpoints LLM realmente sem throttle, o vetor de exaustão de tokens. Adicionalmente, `GET /api/ai/estimate-cost` (`routes_ai.py:408-413`) **não declara nenhuma dependência de auth** (só recebe `prompt_tokens`, `completion_tokens`, `model` via Query), expondo a config de pricing/modelo a qualquer não-autenticado.

**Impacto:** abuso de custo/exaustão de tokens via editor/tester sem budget (qualquer aluno logado); `estimate-cost` divulga config de pricing/modelo sem auth.

**Carve-out crítico:** `ai_socrates_dialogue` (`routes_ai.py:219-222`) é o tutor socrático dos alunos e DEVE permanecer em `get_current_user` (STUDENT → 200). Gatear esse endpoint por engano derruba o tutor de TODOS os alunos — é o erro mais perigoso a evitar nesta story (ver roadmap, linha 433).

## Acceptance Criteria
- [x] STUDENT autenticado recebe **403** em todos os endpoints de autoria: creator/generate, creator/suggest-chapters, analyst/detect, editor/edit, tester/validate, organizer/session, organizer/prepare-export.
- [x] STUDENT autenticado recebe **403** em `GET /api/ai/estimate-cost` (passa a exigir auth + role).
- [x] STUDENT autenticado continua recebendo acesso (não 401/403) em `POST /api/ai/socrates/dialogue` (carve-out crítico — tutor preservado).
- [x] TEACHER e ADMIN recebem **200** nos endpoints de autoria e em `estimate-cost` (acesso legítimo mantido).
- [x] Requisição **não-autenticada** em `estimate-cost` passa de 200 (atual) para **401/403** (deixa de vazar config de pricing).
- [x] Nenhum efeito colateral é executado quando o ator não tem papel autorizado — `require_role` resolve ANTES do corpo do handler.
- [x] O conjunto de papéis usado é consistente com `reprocess_content` (`require_role("ADMIN", "TEACHER", "INSTRUCTOR")`).

## Tasks / Subtasks
- [x] Em `backend/routes_ai.py`, trocar `Depends(get_current_user)` por `Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR"))` nos handlers de autoria: `ai_creator_generate`, `ai_suggest_chapters`, `ai_analyst_detect`, `ai_editor_edit`, `ai_tester_validate`, `ai_organizer_session`, `ai_organizer_prepare_export`.
- [x] Em `ai_estimate_cost`, adicionar `current_user: dict = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR"))` (era sem auth).
- [x] **NÃO alterado** `ai_socrates_dialogue` — mantém `get_current_user`. Comentário inline `# carve-out: tutor do aluno — NÃO gatear (SEC-SCOPE-3)` adicionado.
- [x] Confirmado que `require_role` já está importado de `auth` — sem novo import.
- [x] Teste de regressão cobrindo STUDENT→403 nos gateados, STUDENT acessa socrates, e TEACHER→200.

## Dev Notes
- **Arquivos:** `backend/routes_ai.py` (handlers `ai_creator_generate`, `ai_suggest_chapters`, `ai_analyst_detect`, `ai_editor_edit`, `ai_tester_validate`, `ai_organizer_session`, `ai_organizer_prepare_export`, `ai_estimate_cost`); `backend/auth.py` (origem de `require_role`/`get_current_user`).
- **Abordagem:** Mudança cirúrgica de dependência FastAPI. O padrão canônico já existe na mesma rota: `reprocess_content` usa `Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR"))` (`routes_ai.py:656`). Reusar exatamente essa assinatura garante consistência de papéis e comportamento 403. `require_role` deve resolver ANTES do corpo do handler (é dependência do FastAPI), garantindo que nenhuma geração/edição/LLM ocorra para ator não autorizado. O carve-out do socrates é por omissão deliberada: ele permanece com `get_current_user`.
- **Riscos de regressão:** (1) **Risco máximo** — gatear acidentalmente `socrates/dialogue` derruba o tutor de 100% dos alunos; teste STUDENT→200 no socrates é blocking. (2) Frontend de autoria (creator/editor/tester) assume hoje acesso de qualquer usuário logado — telas usadas por TEACHER/ADMIN não devem quebrar (eles continuam 200); telas de aluno que indevidamente chamavam autoria passarão a receber 403 (comportamento desejado). (3) `estimate-cost` ganha auth — qualquer chamador anônimo/aluno que dependia dele passa a falhar; verificar se alguma tela pública o consome (não deveria). (4) Blast radius confinado a `routes_ai.py`; `require_role` e `get_current_user` não são modificados, apenas referenciados.

## Definition of Done
- [x] Teste de regressão (falha-antes / passa-depois) verde: STUDENT → 403 em {creator, suggest-chapters, analyst, editor, tester, organizer/session, organizer/prepare-export, estimate-cost}; TEACHER → 200 em estimate-cost.
- [x] Teste dedicado do carve-out: STUDENT NÃO recebe 401/403 em `POST /api/ai/socrates/dialogue` (blocking — tutor preservado).
- [x] Teste de `estimate-cost` sem token → 401/403 (deixa de responder 200 sem auth).
- [x] Sem regressão na suíte de segurança (demais stories de EPIC-SEC).
- [ ] QA Gate: PASS ou CONCERNS.
- [x] Comentário de proteção do carve-out presente no handler `ai_socrates_dialogue`.

## Dev Agent Record

**Agent:** Dex (@dev) · **Date:** 2026-06-04

### Files changed
- `backend/routes_ai.py` — `ai_creator_generate`, `ai_suggest_chapters`, `ai_analyst_detect`, `ai_editor_edit`, `ai_tester_validate`, `ai_organizer_session`, `ai_organizer_prepare_export` switched to `Depends(require_role("ADMIN","TEACHER","INSTRUCTOR"))`. `ai_estimate_cost` gained the same dependency (was fully unauthenticated). `ai_socrates_dialogue` left on `get_current_user` with the protective carve-out comment.
- `backend/tests/security/test_idor_chat.py` — `TestAuthoringRoleGate` (parametrized authoring matrix, organizer, estimate-cost anon/student/teacher, socrates carve-out).

### Summary
Surgical FastAPI dependency change matching the existing `reprocess_content` pattern. The token-exhaustion vector (editor/tester without budget) and the unauthenticated pricing leak (estimate-cost) are both closed at the dependency layer, so no LLM call or pricing read runs for an unauthorized actor. The Socratic tutor is the explicit carve-out — kept on `get_current_user` and asserted reachable by a STUDENT (blocking test).

### Test results
`58 passed` in `test_idor_chat.py`; full suite `163 passed`. STUDENT → 401/403 on every authoring path and estimate-cost; anonymous estimate-cost → 401/403; STUDENT socrates → not 401/403; TEACHER estimate-cost → 200.

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-04 (adversarial security review)

Cluster: **teacher-scoping / role-gates** (SEC-SCOPE-3 — AI authoring role-gated, STUDENT tutor preserved).

CRITICAL carve-out **confirmed working**: `POST /api/ai/socrates/dialogue` stays on `get_current_user` (any authenticated user) — a STUDENT reaches it (test asserts status NOT in 401/403). Gating it would break the Socratic tutor for every student; it is correctly NOT role-gated, and the carve-out is documented both in the handler and in `scope_registry.ALLOWLIST` with a reason. Authoring endpoints (creator/generate, suggest-chapters, analyst/detect, editor/edit, tester/validate, organizer/session, organizer/prepare-export) → `require_role("ADMIN","TEACHER","INSTRUCTOR")` (STUDENT→403). `estimate-cost` was fully unauthenticated → now role-gated (anonymous→401, STUDENT→403, TEACHER→200), closing a pricing/model-config leak. Token-exhaustion vector (editor/tester without budget) closed at the dependency layer — no LLM call runs for an unauthorized actor. A static drift meta-test (`test_sec_scope_contract`) with self-proof guards against regression.

Tests: authoring role-gate + scope-contract suites green; full suite **257 passed, 0 failed**.
