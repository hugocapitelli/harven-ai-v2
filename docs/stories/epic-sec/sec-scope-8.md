---
id: SEC-SCOPE-8
epic: EPIC-SEC
phase: 2
status: Done
severity: CRITICAL
---
# SEC-SCOPE-8: Fechar ownership de course/chapter/content em `main.py`

## Contexto

Auditoria de segurança (2026-07-20, @qa) encontrou vazamento cross-teacher sistêmico: a
remediação original de SEC-SCOPE-1..7 blindou apenas as rotas discipline-scoped em
`routes_admin.py` (`/disciplines/*`, `/classes/*`). O CRUD principal de curso/capítulo/
conteúdo vive em `backend/main.py` e ficou inteiramente descoberto — 18 endpoints sem
checagem de ownership entre professores.

Causa-raiz: `assert_teacher_owns_discipline` (`backend/authz.py:165`) só valida por
`discipline_id`. As rotas de `main.py` recebem `course_id`/`chapter_id`/`content_id`
diretamente e não existe helper que percorra `content → chapter → course → discipline`
para confirmar o dono.

Achado completo: `.claude/agent-memory/aiox-qa/project_harven-ai-v2-cross-teacher-leak.md`.

## Endpoints afetados (main.py, não exaustivo — @dev deve confirmar a lista completa)

- `PUT /courses/{id}` (main.py:1147) — edita curso alheio
- `DELETE /chapters/{id}` (main.py:1287) — apaga capítulo de outro professor
- `DELETE /contents/{id}` (main.py:1362) — apaga conteúdo de outro professor
- `PUT /contents/{id}/questions/batch` (main.py:1499) — reescreve perguntas socráticas alheias
- + 14 outros endpoints de course/chapter/content em main.py sem ownership check (mapear via
  `grep -n "def " backend/main.py | grep -i "course\|chapter\|content"`)

## Critérios de Aceite

1. Criar helper(s) em `backend/authz.py` que validem ownership subindo a cadeia
   `content → chapter → course → discipline_teachers` (ex.: `assert_teacher_owns_course`,
   `assert_teacher_owns_chapter`, `assert_teacher_owns_content`), reaproveitando o modelo
   M2M já existente em `repositories/discipline_repo.py:39`.
2. Todos os 18 endpoints de course/chapter/content em `main.py` acessíveis a
   TEACHER/INSTRUCTOR aplicam o helper correspondente antes de qualquer mutação ou leitura
   sensível. ADMIN mantém acesso irrestrito (override já existente no padrão do repo).
3. Tentativa de um professor B mexer em curso/capítulo/conteúdo do professor A retorna
   403/404 (nunca 200), com teste de regressão cobrindo pelo menos os 4 endpoints
   destrutivos listados acima.
4. Zona ambígua (cross-teacher em sessão/review/export Moodle, `routes_ai.py:1666,1777,1566`,
   `routes_admin.py:1875,1903`) fica FORA de escopo desta story — documentar como
   `KNOWN_UNREMEDIATED` se ainda não estiver, não alterar comportamento sem decisão explícita
   do dono do produto.
5. Suíte de testes existente permanece 100% verde; novos testes de regressão IDOR somam-se
   a `backend/tests/security/`.

## Dev Notes

- Seguir o padrão já estabelecido em SEC-SCOPE-1..7 (módulo único `authz.py`, sem duplicar
  helpers entre `auth.py`/`authz.py`).
- Não tocar nas rotas discipline-scoped já mitigadas em `routes_admin.py`.
- Loop @dev ↔ @qa, máximo 3 iterações (convenção da sessão, ver goals GRD-*).

## Dev Agent Record

### Agent
Dex (@dev) — implementação SEC-SCOPE-8.

### Approach (IDS: REUSE + CREATE + ADAPT)
- **REUSE:** `assert_teacher_owns_discipline` (`authz.py:165`) e o modelo M2M
  `discipline_teachers` (`repositories/discipline_repo.py`) — nenhuma lógica de
  ownership reimplementada. Padrão de loader `load_session_or_404` reaproveitado.
- **CREATE:** 4 helpers finos em `authz.py` que sobem a cadeia
  `content → chapter → course → discipline_id` e delegam a decisão final ao
  helper de disciplina já provado (`assert_teacher_owns_course` / `_chapter` /
  `_content` / `_question`), mais 1 wrapper condicional
  `enforce_teacher_scope_on_read` para os READs compartilhados (`get_current_user`).
- **ADAPT:** 22 call-sites em `main.py` (todos os endpoints de course/chapter/
  content/question acessíveis a TEACHER/INSTRUCTOR) passam a gatear antes de
  qualquer mutação/leitura sensível.

### Design decisions
- **ADMIN bypass** curto-circuita *antes* de qualquer load (autoridade global),
  espelhando `assert_teacher_owns_discipline`.
- **Fail-closed em curso órfão** (`discipline_id = NULL`, legado / `ON DELETE
  SET NULL`): negado para qualquer não-ADMIN — não há disciplina contra a qual
  escopar, então não se deixa um professor não-dono mexer num curso sem dono.
- **404 vs 403 hygiene:** row inexistente → 404 (não revela existência para outro
  professor), fora-de-escopo → 403 (mesma semântica das rotas SEC-SCOPE-1..7).
- **READs compartilhados** (`GET /courses/{id}`, `/export`, list-chapters,
  get-content, list-questions): o gate cross-teacher só se aplica quando o ator é
  TEACHER/INSTRUCTOR (o vazamento é um professor lendo o material de outro).
  STUDENT segue governado pelo enrollment scoping existente
  (`test_courses_student_scope`), ADMIN passa. Isso fecha AC2/AC3 sem quebrar AC5.
- **Escopo:** `POST /courses` (pin de disciplina) e `POST /classes/{id}/courses`
  também gateados na criação; `DELETE /courses/{id}` é ADMIN-only e ficou intacto.
  Rotas de sessão/review/export-moodle (zona ambígua) NÃO tocadas (AC4).

### Verification
- `python -m pytest tests/` → **759 passed, 0 failed** (baseline crescido de ~616
  para 759 no repo; zero regressão).
- `python -m pytest tests/security/test_idor_content_tree.py` → **30 passed**
  (cobre os 4 endpoints destrutivos + writes + reads + orphan fail-closed + 404
  hygiene + ADMIN bypass + owner-passes).
- `grep -c "assert_teacher_owns_course\|_chapter\|_content" main.py` → 20 (mais 3
  de `_question`), 22 call-sites gateados no total.

### File List
- `backend/authz.py` — MODIFIED (4 helpers de cadeia + 1 wrapper de read + loader).
- `backend/main.py` — MODIFIED (import + 22 call-sites de ownership nos endpoints
  de course/chapter/content/question).
- `backend/tests/security/test_idor_content_tree.py` — NEW (30 testes de regressão
  IDOR cross-teacher).
- `backend/tests/test_chapter_upload.py` — MODIFIED (fixture `_seed_chapter`
  estendida com a cadeia de ownership `course-1 → DISCIPLINE_ID`, exposta pelo novo
  gate; intenção do teste preservada, gate NÃO enfraquecido).

## Change Log

| Data | Versão | Descrição | Autor |
|:---|:---|:---|:---|
| 2026-07-20 | 1.0 | Fechado o IDOR cross-teacher sistêmico em `main.py`: helpers de ownership por cadeia em `authz.py`, aplicados aos 18+ endpoints de course/chapter/content/question; 30 testes de regressão; suíte 759/759 verde. | Dex (@dev) |
