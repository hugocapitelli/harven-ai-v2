---
id: MEDIA-2
epic: EPIC-FRONT
phase: 4
status: Draft
severity: HIGH
terminal: UX/UI & Design
complexity: medium
depends_on: [MEDIA-1]
bug_refs: [10]
---
# MEDIA-2: Renderizar vídeo/áudio/imagem no ChapterReader + remover `@ts-nocheck`

## Story
Como aluno consumindo um capítulo na Harven.AI, quero que conteúdos do tipo VIDEO, AUDIO e IMAGE sejam efetivamente renderizados (player de vídeo, player de áudio e a imagem em si) a partir do `file_url` normalizado, para que eu consiga assistir/ouvir/ver o material em vez de receber um bloco de texto vazio ou um rótulo errado.

## Contexto (do bug sweep)
Item de bug **#10**: o `ChapterReader.tsx` carrega `@ts-nocheck` no topo, o que silencia erros de contrato de tipos e esconde o defeito de renderização de mídia. O componente trata os conteúdos como se fossem sempre texto/`summary`: não há ramo de renderização para VIDEO (elemento `<video>`), AUDIO (elemento `<audio>`) nem IMAGE (`<img>`), e o `file_url` normalizado pelo contrato de mídia (entregue por MEDIA-1) não é consumido. Consequências concretas:
- Conteúdo VIDEO/AUDIO/IMAGE aparece sem player/imagem — o aluno vê área vazia ou apenas o título.
- Áudio gravado/salvo é tratado/rotulado como `summary` (texto), mascarando que é mídia de áudio e impedindo o player correto.
- Não existe badge/tipo IMAGE; o tipo de imagem não é reconhecido na UI.
- O `@ts-nocheck` impede o TypeScript de apontar que o componente ignora os campos do contrato normalizado (`type`/`file_url`), perpetuando o bug em silêncio.

Impacto: features pedagógicas de mídia (FASE 4 — "vídeo/áudio/imagem renderizam via contrato normalizado") ficam inoperantes do lado do aluno. Esta story depende de **MEDIA-1**, que define/normaliza o contrato de mídia (`type` + `file_url`) consumido aqui.

## Acceptance Criteria
- [ ] Conteúdo do tipo **VIDEO** renderiza um player de vídeo (`<video controls>`) cujo `src` vem do `file_url` normalizado (contrato MEDIA-1); sem `file_url` válido, exibe estado de fallback claro (ex.: "mídia indisponível"), nunca um bloco vazio.
- [ ] Conteúdo do tipo **AUDIO** renderiza um player de áudio (`<audio controls>`) cujo `src` vem do `file_url`; áudio salvo **não** é rotulado/tratado como `summary` — o tipo exibido e o ramo de render são de AUDIO.
- [ ] Conteúdo do tipo **IMAGE** renderiza a imagem (`<img>`) com `src` do `file_url` e `alt` descritivo (título do conteúdo); o tipo **IMAGE** ganha **badge** próprio na UI.
- [ ] O `file_url` é a única fonte de URL de mídia consumida pelo componente (sem leitura direta de `media_url`/`content_type` cru fora do contrato normalizado).
- [ ] `@ts-nocheck` é **removido** do topo de `ChapterReader.tsx` e o arquivo **type-checa** (`tsc`/build de tipos passa) sem erros, com os campos do contrato (`type`, `file_url`) tipados corretamente.
- [ ] Tipos de conteúdo já existentes (texto/summary, e qualquer outro renderizado hoje) continuam renderizando sem regressão.

## Tasks / Subtasks
- [ ] Confirmar o contrato de mídia normalizado entregue por **MEDIA-1** (formato de `type` e presença de `file_url`) e importar/usar o tipo correspondente em `ChapterReader.tsx`.
- [ ] Adicionar ramo de renderização para **VIDEO** em `ChapterReader.tsx`: `<video controls src={content.file_url} />` com fallback quando `file_url` ausente.
- [ ] Adicionar ramo de renderização para **AUDIO**: `<audio controls src={content.file_url} />`; garantir que áudio não caia no ramo `summary`/texto.
- [ ] Adicionar ramo de renderização para **IMAGE**: `<img src={content.file_url} alt={content.title} />` e incluir **IMAGE** no mapa de tipos/badges da UI (badge IMAGE).
- [ ] Garantir que VIDEO/AUDIO/IMAGE leem exclusivamente o `file_url` normalizado (remover qualquer leitura de campo cru de mídia, se existir).
- [ ] Remover a diretiva `@ts-nocheck` do topo de `ChapterReader.tsx`; corrigir os erros de tipo que surgirem (tipar `content`/`type`/`file_url` conforme o contrato).
- [ ] Rodar o type-check/build de tipos do frontend e garantir verde para o arquivo.
- [ ] Verificação visual rápida: VIDEO toca, AUDIO toca, IMAGE aparece, badge IMAGE visível, texto/summary inalterado.

## Dev Notes
- **Arquivos:** `ChapterReader.tsx` (componente do leitor de capítulo do aluno — alvo principal); mapa/constantes de metadados de tipo de conteúdo usados para badges/ícones (ex.: `CONTENT_TYPE_META`, compartilhado com MEDIA-4); tipos do contrato de mídia definidos/normalizados em **MEDIA-1**.
- **Abordagem:** consumir o contrato normalizado de MEDIA-1 (`type` discriminado + `file_url`) e adicionar três ramos de render (VIDEO → `<video>`, AUDIO → `<audio>`, IMAGE → `<img>`), cada um lendo `file_url`. Adicionar IMAGE ao conjunto de badges/tipos. Remover `@ts-nocheck` por último e corrigir os erros de tipo expostos — eles são exatamente o sinal que `@ts-nocheck` escondia.
- **Riscos de regressão:** `ChapterReader.tsx` é o caminho de leitura do aluno; alterar a árvore de renderização por tipo pode afetar a exibição de conteúdos texto/summary já existentes — preservar esses ramos. Remover `@ts-nocheck` pode expor erros de tipo em código vizinho do mesmo arquivo (não só na parte de mídia) — corrigir sem mudar comportamento. Mudança no mapa de tipos (badge IMAGE) é compartilhada com **MEDIA-4** (badges/ícones em ChapterDetail/CourseDetails) — alinhar o nome/valor do tipo IMAGE para não divergir. Bloqueia **SF-1**, **SF-2** e **SF-3** (e **TPP-6**), que dependem desta story.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: cenário que renderiza VIDEO/AUDIO/IMAGE via `file_url` falha no estado atual e passa após a correção; áudio não rotulado como summary.
- [ ] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [ ] `@ts-nocheck` removido de `ChapterReader.tsx` e arquivo type-checa sem erros (build/tsc verde); badge IMAGE presente; texto/summary renderiza inalterado.

## QA Results
_(a preencher pelo @qa)_
