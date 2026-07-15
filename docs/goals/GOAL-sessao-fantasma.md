# GOAL — Sessão fantasma: concluída sem interação e invisível na avaliação

> Declarado via `/goal` por Hugo Capitelli, 2026-07-15 10:18 (bug report com screenshot).
> Status: `ACHIEVED` (2026-07-15, QA PASS na iteração 1) · Story: `docs/stories/epic-grades/GRD-2.story.md`

## Sintoma reportado

1. Sessão do Tutor Socrático aparece como **"Concluído"** com contador **0/3** interações:
   o painel mostra apenas a mensagem de abertura do tutor (nenhuma resposta do aluno) e o
   rodapé "Sessao concluida. Veja a sintese de fechamento acima."
2. Na avaliação do professor (drill-down do aluno / aba Conversas), **a sessão não aparece**.

Reprodução observada: disciplina IAA-2026, aluno Jeferson (JE), conteúdo de liderança/trilhas.

## Pronto quando (critério verificável)

1. **Causa raiz documentada** na story GRD-2 (por que a sessão foi marcada `completed` sem
   nenhuma mensagem do aluno; e por que ela não é listada na avaliação).
2. **Teste vermelho→verde:** teste(s) pytest que reproduzem o bug ANTES do fix (vermelho) e
   passam DEPOIS (verde) — first-move rule de bug fix.
3. **Comportamento correto:** sessão só vira `completed` mediante interação real/fluxo
   legítimo de conclusão; sessões existentes do aluno (qualquer status) ficam visíveis ao
   professor no drill-down/avaliação, para que nenhuma interação fique fora do alcance da nota.
4. **Gates:** `cd backend && python -m pytest -q` sem regressão (2 falhas pré-existentes do
   tutor pacing toleradas se ainda fora de escopo); `cd frontend && npm run build` exit 0 se
   houver mudança de frontend.

## Pilares do loop

- **Verifier:** rubrica acima + re-gate @qa se o fix for não-trivial.
- **State:** este arquivo + story GRD-2.
- **Stop:** máx 3 iterações; depois escala ao Senhor.
