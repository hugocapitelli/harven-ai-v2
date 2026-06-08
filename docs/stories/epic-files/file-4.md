---
id: FILE-4
epic: EPIC-FILES
phase: 4
status: Draft
severity: HIGH
terminal: UX/UI & Design
complexity: low
depends_on: [FILE-1, FILE-3]
bug_refs: [51]
---
# FILE-4: Surfacear extraction_status na resposta + UI de erro gracioso

## Story
Como aluno que anexa um arquivo (PDF, imagem, áudio) a uma mensagem do tutor, quero ser informado de forma clara e não-bloqueante quando a extração de texto/conteúdo do meu arquivo falhar, para que eu entenda que a mídia foi salva mas o tutor pode não enxergar o conteúdo dela — em vez de o upload simplesmente travar ou prosseguir silenciosamente sem que eu saiba que algo deu errado.

## Contexto (do bug sweep)
Item #51 do BUG-SWEEP-2026-06-03.md: o endpoint de upload de arquivos tenta extrair o conteúdo textual do arquivo (parsing de PDF, OCR de imagem, transcrição de áudio) e, quando essa extração falha, o backend ou (a) retorna erro 500 derrubando o upload inteiro mesmo a mídia já tendo sido persistida, ou (b) prossegue silenciosamente sem nenhum sinal de que o `body`/conteúdo extraído está vazio. O frontend (`handleUpload`) não tem como distinguir "arquivo salvo com conteúdo extraído" de "arquivo salvo mas extração falhou", então ou o aluno vê uma falha total enganosa, ou anexa um arquivo achando que o tutor lê o conteúdo quando na verdade não lê. Impacto: experiência confusa e perda de confiança — o aluno não sabe o estado real do anexo. Esta story depende de FILE-1 e FILE-3 (que tornam a extração tolerante a falha e separam a persistência da mídia da extração de conteúdo no backend), e fecha o loop expondo o `extraction_status` na resposta da API e tratando-o graciosamente na UI.

## Acceptance Criteria
- [ ] A resposta do endpoint de upload SEMPRE inclui um campo `extraction_status` (valores ao menos `ok` e um valor de falha, ex.: `failed`/`error`) e, quando não-ok, um campo `extraction_detail` (ou equivalente) com mensagem legível do motivo.
- [ ] O campo `body` (conteúdo textual extraído) só é incluído/preenchido na resposta quando `extraction_status === ok`; em caso de falha o `body` vem vazio/ausente, nunca com lixo parcial silencioso.
- [ ] A mídia (arquivo original) é SEMPRE salva e referenciável independentemente do `extraction_status` — falha de extração nunca impede a persistência nem invalida `result.id`.
- [ ] `result.id` (identificador do upload/mensagem) permanece íntegro e utilizável tanto no caminho ok quanto no caminho de falha de extração.
- [ ] `handleUpload` no frontend, ao receber `extraction_status` não-ok, exibe um aviso não-bloqueante (toast/banner/inline) informando que o arquivo foi anexado mas o conteúdo pode não ter sido lido, e **avança** o fluxo (não cancela o upload, não trava a UI, não impede o envio da mensagem).
- [ ] `handleUpload`, ao receber `extraction_status === ok`, segue o fluxo normal sem exibir nenhum aviso de erro.
- [ ] Nenhuma regressão no caminho feliz: uploads com extração bem-sucedida continuam anexando e exibindo o conteúdo como antes.

## Tasks / Subtasks
- [ ] Backend: garantir que o endpoint de upload de arquivos (camada que FILE-1/FILE-3 deixaram tolerante a falha) inclua `extraction_status` e `extraction_detail` no payload de resposta — alinhar nome dos campos com o que o frontend vai consumir.
- [ ] Backend: garantir que `body` só seja serializado na resposta quando `extraction_status === ok`; caminho de falha retorna `body` vazio/ausente + `extraction_status` + `extraction_detail`, preservando `result.id`.
- [ ] Frontend: localizar `handleUpload` (componente de chat/upload do tutor) e ler `extraction_status` do retorno da API.
- [ ] Frontend: ramificar `handleUpload` — em `ok` seguir fluxo atual; em não-ok exibir aviso não-bloqueante (usar o sistema de toast/notificação existente) e prosseguir com o anexo usando `result.id`.
- [ ] Frontend: redigir cópia do aviso em pt-BR, clara e tranquilizadora (ex.: "Arquivo anexado. Não conseguimos ler o conteúdo dele — o tutor pode não enxergar o que está dentro."), seguindo voz da Harven.Az.
- [ ] Validar contrato fim-a-fim: upload com arquivo que falha extração → aviso aparece, mensagem segue, `result.id` válido; upload normal → sem aviso.

## Dev Notes
- **Arquivos:**
  - Backend: rota/serviço de upload de arquivos do tutor em `harven-ai-v2` (camada tocada por FILE-1 e FILE-3 — confirmar caminho exato no diff dessas stories; tipicamente o handler de `POST` de upload/anexo de mensagem).
  - Frontend: componente de chat/upload contendo `handleUpload` (busca por `handleUpload` no frontend de `harven-ai-v2`).
- **Abordagem:** Esta é uma story de UX/UI + contrato de API, não de lógica de extração — FILE-1/FILE-3 já tornam a extração não-fatal no backend. Aqui (1) o backend expõe explicitamente `extraction_status`/`extraction_detail` e condiciona `body` ao sucesso, e (2) o frontend trata o status como sinal de UX: avisa sem bloquear e continua usando `result.id`. Reutilizar o sistema de notificação/toast já existente em vez de criar novo. Manter o contrato de resposta retrocompatível (campos adicionais, não removidos).
- **Riscos de regressão:** Blast radius é a resposta do endpoint de upload (qualquer consumidor que faça parse do payload) e o componente que invoca `handleUpload`. Mudar a forma do `body` (passar a omiti-lo em falha) pode afetar código que assume `body` sempre presente — confirmar que todos os consumidores tratam `body` opcional. Depende de FILE-1/FILE-3 já mesclados: se a extração ainda for fatal no backend, o `extraction_status` non-ok nunca chegará ao frontend. Garantir que o aviso não-bloqueante não interfira no envio da mensagem nem em uploads concorrentes.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde
- [ ] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [ ] Verificado manualmente os dois caminhos: (a) arquivo com extração que falha → resposta traz `extraction_status` non-ok + `extraction_detail`, `body` ausente/vazio, mídia salva, `result.id` íntegro, `handleUpload` mostra aviso não-bloqueante e avança; (b) arquivo com extração ok → resposta traz `extraction_status: ok` + `body`, sem aviso, fluxo normal.

## QA Results
_(a preencher pelo @qa)_
