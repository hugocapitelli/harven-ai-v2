---
id: MEDIA-3
epic: EPIC-FRONT
phase: 4
status: Draft
severity: HIGH
terminal: UX/UI & Design
complexity: low
depends_on: [MEDIA-1]
bug_refs: [10]
---
# MEDIA-3: Renderizar mídia no ContentRevision (instrutor) + remover @ts-nocheck

## Story
Como instrutor revisando conteúdo gerado pela IA, quero que o bloco de mídia (vídeo, áudio, imagem, iframe) seja efetivamente renderizado na tela de revisão de conteúdo, para que eu consiga validar visualmente o material antes de publicar — em vez de ver placeholders quebrados, texto bruto ou nada.

## Contexto (do bug sweep)
Item #10 (BUG-SWEEP-2026-06-03.md): a tela de revisão de conteúdo do instrutor (`ContentRevision`) não renderiza os blocos de mídia produzidos pelo pipeline de IA. O componente assume `@ts-nocheck` no topo do arquivo, o que mascara erros de tipo reais no acesso ao conteúdo da revisão — escondendo justamente o contrato divergente que impede a renderização.

Sintomas verificados:
- Blocos de tipo `VIDEO`/`AUDIO`/`IMAGE`/`IFRAME` não aparecem ou aparecem como placeholder/texto cru.
- Conteúdo `IMAGE` não é renderizado como elemento `<img>`.
- O corpo do conteúdo é lido de campo errado: o componente cai no fallback `extracted_text` (texto bruto de extração) em vez de usar o campo `body` já normalizado pela camada de tipos/normalização entregue em **MEDIA-1**.
- `@ts-nocheck` no arquivo suprime os erros de compilação que sinalizariam exatamente esse acesso a campos inexistentes/errados.

Impacto: instrutor não consegue revisar mídia, aprovando ou rejeitando às cegas. Como o conteúdo de mídia é o que MEDIA-1/MEDIA-2 passaram a normalizar corretamente no backend/tipos, o defeito é puramente de consumo no frontend de revisão.

## Acceptance Criteria
- [ ] Para um bloco de conteúdo cujo tipo seja `VIDEO`, a `ContentRevision` renderiza um player/elemento de vídeo com a URL de mídia normalizada.
- [ ] Para tipo `AUDIO`, renderiza um player/elemento de áudio.
- [ ] Para tipo `IMAGE`, renderiza um elemento `<img>` (não texto, não placeholder genérico) com a URL de imagem.
- [ ] Para tipo `IFRAME` (embed/iframe), renderiza um `<iframe>` com a URL de embed normalizada.
- [ ] O corpo textual do conteúdo é lido do campo `body` (contrato normalizado de MEDIA-1) e **não** do fallback `extracted_text`.
- [ ] `@ts-nocheck` é removido do arquivo `ContentRevision` e o arquivo compila sem erros de TypeScript (os tipos de MEDIA-1 são usados para acessar tipo/URL/`body`).
- [ ] Tipos de mídia desconhecidos degradam graciosamente (sem crash em branco) — fallback explícito para um aviso/representação textual.
- [ ] Nenhuma leitura direta de campos brutos/legados de mídia que MEDIA-1 já encapsulou (sem reintroduzir `media_url`/`content_type` cru se a normalização provê o acessor).

## Tasks / Subtasks
- [ ] Localizar o componente de revisão: `grep -rn "ts-nocheck" frontend/src` e identificar o arquivo `ContentRevision` (provável `frontend/src/.../ContentRevision.tsx`).
- [ ] Remover a diretiva `// @ts-nocheck` do topo do arquivo e rodar `tsc`/build para expor os erros de tipo reais.
- [ ] Substituir o acesso ao corpo do conteúdo pelo campo `body` do tipo normalizado introduzido em MEDIA-1; remover o fallback para `extracted_text`.
- [ ] Implementar/ajustar o switch de renderização por tipo de conteúdo: `VIDEO` → `<video>`, `AUDIO` → `<audio>`, `IMAGE` → `<img>`, `IFRAME` → `<iframe>`; usar o acessor de URL normalizado de MEDIA-1.
- [ ] Adicionar um branch `default` para tipos não mapeados (aviso/fallback textual) evitando render vazio.
- [ ] Corrigir todos os erros de tipo restantes após a remoção do `@ts-nocheck`, importando os tipos de mídia/conteúdo de MEDIA-1.
- [ ] Conferir os outros consumidores da mesma tela (ChapterDetail/CourseDetails são tratados em MEDIA-4, fora de escopo aqui) para não reintroduzir leitura crua.

## Dev Notes
- **Arquivos:** componente de revisão do instrutor `ContentRevision` em `frontend/src/` (confirmar via `grep -rn "ContentRevision" frontend/src` + `grep -rn "ts-nocheck" frontend/src`); tipos/normalização de mídia entregues em **MEDIA-1** (provável `frontend/src/types/` ou util de normalização compartilhado).
- **Abordagem:** trocar acesso de campo bruto + `extracted_text` por contrato `body` normalizado; introduzir/consolidar render switch por `contentType`; remover `@ts-nocheck` e deixar o compilador validar o consumo correto do tipo de MEDIA-1.
- **Riscos de regressão:** mudança restrita ao frontend de revisão do instrutor — não toca rota/API nem RLS. Blast radius limitado ao próprio `ContentRevision`; remover `@ts-nocheck` pode expor outros erros de tipo pré-existentes no mesmo arquivo (esperado — devem ser corrigidos, não re-suprimidos). Depende de MEDIA-1 já ter exportado o tipo normalizado com `body` e acessor de URL; se MEDIA-1 não estiver mergeado, esta story bloqueia.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde — render dos 4 tipos de mídia + leitura de `body` validados (component test/render snapshot por tipo).
- [ ] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [ ] `@ts-nocheck` removido e `npm run build` / `tsc` do frontend passa sem erro no `ContentRevision`; nenhum fallback para `extracted_text` permanece no componente.

## QA Results
_(a preencher pelo @qa)_
