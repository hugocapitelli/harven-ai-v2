---
id: SEC-SCOPE-1
epic: EPIC-SEC
phase: 2
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: medium
depends_on: [SEC-AUTHZ-0]
bug_refs: [18]
---
# SEC-SCOPE-1: Helper teacher→disciplina + role gates em stats/sessions

## Story
Como administrador/professor da Harven.AI, quero que os endpoints de estatísticas e sessões de disciplina exijam papel ADMIN/TEACHER e, no caso de professores, restrinjam o acesso às disciplinas que o professor leciona, para que alunos não possam minerar notas, RAs, nomes e atividade de tutoria de colegas (e de qualquer disciplina).

## Contexto (do bug sweep)
Item #18 do bug sweep — **Endpoints de stats/sessões de disciplina sem role gate; alunos leem dados de colegas**.

Três endpoints em `backend/routes_admin.py` expõem dados sensíveis mas só dependem de `get_current_user` (qualquer autenticado), sem `require_role` nem checagem de propriedade/matrícula:

- `class_stats` — `backend/routes_admin.py:878-911` (`GET /classes/{class_id}/stats`): retorna contagens agregadas de uma disciplina (`student_count`, `course_count`, `session_count`).
- `discipline_students_stats` — `backend/routes_admin.py:914-970` (`GET /disciplines/{discipline_id}/students/stats`): expõe scores por aluno, nomes e RAs.
- `discipline_sessions` — `backend/routes_admin.py:1646-1726` (`GET /disciplines/{discipline_id}/sessions`): lista completa de sessões de tutoria da disciplina.

Atualmente cada um assina `_user: dict = Depends(get_current_user)` (linhas 881, 921, 1656). Qualquer aluno autenticado pode chamar os três e ler dados de colegas e de disciplinas que não cursa — escalação de privilégio horizontal e vertical somente-leitura. O bug sweep classifica a correção como gatear com `require_role(ADMIN, TEACHER)` e, para professores, restringir às disciplinas que possuem; nunca expor a STUDENT.

O helper canônico `assert_teacher_owns_discipline` é entregue por SEC-AUTHZ-0 em `backend/authz.py` (esta story **consome**, não recria).

## Acceptance Criteria
- [x] STUDENT autenticado recebe **403** nos três endpoints, sem dados no corpo (rejeitado por `require_role("ADMIN", "TEACHER")` antes de qualquer leitura).
- [x] TEACHER **vinculado** → **200**; TEACHER **não vinculado** → **403** sem exposição de outra disciplina.
- [x] ADMIN → **200** em qualquer disciplina (bypass em `assert_teacher_owns_discipline`).
- [x] **404 de disciplina inexistente** preservado para chamador autorizado (`class_stats` e `discipline_students_stats` checam existência antes do gate de ownership; ADMIN/TEACHER vinculado em disciplina inexistente → 404).
- [x] Escopo nunca derivado de campo do cliente — path param validado contra o vínculo real via `assert_teacher_owns_discipline` (deriva do `current_user["id"]`).
- [x] Gate aplicado **antes** da leitura sensível — em `discipline_sessions` o gate precede toda query; em `class_stats`/`discipline_students_stats` o role gate (Depends) precede tudo e o ownership precede as queries de PII/scores.

## Tasks / Subtasks
- [x] Importar `assert_teacher_owns_discipline` de `authz.py` e `DisciplineRepository` no topo de `routes_admin.py` (`require_role` já importado de `auth`).
- [x] `class_stats`: `_user`→`current_user: Depends(require_role("ADMIN", "TEACHER"))`; após o 404 de existência, `assert_teacher_owns_discipline(class_id, current_user, DisciplineRepository(client))` (ADMIN bypass interno).
- [x] `discipline_students_stats`: mesmo gate + `assert_teacher_owns_discipline` antes de buscar scores/RAs/nomes.
- [x] `discipline_sessions`: gate + `assert_teacher_owns_discipline` antes de montar a listagem (este handler não tem 404 de existência próprio; gate vem primeiro).
- [x] Ordem confirmada: role gate (403 STUDENT) → existência (404) → ownership (403 não vinculado) → leitura.
- [x] Testes de regressão: STUDENT→403, TEACHER não vinculado→403, TEACHER vinculado→200, ADMIN→200, disciplina inexistente→404 (`TestScopeStatsSessions`).
- **Nota de contrato:** a assinatura canônica em `authz.py` é `assert_teacher_owns_discipline(discipline_id, current_user, repo)` (repo = `DisciplineRepository`), não `(user, id, client)` como no rascunho — implementação seguiu o helper real entregue por SEC-AUTHZ-0.

## Dev Notes
- **Arquivos:**
  - `backend/routes_admin.py` (endpoints `class_stats` @878, `discipline_students_stats` @914, `discipline_sessions` @1646; import @22)
  - `backend/authz.py` (helper `assert_teacher_owns_discipline`, entregue por SEC-AUTHZ-0 — consumir, não recriar)
  - `backend/auth.py` (`require_role`, `get_current_user` — já existentes)
- **Abordagem:** Substituir `Depends(get_current_user)` por `Depends(require_role("ADMIN", "TEACHER"))` nos três handlers (capturando o dict de usuário). Para o papel TEACHER, validar vínculo com a disciplina do path via `assert_teacher_owns_discipline(user, discipline_id, client)`, que deve levantar 403 quando o professor não leciona a disciplina. ADMIN ignora o check de ownership. Preservar a verificação de existência (404) que já existe em `class_stats` e replicar o mesmo cuidado de ordem nos outros dois. Nenhuma decisão de escopo deve usar dado vindo do body/query — somente o path param de disciplina validado contra o vínculo real.
- **Riscos de regressão:** Blast radius restrito aos três handlers GET de dashboard/session-review em `routes_admin.py`. Consumidores frontend desses endpoints são telas administrativas/de professor (dashboards de turma, stats de alunos, SessionReview) — chamadas legítimas de ADMIN/TEACHER vinculado continuam 200; qualquer integração que chamasse esses endpoints como STUDENT passará a 403 (comportamento desejado). Depende de SEC-AUTHZ-0 estar concluída (helper + harness de teste com fake Supabase). Atenção para não inverter a ordem 404↔403 e quebrar o contrato de "disciplina inexistente → 404" para chamador autorizado.

## Definition of Done
- [x] Teste de regressão verde: STUDENT→403 nos três endpoints; TEACHER não vinculado→403; TEACHER vinculado→200; ADMIN→200; disciplina inexistente→404.
- [x] Sem regressão na suíte de segurança (105 testes verdes).
- [ ] QA Gate: PASS ou CONCERNS.
- [x] Nenhum dado de colega/disciplina é lido antes do gate (gate precede a leitura sensível); escopo nunca confia em campo do cliente.

## Dev Agent Record

**Agent:** Dex (@dev)
**Files changed:**
- `backend/routes_admin.py` — `class_stats`, `discipline_students_stats`, `discipline_sessions`: `Depends(get_current_user)` → `Depends(require_role("ADMIN", "TEACHER"))`; `assert_teacher_owns_discipline(discipline_id, current_user, DisciplineRepository(client))` added (after the existence check where one exists; first thing for `discipline_sessions`).
- `backend/tests/security/test_idor_admin.py` — `TestScopeStatsSessions` (13 tests).

**Summary:** STUDENT is rejected by the role gate before any read. TEACHER is scoped to owned disciplines via the shared `assert_teacher_owns_discipline` helper (consumed, not recreated); ADMIN bypasses scoping. 404 for a nonexistent discipline is preserved for authorized callers. `discipline_repo.py` was used (read-only via `get_teacher_discipline_ids`) but not modified.

**Test results:** `TestScopeStatsSessions` 13/13 pass. Full backend suite: 105 passed, 0 failed.

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-04 (adversarial security review)

Cluster: **teacher-scoping** (SEC-SCOPE-1 — class/discipline stats + sessions).

`class_stats`/`discipline_students_stats`/`discipline_sessions` now `require_role("ADMIN", "TEACHER")` (STUDENT→403 before any read) then `assert_teacher_owns_discipline(discipline_id, current_user, DisciplineRepository(client))` — verified: linked teacher→200, unlinked teacher→403 (cross-discipline blocked), ADMIN→200 any discipline, nonexistent→404 for authorized. Scoping derives from `current_user["id"]` via `discipline_teachers`, never a client field. No peer/discipline data is read before the gate.

Tests: scope-stats suite green; full suite **257 passed, 0 failed**.
