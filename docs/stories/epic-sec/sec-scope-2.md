---
id: SEC-SCOPE-2
epic: EPIC-SEC
phase: 2
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: low
depends_on: [SEC-SCOPE-1]
bug_refs: [17]
---
# SEC-SCOPE-2: Escopar gradebook read + grade override às disciplinas do professor

## Story
Como administrador da plataforma Harven.AI responsável pela integridade acadêmica, quero que a leitura do gradebook (GET) e a sobrescrita manual de notas (PUT) sejam restritas às disciplinas às quais o professor está efetivamente vinculado, para impedir que um professor leia notas ou altere notas de disciplinas que não são suas, preservando o isolamento entre professores.

## Contexto (do bug sweep)
Bug #17 — `backend/routes_admin.py:1739-1748` (`discipline_gradebook`, GET) e `backend/routes_admin.py:1881-1956` (`set_student_grade`, PUT).

Ambos os endpoints usam apenas `require_role("ADMIN", "TEACHER", "INSTRUCTOR")` e **nunca verificam que o professor está ligado a `{discipline_id}`**. Eles validam apenas que a disciplina existe (e, no PUT, que o aluno está matriculado), mas qualquer conta TEACHER/INSTRUCTOR pode passar um `discipline_id` arbitrário.

Isso contrasta com o padrão já estabelecido em `backend/main.py:635-665` (`list_disciplines`), que escopa via `disc_repo.get_teacher_discipline_ids(current_user["id"])` (`backend/repositories/discipline_repo.py:39`).

**Impacto:** Um professor malicioso/comprometido lê o gradebook completo (nomes, RAs, médias) de QUALQUER disciplina (GET) e sobrescreve QUALQUER nota em QUALQUER disciplina (PUT, escrevendo em `grade_overrides`) — quebra de isolamento entre professores e violação de integridade acadêmica. Disparado por qualquer conta TEACHER.

## Acceptance Criteria
- [x] **Owner autorizado passa:** TEACHER/INSTRUCTOR vinculado à `discipline_id` recebe **200** no GET e no PUT, comportamento idêntico ao atual.
- [x] **Ator cruzado é bloqueado:** TEACHER/INSTRUCTOR NÃO vinculado → **403** no GET e no PUT; nenhuma leitura retornada e **nenhuma mutação** em `grade_overrides` (verificado via mutation log).
- [x] **Identidade não é confiada do body:** vínculo verificado via `current_user["id"]` (em `assert_teacher_owns_discipline` → `get_teacher_discipline_ids`); `body` só fornece `course_id`/`grade`.
- [x] **ADMIN mantém acesso total:** ADMIN → **200** em GET e PUT para qualquer `discipline_id` (bypass de escopo).
- [x] **Ordem de checagem preserva semântica:** o 403 de não-vínculo precede leitura/escrita; para ator autorizado, disciplina/aluno inexistentes continuam 404.

## Tasks / Subtasks
- [x] `discipline_gradebook`: `_user`→`current_user: Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR"))`; `assert_teacher_owns_discipline(discipline_id, current_user, DisciplineRepository(client))` no topo (ADMIN bypass interno; computa `get_teacher_discipline_ids` para TEACHER/INSTRUCTOR).
- [x] Exposto o usuário autenticado (`current_user`) em ambos os handlers.
- [x] `DisciplineRepository(client)` instanciado em ambos os handlers, reutilizando `get_teacher_discipline_ids`.
- [x] `set_student_grade`: mesma verificação de vínculo **antes** de qualquer escrita em `grade_overrides` (gate no topo, antes de existência/matrícula/upsert) — 403 sem mutação.
- [x] ADMIN continua bypassando o escopo (bypass interno do helper).
- [x] Teste de regressão dos 3 desfechos para GET e PUT (`TestGradebookScope`).

## Dev Notes
- **Arquivos:**
  - `backend/routes_admin.py:1739-1748` (`discipline_gradebook`, GET)
  - `backend/routes_admin.py:1881-1956` (`set_student_grade`, PUT, com escrita em `grade_overrides` em `~1916-1949`)
  - `backend/repositories/discipline_repo.py:39` (`get_teacher_discipline_ids` — helper a reutilizar)
  - `backend/main.py:635-665` (`list_disciplines` — padrão de referência já validado)
- **Abordagem:** Espelhar o gate de escopo já provado em `list_disciplines`: para roles `TEACHER`/`INSTRUCTOR`, exigir `discipline_id ∈ get_teacher_discipline_ids(current_user.id)`; `ADMIN` ignora o escopo. A correção é cirúrgica (gate inserido no topo de cada handler), sem alterar a lógica de negócio existente (validação de disciplina/aluno, upsert). Requer expor o usuário autenticado no handler (hoje descartado como `_user`). Depende de SEC-SCOPE-1 ter estabelecido/consolidado o padrão de escopo por professor.
- **Riscos de regressão:** Blast radius restrito aos dois endpoints de gradebook em `routes_admin.py` (rotas `GET /disciplines/{id}/gradebook` e `PUT /disciplines/{id}/students/{sid}/grade`). Consumidores prováveis: telas de gradebook/lançamento de notas no frontend para perfis TEACHER. Risco principal: aplicar o escopo a ADMIN por engano (negaria acesso legítimo) ou bloquear professor legitimamente vinculado se `get_teacher_discipline_ids` não refletir o vínculo — validar com conta vinculada real. `grade_overrides` é tabela sensível; garantir que o 403 ocorre ANTES do upsert para evitar mutação parcial.

## Definition of Done
- [x] Teste de regressão verde: (a) TEACHER vinculado → 200 GET/PUT; (b) TEACHER não vinculado → 403 GET/PUT e `grade_overrides` inalterado; (c) ADMIN → 200 GET/PUT.
- [x] Sem regressão na suíte de segurança (105 testes verdes).
- [ ] QA Gate: PASS ou CONCERNS
- [x] PUT bloqueado por 403 não cria nem atualiza linha em `grade_overrides` (verificado via mutation log em `test_set_grade_teacher_unlinked_forbidden_no_mutation`); autorização nunca usa identidade do body.

## Dev Agent Record

**Agent:** Dex (@dev)
**Files changed:**
- `backend/routes_admin.py` — `discipline_gradebook` and `set_student_grade`: `_user` → `current_user` (kept the existing `require_role("ADMIN", "TEACHER", "INSTRUCTOR")` dependency) + `assert_teacher_owns_discipline(discipline_id, current_user, DisciplineRepository(client))` inserted at the top of each handler, before any read (GET) or write (PUT). For the PUT, the gate precedes the existence/enrollment checks and the upsert, so an unlinked teacher causes zero mutation.
- `backend/tests/security/test_idor_admin.py` — `TestGradebookScope` (6 tests).

**Note on mission scope:** SEC-SCOPE-2's two endpoints (`discipline_gradebook`, `set_student_grade`) live in `routes_admin.py`, not `main.py` — `main.py:list_disciplines` is only the reference pattern this story mirrors. No `main.py` edit was required. `discipline_repo.py` used read-only, not modified.

**Summary:** Gradebook read and grade override are now scoped to the teacher's own disciplines via the shared `assert_teacher_owns_discipline` helper; ADMIN bypasses. The scoping decision derives solely from `current_user["id"]`; `GradeOverride` body provides only `course_id`/`grade`.

**Test results:** `TestGradebookScope` 6/6 pass. Full backend suite: 105 passed, 0 failed.

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-04 (adversarial security review)

Cluster: **teacher-scoping** (SEC-SCOPE-2 — gradebook read + grade override).

`discipline_gradebook` (GET) and `set_student_grade` (PUT) keep `require_role("ADMIN","TEACHER","INSTRUCTOR")` and now call `assert_teacher_owns_discipline` at the top — before any read (GET) or write (PUT). **Cross-discipline teacher blocked**: an unlinked teacher writing a grade gets 403 with zero `grade_overrides` mutation (verified via mutation log); linked teacher→200 with the override persisted; ADMIN bypasses scoping. Identity from token only; body provides just `course_id`/`grade`. This closes the cross-discipline gradebook IDOR.

Tests: gradebook-scope suite green; full suite **257 passed, 0 failed**.
