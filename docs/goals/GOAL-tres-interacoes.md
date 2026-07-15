# GOAL, Três interações reais garantidas por sessão socrática

> Declarado por Hugo Capitelli (via screenshot + "não deixa concluir as três mensagens"), 2026-07-15 16:20.
> Status: `PASSED` (loop iter 1/3, QA adversarial PASS 5/5, 2026-07-15) · Story: `docs/stories/epic-socratic/SOC-2.story.md`
> Provas: pytest 637 passed/0 failed · build exit 0 · vermelho-antes/verde-depois documentado.

## Objetivo

O aluno tem direito a EXATAMENTE 3 interações reais (mensagens dele, pós-kickoff) por sessão
socrática. Hoje: (1) off-by-one em `_derive_pacing` (`should_finalize = used >= MAX-1`, com
`used` já incluindo o turno corrente) conclui a sessão na 2ª mensagem; (2) sessão que atinge
o limite nunca é marcada `completed` no banco, virando zumbi `active` esgotada que, retomada
via create-or-get, consome o kickoff como turno e conclui na 1ª mensagem do aluno (caso do
screenshot: 0/3 após 1 mensagem).

## Pronto quando (critério verificável, rubrica ÚNICA do revisor)

1. **3 turnos reais, fecha no 3º:** com sessão virgem e kickoff honrado (GRD-4), as mensagens
   reais 1 e 2 do aluno retornam `should_finalize: false` (`interactions_remaining` 2 e 1) e a
   3ª retorna `should_finalize: true` com a síntese de fechamento. Teste vermelho-antes/verde-depois
   em `backend/tests/` provando a sequência completa (kickoff + 3 turnos).
2. **Completion edge server-side:** o turno que retorna `should_finalize: true` marca a sessão
   `completed` no banco (sem depender do frontend chamar `complete`), sem quebrar o hook de
   score/gamificação existente da edge de conclusão (DATA-GAM-3/GRD-2) e sem dupla conclusão.
   Teste backend prova: após o 3º turno, `chat_sessions.status == 'completed'`.
3. **Zumbi nunca mais:** com a sessão mais recente `completed`, o fluxo existente (SEC-CHAT-3 +
   GRD-3 Refazer + SOC-1 by-content) cria sessão NOVA virgem onde o kickoff é honrado, e o
   aluno tem 3 interações de novo. Teste backend: sessão esgotada → novo create-or-get →
   kickoff honrado (não conta) → turno 1 retorna remaining=2.
4. **Sem regressão:** suíte inteira verde, incluindo `test_tutor_persistence.py` (oracles TPP-5
   re-alinhados ao contrato corrigido, se necessário), `test_session_question_lock.py`, GRD-2/3/4
   e segurança IDOR.
5. **Gates mecânicos:**
   - `cd backend && python3 -m pytest -q` → exit 0
   - `cd frontend && npm run build` → exit 0 (se houver ajuste de frontend; contador 0/3 → N/3 correto)

## Comandos de verificação literais

```bash
cd /Users/hugocapitelli/Dev/eximia/harven-ai-v2/backend && python3 -m pytest -q
cd /Users/hugocapitelli/Dev/eximia/harven-ai-v2/frontend && npm run build
grep -n 'should_finalize' /Users/hugocapitelli/Dev/eximia/harven-ai-v2/backend/services/ai_service.py
```

## Pilares do loop

- **Verifier:** rubrica acima (imutável durante o ciclo) + QA gate @qa adversarial.
- **State:** este arquivo + story SOC-2 (Change Log append-only).
- **Stop:** máx 3 iterações dev↔qa; depois escala ao Senhor (finops-guardrails).
