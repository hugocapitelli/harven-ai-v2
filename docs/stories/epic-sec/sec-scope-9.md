---
id: SEC-SCOPE-9
epic: EPIC-SEC
phase: 2
status: Done
severity: MEDIUM
---
# SEC-SCOPE-9: Fechar leitura cross-teacher residual em `routes_ai.py`

## Contexto

QA Gate adversarial de SEC-SCOPE-8 (2026-07-20, @qa) confirmou que o fix de `main.py`
está correto, mas achou resíduo: a mesma classe de vulnerabilidade (IDOR cross-teacher)
segue aberta em `backend/routes_ai.py`, onde um professor pode passar o `content_id` de
OUTRO professor no corpo da requisição e receber de volta conteúdo/texto gerado a partir
do material alheio. Severidade MÉDIA — é leitura via eco de geração de IA, não mutação
destrutiva como os endpoints já fechados em SEC-SCOPE-8.

Achado bruto: `.claude/agent-memory/aiox-qa/project_harven-ai-v2-sec-scope-8.md` (seção
"Ressalva SS8-1").

## Sítios afetados (routes_ai.py)

- `routes_ai.py:186` — `POST /api/ai/creator/generate`: `content_repo.get_by_id(req.content_id)`
  sem ownership check.
- `routes_ai.py:223` — `/suggest-chapters`: mesmo padrão.
- `routes_ai.py:576` — TTS: `get_by_id(body.content_id)` sem check.
- `routes_ai.py:1092` — sem check.
- `routes_ai.py:1225` — sem check.

## Critérios de Aceite

1. Cada um dos 5 sítios aplica `assert_teacher_owns_content` (ou o wrapper de leitura
   `enforce_teacher_scope_on_read`, ambos já criados em `backend/authz.py` por SEC-SCOPE-8)
   antes de usar o conteúdo carregado. Reaproveitar os helpers existentes — NÃO recriar
   lógica de ownership.
2. ADMIN mantém acesso irrestrito, mesma semântica de SEC-SCOPE-8.
3. Rotas de sessão/review/export-Moodle (zona ambígua) permanecem fora de escopo, sem
   alteração de comportamento.
4. `POST /socrates/dialogue` continua acessível a STUDENT (carve-out crítico já
   estabelecido em SEC-SCOPE-3) — este fix NÃO pode quebrar o fluxo do aluno.
5. Teste de regressão cobrindo os 5 sítios: professor B passando `content_id` do
   professor A deve receber 403/404, nunca o conteúdo/texto gerado.
6. Suíte completa permanece 100% verde (baseline 759 + 30 de SEC-SCOPE-8).

## Dev Notes

- Reusar helpers de `backend/authz.py` criados em SEC-SCOPE-8, não duplicar.
- Loop @dev ↔ @qa, máximo 3 iterações.

## Dev Agent Record

### Agente
Dex (@dev) — Full Stack Developer.

### Abordagem (IDS: REUSE)
Os 5 sítios em `routes_ai.py` passaram a chamar
`enforce_teacher_scope_on_read(assert_teacher_owns_content, content_id, current_user, client, DisciplineRepository(client))`
antes de carregar/usar o conteúdo. Zero lógica de ownership nova — reuso literal
dos helpers de SEC-SCOPE-8 e do mesmo idioma já provado em `main.py` (linhas
1142/1159/1282/1351). A escolha do wrapper `enforce_teacher_scope_on_read` (e não
do `assert_teacher_owns_content` cru) é deliberada e crítica: ele só aplica a
assertion ao ator TEACHER/INSTRUCTOR e é **no-op para ADMIN e STUDENT**. Isso:

- fecha o vazamento cross-teacher (professor B com `content_id` do professor A → 403/404);
- preserva o acesso irrestrito do ADMIN (AC2);
- **não quebra os endpoints student-reachable** (`tts/generate` e
  `audio/generate-from-content` são `get_current_user`): um STUDENT nunca é ator de
  professor, então o gate o ignora (AC4). O carve-out do tutor Socrático
  (`/socrates/dialogue`) não foi tocado — não carrega `content_id`.

### Colocação por sítio
| Sítio | Endpoint | Gate | Auth | Observação |
|:---|:---|:---|:---|:---|
| ~196 | `POST /api/ai/creator/generate` | antes do load | require_role (T/A/I) | geração de questões |
| ~239 | `POST /api/ai/creator/suggest-chapters` | antes do load | require_role (T/A/I) | sugestão de capítulos |
| ~600 | `POST /api/ai/tts/generate` | antes do load | get_current_user | STUDENT-reachable, gate no-op p/ aluno |
| ~1124 | `POST /api/ai/audio/generate-from-content` | antes do load | get_current_user | STUDENT-reachable, gate no-op p/ aluno |
| ~1266 | `POST /api/ai/reprocess-content` | antes do load E do `update` | require_role (T/A/I) | READ+WRITE: sobrescreve `content.body`, o mais perigoso |

### Pitfall encontrado e resolução (precedente SEC-SCOPE-8)
O gate novo no sítio `audio/generate-from-content` fez 7 testes de TTS
(`test_tts_lifecycle.py`, `test_tts_budget.py` — camada de rota) falharem com 403
"Permissao insuficiente para este conteudo". Causa: essas fixtures semeavam
`content-1`/`content-2` como linhas soltas (sem cadeia
`content -> chapter -> course -> discipline`) e agiam `as_teacher` (TEACHER_ID). Antes
do gate, passavam livres; agora a cadeia de ownership não resolvia. **Correção =
completar a fixture (semear a cadeia sob `DISCIPLINE_ID`, que o conftest já dá como
propriedade de TEACHER_ID), nunca afrouxar o gate.** Os testes de camada de worker
(`_run_tts_job` direto, sem passar pela rota) não foram afetados. `fake.find()`
retorna deepcopy, então o `chapter_id` foi semeado direto na linha do `contents`,
não patcheado depois.

### Comandos de verificação executados
- `python3 -m pytest tests/ -q` → **777 passed, 0 failed**.
- `python3 -m pytest tests/ -k "socrates or dialogue" -q` → 12 passed (carve-out AC4 intacto).
- `python3 -m pytest tests/security/test_idor_ai_content_leak.py -q` → 18 passed (novos).
- `grep -n "assert_teacher_owns_content\|enforce_teacher_scope_on_read" routes_ai.py` → 5 gates presentes.

### Critérios de Aceite — status
- AC1 ✅ 5 sítios aplicam `enforce_teacher_scope_on_read`/`assert_teacher_owns_content` (reuso, sem duplicação).
- AC2 ✅ ADMIN irrestrito (classe `TestAdminUnrestricted`, 5 casos).
- AC3 ✅ Rotas de sessão/review/export-Moodle intocadas.
- AC4 ✅ `/socrates/dialogue` aberto ao STUDENT; TTS/áudio student-reachable não bloqueados (classe `TestStudentCarveOutIntact`).
- AC5 ✅ Regressão dos 5 sítios: professor B → 403/404, sem vazamento e sem mutação (classe `TestCrossTeacherBlockedOnAllSites`, inclui prova de que `reprocess` não sobrescreveu o body da vítima).
- AC6 ✅ Suíte 100% verde (777 passed; +18 testes novos sobre a baseline).

## File List

| Arquivo | Ação |
|:---|:---|
| `backend/routes_ai.py` | Modificado — imports (authz + DisciplineRepository) + gate de ownership nos 5 sítios |
| `backend/tests/security/test_idor_ai_content_leak.py` | Criado — 18 testes de regressão SEC-SCOPE-9 |
| `backend/tests/test_tts_lifecycle.py` | Modificado — cadeia de ownership na fixture `tts_setup` (repara falso-positivo do gate) |
| `backend/tests/test_tts_budget.py` | Modificado — cadeia de ownership nos 2 testes de rota (repara falso-positivo do gate) |
| `docs/stories/epic-sec/sec-scope-9.md` | Modificado — status Done + Dev Agent Record + File List + Change Log |

## Change Log

| Data | Autor | Mudança |
|:---|:---|:---|
| 2026-07-20 | @dev (Dex) | Fechado IDOR cross-teacher residual nos 5 sítios de `routes_ai.py` reusando helpers de SEC-SCOPE-8; 18 testes de regressão; 2 fixtures de TTS estendidas com a cadeia de ownership; suíte 777/777 verde. Sem commit/push. |
