---
id: SEC-CHAT-5
epic: EPIC-SEC
phase: 2
status: Done
severity: CRITICAL
terminal: Backend & Infra
complexity: low
depends_on: [SEC-AUTHZ-0]
bug_refs: [2, 18]
---
# SEC-CHAT-5: ADR plano de migração RLS (doc only)

## Story
Como engenheiro de backend/segurança da Harven.AI, quero um ADR que documente formalmente por que o RLS está hoje inativo (cliente Supabase único com `service_role`) e qual é o caminho de migração para isolamento real (cliente por-request com JWT do usuário), para que toda decisão de autorização futura seja rastreável, evitando que alguém adicione políticas RLS achando que elas terão efeito (no-op) e firmando que as guards de aplicação (SEC-AUTHZ-0) são hotfix temporário, não a arquitetura-alvo.

## Contexto (do bug sweep)
O bug sweep documentou que **a camada de autorização da aplicação é a única barreira de isolamento entre tenants/usuários — não há nenhuma política RLS no schema**, e o cliente Supabase agrava isso:

- **Bug #2 (IDOR generalizado em chat-sessions)** — `BUG-SWEEP-2026-06-03.md` linhas 39-45. O cliente Supabase é **único, compartilhado, com `SUPABASE_KEY` estática que decodifica para `service_role`** — ou seja, **bypassa RLS por construção**. Evidência no código: `backend/database.py:6` lê `SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")`, e `backend/database.py:10-11` cria um cliente global `supabase = create_client(SUPABASE_URL, SUPABASE_KEY)`, exposto via `get_supabase()` (`backend/database.py:14`). Como toda query usa essa mesma conexão privilegiada, **qualquer política RLS adicionada ao schema seria no-op**. O relatório também registra a recomendação de longo prazo: "RLS com cliente Supabase por-usuário" (linha 45).
- **Bug #18 (IDOR em gamificação)** — `BUG-SWEEP-2026-06-03.md` linha 197. Confirma o mesmo mecanismo: "O service_role bypassa RLS", reforçando que o problema é arquitetural e sistêmico, não pontual.
- **Convenção de migrations** — `REMEDIATION-ROADMAP-2026-06-03.md` linha 343 já proíbe novas políticas RLS justamente porque "seria no-op com client service_role — documentado em ADR SEC-CHAT-5". Este story produz exatamente esse ADR referenciado.

**Impacto:** Sem este ADR, há risco real de regressão de governança — um dev futuro pode (a) adicionar políticas RLS que dão falsa sensação de segurança sem efeito algum, ou (b) remover as guards de aplicação de SEC-AUTHZ-0 achando que o RLS cobre. O ADR fecha esse gap documental e marca o estado atual como hotfix consciente.

## Acceptance Criteria
- [x] Existe um arquivo ADR versionado (ex.: `docs/adr/ADR-001-rls-migration-plan.md`) com status, data, autor e contexto.
- [x] O ADR **explica por que o RLS é no-op hoje**, citando explicitamente `backend/database.py:10-11` (cliente único `create_client(SUPABASE_URL, SUPABASE_KEY)`) e o fato de `SUPABASE_KEY` decodificar para `service_role`, que bypassa toda política RLS.
- [x] O ADR **lista as tabelas-alvo** que precisarão de RLS na migração (no mínimo: `chat_sessions`, `chat_messages`, `notifications`, e as tabelas de gamificação — reais no schema: `user_activities`/`user_achievements`/`certificates`/`course_progress`/`user_stats`), com a coluna de posse (`user_id`) usada como predicado.
- [x] O ADR **descreve o caminho-alvo "cliente por-request com JWT do usuário"**: cada request cria/usa um cliente Supabase com o JWT do usuário autenticado (em vez do `service_role` global), de modo que o `auth.uid()` do Postgres passe a refletir o usuário e as políticas RLS passem a ter efeito; descreve override TEACHER/ADMIN.
- [x] O ADR **marca as guards de aplicação (helpers de SEC-AUTHZ-0) como "hotfix shipped"** — barreira temporária e atual, não a arquitetura final — e estabelece a regra: enquanto o cliente for `service_role`, **NÃO** adicionar políticas RLS ao schema (elas seriam no-op).
- [x] O ADR registra o desfecho de autorização esperado pós-migração para queries com posse (alinhado a SEC-AUTHZ-0): **dono autorizado passa**; **ator cruzado recebe 403/404 e nenhuma leitura/mutação ocorre**; **`body.user_id` nunca é confiado** (sempre usar a identidade autenticada do JWT) — referenciando o achado de `create_or_get_chat_session` (`uid = data.user_id or current_user["id"]`, bug #2).
- [x] **Story doc-only:** nenhuma alteração em código de produção, schema ou migrations é feita neste story.

## Tasks / Subtasks
- [x] Confirmar o estado atual lendo `backend/database.py:1-20` (cliente único service_role) e `backend/config.py` (`SUPABASE_URL`/`SUPABASE_KEY` em :20-21, `JWT_SECRET_KEY` em :28 — line refs reais citados no ADR) para citar file:line corretos no ADR.
- [x] Levantar a lista real de tabelas com coluna de posse a partir das rotas afetadas (`backend/routes_ai.py`, `backend/routes_admin.py` e demais que usam `get_supabase()`), para preencher a seção "tabelas-alvo".
- [x] Criar diretório `docs/adr/` (se não existir) e escrever `docs/adr/ADR-001-rls-migration-plan.md` com as seções: Status, Contexto, Decisão (por que no-op hoje), Tabelas-alvo, Caminho de migração (cliente por-request JWT), Hotfix atual (helpers SEC-AUTHZ-0), Consequências, Regra de proibição de RLS no-op.
- [x] Adicionar referência cruzada: linkar o ADR de volta ao `REMEDIATION-ROADMAP-2026-06-03.md` linha 343 e ao story SEC-AUTHZ-0. (Bidirecional: roadmap linha 343 agora linka o arquivo do ADR.)
- [ ] Validar com o time Backend & Infra que a lista de tabelas-alvo e a estratégia de JWT por-request estão tecnicamente corretas (revisão de doc). _(pendente — revisão humana no QA gate)_

## Dev Notes
- **Arquivos:** (novo) `docs/adr/ADR-001-rls-migration-plan.md`; (leitura/evidência, sem edição) `backend/database.py` (linhas 1-20, cliente global service_role), `backend/config.py` (linhas 11-15, keys), `backend/routes_ai.py`, `backend/routes_admin.py`, `BUG-SWEEP-2026-06-03.md` (itens #2 e #18), `REMEDIATION-ROADMAP-2026-06-03.md` (linha 343).
- **Abordagem:** Story 100% documental. O ADR registra a decisão arquitetural — não muda comportamento. Núcleo técnico a documentar: hoje `backend/database.py` instancia **um** cliente global com `SUPABASE_KEY` (service_role) e o reusa via `get_supabase()`; como service_role bypassa RLS, qualquer `CREATE POLICY` no schema é inerte. O caminho-alvo troca o cliente global por um cliente criado por-request usando o `access_token` (JWT) do usuário autenticado, fazendo `auth.uid()` refletir o usuário no Postgres e habilitando políticas RLS reais; até lá, os helpers de autorização de aplicação (SEC-AUTHZ-0) são a barreira efetiva e devem ser tratados como hotfix shipped.
- **Riscos de regressão:** Nenhum risco de runtime — não há mudança de código nem de schema. **Blast radius do tema (não da edição):** todo consumidor de `get_supabase()` em `backend/routes_ai.py` e `backend/routes_admin.py` depende hoje do bypass service_role; o ADR apenas governa decisões futuras. Risco principal é **documental/de governança**: ADR incompleto ou ambíguo poderia levar alguém a adicionar RLS no-op ou a remover as guards de SEC-AUTHZ-0 prematuramente — mitigado pelos AC que exigem a regra explícita de "não adicionar RLS enquanto o cliente for service_role" e a marcação de hotfix.

## Definition of Done
- [x] Teste de regressão (falha-antes / passa-depois) verde — N/A para conteúdo executável (story doc-only); substituído por verificação de que o arquivo ADR existe e satisfaz todos os AC (checklist de conteúdo acima, todos `[x]`).
- [x] Sem regressão na suíte de segurança — garantido por construção: nenhum código/schema alterado; suíte de segurança rodada para confirmar baseline inalterado (257 passed).
- [ ] QA Gate: PASS ou CONCERNS. _(a preencher pelo @qa)_
- [ ] ADR revisado e aprovado pelo terminal Backend & Infra, com referência cruzada bidirecional ao roadmap (linha 343) e ao story SEC-AUTHZ-0, e a lista de tabelas-alvo validada contra o schema real. _(referências bidirecionais escritas; aprovação humana pendente)_

## Dev Agent Record

**Agent:** Dex (@dev) · **Date:** 2026-06-04 · **Label:** guards

### Files changed (doc-only — ZERO code/schema/migration changes)
- **NEW** `docs/adr/ADR-001-rls-migration-plan.md` — full ADR: Status/Date/Authors, Context (why RLS is no-op today with precise live line refs `database.py:5,10-11,14` + `config.py:20-21,28`), Decision (no RLS while service_role), Target tables (10 ownership-bearing tables with `user_id = auth.uid()` predicates, drawn from live route queries), Migration path (per-request JWT client, 4 sequenced steps), Hotfix section (SEC-AUTHZ-0 helpers = shipped temporary barrier + governance rules), Expected authz outcome (3-outcome contract incl. body.user_id never trusted, citing bug #2 `uid = data.user_id or current_user["id"]`), Consequences, bidirectional Cross-references.
- **EDIT** `docs/REMEDIATION-ROADMAP-2026-06-03.md` line 343 — turned the bare "ADR SEC-CHAT-5" mention into a clickable link to the ADR file (completes the bidirectional reference required by the DoD). Doc-only.

### Key decisions
- **[FINDING]** The AC referenced `config.py:11-15` for the keys, but those lines actually hold `WEAK_JWT_SECRETS`/`MIN_JWT_SECRET_LENGTH`. Cited the *real* current lines (`SUPABASE_URL/KEY` at :20-21, `JWT_SECRET_KEY` at :28) so the ADR stays accurate as a forensic record.
- **[FINDING]** Real schema gamification tables are `user_activities`/`user_achievements`/`certificates`/`course_progress`/`user_stats` (not `activities`/`content_progress` as the AC approximated) — verified by grepping `.table("...")` calls; ADR lists the real names.

### Verification (doc-only story — no executable regression)
- ADR exists and satisfies all 7 AC (content checklist above).
- Security suite re-run to confirm baseline unchanged: **257 passed** (no code/schema touched).

## QA Results

**Gate: PASS** — @qa (Quinn), 2026-06-04 (adversarial security review)

Cluster: **chat**. Covered by the chat IDOR regression suite and the happy-path caller suite. The 3-outcome contract holds across all chat-session surfaces; no false-green tests detected (cross-actor tests assert absence of victim content/PII and an empty mutation log).

Tests: full suite **257 passed, 0 failed**.
