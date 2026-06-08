---
id: EPIC-SEC
title: "Security: Account-Takeover Hotfix + Authorization Foundation"
status: Draft
phases: [1, 2]
story_count: 25
---
# EPIC-SEC: Security: Account-Takeover Hotfix + Authorization Foundation

## Objetivo

Neutralizar credenciais forjáveis/vazadas (Fase 1) e, em seguida, tornar **ownership** (`.eq("user_id", current_user["id"])` ou load-and-compare) + `require_role` o padrão **uniforme** em toda a superfície de autorização da aplicação (Fase 2).

A camada de autorização da aplicação é hoje a **única barreira** — não há RLS no schema, e o cliente Supabase roda como `service_role`. Ela está ausente em praticamente toda a superfície de chat-sessions, notificações e gamificação, e fail-open por design nos secrets. Qualquer aluno autenticado explora IDOR generalizado hoje, em produção.

A Fase 1 (Account-Takeover Hotfix) elimina os dois vetores de takeover trivial e maior blast-radius com edits minúsculos e risco estrutural near-zero: o token de reset que vaza no body/log (#4) e o `JWT_SECRET_KEY` com default público `change-me-in-production` sem guard de boot (#3, agravado por `.env.example` documentando nomes ERRADOS).

A Fase 2 (Authorization Foundation) fecha a superfície sistêmica de IDOR e role-gates em: chat-sessions (`routes_ai.py`), notificações + gamificação + reviews + avatar (`routes_admin.py` + `main.py`), gradebook/grade-override + discipline stats com teacher-scoping por disciplina, AI-authoring + estimate-cost + integrations/status (role-gated), webhook Moodle (HMAC) e LTI launch (hardening). Por fim, move o segredo JWT para o DB (`system_settings`) com rotação via force-logout que mata tokens antigos sem restart — corrigindo a precedência de env var que tornava o `force_logout` atual um no-op silencioso (#22).

## Critérios de Saída (Exit Criteria)

**Fase 1 — Account-Takeover Hotfix:**
- O token de reset **nunca** sai do servidor — `POST /auth/request-reset` retorna 200 sem chave `token` no body (existente e inexistente: mensagem idêntica, anti-enumeração); token nunca aparece em logs; `RESET_TOKEN_DEBUG` só em dev.
- Backend **recusa boot** em `ENVIRONMENT=production` com `JWT_SECRET_KEY` vazio/default/`<32` chars (`RuntimeError` fail-closed); segredo forte → boot normal; non-prod loga WARNING.
- Ambos os `.env.example` (raiz + `backend/`) usam os nomes reais (`SUPABASE_KEY`, `JWT_SECRET_KEY`), exatamente como em `config.py:12/15` e `database.py:6`; zero referência a `SUPABASE_ANON_KEY`/`SUPABASE_SERVICE_ROLE_KEY`/`JWT_SECRET`/`DATABASE_URL`.
- Token assinado com o default público **não valida** (forja → 401).

**Fase 2 — Authorization Foundation:**
- Todo endpoint que aceita `session_id`/`user_id`/`notification_id`/`discipline_id`/`job_id` filtra por `current_user["id"]` ou carrega a linha e compara ownership, com override TEACHER/ADMIN/INSTRUCTOR.
- `body.user_id` **nunca** é o ator — a identidade vem sempre do usuário autenticado (ou é derivada de `session.user_id`).
- AI-authoring + `estimate-cost` + `GET /integrations/status` são role-gated; **carve-out crítico:** `POST /socrates/dialogue` permanece acessível a STUDENT (200).
- Gradebook read + grade override + discipline stats/sessions de professor escopados às disciplinas próprias (não vinculado → 403); STUDENT nunca acessa.
- Tentativas cross-user retornam **403/404** (sem vazar PII de sessão estranha).
- `force_logout` rotaciona o segredo **no DB** (para de mutar `.env`) e invalida cache; tokens pré-rotação morrem (401) **sem restart**; pós-rotação validam.

## Stories

| ID | Título | Fase | Terminal | Compl. | Depende de | Severidade |
|:--|:--|:--:|:--|:--:|:--|:--:|
| SEC-ATO-1 | Reconciliar nomes de variáveis nos dois `.env.example` | 1 | Backend & Infra | low | — | CRITICAL |
| SEC-ATO-2 | Guard fail-closed para `JWT_SECRET_KEY` | 1 | Backend & Infra | low | SEC-ATO-1 | CRITICAL |
| SEC-ATO-3 | Parar de vazar o token de reset no body e nos logs | 1 | Backend & Infra | low | — | CRITICAL |
| SEC-AUTHZ-0 | Módulo `authz.py` + harness de teste IDOR | 2 | Backend & Infra | low | SEC-ATO-3 | CRITICAL |
| SEC-CHAT-1 | Ownership em endpoints de leitura de chat-session | 2 | Backend & Infra | med | SEC-AUTHZ-0 | CRITICAL |
| SEC-CHAT-2 | Ownership + remover spoof de `user_id` (create_or_get, add_session_message) | 2 | Backend & Infra | med | SEC-AUTHZ-0 | CRITICAL |
| SEC-CHAT-3 | `complete_chat_session` idempotente + ownership; create_or_get não reativa `completed` | 2 | Backend & Infra | low | SEC-AUTHZ-0, SEC-CHAT-2 | CRITICAL |
| SEC-CHAT-4 | Gate organizer/session + prepare-export; derivar ator da sessão | 2 | Backend & Infra | med | SEC-AUTHZ-0 | CRITICAL |
| SEC-CHAT-5 | ADR plano de migração RLS (doc only) | 2 | Backend & Infra | low | SEC-AUTHZ-0 | CRITICAL |
| SEC-ADMIN-1 | Bootstrap harness de teste backend (pytest + TestClient + fake Supabase) | 2 | Backend & Infra | med | — | CRITICAL |
| SEC-ADMIN-2 | IDOR de avatar (`main.py`) | 2 | Backend & Infra | low | SEC-AUTHZ-0, SEC-ADMIN-1 | CRITICAL |
| SEC-ADMIN-3 | IDOR notificações + criação só ADMIN | 2 | Backend & Infra | med | SEC-AUTHZ-0, SEC-ADMIN-1 | CRITICAL |
| SEC-ADMIN-4 | IDOR gamificação + integrity | 2 | Backend & Infra | med | SEC-AUTHZ-0, SEC-ADMIN-1 | CRITICAL |
| SEC-ADMIN-5 | Authz session-review | 2 | Backend & Infra | med | SEC-AUTHZ-0, SEC-ADMIN-1 | CRITICAL |
| SEC-ADMIN-6 | Guard de regressão IDOR + meta signature check | 2 | Backend & Infra | low | SEC-ADMIN-2, SEC-ADMIN-3, SEC-ADMIN-4, SEC-ADMIN-5 | CRITICAL |
| SEC-SCOPE-1 | Helper teacher→disciplina + role gates em stats/sessions | 2 | Backend & Infra | med | SEC-AUTHZ-0 | CRITICAL |
| SEC-SCOPE-2 | Escopar gradebook read + grade override às disciplinas do professor | 2 | Backend & Infra | low | SEC-SCOPE-1 | CRITICAL |
| SEC-SCOPE-3 | Role-gate AI authoring + estimate-cost; preservar tutor do aluno | 2 | Backend & Infra | low | — | CRITICAL |
| SEC-SCOPE-4 | Role-gate `GET /integrations/status` | 2 | Backend & Infra | low | — | CRITICAL |
| SEC-SCOPE-5 | HMAC shared-secret no webhook Moodle | 2 | Backend & Infra | med | — | CRITICAL |
| SEC-SCOPE-6 | LTI launch role + credential hardening | 2 | Backend & Infra | low | — | CRITICAL |
| SEC-SCOPE-7 | Contract test de min-role + suíte de regressão negativa | 2 | Backend & Infra | low | SEC-SCOPE-1, SEC-SCOPE-2, SEC-SCOPE-3, SEC-SCOPE-4 | CRITICAL |
| SEC-ROT-1 | Colunas DB do segredo JWT em `system_settings` + provider com cache TTL | 2 | Backend & Infra | med | SEC-ATO-2 | CRITICAL |
| SEC-ROT-2 | Sign/verify a partir do provider DB + seed no startup | 2 | Backend & Infra | low | SEC-ROT-1 | CRITICAL |
| SEC-ROT-3 | `force_logout` rotaciona o segredo no DB (para de mutar `.env`) + invalida cache | 2 | Backend & Infra | low | SEC-ROT-2 | CRITICAL |

## Sequência / Caminho Crítico interno

**Fase 1 (paralelizável em 2 trilhas, ambas Backend & Infra):**
- Trilha A (config/secret): `SEC-ATO-1` → `SEC-ATO-2`.
- Trilha B (reset-token): `SEC-ATO-3` (independente).
- `SEC-ATO` é o **primeiro a tocar `backend/tests/`** — cria `conftest.py` e é dono da fixture `FakeSupabaseClient`. Todas as Stories de teste posteriores importam daqui. (`backend/tests/` não existe ainda no repo.)

**Fundação da Fase 2:**
- `SEC-AUTHZ-0` (depende de `SEC-ATO-3`) é o **gate da Fase 2** — cria `backend/authz.py`, o lar canônico de todos os helpers de ownership/role. Quase tudo da Fase 2 depende dele.
- `SEC-ADMIN-1` (sem deps de código; consome o `conftest` de SEC-ATO) bootstrapa o harness de teste backend; pré-requisito dos SEC-ADMIN-2..5.

**Caminho crítico longo (mais profundo do epic):**
`SEC-ATO-1` → `SEC-ATO-2` → `SEC-ROT-1` → `SEC-ROT-2` → `SEC-ROT-3` (rotação DB-backed depende do guard fail-closed e do provider).

**Trilhas paralelas após `SEC-AUTHZ-0`:**
- Chat: `SEC-CHAT-1`, `SEC-CHAT-4`, `SEC-CHAT-5` em paralelo; `SEC-CHAT-2` → `SEC-CHAT-3` em série.
- Admin writes: `SEC-ADMIN-2..5` (após `SEC-AUTHZ-0` + `SEC-ADMIN-1`) → convergem em `SEC-ADMIN-6` (guard de regressão).
- Teacher scoping: `SEC-SCOPE-1` → `SEC-SCOPE-2`; `SEC-SCOPE-3/4/5/6` independentes → convergem (com 1/2/3/4) em `SEC-SCOPE-7`.

**Pontos de convergência (gates de fechamento):** `SEC-ADMIN-6` (meta-test IDOR) e `SEC-SCOPE-7` (contract test min-role no CI) são os guards que provam que nenhum gate foi revertido.

## Notas de Arquitetura

**Módulo único de authz (`backend/authz.py`) — decisão reconciliada (resolve 3 conflitos do review).**
`authz.py` é o **lar canônico** de TODOS os helpers de ownership/role: `load_session_or_404`, `assert_owner_or_role`, `assert_self_or_role`, `require_self_or_role`, `assert_notification_owner`, `assert_teacher_owns_discipline`. Os clusters `idor-admin-writes` e `teacher-scoping` **consomem** daqui — não recriam helpers em `auth.py`. `auth.py` (já existente) mantém apenas `get_current_user`/`require_role`. Helpers sem acoplamento a `Depends` (testáveis em isolamento). O módulo `authz.py` ainda não existe no repo — `SEC-AUTHZ-0` o cria.

**Ownership = filtro server-side, não confiança no cliente.**
Padrão uniforme: ou `.eq("user_id", current_user["id"])` na query, ou load-and-compare (`load_session_or_404` → 404 em row nula → `assert_owner_or_role`). Override TEACHER/ADMIN/INSTRUCTOR via `require_role`. STUDENT estranho → 403. `body.user_id` é **sempre** ignorado; o ator vem do JWT (ou é derivado de `session.user_id` em prepare-export). Carve-out de produto: `POST /socrates/dialogue` deve permanecer STUDENT-acessível (é o tutor do aluno) — `SEC-SCOPE-7` guarda isso explicitamente.

**Sem RLS hoje — a aplicação é a única barreira.**
O cliente Supabase é `service_role`, então qualquer policy RLS atual é no-op. `SEC-CHAT-5` produz o ADR (doc only) com o caminho de longo prazo (cliente Supabase por-request com JWT do usuário) e marca os helpers de `authz.py` como hotfix de aplicação shipped.

**Conflitos de arquivo coordenados (cross-epic, do review):**
- `create_or_get_chat_session` (`routes_ai.py:776-810`) é co-editado por `SEC-CHAT-2/3`, **TPP-2** (EPIC-AI Fase 3) e **DATA-GAM-4** (Fase 4). **Dono único = TPP-2** (rewrite com upsert/ON CONFLICT); SEC-CHAT e GAM **adicionam** sobre o resultado, não reescrevem. Como TPP é Fase 3, os hooks de ownership de SEC-CHAT-2/3 entram primeiro e TPP-2 rebaseia preservando-os.
- `complete_chat_session` (`routes_ai.py:914-931`) é co-editado por `SEC-CHAT-3`, **DATA-GAM-3/4**, **INT-MOODLE-4** e dirigido por TPP. Hooks aditivos sobre a versão TPP.
- `_handle_rating_submitted` co-editado por `SEC-SCOPE-5` (HMAC) e **INT-MOODLE-3** (validação): **HMAC primeiro, validação por cima**.
- `audio_job_status` ownership (#60) está **fora** do escopo deste epic — é de propriedade exclusiva de `tts-job-store-lifecycle` (Fase 4), que detém o shape final de storage do job.

**Conflito interno SEC-ATO-3 ↔ CFG-3 (Fase 5):**
`SEC-ATO-3` edita o bloco de reset-token em `main.py:404-477` (dict in-memory). `CFG-3` (Fase 5) substitui o dict pela tabela `password_resets` (token hasheado sha256, single-use via flag `used`, rate-limit por conta — migração `20260519` já existe). `CFG-3` **rebaseia sobre SEC-ATO-3 e não pode reintroduzir o leak** (#4).

**Conftest/test harness — dono único.**
`backend/tests/conftest.py` é criado **uma vez** por `SEC-ATO` (Fase 1, primeiro a tocar `backend/tests/`) e é o dono da fixture `FakeSupabaseClient` (chained builder, sem rede/DB real). `SEC-ADMIN-1` estende o harness (pytest + TestClient + seed de 2 students/1 teacher/1 admin + chat_sessions/notifications/reviews/course_progress) importando o conftest. `SEC-ADMIN-6` é um meta-test que falha o CI se algum handler in-scope mantiver `get_current_user` sem comparação de ownership (anti-pattern `_user`). `SEC-SCOPE-7` é o contract test de min-role.

**JWT secret DB-backed + rotação (`force-logout-secret-rotation`).**
Causa raiz do force-logout quebrado (#22): pydantic-settings ranqueia env vars ACIMA do arquivo `.env`, então reescrever `/app/.env` em runtime é ignorado por `get_settings()`. Correção: `system_settings.jwt_secret` + `jwt_secret_rotated_at` (nullable, **sem plaintext extra no schema além desta coluna**); `get_active_jwt_secret()` lê DB, semeia do bootstrap env (`settings.JWT_SECRET_KEY`) se NULL, com cache TTL (default 30s) e **fail-closed** para `settings.JWT_SECRET_KEY` em erro de DB (nunca cai em default fraco). `create_access_token` e `get_current_user` passam a usar o provider (~96 call sites preservados — assinaturas de função intactas; `lifespan` semeia a linha no startup). `force_logout` grava `token_urlsafe(48)` + `rotated_at`, invalida o cache, **não toca o filesystem**; tokens pré-rotação morrem (401) sem restart, mantendo `require_role('ADMIN')`, audit log e o contrato frontend `forceLogoutAll()` inalterados. DoD da fase exige staging single-worker confirmando `/app/.env` byte-idêntico antes/depois do force-logout.

**Hotspots de código (grounding):**
- `backend/config.py:15` → `JWT_SECRET_KEY = "change-me-in-production"` (confirmado, sem guard).
- `backend/config.py:12` → `SUPABASE_KEY` (nome real lido pelo código).
- `.env.example` (raiz, 710 bytes) + `backend/.env.example` (256 bytes) → ambos com nomes errados a reconciliar.
- `backend/auth.py` (existente) → mantém `get_current_user`/`require_role`; `backend/authz.py` a criar.
- `backend/tests/` → não existe; criado por SEC-ATO.
- `routes_ai.py` (chat-sessions IDOR), `routes_admin.py` + `main.py` (admin writes/avatar/notif/gamificação/reviews/gradebook/stats), `integration_service.py` (integrations/status + webhook/LTI).
