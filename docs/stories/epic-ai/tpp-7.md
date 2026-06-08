---
id: TPP-7
epic: EPIC-AI
phase: 3
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: high
depends_on: [TPP-4, ASYNC-AI-1]
bug_refs: [5, 32]
---
# TPP-7: Encadear gate Editor→Tester atrás de flag

## Story
Como aluno do tutor socrático da Harven.AI, quero que toda resposta do tutor passe por um segundo passe determinístico de validação pedagógica (Editor refina, Tester valida) antes de me ser exibida, para que respostas degradadas ou que vazem a resposta sejam filtradas/regeneradas — sem que uma eventual falha desse passe de validação me deixe sem resposta.

## Contexto (do bug sweep)
Defeito raiz — Item #5 (`backend/routes_ai.py:261-292`): a arquitetura anuncia um pipeline de 6 agentes (Socrates gera → Editor refina → Tester valida com APROVADO/NEEDS_REVISION/REJECTED), mas o diálogo ao vivo (`ChapterReader.tsx → aiApi.socraticDialogue`) só chama `/api/ai/socrates/dialogue`. Os endpoints `/editor/edit` e `/tester/validate` são isolados e **nunca invocados no fluxo** — os wrappers frontend `editResponse`/`validateResponse` não são usados. Resultado: a camada de validação/edição é **código morto**; uma resposta socrática degradada ou que vaze a solução é mostrada ao aluno sem filtro, e o veredito do Tester não barra nada (impacto em todo turno do tutor em produção).

Defeito acoplado — Item #32 (`backend/services/ai_service.py:629-633`): `validate_response` (o Tester) usa `except (json.JSONDecodeError, Exception)` que captura **todo** erro e retorna um veredito **fabricado** `{verdict: APPROVED, score: 0.80}`. Hoje, como o veredito não alimenta nenhum gating aluno-facing, o impacto realizado é apenas resposta de endpoint enganosa. Mas ao encadear o gate (esta story), esse fail-open silencioso se torna perigoso: precisa virar fail-open **explícito e logado** que jamais bloqueia o aluno, em vez de carimbar APPROVED mascarando a falha.

A correção do item #5 (encadear server-side dentro de `socratic_dialogue`: Socrates → Editor → Tester, retornando só output APROVADO e regenerando em REJECTED) é exatamente o escopo desta story, **atrás de feature flag** para rollout seguro.

## Acceptance Criteria
- [x] **Flag OFF (default):** `socratic_dialogue` faz uma única chamada (Socrates) e retorna direto — sem Editor/Tester. _(`test_flag_off_single_call_unchanged` → `len(fake.calls) == 1`.)_
- [x] **Flag ON — caminho feliz:** encadeia Socrates → Editor → Tester server-side; APPROVED/NEEDS_REVISION retorna o texto editado. _(`test_flag_on_runs_editor_and_tester` → ≥3 chamadas.)_
- [x] **Flag ON — REJECTED:** regenera **exatamente 1 vez** (novo passe Socrates → Editor), depois devolve a melhor resposta sem segundo retry. _(`test_flag_on_rejected_regenerates_once` → exatamente 6 chamadas, output = `edited v2`.)_
- [x] **Falha do Tester nunca bloqueia o aluno:** Tester com exceção → aluno recebe a resposta editada; `validate_response` retorna `UNKNOWN`/`NEEDS_REVISION`, **nunca** `APPROVED` fabricado (#32). _(`test_tester_failure_never_blocks_and_no_fabricated_approved`.)_
- [x] **Falha do Editor nunca bloqueia o aluno:** `_edit_safe` cai para o texto de entrada; o gate (`_run_editor_tester_gate`) degrada para a melhor resposta com log.
- [x] Nenhuma exceção do gate propaga: `_run_editor_tester_gate` envolve tudo em try/except, sempre retornando a melhor resposta (nunca 5xx).
- [x] Testes de regressão: (a) OFF inalterado, (b) ON+REJECTED 1 regeneração, (c) Tester exceção → resposta + log, sem APPROVED fabricado.

## Tasks / Subtasks
- [ ] Adicionar feature flag de servidor (ex.: env `AI_GATE_EDITOR_TESTER_ENABLED`, default `false`) lida em `backend/services/ai_service.py` (ou no módulo de settings existente). Documentar default = OFF.
- [ ] Em `backend/services/ai_service.py`, dentro de `socratic_dialogue` (def a partir de `ai_service.py:367`), após obter o output do Socrates: se flag OFF → `return` imediato do comportamento atual; se ON → encadear o gate.
- [ ] Implementar o gate como helper interno (ex.: `_run_editor_tester_gate(socrates_output, context)`) que chama `edit_response` (`ai_service.py:573`) e depois `validate_response` (`ai_service.py:610`).
- [ ] Implementar regeneração 1× em REJECTED: re-chamar o passe Socrates→Editor→Tester apenas uma vez; após isso devolver a melhor resposta sem novo retry.
- [ ] **Corrigir item #32** em `validate_response` (`ai_service.py:629-633`): separar `json.JSONDecodeError`/erros de transporte de veredito real; no `except`, logar e retornar `verdict: "NEEDS_REVISION"` (ou `"UNKNOWN"`) em vez de `APPROVED` fabricado. Preservar o ramo MOCK_MODE.
- [ ] Garantir try/except no gate dentro de `socratic_dialogue` de modo que qualquer falha de Editor/Tester resulte em fallback para a resposta disponível + log (nunca 5xx ao aluno).
- [ ] Confirmar que as chamadas do gate respeitam o padrão async corrigido por ASYNC-AI-1 (não bloquear o event loop ao adicionar 1–2 chamadas LLM extras por turno) e o tratamento de erro consolidado por TPP-4.
- [ ] Escrever testes de regressão (pytest) cobrindo os 3 desfechos dos AC, mockando `_call_openai`/`edit_response`/`validate_response`.

## Dev Notes
- **Arquivos:**
  - `backend/services/ai_service.py` — `socratic_dialogue` (def `:367`), `edit_response` (`:573`), `validate_response` (`:610-633`), prompts `EDITOR_PROMPT`/`TESTER_PROMPT` e contrato de veredito (`:119` → `APPROVED|NEEDS_REVISION|REJECTED`).
  - `backend/routes_ai.py:261-292` — handlers isolados `/editor/edit` e `/tester/validate` (referência do contrato; o encadeamento NÃO deve ser feito no frontend e sim server-side em `socratic_dialogue`).
  - Frontend `apps/.../ChapterReader.tsx` + wrapper `aiApi.socraticDialogue` — apenas consumidor; **não deve mudar** (o gate é transparente server-side).
- **Abordagem:** Encadeamento server-side dentro de `socratic_dialogue`, gated por flag. OFF preserva o caminho atual literalmente (early return). ON: Socrates → Editor → Tester; APPROVED/NEEDS_REVISION devolve texto editado; REJECTED regenera 1×; qualquer falha do gate degrada graciosamente para a melhor resposta disponível e loga. Corrigir o fail-open do Tester (#32) para que falha vire `NEEDS_REVISION`/`UNKNOWN` logado, não `APPROVED` — assim "falha do Tester nunca bloqueia o aluno" é satisfeito devolvendo a resposta editada, não inventando aprovação.
- **Riscos de regressão (blast radius):**
  - `socratic_dialogue` é o coração do tutor ao vivo — chamado em **todo turno** via `/api/ai/socrates/dialogue` ← `ChapterReader.tsx`. Mudança incorreta afeta 100% das interações do aluno → flag OFF por default é o gate de segurança.
  - Custo/latência: ON adiciona até 2 chamadas LLM por turno (3 no caso de regeneração REJECTED). Validar contra orçamento de tokens (relacionado ao budget de editor/tester mencionado no item de FinOps do sweep).
  - Dependência ASYNC-AI-1: chamadas LLM extras precisam ser não-bloqueantes; sem isso, o gate amplifica o congelamento do event loop. **Esta story assume ASYNC-AI-1 já mergeado.**
  - Dependência TPP-4: padronização de tratamento de erro/exceções nos endpoints AI; o gate deve usar a mesma convenção para não reintroduzir vazamento/5xx.
  - `validate_response` também é usado pelo endpoint isolado `/tester/validate` (`routes_ai.py:278-292`) — a correção do `except` (#32) muda o veredito devolvido a esse endpoint em caso de falha (de APPROVED para NEEDS_REVISION/UNKNOWN); confirmar que nenhum consumidor depende do APPROVED fabricado.

## Definition of Done
- [x] Teste de regressão verde para os 3 cenários (4 testes `TestTpp7Gate`).
- [x] Sem regressão na suíte de segurança (323 verdes).
- [x] QA Gate: PASS ou CONCERNS.
- [x] Flag default = OFF (`AI_GATE_EDITOR_TESTER_ENABLED`, lida via `os.getenv`, default `false`); OFF idêntico ao baseline (1 chamada).
- [x] `validate_response` não retorna mais `APPROVED` em exceção (#32): transporte → `UNKNOWN`, JSON inválido → `NEEDS_REVISION`, ambos logados. MOCK_MODE preserva o fallback canônico APPROVED.
- [x] Nenhuma falha de Editor/Tester vira 5xx (gate sempre devolve a melhor resposta).

## Dev Agent Record

**Agent:** Dex (@dev) · **Date:** 2026-06-05 · **Status:** Ready for Review

**Files changed:**
- `backend/services/ai_service.py`:
  - Flag `AI_GATE_EDITOR_TESTER_ENABLED` (default OFF) + `_editor_tester_gate_enabled()` (read per-call, monkeypatchable).
  - `socratic_dialogue` invokes `_run_editor_tester_gate` only when ON, after generating the Socrates reply.
  - `_run_editor_tester_gate` (Editor→Tester; REJECTED → regenerate exactly once; any failure → best available reply + log; never raises). Helpers `_generate_socratic_reply`, `_edit_safe`, `_validate_safe`.
  - **Fixed #32**: `validate_response` exception path no longer fabricates `APPROVED` — transport/runtime → `UNKNOWN`, JSON parse error → `NEEDS_REVISION`, both logged; MOCK_MODE branch (canned APPROVED) preserved.
- `backend/tests/test_tutor_persistence.py` — `TestTpp7Gate` (4 tests, including a scripted client proving exactly one regeneration and a flaky Tester proving no fabricated APPROVED).

**Notes / decisions:**
- `[AUTO-DECISION]` Flag read via `os.getenv` inside the service (not `config.Settings`). Reason: TPP-7 task permits "ai_service.py or settings"; per-call env read is the cleanest monkeypatch surface for tests and a flippable runtime toggle. Default OFF keeps the existing `len(fake.calls)==1` contracts green.
- OFF path makes exactly one `_call_openai` — zero added latency/cost, byte-identical to baseline.

**Tests:** full suite `323 passed`. TPP-7-specific: 4/4 pass.

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-05 (re-review after delivery; supersedes the earlier FAIL, which predated the merge).

Verified in `ai_service.py` (lines 559-666, 851-882):
- Flag `AI_GATE_EDITOR_TESTER_ENABLED` (default OFF, read per-call via `_editor_tester_gate_enabled()` → monkeypatchable). OFF → `socratic_dialogue` makes exactly one Socrates `_call_openai` and returns raw (byte-identical baseline).
- ON → `_run_editor_tester_gate`: Socrates → `_edit_safe` (Editor) → `_validate_safe` (Tester). APPROVED/NEEDS_REVISION returns the edited text. REJECTED → regenerate the full pass EXACTLY ONCE, then return the best reply (no second retry, no loop). Any gate exception degrades to the best available reply + log — never raises, never 5xx to the student.
- #32 fix confirmed in `validate_response`: MOCK_MODE keeps canned APPROVED; a real transport/runtime failure returns `UNKNOWN`, JSON parse error returns `NEEDS_REVISION` — never a fabricated APPROVED. `_validate_safe` defaults to `NEEDS_REVISION`.

Tests: `TestTpp7Gate` (4) green and rigorous:
- `test_flag_off_single_call_unchanged`: exactly 1 call, raw output.
- `test_flag_on_rejected_regenerates_once`: scripted client asserts EXACTLY 6 calls (one regeneration, never more) and the student receives `edited v2` — proves bounded retry + approved-only output.
- `test_tester_failure_never_blocks_and_no_fabricated_approved`: flaky Tester → verdict in {UNKNOWN, NEEDS_REVISION}, `!= APPROVED`, and the dialogue still returns the edited reply.

Minor note (non-blocking): `test_flag_on_runs_editor_and_tester` is the weakest of the four (asserts only `len(calls) >= 3`, doesn't assert the approved-only output shape) — but the rejected-regeneration test covers exact count + exact content, so the cluster is not false-green. Gate ships OFF by default = safe rollout.
