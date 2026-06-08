---
id: FILE-5
epic: EPIC-FILES
phase: 4
status: Draft
severity: HIGH
terminal: Backend & Infra
complexity: low
depends_on: []
bug_refs: [61]
---
# FILE-5: Corrigir corrupção de path em delete_file + guard de traversal

## Story
Como engenheiro de backend responsável pelo armazenamento de arquivos do tutor Harven.AI, quero que `delete_file` resolva o caminho-alvo de forma correta e confinada ao diretório base, para que a exclusão apague exatamente o arquivo pretendido e nunca permita que um caminho relativo malicioso (`../`) saia da raiz de armazenamento e remova arquivos fora do sandbox.

## Contexto (do bug sweep)
Item #61 do bug sweep. A função `delete_file` usa `lstrip` para retirar o prefixo do diretório base do path recebido (ex.: `path.lstrip(base_dir)`). `lstrip` não remove um prefixo — remove **qualquer caractere** do conjunto informado, do início da string. Isso corrompe o caminho: nomes de arquivo que começam com letras presentes em `base_dir` (barras, pontos, ou caracteres do prefixo) são truncados de forma imprevisível, fazendo a função tentar excluir o arquivo errado — ou nenhum. Além disso, não há validação de path traversal: um path contendo `../` é concatenado/resolvido sem confinamento, permitindo que a operação de `unlink` aponte para fora do `base_dir` e exclua arquivos arbitrários do sistema de arquivos. Impacto: corrupção silenciosa de dados (arquivo errado apagado) e vetor de exclusão arbitrária de arquivos (traversal) — classificado HIGH.

## Acceptance Criteria
- [ ] A remoção do prefixo do diretório base usa `removeprefix(base_dir)` (semântica de prefixo exato) em vez de `lstrip(base_dir)` (remoção de conjunto de caracteres), eliminando a corrupção de path.
- [ ] O caminho-alvo final é resolvido (ex.: `Path(...).resolve()`) e verificado como estando **dentro** de `base_dir` resolvido antes de qualquer operação de filesystem.
- [ ] Um path contendo traversal (`../`, ou qualquer caminho que resolva para fora de `base_dir`) é rejeitado: a função retorna `False` e **nenhum** `unlink`/exclusão é executado.
- [ ] Um path válido apontando para um arquivo real dentro de `base_dir` continua sendo excluído corretamente e retorna o valor de sucesso esperado (compatível com o contrato atual de retorno).
- [ ] Um path válido apontando para arquivo inexistente dentro de `base_dir` é tratado de forma defensiva (retorna `False`, sem exceção não tratada), preservando o comportamento idempotente esperado.

## Tasks / Subtasks
- [ ] Localizar a função `delete_file` no módulo de serviço de armazenamento de arquivos do backend (`backend/app/services/file_*` / `file_service.py` — confirmar path exato via grep por `def delete_file` e `lstrip`).
- [ ] Substituir `path.lstrip(base_dir)` por `path.removeprefix(base_dir)` (Python 3.9+; o projeto já usa Python compatível — confirmar versão no `pyproject.toml`/`requirements`).
- [ ] Resolver o caminho final com `Path(base_dir, relative).resolve()` e validar confinamento via `resolved.is_relative_to(base_resolved)` (ou `os.path.commonpath`) antes de excluir.
- [ ] Em caso de traversal/fora-de-base ou path inválido: retornar `False` sem chamar `unlink`.
- [ ] Garantir que o caminho de sucesso e o de arquivo inexistente preservam o contrato de retorno atual dos callers.
- [ ] Adicionar teste de regressão cobrindo os quatro cenários: prefixo corrompido (caso #61), traversal rejeitado, exclusão válida, arquivo inexistente.

## Dev Notes
- **Arquivos:** serviço de arquivos do backend que contém `delete_file` e a constante/variável `base_dir` (confirmar via `grep -rn "def delete_file\|lstrip" backend/app/`). Teste de regressão em `backend/tests/` (espelhar o módulo).
- **Abordagem:** dois defeitos em uma função pequena. (1) Correção de string: `removeprefix` (prefixo exato) no lugar de `lstrip` (set de chars). (2) Hardening de segurança: resolver o caminho e confinar a `base_dir` com `Path.resolve()` + `is_relative_to`, rejeitando traversal antes de qualquer `unlink`. Manter a assinatura e o tipo de retorno (`bool`) para não quebrar callers.
- **Riscos de regressão:** mudança localizada em `delete_file`. Blast radius = todos os pontos que disparam exclusão de arquivo (handlers/rotas de delete de upload, limpeza de arquivos órfãos, cleanup de sessão). `removeprefix` é estritamente mais correto que `lstrip`, então paths anteriormente corrompidos passam a resolver para o arquivo certo — verificar que nenhum caller dependia (incorretamente) do truncamento. O guard de traversal só rejeita paths que já eram inválidos/maliciosos; fluxos legítimos não são afetados.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde — cobrindo corrupção de prefixo (#61) e traversal.
- [ ] Sem regressão na suíte de segurança.
- [ ] QA Gate: PASS ou CONCERNS
- [ ] `delete_file` rejeita explicitamente `../` retornando `False` sem executar `unlink`, e o caso de exclusão legítima dentro de `base_dir` continua funcionando.

## QA Results
_(a preencher pelo @qa)_
