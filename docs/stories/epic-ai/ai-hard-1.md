---
id: AI-HARD-1
epic: EPIC-AI
phase: 4
status: Draft
severity: HIGH
terminal: Backend & Infra
complexity: medium
depends_on: [AI-HARD-0]
bug_refs: [30]
---
# AI-HARD-1: Detector contract hardening: probability validada + fallback heurístico

## Story
Como aluno avaliado pelo detector de IA da Harven.AI, quero que a rota de detecção nunca retorne erro 500 nem produza uma flag espúria por causa de saída malformada do modelo, para que minha avaliação seja confiável e o serviço permaneça estável mesmo quando o LLM devolve dados fora do contrato.

## Contexto (do bug sweep)
Item #30 do BUG-SWEEP-2026-06-03 — **`detect_ai_content` confia em saída não validada do modelo (probability fora de range/tipo errado)**.

No caminho LLM, os campos `probability`, `confidence` e `verdict` são lidos verbatim da resposta do modelo, sem coerção/validação, e usados diretamente em `probability > 0.70` (l.497) e `round(probability, 2)` (l.504). Essas linhas estão **fora do try/except**, então:

- **(a)** `probability` como string (`'0.8'`) ou `null` → `'0.8' > 0.70` / `None > 0.70` levanta `TypeError`, que NÃO cai na heurística e propaga como **HTTP 500** (crash da rota).
- **(b)** `probability` numérica fora de range (ex.: `1.5`) → não há crash, mas gera probability sem sentido e **flag espúria contra o aluno**.
- **(c)** `verdict` não restrito ao enum — o modelo pode devolver um veredito arbitrário que vaza para a resposta.

Sub-defeito relacionado (item #29): `parsed.get("probability", 0.3)` em JSON válido sem a chave produz veredito quase-limpo silencioso (0.3 benigno) em vez de cair de forma dura na heurística.

Impacto: instabilidade de produção (500s evitáveis) e injustiça avaliativa (flag falsa) — ambos críticos em um detector que decide integridade acadêmica.

## Acceptance Criteria
- [ ] `probability` recebida do LLM como **string** (`'0.8'`), `null`/ausente, ou tipo inesperado **nunca** causa HTTP 500: é coagida para `float` quando possível e tratada como falha de contrato quando não.
- [ ] `probability` numérica **fora de [0,1]** (ex.: `1.5`, `-0.2`) é **clampada** ao intervalo antes de qualquer comparação (`> 0.70`) ou `round`, evitando flag espúria.
- [ ] `probability` **ausente** no JSON do LLM dispara **fallback duro à heurística** (`_heuristic_ai_detection`), e **não** o default silencioso `0.3`.
- [ ] `verdict` é sempre restrito ao enum válido do detector; valor fora do enum é normalizado/rejeitado (nunca vaza verbatim).
- [ ] `confidence` é sempre restrita ao enum válido do detector; valor fora do enum é normalizado/rejeitado.
- [ ] A coerção/validação/clamp acontece **antes** das linhas `probability > 0.70` (l.497) e `round(probability, 2)` (l.504), e essas linhas passam a operar somente sobre valores garantidamente válidos.
- [ ] A rota expõe um `response_model` (Pydantic) que é **superset** do payload retornado — campos extras do modelo não quebram a serialização e o contrato de saída é estável e documentado.
- [ ] Caminho feliz (LLM devolve `probability` float em range + `verdict`/`confidence` no enum) permanece inalterado em comportamento observável.

## Tasks / Subtasks
- [ ] Localizar a função `detect_ai_content` e as linhas `probability > 0.70` (l.497) e `round(probability, 2)` (l.504) no módulo do detector (backend `app/services` / `app/routers` de IA-Diálogo).
- [ ] Criar um helper de coerção `_coerce_probability(raw) -> float | None`: tenta `float(raw)` (cobre string numérica), retorna `None` para `null`/não-numérico; o caller decide fallback.
- [ ] Implementar clamp `max(0.0, min(1.0, prob))` aplicado imediatamente após a coerção bem-sucedida, antes de qualquer uso.
- [ ] Implementar validação de enum para `verdict` e `confidence` (mapear/normalizar valores válidos; valor inválido → fallback duro à heurística ou normalização para o enum, conforme contrato).
- [ ] Substituir `parsed.get("probability", 0.3)` por: se `probability` ausente/não coercível → invocar `_heuristic_ai_detection` (fallback duro), eliminando o default `0.3`.
- [ ] Mover as comparações/`round` para depois da coerção+clamp+validação de enum, garantindo que nunca operem sobre tipos inválidos.
- [ ] Definir um Pydantic `response_model` (superset) para a rota e anexá-lo ao decorator FastAPI da rota de detecção.
- [ ] Adicionar testes de regressão cobrindo: string `'0.8'`, `null`, ausente, `1.5`, `-0.2`, `verdict` fora do enum, `confidence` fora do enum, e caminho feliz.

## Dev Notes
- **Arquivos:** módulo do detector de IA-Diálogo em `harven-ai-v2/backend/app/` — função `detect_ai_content` (linhas críticas l.497 `probability > 0.70` e l.504 `round(probability, 2)`); função `_heuristic_ai_detection` (caminho de fallback); o router FastAPI que expõe a rota de detecção (onde será anexado o `response_model`); schemas Pydantic relacionados. (Caminhos exatos a confirmar pelo @dev via Grep por `detect_ai_content` / `_heuristic_ai_detection` / `0.70`.)
- **Abordagem:** introduzir uma camada de saneamento entre a saída do LLM e o uso dos campos — coerção segura (`float()`), clamp em [0,1], validação de `verdict`/`confidence` contra enums, e fallback duro à heurística quando `probability` está ausente/não coercível. As linhas de comparação/round migram para dentro/depois dessa camada. Adicionar `response_model` superset na rota para estabilizar o contrato de saída e tolerar campos extras do modelo.
- **Riscos de regressão:** blast radius é a rota de detecção de IA e qualquer caller de `detect_ai_content` (export Moodle / relatórios que consomem `avg_ai_probability`/flags — cf. item #34). Mudar o fallback de `0.3` para heurística altera o veredito em JSONs sem `probability`: validar que isso é o comportamento desejado e que não muda silenciosamente resultados já persistidos. Depende de AI-HARD-0 (deve estar concluída antes — contrato/base do detector). Confirmar que o `response_model` superset não esconde campos hoje retornados.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde
- [ ] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [ ] Nenhum dos cenários do item #30 (string, null, ausente, fora-de-range) produz HTTP 500; `verdict`/`confidence` sempre dentro do enum; `response_model` superset presente e validado na rota; default silencioso `0.3` removido em favor da heurística.

## QA Results
_(a preencher pelo @qa)_
