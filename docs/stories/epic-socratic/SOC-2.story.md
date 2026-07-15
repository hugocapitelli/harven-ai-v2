---
id: SOC-2
epic: GOAL-tres-interacoes
goal_ref: docs/goals/GOAL-tres-interacoes.md
phase: 1
status: Done
severity: HIGH
terminal: Backend
complexity: medium
depends_on: [SOC-1]
---
# SOC-2: Três interações reais garantidas por sessão socrática

## Story

Como aluno, quero ter direito às 3 interações reais com o tutor socrático antes da sessão
concluir, para que o diálogo não termine na minha 1ª ou 2ª mensagem (bug do screenshot de
2026-07-15: 1 mensagem enviada, sessão concluída com contador 0/3).

## Diagnóstico (verificado pelo orquestrador antes do loop)

1. **Off-by-one:** `_derive_pacing` usava `should_finalize = used >= MAX_INTERACTIONS - 1`
   com `used` já incluindo o turno corrente → finalizava na 2ª mensagem real.
2. **Sessão zumbi:** o turno finalizador nunca marcava a sessão `completed` no banco; a
   sessão esgotada ficava `active`, o create-or-get a retomava, o kickoff era replay em
   sessão não-virgem (GRD4-1) e contava como turno → conclusão na 1ª mensagem.

## Resolução (loop iter 1/3, PASS)

- `backend/services/ai_service.py` — `should_finalize = used >= MAX_INTERACTIONS`.
- `backend/routes_ai.py` — helper `_apply_session_completion` extraído de
  `complete_chat_session` (idempotente, guarda GRD-2, edge de score DATA-GAM-3 roda 1x) e
  invocado best-effort no turno finalizador da rota socrática, com ownership re-gateado;
  falha na marcação nunca derruba a resposta do tutor.
- `backend/tests/test_socratic_three_interactions.py` — NOVO, 4 oracles, com prova
  vermelho-antes/verde-depois dos 2 defeitos.
- `backend/tests/test_tutor_persistence.py` — 2 oracles TPP-5 re-alinhados ao contrato novo.
- Frontend intocado (decisão verificada pelo @qa: contador e transições 100% server-driven).

## QA Results

**Gate: PASS 5/5** (2026-07-15, @qa adversarial, provas reproduzidas independentemente).
Suíte 637 passed / 0 failed · build exit 0 · sem regressão SOC-1/GRD-2/3/4/IDOR/TPP.
Follow-ups LOW (backlog, não-bloqueantes): (1) guard fail-closed de sessão `completed` no
início de `socratic_dialogue`; (2) oracle zumbi bater no handler `create_or_get` end-to-end.

## Change Log

| Data | Mudança | Autor |
|:---|:---|:---|
| 2026-07-15 | Goal declarado, loop executado (red-test-first), QA PASS iter 1, status Done. | @dev + @qa via J.A.R.V.I.S. |
