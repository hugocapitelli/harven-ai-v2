---
id: CFG-5
epic: EPIC-CLEANUP
phase: 5
status: Draft
severity: MEDIUM
terminal: Backend & Infra
complexity: low
depends_on: [CFG-2]
bug_refs: [62]
---
# CFG-5: Remover favicon_url inexistente + allowlist de colunas no save de settings

## Story
Como administrador da plataforma Harven.AI, quero que o endpoint de salvar configurações ignore chaves desconhecidas e não referencie colunas inexistentes, para que o save de settings nunca falhe com erro 400 do PostgREST e apenas colunas legítimas de `system_settings` sejam persistidas.

## Contexto (do bug sweep)
Item #62 do BUG-SWEEP-2026-06-03.md (`backend/routes_admin.py:57-62`): o conjunto `SETTINGS_URL_FIELDS` inclui `"favicon_url"` (linha 61), mas a tabela `system_settings` **não possui** essa coluna. Defeito latente: `save_admin_settings` (linha 194) monta o dict `cleaned` a partir do `payload` arbitrário e o passa diretamente para `client.table("system_settings").update(cleaned).eq("id", row_id).execute()` (linha 215) sem filtrar contra as colunas conhecidas. Qualquer chave desconhecida no payload — incluindo `favicon_url` — produz um **400 do PostgREST** ("column not found"). Hoje não é alcançável pelo frontend shipped (que não envia `favicon_url`), mas é explorável via chamada API direta por um admin e quebra silenciosamente o save. Correção recomendada pelo bug sweep: filtrar o payload contra colunas conhecidas (allowlist) **e/ou** adicionar a coluna — esta story adota a allowlist + remoção de `favicon_url`. Impacto: integridade/robustez do endpoint de settings; UX administrativa degradada quando payload contém campo extra.

## Acceptance Criteria
- [ ] `"favicon_url"` removido de `SETTINGS_URL_FIELDS` em `backend/routes_admin.py` (linhas 57-62).
- [ ] `save_admin_settings` (linha 194) filtra `cleaned` por uma **allowlist de colunas conhecidas** de `system_settings` **antes** do `client.table("system_settings").update(...)` (linha 215) — chaves desconhecidas são descartadas e nunca chegam ao UPDATE.
- [ ] Payload contendo apenas colunas legítimas (ex.: `logo_url`, `login_logo_url`, `login_bg_url`, e demais colunas reais) salva com sucesso e os valores são persistidos.
- [ ] Payload contendo chave inexistente (ex.: `favicon_url` ou `foo`) **não** dispara 400 do PostgREST — a chave é silenciosamente ignorada e o save retorna 200 com as colunas válidas persistidas.
- [ ] `SENSITIVE_FIELDS` permanece intacto: o masking de valores `****` e o `_mask_sensitive` da resposta continuam funcionando exatamente como antes (sem regressão na lógica das linhas 206-209).
- [ ] `SETTINGS_READONLY_FIELDS` (`id`, `created_at`, `updated_at`) continua sendo removido do `cleaned` (sem regressão nas linhas 211-213).
- [ ] A ordem das etapas de saneamento (filtro de URL vazia → remoção de sensíveis mascarados → remoção de read-only → allowlist) preserva o comportamento existente e não inverte nenhuma garantia atual.

## Tasks / Subtasks
- [ ] Em `backend/routes_admin.py`, remover a linha `"favicon_url",` do conjunto `SETTINGS_URL_FIELDS` (linhas 57-62).
- [ ] Definir uma allowlist explícita de colunas gravavéis de `system_settings` (constante de módulo, ex.: `SETTINGS_WRITABLE_COLUMNS`), derivada das colunas reais da tabela (validar contra a migration/schema de `system_settings`).
- [ ] Em `save_admin_settings` (linha 194), após as etapas existentes de saneamento e **antes** do `if cleaned:` / `update(cleaned)` (linha 215), aplicar a allowlist: `cleaned = {k: v for k, v in cleaned.items() if k in SETTINGS_WRITABLE_COLUMNS}`.
- [ ] Garantir que `SENSITIVE_FIELDS` e `SETTINGS_READONLY_FIELDS` continuam sendo processados (não duplicar nem remover sua lógica; a allowlist é etapa adicional, não substituta).
- [ ] Verificar que os endpoints de upload (`upload_logo`, `upload_login_logo` e similares) que fazem `update` direto de uma única coluna conhecida não são afetados (eles não passam por `save_admin_settings`).
- [ ] Adicionar teste de regressão (ver DoD) cobrindo: coluna legítima salva; chave desconhecida ignorada sem 400; sensível mascarado descartado.

## Dev Notes
- **Arquivos:** `backend/routes_admin.py` (def `SETTINGS_URL_FIELDS` linhas 57-62; def `SENSITIVE_FIELDS` linha 33; def `save_admin_settings` linha 194; UPDATE em linha 215). Schema/migration de `system_settings` (validar colunas reais para a allowlist).
- **Abordagem:** (1) remover `favicon_url` do `SETTINGS_URL_FIELDS`; (2) introduzir allowlist `SETTINGS_WRITABLE_COLUMNS` com as colunas reais da tabela; (3) aplicar o filtro de allowlist como última etapa de saneamento do `cleaned`, imediatamente antes do `update`. Isso transforma o defeito de "400 do PostgREST por coluna inexistente" em "ignorar silenciosamente chave desconhecida", que é o comportamento defensivo desejado. A allowlist deve ser a fonte de verdade das colunas gravavéis — preferível a uma denylist.
- **Riscos de regressão:** blast radius restrito ao endpoint `POST /admin/settings` (`save_admin_settings`). Quem consome: o painel admin (frontend de settings) e qualquer chamada API direta de admin. Risco de "esquecer" uma coluna legítima na allowlist → coluna deixaria de salvar; mitigado validando a allowlist contra o schema real de `system_settings`. `_get_or_create_settings`, `_mask_sensitive`, `_log` e os endpoints de upload não são tocados. Depende de **CFG-2** (concluída antes) — confirmar que mudanças de CFG-2 sobre o mesmo arquivo/endpoint estão integradas antes de iniciar.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: caso com chave `favicon_url`/`foo` no payload retorna 200 (sem 400 PostgREST) e não persiste a chave inexistente.
- [ ] Sem regressão na suíte de segurança (masking de `SENSITIVE_FIELDS` e remoção de `SETTINGS_READONLY_FIELDS` preservados).
- [ ] QA Gate: PASS ou CONCERNS.
- [ ] Allowlist `SETTINGS_WRITABLE_COLUMNS` validada contra o schema real de `system_settings` (nenhuma coluna legítima ausente, nenhuma coluna inexistente incluída).

## QA Results
_(a preencher pelo @qa)_
