# GOAL — Refazer sessão socrática (destravar aluno de sessão concluída)

> Declarado por Hugo Capitelli, 2026-07-15 ~10:40.
> Status: `ACHIEVED` (2026-07-15, QA PASS na iteração 1; validação visual do Hugo pendente) · Story: `docs/stories/epic-grades/GRD-3.story.md`

## Sintoma / necessidade

Não existe botão de refazer a sessão socrática. Com uma sessão marcada `completed`
(inclusive as fantasmas legadas com 0 interações) e/ou o flag `tutorDone` sujo no
localStorage, o painel do tutor mostra "Sessão concluída" e o aluno fica SEM caminho
para fazer/refazer as perguntas e interações. É o caso vivo do Hugo agora (IAA-2026).

## Pronto quando (critério verificável)

1. **Botão "Refazer sessão"** no painel do Tutor Socrático quando a sessão do conteúdo
   está `completed`: inicia uma NOVA sessão (nova linha em `chat_sessions`, padrão de
   nova tentativa já existente), limpa o estado local do conteúdo (flag `tutorDone`
   e afins) e abre o chat pronto para interagir com a pergunta.
2. **Sessão fantasma não tranca:** um conteúdo cuja única sessão é fantasma
   (`completed` com 0 mensagens do aluno) permite refazer normalmente pelo mesmo botão.
3. **Avaliação preserva histórico:** as sessões anteriores (inclusive refeitas)
   continuam visíveis ao professor no drill-down; a nova sessão aparece após interação.
4. **Gates:** `cd frontend && npm run build` exit 0; `cd backend && python -m pytest -q`
   sem regressão (614 passed baseline); teste novo cobrindo o fluxo de refazer se houver
   mudança de backend.

## Pilares do loop

- **Verifier:** rubrica acima + validação visual do Hugo (caso vivo dele destravado).
- **State:** este arquivo + story GRD-3.
- **Stop:** máx 3 iterações; depois escala ao Senhor.
