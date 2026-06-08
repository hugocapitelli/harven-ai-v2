---
id: CFG-3
epic: EPIC-CLEANUP
phase: 5
status: Draft
severity: MEDIUM
terminal: Backend & Infra
complexity: medium
depends_on: [SEC-ATO-3]
bug_refs: [62, 4]
---
# CFG-3: Persistir reset-token (hashed, single-use, rate-limited) no DB

## Story
Como engenheiro de backend responsável pela segurança da conta, quero persistir os tokens de reset de senha no banco de dados em formato hasheado (sha256), com uso único e rate-limit por conta, para que o fluxo de recuperação de senha seja seguro, sobreviva a restarts do processo e não vaze o token cru em body de resposta nem em logs.

## Contexto (do bug sweep)
O fluxo de reset de senha em `main.py:404-477` armazena tokens de reset em um **dict in-memory** (estrutura volátil no processo). Isso gera três problemas concretos:

- **#62 — Persistência volátil:** os tokens vivem apenas na memória do processo. Qualquer restart do backend (deploy, crash, scale) invalida todos os tokens pendentes, quebrando links de reset legítimos já enviados por e-mail. Não há single-use confiável nem rate-limit por conta enquanto o estado é apenas in-memory.
- **#4 — Token cru exposto:** o token de reset era exposto no corpo da resposta (leak). A Story `SEC-ATO-3` (EPIC-SEC, Fase 1) já corrigiu esse leak alterando o bloco de reset-token em `main.py:404-477`. Esta Story **rebaseia sobre SEC-ATO-3** e a migração para a tabela `password_resets` **não pode reintroduzir** o vazamento do token cru.

A tabela `password_resets` já existe (migração `20260519`). Esta Story substitui o dict in-memory por essa tabela, gravando o `token_hash` (sha256), flag `used` para single-use e controle de rate-limit por conta. O token cru continua existindo apenas em memória pelo tempo de envio do e-mail — nunca é persistido nem retornado em resposta/log.

## Acceptance Criteria
- [ ] Ao solicitar reset, o backend gera um token cru aleatório, calcula `token_hash = sha256(token_raw)` e **persiste apenas o hash** na tabela `password_resets` (nunca o token cru).
- [ ] O token cru **nunca** aparece no corpo da resposta HTTP nem em qualquer log (mantém o fix #4 — verificar que `SEC-ATO-3` continua válido).
- [ ] O reset é **single-use**: ao validar/consumir um token, a linha é marcada `used = true` (ou equivalente) de forma atômica; tentativas subsequentes com o mesmo token retornam erro (token inválido/expirado) e **não** alteram a senha.
- [ ] Tokens possuem expiração (`expires_at`) verificada na validação; tokens expirados são rejeitados.
- [ ] **Rate-limit por conta:** solicitações de reset acima do limite definido por janela de tempo para a mesma conta/e-mail são rejeitadas (HTTP 429 ou equivalente) sem revelar existência da conta.
- [ ] **Sobrevive a restart:** com o backend reiniciado, um token gerado antes do restart continua válido (dentro da expiração) — comprovando persistência em DB, não em memória.
- [ ] A validação do token é feita comparando o `sha256` do token recebido contra o `token_hash` armazenado; nenhuma lookup é feita pelo token cru em claro.
- [ ] O dict in-memory de tokens em `main.py:404-477` é **removido** — não há mais estado de reset mantido em memória do processo.
- [ ] Migração: a tabela `password_resets` possui coluna `token_hash`; se existir coluna `token` plaintext legada, ela é removida ou depreciada (deixa de ser lida/gravada).

## Tasks / Subtasks
- [ ] Confirmar o schema atual de `password_resets` (migração `20260519`) e identificar colunas presentes: `token_hash`, `used`, `expires_at`, `account/email`, `created_at`.
- [ ] Criar migração de ajuste (se necessário) que: garante `token_hash` (sha256, indexável), garante `used` (boolean default false) e `expires_at`; **remove/deprecia** qualquer coluna `token` plaintext. Adicionar índice em `token_hash` e índice/coluna de suporte ao rate-limit (ex.: por `email` + `created_at`).
- [ ] No endpoint de solicitação de reset em `main.py:404-477`: gerar token cru, calcular `sha256`, inserir linha em `password_resets` com hash + expiração; enviar o token cru somente via canal de e-mail; **não** retornar no body nem logar.
- [ ] Implementar rate-limit por conta: contar solicitações recentes em `password_resets` (ou tabela auxiliar) na janela definida e rejeitar acima do limite.
- [ ] No endpoint de confirmação/consumo de reset: calcular `sha256` do token recebido, buscar linha por `token_hash`, validar `used = false` e `expires_at > now`, aplicar a nova senha e marcar `used = true` de forma atômica (ex.: UPDATE condicional / transação).
- [ ] Remover o dict in-memory de tokens e qualquer referência a ele em `main.py`.
- [ ] Escrever teste de regressão: (a) fluxo feliz com restart simulado, (b) single-use (segundo uso falha), (c) token cru ausente do body/log, (d) rate-limit dispara após N solicitações.

## Dev Notes
- **Arquivos:** `main.py` (bloco de reset-token, linhas ~404-477); diretório de migrações do projeto (tabela `password_resets`, migração base `20260519` + nova migração de ajuste); módulo/utilitário de hashing (sha256) e de envio de e-mail.
- **Abordagem:** Substituir o estado volátil in-memory por persistência em `password_resets`. Gravar somente `token_hash = sha256(token_raw)`. Validação por igualdade de hash. Single-use via flag `used` atualizada atomicamente (UPDATE condicional `WHERE token_hash = ? AND used = false AND expires_at > now`), evitando race no consumo. Rate-limit por conta consultando solicitações recentes na janela. O token cru existe apenas em memória pelo tempo necessário ao envio do e-mail e nunca é retornado em resposta nem logado, preservando o fix #4 de `SEC-ATO-3`.
- **Riscos de regressão:**
  - **Não regredir #4 (SEC-ATO-3):** `SEC-ATO-3` já tocou exatamente este bloco `main.py:404-477` para remover o leak do token no body. Esta Story rebaseia sobre ele — confirmar que a refatoração para DB não reintroduz o token cru em nenhuma resposta/log.
  - **Blast radius:** os dois endpoints de reset (solicitar / confirmar) em `main.py` e qualquer caller do antigo dict in-memory. Verificar consumidores do envio de e-mail de reset.
  - **Migração destrutiva:** remover coluna `token` plaintext invalida tokens pendentes legados — aceitável (tokens antigos in-memory já não sobreviviam a restart). Garantir ordem: deploy do código que usa `token_hash` antes/junto da remoção da coluna plaintext.
  - **Concorrência:** consumo single-use precisa ser atômico para evitar duplo-uso em chamadas simultâneas.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde
- [ ] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [ ] Confirmado por inspeção/teste que o token cru não aparece em body de resposta nem em logs (fix #4 / SEC-ATO-3 preservado), que o token sobrevive a restart do backend e que o segundo uso do mesmo token é rejeitado; dict in-memory removido de `main.py`.

## QA Results
_(a preencher pelo @qa)_
