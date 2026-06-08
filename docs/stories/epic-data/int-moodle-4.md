---
id: INT-MOODLE-4
epic: EPIC-DATA
phase: 4
status: Draft
severity: HIGH
terminal: Backend & Infra
complexity: high
depends_on: [INT-MOODLE-1, TPP-4]
bug_refs: [62]
---
# INT-MOODLE-4: Persistir handle LTI no launch + grade write-back na conclusão

## Story
Como aluno que acessa o tutor Harven.AI a partir de um curso Moodle via LTI, quero que minha nota ao concluir uma atividade seja devolvida automaticamente para o livro de notas do LMS, para que meu progresso no Moodle reflita o que efetivamente concluí no tutor — sem intervenção manual do professor.

## Contexto (do bug sweep)
Bug #62: o launch LTI valida o consumer e cria a sessão, mas **descarta o handle de outcome** (`lis_outcome_service_url`, `lis_result_sourcedid`, `oauth_consumer_key`) recebido no payload do launch. Como esses três valores nunca são persistidos, no momento da conclusão (`complete_chat_session`, `routes_ai.py:914-931`) não há como o backend localizar o serviço de outcomes do LMS nem assinar a chamada de devolução. Resultado: **a nota nunca volta para o Moodle** — o write-back de grade (LTI Basic Outcomes / `replaceResult`) é silenciosamente impossível.

Impacto: integração LTI funciona apenas "para dentro" (launch → sessão), mas é um beco sem saída "para fora" (conclusão → nota). Professores precisam lançar notas manualmente, anulando o propósito da integração e quebrando a expectativa de sincronização do gradebook. Roadmap (linha 253) confirma a forma da correção: nova tabela `lti_outcomes` com unique `(user_id, content_id)`, persistência no launch e write-back não-bloqueante na conclusão.

Coexistência crítica (linhas 131 e 330): `complete_chat_session` (`routes_ai.py:914-931`) é reformatado por **TPP** (que define o shape final do endpoint) e recebe hooks **aditivos** de SEC-CHAT-3, DATA-GAM-3/4 e desta story. Por isso `depends_on: [INT-MOODLE-1, TPP-4]` — esta story só entra **depois** da TPP estabilizar a assinatura/shape do `complete`, e reusa a base de launch/validação OAuth de INT-MOODLE-1. O hook de write-back é um add-on sobre a versão TPP, nunca uma reescrita concorrente.

## Acceptance Criteria
- [ ] Existe a tabela `lti_outcomes` com colunas mínimas: `id`, `user_id`, `content_id`, `outcome_service_url`, `result_sourcedid`, `consumer_key`, `created_at`, `updated_at`, e constraint **unique `(user_id, content_id)`** (upsert idempotente — relaunch da mesma atividade pelo mesmo usuário atualiza o handle, não duplica).
- [ ] No **launch LTI**, quando o payload contém `lis_outcome_service_url` + `lis_result_sourcedid` + `oauth_consumer_key`, esses três valores são persistidos (upsert) em `lti_outcomes` associados ao `(user_id, content_id)` da sessão. Launch **sem** handle de outcome (atividade não-graded) continua funcionando normalmente, sem erro e sem linha em `lti_outcomes`.
- [ ] `post_lti_grade(outcome_service_url, result_sourcedid, consumer_key, score)` monta o envelope XML `replaceResultRequest` do LTI Basic Outcomes, **assina via OAuth1** (reusando o helper/credenciais de INT-MOODLE-1, vetor de assinatura conhecido) e faz **POST via `httpx`** (cliente assíncrono, com timeout explícito) para o `outcome_service_url`. Sucesso é confirmado parseando o `imsx_codeMajor = success` da resposta.
- [ ] O `score` enviado é **normalizado para o intervalo `[0, 1]`** conforme exige o LTI Outcomes (clamp: valores <0 → 0, >1 → 1; conversão a partir da escala interna do tutor documentada no helper).
- [ ] Em `complete_chat_session` (versão **pós-TPP**, `routes_ai.py:914-931`), ao concluir a atividade o backend busca o handle em `lti_outcomes` por `(user_id, content_id)` e dispara o write-back de forma **não-bloqueante** (background task / fire-and-forget): a resposta de `complete` ao usuário NÃO espera, NÃO falha e NÃO sofre regressão de latência por causa do write-back. Falha no POST ao LMS é logada (warning/error estruturado), nunca propagada ao cliente.
- [ ] **`score == null` → skip honesto:** quando a sessão concluída não produz um score (ex.: atividade sem avaliação numérica, ou score indisponível), o write-back é **explicitamente pulado** — nenhuma chamada `replaceResult` com nota `0`/vazia é enviada ao LMS. O skip é logado com motivo (`score is None → skipping LTI grade write-back`), não silenciado.
- [ ] Atividade **sem handle persistido** em `lti_outcomes` (launch não-LTI ou sem outcome service) → `complete` pula o write-back sem erro (skip honesto análogo).

## Tasks / Subtasks
- [ ] Criar migration da tabela `lti_outcomes` (constraint unique `(user_id, content_id)`, índice implícito pela unique para o lookup do `complete`). Alinhar nome/local com as demais migrations da janela DATA (roadmap linha 354 lista `lti_outcomes` entre as tabelas novas).
- [ ] Adicionar modelo/repository `lti_outcomes` (SQLAlchemy/ORM do projeto) com método `upsert_outcome(user_id, content_id, outcome_service_url, result_sourcedid, consumer_key)` (ON CONFLICT em `(user_id, content_id)` → UPDATE) e `get_outcome(user_id, content_id)`.
- [ ] No handler de **launch LTI** (módulo de integração Moodle, mesmo módulo tocado por INT-MOODLE-1): extrair `lis_outcome_service_url`, `lis_result_sourcedid`, `oauth_consumer_key` do payload validado e chamar `upsert_outcome` quando os três estiverem presentes; não persistir nada quando ausentes.
- [ ] Implementar `post_lti_grade(...)` no módulo de integração LTI: montar XML `replaceResultRequest` com `result_sourcedid` + `resultScore` normalizado, assinar OAuth1 com o helper de INT-MOODLE-1, `POST` via `httpx.AsyncClient` com timeout; parsear `imsx_codeMajor` da resposta e retornar sucesso/falha.
- [ ] Implementar helper de normalização de score → `[0,1]` (clamp + conversão de escala) com testes unitários de borda (`-0.5→0`, `1.5→1`, `0.73→0.73`, `None→sentinel de skip`).
- [ ] Em `complete_chat_session` (`routes_ai.py:914-931`, **sobre a versão TPP**): adicionar hook aditivo que (1) busca `get_outcome(user_id, content_id)`; (2) se handle ausente → skip log; (3) se `score is None` → skip honesto log; (4) caso contrário → agendar `post_lti_grade` como background task não-bloqueante. NÃO alterar o shape de resposta definido por TPP.
- [ ] Logging estruturado dos três caminhos (success / skip-no-handle / skip-null-score / failure) para observabilidade da integração.

## Dev Notes
- **Arquivos:**
  - `backend/.../routes_ai.py` (função `complete_chat_session`, linhas ~914-931 — **editar sobre a versão TPP**, apenas hook aditivo)
  - Módulo de integração LTI/Moodle (mesmo onde INT-MOODLE-1 implementou launch + assinatura OAuth1) — adicionar `post_lti_grade` e persistência do handle no launch
  - Nova migration + modelo/repository `lti_outcomes`
  - Helper de normalização de score (no módulo LTI ou utils de scoring)
- **Abordagem:** Persistir no launch o handle de outcome (upsert idempotente por `(user_id, content_id)`); na conclusão, lookup + write-back assíncrono não-bloqueante. Reusar a infraestrutura OAuth1 de INT-MOODLE-1 (não reimplementar assinatura). Write-back é fire-and-forget: a UX de `complete` não pode regredir nem depender da disponibilidade do LMS. Score `None` e ausência de handle são caminhos de **skip honesto e logado**, nunca chamadas degradadas ao LMS.
- **Riscos de regressão:** `complete_chat_session` é alta concorrência de edições nesta janela (TPP define shape; SEC-CHAT-3, DATA-GAM-3/4 e esta story aplicam hooks aditivos — roadmap linhas 131/330). Blast radius: qualquer alteração no shape de resposta ou no fluxo síncrono do `complete` quebra TPP e as demais stories. Mitigação: entrar **depois** de TPP-4 (dependência declarada), manter o hook estritamente aditivo e o write-back fora do caminho síncrono (background task). A nova tabela `lti_outcomes` não toca tabelas existentes. `httpx` chamando o LMS introduz dependência de rede externa → timeout obrigatório + falha contida em log para não vazar erro 5xx ao cliente.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde
- [ ] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [ ] Migration `lti_outcomes` aplicada com unique `(user_id, content_id)` verificada; upsert idempotente comprovado por teste (relaunch não duplica)
- [ ] Teste cobrindo os 4 caminhos do `complete`: handle presente + score válido → `replaceResult` POST disparado com score em `[0,1]`; handle presente + `score null` → skip honesto logado, nenhum POST; sem handle → skip; falha de rede no LMS → logada e NÃO propagada ao cliente (resposta de `complete` inalterada)
- [ ] Write-back confirmado não-bloqueante (latência de `complete` não regride; resposta retorna antes/independente do POST ao LMS)
- [ ] Assinatura OAuth1 do `replaceResult` validada contra o vetor conhecido de INT-MOODLE-1
- [ ] Shape de resposta de `complete_chat_session` definido por TPP preservado (hook estritamente aditivo)

## QA Results
_(a preencher pelo @qa)_
