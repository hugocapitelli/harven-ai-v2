---
id: MEDIA-4
epic: EPIC-FRONT
phase: 4
status: Draft
severity: HIGH
terminal: UX/UI & Design
complexity: low
depends_on: [MEDIA-1]
bug_refs: [10]
---
# MEDIA-4: Corrigir badges/ícones de tipo em ChapterDetail e CourseDetails

## Story
Como aluno navegando por capítulos e cursos, quero que cada conteúdo exiba o badge e o ícone corretos para o seu tipo real (texto, vídeo, áudio/podcast, imagem, PDF), para que eu entenda imediatamente que mídia vou consumir antes de abrir o conteúdo.

## Contexto (do bug sweep)
Bug item #10 — A mídia não renderiza/identifica corretamente nas telas de listagem de conteúdo. Em `ChapterDetail` e `CourseDetails` o mapa `CONTENT_TYPE_META` não resolve o tipo real do conteúdo: tipos não previstos (ou grafia divergente vinda do backend) caem silenciosamente no fallback `TEXT`, fazendo todos os conteúdos aparecerem como "texto" com o ícone errado. O tipo `IMAGE` simplesmente não existe no mapa, então conteúdos de imagem nunca recebem badge/ícone próprios. Além disso, partes do componente leem o `content_type`/`media_url` cru do registro em vez de derivar o display a partir de um único contrato normalizado, o que produz inconsistência entre telas. Impacto: aluno é induzido a erro sobre o tipo de mídia; UX inconsistente entre ChapterDetail e CourseDetails; mídia (especialmente imagem) renderizada/rotulada de forma incorreta. Depende de MEDIA-1, que normaliza o contrato de tipo de conteúdo no backend — esta story consome esse contrato no frontend.

## Acceptance Criteria
- [ ] `CONTENT_TYPE_META` cobre TODOS os tipos canônicos do contrato (pós MEDIA-1): `TEXT`, `VIDEO`, `AUDIO`/`PODCAST`, `IMAGE`, `PDF` (e qualquer outro definido em MEDIA-1) — cada um com label e ícone próprios.
- [ ] Tipo `IMAGE` adicionado ao mapa com badge e ícone dedicados (não cai em TEXT).
- [ ] O fallback para `TEXT` só ocorre quando o tipo é genuinamente desconhecido/ausente — nunca para um tipo válido por mismatch de grafia/case (a resolução é case-insensitive / normalizada ao contrato).
- [ ] O ícone e o badge renderizados refletem o tipo real do conteúdo em ambas as telas: `ChapterDetail` e `CourseDetails`.
- [ ] Nenhum trecho do componente lê `content_type` cru ou `media_url` diretamente do registro para decidir display — todo o display deriva do contrato normalizado / helper único de resolução de tipo.
- [ ] Comportamento idêntico e consistente entre `ChapterDetail` e `CourseDetails` (mesma fonte de verdade para badge/ícone).

## Tasks / Subtasks
- [ ] Localizar a definição de `CONTENT_TYPE_META` (mapa de tipo → {label, icon}) usada por `ChapterDetail` e `CourseDetails` e confirmar a lista canônica de tipos entregue por MEDIA-1.
- [ ] Adicionar a entrada `IMAGE` (label + ícone) e garantir entradas completas para todos os tipos canônicos do contrato.
- [ ] Substituir a resolução atual por um helper único (ex.: `getContentTypeMeta(type)`) que normaliza o tipo (trim/upper-case) antes do lookup e só faz fallback `TEXT` quando o tipo é realmente desconhecido.
- [ ] Trocar quaisquer leituras de `content_type`/`media_url` cru por consumo do contrato normalizado / helper, em `ChapterDetail`.
- [ ] Aplicar a mesma troca em `CourseDetails`, garantindo paridade de badge/ícone entre as duas telas.
- [ ] Validar visualmente cada tipo (text, video, audio/podcast, image, pdf) exibindo badge + ícone corretos.

## Dev Notes
- **Arquivos:** componentes de frontend `ChapterDetail` e `CourseDetails` (telas de detalhe de capítulo e de curso) + o módulo onde `CONTENT_TYPE_META` está declarado. Caminhos exatos a confirmar via grep por `CONTENT_TYPE_META` no diretório frontend do repo. Consome o contrato de tipo normalizado introduzido por MEDIA-1.
- **Abordagem:** centralizar a resolução de tipo num único mapa/helper completo (incluindo `IMAGE`) com lookup normalizado e case-insensitive; eliminar fallback prematuro para `TEXT` e qualquer leitura de campo cru (`content_type`/`media_url`) no caminho de decisão de display. Display puramente derivado do contrato MEDIA-1.
- **Riscos de regressão:** blast radius restrito às duas telas de listagem/detalhe (`ChapterDetail`, `CourseDetails`). Mudar o helper de resolução de tipo pode afetar qualquer outro componente que reuse `CONTENT_TYPE_META` — verificar consumidores do mapa antes de alterar a assinatura. Adicionar `IMAGE` não deve mudar o display de tipos já corretos. Risco baixo: nenhuma mudança de dados/API, somente apresentação. Dependência dura de MEDIA-1: se o contrato de tipos do backend não estiver normalizado, o lookup ainda pode falhar — confirmar MEDIA-1 concluída antes do QA.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde — caso cobrindo `IMAGE` e um tipo válido com grafia divergente que antes caía em `TEXT`.
- [ ] Sem regressão na suíte de segurança.
- [ ] QA Gate: PASS ou CONCERNS.
- [ ] Cada tipo canônico (TEXT, VIDEO, AUDIO/PODCAST, IMAGE, PDF) exibe badge + ícone corretos e idênticos em `ChapterDetail` e `CourseDetails`; nenhuma leitura de `content_type`/`media_url` cru permanece no caminho de display.

## QA Results
_(a preencher pelo @qa)_
