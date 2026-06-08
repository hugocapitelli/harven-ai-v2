---
id: SEC-SCOPE-6
epic: EPIC-SEC
phase: 2
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: low
depends_on: []
bug_refs: [20]
---
# SEC-SCOPE-6: LTI launch role + credential hardening

## Story
Como operador de segurança da plataforma Harven.ai, quero que o launch LTI nunca conceda papel ADMIN com base em roles enviadas pelo cliente e que contas auto-criadas via LTI não recebam senhas previsíveis, para impedir escalação de privilégio por spoofing de role e login direto com credencial adivinhável.

## Contexto (do bug sweep)
Item #20 do bug sweep (CRITICAL — Segurança), código em `backend/routes_ai.py:1138-1198` e `backend/services/integration_service.py:580-603`.

Dois defeitos concretos no fluxo `lti_launch`:

1. **Escalação a ADMIN via role do cliente.** `_map_lti_roles` (integration_service.py:595-603) consulta o `ROLE_MAP` (linhas 580-588) que inclui `"administrator": "ADMIN"`. O papel resolvido (`launch_data.role`) é gravado diretamente em `new_user["role"]` (routes_ai.py:1178). Um launch com `roles=administrator` auto-cria um usuário **ADMIN** — a única barreira é o segredo OAuth compartilhado (`LTI_SHARED_SECRET`). Se esse segredo vazar ou for fraco, qualquer ator forja um ADMIN.

2. **Senha previsível em contas auto-criadas.** routes_ai.py:1179 faz `password_hash = hash_password(launch_data.ra or launch_data.user_id)` — a senha é igual a um identificador conhecido e logável (o RA ou o user_id). Qualquer um que saiba o RA loga via `/auth/login` com o RA como senha.

3. **Default inseguro de auto-criação.** routes_ai.py:1171 lê `LTI_AUTO_CREATE_USERS` com **default `"true"`** — provisionamento automático ligado por omissão, ampliando a superfície dos dois pontos acima.

Manifesta-se apenas com `LTI_ENABLED=true` (default false — opt-in do operador). Impacto: escalação para ADMIN via spoofing de role LTI e contas com credencial previsível logáveis diretamente.

## Acceptance Criteria
- [x] Um launch LTI com `roles=administrator` **nunca** resulta em `role=ADMIN`: roles auto-provisionadas limitadas a `STUDENT`/`TEACHER`, fallback `STUDENT` (verificado em unit test de `_map_lti_roles`).
- [x] `instructor`/`contentdeveloper`/`teachingassistant` → `TEACHER`; `learner`/`student`/`member` → `STUDENT` — preservado.
- [x] Usuário **existente** ADMIN mantém papel — o branch `elif user:` (intocado) não rebaixa/promove; o teto aplica-se só à criação.
- [x] Conta auto-criada via LTI recebe `password_hash = hash_password(secrets.token_urlsafe(32))` — **nunca** `hash_password(ra/user_id)`; login com RA/user_id como senha falha (senha aleatória inutilizável).
- [x] `LTI_AUTO_CREATE_USERS` passa a ter **default `false`**; com auto-create off e usuário inexistente, o launch retorna 403, sem criar conta.
- [x] Nenhuma role do cliente concede privilégio elevado: `_map_lti_roles` é a fonte de verdade do teto (allowlist `LTI_PROVISIONABLE_ROLES = {STUDENT, TEACHER}`), ignorando `administrator`.

## Tasks / Subtasks
- [x] Em `backend/services/integration_service.py`: `"administrator": "ADMIN"` removido de `ROLE_MAP`; allowlist `LTI_PROVISIONABLE_ROLES = {"STUDENT","TEACHER"}` adicionada; `_map_lti_roles` só retorna roles allowlisted (qualquer outra → `STUDENT`).
- [x] Em `backend/routes_ai.py` (auto-create branch): `hash_password(launch_data.ra or launch_data.user_id)` → `hash_password(secrets.token_urlsafe(32))` (import `secrets`).
- [x] Em `backend/routes_ai.py` (auto-create branch): default de `os.getenv("LTI_AUTO_CREATE_USERS", "true")` → `"false"`.
- [x] Atualizado `.env.example` + `backend/.env.example` com `LTI_AUTO_CREATE_USERS=false` default e nota de que roles LTI não concedem ADMIN.
- [x] Teste de regressão: (a) `roles=administrator` → STUDENT, nunca ADMIN; (b) `ROLE_MAP` sem valor ADMIN; (c) default `LTI_AUTO_CREATE_USERS` ausente → "false"; (d) `instructor`→TEACHER, `learner`→STUDENT; LTI disabled → 403.

## Dev Notes
- **Arquivos:**
  - `backend/routes_ai.py` (handler `lti_launch`, linhas 1138-1198 — branch de auto-create em 1171-1183)
  - `backend/services/integration_service.py` (`ROLE_MAP` linhas 580-588, `_map_lti_roles` linhas 595-603)
  - `.env.example` / docs LTI (default de `LTI_AUTO_CREATE_USERS`)
  - `backend/tests/` (novo teste de regressão de LTI)
- **Abordagem:** Defesa em profundidade — (1) o servidor é a fonte de verdade do papel: `_map_lti_roles` deixa de poder retornar `ADMIN`, então mesmo um param `roles=administrator` forjado vira STUDENT/TEACHER; (2) credenciais LTI não são utilizáveis para login local (senha aleatória via `secrets.token_urlsafe`); (3) provisionamento automático passa a ser opt-in explícito (`LTI_AUTO_CREATE_USERS` default false). Mudanças cirúrgicas, sem alterar o caminho de validação OAuth nem o RedirectResponse final.
- **Riscos de regressão:**
  - Blast radius de `_map_lti_roles`/`ROLE_MAP`: usado pela resolução de papel no launch LTI. Confirmar que nenhum fluxo administrativo legítimo dependia de provisionar ADMIN por LTI — pela documentação não há; ADMIN deve ser concedido fora do LTI.
  - `launch_data.role` é gravado em `new_user["role"]` e propagado para `create_access_token(user["id"], user["role"])` (routes_ai.py:1197) e para o JWT — garantir que o teto de papel seja aplicado antes da emissão do token.
  - Mudar `LTI_AUTO_CREATE_USERS` default para false altera comportamento de deploys que dependiam do auto-create implícito; documentar no changelog/.env. Como LTI é opt-in (`LTI_ENABLED` default false), o impacto em produção atual é nulo.
  - Não tocar em contas já existentes (branch `elif user:` em 1184-1192) — o gate aplica-se só à criação.

## Definition of Done
- [x] Teste de regressão (falha-antes / passa-depois) verde: `roles=administrator` não gera ADMIN (capped a STUDENT); senha de conta LTI é aleatória (RA-como-senha inutilizável).
- [x] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [x] `instructor→TEACHER` e `learner→STUDENT` verificados em teste; `LTI_AUTO_CREATE_USERS` documentado com default false em `.env.example` + `backend/.env.example`.

## Dev Agent Record

**Agent:** Dex (@dev) · **Date:** 2026-06-04

### Files changed
- `backend/services/integration_service.py` — `ROLE_MAP` no longer contains `administrator`/ADMIN; added `LTI_PROVISIONABLE_ROLES = {"STUDENT","TEACHER"}`; `_map_lti_roles` returns only allowlisted roles (forged `administrator` → STUDENT).
- `backend/routes_ai.py` — `lti_launch` auto-create now hashes `secrets.token_urlsafe(32)` (random, unusable password) and reads `LTI_AUTO_CREATE_USERS` with default `"false"`. Existing-user branch untouched. `secrets` imported.
- `.env.example` + `backend/.env.example` — `LTI_*` documented (auto-create default false; roles never grant ADMIN; random LTI password).
- `backend/tests/security/test_idor_chat.py` — `TestLTIHardening` (7 tests).

### Summary
Defense in depth: the server is now the sole authority on the LTI role ceiling — a forged `roles=administrator` can never reach ADMIN (capped at STUDENT), proven by unit tests on `_map_lti_roles` and an assertion that `ROLE_MAP` has no ADMIN value. Auto-created accounts get a random, unusable password so the RA/user_id can't be used to log in. Auto-provisioning is now opt-in (default false). The existing-user branch is untouched, so a real ADMIN keeps their role.

### Test results
`58 passed` in `test_idor_chat.py`; full suite `163 passed`. `administrator`→STUDENT (incl. URN form and mixed roles, never ADMIN); `instructor`→TEACHER; `learner`→STUDENT; `ROLE_MAP` has no ADMIN value; LTI disabled → 403; default flag resolves to `false`.

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-04 (adversarial security review)

Cluster: **teacher-scoping / LTI hardening** (SEC-SCOPE-6 — LTI role ceiling + credential hardening).

Defense in depth verified: `_map_lti_roles` can never return ADMIN — a forged `roles=administrator` (incl. URN form and mixed roles) is capped at STUDENT via the `LTI_PROVISIONABLE_ROLES` safety net; `ROLE_MAP` contains no ADMIN value (asserted). Auto-created LTI accounts hash a random `secrets.token_urlsafe(32)` so the RA/user_id can't be used to log in via `/auth/login`. Auto-provisioning is now opt-in (`LTI_AUTO_CREATE_USERS` default `false`). The existing-user branch is untouched, so a real ADMIN keeps their role. LTI privilege-escalation and credential-derivation vectors closed.

Tests: LTI hardening suite (7) green; full suite **257 passed, 0 failed**.
