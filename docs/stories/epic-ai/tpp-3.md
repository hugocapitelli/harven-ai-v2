---
id: TPP-3
epic: EPIC-AI
phase: 3
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: medium
depends_on: [TPP-1, ASYNC-AI-1]
bug_refs: [40]
---
# TPP-3: Centralizar persistência + count atômico em `chat_repo`

## Story
Como engenheiro de backend responsável pela integração do tutor de IA, quero centralizar toda a persistência de turnos de chat no `ChatRepo` com incremento atômico do contador de mensagens e I/O não-bloqueante, para que `chat_sessions.total_messages` reflita sempre a contagem real, os analytics (avg_messages) parem de derivar e o event loop do FastAPI não seja bloqueado por chamadas síncronas ao Supabase.

## Contexto (do bug sweep)
Item #40 — `total_messages` atualizado com read-modify-write não atômico → lost updates (CRITICAL, Estado de Sessão / Concorrência).

- `backend/routes_ai.py:874-877` (`add_session_message`): lê `total_messages` (`session.get("total_messages")`), computa `+1` em Python e regrava via `update`. Não há incremento atômico — sob concorrência, dois turnos podem ler o mesmo valor e gravar o mesmo `+1`, perdendo updates.
- **Defeito mais confiável (do impacto):** o contador diverge sistematicamente porque mensagens são inseridas/omitidas por caminhos que NÃO rodam este incremento — o frontend só persiste mensagens `role='user'`, nunca `assistant`. Logo, mesmo sem concorrência, `total_messages` fica abaixo da contagem real de rows em `chat_messages`.
- `backend/repositories/chat_repo.py:42-45` (`ChatRepo.add_message`): insere a row em `chat_messages` mas **não** incrementa `total_messages` — a contagem vive apenas na rota, fora do repositório, gerando duas fontes de verdade divergentes.
- `backend/repositories/chat_repo.py:47-55` (`get_session_messages`): ordena só por `created_at`, sem tiebreaker — empates de microssegundo entre turnos user/instrutor podem reordenar a transcrição/export (defeito correlato citado no relatório).
- Todos os métodos do `ChatRepo` (`add_message`, `get_session_messages`, etc.) e a rota `add_session_message` chamam o cliente Supabase de forma **síncrona** (`.execute()`) dentro de handlers `async`, bloqueando o event loop (alinha com ASYNC-AI-1).

**Impacto:** `chat_sessions.total_messages` deriva abaixo da contagem real; `avg_messages` e demais analytics ficam errados. As mensagens em si são armazenadas corretamente — apenas o contador e a ordenação derivam. Registro acadêmico apresenta métricas materialmente imprecisas.

## Acceptance Criteria
- [x] `chat_repo.persist_turn(session_id, message)` insere exatamente **1 row** em `chat_messages` e incrementa `total_messages` **atomicamente** via RPC `increment_chat_session_messages` (fallback guarded quando RPC ausente) — sem read-modify-write em Python no caminho RPC. _(`test_persist_turn_inserts_one_and_increments_via_rpc`.)_
- [x] `persist_turn` é o **único** incrementador: `add_message` agora é alias de `persist_turn` (`test_add_message_alias_routes_through_persist_turn`); a rota não escreve `total_messages` inline.
- [x] `add_session_message` (rota) roteia toda a persistência por `persist_turn` — o bloco `new_count = ... + 1` + `update` foi removido.
- [x] Existe `chat_repo.count_user_messages(session_id)` retornando a contagem real de turnos `role='user'` (`test_count_user_messages_counts_only_user_role`) — fonte canônica para analytics e para a derivação de pacing (TPP-5).
- [x] I/O do `ChatRepo` é **não-bloqueante** nos handlers `async`: a rota usa `run_in_threadpool(repo.persist_turn / get_session_messages)`; `socratic_dialogue` idem (ASYNC-AI-1).
- [x] Concorrência: `persist_turn` simultâneos na mesma sessão → `total_messages` += N exato via RPC atômico (`test_concurrent_persist_turn_counts_exactly_n_with_rpc`).
- [x] `get_session_messages` ordena por `(created_at, sequence, id)` — tiebreaker estável (`test_get_session_messages_stable_order_with_sequence_tiebreak`).

## Tasks / Subtasks
- [ ] Em `backend/repositories/chat_repo.py`: criar método `persist_turn(self, session_id, message_data)` que (a) chama `add_message` para inserir 1 row e (b) dispara o incremento atômico do contador (RPC/trigger). Tornar `add_message` interno/privado ou garantir que ele não seja chamado fora de `persist_turn` para persistência de turno.
- [ ] Adicionar `count_user_messages(self, session_id)` em `chat_repo.py` retornando a contagem real (`select count` ou len das rows) — espelhando a derivação já usada pelo organizer.
- [ ] Implementar o incremento atômico: criar RPC Supabase `increment_session_messages(session_id)` (`UPDATE ... SET total_messages = total_messages + 1`) ou trigger `AFTER INSERT ON chat_messages`; documentar a migration em `backend/` (migrations/supabase).
- [ ] Em `backend/routes_ai.py:848-881` (`add_session_message`): substituir o bloco `new_count = ... + 1` + `update(...)` (linhas 874-877) por uma única chamada a `chat_repo.persist_turn(...)`. Manter a verificação de existência da sessão e o tratamento de erro 404/500.
- [ ] Garantir não-bloqueio: envolver as chamadas síncronas do `ChatRepo` (e da RPC) em `run_in_threadpool`/`to_thread` ou migrar para cliente async, conforme padrão estabelecido em ASYNC-AI-1.
- [ ] Em `chat_repo.py:47-55` (`get_session_messages`): adicionar tiebreaker estável na ordenação (`.order("created_at").order("id")` ou coluna de sequência).
- [ ] Atualizar quaisquer outros chamadores que persistem mensagens (ex.: persistência server-side de turno do assistente, dependente de TPP-4) para rotear por `persist_turn`.

## Dev Notes
- **Arquivos:** `backend/repositories/chat_repo.py` (classe `ChatRepo`: `add_message` L42-45, `get_session_messages` L47-55 — adicionar `persist_turn`, `count_user_messages`); `backend/routes_ai.py` (`add_session_message` L848-881, especialmente o incremento L874-877); migration Supabase para a RPC/trigger de incremento atômico.
- **Abordagem:** Mover a responsabilidade de "persistir turno + contar" para dentro do `ChatRepo`, expondo `persist_turn` como ponto único de escrita. O incremento deixa de ser read-modify-write em Python e passa a ser uma operação atômica no banco (RPC ou trigger), eliminando lost updates e a divergência por caminhos que pulam o contador. `count_user_messages` fornece a contagem canônica derivável on-read para analytics e reconciliação. I/O segue o padrão não-bloqueante de ASYNC-AI-1.
- **Riscos de regressão:** `add_session_message` é o endpoint público de gravação de mensagens chamado pelo frontend do chat (hoje só persiste turnos `user`). Mudar o contrato de contagem afeta `total_messages` lido por analytics admin (`avg_messages`, dashboards). TPP-4 depende deste centralizador para persistir o turno do assistente server-side — `persist_turn` deve estar estável antes. Blast radius: rota `add_session_message`, todo consumidor de `chat_sessions.total_messages`, e qualquer service que insira em `chat_messages` fora do repo (deve ser redirecionado). Atenção: a migration de trigger/RPC roda em produção — validar que o incremento não dispara em dobro (trigger + RPC ao mesmo tempo seria double-count).

## Definition of Done
- [x] Teste de regressão verde: N turnos via `persist_turn` (incl. `assistant`) → `total_messages == N` (`test_persist_turn_increments_via_fallback_when_no_rpc`); concorrência → +N exato (`test_concurrent_persist_turn_counts_exactly_n_with_rpc`).
- [x] Sem regressão na suíte de segurança (323 verdes; endpoints de chat seguem ownership-scoped; nenhum caminho confia em `body.user_id`).
- [x] QA Gate: PASS ou CONCERNS.
- [x] `persist_turn` é o único incrementador (rota não tem mais `total_messages + 1` inline; grep confirma); `get_session_messages` com tiebreaker `(created_at, sequence, id)`; I/O do repo via `run_in_threadpool`.

## Dev Agent Record

**Agent:** Dex (@dev) · **Date:** 2026-06-05 · **Status:** Ready for Review

**Files changed:**
- `backend/repositories/chat_repo.py` — added `persist_turn` (insert + atomic increment, single write path), `count_user_messages` (real `role='user'` count), `_insert_message`/`_increment_total_messages` internals (RPC-first, guarded fallback). `get_session_messages` now orders `(created_at, sequence, id)`. `add_message` is a backwards-compat alias of `persist_turn` so no path skips the counter.
- `backend/routes_ai.py` — `add_session_message` routes through `run_in_threadpool(ChatRepository(client).persist_turn, ...)`; removed the inline `total_messages + 1`. `get_chat_session` / `get_session_messages` / `export_session_moodle` read via `ChatRepository.get_session_messages` (stable order).
- `backend/tests/fakes.py` — `.rpc(rpc_enabled=...)` + multi-key `.order()` to test both the atomic-RPC and the non-RPC fallback paths and the ordering tiebreaker.
- `backend/tests/test_tutor_persistence.py` — `TestTpp3ChatRepo` (6 tests).

**Notes / decisions:**
- `[AUTO-DECISION]` `_increment_total_messages` falls back to a guarded read-then-update when `client.rpc` is absent (un-migrated DB / in-memory fake). Reason: never sacrifice the message insert; a lagging counter is recoverable, lost messages are not. Once migration B is applied in prod, the atomic RPC path is taken and lost-updates are eliminated.

**Tests:** full suite `323 passed`. TPP-3-specific: 6/6 pass.

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-05 (re-review after delivery; supersedes the earlier FAIL, which looked for `backend/chat_repo.py` — the file is `backend/repositories/chat_repo.py`).

Verified in `repositories/chat_repo.py`:
- `persist_turn` is the single write path: `_insert_message` (1 row) + `_increment_total_messages` (RPC `increment_chat_session_messages` first; guarded read-then-update fallback only when `.rpc` is absent). `add_message` is now an alias of `persist_turn`, so no path can insert a message while skipping the counter.
- `count_user_messages` returns the real `role='user'` count (canonical for analytics + TPP-5 pacing), derived on-read — never trusting `total_messages`.
- `get_session_messages` orders `(created_at, sequence, id)` — stable tiebreaker (no microsecond reorder).
- `routes_ai.add_session_message` routes through `run_in_threadpool(ChatRepository(client).persist_turn, ...)`; the inline `total_messages + 1` is gone (confirmed by grep). Read paths use the repo's ordered transcript.

Tests: `TestTpp3ChatRepo` (6) green — incl. atomic-RPC path, non-RPC fallback, concurrent `persist_turn` counting exactly N, user-role-only count, and stable-order tiebreak. The `_increment_total_messages` fallback is intentionally non-atomic (documented `[AUTO-DECISION]`): correctness of the insert is never sacrificed; a lagging counter is recoverable. Once migration B is applied in prod, the atomic RPC path is taken and lost-updates (#40) are eliminated.
