---
id: SEC-SCOPE-4
epic: EPIC-SEC
phase: 2
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: low
depends_on: []
bug_refs: [44]
---
# SEC-SCOPE-4: Role-gate `GET /integrations/status`

## Story
Como administrador da plataforma, quero que o endpoint `GET /integrations/status` exija papel ADMIN, para que usuários anônimos e alunos não consigam descobrir o estado das integrações (JACAD/Moodle) nem disparar probes de conexão.

## Contexto (do bug sweep)
Item #44 — `backend/routes_ai.py:982-986`. O handler `integration_status` não declara nenhuma dependência de autenticação (apenas `Depends(get_integration_service)`) e chama `svc.get_status()`, que sonda JACAD/Moodle e retorna flags `connected`/`enabled`, `mode`, `sitename` e a versão do Moodle. Os endpoints irmãos no mesmo bloco `INTEGRATION ENDPOINTS` já protegem corretamente: `integration_test_connection` (`routes_ai.py:973-979`) usa `require_role("ADMIN", "TEACHER")` e `integration_logs` (`routes_ai.py:989-995`) usa `require_role("ADMIN")`.

**Impacto:** Usuários anônimos descobrem se as integrações estão ativas, o nome/versão do site Moodle (em modo live; em mock retorna valores hardcoded) e conseguem disparar probes de conexão a sistemas externos (mild SSRF-amplification / recon). Classificado como CRITICAL por ser superfície totalmente não autenticada que vaza config de integração.

## Acceptance Criteria
- [x] Requisição **anônima** (sem `Authorization`) a `GET /integrations/status` → **401/403** (nenhum status de integração retornado).
- [x] **STUDENT** autenticado → **403** (corpo não contém flags de integração, `sitename` nem versão do Moodle).
- [x] **ADMIN** autenticado → **200** com o payload de `svc.get_status()` inalterado.
- [x] A dependência adicionada usa exatamente o padrão dos endpoints irmãos: `Depends(require_role("ADMIN"))`, consistente com `integration_logs`.
- [x] Nenhuma alteração no formato de resposta do caso ADMIN (contrato `integrationsApi.getStatus` preservado — só adiciona dependência de auth, sem mudar o schema).

## Tasks / Subtasks
- [x] Em `backend/routes_ai.py`, adicionar `current_user: dict = Depends(require_role("ADMIN"))` ao handler `integration_status`, espelhando `integration_logs`.
- [x] Confirmado que `require_role` já está importado no módulo; nenhum novo import.
- [x] Teste de regressão (`tests/security/test_idor_chat.py::TestIntegrationStatusGate`) cobrindo: anônimo → 401/403, STUDENT → 403, TEACHER → 403, ADMIN → 200.
- [x] Validado via teste que o body do caso ADMIN mantém `jacad`/`moodle` (sem mudança de schema).

## Dev Notes
- **Arquivos:** `backend/routes_ai.py` (handler `integration_status`, linhas 982-986); referência de padrão: `backend/auth.py:53` (`require_role`) e endpoints irmãos `routes_ai.py:973-979` e `989-995`. Teste em `tests/` (harness de SEC-ADMIN-1).
- **Abordagem:** Mudança cirúrgica de uma linha — adicionar `Depends(require_role("ADMIN"))` ao handler, alinhando-o aos dois endpoints irmãos do bloco de integração. `require_role` retorna o usuário autenticado e levanta 401/403 antes de o handler executar `svc.get_status()`, então nenhuma probe é disparada por chamador não autorizado.
- **Riscos de regressão:** Blast radius mínimo. O único consumidor frontend do endpoint é o wrapper `integrationsApi.getStatus` em `frontend/src/services/api.ts:288`; não há view atualmente acoplada a esse wrapper, então nenhum fluxo de aluno depende do acesso anônimo. Atenção: garantir que qualquer painel admin que venha a usar `getStatus` envie o token ADMIN. Não tocar em `test-connection`/`logs` (já protegidos) para evitar churn.

## Definition of Done
- [x] Teste de regressão (falha-antes / passa-depois) verde — anônimo/STUDENT/TEACHER bloqueados, ADMIN 200.
- [x] Sem regressão na suíte de segurança (demais gates de integração e SEC-SCOPE inalterados).
- [ ] QA Gate: PASS ou CONCERNS.
- [x] Padrão idêntico ao endpoint irmão `integration_logs` confirmado (`require_role("ADMIN")`), sem mudança no schema de resposta para ADMIN.

## Dev Agent Record

**Agent:** Dex (@dev) · **Date:** 2026-06-04

### Files changed
- `backend/routes_ai.py` — `integration_status` gained `current_user: dict = Depends(require_role("ADMIN"))`, mirroring `integration_logs`.
- `backend/tests/security/test_idor_chat.py` — `TestIntegrationStatusGate` (4 tests).

### Summary
One-line dependency add. `require_role` resolves before `svc.get_status()`, so no JACAD/Moodle probe fires for an anonymous/STUDENT/TEACHER caller. ADMIN response schema unchanged (`jacad`/`moodle` keys preserved). No frontend api.ts change required — the wrapper already sends the auth header; the contract only narrows to ADMIN.

### Test results
`58 passed` in `test_idor_chat.py`; full suite `163 passed`. Anonymous/STUDENT/TEACHER → 401/403 with no `sitename` leak; ADMIN → 200 with `jacad`+`moodle`.

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-04 (adversarial security review)

Cluster: **teacher-scoping / role-gates** (SEC-SCOPE-4 — GET /integrations/status ADMIN-only).

`integration_status` gained `require_role("ADMIN")`, mirroring its sibling `integration_logs`. The gate resolves before `svc.get_status()`, so no JACAD/Moodle probe fires for anonymous/STUDENT/TEACHER (verified, and no `sitename` leak in the body). ADMIN→200 with `jacad`/`moodle` schema preserved. Previously fully unauthenticated — leak closed.

Tests: integration-status suite green; full suite **257 passed, 0 failed**.
