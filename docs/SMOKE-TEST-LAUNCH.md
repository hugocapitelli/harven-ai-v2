# Smoke Test — Lançamento Harven.AI v2

> Checklist manual, passo a passo, para o teste contra staging/produção do dia
> seguinte ao sprint `sprint/launch-funcional`. Cobre os 3 commits do sprint:
> `4631756` (onda 1 — uploads honestos e performance_score real),
> `1465102` (onda 2 — fluxo do aluno + notas JSON/CSV),
> `f6441ff` (onda 3 — podcast completo e jobs TTS duráveis).

## Antes de começar (obrigatório)

1. **Aplicar as migrações no Supabase ANTES do deploy.** No SQL Editor do
   projeto, rodar em **ordem alfabética** os dois arquivos novos deste sprint:
   - `supabase/migrations/20260707000001_tts_jobs.sql`
   - `supabase/migrations/20260707000002_content_audio_type.sql`

   Confirme que ambos rodam sem erro (idempotentes — podem ser reexecutados
   com segurança se algo falhar no meio).

2. **O deploy no EasyPanel só acontece com push + aprovação do Hugo.** Este
   smoke test roda contra o ambiente já publicado (staging ou produção) — não
   é um gate para autorizar o push, é a verificação pós-deploy.

3. Tenha em mãos: 1 login de professor (`TEACHER`/`INSTRUCTOR`), 2 logins de
   aluno distintos (`STUDENT` A e B), 1 disciplina com pelo menos 1 curso e 1
   capítulo, e os dois logins de aluno matriculados na mesma disciplina.

---

## Passo a passo

### 1. Login professor + aluno

- **Rota:** `POST /auth/login`
- **Verificar:** ambos os logins retornam 200 com token JWT válido; o painel
  carrega conforme o `role` (professor vê gestão de disciplina, aluno vê
  catálogo de cursos).
- **Bug antigo:** N/A — item de baseline, confirma que o ambiente está no ar
  antes de seguir.

### 2. Criar usuário (senha ≥ 6 caracteres)

- **Rota:** `POST /users`
- **Verificar:** criar 1 usuário novo com senha de 6 caracteres exatos —
  aceita (200/201). Repetir com senha de 5 caracteres — rejeita (422/400).
- **Bug antigo:** validação de senha mínima inconsistente entre front e back;
  confirmar que o back também recusa senha curta, não só o front.

### 3. Vincular professor a disciplina

- **Rota:** `POST /disciplines/{discipline_id}/teachers`
- **Verificar:** professor aparece em `GET /disciplines/{discipline_id}/teachers`
  logo em seguida.
- **Bug antigo:** N/A — pré-requisito para o gate de escopo
  (`assert_teacher_owns_discipline`) usado nas rotas de notas abaixo.

### 4. Matricular aluno

- **Rota:** `POST /disciplines/{discipline_id}/students`
- **Verificar:** aluno A e aluno B aparecem em
  `GET /disciplines/{discipline_id}/students` após a matrícula.
- **Bug antigo:** N/A — pré-requisito para os passos de progresso per-aluno.

### 5. Upload de PDF (extraction_status ok)

- **Rota:** `POST /chapters/{chapter_id}/upload` (multipart, campo `file`)
- **Verificar:** resposta 200/201 com `extraction_status: "ok"` e o campo
  `body` do content criado preenchido com o texto extraído do PDF.
- **Bug antigo:** extração de PDF podia falhar silenciosamente e o content
  ficava sem `body`, sem sinalizar o motivo. Agora o status é honesto
  (`ok` / `empty` / `failed` / `unsupported`) e visível na resposta.

### 6. Upload de PPTX (extrai agora)

- **Rota:** `POST /chapters/{chapter_id}/upload` com um `.pptx`
  (`content_type: application/vnd.openxmlformats-officedocument.presentationml.presentation`)
- **Verificar:** resposta com `extraction_status: "ok"` e `body` populado com
  o texto slide a slide (não mais `"unsupported"`).
- **Bug antigo:** antes deste sprint, `.pptx` caía direto em
  `extraction_status: "unsupported"` — nunca era extraído. Este é o teste que
  prova a correção (commit `4631756`, `services/text_extractor.py`).

### 7. Upload inválido (400, não 500)

- **Rota:** `POST /chapters/{chapter_id}/upload` com um tipo de arquivo fora
  da lista permitida (ex.: `.zip`, `application/zip`)
- **Verificar:** resposta **400** com `detail` explicando o tipo não
  permitido. Repetir com um arquivo maior que o limite de upload (50MB) —
  resposta **413**, não 500.
- **Bug antigo:** uploads inválidos podiam estourar em erro 500 genérico em
  vez de um 400/413 tratado.

### 8. Aluno abre conteúdo (mídia renderiza)

- **Rota (view):** tela do capítulo/conteúdo do aluno (`ChapterReader`)
- **Verificar:** o PDF, o PPTX extraído e qualquer vídeo/áudio anexado
  renderizam corretamente na tela do aluno (não apenas o link cru).
- **Bug antigo:** commit `1465102` corrigiu renderização de mídia que não
  aparecia corretamente para o aluno.

### 9. Diálogo socrático completo (pacing server-side)

- **Rota:** `POST /api/ai/socrates/dialogue`
- **Verificar:** iniciar uma sessão de chat no conteúdo, trocar mensagens até
  o limite de interações (`MAX_INTERACTIONS` na UI, contador decrescente
  visível). Confirmar que o contador de interações restantes reflete o que
  está persistido no `session_id` do backend, não um contador local do
  front (recarregar a página no meio do diálogo e confirmar que o contador
  não reseta).
- **Bug antigo:** o pacing (quantas interações restam) podia divergir entre
  front e back quando calculado só no cliente; agora
  `interactions_remaining` é resolvido a partir do transcript persistido
  via `session_id` sempre que ele existe (ver `routes_ai.py`, comentário
  TPP-5).

### 10. Fechar/reabrir chat (botões funcionam)

- **Rota (view):** botão de fechar (X) e reabrir o painel do Tutor Socrático
  em `ChapterReader`
- **Verificar:** fechar o painel de chat e reabri-lo preserva o histórico de
  mensagens da sessão ativa (não perde o transcript); os botões de
  fechar/enviar/reabrir respondem sem travar em estado de loading.
- **Bug antigo:** commit `1465102`/`f6441ff` mexeram em `ChapterReader.tsx`
  (estado `chatOpen`) — confirmar que não há regressão de UI travada.

### 11. Concluir conteúdo (progresso per-aluno, NÃO vaza pro outro aluno — testar com 2º login)

- **Rota:** `POST /users/{user_id}/activities` (via `userStatsApi.completeContent`)
- **Verificar:**
  1. Logado como aluno A, marcar o conteúdo como concluído. Confirmar que
     o badge "Concluído" aparece para o aluno A.
  2. Trocar para o login do aluno B (mesma disciplina, mesmo conteúdo).
     Confirmar que o conteúdo aparece **"Em andamento"** para o aluno B, ou
     seja, o progresso de A **não vazou** para B.
  3. Confirmar que a chamada usa `user.id` da sessão autenticada do aluno
     que clicou, nunca um id vindo de props/estado compartilhado.
- **Bug antigo (B2, bug #24):** completar conteúdo antes mutava o registro
  compartilhado do catálogo (`contentsApi.update({ completed })`), então a
  conclusão de um aluno aparecia como concluída para todos. Agora é
  `userStatsApi.completeContent(user.id, courseId, contentId)`, escopado por
  usuário. Um 503 (tabela de progresso ausente) deve degradar
  graciosamente para "concluído visualmente" sem travar o aluno.

### 12. Sessão `completed` grava `performance_score`

- **Rota:** `PUT /chat-sessions/{session_id}/complete`
- **Verificar:** ao completar a sessão de chat (via passo 11, que também
  fecha a sessão associada), o registro em `chat_sessions` passa a ter
  `status: "completed"` e `performance_score` preenchido (não nulo, salvo
  quando o transcript é curto demais para computar sinal — nesse caso fica
  `NULL`, nunca `0` forçado). Chamar o mesmo endpoint uma 2ª vez na mesma
  sessão deve ser um no-op idempotente (200, sem recalcular o score).
- **Bug antigo:** `performance_score` não era calculado de verdade; a
  correção computa a partir dos turnos persistidos (`compute_performance_score`)
  exatamente uma vez, na transição `active -> completed`.

### 13. Professor revisa sessão + dá nota manual (sem 500)

- **Rota A (revisão da sessão):** `POST /chat-sessions/{session_id}/review`
  (rating + feedback do professor)
- **Rota B (nota manual):**
  `PUT /disciplines/{discipline_id}/students/{student_id}/grade`
  (body: `{ course_id, grade }`)
- **Verificar:**
  1. Logado como professor, criar uma review na sessão do aluno A — 201,
     sem erro. Tentar criar uma 2ª review na mesma sessão — 409 (já existe).
  2. Definir uma nota manual para o aluno A no curso — 200, sem 500, mesmo
     se a tabela `grade_overrides` ainda não existisse antes (o endpoint
     trata a ausência da tabela com erro tratado, nunca um crash cru).
  3. Confirmar que o campo `graded_by` na nota gravada é o `id` do professor
     autenticado, nunca vindo do corpo da requisição.
- **Bug antigo:** commit `1465102` corrigiu `graded_by` (estava incorreto/
  não persistido) e tratou o caso de a tabela `grade_overrides` não existir
  sem estourar 500.

### 14. `GET /api/disciplines/{id}/grades/export` (JSON com notas reais) e `?format=csv` (baixa planilha)

- **Rota:** `GET /disciplines/{discipline_id}/grades/export`
  (querystring opcional `?format=csv`, default `json`)
- **Verificar:**
  1. Sem querystring (ou `?format=json`): resposta 200,
     `{"discipline_id": ..., "data": [...]}`, com uma linha por sessão de
     cada aluno matriculado, incluindo `performance_score`,
     `review_rating` (da review do passo 13) e `grade_override` (da nota
     manual do passo 13) quando existirem.
  2. Com `?format=csv`: resposta 200, `Content-Type: text/csv`,
     `Content-Disposition: attachment; filename=grades-{discipline_id}.csv`,
     e o arquivo baixa/abre como planilha com o cabeçalho
     `student_id, student_name, ra, email, content_id, content_title,
     session_status, started_at, completed_at, interactions_used,
     performance_score, review_rating, grade_override`.
  3. Confirmar escopo: logado como o professor vinculado à disciplina, a
     exportação funciona; logado como professor de OUTRA disciplina, a
     mesma rota deve barrar (403) — não vazar notas de disciplina alheia.
- **Bug antigo:** endpoint de export não existia ou não trazia notas reais
  (dados mockados/incompletos); agora agrega sessões + reviews + overrides
  de verdade, com fallback gracioso se `grade_overrides` não existir.

### 15. Gerar podcast de capítulo longo (script completo, job sobrevive, sem done fantasma)

- **Rota A (disparo):** `POST /api/ai/audio/generate-from-content`
  (body: `{ content_id, audio_type: "podcast", voice? }`)
- **Rota B (polling):** `GET /api/ai/audio/status/{job_id}`
- **Verificar:**
  1. Disparar a geração num conteúdo com texto longo (capítulo extenso,
     não um parágrafo curto). Resposta imediata: `{"job_id": ..., "status":
     "processing"}` — não bloqueia a requisição esperando o áudio pronto.
  2. Fazer polling em `GET /api/ai/audio/status/{job_id}` a cada alguns
     segundos. Enquanto processando: `{"status": "processing"}`.
     Ao concluir: `{"status": "done", "audio_url": ..., "duration_estimate":
     ..., "audio_type": "podcast"}`. O **script do podcast deve cobrir o
     capítulo inteiro**, não só um resumo truncado do início.
  3. Disparar um 2º submit para o MESMO `content_id` + mesmo `audio_type`
     enquanto o 1º ainda está `processing` — deve retornar o **mesmo**
     `job_id` já ativo (dedup), não criar um job duplicado.
  4. Fazer 2 polls consecutivos DEPOIS de `done` — ambos devem retornar o
     mesmo payload (idempotente, sem "pop"/apagar o resultado no meio do
     caminho — sem "done fantasma" que suma numa 2ª consulta).
  5. Se possível, simular/observar timeout ou erro do worker: o job deve
     transicionar para `{"status": "error", "detail": ...}` de forma
     persistida (não travar em `processing` para sempre nem sumir sem
     explicação).
- **Bug antigo:** jobs de TTS viviam em memória de processo (dict volátil),
  perdiam-se em restart/erro, podiam retornar "done" numa consulta e depois
  desaparecer ("done fantasma") numa consulta seguinte, e o script do
  podcast era truncado em vez de cobrir o capítulo completo. Este sprint
  (onda 3, `f6441ff`) introduziu `tts_jobs` persistido
  (`TtsJobRepository`), dedup por `(content_id, audio_type)`, cap de jobs
  concorrentes por usuário, e poller resiliente no front.

---

## Resumo de rotas testadas

| # | Rota | Método |
|---|---|---|
| 1 | `/auth/login` | POST |
| 2 | `/users` | POST |
| 3 | `/disciplines/{id}/teachers` | POST |
| 4 | `/disciplines/{id}/students` | POST |
| 5, 6, 7 | `/chapters/{chapter_id}/upload` | POST |
| 8 | (view) `ChapterReader` | — |
| 9 | `/api/ai/socrates/dialogue` | POST |
| 10 | (view) `ChapterReader` (chat panel) | — |
| 11 | `/users/{user_id}/activities` (`userStatsApi.completeContent`) | POST |
| 12 | `/chat-sessions/{session_id}/complete` | PUT |
| 13 | `/chat-sessions/{session_id}/review`, `/disciplines/{id}/students/{student_id}/grade` | POST, PUT |
| 14 | `/disciplines/{id}/grades/export` | GET |
| 15 | `/api/ai/audio/generate-from-content`, `/api/ai/audio/status/{job_id}` | POST, GET |

## Critério de aprovação

Todos os 15 passos concluídos sem erro 500 inesperado, sem vazamento de
progresso/nota entre alunos ou disciplinas, e com os campos honestos
(`extraction_status`, `performance_score`, `grade_override`,
`audio_url`/`status`) refletindo o estado real, não valores mockados ou
travados. Qualquer desvio deve ser registrado com o número do passo e a
resposta exata recebida, antes de autorizar o push/deploy final.
