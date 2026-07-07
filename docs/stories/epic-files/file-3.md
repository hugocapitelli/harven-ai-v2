---
id: FILE-3
epic: EPIC-FILES
phase: 4
status: InReview
severity: HIGH
terminal: Backend & Infra
complexity: medium
depends_on: [FILE-1]
bug_refs: [50, 54]
---
# FILE-3: Buffer de upload single-read + ValueError->400/413 + reconciliar allowlists

## Story
Como engenheiro de backend responsável pelo serviço de upload de arquivos do tutor Harven.AI, quero ler o conteúdo do arquivo enviado uma única vez, traduzir as falhas de validação (`ValueError`) em respostas HTTP corretas (extensão inválida → 400, arquivo grande demais → 413) e reconciliar as allowlists divergentes entre validação e armazenamento, para que uploads inválidos retornem o status apropriado em vez de erro 500, sem dupla leitura do stream e sem quebrar os demais consumidores de `save_file`.

## Contexto (do bug sweep)
Itens #50 e #54 do bug sweep apontam dois defeitos correlatos no caminho de upload de arquivos:

- **#54 — Dupla leitura do buffer + erro genérico:** o handler de upload lê o `UploadFile` mais de uma vez (uma para validar tamanho/extensão e outra para persistir), o que pode produzir bytes vazios após a primeira leitura (o cursor do stream fica no fim) e força leitura redundante de memória. Além disso, quando a validação interna levanta `ValueError` (extensão proibida ou arquivo acima do limite), a exceção não é capturada e sobe como erro **500 Internal Server Error**, escondendo do cliente que o problema é dele (input inválido), não do servidor.
- **#50 — Cap de 50MB sem distinção de causa (cobertura parcial):** o limite de tamanho é validado mas todas as falhas colapsam no mesmo erro genérico. Esta story cobre single-read + cap de 50MB e a tradução de oversize → 413; o limite de **uploads grandes concorrentes** (concurrency cap) NÃO está no escopo desta story — fica registrado como cobertura parcial.
- **Allowlists divergentes:** a lista de extensões aceitas usada na validação do handler diverge da allowlist usada em `save_file`/`save_file_from_bytes`, de modo que um arquivo pode passar em uma camada e falhar (ou ser silenciosamente aceito) na outra. As duas devem ser reconciliadas para uma única fonte de verdade.

Impacto: clientes recebem 500 em vez de 400/413 (degrada observabilidade e UX, polui logs de erro do servidor), risco de salvar arquivo vazio/corrompido por leitura dupla, e inconsistência de política de extensões entre validação e persistência.

## Acceptance Criteria
- [ ] O conteúdo do arquivo enviado é lido **exatamente uma vez** (single-read) no caminho de upload — sem reposicionar/reler o stream para validar e depois persistir.
- [ ] Existe uma função `save_file_from_bytes(...)` que recebe os bytes já lidos e a função `save_file(...)` passa a **delegar** para `save_file_from_bytes` (não há duplicação de lógica de validação/escrita).
- [ ] Upload com **extensão inválida** retorna **HTTP 400** (Bad Request) com mensagem clara, e **não** 500.
- [ ] Upload **acima do limite de 50MB** (oversize) retorna **HTTP 413** (Payload Too Large), e **não** 500.
- [ ] `ValueError` originado da validação de extensão é mapeado para 400 e `ValueError` de tamanho é mapeado para 413 (mapeamento determinístico, não genérico).
- [ ] As **allowlists de extensões** usadas na validação do handler e em `save_file`/`save_file_from_bytes` são **reconciliadas** em uma única fonte de verdade (constante/config compartilhada), eliminando divergência.
- [ ] Os **demais callers de `save_file`** (fora do caminho de upload do tutor) continuam funcionando com o mesmo contrato — nenhum quebra de assinatura/comportamento observável.
- [ ] Upload válido (extensão permitida, dentro de 50MB) continua persistindo corretamente e retornando o mesmo resultado de sucesso de antes (incluindo `result.id`).
- [ ] Registrado explicitamente que o **concurrency cap** de uploads grandes (parte de #50) está fora do escopo desta story.

## Tasks / Subtasks
- [ ] Localizar o handler de upload no backend (rota/endpoint de upload do tutor) e identificar o(s) ponto(s) onde o `UploadFile`/stream é lido — confirmar a dupla leitura.
- [ ] Refatorar o handler para ler os bytes **uma única vez** em uma variável local e reutilizá-la para validação e persistência.
- [ ] Criar `save_file_from_bytes(filename, content_bytes, ...)` no módulo de storage que concentra a validação de extensão/tamanho e a escrita; manter `save_file(upload_file, ...)` lendo os bytes 1× e delegando a `save_file_from_bytes`.
- [ ] Definir uma **única allowlist de extensões** (constante/config compartilhada) e referenciá-la tanto na validação do handler quanto em `save_file_from_bytes` — remover a lista duplicada/divergente.
- [ ] No handler, envolver a chamada de validação/persistência em tratamento de exceção que mapeia `ValueError` de extensão → `HTTPException(400)` e `ValueError` de tamanho → `HTTPException(413)` (diferenciar por tipo/flag, não por string frágil).
- [ ] Garantir mensagens de erro claras e estáveis no corpo das respostas 400 e 413 (para o front consumir — ver FILE-4).
- [ ] Auditar todos os call sites de `save_file` no repositório (grep) e confirmar que a delegação mantém contrato; ajustar somente se houver quebra de assinatura.
- [ ] Adicionar/atualizar testes de regressão: (a) extensão inválida → 400; (b) arquivo > 50MB → 413; (c) upload válido → sucesso com bytes íntegros; (d) leitura única (os bytes persistidos não vêm vazios).

## Dev Notes
- **Arquivos:** handler de upload do backend (endpoint de upload do tutor — provável `app/routers/` ou `app/api/` no `harven-ai-v2`) e o módulo de storage que define `save_file`/`save_file_from_bytes` e a allowlist de extensões (provável `app/services/` ou `app/storage/`). Confirmar paths reais via grep por `save_file(` e pela definição da rota de upload antes de editar.
- **Abordagem:** Single-read no handler — ler `await file.read()` uma vez para uma variável `content`; introduzir `save_file_from_bytes(filename, content, ...)` como a função núcleo (valida extensão contra a allowlist única, valida `len(content) <= 50MB`, escreve no disco/storage) e reescrever `save_file` para apenas ler os bytes 1× e chamar `save_file_from_bytes`. A validação levanta `ValueError` com um discriminador (tipo de erro distinto ou flag/atributo) para que o handler diferencie extensão (400) de tamanho (413). Unificar a allowlist numa constante compartilhada importada por ambas as camadas.
- **Riscos de regressão:** o blast radius principal são **todos os callers de `save_file`** — qualquer outro fluxo (ex.: uploads administrativos, anexos não-tutor) que dependa do comportamento atual. A delegação deve preservar a assinatura pública de `save_file`. Mudar a allowlist para uma fonte única pode alterar quais extensões são aceitas se as duas listas hoje divergem — validar que a lista reconciliada é o superset/intersecção correto conforme política (decidir e documentar). Mapear `ValueError` para HTTP exige cuidado para não engolir outros `ValueError` não relacionados (capturar apenas os levantados pela validação de upload). Depende de **FILE-1** (que estabelece o caminho base de upload/extração) — confirmar que FILE-1 está concluída antes de implementar.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde — cobrindo extensão inválida → 400, oversize → 413 e upload válido com bytes íntegros (single-read)
- [ ] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [ ] Allowlist de extensões verificada como fonte única (validação do handler e `save_file_from_bytes` apontam para a mesma constante) e todos os callers de `save_file` auditados sem quebra de contrato
- [ ] Registrado no PR/story que o concurrency cap de uploads grandes (#50) permanece fora de escopo (cobertura parcial)

## QA Results
_(a preencher pelo @qa)_
