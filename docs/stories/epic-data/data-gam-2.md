---
id: DATA-GAM-2
epic: EPIC-DATA
phase: 4
status: Draft
severity: HIGH
terminal: Backend & Infra
complexity: low
depends_on: [DATA-GAM-1, SEC-ADMIN-4]
bug_refs: [15]
---
# DATA-GAM-2: Unlock de achievement idempotente — PK fresca + dedup por achievement_key

## Story
Como aluno da Harven.AI que conquista achievements ao progredir no curso, quero que o unlock de uma conquista seja idempotente e seguro sob concorrência, para que eu nunca receba erro 500 ao desbloquear uma conquista (mesmo em clique duplo) e o sistema nunca crie linhas duplicadas para a mesma conquista.

## Contexto (do bug sweep)
Bug #15 — O fluxo de unlock de achievement (gamificação) sofre de dois defeitos correlacionados:

1. **PK reutilizada / colisão de id:** o insert de achievement não gera uma primary key fresca de forma confiável (ex.: id derivado de valor reutilizado ou ausência de `gen_random_uuid()`/`DEFAULT` na coluna PK). Resultado: ao tentar desbloquear a MESMA conquista para **dois usuários distintos**, o segundo insert colide na PK e o backend retorna **HTTP 500** em vez de tratar como dois unlocks legítimos e independentes.
2. **Ausência de dedup por `achievement_key`:** não há constraint de unicidade nem tratamento de idempotência por `(user_id, achievement_key)`. Quando o **mesmo usuário** dispara o unlock duas vezes (clique duplo, retry de rede, double-submit), o sistema ou cria **linha duplicada** ou estoura erro, em vez de retornar `already_unlocked` de forma idempotente. Sob **concorrência** (duas requisições simultâneas para o mesmo `(user_id, achievement_key)`), nada garante que apenas 1 linha seja persistida.

Impacto: quebra da experiência de gamificação (500 visível ao aluno), dados de conquista inconsistentes (duplicatas), e fragilidade sob carga/retry. Severidade HIGH: afeta dado de produção e a confiabilidade do feature de gamificação.

> Arquivos prováveis (confirmar na implementação): rota/controller de unlock de achievement, repository/service de gamificação e a migration da tabela `achievements`/`user_achievements`. Caminhos exatos a serem validados pelo @dev no início da story (ver Dev Notes).

## Acceptance Criteria
- [ ] **Dois usuários distintos, mesma conquista:** unlock para `userA` e `userB` no mesmo `achievement_key` → ambos retornam sucesso, geram **ids distintos** (PK fresca por linha) e **nenhum HTTP 500** ocorre.
- [ ] **Mesmo usuário, duas vezes (idempotência):** segundo unlock do mesmo `(user_id, achievement_key)` retorna `already_unlocked` (sem erro), e a tabela contém **exatamente 1 linha** para esse par.
- [ ] **Concorrência:** duas requisições simultâneas de unlock para o mesmo `(user_id, achievement_key)` resultam em **exatamente 1 linha** persistida, garantida por **índice/constraint único** em `(user_id, achievement_key)` (race resolvida no nível do banco, não apenas em código).
- [ ] **PK fresca garantida:** a coluna PK da tabela de unlock usa `DEFAULT gen_random_uuid()` (ou geração de id equivalente no insert) de modo que nenhum insert reutilize id de outra linha.
- [ ] **Repository atualizado:** o método de unlock no repository/service trata a violação de unique constraint (ex.: `ON CONFLICT (user_id, achievement_key) DO NOTHING` / catch do erro `23505`) e mapeia para o desfecho `already_unlocked` em vez de propagar 500.
- [ ] **Sem confiar em input não verificado:** o `user_id` usado na escrita vem do contexto autenticado (sessão/token), **nunca** de `body.user_id` enviado pelo cliente.

## Tasks / Subtasks
- [ ] **Localizar o código tocado:** identificar a rota/controller de unlock (`grep -rn "achievement" backend/src --include="*.ts"` ou equivalente), o repository/service de gamificação e a migration da tabela de achievements.
- [ ] **Migration — PK fresca:** garantir que a coluna PK da tabela de unlock (`user_achievements` ou equivalente) tenha `DEFAULT gen_random_uuid()` (habilitar extensão `pgcrypto`/`uuid-ossp` se necessário) e que o insert não defina id manualmente a partir de valor reutilizado.
- [ ] **Migration — índice único de dedup:** criar `CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_user_achievement ON user_achievements (user_id, achievement_key);` (limpar duplicatas existentes antes, se houver, num passo idempotente da migration).
- [ ] **Repository — idempotência:** ajustar o método de unlock para usar `INSERT ... ON CONFLICT (user_id, achievement_key) DO NOTHING RETURNING *` (ou capturar erro `23505` do Postgres) e retornar contrato claro: `{ status: 'unlocked', id }` ou `{ status: 'already_unlocked' }`.
- [ ] **Controller — desfecho HTTP:** mapear `unlocked` → 200/201 com o id criado; `already_unlocked` → 200 (idempotente), nunca 500. Garantir que `user_id` venha da sessão autenticada (alinhado a SEC-ADMIN-4), não do body.
- [ ] **Testes de regressão:** escrever testes cobrindo os 4 cenários dos AC (dois users distintos; mesmo user 2x; concorrência simulada com Promise.all/duas conexões; verificação de id fresco).

## Dev Notes
- **Arquivos:** (confirmar paths reais no início da story)
  - Migration da tabela de achievements: `backend/migrations/*achievements*` (ou `supabase/migrations/`).
  - Repository/service de gamificação: provável `backend/src/.../gamification/*.repository.ts` / `*.service.ts`.
  - Controller/rota de unlock: provável `backend/src/.../gamification/*.controller.ts` (endpoint `POST /achievements/unlock` ou similar).
- **Abordagem:** Resolver os dois eixos do bug #15 no nível do banco (única fonte de verdade): (1) PK via `DEFAULT gen_random_uuid()` elimina a colisão de id entre usuários distintos; (2) `UNIQUE (user_id, achievement_key)` + `ON CONFLICT DO NOTHING` torna o unlock idempotente e seguro sob concorrência sem lock aplicacional. O código apenas traduz o resultado do banco em `unlocked` / `already_unlocked`. `user_id` SEMPRE do contexto autenticado.
- **Riscos de regressão / blast radius:** Toca a tabela `user_achievements` e seu repository — qualquer leitura de conquistas do aluno (perfil, dashboard de gamificação, ranking) depende da forma dessa tabela. O índice único pode falhar a migration se já existirem duplicatas em produção → incluir passo de dedup antes de criar o índice (usar `CREATE UNIQUE INDEX CONCURRENTLY` para evitar lock longo). Mudança de contrato de retorno (`already_unlocked`) deve ser compatível com o frontend consumidor — verificar callers do endpoint antes do merge.
- **Dependências:** DATA-GAM-1 (estrutura base da tabela de achievements) deve estar concluída; SEC-ADMIN-4 garante que o `user_id` autenticado é confiável (não derivado de input do cliente).

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde para os 4 cenários: dois users distintos (ids distintos, sem 500), mesmo user 2x (`already_unlocked`, 1 row), concorrência (1 row via índice), id fresco por linha.
- [ ] Sem regressão na suíte de segurança (`user_id` sempre do contexto autenticado, nunca do body).
- [ ] QA Gate: PASS ou CONCERNS.
- [ ] Migration idempotente e reversível: cria índice único `(user_id, achievement_key)`, garante `DEFAULT gen_random_uuid()` na PK, e remove duplicatas pré-existentes antes de criar o índice; aplicável a produção via `CONCURRENTLY` sem lock bloqueante.

## QA Results
_(a preencher pelo @qa)_
