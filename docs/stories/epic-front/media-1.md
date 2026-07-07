---
id: MEDIA-1
epic: EPIC-FRONT
phase: 4
status: InReview
severity: HIGH
terminal: UX/UI & Design
complexity: low
depends_on: []
bug_refs: [10]
---
# MEDIA-1: Adapter de contrato de leitura de conteúdo + wire no API client

## Story
Como aluno (e instrutor) consumindo conteúdo na plataforma, quero que o frontend traduza corretamente o contrato de leitura de conteúdo retornado pelo backend, para que vídeo, áudio, imagem e texto sejam reconhecidos pelo tipo certo e suas mídias apontem para a URL correta — eliminando a divergência de campos que hoje faz a mídia sumir ou cair em fallback de texto.

## Contexto (do bug sweep)
Item #10 do bug sweep: o backend retorna o conteúdo com o contrato `content_type` (em alguns endpoints/legado em UPPERCASE, em outros lowercase) e `media_url`, enquanto o frontend lê `type` e `file_url`. Essa divergência de nomes de campo faz com que o componente de leitura não reconheça o tipo real do conteúdo (caindo em fallback de TEXT) e não encontre a URL da mídia (`file_url` chega `undefined`), de modo que vídeo/áudio/imagem não renderizam. Além disso o campo de texto vem em `body`, mas partes da UI esperam `extracted_text`, gerando texto vazio. O tipo `Content` no frontend não contempla `IMAGE` nem `audio_url`. Esta story é a base (não há `depends_on`) sobre a qual MEDIA-2, MEDIA-3 e MEDIA-4 dependem — todas leem do contrato normalizado. Sequência declarada no roadmap: `MEDIA-1 → MEDIA-2`.

## Acceptance Criteria
- [ ] Existe uma função pura `normalizeContent(raw)` que mapeia `content_type` → `type`, normalizando tanto valores lowercase (`text`/`video`/`audio`/`image`) quanto o legado UPPERCASE (`TEXT`/`VIDEO`/`AUDIO`/`IMAGE`) para um único valor canônico (UPPERCASE) consumido pela UI.
- [ ] `normalizeContent` mapeia `media_url` → `file_url`, preservando o `file_url` já presente caso o backend já tenha enviado no nome novo (não sobrescreve com `undefined`).
- [ ] `normalizeContent` preserva `body` e `audio_url` do payload original sem perda.
- [ ] `normalizeContent` cria o alias `extracted_text` a partir de `body` (`extracted_text ← body`) para compatibilidade com a UI que ainda lê `extracted_text`.
- [ ] A normalização é aplicada em `contentsApi.get` (objeto único) e em `contentsApi.list` (array — cada item normalizado).
- [ ] O tipo TypeScript `Content` inclui o valor de tipo `IMAGE` e o campo opcional `audio_url`.
- [ ] `normalizeContent` é null-safe: aceita `undefined`/`null` e objetos sem `content_type`/`media_url` sem lançar exceção (retorna objeto com defaults seguros, ex.: `type: 'TEXT'`).
- [ ] Nenhum componente downstream precisa ler `content_type` ou `media_url` crus — o contrato exposto pelo `contentsApi` já é o normalizado.

## Tasks / Subtasks
- [ ] Localizar o API client de conteúdos (provável `frontend/src/api/contents.ts` ou `lib/api/contents.ts`) e o tipo `Content` (provável `frontend/src/types/content.ts`).
- [ ] Adicionar `IMAGE` ao enum/union de `type` e o campo opcional `audio_url?: string` ao tipo `Content`; confirmar `file_url?`, `body?`, `extracted_text?` presentes.
- [ ] Implementar `normalizeContent(raw): Content` como função pura, exportada (testável isoladamente): map de `content_type`→`type` com `String(raw?.content_type ?? raw?.type ?? '').toUpperCase()` e default `TEXT`; `file_url = raw?.file_url ?? raw?.media_url ?? null`; preservar `body`, `audio_url`; `extracted_text = raw?.extracted_text ?? raw?.body ?? null`.
- [ ] Wire em `contentsApi.get`: `return normalizeContent(response.data)`.
- [ ] Wire em `contentsApi.list`: `return (response.data ?? []).map(normalizeContent)`.
- [ ] Garantir guarda null-safe na entrada (`raw == null` → objeto default).
- [ ] Escrever teste unitário de `normalizeContent` cobrindo: lowercase, UPPERCASE legado, `media_url`→`file_url`, preservação de `file_url` novo, `extracted_text`←`body`, IMAGE+`audio_url`, e entrada `null`/sem campos.

## Dev Notes
- **Arquivos:** API client de conteúdos (`frontend/src/api/contents.ts` ou equivalente que exporta `contentsApi`); tipo `Content` (`frontend/src/types/content.ts` ou equivalente). Confirmar paths exatos via grep por `contentsApi` e `content_type` no repo antes de editar.
- **Abordagem:** Adapter de contrato no boundary do API client. `normalizeContent` é o único ponto de tradução `content_type`/`media_url`/`body` → `type`/`file_url`/`extracted_text`. Função pura para permitir teste sem mock de rede. Canonicalizar `type` em UPPERCASE resolve a coexistência lower/legado-upper. Nunca sobrescrever campo novo com `undefined` (usar `??`, não `||` cego para strings vazias quando relevante).
- **Riscos de regressão:** Blast radius limitado ao consumo de conteúdo no frontend. Quem chama `contentsApi.get/list`: ChapterReader (MEDIA-2), ContentRevision (MEDIA-3), ChapterDetail/CourseDetails badges (MEDIA-4). Como essas stories dependem desta e ainda leem o contrato antigo via fallback, a normalização canônica em UPPERCASE deve permanecer compatível com leituras existentes de `type` (que já esperam UPPERCASE em CONTENT_TYPE_META). Verificar que nenhum componente compara `type` contra valores lowercase hardcoded — se houver, é escopo de MEDIA-2..4, não regressão aqui.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: teste unitário de `normalizeContent` cobrindo os 6 mapeamentos + null-safety; antes da mudança o contrato cru não tinha `type`/`file_url`/`extracted_text` normalizados.
- [ ] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [ ] `contentsApi.get` e `contentsApi.list` retornam objetos `Content` normalizados; tipo `Content` type-checa com `IMAGE` + `audio_url`; nenhum erro de TypeScript introduzido no API client; `normalizeContent` exportada e coberta por teste.

## QA Results
_(a preencher pelo @qa)_
