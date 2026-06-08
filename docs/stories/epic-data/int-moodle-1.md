---
id: INT-MOODLE-1
epic: EPIC-DATA
phase: 4
status: Draft
severity: HIGH
terminal: Backend & Infra
complexity: low
depends_on: []
bug_refs: [41]
---
# INT-MOODLE-1: Mapeamento de campos veraz em prepare_moodle_export

## Story
Como integrador da plataforma Harven.AI com o Moodle, quero que a função `prepare_moodle_export` mapeie os campos de sessão de forma veraz (a partir dos dados reais persistidos, sem valores hardcoded), para que o portfólio/gradebook do Moodle reflita o desempenho e os sinais de detecção reais do aluno, e não placeholders enganosos.

## Contexto (do bug sweep)
O item #41 do bug sweep documenta que `prepare_moodle_export` produz um payload de exportação com **mapeamento de campos falso/incorreto**, comprometendo a veracidade dos dados enviados ao Moodle:

- **`started_at` ausente ou inconsistente:** o campo de início da sessão não é derivado corretamente da origem real. O timestamp de início deve vir de `started_at` quando presente e cair para `created_at` como fallback — hoje a função não garante esse encadeamento, resultando em datas vazias ou erradas no portfólio.
- **`score.raw` hardcoded como 0:** quando `performance_score` não existe na sessão, a função emite `0` em vez de `null`. Um `0` falso é interpretado pelo Moodle como "nota zero" (aluno reprovado/sem desempenho), quando o correto é "sem nota disponível". Isso corrompe o gradebook.
- **Métricas de detecção de IA hardcoded:** sinais de detecção (ex.: probabilidade de IA, flags, evidências) são emitidos com valores fixos `0.0` / `[]` em vez dos valores reais de detecção ou de serem omitidos quando não há detecção computada. Isso comunica falsamente "0% de suspeita de IA" mesmo quando nenhuma análise foi feita.
- **Inconsistência entre callers:** a função é consumida por mais de um caller (notadamente o fluxo de `export_sessions_to_moodle` — INT-MOODLE-2 — e outros consumidores diretos), e o shape atual divergente propaga os dados falsos a todos eles.

**Impacto:** dados de avaliação enganosos no Moodle (notas zero falsas, datas ausentes, "ausência de suspeita de IA" falsa), violando a confiabilidade pedagógica e de integridade acadêmica da integração. Severidade HIGH.

## Acceptance Criteria
- [ ] `started_at` no payload exportado é derivado de `session.started_at` quando presente; quando ausente, faz fallback para `session.created_at`. Nunca emite string vazia ou `None` se ao menos um dos dois existir.
- [ ] `score.raw` recebe `performance_score` real da sessão; quando `performance_score` é ausente/`None`, `score.raw` é `null` (e NÃO `0`). Um score `0` legítimo (aluno realmente tirou 0) continua sendo enviado como `0`.
- [ ] Métricas de detecção de IA são derivadas dos valores reais de detecção da sessão; quando não há detecção computada, os campos são **omitidos** do payload (não enviados com `0.0` ou `[]` hardcoded). Nenhum valor de detecção é fabricado.
- [ ] O shape corrigido é retornado de forma idêntica para **todos os callers** de `prepare_moodle_export` — verificado que `export_sessions_to_moodle` e qualquer outro consumidor direto recebem o mesmo dicionário corrigido (sem ramos divergentes).
- [ ] Nenhum campo do payload usa valor literal hardcoded como substituto de dado ausente (auditar a função: toda chave reflete dado real ou é omitida/`null`).

## Tasks / Subtasks
- [ ] Localizar a definição de `prepare_moodle_export` (provável `app/services/integrations/moodle.py` ou módulo equivalente em `app/integrations/`) e mapear o objeto `session` de entrada (campos `started_at`, `created_at`, `performance_score`, e os campos de detecção de IA disponíveis no modelo de sessão).
- [ ] Corrigir o mapeamento de `started_at`: `session.started_at or session.created_at` (com guarda para o caso de ambos ausentes → omitir ou `null` explícito).
- [ ] Corrigir `score.raw`: emitir `performance_score` quando presente; emitir `null` (não `0`) quando ausente. Garantir que `0` legítimo seja preservado (distinguir `None` de `0`).
- [ ] Substituir as métricas de detecção de IA hardcoded (`0.0`, `[]`) por leitura dos campos reais de detecção; quando não houver dado, **não incluir a chave** no payload.
- [ ] Identificar todos os callers de `prepare_moodle_export` (grep por `prepare_moodle_export(`) e confirmar que cada um consome o dict corrigido sem reprocessar/sobrescrever os campos.
- [ ] Adicionar/ajustar teste de regressão cobrindo: sessão com `started_at` ausente (fallback p/ `created_at`); sessão sem `performance_score` (→ `score.raw == None`); sessão com `performance_score == 0` (→ `score.raw == 0`); sessão sem detecção de IA (→ chaves de detecção ausentes do payload).

## Dev Notes
- **Arquivos:** função `prepare_moodle_export` no módulo de integração Moodle do backend (provável `app/services/integrations/moodle.py` / `app/integrations/moodle.py` — confirmar via grep `def prepare_moodle_export`); callers incluem o fluxo `export_sessions_to_moodle` (alvo de INT-MOODLE-2). Modelo de sessão (`Session` ORM) como fonte dos campos `started_at`, `created_at`, `performance_score` e métricas de detecção.
- **Abordagem:** mudança localizada e puramente de mapeamento — sem alteração de schema, sem migração. Aplicar o princípio "dado real ou omitido/`null`, nunca hardcoded". Cuidado especial para distinguir `None` (ausente) de `0` (valor legítimo) no `score.raw`, usando checagem explícita `is None` em vez de truthiness.
- **Riscos de regressão:** blast radius restrito aos consumidores de `prepare_moodle_export`. O caller principal `export_sessions_to_moodle` depende deste shape (INT-MOODLE-2 está bloqueado por esta story — `depends_on: [INT-MOODLE-1]`), portanto a mudança de contrato (notadamente `score.raw` agora podendo ser `null` e chaves de detecção podendo estar ausentes) deve ser absorvida sem quebra no consumo downstream e no payload enviado ao Moodle. Verificar serialização (Pydantic/dict→JSON) para que `null` e chaves omitidas sejam aceitos pelo endpoint do Moodle.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde cobrindo os 4 cenários de mapeamento (fallback de `started_at`, `score.raw == None`, `score.raw == 0`, omissão de detecção de IA)
- [ ] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [ ] Auditoria confirma que `prepare_moodle_export` não contém nenhum valor de campo hardcoded como substituto de dado ausente, e que todos os callers recebem o shape corrigido idêntico

## QA Results
_(a preencher pelo @qa)_
