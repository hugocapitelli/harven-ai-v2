# GOAL — 500 no resume do chat (GET messages)

> Declarado por Hugo Capitelli, 2026-07-15 ~14:30 (console do browser).
> Status: `ACHIEVED` (2026-07-15, it2 fechou GRD5-1/2/3 do QA; pendente rebuild do backend do Hugo) · Story: `docs/stories/epic-grades/GRD-5.story.md`

## Sintoma

Em build de produção (bundle `ChapterReader-B6L-qdId.js`), o resume do chat falha:
`Chat resume error: AxiosError 500` em recurso `messages` (2x). O aluno não consegue
retomar/abrir a sessão.

## Pronto quando (critério verificável)

1. Causa raiz nomeada na story GRD-5, com atenção à semântica real do supabase-py 2.28.x
   (`maybe_single().execute()` retorna `None` com 0 linhas — precedente: commit `5847a60`).
2. Teste vermelho→verde reproduzindo o 500 do caminho de resume (fake fiel ao None).
3. Caminho de resume (session by-content → messages) não retorna 500 em nenhum estado
   legítimo: sem sessão, sessão nova, sessão multi-row, sessão completed.
4. `cd backend && python -m pytest -q` exit 0.

## Pilares do loop

- **Verifier:** rubrica acima + validação do Hugo no ambiente real.
- **State:** este arquivo + story GRD-5.
- **Stop:** máx 3 iterações; depois escala.
