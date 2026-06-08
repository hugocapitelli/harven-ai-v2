---
id: AI-HARD-2
epic: EPIC-AI
phase: 4
status: Draft
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
- [ ] **JSON malformado → NEEDS_REVISION:** quando a saída do LLM falha no parse (`json.JSONDecodeError` / payload inválido mesmo sob `json_mode`), `validate_response` retorna veredito `NEEDS_REVISION` (nunca `APPROVED`), sem fabricar `score: 0.80`.
- [ ] **Exceção de transporte → NEEDS_REVISION + degraded + ERROR log:** qualquer exceção de transporte/runtime (OpenAI, rede, timeout, exceção genérica) resulta em veredito `NEEDS_REVISION`, sinalizando estado degradado (`degraded: true`) e gerando um log de nível **ERROR** com a causa raiz.
- [ ] **APPROVED só com payload bem-formado:** o veredito `APPROVED` só pode ser retornado quando o LLM produziu um payload bem-formado e parseável que efetivamente contém esse veredito — nunca como default de catch-all.
- [ ] **MOCK_MODE com `mock:true`:** quando em `MOCK_MODE` (startup sem key / placeholder, conforme AI-HARD-0), o retorno do validador inclui `mock: true` para que o consumidor distinga um veredito real de um stub de mock; e o branch mock não dispara em falha de quota em runtime (essa permanece como erro propagado).
- [ ] **`AIServiceError` preservado:** o comportamento de re-lançar `AIServiceError` não-mock permanece intacto (sem regressão na propagação de erros legítimos).
- [ ] Nenhum caminho de execução do `validate_response` produz `APPROVED` a partir de um bloco `except`.

## Tasks / Subtasks
- [ ] Localizar `validate_response` no backend (arquivo do serviço de IA / Tester — ver Dev Notes) e o bloco `except (json.JSONDecodeError, Exception)` que retorna `APPROVED`.
- [ ] Separar o tratamento de exceções em camadas distintas:
  - [ ] Re-lançar `AIServiceError` não-mock (manter comportamento atual).
  - [ ] `except json.JSONDecodeError` → retornar `{verdict: "NEEDS_REVISION", degraded: true, reason: "malformed_json"}` + log ERROR.
  - [ ] `except Exception` (transporte/runtime) → retornar `{verdict: "NEEDS_REVISION", degraded: true, reason: "transport_error"}` + log ERROR com a exceção.
- [ ] Garantir que o caminho de sucesso só retorna `APPROVED` quando o payload parseado contém o veredito válido; validar o shape do payload antes de confiar no `verdict`.
- [ ] Integrar com o flag/branch de `MOCK_MODE` introduzido em AI-HARD-0: incluir `mock: true` no retorno de mock e confirmar que falha de quota em runtime não cai no branch mock.
- [ ] Adicionar logging estruturado de nível ERROR (não silenciar) em todos os caminhos de falha.
- [ ] Escrever teste de regressão (ver Definition of Done).

## Dev Notes
- **Arquivos:** backend — módulo do serviço de IA contendo `validate_response` (Tester / quality gate). Localizar via `grep -rn "def validate_response" backend/` e `grep -rn "json.JSONDecodeError, Exception" backend/`. Endpoint relacionado: `/tester/validate`. Constante de veredito: `APPROVED` / `NEEDS_REVISION` / `REJECTED`. Dependência: o flag `MOCK_MODE` / detecção de mock no startup vem de AI-HARD-0.
- **Abordagem:** substituir o catch-all fail-open por tratamento de exceções estratificado. A regra de ouro: **falha nunca produz APPROVED**. Parse e transporte falham para `NEEDS_REVISION` + `degraded` + log ERROR; `AIServiceError` continua propagando; `APPROVED` exige payload bem-formado e parseável. Esta é uma mudança localizada de baixo risco (fail-closed), sem alterar a assinatura pública do endpoint além de adicionar campos `degraded`/`mock` ao retorno.
- **Riscos de regressão:** blast radius pequeno hoje — o veredito do Tester não é consumido por nenhum pipeline aluno-facing no estado atual (endpoint isolado), então mudar o default de falha não quebra fluxo de alunos. Consumidores atuais a verificar: o endpoint `/tester/validate` e o wrapper frontend `validateResponse` (atualmente não usado). Verificar que nenhum teste existente assume `APPROVED` como retorno em cenário de erro. Depende de AI-HARD-0 estar concluído (detecção de MOCK_MODE no startup) para o critério `mock:true`.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: cobre (a) `JSONDecodeError` → `NEEDS_REVISION`; (b) exceção de transporte → `NEEDS_REVISION` + `degraded` + log ERROR; (c) payload bem-formado válido → `APPROVED`; (d) `MOCK_MODE` → `mock:true`.
- [ ] Sem regressão na suíte de segurança / suíte de IA existente (propagação de `AIServiceError` intacta).
- [ ] QA Gate: PASS ou CONCERNS
- [ ] Nenhum bloco `except` no `validate_response` retorna `APPROVED`; logs ERROR confirmados em ambos os caminhos de falha.

## QA Results
_(a preencher pelo @qa)_
