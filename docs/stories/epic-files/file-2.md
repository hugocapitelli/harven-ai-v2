---
id: FILE-2
epic: EPIC-FILES
phase: 4
status: Draft
severity: HIGH
terminal: Backend & Infra
complexity: medium
depends_on: [FILE-1]
bug_refs: [52, 53]
---
# FILE-2: Validação magic-byte + dispatch por tipo detectado no upload

## Story
Como engenheiro de backend responsável pelo pipeline de ingestão de arquivos do Harven.AI, quero validar o conteúdo real de cada upload por magic-byte (assinatura binária) e despachar o parser pelo tipo DETECTADO — não pelo `Content-Type`/extensão informados pelo cliente —, para impedir que arquivos rotulados incorretamente sejam parseados pelo handler errado, gerando mojibake, exceções não tratadas ou bypass de validação.

## Contexto (do bug sweep)
Conforme itens **#52** e **#53** do `docs/BUG-SWEEP-2026-06-03.md`, o endpoint de upload confia no `Content-Type`/extensão enviados pelo cliente para decidir qual parser invocar, sem inspecionar a assinatura binária real do arquivo:

- **#52 — Dispatch por rótulo, não por conteúdo:** um arquivo binário (PDF/DOCX/PPTX) renomeado/rotulado como outro tipo (ex.: `.txt`, ou `Content-Type: text/plain`) é roteado para o parser de texto. O leitor de texto tenta decodificar bytes binários como UTF-8/latin-1 e produz **mojibake** (texto corrompido) que entra no índice/contexto do tutor, ou lança exceção não tratada (HTTP 500). Inversamente, um `.txt` real rotulado como PDF cai no parser de PDF e estoura uma exceção opaca em vez de um erro de validação claro.
- **#53 — Ausência de magic-byte gate:** não há rejeição precoce. Tipos binários sem assinatura coerente com o rótulo deveriam retornar **400/415** com mensagem clara (e SEM emitir o conteúdo corrompido na resposta). Formatos de texto puro (txt/md/csv/html) que legitimamente NÃO possuem magic-byte estável precisam de um **fallback por extensão** controlado — hoje esse fallback inexiste de forma explícita, então a borda fica indefinida.

Impacto: ingestão de conteúdo corrompido no RAG do tutor (degradação silenciosa de qualidade), respostas 500 não acionáveis, e superfície para upload de binário disfarçado escapar da validação de tipo. Esta story depende de **FILE-1** (que estabelece o saneamento/limite base do upload) e adiciona a camada de detecção de tipo por conteúdo.

> O upload handler e os parsers vivem no backend de ingestão. Os paths exatos devem ser confirmados pelo @dev via grep no início da implementação (ver Dev Notes) — o roadmap referencia o módulo de upload/parsing de arquivos do `harven-ai-v2`.

## Acceptance Criteria
- [ ] **Magic-byte para binários:** PDF, DOCX e PPTX são identificados pela assinatura binária real (não pelo `Content-Type`/extensão). Um arquivo cuja assinatura NÃO corresponde ao rótulo declarado é **rejeitado com 400 ou 415** antes de qualquer tentativa de parse.
- [ ] **Sem mojibake na resposta:** em caso de rejeição, a resposta de erro NÃO contém o conteúdo decodificado/corrompido do arquivo — apenas mensagem de validação acionável (tipo detectado vs. tipo esperado, sem vazar bytes).
- [ ] **Fallback por extensão para texto:** arquivos `txt`, `md`, `csv`, `html` (que não têm magic-byte estável) são aceitos via fallback explícito por extensão + verificação de que o conteúdo é texto decodificável; binário disfarçado de `.txt` é rejeitado (400/415), não decodificado às cegas.
- [ ] **Dispatch pelo tipo DETECTADO:** o roteamento para o parser usa exclusivamente o tipo detectado (magic-byte ou fallback de extensão validado), nunca o `Content-Type`/extensão crus do cliente. PDF detectado → parser PDF; DOCX → parser DOCX; PPTX → parser PPTX; texto → parser de texto.
- [ ] **Caminho feliz preservado:** uploads legítimos de cada um dos 7 tipos (pdf, docx, pptx, txt, md, csv, html) continuam sendo aceitos e parseados corretamente (sem regressão funcional).
- [ ] **`filetype` pinado:** a dependência usada para detecção de magic-byte (`filetype`) é adicionada com versão pinada (exata) no manifesto de dependências do backend.
- [ ] **`nosniff` nos servidos:** arquivos/streams servidos de volta pelo backend incluem o header `X-Content-Type-Options: nosniff`.
- [ ] **Teste de regressão (falha-antes / passa-depois):** existe teste cobrindo (a) PDF/DOCX/PPTX rotulado errado → 400/415 sem mojibake; (b) txt/md/csv/html via fallback de extensão; (c) dispatch correto pelo tipo detectado.

## Tasks / Subtasks
- [ ] Localizar o upload handler e o roteador de parsers no backend (grep por `Content-Type`, `filename`, `.endswith`, `pdf`, `docx`, `pptx`, `multipart`, `UploadFile` no dir do backend de `harven-ai-v2`) e confirmar os paths reais antes de editar.
- [ ] Adicionar a dependência `filetype` com versão **pinada** ao manifesto do backend (`requirements.txt` / `pyproject.toml` — confirmar qual está em uso) e instalar.
- [ ] Implementar função de detecção de tipo: `detect_upload_type(raw_bytes, declared_name, declared_content_type)` que (1) inspeciona magic-byte via `filetype` para binários (pdf/docx/pptx — atenção: docx/pptx são ZIP/OOXML, exigem verificação do container OOXML, não só `application/zip`); (2) se não houver magic-byte, aplica fallback por extensão para `txt/md/csv/html` + valida que os bytes são texto decodificável; (3) retorna tipo canônico ou levanta erro de validação.
- [ ] Substituir o dispatch atual (baseado em rótulo) para usar o tipo retornado por `detect_upload_type`. Mapear tipo detectado → parser correto.
- [ ] Mapear rejeições para **HTTP 400/415** com payload de erro limpo (tipo detectado, tipo esperado) e garantir que NENHUM byte/conteúdo decodificado do arquivo vaze na resposta de erro.
- [ ] Adicionar header `X-Content-Type-Options: nosniff` na(s) rota(s) que servem arquivos/streams de volta.
- [ ] Escrever testes de regressão (ver Dev Notes): fixtures binárias rotuladas errado, fixtures de texto puro, e asserts de dispatch correto.

## Dev Notes
- **Arquivos (confirmar via grep no início):**
  - Backend de ingestão/upload do `harven-ai-v2` — provável upload handler (rota `multipart`/`UploadFile`) e módulo de parsing por tipo.
  - Manifesto de dependências do backend (`requirements.txt` ou `pyproject.toml`) — para pinar `filetype`.
  - Suíte de testes do backend — adicionar testes de regressão de upload.
  - Reutilizar/estender o saneamento de upload introduzido em **FILE-1** (não duplicar limite de tamanho/sanitização de nome — esta story acopla a detecção de tipo nesse mesmo ponto de entrada).
- **Abordagem:** introduzir uma única função canônica de detecção (`detect_upload_type`) chamada imediatamente após o gate do FILE-1 e ANTES do dispatch. Decisão de roteamento passa a ler somente o tipo detectado. Para OOXML (docx/pptx), confirmar o subtipo correto (não aceitar genérico `application/zip` como docx). Para texto, fallback por extensão whitelisted (`txt/md/csv/html`) + tentativa de decode (utf-8 com fallback controlado) — rejeitar se contiver bytes nulos / não-texto. Erros de validação retornam 400 (rótulo/extensão incoerente) ou 415 (tipo não suportado), sempre sem ecoar conteúdo.
- **Riscos de regressão (blast radius):** todo arquivo enviado ao tutor passa por este handler — qualquer endurecimento incorreto pode **bloquear uploads legítimos**. Pontos de atenção: (1) docx/pptx detectados como zip genérico → falsos 415; (2) `.md`/`.csv`/`.html` válidos rejeitados pelo check de "é texto"; (3) consumidores downstream (indexação RAG, embedding, tutor) que assumiam o tipo antigo — garantir que o tipo canônico retornado mantém o mesmo contrato para os parsers existentes. Caminho feliz dos 7 tipos é o gate de não-regressão.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde para os três cenários: rótulo errado → 400/415 sem mojibake; fallback de extensão de texto; dispatch pelo tipo detectado.
- [ ] Sem regressão na suíte de segurança.
- [ ] QA Gate: PASS ou CONCERNS.
- [ ] `filetype` pinado no manifesto e `X-Content-Type-Options: nosniff` presente nas respostas de arquivos servidos, verificados manualmente.
- [ ] Caminho feliz dos 7 tipos (pdf, docx, pptx, txt, md, csv, html) confirmado sem regressão funcional.

## QA Results
_(a preencher pelo @qa)_
