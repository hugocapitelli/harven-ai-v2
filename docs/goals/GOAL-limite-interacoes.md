# GOAL — Limite de interações não pode ser consumido pelo tutor

> Declarado por Hugo Capitelli, 2026-07-15 13:50 (screenshot).
> Status: `ACHIEVED` (2026-07-15, QA PASS na iteração 2; pendente rebuild do backend do Hugo — Frente A) · Story: `docs/stories/epic-grades/GRD-4.story.md`

## Sintoma

Ao iniciar a sessão socrática, o tutor manda a mensagem de abertura (kickoff) e o limite
da sessão se esgota imediatamente: contador **0/3**, rodapé "Sessao concluida", input
bloqueado, status Concluído — sem o aluno ter mandado UMA mensagem. Todo clique em
iniciar repete o padrão. (Caso vivo: IAA-2026, 1_Aula_Inaugural.pdf, questão 1.)

## Pronto quando (critério verificável)

1. **Causa raiz nomeada na story GRD-4**, incluindo veredito explícito sobre o ambiente:
   o backend que o Hugo está rodando contém os fixes it2/it3 da GRD-3 (working tree) ou
   está servindo código velho (Docker sem rebuild)?
2. **Semântica do limite correta e testada:** o limite de interações da sessão conta
   APENAS turnos do aluno (`role='user'`); kickoff e mensagens do tutor nunca consomem
   limite nem finalizam a sessão. Contador da UI reflete isso (sessão recém-criada com
   kickoff = 3/3 disponíveis ou 0 usadas, input liberado).
3. **Fluxo vivo do Hugo destravado:** iniciar/refazer sessão → kickoff → aluno consegue
   enviar mensagens até o limite real de turnos do aluno.
4. **Gates:** `cd backend && python -m pytest -q` (baseline 619/0) e
   `cd frontend && npm run build` exit 0 se tocar frontend.

## Pilares do loop

- **Verifier:** rubrica acima + validação visual do Hugo.
- **State:** este arquivo + story GRD-4.
- **Stop:** máx 3 iterações; depois escala ao Senhor.
