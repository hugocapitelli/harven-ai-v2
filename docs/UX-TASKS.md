# Harven AI V2 — UX Micro Tasks
## Decomposicao atomica das 17 specs em tasks executaveis

**Gerado:** 26/05/2026 | **Origem:** UX-REVIEW-SPEC.md
**Total:** 72 micro tasks | **Estimativa total:** ~62.5h

---

## Como usar

Cada task e atomica — pode ser executada independentemente dentro do seu bloco.
Tasks com `[BLOCKED BY]` dependem de outra task concluida antes.
Checkboxes para tracking de progresso.

---

# TIER 1: FOUNDATION (~18h)

## SPEC-01: EmptyState Component (~2h)

- [x] **T01.1** — Criar `frontend/src/components/ui/EmptyState.tsx` com interface (icon, title, description, action, size, className). Sizes: sm (py-8), md (py-12 default), lg (py-16). Icone material-symbols em text-4xl/5xl/6xl muted. Titulo font-display, description text-sm muted. Action renderiza Button.
- [x] **T01.2** — Migrar empty state do `StudentDashboard.tsx` para usar `<EmptyState>`. Reescrever texto para tom positivo ("Sua jornada comeca aqui" > "Nenhum curso encontrado").
- [x] **T01.3** — Migrar empty states de `InstructorList.tsx` e `InstructorDetail.tsx`.
- [x] **T01.4** — Migrar empty states de `CourseList.tsx` e `CourseDetails.tsx`.
- [x] **T01.5** — Migrar empty states de `StudentAchievements.tsx` e `StudentHistory.tsx`.
- [x] **T01.6** — Migrar empty states de `AdminConsole.tsx` (logs), `UserManagement.tsx`, `ClassManagement.tsx`.
- [ ] **T01.7** — Verificar que ZERO empty states inline restam no codebase (`grep -r "Nenhum\|Nenhuma\|empty" frontend/src/views/`).

---

## SPEC-02: Modal/Dialog System (~4h)

- [x] **T02.1** — Criar `frontend/src/components/ui/Modal.tsx` com composicao: `Modal.Root` (open, onClose, size), `Modal.Header` (title, onClose com botao X), `Modal.Body` (padding p-6), `Modal.Footer` (flex justify-end gap-3).
- [x] **T02.2** — Implementar backdrop padrao: bg-black/50 + backdrop-blur-sm. Animacao entrada 200ms (scale 0.96->1, opacity 0->1, ease-out). Animacao saida 150ms (opacity 1->0).
- [x] **T02.3** — Implementar focus trap: Tab cicla dentro do modal. Esc fecha. Focus restaurado ao trigger element no fechamento. aria-modal, role="dialog", aria-labelledby.
- [ ] **T02.4** — Refatorar `ConfirmDialog.tsx` para usar `Modal.Root` internamente. Manter API publica identica.
- [x] **T02.5** — Migrar modais de `UserManagement.tsx` (create/edit user) para usar `<Modal>`.
- [x] **T02.6** — Migrar modais de `ClassManagement.tsx` (create discipline, add teacher/student) para usar `<Modal>`.
- [x] **T02.7** — Migrar modais de `AdminConsole.tsx` (acao global, broadcast) para usar `<Modal>`.
- [ ] **T02.8** — Migrar modais de `StudentAchievements.tsx` (achievement detail) para usar `<Modal>`.
- [ ] **T02.9** — Verificar que ZERO modais inline restam (`grep -r "fixed inset-0" frontend/src/views/`). Excecao: componentes que usam Modal internamente.

---

## SPEC-03: Textarea + Toggle (~1.5h)

- [x] **T03.1** — Criar `frontend/src/components/ui/Textarea.tsx`. Mesmas props de label/error/containerClassName do Input. forwardRef. Styling identico ao Input (border-harven-border, bg-harven-bg, focus:border-primary, focus:ring-2). Default rows=4.
- [x] **T03.2** — Criar `frontend/src/components/ui/Toggle.tsx`. Props: checked, onChange, label, description, disabled, size (sm/md). Track bg-muted (off) / bg-primary (on), knob branco, transition 200ms. Layout horizontal (label + description a direita do toggle).
- [x] **T03.3** — Migrar textareas inline em `DisciplineEdit.tsx`, `SessionReview.tsx`, `AdminConsole.tsx` para `<Textarea>`.
- [x] **T03.4** — Migrar toggles/switches inline em `SystemSettings.tsx` para `<Toggle>`.

---

## SPEC-04: SearchInput (~1h)

- [x] **T04.1** — Criar `frontend/src/components/ui/SearchInput.tsx`. Composicao sobre Input com icon="search". Debounce integrado (300ms default). Botao clear (X) quando value.length > 0. Loading state (spinner no lugar do icone).
- [x] **T04.2** — Migrar search input de `CourseList.tsx` para `<SearchInput>`.
- [x] **T04.3** — Migrar search input de `InstructorList.tsx` para `<SearchInput>`.
- [x] **T04.4** — Migrar search input de `ClassManagement.tsx` para `<SearchInput>`.

---

## SPEC-05: StatCard (~1.5h)

- [x] **T05.1** — Criar `frontend/src/components/ui/StatCard.tsx`. Props: icon, value, label, trend (direction + value), loading, variant (default/highlight), className. Valor em font-display text-3xl font-bold. Variante highlight: bg-harven-dark + text-primary.
- [x] **T05.2** — Implementar animated counter: valor conta de 0 ao real em 800ms ease-out ao montar. Usar requestAnimationFrame ou useEffect com interval.
- [x] **T05.3** — Migrar stat cards de `StudentDashboard.tsx` para `<StatCard>`. Eliminar cores ad hoc (text-blue-500 etc).
- [x] **T05.4** — Migrar stat cards de `AdminConsole.tsx` para `<StatCard>`.
- [x] **T05.5** — Migrar stat cards de `InstructorDetail.tsx` para `<StatCard>`.

---

## SPEC-06: DataTable (~6h)

- [ ] **T06.1** — Criar `frontend/src/components/ui/DataTable.tsx` com interface Column<T> (key, header, render, sortable, width, align) e DataTableProps<T> (columns, data, loading, emptyState, pagination, onSort, stickyHeader, rowKey, onRowClick).
- [ ] **T06.2** — Implementar sticky header: position sticky top-0, bg-card z-10, border-b. Padding vertical de linhas: py-4.
- [ ] **T06.3** — Implementar sort: icone chevron no header de colunas sortable. Estado neutro (duplo cinza), ativo (direcional em primary). Callback onSort.
- [ ] **T06.4** — Implementar paginacao: footer com "Exibindo X-Y de Z" + botoes prev/next + seletor pageSize (10/25/50). Componente `Pagination` interno ou inline.
- [ ] **T06.5** — Implementar loading state: renderiza N linhas de Skeleton (usa loadingRows prop, default 5). Implementar empty state: renderiza EmptyState quando data vazio. `[BLOCKED BY T01.1]`
- [ ] **T06.6** — Migrar tabela de `UserManagement.tsx` para `<DataTable>`.
- [ ] **T06.7** — Migrar tabela de `ClassManagement.tsx` (alunos, professores) para `<DataTable>`.
- [ ] **T06.8** — Migrar tabela de `InstructorDetail.tsx` (student list) para `<DataTable>`.
- [ ] **T06.9** — Migrar tabela de `AdminConsole.tsx` (logs) para `<DataTable>`.

---

## SPEC-07: PageHeader (~2h)

- [x] **T07.1** — Criar `frontend/src/components/ui/PageHeader.tsx`. Props: title, subtitle, backAction (label + onClick), breadcrumbs (array de {label, onClick?}), actions (ReactNode), constrained (default true = max-w-7xl mx-auto). mb-8 inferior.
- [x] **T07.2** — Implementar breadcrumbs: items separados por chevron_right, ultimo sem link. Em mobile: colapsa para mostrar apenas nivel superior + current.
- [x] **T07.3** — Migrar headers de views Student (Dashboard, Achievements, History) para `<PageHeader>`.
- [x] **T07.4** — Migrar headers de views Instructor (List, Detail, DisciplineEdit, SessionReview) para `<PageHeader>`. Incluir breadcrumbs em Detail e SessionReview.
- [x] **T07.5** — Migrar headers de views Admin (Console, UserManagement, ClassManagement, SystemSettings) para `<PageHeader>`.
- [x] **T07.6** — Migrar headers de views Courses (List, Details, Edit, ChapterDetail, ChapterReader, ContentCreation, ContentRevision) para `<PageHeader>`. Breadcrumbs obrigatorios em: ChapterDetail, ChapterReader, ContentCreation, ContentRevision (hierarquia: Curso > Capitulo > Conteudo).

---

# TIER 2: USABILITY (~7h)

## SPEC-08: Real-Time Form Validation (~3h)

- [ ] **T08.1** — Adicionar prop `helpText?: string` ao componente `Input.tsx`. Renderiza abaixo do label em text-xs text-muted-foreground. Fazer o mesmo para `Textarea.tsx` e `Select.tsx`. `[BLOCKED BY T03.1]`
- [ ] **T08.2** — Criar hook `useFormValidation` ou utility de validacao. Regras: required, minLength, maxLength, pattern (regex), range (min/max numerico), email, match (confirmacao de senha). Retorna errors por campo, validate(field) para onBlur, validateAll() para submit.
- [ ] **T08.3** — Aplicar validacao onBlur em `Login.tsx`: RA obrigatorio (helpText: "Seu numero de matricula"), senha obrigatoria.
- [ ] **T08.4** — Aplicar validacao onBlur em modal de criacao/edicao de usuario (`UserManagement.tsx`): nome obrigatorio, RA obrigatorio (helpText: "8 digitos numericos"), email valido, senha min 4 chars + confirmacao.
- [ ] **T08.5** — Aplicar validacao em grade inputs de `ClassManagement.tsx` e `InstructorDetail.tsx`: min=0, max=10, step=0.5. Feedback visual quando fora do range. helpText: "Nota de 0 a 10".

---

## SPEC-09: Session Timeout Redesign (~2h)

- [ ] **T09.1** — Criar componente `SessionTimeoutModal.tsx` usando `<Modal>`. Countdown visual (mm:ss) atualizando a cada segundo. Botao primario "Continuar Conectado" (chama API de refresh token). Botao secundario "Sair Agora". `[BLOCKED BY T02.1]`
- [ ] **T09.2** — Integrar no `AuthContext.tsx`: monitorar expiracao do token JWT. Abrir SessionTimeoutModal 5 minutos antes da expiracao. Se countdown = 0: redirect para login com toast "Sessao expirada".
- [ ] **T09.3** — Garantir que durante chat AI ativo, o estado da conversa e preservado antes de redirect (salvar em localStorage ou sessionStorage).

---

## SPEC-10: Terminologia Unificada (~2h)

- [ ] **T10.1** — Criar `frontend/src/lib/i18n.ts` com mapa de termos canonicos (roles, entities, actions, messages). Padrao: portugues (pt-BR). Exportar como objeto tipado `const t = {...} as const`.
- [ ] **T10.2** — Auditar e substituir termos em views Student: "Student" -> t.roles.student, etc.
- [ ] **T10.3** — Auditar e substituir termos em views Instructor e Admin.
- [ ] **T10.4** — Auditar backend (`routes_admin.py`, `routes_ai.py`, `main.py`): normalizar labels de role nas API responses para portugues consistente.

---

# TIER 3: EXPERIENCE (~9.5h)

## SPEC-11: Color System Consolidation (~3h)

- [ ] **T11.1** — Expandir `index.css` @theme com novos tokens: stat-1..4 (escala de verdes), rarity tokens (common, rare, epic, legendary), semanticos (success, warning, info) derivados da paleta Harven.
- [ ] **T11.2** — Migrar `StudentDashboard.tsx`: substituir text-blue-500, text-green-500, text-orange-500, text-yellow-500 por stat-1..4 tokens.
- [ ] **T11.3** — Migrar `StudentAchievements.tsx`: substituir bg-blue-100, bg-purple-100, from-amber-100 por rarity tokens.
- [ ] **T11.4** — Migrar `InstructorList.tsx`: substituir gradientes emerald-teal por bg solida com hover sutil usando tokens do sistema.
- [ ] **T11.5** — Grep final: verificar que ZERO cores Tailwind ad hoc restam (`grep -rn "text-blue\|text-orange\|text-purple\|bg-blue\|bg-purple\|from-emerald\|from-amber" frontend/src/views/`).

---

## SPEC-12: Transitions & Animations (~3h)

- [ ] **T12.1** — Adicionar animacoes de entrada/saida ao Modal (se nao feito em T02.2): scale + opacity com CSS @keyframes ou Tailwind animate.
- [ ] **T12.2** — Criar CSS keyframes para achievement unlock: `@keyframes achievement-common` (glow 400ms), `@keyframes achievement-rare` (scale bounce 600ms + glow), `@keyframes achievement-epic` (scale + radial glow 800ms), `@keyframes achievement-legendary` (full ceremony 1200ms).
- [ ] **T12.3** — Aplicar animacoes em `StudentAchievements.tsx`: ao desbloquear, aplicar classe de animacao por raridade.
- [ ] **T12.4** — Implementar animated counter no `StatCard.tsx` (se nao feito em T05.2): useEffect com requestAnimationFrame, 0->valor em 800ms ease-out.
- [ ] **T12.5** — Criar toast especial para achievement unlock em contexto: quando conquista desbloqueada durante navegacao/chat, mostrar toast com icone da conquista + nome.

---

## SPEC-13: Typography Display Scale (~1.5h)

- [ ] **T13.1** — Atualizar StatCard (T05.1) para usar text-3xl font-display font-bold no valor. Se ja feito, verificar.
- [ ] **T13.2** — Atualizar `StudentAchievements.tsx`: level number no circular progress em text-4xl font-display font-bold.
- [ ] **T13.3** — Atualizar labels globais: mudar de `text-[10px] font-bold uppercase tracking-wider` para `text-[11px] font-normal tracking-normal text-muted-foreground`. Aplicar em Input.tsx, Select.tsx, Textarea.tsx, DataTable headers.
- [ ] **T13.4** — Verificar contraste de peso em titulos: h1 font-bold (700), h2 font-semibold (600), body font-normal (400). Ajustar onde necessario.

---

## SPEC-14: Surface Hierarchy (~2h)

- [ ] **T14.1** — Atualizar Card.tsx: adicionar variant `featured` (bg-harven-dark, text off-white, borders mais sutis). Atualizar bg de cards default para rgba(255,253,248,1) (warm white) em vez de puro #ffffff.
- [ ] **T14.2** — Aplicar `<Card variant="featured">` ao stat card principal de `StudentDashboard.tsx` (streak ou score).
- [ ] **T14.3** — Aplicar `<Card variant="featured">` ao stat card de "Usuarios ativos" em `AdminConsole.tsx`.
- [ ] **T14.4** — Aplicar `<Card variant="featured">` ao stat de "Media da turma" em `InstructorDetail.tsx`.

---

# TIER 4: VISION (~28h)

## SPEC-15: Student Trajectory Visualization (~8h)

- [ ] **T15.1** — Instalar `recharts` (ou lib equivalente) como dependencia frontend.
- [ ] **T15.2** — Criar componente `Sparkline.tsx`: SVG line chart minimal (150x40px default), props: data (number[]), color, areaFill. Sem eixos, sem labels — apenas a linha.
- [ ] **T15.3** — Backend: verificar/criar endpoint `GET /users/{id}/session-history` que retorna array de {date, score, duration} das ultimas 30 sessoes.
- [ ] **T15.4** — Integrar Sparkline no StatCard de score/sessions do `StudentDashboard.tsx`. Dados: ultimas 30 sessoes.
- [ ] **T15.5** — Criar componente `ActivityCalendar.tsx`: grid 7x5 (35 dias), cada quadrado colorido por intensidade de estudo (0=cinza, 1-30min=verde claro, 30-60min=verde medio, 60min+=verde escuro).
- [ ] **T15.6** — Adicionar ActivityCalendar ao `StudentDashboard.tsx` abaixo do streak card.
- [ ] **T15.7** — Criar feature de comparacao com turma: backend expoe `GET /disciplines/{id}/avg-stats`. Frontend renderiza linha dashed muted como referencia. Toggle "Comparar com turma" (off default).

---

## SPEC-16: Instructor Difficulty Heatmap (~8h)

- [ ] **T16.1** — Backend: criar endpoint `GET /disciplines/{id}/chapter-difficulty` que retorna array de {chapter_id, chapter_title, avg_score, total_attempts} agregado por capitulo.
- [ ] **T16.2** — Backend: criar endpoint `GET /chapters/{id}/question-difficulty` que retorna array de {question_id, question_text, avg_score, total_attempts} agregado por pergunta.
- [ ] **T16.3** — Criar componente `HeatmapGrid.tsx`: grid de blocos, cada bloco com cor por valor (verde->amarelo->vermelho). Props: data (array de {id, label, value}), onBlockClick, colorScale. Tooltip no hover com detalhes.
- [ ] **T16.4** — Integrar HeatmapGrid na view `InstructorDetail.tsx`: nova tab "Mapa de Dificuldade" com heatmap por capitulo. Click no bloco expande para heatmap de perguntas.
- [ ] **T16.5** — Backend: criar endpoint `GET /disciplines/{id}/students-at-risk` que retorna alunos com desempenho >20% abaixo da media por 2+ semanas.
- [ ] **T16.6** — Adicionar highlight visual na tabela de alunos de `InstructorDetail.tsx`: alunos em risco com badge amarelo + tooltip explicativo.

---

## SPEC-17: Socratic Dialogue Enhancements (~12h)

### Fase 1: Temperatura Visual (~4h)
- [ ] **T17.1** — Backend: adicionar campo `turn_type` ao response do AI chat: 'confirmation' | 'refinement' | 'refutation' | 'synthesis'. Classificar via prompt engineering no system message da IA.
- [ ] **T17.2** — Frontend: atualizar `ChapterReader.tsx` (ou componente de chat) para ler `turn_type` e aplicar estilo condicional. Confirmation: borda esquerda verde 2px. Refutation: borda esquerda amarela. Synthesis: card com bg diferente + mais espacamento.
- [ ] **T17.3** — Criar toast especial para sintese final: quando turn_type='synthesis', exibir feedback visual mais proeminente (card expandido, animacao sutil de conclusao).

### Fase 2: Mapa de Raciocinio (~8h)
- [ ] **T17.4** — Instalar React Flow como dependencia.
- [ ] **T17.5** — Backend: criar endpoint `GET /sessions/{id}/reasoning-map` que retorna grafo de nos (cada turno = no com type, content_summary) e edges (conexoes de raciocinio).
- [ ] **T17.6** — Criar componente `ReasoningMap.tsx`: renderiza grafo com React Flow + dagre layout. Nos coloridos por tipo (hipotese=azul marca, refutacao=amarelo, confirmacao=verde, conclusao=limao). Click no no destaca mensagem correspondente no chat.
- [ ] **T17.7** — Integrar ReasoningMap no `ChapterReader.tsx`: panel lateral em desktop (30% width), expandivel em mobile.
- [ ] **T17.8** — Integrar ReasoningMap no `SessionReview.tsx` para instrutores: substituir leitura linear de transcricao por navegacao visual do grafo.

---

# RESUMO EXECUTIVO

| Tier | Tasks | Esforco | Dependencias |
|:---|:---:|:---:|:---|
| **1 Foundation** | 37 tasks | ~18h | Nenhuma (pode iniciar imediatamente) |
| **2 Usability** | 12 tasks | ~7h | T01.1 (EmptyState), T02.1 (Modal), T03.1 (Textarea) |
| **3 Experience** | 14 tasks | ~9.5h | Tier 1 concluido (usa componentes novos) |
| **4 Vision** | 19 tasks | ~28h | Tier 1+2 concluidos + endpoints backend |
| **TOTAL** | **72 tasks** | **~62.5h** | — |

## Ordem de Execucao — Caminho Critico

```
T01.1 ──→ T01.2..T01.7 (EmptyState: create + migrate)
T02.1 ──→ T02.2 ──→ T02.3 ──→ T02.4..T02.9 (Modal: create + migrate)
T03.1 ──→ T03.2 ──→ T03.3..T03.4 (Textarea/Toggle: create + migrate)
T04.1 ──→ T04.2..T04.4 (SearchInput: create + migrate)
T05.1 ──→ T05.2 ──→ T05.3..T05.5 (StatCard: create + animate + migrate)
T06.1 ──→ T06.2..T06.4 ──→ T06.5 [T01.1] ──→ T06.6..T06.9 (DataTable)
T07.1 ──→ T07.2 ──→ T07.3..T07.6 (PageHeader: create + breadcrumbs + migrate)

Tier 2 pode iniciar em paralelo com Tier 1 (exceto T08.1 que depende de T03.1, T09.1 de T02.1)

Tier 3 inicia apos componentes base existirem.
Tier 4 inicia apos Tier 1+2 + endpoints backend criados.
```

## Blocos Paralelizaveis

| Bloco | Tasks | Podem rodar simultaneamente |
|:---|:---|:---|
| Atomos | T01.1, T03.1, T03.2, T04.1 | Sim — independentes |
| Organismos | T02.1, T06.1, T07.1 | Sim — independentes |
| Migracoes EmptyState | T01.2..T01.7 | Sim — views diferentes |
| Migracoes Modal | T02.5..T02.9 | Sim — views diferentes |
| Color + Typography | T11.1..T11.5, T13.1..T13.4 | Sim — CSS vs componentes |

---

*Micro tasks geradas por J.A.R.V.I.S. — 26/05/2026*
