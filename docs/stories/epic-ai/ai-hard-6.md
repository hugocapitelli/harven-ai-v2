---
id: AI-HARD-6
epic: EPIC-AI
phase: 4
status: Done
severity: HIGH
terminal: Backend & Infra
complexity: low
depends_on: [AI-HARD-5]
bug_refs: [27]
---
# AI-HARD-6: Cap de contexto de referência + seam de retrieval

## Story
Como aluno usando o tutor socrático em capítulos longos, quero que o tutor enxergue o conteúdo relevante do capítulo inteiro (e não apenas os primeiros 4000 chars), para que as perguntas socráticas mantenham fundamentação factual e pedagógica em toda a extensão do material.

## Contexto (do bug sweep)
Bug #27 — `backend/services/ai_service.py:384`. O método `socratic_dialogue` embute o conteúdo de referência via `chapter_content[:4000]`, um magic number hardcoded inline no bloco `context`. Para capítulos > ~4000 chars, o tutor só recebe o primeiro trecho e perde grounding na segunda metade. Isso é inconsistente com os demais caminhos do mesmo serviço: a geração de questões usa `chapter_content[:15000]` (`ai_service.py:289`) e o reprocess usa `[:15000]`/`[:8000]` (`routes_ai.py:537,547`). Impacto: em capítulos longos a relevância das perguntas degrada e o prompt socrático pode operar sem fundamentação factual da parte truncada.

## Acceptance Criteria
- [x] O cap de contexto de referência em `socratic_dialogue` passa de 4000 para até 15000 chars, alinhado ao caminho de geração de questões.
- [x] O fatiamento NÃO é mais um magic number inline: a seleção do trecho é centralizada em um seam `_select_reference_context(chapter_content, student_message=...)` (ou assinatura equivalente) com o limite expresso como constante nomeada (ex.: `REFERENCE_CONTEXT_MAX_CHARS = 15000`).
- [x] `socratic_dialogue` chama `_select_reference_context(...)` ao montar o bloco `context`, em vez de `chapter_content[:4000]` direto.
- [x] O seam é extensível para retrieval futuro (chunk + embed/retrieve do segmento relevante à pergunta atual) sem alterar os call sites — por enquanto a implementação pode retornar o head truncado, mas a interface aceita `student_message` para evolução.
- [x] Capítulos curtos (≤ limite) continuam recebendo o conteúdo integral (sem regressão de comportamento).
- [x] Nenhum outro magic number de truncamento é reintroduzido em `socratic_dialogue`.

## Tasks / Subtasks
- [x] Em `backend/services/ai_service.py`, declarar a constante `REFERENCE_CONTEXT_MAX_CHARS = 15000` (escopo de módulo ou classe), substituindo o uso semântico do `[:4000]` e padronizando com o `[:15000]` da geração de questões (linha ~289).
- [x] Criar o método `_select_reference_context(self, chapter_content: str, student_message: Optional[str] = None) -> str` que retorna `chapter_content[:REFERENCE_CONTEXT_MAX_CHARS]` hoje, com docstring indicando o ponto de extensão para retrieval (chunk/embed) baseado em `student_message`.
- [x] Em `socratic_dialogue`, trocar `f"Conteudo de referencia:\n{chapter_content[:4000]}"` por chamada a `self._select_reference_context(chapter_content, student_message=student_message)`.
- [x] Adicionar teste de regressão cobrindo: capítulo > 4000 e ≤ 15000 chars retorna conteúdo além de 4000; capítulo > 15000 é cortado em 15000; capítulo curto retorna integral.

## Dev Notes
- **Arquivos:** `backend/services/ai_service.py` (método `socratic_dialogue` ~L367-405, especificamente a montagem de `context` em L380-385; referência de padronização na geração de questões em L289). Caminhos relacionados que já usam caps maiores: `backend/routes_ai.py:537,547` (`[:8000]`).
- **Abordagem:** Extrair o fatiamento para o seam `_select_reference_context`, elevar o cap para a constante `REFERENCE_CONTEXT_MAX_CHARS = 15000` e deixar a assinatura preparada para retrieval (recebe `student_message`). Mudança cirúrgica e localizada — substitui apenas a expressão `chapter_content[:4000]` por uma chamada de método; o restante do fluxo de `context`/`_call_openai` permanece intacto.
- **Riscos de regressão:** Blast radius baixo. `socratic_dialogue` é chamado por `backend/routes_ai.py:226` (endpoint de diálogo socrático). Atenção a: (1) aumento de tokens por turno em capítulos longos — coexiste com o budget check (`check_token_budget`) já presente em L378, e o bug #28 (L394-401, escopo de AI-HARD distinto) trata da reinjeção do contexto a cada turno; não resolver #28 aqui, apenas não piorá-lo. (2) Manter `student_message` apenas como parâmetro do seam (sem alterar a semântica atual de truncamento por head) para não introduzir mudança comportamental não testada. Depende de AI-HARD-5 (concluir antes).

## Definition of Done
- [x] Teste de regressão (falha-antes / passa-depois) verde — verifica cap de 15000 e seam `_select_reference_context`
- [x] Sem regressão na suíte de segurança
- [x] QA Gate: PASS ou CONCERNS
- [x] Nenhum magic number de truncamento remanescente em `socratic_dialogue`; limite expresso como constante nomeada e fatiamento roteado pelo seam

## File List
- `backend/services/ai_service.py` — adicionada constante de módulo `REFERENCE_CONTEXT_MAX_CHARS = 15000` (perto de `MAX_INTERACTIONS`/`MAX_HISTORY_TURNS`); novo seam `AIService._select_reference_context(self, chapter_content, student_message=None) -> str` (head capado pela constante, docstring marca o ponto de extensão para retrieval futuro via `student_message`); `socratic_dialogue` agora monta `Conteudo de referencia` via `self._select_reference_context(chapter_content, student_message=student_message)` em vez do inline `chapter_content[:4000]`.
- `backend/tests/test_ai_hard_reference_context.py` — NOVO. 9 testes: 5 de unidade do seam/constante (cap em 15000, truncamento em chapter longo, integral em chapter curto e no limite exato, aceitação do kwarg `student_message`) + 4 end-to-end de `socratic_dialogue` (4000<len≤15000 mantém conteúdo pós-4000; >15000 cortado no cap via marcador sentinela; chapter curto integral; ausência do antigo corte em 4000).
- `docs/stories/epic-ai/ai-hard-6.md` — status Draft → Done; ACs/Tasks/DoD marcados; File List.

## QA Results
**Verde.** Suíte-alvo (`test_ai_hard_reference_context.py` + `test_ai_service_methods.py`): 36 passed. Suíte completa do backend: **409 passed, 0 failed, 0 errors, 0 skipped** (era 400 antes da onda; +9 do novo arquivo) — zero regressão, acima do piso ≥381. Mudança cirúrgica e localizada: nenhum magic number de truncamento remanescente em `socratic_dialogue`; cap expresso na constante nomeada e fatiamento roteado pelo seam extensível. Gate: **PASS**.
