---
id: SEC-ADMIN-2
epic: EPIC-SEC
phase: 2
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: low
depends_on: [SEC-AUTHZ-0, SEC-ADMIN-1]
bug_refs: [49]
---
# SEC-ADMIN-2: IDOR de avatar (main.py)

## Story
Como aluno autenticado da plataforma Harven.AI, quero que o endpoint de upload de avatar só me permita alterar o meu próprio avatar (ou que apenas um ADMIN possa alterar o de terceiros), para que nenhum usuário consiga adulterar, desfigurar ou personificar a identidade visual de outra conta.

## Contexto (do bug sweep)
Defeito #49 (`backend/main.py:614-629`). O handler `POST /users/{user_id}/avatar` (`upload_avatar`) só exige `get_current_user` como dependência e, em seguida, executa `user_repo.update(user_id, {"avatar_url": url})` usando o `user_id` arbitrário recebido no path — **sem nunca comparar esse `user_id` ao chamador (`current_user["id"]`)**. Qualquer usuário autenticado pode, portanto, sobrescrever o `avatar_url` de qualquer outra conta.

Trecho vulnerável (`backend/main.py:614-629`):
```python
@app.post("/users/{user_id}/avatar", tags=["Users"])
async def upload_avatar(
    user_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),   # autentica, mas NÃO autoriza
    client: Client = Depends(get_supabase),
):
    ...
    url = await storage.save_file(file, subdir="avatars")
    user_repo = UserRepository(client)
    user = user_repo.update(user_id, {"avatar_url": url})  # user_id do path, sem checagem de dono
    if not user:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")
    return {"avatar_url": url}
```

**Impacto:** Adulteração cross-usuário do avatar (defacement / impersonação). Limitado ao campo `avatar_url`, mas explorável hoje, em produção, por qualquer aluno autenticado, já que a camada de autorização da aplicação é a única barreira (não há RLS no schema).

## Acceptance Criteria
- [x] **Dono autorizado passa:** STUDENT autenticado fazendo `POST /users/{seu_proprio_id}/avatar` recebe **200** e o `avatar_url` da própria conta é atualizado.
- [x] **Ator cruzado é barrado:** STUDENT autenticado fazendo `POST /users/{outro_user_id}/avatar` recebe **403** e **nenhuma escrita/mutação ocorre** — `storage.save_file` e `user_repo.update` do alvo NÃO são chamados e o `avatar_url` da vítima permanece inalterado.
- [x] **ADMIN é onipotente:** usuário com role `ADMIN` fazendo `POST /users/{qualquer_user_id}/avatar` recebe **200** e atualiza o avatar do alvo.
- [x] **Alvo inexistente → 404:** após passar pela autorização (próprio id ou ADMIN), `user_id` que não existe retorna **404** "Usuario nao encontrado", preservando o comportamento atual.
- [x] **O identificador de propriedade nunca vem do cliente além do path autorizado:** a decisão (`require_self_or_role`) compara `user_id` (path) com `current_user["id"]` (token), nunca confia em `user_id` vindo de body/query; o avatar é sempre gravado no `user_id` autorizado.
- [x] **AccountSettings self-upload intacto:** o fluxo `usersApi.uploadAvatar(user.id, file)` → `POST /users/${user.id}/avatar` cai no caminho self → 200 (contrato de resposta `{"avatar_url": url}` inalterado).
- [x] **Teste de regressão escrito** sob o harness do SEC-ADMIN-1 cobrindo os 3 desfechos (próprio → 200, cruzado → 403, ADMIN → 200) — falha antes do fix, passa depois.

## Tasks / Subtasks
- [x] Em `backend/main.py`, no handler `upload_avatar`, inserida guarda de autorização **antes** de `storage.save_file` e de `user_repo.update`, usando o helper central `require_self_or_role(user_id, current_user, "ADMIN")` (importado de `authz`). _(Optei pelo helper de authz em vez de checagem inline — SEC-AUTHZ-0 é a fonte única de ownership; o helper já implementa "self OR role" com 403, alinhado ao contrato do epic.)_
- [x] `storage.save_file` (efeito colateral) só executa **após** a guarda passar — ator não autorizado é barrado antes de qualquer I/O (asseverado por tripwire de `save_file` no teste cross-user).
- [x] Reaproveitado o helper central `require_self_or_role` (authz) em vez de duplicar lógica; `require_role` sozinho não cobre "dono OU admin", por isso o helper específico.
- [x] Verificado que a resposta de sucesso (`{"avatar_url": url}`) e o 404 "Usuario nao encontrado" permanecem idênticos ao contrato atual.
- [x] Escrito teste de regressão em `backend/tests/security/test_idor_avatar.py` (harness SEC-ADMIN-1): `test_upload_avatar_self_200`, `test_upload_avatar_cross_user_403_no_mutation`, `test_upload_avatar_admin_any_200`, `test_upload_avatar_admin_missing_target_404`.

## Dev Notes
- **Arquivos:**
  - `backend/main.py` (handler `upload_avatar`, linhas 614-629) — alvo da correção.
  - `backend/auth.py` (`get_current_user`, `require_role`) — helpers de autenticação/autorização já importados em `main.py:42`.
  - `backend/repositories` → `UserRepository.update` — invocado em `main.py:626`.
  - `backend/tests/` — harness pytest + TestClient + fake Supabase entregue por SEC-ADMIN-1 (depende de conftest de SEC-ATO).
  - Caller real (não tocar): `frontend/src/services/api.ts:200` (`uploadAvatar: (id, file) => upload(\`/users/${id}/avatar\`, file, 'file')`) e `frontend/src/views/profile/AccountSettings.tsx` (passa sempre `user.id` próprio).
- **Abordagem:** Defesa em nível de handler — comparar identidade do token com o recurso do path. A regra é "self OR admin". Como o `avatar_url` é derivado server-side do arquivo enviado (`storage.save_file`), não há `body.user_id` a confiar; o único vetor é o `user_id` do path, que passa a ser autorizado contra `current_user["id"]`. Alinhado ao padrão de SEC-AUTHZ-0 (helper central de authz) e ao formato de checagem de propriedade que as demais stories SEC-ADMIN reaplicam (`_user` anti-pattern → comparação explícita).
- **Riscos de regressão:** Blast radius mínimo. O único caller de produção é `AccountSettings` via `usersApi.uploadAvatar`, sempre com o id do próprio usuário logado → caminho self → 200 preservado. Painéis admin (`UserManagement.tsx`) apenas exibem `avatar_url`, não fazem upload de terceiros (se vierem a fazer, o branch ADMIN cobre). Atenção para não bloquear o caso ADMIN legítimo nem inverter a ordem (autorizar **antes** de qualquer efeito colateral de I/O de arquivo). Não alterar o contrato de resposta (`{"avatar_url": url}`) nem o 404.

## Definition of Done
- [x] Teste de regressão (falha-antes / passa-depois) verde para os 3 desfechos do IDOR de avatar.
- [x] Sem regressão na suíte de segurança (harness SEC-ADMIN-1 / SEC-ATO permanece verde; 178 passed).
- [ ] QA Gate: PASS ou CONCERNS _(a cargo do @qa)_.
- [x] Guarda implementada estritamente como "self OR ADMIN", efeitos colaterais (`storage.save_file`, `user_repo.update`) só executam após autorização, contrato de resposta e 404 inalterados.

## Dev Agent Record

**Agent:** Dex (@dev) · auth-infra · 2026-06-04

**Files changed:**
- `backend/main.py` — `import require_self_or_role` from `authz`; in `upload_avatar`, added `require_self_or_role(user_id, current_user, "ADMIN")` as the **first** statement, before the content-type check, `storage.save_file`, and `user_repo.update`. Response shape `{"avatar_url": url}` and the 404 are unchanged.
- `backend/tests/security/test_idor_avatar.py` (new) — 4 tests under the SEC-ADMIN-1 harness: self → 200, cross-user → 403 + no mutation + no `save_file` call, ADMIN → 200, ADMIN missing target → 404.
- `backend/tests/conftest.py` — (shared with SEC-ROT) seed additions; the avatar tests reuse the existing `client`/`as_student`/`as_admin`/`fake_supabase` fixtures.

**Summary:** Bug #49 closed. The handler now authorizes via the shared authz module (no inline ownership logic, no duplication into `auth.py`) before any side-effect, so a cross-user STUDENT gets 403 with zero file I/O and zero mutation of the victim row, while self and ADMIN get 200. Ownership derives only from `current_user["id"]` vs the path; no body field is trusted (the avatar URL is server-derived, so there is no `body.user_id` vector). IDS: REUSED `authz.require_self_or_role` and the SEC-ADMIN-1 IDOR helpers (`assert_owner_passes`, `assert_cross_actor_forbidden_no_mutation`); nothing redefined.

**Test results:** `pytest tests/` → **178 passed, 0 failed** (ephemeral venv, Python 3.14.3). 4 avatar IDOR tests pass; full suite green.

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-04 (adversarial security review)

Cluster: **admin-writes** (SEC-ADMIN-2 — avatar IDOR, `main.py`).

`upload_avatar` now calls `require_self_or_role(user_id, current_user, "ADMIN")` BEFORE `storage.save_file` and `user_repo.update`. Verified: owner self-upload → 200 + row updated; cross-user → 403 with `patched_storage["called"] is False` (gate precedes the side-effect — no orphan file, no victim mutation); ADMIN → 200 any user; authorized missing target → 404. The storage tripwire makes this a genuine adversarial test, not a false-green.

Tests: avatar IDOR suite (test_idor_avatar + happy-path) green; full suite **257 passed, 0 failed**.
