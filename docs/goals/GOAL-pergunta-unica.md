# GOAL, Pergunta socrática única e retomável por conteúdo

> Declarado via `/goal` por Hugo Capitelli, 2026-07-15 09:24.
> Status: `PASSED` (loop iter 1/3, QA adversarial PASS 2026-07-15 09:50) · Story: `docs/stories/epic-socratic/SOC-1.story.md`
> Provas: pytest 610 passed/0 failed · npm run build exit 0 · 5/5 critérios com evidência reproduzida pelo @qa.

## Objetivo

Nas "Perguntas para Reflexão" de um capítulo (visão do aluno, `ChapterReader`), a partir do
momento que o aluno inicia a sessão socrática numa pergunta, a escolha é PERSISTIDA na
sessão, as demais perguntas ficam anuladas de forma DURÁVEL (sobrevive a fechar o chat e a
recarregar a página) enquanto existir sessão ativa daquele conteúdo, e a pergunta escolhida
passa a oferecer "Retomar Sessão", que reabre a MESMA sessão com o histórico carregado,
nunca um diálogo novo. Sessão `completed` segue a regra SEC-CHAT-3 já existente: nova
tentativa libera as perguntas novamente.

Hoje o bloqueio é só estado local (`selectedQuestion`), que reseta no `closeChat` e no
reload, e a pergunta escolhida não é gravada em lugar nenhum, o aluno consegue reabrir a
mesma sessão com outra pergunta e misturar os diálogos.

## Pronto quando (critério verificável, rubrica ÚNICA do revisor)

1. **Pergunta persistida na sessão:** migração aditiva cria `chat_sessions.initial_question_text`
   (TEXT, nullable); `POST /chat-sessions` aceita o campo opcional, grava na criação e NUNCA
   sobrescreve valor não-nulo em resume (first write wins, mesmo que o request traga outra
   pergunta, a resposta devolve a pergunta armazenada).
   - Verificação: `grep -rn 'initial_question_text' supabase/migrations/ backend/routes_ai.py` → migração + rota; teste backend prova gravação e não-sobrescrita.
2. **Bloqueio durável no frontend:** no load do capítulo com perguntas,
   `frontend/src/views/courses/ChapterReader.tsx` hidrata via
   `chatSessionsApi.byContent(contentId)`; se existe sessão `active`, as outras perguntas
   ficam `disabled` e a escolhida (comparada pela `initial_question_text` da sessão) exibe
   "Retomar Sessão". Fechar o chat (`closeChat`) NÃO volta a liberar as outras perguntas
   enquanto a sessão estiver `active` (reverte parcialmente o comportamento do bug #21/H3).
   - Verificação: `grep -n 'byContent' frontend/src/views/courses/ChapterReader.tsx` → hidratação presente; `grep -n 'Retomar' frontend/src/views/courses/ChapterReader.tsx` → rótulo de resume.
3. **Retomada com histórico:** "Retomar Sessão" reabre a sessão existente carregando as
   mensagens via `GET /chat-sessions/{session_id}/messages`, sem chamar o kickoff socrático
   ("Quero explorar a seguinte questão") de novo e sem criar sessão nova.
   - Verificação: `grep -n 'getMessages' frontend/src/views/courses/ChapterReader.tsx` → usado no fluxo de resume; leitura do código confirma que o kickoff só roda em sessão recém-criada.
4. **Nova tentativa após completed:** com a sessão mais recente `completed`, as perguntas
   voltam a ficar habilitadas e iniciar outra pergunta cria sessão nova com a nova
   `initial_question_text` (contrato SEC-CHAT-3 preservado).
   - Verificação: teste backend cobrindo completed → nova sessão com pergunta diferente.
5. **Gates mecânicos verdes:**
   - `cd frontend && npm run build` (tsc -b && vite build) → exit 0
   - `cd backend && python -m pytest -q` → exit 0 (inclui os testes novos)

## Comandos de verificação literais

```bash
cd /Users/hugocapitelli/Dev/eximia/harven-ai-v2/frontend && npm run build
cd /Users/hugocapitelli/Dev/eximia/harven-ai-v2/backend && python -m pytest -q
grep -rn 'initial_question_text' /Users/hugocapitelli/Dev/eximia/harven-ai-v2/supabase/migrations/ /Users/hugocapitelli/Dev/eximia/harven-ai-v2/backend/routes_ai.py
grep -n 'byContent\|getMessages\|Retomar' /Users/hugocapitelli/Dev/eximia/harven-ai-v2/frontend/src/views/courses/ChapterReader.tsx
```

## Pilares do loop

- **Verifier:** rubrica acima (imutável durante o ciclo) + QA gate @qa.
- **State:** este arquivo + story SOC-1 (Change Log append-only).
- **Stop:** máx 3 iterações dev↔qa; depois escala ao Senhor (finops-guardrails).
