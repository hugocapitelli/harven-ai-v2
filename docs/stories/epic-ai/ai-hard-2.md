---
id: AI-HARD-2
epic: EPIC-AI
phase: 4
status: Done
severity: HIGH
terminal: Backend & Infra
complexity: low
depends_on: [AI-HARD-0]
bug_refs: [32]
---
# AI-HARD-2: Remover fail-open do Tester: nunca fabricar APPROVED

## Story
Como mantenedor da plataforma Harven.AI responsável pela integridade do quality gate pedagógico, quero que o validador (`validate_response` / Tester) jamais fabrique um veredito `APPROVED` quando ocorre falha de parse ou de transporte, para que o gate de validação deixe de ser um carimbo silencioso e nunca aprove respostas degradadas — especialmente se for futuramente encadeado ao fluxo aluno-facing (AI-HARD-1 / item #5).

## Contexto (do bug sweep)
Bug item #32 (BUG-SWEEP-2026-06-03.md, linhas 420-427): o Tester (quality gate) em `validate_response` usa um bloco `except (json.JSONDecodeError, Exception)` que captura **todo** erro e retorna `{verdict: APPROVED, score: 0.80}` fabricado. O fail-open dispara em dois cenários:
- `json.JSONDecodeError` — saída do LLM malformada, mesmo sob `json_mode`.
- Qualquer exceção OpenAI/rede/runtime — apenas `AIServiceError` não-mock são re-lançadas; todo o resto vira `APPROVED`.

Impacto: o gate de validação vira carimbo — qualquer falha resulta em `APPROVED`. Nuance honesta do report: o veredito hoje não é consumido por nenhum pipeline aluno-facing (endpoint isolado), então o impacto **realizado** é uma resposta de endpoint enganosa e não logada. Porém o padrão fail-open é genuíno e perigoso: se o Tester for encadeado ao gating (ver AI-HARD-1 / item #5 — Editor/Tester nunca encadeados ao diálogo), uma resposta socrática degradada ou que vaze a resposta passaria sem filtro.

Correção indicada pelo report: distinguir falhas de parse/transporte de um veredito real; em falha retornar `NEEDS_REVISION`/`UNKNOWN` (nunca `APPROVED`) e logar.

## Acceptance Criteria
- [x] **JSON malformado → NEEDS_REVISION:** quando a saída do LLM falha no parse (`json.JSONDecodeError` / payload inválido mesmo sob `json_mode`), `validate_response` retorna veredito `NEEDS_REVISION` (nunca `APPROVED`), sem fabricar `score: 0.80`.
- [x] **Exceção de transporte → NEEDS_REVISION + degraded + ERROR log:** qualquer exceção de transporte/runtime (OpenAI, rede, timeout, exceção genérica) resulta em veredito `NEEDS_REVISION`, sinalizando estado degradado (`degraded: true`) e gerando um log de nível **ERROR** com a causa raiz.
- [x] **APPROVED só com payload bem-formado:** o veredito `APPROVED` só pode ser retornado quando o LLM produziu um payload bem-formado e parseável que efetivamente contém esse veredito — nunca como default de catch-all.
- [x] **MOCK_MODE com `mock:true`:** quando em `MOCK_MODE` (startup sem key / placeholder, conforme AI-HARD-0), o retorno do validador inclui `mock: true` para que o consumidor distinga um veredito real de um stub de mock; e o branch mock não dispara em falha de quota em runtime (essa permanece como erro propagado).
- [x] **`AIServiceError` preservado:** o comportamento de re-lançar `AIServiceError` não-mock permanece intacto (sem regressão na propagação de erros legítimos).
- [x] Nenhum caminho de execução do `validate_response` produz `APPROVED` a partir de um bloco `except`.

## Tasks / Subtasks
- [x] Localizar `validate_response` no backend (arquivo do serviço de IA / Tester — ver Dev Notes) e o bloco `except (json.JSONDecodeError, Exception)` que retorna `APPROVED`.
- [x] Separar o tratamento de exceções em camadas distintas:
  - [x] Re-lançar `AIServiceError` não-mock (manter comportamento atual).
  - [x] `except json.JSONDecodeError` → retornar `{verdict: "NEEDS_REVISION", degraded: true, reason: "malformed_json"}` + log ERROR.
  - [x] `except Exception` (transporte/runtime) → retornar `{verdict: "NEEDS_REVISION", degraded: true, reason: "transport_error"}` + log ERROR com a exceção.
- [x] Garantir que o caminho de sucesso só retorna `APPROVED` quando o payload parseado contém o veredito válido; validar o shape do payload antes de confiar no `verdict`.
- [x] Integrar com o flag/branch de `MOCK_MODE` introduzido em AI-HARD-0: incluir `mock: true` no retorno de mock e confirmar que falha de quota em runtime não cai no branch mock.
- [x] Adicionar logging estruturado de nível ERROR (não silenciar) em todos os caminhos de falha.
- [x] Escrever teste de regressão (ver Definition of Done).

## Dev Notes
- **Arquivos:** backend — módulo do serviço de IA contendo `validate_response` (Tester / quality gate). Localizar via `grep -rn "def validate_response" backend/` e `grep -rn "json.JSONDecodeError, Exception" backend/`. Endpoint relacionado: `/tester/validate`. Constante de veredito: `APPROVED` / `NEEDS_REVISION` / `REJECTED`. Dependência: o flag `MOCK_MODE` / detecção de mock no startup vem de AI-HARD-0.
- **Abordagem:** substituir o catch-all fail-open por tratamento de exceções estratificado. A regra de ouro: **falha nunca produz APPROVED**. Parse e transporte falham para `NEEDS_REVISION` + `degraded` + log ERROR; `AIServiceError` continua propagando; `APPROVED` exige payload bem-formado e parseável. Esta é uma mudança localizada de baixo risco (fail-closed), sem alterar a assinatura pública do endpoint além de adicionar campos `degraded`/`mock` ao retorno.
- **Riscos de regressão:** blast radius pequeno hoje — o veredito do Tester não é consumido por nenhum pipeline aluno-facing no estado atual (endpoint isolado), então mudar o default de falha não quebra fluxo de alunos. Consumidores atuais a verificar: o endpoint `/tester/validate` e o wrapper frontend `validateResponse` (atualmente não usado). Verificar que nenhum teste existente assume `APPROVED` como retorno em cenário de erro. Depende de AI-HARD-0 estar concluído (detecção de MOCK_MODE no startup) para o critério `mock:true`.

## Definition of Done
- [x] Teste de regressão (falha-antes / passa-depois) verde: cobre (a) `JSONDecodeError` → `NEEDS_REVISION`; (b) exceção de transporte → `NEEDS_REVISION` + `degraded` + log ERROR; (c) payload bem-formado válido → `APPROVED`; (d) `MOCK_MODE` → `mock:true`.
- [x] Sem regressão na suíte de segurança / suíte de IA existente (propagação de `AIServiceError` intacta).
- [ ] QA Gate: PASS ou CONCERNS
- [x] Nenhum bloco `except` no `validate_response` retorna `APPROVED`; logs ERROR confirmados em ambos os caminhos de falha.

## File List
- `backend/services/ai_service.py` — `validate_response` rewritten (fail-closed); success path routed through `_parse_model_json(raw, TesterVerdict)`; import of `TesterVerdict` added.
- `backend/tests/test_ai_service_methods.py` — 5 new AI-HARD-2 regression tests + `import logging`.
- `docs/stories/epic-ai/ai-hard-2.md` — status → Done, File List.

## Dev Agent Record

### Implementation notes
- Success path no longer trusts the LLM JSON verbatim. It is routed through `_parse_model_json(result["content"], TesterVerdict)` (the single bad-JSON/contract-violation → `None` decision point). `APPROVED` can only surface when the validated payload actually carries it. Malformed JSON **or** valid JSON lacking/violating `verdict` collapses to `None` → `NEEDS_REVISION` + `degraded: true` + ERROR log — never fail-open APPROVED. The richer LLM payload (`criteria`) is re-surfaced on success with the validated `verdict`/`score` as source of truth.
- Three failure paths now log at **ERROR** (was `warning`) with root cause: contract failure (NEEDS_REVISION + `reason: malformed_json`), non-mock `AIServiceError` (UNKNOWN + `reason: transport_error`), generic `Exception` (UNKNOWN + `reason: transport_error`). All carry `degraded: true`.
- MOCK_MODE canned APPROVED now tagged `mock: true` and gated on `self.mock_mode` — a runtime quota `AIServiceError` on a real client does **not** masquerade as a benign mock verdict; it falls through to the transport (UNKNOWN) path.
- `AIServiceError` non-mock continues to be treated as transport failure (UNKNOWN). No `except` block produces APPROVED. Regression test in `test_tutor_persistence.py` (flaky Tester → `verdict in (UNKNOWN, NEEDS_REVISION)`, `!= APPROVED`) preserved and green.

### Tests
- `tests/test_ai_service_methods.py` + `tests/test_tutor_persistence.py`: **54 passed** (5 new AI-HARD-2 tests: JSONDecodeError→NEEDS_REVISION; transport→UNKNOWN+degraded+ERROR log; well-formed→APPROVED; MOCK_MODE→mock:true; valid JSON w/o `verdict`→NEEDS_REVISION; plus an exhaustive no-except-APPROVED guard).
- Full suite: **381 passed**, 0 failures.

## QA Results
_(a preencher pelo @qa)_
