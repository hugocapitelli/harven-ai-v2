---
id: INT-MOODLE-3
epic: EPIC-DATA
phase: 4
status: Draft
severity: HIGH
terminal: Backend & Infra
complexity: low
depends_on: []
bug_refs: [62]
---
# INT-MOODLE-3: Validar payload do rating webhook antes do insert

## Story
Como mantenedor do backend de integração Moodle, quero validar e sanitizar o payload do webhook de rating antes de persistir no banco, para garantir que somente avaliações bem-formadas sejam gravadas, que falhas de DB não sejam mascaradas como sucesso e que a resposta da rota não vaze a existência de sessões internas.

## Contexto (do bug sweep)
O handler `_handle_rating_submitted` (item #62 do bug sweep) processa o webhook de rating do Moodle confiando cegamente no payload recebido:

- **Campos vazios/ausentes** (`session_id`, `rating` faltando ou string vazia) seguem para o `insert` sem rejeição prévia — gerando linhas inválidas ou erro de constraint silencioso.
- **`rating` não é coagido nem validado por faixa** — valores fora do intervalo esperado (ex.: 0, negativos, > máximo, ou strings não-numéricas) são aceitos.
- **Falha de DB é mascarada:** quando o `insert` falha, a rota ainda responde como se a avaliação tivesse sido `processed`, escondendo o erro do chamador e da observabilidade.
- **Vazamento de existência de sessão:** a resposta diferencia "sessão não encontrada" de outros desfechos, permitindo que um chamador enumere quais `session_id` existem.

Impacto: dados de avaliação corrompidos/inconsistentes na tabela de ratings, falhas de persistência invisíveis e um vetor de enumeração de sessões. Esta story compõe com **SEC-SCOPE-5** (verificação HMAC): a ordem obrigatória é **HMAC primeiro → validação de payload por cima** (ver roadmap linha 132 e 335 — handler co-editado).

## Acceptance Criteria
- [ ] **Campos obrigatórios vazios/ausentes → rejeição sem insert:** payload sem `session_id` ou sem `rating` (ou com strings vazias) retorna desfecho `rejected`/non-success e **nenhum `insert` é executado** (verificável: zero linhas novas + nenhuma chamada ao DB de escrita).
- [ ] **`rating` coagido e validado por faixa:** o valor é convertido ao tipo numérico esperado e checado contra o intervalo válido (mínimo/máximo definidos pela tabela de ratings); valores fora da faixa ou não-coercíveis → `rejected` sem insert.
- [ ] **Falha de DB → erro, nunca 'processed':** se o `insert` lançar exceção, o handler propaga/registra o erro e a resposta reflete falha — **jamais** retorna `processed` quando a persistência não ocorreu.
- [ ] **Resposta não vaza existência de sessão:** desfechos non-success (sessão inexistente, payload inválido, falha interna) retornam uma resposta uniforme que **não** permite distinguir "sessão não existe" de "payload inválido" — sem enumeração de `session_id`.
- [ ] **Composição com HMAC (SEC-SCOPE-5):** a validação de payload roda **após** a verificação HMAC; payload com assinatura inválida é barrado por SEC-SCOPE-5 antes de chegar à validação desta story, e a validação não desfaz/contorna o gate HMAC.
- [ ] **Caminho feliz preservado:** payload válido e bem-assinado continua sendo persistido e respondido como `processed` exatamente como hoje (sem regressão funcional).

## Tasks / Subtasks
- [ ] Localizar o handler `_handle_rating_submitted` no backend de integração Moodle e mapear o ponto de entrada (rota webhook) que o invoca.
- [ ] Adicionar uma etapa de validação/sanitização do payload **antes** do `insert`: checar presença e não-vazio de `session_id` e `rating`; coagir `rating` ao tipo numérico; validar faixa (min/max) contra a definição da tabela de ratings.
- [ ] Garantir ordem de composição com SEC-SCOPE-5: HMAC verificado primeiro, validação de payload imediatamente depois (sem reordenar nem remover o gate HMAC).
- [ ] Envolver o `insert` em tratamento de erro que distingue sucesso de falha de DB; nunca marcar `processed` quando a escrita não foi confirmada.
- [ ] Padronizar a resposta da rota para desfechos non-success de modo a não revelar a existência (ou inexistência) da sessão — resposta uniforme entre "sessão inexistente" e "payload inválido".
- [ ] Adicionar logging estruturado dos casos `rejected` e de falha de DB para observabilidade (sem expor dados sensíveis na resposta ao chamador).

## Dev Notes
- **Arquivos:** handler `_handle_rating_submitted` e a rota webhook de rating do backend de integração Moodle (ver `docs/REMEDIATION-ROADMAP-2026-06-03.md` linhas 132 e 335 para o ponto co-editado). Confirmar o módulo exato via grep por `_handle_rating_submitted` no backend antes de editar.
- **Abordagem:** inserir um guard de validação puro (sem efeitos colaterais) entre a verificação HMAC e o `insert`. Sequência: HMAC (SEC-SCOPE-5) → validar/coagir payload → insert protegido por try/except → resposta uniforme. Coerção de `rating` deve falhar fechado (rejeitar em vez de truncar silenciosamente).
- **Riscos de regressão:** blast radius limitado ao caminho do webhook de rating. Risco principal é (1) rejeitar payloads legítimos por critério de faixa mal calibrado — calibrar min/max pela definição real da tabela; (2) conflito de merge/ordem com SEC-SCOPE-5, que edita o mesmo handler — coordenar a integração mantendo HMAC primeiro. Nenhum outro fluxo consome `_handle_rating_submitted` diretamente, mas confirmar via busca por callers antes do merge.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: casos cobrindo campos vazios → rejected sem insert, rating fora de faixa → rejected, falha de DB → erro (não processed), e payload válido → processed.
- [ ] Sem regressão na suíte de segurança (em especial o gate HMAC de SEC-SCOPE-5 continua barrando assinaturas inválidas).
- [ ] QA Gate: PASS ou CONCERNS.
- [ ] Verificado que a resposta non-success é uniforme e não permite enumeração de `session_id` (teste comparando resposta de "sessão inexistente" vs "payload inválido").
- [ ] Confirmada a ordem de composição HMAC → validação no handler integrado com SEC-SCOPE-5.

## QA Results
_(a preencher pelo @qa)_
