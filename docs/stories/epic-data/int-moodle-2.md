---
id: INT-MOODLE-2
epic: EPIC-DATA
phase: 4
status: Draft
severity: HIGH
terminal: Backend & Infra
complexity: medium
depends_on: [INT-MOODLE-1]
bug_refs: [11]
---
# INT-MOODLE-2: export_sessions_to_moodle envia de fato + status veraz

## Story
Como instrutor/administrador que sincroniza o aprendizado dos alunos com o Moodle, quero que `export_sessions_to_moodle` realmente escreva cada sessão como entrada de portfólio no Moodle e só marque `moodle_export_id` após confirmação remota, para que o status do job (success/partial/failed) reflita a realidade e eu possa confiar nos contadores antes de assumir que os dados foram entregues.

## Contexto (do bug sweep)
Item #11 — `export_sessions_to_moodle` (cluster `moodle-export-truth`, EPIC-DATA, fase 4): a função de export hoje **não chama de fato o write remoto** por sessão e/ou marca `moodle_export_id` antes de qualquer confirmação do Moodle. O resultado é um job que reporta `success` mesmo quando nada foi gravado no LMS — um caso clássico de status mentiroso (silent failure): o `integration_log` indica sucesso, o registro local ganha um `moodle_export_id` fantasma, mas o portfólio do aluno no Moodle continua vazio. Não há distinção entre "exportado e confirmado", "falhou e é retryable" e "sem mapping de curso/usuário". Sessões sem mapping de destino são tratadas como sucesso silencioso em vez de falha rastreável, e os contadores (`records_exported` / `records_failed`) não são persistidos de forma íntegra em `integration_logs`. Depende de INT-MOODLE-1, que estabelece o cliente Moodle / `create_portfolio_entry` confiável a ser consumido por esta story.

## Acceptance Criteria
- [ ] Para cada sessão elegível, `export_sessions_to_moodle` invoca `create_portfolio_entry` (cliente Moodle de INT-MOODLE-1) com os campos reais da sessão — uma chamada de write remoto por sessão, sem stub/no-op.
- [ ] `moodle_export_id` (no registro da sessão / tabela de export) só é gravado **após** o write remoto retornar confirmação positiva do Moodle (id remoto válido). Nenhum id é setado especulativamente antes da resposta.
- [ ] Falha de write remoto (timeout, erro HTTP, exceção do cliente) → a sessão conta em `records_failed`, `moodle_export_id` permanece NULL, e o registro fica em estado **retryable** (próxima execução reprocessa essa sessão).
- [ ] Sessão sem mapping de curso/usuário (sem destino resolvível no Moodle) → marcada como **failed** com razão explícita registrada (ex.: `reason="no_course_mapping"`), conta em `records_failed`, e **não** é tratada como sucesso silencioso.
- [ ] Status final do job é veraz: `success` apenas se todas as sessões elegíveis foram confirmadas; `partial` se houve mistura de confirmadas e falhas; `failed` se nenhuma foi confirmada (ou erro global).
- [ ] `integration_logs` persiste os contadores reais ao fim do job: `records_exported` (confirmados) e `records_failed`, com o status veraz acima — nada de contadores zerados ou status hardcoded como sucesso.

## Tasks / Subtasks
- [ ] Localizar `export_sessions_to_moodle` no backend (provável `backend/app/services/moodle_export*.py` ou `integration`/`tasks`) e identificar a query de sessões elegíveis.
- [ ] Substituir qualquer write fake/no-op pela chamada real ao `create_portfolio_entry` do cliente Moodle entregue por INT-MOODLE-1, passando os campos reais da sessão (curso, usuário/aluno mapeado, conteúdo do portfólio).
- [ ] Resolver o mapping curso/usuário → destino Moodle antes do write; quando ausente, curto-circuitar a sessão como `failed` com `reason` e contabilizar em `records_failed`.
- [ ] Mover a gravação de `moodle_export_id` para **depois** do retorno confirmado do write remoto; em caso de exceção/erro, não gravar id e manter a sessão retryable.
- [ ] Acumular contadores `records_exported` e `records_failed` ao longo do loop e derivar o status final (`success`/`partial`/`failed`).
- [ ] Persistir os contadores e o status veraz em `integration_logs` ao fim do job (uma entrada por execução).
- [ ] Adicionar teste de regressão cobrindo: confirmação seta id; falha de write → records_failed + id NULL + retryable; ausência de mapping → failed com razão; derivação de status partial.

## Dev Notes
- **Arquivos:** `backend/app/services/moodle_export*.py` (função `export_sessions_to_moodle` e o cliente/`create_portfolio_entry` de INT-MOODLE-1); modelo/tabela de export de sessões (campo `moodle_export_id`); modelo `integration_logs`; testes em `backend/tests/` (suite de integração Moodle).
- **Abordagem:** transformar o export num loop transacional por sessão — resolver destino → write remoto → confirmar → só então persistir `moodle_export_id`. Tratar três desfechos por sessão (confirmada / falha retryable / sem mapping) e agregá-los em contadores que alimentam um status derivado, não hardcoded. A unidade de verdade é a confirmação remota, não a intenção de exportar.
- **Riscos de regressão:** o blast radius é o cluster `moodle-export-truth` (#11/#41) e quem dispara o job de export (scheduler/endpoint de integração que chama `export_sessions_to_moodle`). Depende diretamente de INT-MOODLE-1 (cliente Moodle / `create_portfolio_entry`) — não iniciar antes de INT-MOODLE-1 estar mergeado. Mudança no semântica de `moodle_export_id` pode afetar consultas que assumem que id != NULL significa "exportado"; verificar se algum dashboard/relatório lê esse campo. A introdução de estado retryable não deve causar reexportação dupla de sessões já confirmadas (idempotência garantida por `moodle_export_id` não-nulo como guard).

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde
- [ ] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [ ] Verificado manualmente (ou via teste com cliente Moodle mockado) que: write remoto é de fato chamado por sessão; `moodle_export_id` só aparece após confirmação; falha → `records_failed` + id NULL + reprocessável; sem mapping → `failed` com razão; `integration_logs` registra counts e status veraz (success/partial/failed) consistentes com o que foi efetivamente gravado no Moodle.

## QA Results
_(a preencher pelo @qa)_
