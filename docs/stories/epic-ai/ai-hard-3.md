---
id: AI-HARD-3
epic: EPIC-AI
phase: 4
status: Draft
severity: HIGH
terminal: Backend & Infra
complexity: medium
depends_on: [AI-HARD-0]
bug_refs: [29]
---
# AI-HARD-3: Qualidade do detector heurístico — density-weighting + remover conectores PT-BR neutros

## Story
Como aluno que escreve em português acadêmico padrão, quero que o detector heurístico de IA não me sinalize falsamente por usar conectores comuns da língua, para que minha integridade acadêmica não seja questionada por estilo de escrita legítimo; e como instrutor, quero que o score reflita densidade de clichês (não mera presença), para que textos genuinamente gerados por IA pontuem mais alto que ensaios humanos bem-redigidos.

## Contexto (do bug sweep)
Item #29 — `backend/services/ai_service.py:144-152` (lista `AI_PHRASES`) e `:525-553` (`_heuristic_ai_detection`).

`_heuristic_ai_detection` parte de `score = 0.3` (l.527) e adiciona `+0.08` por **presença** (não densidade) de cada match em `AI_PHRASES` (l.530-532). A lista inclui conectores acadêmicos neutros do PT-BR — `'dessa forma'`, `'sendo assim'`, `'nesse contexto'`, `'em suma'`, `'nesse sentido'`, `'por conseguinte'`, `'em linhas gerais'`, `'em termos gerais'` (l.140-151). Threshold preciso: 5 matches → 0.70; **6 matches → 0.78**, que ultrapassa o `> 0.70` (l.497, l.521) e dispara a flag `alta_probabilidade_texto_IA` + "Revisao manual recomendada". Um ensaio humano em português formal facilmente acumula 5-6 desses conectores e é falsamente sinalizado.

Sub-defeito real do mesmo item: no caminho LLM (l.486), `parsed.get("probability", 0.3)` em JSON válido **sem** a chave `probability` retorna 0.3 silenciosamente — veredito quase-limpo fabricado, em vez de cair para a heurística como fallback duro.

Esse caminho é exercido sempre que o LLM está em mock ou falha (l.489-494). **Impacto:** dano reputacional/acadêmico a alunos (falso positivo por estilo PT-BR) e escape de IA real via JSON malformado (falso negativo benigno em 0.3).

> Observação de sequência: depende de AI-HARD-0 (estabilização do caminho de detecção), portanto esta story assume a base já tratada e foca exclusivamente na **qualidade do scoring heurístico** e no fallback de `probability` ausente.

## Acceptance Criteria
- [ ] Um ensaio humano em PT-BR acadêmico padrão contendo 5-6 conectores neutros (ex.: "dessa forma", "sendo assim", "nesse contexto", "em suma", "nesse sentido") produz `probability < 0.70` e **não** dispara a flag `alta_probabilidade_texto_IA` nem a recomendação de "Revisao manual".
- [ ] Conectores genéricos/neutros do PT-BR são **removidos** de `AI_PHRASES` (no mínimo: `nesse sentido`, `em suma`, `nesse contexto`, `em linhas gerais`, `em termos gerais`, `por conseguinte`, `dessa forma`, `sendo assim`); permanecem apenas marcadores de fato indicativos de prosa gerada por IA.
- [ ] O score do detector é função da **densidade** de clichês (frequência relativa ao tamanho do texto), não da mera contagem/presença: um texto curto saturado de clichês pontua mais alto que um texto longo onde os mesmos clichês são esparsos.
- [ ] A contribuição total das frases-indicadoras de IA ao score é **limitada** (cap), de modo que nenhum conjunto de matches por presença consiga sozinho empurrar um ensaio legítimo acima do threshold de flag.
- [ ] Texto cliché-denso (alta proporção de frases-indicadoras por palavra/sentença) pontua estritamente mais alto que ensaio humano de mesmo tamanho com poucos clichês.
- [ ] No caminho LLM (`detect_ai_content`, l.486), `probability` ausente em JSON válido **não** retorna 0.3 benigno: faz fallback duro à heurística (`_heuristic_ai_detection`) em vez de fabricar veredito quase-limpo.
- [ ] Threshold de flag (`> 0.70`, l.497/l.521) permanece coerente com a nova escala de score após o density-weighting (sem reintroduzir o falso positivo de 5-6 conectores).

## Tasks / Subtasks
- [ ] Em `backend/services/ai_service.py:136-152`, depurar `AI_PHRASES` removendo conectores neutros do PT-BR; documentar em comentário por que cada frase remanescente é um indicador real de IA (não apenas formalidade).
- [ ] Refatorar `_heuristic_ai_detection` (l.525-553): substituir o `score += 0.08` por presença (l.530-532) por um cálculo de **densidade** — contar matches ponderados pelo tamanho do texto (palavras/sentenças) e aplicar um **cap** à contribuição agregada das frases de IA.
- [ ] Garantir que `HUMAN_INDICATORS` (l.539-546) e os ajustes por comprimento (l.548-551) permaneçam coerentes com a nova escala; recalibrar limiares de `verdict`/`confidence` (l.555-558) se necessário para manter a semântica de `likely_human`/`uncertain`/`likely_ai`.
- [ ] Em `detect_ai_content` (l.485-488), tratar `probability` ausente do LLM como fallback duro à heurística — não usar default 0.3; preferencialmente reaproveitar o branch `except` (l.489-494) ou um guard explícito quando a chave não existir.
- [ ] Adicionar teste de regressão (pytest) com: (a) ensaio humano PT-BR com 5-6 conectores → `probability < 0.70`, sem flag; (b) texto cliché-denso curto → score maior que (a); (c) JSON LLM válido sem `probability` → cai na heurística, não 0.3.

## Dev Notes
- **Arquivos:** `backend/services/ai_service.py` — `AI_PHRASES` (l.136-152), `_heuristic_ai_detection` (l.525-558), `detect_ai_content` (l.469-523, com foco em l.486 e l.497/l.521).
- **Abordagem:** (1) curar `AI_PHRASES` para indicadores genuínos de IA; (2) trocar pontuação por presença por densidade normalizada pelo tamanho do texto, com cap na contribuição agregada das frases de IA; (3) endurecer o fallback de `probability` ausente no caminho LLM. O threshold público (`> 0.70`) e a string de recomendação não mudam de forma — apenas a escala de score subjacente é recalibrada para não produzir falsos positivos.
- **Riscos de regressão:** `_heuristic_ai_detection` é chamado por `detect_ai_content` (caminho mock/falha LLM), que serve a rota de detecção em `backend/routes_ai.py`. Alterar a escala de score pode mexer em vereditos de testes existentes e em qualquer consumidor da flag `alta_probabilidade_texto_IA` ou do campo `recommendation`. Não confundir com o item #30 (validação da saída LLM no caminho feliz) — esta story trata apenas do caminho heurístico e do default de `probability`. Coordenar com AI-HARD-0 (dependência) para não duplicar mudanças no mesmo bloco.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: ensaio PT-BR com 5-6 conectores deixa de ser sinalizado; texto cliché-denso pontua mais alto.
- [ ] Sem regressão na suíte de segurança.
- [ ] QA Gate: PASS ou CONCERNS.
- [ ] Conectores neutros do PT-BR removidos de `AI_PHRASES` e scoring por densidade com cap aplicado; `probability` ausente do LLM faz fallback à heurística (não 0.3).

## QA Results
_(a preencher pelo @qa)_
