# Harven AI V2 — UX Review Spec
## Resultado da Revisao Multi-Expert (26/05/2026)

**Painel:** Don Norman (usabilidade) + Bret Victor (interacao) + Brad Frost (design system) + Jony Ive (craft visual)
**Total de recomendacoes:** 28 | **Sintetizadas em:** 17 specs executaveis em 4 tiers

---

## Tier 1: Foundation (Design System)
> Componentes que desbloqueiam consistencia em TODAS as views.
> Prioridade: executar ANTES de qualquer outra melhoria.

---

### SPEC-01: EmptyState Component
**Origem:** Frost #1 (Critica) + Ive #7 (Media)
**Tipo:** Molecula
**Esforco:** ~2h

**Problema:**
8+ implementacoes inline com markup quase identico. Estados vazios sao tratados como excecao tecnica, nao como momento de design.

**Spec:**
Criar `frontend/src/components/ui/EmptyState.tsx`:

```tsx
interface EmptyStateProps {
  icon: string;              // material-symbols-outlined name
  title: string;
  description?: string;
  action?: {
    label: string;
    onClick: () => void;
    variant?: 'primary' | 'outline';
  };
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}
```

**Requisitos:**
- Tamanhos: sm (py-8), md (py-12, default), lg (py-16)
- Icone em text-4xl (sm), text-5xl (md), text-6xl (lg), cor muted
- Titulo em font-display, description em text-sm text-muted-foreground
- Action renderiza Button com variant especificado
- Texto orientado a possibilidade, nao a ausencia: "Sua turma esta pronta para receber alunos" > "Nenhum aluno cadastrado"

**Migrar em:**
- StudentDashboard, InstructorList, StudentAchievements, StudentHistory
- AdminConsole (logs), CourseList, ClassManagement, UserManagement

**Impacto:** ~400 LOC removidos, consistencia visual de estados vazios em 100% das views.

---

### SPEC-02: Modal/Dialog System
**Origem:** Norman #4 (Alta) + Frost #2 (Critica) + Ive #5 (Media-Alta)
**Tipo:** Organismo
**Esforco:** ~4h

**Problema:**
Modais construidos do zero em cada view. Backdrop inconsistente (blur vs nao), padding (p-4 vs p-6), sem botao X, sem focus trap universal, sem animacao de entrada.

**Spec:**
Criar `frontend/src/components/ui/Modal.tsx` com composicao:

```tsx
// Modal.Root
interface ModalRootProps {
  open: boolean;
  onClose: () => void;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  children: React.ReactNode;
}

// Modal.Header
interface ModalHeaderProps {
  title: string;
  onClose?: () => void;  // renderiza botao X
}

// Modal.Body — wrapper com padding padrao p-6
// Modal.Footer — flex justify-end gap-3
```

**Requisitos:**
- Backdrop: bg-black/50 + backdrop-blur-sm (SEMPRE)
- Animacao entrada: 200ms, scale 0.96->1.0, opacity 0->1, ease-out
- Animacao saida: 150ms, opacity 1->0
- Botao X no header (OBRIGATORIO se onClose fornecido)
- Focus trap: Tab cicla dentro do modal
- Esc fecha o modal
- Restauracao de foco ao elemento disparador no fechamento
- aria-modal="true", role="dialog", aria-labelledby
- Refatorar ConfirmDialog para usar Modal internamente

**Migrar em:** Todos os modais de UserManagement, ClassManagement, AdminConsole, StudentAchievements, etc.

**Impacto:** ~200+ LOC removidos, acessibilidade universal em modais, UX consistente.

---

### SPEC-03: Textarea + Toggle Atoms
**Origem:** Frost #6 (Alta) + Norman #2 (Alta, parcial)
**Tipo:** Atomo
**Esforco:** ~1.5h

**Problema:**
Textareas inline com styling inconsistente. Toggles em SystemSettings com logica customizada.

**Spec:**
Criar `frontend/src/components/ui/Textarea.tsx`:

```tsx
interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
  containerClassName?: string;
  rows?: number; // default: 4
}
```

Criar `frontend/src/components/ui/Toggle.tsx`:

```tsx
interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: string;
  description?: string;
  disabled?: boolean;
  size?: 'sm' | 'md';
}
```

**Requisitos:**
- Textarea segue EXATAMENTE o padrao visual do Input (border, bg, focus ring, label style, error style)
- Toggle: track em bg-muted (off) / bg-primary (on), knob branco, transicao 200ms
- Toggle com label e description inline (layout horizontal)
- Ambos com forwardRef e suporte a disabled

**Impacto:** Completa a camada atomica, ~80 LOC de componente, elimina inconsistencias em todos os forms.

---

### SPEC-04: SearchInput Molecule
**Origem:** Frost #4 (Alta)
**Tipo:** Molecula
**Esforco:** ~1h

**Problema:**
3 implementacoes inline com styling e comportamento de debounce variavel.

**Spec:**
Criar `frontend/src/components/ui/SearchInput.tsx`:

```tsx
interface SearchInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;    // default: "Buscar..."
  debounceMs?: number;     // default: 300
  loading?: boolean;       // spinner no lugar do icone
  onClear?: () => void;    // botao X quando ha valor
  className?: string;
}
```

**Requisitos:**
- Composto sobre Input existente com icon="search"
- Debounce integrado (useEffect + setTimeout)
- Botao clear (X) aparece quando value.length > 0
- Loading substitui icone search por spinner animado
- Focus ring segue padrao do Input

**Migrar em:** CourseList, InstructorList, ClassManagement (+ futuras views)

**Impacto:** ~80 LOC removidos, debounce consistente, UX de busca padronizada.

---

### SPEC-05: StatCard Molecule
**Origem:** Frost #3 (Alta) + Ive #2 (Alta, tipografia display) + Victor #6 (parcial)
**Tipo:** Molecula
**Esforco:** ~1.5h

**Problema:**
4 implementacoes diferentes de icone + numero + rotulo. Cores ad hoc (blue-500, green-500, etc.). Numeros sem peso visual.

**Spec:**
Criar `frontend/src/components/ui/StatCard.tsx`:

```tsx
interface StatCardProps {
  icon: string;
  value: string | number;
  label: string;
  trend?: {
    direction: 'up' | 'down' | 'neutral';
    value: string;
  };
  loading?: boolean;
  variant?: 'default' | 'highlight';
  className?: string;
}
```

**Requisitos:**
- Valor em font-display text-3xl font-bold (tipografia display — Ive #2)
- Variante default: bg-card, texto escuro
- Variante highlight: bg-harven-dark, valor em text-primary (limao)
- Trend: seta up/down com texto verde/vermelho + valor percentual
- Loading: Skeleton integrado
- SEM cores ad hoc (text-blue-500 etc.) — usar apenas tokens do sistema
- Animacao de contagem no valor ao carregar (0 -> valor real em 800ms, ease-out — Ive #5)

**Migrar em:** StudentDashboard, AdminConsole, InstructorDetail, ClassManagement

**Impacto:** ~140 LOC removidos, hierarquia visual dramaticamente melhorada, metricas com peso emocional.

---

### SPEC-06: DataTable Organism
**Origem:** Norman #5 (Media-Alta) + Frost #5 (Alta) + Ive #3 (Alta, espacamento)
**Tipo:** Organismo
**Esforco:** ~6h

**Problema:**
Tabelas construidas do zero em cada view. Sem sticky headers, sem sort, sem paginacao.

**Spec:**
Criar `frontend/src/components/ui/DataTable.tsx`:

```tsx
interface Column<T> {
  key: string;
  header: string;
  render?: (value: any, row: T) => React.ReactNode;
  sortable?: boolean;
  width?: string;
  align?: 'left' | 'center' | 'right';
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  loading?: boolean;
  loadingRows?: number;       // default: 5
  emptyState?: React.ReactNode;
  selectable?: boolean;
  onSelectionChange?: (selected: T[]) => void;
  pagination?: {
    page: number;
    pageSize: number;
    total: number;
    onPageChange: (page: number) => void;
    pageSizeOptions?: number[];
  };
  onSort?: (key: string, direction: 'asc' | 'desc') => void;
  stickyHeader?: boolean;     // default: true
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  className?: string;
}
```

**Requisitos:**
- Sticky header: position sticky, top 0, bg-card, z-10
- Sort: chevron up/down no header, estado neutro (cinza duplo), ativo (limao direcional)
- Paginacao: footer com "Exibindo 1-25 de 142" + botoes prev/next + seletor de pageSize
- Loading: renderiza Skeleton rows (usa loadingRows para quantidade)
- Empty: renderiza EmptyState (SPEC-01) quando data.length === 0
- Hover row: bg-muted/50 transition-colors
- Padding vertical linhas: py-4 (Ive #3 — respiracao)
- Coluna de acoes: largura fixa (w-24 ou w-32)
- Selecao: checkbox na primeira coluna, header checkbox seleciona todos

**Migrar em:** UserManagement, ClassManagement, InstructorDetail (student table), AdminConsole (logs)

**Impacto:** ~300+ LOC removidos, usabilidade de tabelas transformada, funcionalidades avancadas disponíveis para todo o sistema.

---

### SPEC-07: PageHeader Organism
**Origem:** Frost #7 (Media) + Norman #1 (Critica, breadcrumbs)
**Tipo:** Organismo
**Esforco:** ~2h

**Problema:**
Headers de pagina repetidos inline. Sem breadcrumbs em hierarquias profundas. Inconsistencia de max-width.

**Spec:**
Criar `frontend/src/components/ui/PageHeader.tsx`:

```tsx
interface PageHeaderProps {
  title: string;
  subtitle?: string;
  backAction?: {
    label?: string;
    onClick: () => void;
  };
  breadcrumbs?: Array<{ label: string; onClick?: () => void }>;
  actions?: React.ReactNode;
  constrained?: boolean; // default: true (max-w-7xl)
  className?: string;
}
```

**Requisitos:**
- Breadcrumbs: items separados por chevron (>), ultimo item sem link (current)
- Em mobile: breadcrumbs colapsam para mostrar apenas nivel imediatamente superior
- Back button: icone arrow_back + label opcional
- Acoes: slot a direita para botoes
- Titulo: font-display text-2xl font-bold
- Subtitulo: text-sm text-muted-foreground
- Constrained: max-w-7xl mx-auto (padrao canônico)
- Espaco inferior: mb-8 (48px ate primeiro conteudo — Ive #3)

**Migrar em:** TODAS as views que tem header de pagina

**Impacto:** ~150 LOC removidos, navegacao orientada em hierarquias profundas, consistencia de layout.

---

## Tier 2: Usability (UX Fixes)
> Correcoes que impactam diretamente a experiencia do usuario.

---

### SPEC-08: Real-Time Form Validation
**Origem:** Norman #2 (Alta)
**Tipo:** Enhancement
**Esforco:** ~3h

**Problema:**
Validacao apenas no submit. Campos sem help text. Grade inputs sem feedback de range.

**Spec:**
- Adicionar validacao onBlur em TODOS os campos obrigatorios
- Mensagem de erro aparece abaixo do campo apos blur, nao apos submit
- Help text persistente: adicionar prop `helpText?: string` ao Input e Textarea
  - Renderiza abaixo do label, em text-xs text-muted-foreground
  - Exemplo: "RA / Matricula — 8 digitos numericos, ex: 20240142"
- Grade inputs: adicionar atributos min=0, max=10, step=0.5
  - Feedback visual quando valor fora do range (border-warning, texto "Valor deve ser entre 0 e 10")
- Password fields: adicionar confirmacao quando em modo create/edit

**Views afetadas:** Login, UserManagement (create/edit modal), ClassManagement (grade editor), DisciplineEdit

---

### SPEC-09: Session Timeout Redesign
**Origem:** Norman #3 (Alta)
**Tipo:** Enhancement
**Esforco:** ~2h

**Problema:**
Aviso vago ("expirara em breve") sem temporalidade e sem acao de extensao.

**Spec:**
Redesenhar o toast de timeout como modal leve (usando SPEC-02):
- Countdown visual: "Sua sessao expira em 4:32" (atualiza a cada segundo)
- Botao primario: "Continuar Conectado" (renova token via API call)
- Botao secundario: "Sair Agora"
- Aparece 5 minutos antes da expiracao
- Se countdown chega a 0: redirect para login com toast "Sessao expirada"
- Durante chat AI: preservar estado do chat antes de redirect

---

### SPEC-10: Terminologia Unificada + i18n Lite
**Origem:** Norman #6 (Media)
**Tipo:** Refactor
**Esforco:** ~2h

**Problema:**
Termos mistos: Aluno/Student, Professor/Instructor/Teacher.

**Spec:**
- Criar `frontend/src/lib/i18n.ts` com constantes de interface:
  ```tsx
  export const t = {
    roles: {
      student: 'Aluno',
      instructor: 'Professor',
      admin: 'Administrador',
    },
    entities: {
      discipline: 'Disciplina',
      course: 'Curso',
      chapter: 'Capitulo',
      // ...
    }
  } as const;
  ```
- Auditar e substituir todos os termos hardcoded no frontend
- Padronizar em portugues (pt-BR) como lingua canonica
- Backend: normalizar role labels na API response

---

## Tier 3: Experience (Visual Refinement)
> Elevacao visual e emocional da interface.

---

### SPEC-11: Color System Consolidation
**Origem:** Ive #1 (Critica)
**Tipo:** Refactor
**Esforco:** ~3h

**Problema:**
Cores ad hoc do Tailwind (text-blue-500, bg-purple-100, gradientes emerald-teal) que nao pertencem ao sistema.

**Spec:**
Atualizar `index.css` @theme com paleta expandida:

```css
/* Semanticos derivados da marca */
--color-stat-1: #1c2d1b;         /* verde escuro (stat cards) */
--color-stat-2: #2a4528;         /* verde medio */
--color-stat-3: #3d6339;         /* verde claro */
--color-stat-4: #8a7a4f;         /* ouro (premium) */

/* Raridade de conquistas */
--color-rarity-common: #3d6339;
--color-rarity-rare: #1c2d1b;
--color-rarity-epic: #8a7a4f;
--color-rarity-legendary: #d0ff00;

/* Semanticos */
--color-success: #3d6339;
--color-warning: #c9a227;
--color-info: #2a4528;
```

**Migrar:**
- StudentDashboard stat cards: substituir text-blue-500 etc por stat-1..4
- StudentAchievements: substituir bg-blue-100 etc por rarity tokens
- InstructorList: substituir gradientes por bg solida com hover sutil
- Eliminar TODA cor Tailwind ad hoc que nao seja token do sistema

---

### SPEC-12: Transition & Animation System
**Origem:** Ive #5 (Media-Alta) + Victor #3 (conquistas) + Norman #4 (modais)
**Tipo:** Enhancement
**Esforco:** ~3h

**Problema:**
Modais aparecem instantaneamente. Conquistas desbloqueiam sem celebracao. Numeros sao estaticos.

**Spec:**
1. **Modal transitions** (integrar em SPEC-02):
   - Entrada: scale(0.96) -> scale(1), opacity 0->1, 200ms ease-out
   - Saida: opacity 1->0, 150ms
   - Backdrop: opacity 0->1, 150ms

2. **Achievement unlock animation:**
   - Comum: brilho sutil na borda (box-shadow limao, 400ms)
   - Rara: scale 1.0 -> 1.1 -> 1.0 (600ms) + brilho
   - Epica: scale + glow radial limao expandindo do centro (800ms)
   - Lendaria: tela escurece levemente + card centralizado + particulas (1200ms)
   - Implementar com CSS @keyframes (sem lib extra)

3. **Animated counters:**
   - StatCard valores: contagem de 0 ate valor real em 800ms ease-out
   - Progress bars: ja animados (manter)

4. **Toast para achievement unlock em contexto:**
   - Quando conquista desbloqueada durante chat/estudo: toast especial com icone da conquista + "Conquista desbloqueada: {nome}"

---

### SPEC-13: Typography Display Scale
**Origem:** Ive #2 (Alta)
**Tipo:** Enhancement
**Esforco:** ~1.5h

**Problema:**
Metricas e numeros de destaque nao tem peso visual. Tudo parece "informacao", nada parece "conquista".

**Spec:**
- Adicionar escala display para numeros: text-4xl (36px), text-5xl (48px) em font-display font-bold
- Aplicar em: StatCard valor (SPEC-05), StudentAchievements level number, progress percentages
- Labels de 10px uppercase -> 11px, font-normal, tracking-normal, text-muted-foreground (mais suave)
- Aumentar contraste de peso: titulos 700, subtitulos 600, corpo 400
- Espacamento entre label e campo: 8px (mb-2) em vez de 6px (mb-1.5)

---

### SPEC-14: Surface Hierarchy
**Origem:** Ive #4 (Alta)
**Tipo:** Enhancement
**Esforco:** ~2h

**Problema:**
Todos os cards tem a mesma materialidade. Sem distincao de profundidade entre informacao critica e secundaria.

**Spec:**
Definir 3 niveis de superficie:
1. **Ground** — bg #f5f5f0 (ja existente)
2. **Elevated** — cards com bg rgba(255,253,248,1) (warm white, nao puro), shadow-sm (ja existente)
3. **Featured** — cards com bg-harven-dark, texto off-white, valor em text-primary (limao)

Aplicar:
- StudentDashboard: stat card principal (streak ou score) como Featured
- AdminConsole: stat card de "Usuarios ativos" como Featured
- InstructorDetail: stat de "Media da turma" como Featured
- Demais cards como Elevated (maioria ja esta)

Adicionar variant `featured` ao Card:
```tsx
<Card variant="featured">...</Card>
```

---

## Tier 4: Vision (Transformative Features)
> Features que diferenciam o produto. Complexidade maior, impacto estrategico.

---

### SPEC-15: Student Trajectory Visualization
**Origem:** Victor #1 (sparklines) + Victor #6 (streak context)
**Tipo:** Feature
**Esforco:** ~8h

**Problema:**
Alunos veem numeros isolados sem contexto temporal. Nao sabem se estao melhorando.

**Spec:**
1. **Sparkline de evolucao** no StudentDashboard:
   - Grafico de linha sutil (150x40px) dentro de cada StatCard de score/sessions
   - Dados: ultimas 30 sessoes, pontuacao por sessao
   - Lib: recharts (Sparkline component) ou custom SVG path
   - Cor: linha em primary (#d0ff00), area preenchida em primary/10

2. **Calendario de atividade** (tipo GitHub contributions):
   - Grid de 30 dias, cada dia = quadrado colorido (intensidade = tempo de estudo)
   - Expandir ao clicar: mostra detalhes do dia
   - Posicao: abaixo do streak card ou como card dedicado

3. **Comparacao com turma** (nivel intermediario):
   - Linha de referencia sutil (dashed, cor muted) representando media da turma
   - Sem nomes — apenas "media da turma"
   - Toggle: "Comparar com turma" (off por padrao — progressive disclosure)

**Dependencias:** Backend deve expor endpoint de historico de sessoes por aluno (provavelmente ja existe).

---

### SPEC-16: Instructor Difficulty Heatmap
**Origem:** Victor #4
**Tipo:** Feature
**Esforco:** ~8h

**Problema:**
Instrutores veem notas individuais mas nao padroes coletivos. Nao sabem qual capitulo esta "quebrando" a turma.

**Spec:**
1. **Heatmap por capitulo** na view de disciplina:
   - Grid de blocos, cada bloco = capitulo
   - Cor: verde (taxa acerto alta) -> amarelo -> vermelho (taxa acerto baixa)
   - Hover: tooltip com "Cap. 3: Analise de Solo — 42% media de acerto"

2. **Drill-down por pergunta:**
   - Click no bloco -> expande para mostrar perguntas do capitulo
   - Cada pergunta como sub-bloco com mesma escala de cor
   - Identifica a pergunta problematica

3. **Alerta de estudante em risco:**
   - Linha do estudante vs curva da turma
   - Quando gap > 20% por 2+ semanas: highlight amarelo no nome do aluno na tabela
   - Tooltip: "Desempenho 25% abaixo da media da turma nas ultimas 3 semanas"

**Dependencias:** Backend precisa expor agregacoes por capitulo/pergunta. Lib: Nivo heatmap ou custom CSS grid.

---

### SPEC-17: Socratic Dialogue Enhancements
**Origem:** Victor #2 (mapa raciocinio) + Victor #7 (temperatura visual)
**Tipo:** Feature
**Esforco:** ~12h (complexo)

**Problema:**
Chat socratico e lista de mensagens uniforme. Progressao intelectual invisivel. Feedback visual nao reflete qualidade da resposta.

**Spec:**
1. **Temperatura visual do chat** (fase 1 — mais simples):
   - Backend retorna metadata por mensagem: `{type: 'confirmation' | 'refinement' | 'refutation' | 'synthesis'}`
   - Mensagem de confirmacao forte: borda esquerda verde sutil (2px)
   - Mensagem de refutacao: borda esquerda amarela sutil
   - Sintese final: card com bg levemente diferente + espacamento maior ao redor
   - Feedback periferico — sutil, nao intrusivo

2. **Mapa de raciocinio** (fase 2 — opcional, diferencial):
   - Panel lateral (desktop) ou expandivel (mobile) com grafo de nos
   - Cada turno de dialogo = no
   - Conexoes mostram fluxo do raciocinio
   - Nos coloridos por tipo (hipotese, refutacao, conclusao)
   - Lib: React Flow (dagre layout para auto-posicionamento)
   - Instrutor ve o mapa ao revisar sessao (substituindo leitura de transcrição)

**Dependencias:** Backend AI deve classificar cada turno de dialogo (requer prompt engineering no sistema de IA).

---

## Sequencia de Execucao Recomendada

```
TIER 1 — Foundation (~18h)
├── Sprint 1A: SPEC-01 EmptyState + SPEC-03 Textarea/Toggle  (3.5h)
├── Sprint 1B: SPEC-02 Modal + SPEC-04 SearchInput            (5h)
├── Sprint 1C: SPEC-05 StatCard + SPEC-07 PageHeader           (3.5h)
└── Sprint 1D: SPEC-06 DataTable                               (6h)

TIER 2 — Usability (~7h)
├── Sprint 2A: SPEC-08 Form Validation                         (3h)
├── Sprint 2B: SPEC-09 Session Timeout + SPEC-10 i18n          (4h)

TIER 3 — Experience (~9.5h)
├── Sprint 3A: SPEC-11 Color System + SPEC-13 Typography       (4.5h)
├── Sprint 3B: SPEC-12 Animations + SPEC-14 Surfaces           (5h)

TIER 4 — Vision (~28h)
├── Sprint 4A: SPEC-15 Student Trajectory                      (8h)
├── Sprint 4B: SPEC-16 Instructor Heatmap                      (8h)
└── Sprint 4C: SPEC-17 Socratic Enhancements                   (12h)
```

**Total estimado:** ~62.5h de desenvolvimento
**Recomendacao:** Executar Tier 1 + Tier 2 como MVP de melhoria (~25h).
Tier 3 + 4 como evolucao continua.

---

## Creditos

| Expert | Foco | Recomendacoes |
|:---|:---|:---|
| Don Norman | Heuristicas de usabilidade, cognição | 7 (SPEC-07,08,09,10 + inputs em 02,06) |
| Bret Victor | Visao de interacao, dados vivos | 7 (SPEC-15,16,17 + inputs em 05,12) |
| Brad Frost | Design system, atomic design | 7 (SPEC-01,02,03,04,05,06,07) |
| Jony Ive | Craft visual, materialidade | 7 (SPEC-11,12,13,14 + inputs em 01,05) |

---

*Spec gerado por J.A.R.V.I.S. — 26/05/2026*
*Painel multi-role: 4 agentes em paralelo, ~6K tokens de briefing cada*
