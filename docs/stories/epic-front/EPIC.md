---
id: EPIC-FRONT
title: Frontend Read Contracts + Student Flow
status: Draft
phases: [4]
story_count: 7
---
# EPIC-FRONT: Frontend Read Contracts + Student Flow

## Objetivo

Reparar a fronteira de leitura do frontend e fechar o fluxo do aluno de ponta a ponta. Hoje o backend emite a row crua (`content_type` minúsculo, `media_url`/`audio_url`) e o frontend lê um contrato que o backend nunca produziu (`type` maiúsculo, `file_url`) — toda renderização de mídia (vídeo/áudio/imagem) está morta e escondida atrás de `@ts-nocheck`, que impede o compilador de pegar o desencontro de contrato. Além disso, o fluxo do aluno está quebrado em três pontos: o chat socrático trava os botões após o primeiro close, "Reprocessar IA" envia `Authorization` vazio (lê a chave errada do sessionStorage), e "Concluir" chama um endpoint quebrado (`contentsApi.update({completed})`) em vez de escrever progresso/pontos/conclusão de sessão por-usuário.

Este epic introduz um **adapter de contrato de leitura único** (`normalizeContent`) aplicado no API client, faz a mídia renderizar de verdade via `file_url`, **remove `@ts-nocheck` e faz os arquivos type-checarem** (gate frontend do CI), corrige badges/ícones de tipo, e religa o fluxo do aluno (chat reset, reprocess via axios, conclusão por-usuário). Cobre os defeitos verificados #10 (contrato de mídia), #21 (botões do chat travados), #23 (token errado no reprocess) e #24 (conclusão não escreve progresso).

Terminal primário: **UX/UI & Design** (epic 100% frontend). Fase 4.

## Critérios de Saída (Exit Criteria)

- `normalizeContent` aplicado em `contentsApi.get` e `contentsApi.list`: mapeia `content_type`→`type` (lower e legado upper), `media_url`→`file_url`, preserva `body`/`audio_url`, alias `extracted_text`←`body`; tipo `Content` inclui `IMAGE` e `audio_url`; null-safe.
- Mídia renderiza via `file_url`: VIDEO/AUDIO/IMAGE disparam no `ChapterReader` e no `ContentRevision` (instrutor); `@ts-nocheck` **removido** de ambos e os arquivos type-checam (`tsc -b` passa).
- `CONTENT_TYPE_META` resolve o tipo real (não cai sempre no fallback `TEXT`), inclui `IMAGE`, e ícone/badge refletem o tipo — sem leitura de `content_type`/`media_url` crus em `ChapterDetail` e `CourseDetails`.
- Chat: o close limpa `selectedQuestion`/`sessionId`/`chatMessages`, re-habilitando os botões socráticos; nova pergunta inicia novo diálogo; sem `setChatOpen(false)` inline.
- `aiApi.reprocessContent` posta `/api/ai/reprocess-content` via axios compartilhado (com token correto) — **sem** `sessionStorage.getItem('access_token')`, **sem** `fetch` manual; branches success/empty/error preservados.
- "Concluir" chama `userStatsApi.completeContent(user.id, ...)` + `chatSessionsApi.complete` — **não** chama `contentsApi.update({completed})`; 503 (tabelas ausentes) = soft-success; sucesso → badge "Concluído" (não reclicável); certificado deliberadamente adiado/documentado.

## Stories

| ID | Título | Fase | Terminal | Compl. | Depende de | Severidade |
|:--|:--|:--:|:--|:--:|:--|:--:|
| MEDIA-1 | Adapter de contrato de leitura de conteúdo + wire no API client | 4 | UX/UI & Design | low | — | HIGH |
| MEDIA-2 | Renderizar vídeo/áudio/imagem no ChapterReader + remover `@ts-nocheck` | 4 | UX/UI & Design | med | MEDIA-1 | HIGH |
| MEDIA-3 | Renderizar mídia no ContentRevision (instrutor) + remover `@ts-nocheck` | 4 | UX/UI & Design | low | MEDIA-1 | HIGH |
| MEDIA-4 | Corrigir badges/ícones de tipo em ChapterDetail e CourseDetails | 4 | UX/UI & Design | low | MEDIA-1 | HIGH |
| SF-1 | Resetar estado local do chat no close (re-habilitar botões socráticos) | 4 | UX/UI & Design | low | MEDIA-2 | HIGH |
| SF-2 | Rotear 'Reprocessar IA' pelo axios compartilhado com token correto | 4 | UX/UI & Design | low | MEDIA-2 | HIGH |
| SF-3 | Ligar conclusão de conteúdo a progress/cert/session-complete por-user | 4 | UX/UI & Design | med | SEC-ADMIN-4, MEDIA-2, SF-1 | HIGH |

## Sequência / Caminho Crítico interno

```
MEDIA-1 (adapter — gate, sem deps)
   ├─→ MEDIA-2 (ChapterReader render + remove @ts-nocheck)  ← keystone interno
   │       ├─→ SF-1 (chat reset)
   │       ├─→ SF-2 (reprocess via axios)
   │       └─→ SF-3 (conclusão por-user) ── + dep externa SEC-ADMIN-4, e SF-1
   ├─→ MEDIA-3 (ContentRevision render + remove @ts-nocheck)
   └─→ MEDIA-4 (badges/ícones de tipo)
```

**MEDIA-1 é o gate de TODO o epic.** Define o contrato de leitura único (`normalizeContent` + tipo `Content`); MEDIA-2/3/4 consomem o tipo normalizado, e a cadeia do aluno (SF-1/2/3) pende de MEDIA-2.

**MEDIA-2 é o keystone interno** — é o primeiro a remover `@ts-nocheck` de `ChapterReader.tsx`. SF-1/2/3 (e, do EPIC-AI, TPP-6; do EPIC-PODCAST, frontend TTSJOB; do EPIC-CLEANUP, CDC-8) **rebaseiam** sobre essa remoção. Por isso MEDIA-2 deve aterrissar antes que qualquer outra Story toque `ChapterReader.tsx`.

**MEDIA-3 e MEDIA-4 são paralelizáveis** após MEDIA-1 — tocam arquivos distintos (`ContentRevision.tsx`, `ChapterDetail.tsx`/`CourseDetails.tsx`) e não dependem de MEDIA-2.

**SF-3 tem dependência cross-epic:** depende de **SEC-ADMIN-4** (EPIC-SEC — endurecimento de writes admin/escopo por-usuário no backend de conclusão). Não iniciar SF-3 até SEC-ADMIN-4 ter aterrissado; caso contrário a conclusão pode escrever sem o guard de escopo correto.

## Notas de Arquitetura

**Single owner de `ChapterReader.tsx` (coordenação obrigatória — roadmap §3, tabela de conflito de arquivo).** A região de `ChapterReader.tsx` é disputada por múltiplos clusters. **MEDIA-2 é o dono que remove `@ts-nocheck` primeiro**; todos os demais (TPP-6 do EPIC-AI, frontend POD/TTSJOB do EPIC-PODCAST, SF-1/2/3 deste epic, CDC-8 do EPIC-CLEANUP) **rebaseiam** sobre a versão type-checada. Sequenciar: MEDIA-2 land → demais rebaseiam. Sem isso, removidores concorrentes de `@ts-nocheck` colidem e o ganho de type-safety se perde em merge.

**Adapter de contrato como ponto único (`normalizeContent`).** O fix corrige a desconexão na **fronteira do client da API**, não espalhando reads crus pelas views. `normalizeContent` vive no API service (`frontend/src/services/api.ts`) e é aplicado em `contentsApi.get` e `contentsApi.list` (linhas 136 e 135 hoje). Mapeamento canônico:
- `content_type` (lower, ou legado upper) → `type` (maiúsculo canônico)
- `media_url`/`audio_url` → `file_url` (preservando `audio_url` original)
- `body` preservado; `extracted_text` aliasado de `body` (o frontend lê `extracted_text` em pontos, mas o backend só retorna `body` — ver achado LOW de contrato morto)
- null-safe: row parcial/sem mídia não quebra.

O tipo `Content` (em `frontend/src/types/`) ganha `IMAGE` no union de `type` e o campo `audio_url`. Após normalizar na fronteira, **nenhuma view lê `content_type`/`media_url` crus** — esse é o invariante que MEDIA-4 (e o type-checker pós-`@ts-nocheck`) impõem.

**`@ts-nocheck` é o gate do CI frontend.** Os 6 arquivos de `views/courses/` carregam `@ts-nocheck` hoje (`ChapterReader`, `ContentRevision`, `ChapterDetail`, `CourseDetails`, `CourseEdit`, `CourseList`). Este epic remove de **ChapterReader (MEDIA-2)**, **ContentRevision (MEDIA-3)** e corrige os reads de tipo em **ChapterDetail/CourseDetails (MEDIA-4)**. O CI job `frontend` exige `npm run build` com `tsc -b` passando — ou seja, remover `@ts-nocheck` força o compilador a pegar o #10 estaticamente. Remoção parcial é aceitável (CourseEdit/CourseList ficam para EPIC-CLEANUP onde forem tocados), mas todo arquivo que este epic toca deve type-checar.

**`CONTENT_TYPE_META` resolve real, não fallback.** Em `ChapterDetail.tsx:182`, `CONTENT_TYPE_META[content.type] ?? CONTENT_TYPE_META.TEXT` cai sempre no `TEXT` porque `content.type` era undefined (backend não emitia `type`). Pós-MEDIA-1, `type` é populado; MEDIA-4 adiciona a entrada `IMAGE` ao mapa e garante que ícone/cor/label reflitam o tipo real em ambas as telas.

**Fluxo do aluno — endpoints já existem no client, só não eram chamados.** `userStatsApi.completeContent(userId, courseId, contentId)` (api.ts:257) e `chatSessionsApi.complete(sessionId)` (api.ts:270) já existem mas têm zero callers (grep confirma). SF-3 religa "Concluir" a eles e **remove** a chamada quebrada `contentsApi.update(contentId, {completed:true})`. Tratamento de 503 como **soft-success** (tabelas de progresso/gamificação podem estar ausentes atrás de kill-switch da MIGRATION C `persist_tutor_turns_enabled`/gamificação) — a UI marca "Concluído" e não reclica, sem quebrar se o backend ainda não persiste. **Certificado fica deliberadamente fora de escopo** (gap aberto #2 do roadmap: detecção de course-completion é follow-up documentado) — SF-3 não chama `issueCertificate`/`complete_course`.

**Reprocess via axios compartilhado (SF-2).** O `handleReprocess` atual (ChapterReader.tsx:513-522) monta `fetch` manual lendo `sessionStorage.getItem('access_token')`, mas o token vive em `'harven-access-token'` (AuthContext.tsx:36, lido pelo interceptor em api.ts:15) → `Authorization: Bearer ` vazio → 401/403 sempre. SF-2 substitui por `aiApi.reprocessContent` que posta `/api/ai/reprocess-content` pelo client axios — o interceptor injeta o token correto automaticamente. Sem `fetch` manual, sem leitura direta de sessionStorage. Preservar os branches de UI success/empty/error.

**Reset de estado do chat (SF-1).** Os botões socráticos são gateados por `!selectedQuestion && startChat(...)` e `disabled={Boolean(selectedQuestion && selectedQuestion !== q.question)}` (ChapterReader.tsx:1090-1095, 913-914, 333-337). O close só faz `setChatOpen(false)` e nunca reseta `selectedQuestion`/`sessionId`/`chatMessages` → após o primeiro ciclo abrir/fechar, todos os botões ficam travados. SF-1 extrai um `closeChat()` que limpa os três estados, eliminando o `setChatOpen(false)` inline. Re-habilitar os botões depende da renderização correta da mídia (MEDIA-2) já estar no lugar para não rebasear duas vezes.

**Convenção de chave de token.** Token de acesso é armazenado/lido sob `'harven-access-token'` (não `'access_token'`). Qualquer leitura de token neste epic usa o client axios compartilhado (que já resolve a chave via interceptor) — nunca `sessionStorage` direto. Isso compõe com o E2E smoke do roadmap (login com token key `harven-access-token`, #23).
