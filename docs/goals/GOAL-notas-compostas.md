# GOAL — Notas compostas por interação socrática

> Declarado via `/goal` por Hugo Capitelli, 2026-07-15 09:06.
> Status: `ACHIEVED` (2026-07-15, QA PASS na iteração 2/3) · Story: `docs/stories/epic-grades/GRD-1.story.md`

## Objetivo

O Quadro de Notas da disciplina deixa de aceitar nota digitada por módulo/curso e passa a
exibir a nota COMPOSTA (média) das notas dadas pelo professor a cada interação socrática
(`session_reviews.rating`) do aluno. O professor entra no perfil do aluno dentro da
disciplina, vê cada interação (sessão de chat por conteúdo/capítulo), lê a conversa e dá
nota àquela interação. A média por curso e a média geral acompanham automaticamente.

## Pronto quando (critério verificável — rubrica ÚNICA do revisor)

1. **Quadro de Notas read-only composto:** a aba "Quadro de Notas" em
   `frontend/src/views/instructor/InstructorDetail.tsx` renderiza notas vindas de
   `GET /disciplines/{id}/gradebook` (`avg_rating`/`final_grade`/`overall_avg`), SEM
   inputs editáveis de nota por curso.
   - Verificação: `grep -n 'type="number"' frontend/src/views/instructor/InstructorDetail.tsx` → 0 ocorrências na seção de notas; `grep -n 'gradebook' frontend/src/services/api.ts frontend/src/views/instructor/*.tsx` → chamada real ao endpoint.
2. **Drill-down do aluno:** existe visão de perfil do aluno dentro da disciplina listando
   as sessões socráticas dele agrupadas por curso/capítulo, com a conversa legível e nota
   por sessão editável via `POST/PUT /chat-sessions/{session_id}/review`.
   - Verificação: rota/componente novo referenciado a partir do Quadro de Notas e/ou aba Alunos; `grep -n 'review' frontend/src/views/instructor/*.tsx` mostra o fluxo de avaliação por sessão.
3. **Composição automática:** dar nota a uma sessão reflete na média do curso e na média
   geral retornadas pelo gradebook (sem digitação manual).
   - Verificação: teste backend cobrindo agregação `session_reviews.rating → avg_rating → overall_avg` em `backend/tests/`.
4. **Gates mecânicos verdes:**
   - `cd frontend && npm run build` (tsc -b && vite build) → exit 0
   - `cd backend && python -m pytest -q` → exit 0

## Comandos de verificação literais

```bash
cd /Users/hugocapitelli/Dev/eximia/harven-ai-v2/frontend && npm run build
cd /Users/hugocapitelli/Dev/eximia/harven-ai-v2/backend && python -m pytest -q
grep -n 'type="number"' /Users/hugocapitelli/Dev/eximia/harven-ai-v2/frontend/src/views/instructor/InstructorDetail.tsx
grep -rn 'gradebook' /Users/hugocapitelli/Dev/eximia/harven-ai-v2/frontend/src/services/api.ts
```

## Pilares do loop

- **Verifier:** rubrica acima (imutável durante o ciclo) + QA gate @qa.
- **State:** este arquivo + story GRD-1 (Change Log append-only).
- **Stop:** máx 3 iterações dev↔qa; depois escala ao Senhor (finops-guardrails).
