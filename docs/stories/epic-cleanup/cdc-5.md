---
id: CDC-5
epic: EPIC-CLEANUP
phase: 5
status: Draft
severity: MEDIUM
terminal: Backend & Infra
complexity: medium
depends_on: []
bug_refs: [62]
---
# CDC-5: _clean_markdown join conservador

## Story
Como engenheiro de backend responsável pela normalização de texto extraído de PDFs/Markdown no tutor Harven.AI, quero que a função `_clean_markdown` faça join de linhas de forma conservadora, para que apenas quebras de word-wrap reais sejam reunidas — preservando listas não-bullet, headings e hífens literais — evitando corromper o conteúdo apresentado ao aluno e enviado ao LLM.

## Contexto (do bug sweep)
Item #62 do bug sweep aponta que a heurística atual de `_clean_markdown` faz um join agressivo de linhas adjacentes, assumindo que toda quebra de linha é um artefato de word-wrap de PDF. Na prática isso provoca três classes de corrupção:

1. **Listas não-bullet são fundidas.** Itens de lista que não começam com marcador (`-`, `*`, `1.`) — por exemplo listas numeradas por extenso, sub-itens indentados ou linhas curtas sequenciais — são coladas na linha anterior, virando um parágrafo único ilegível.
2. **Headings são fundidos com o corpo.** Uma linha de heading curta (ex.: `## Resultados`) seguida por texto é unida ao parágrafo seguinte, perdendo a separação estrutural do documento.
3. **Hífens literais são tratados como hifenização de fim de linha.** Quando uma linha termina em `-`, a heurística remove o hífen e cola as palavras (`co-` + `produto` → `coproduto`), destruindo hífens que fazem parte do termo original (ex.: `e-commerce`, `pós-graduação`).

O caso legítimo que o join DEVE continuar resolvendo é o **word-wrap de PDF**: um parágrafo contínuo quebrado em múltiplas linhas físicas por largura de página deve ser reunido em uma única linha lógica.

Arquivo/local: heurística de junção de linhas em `_clean_markdown` (backend de ingestão/normalização de texto do tutor). Confirmar o caminho exato com Grep por `_clean_markdown` no momento da implementação. Impacto: conteúdo corrompido tanto na exibição quanto no contexto enviado ao LLM, degradando a qualidade das respostas do tutor.

## Acceptance Criteria
- [ ] Linhas de lista que NÃO começam com bullet (numeradas, sub-itens, linhas curtas sequenciais) NÃO são fundidas com a linha anterior — cada item permanece em sua própria linha.
- [ ] Headings (linhas iniciando com `#`/`##`/`###` ou linhas-título curtas reconhecidas) NÃO são fundidos com o parágrafo seguinte nem com o anterior.
- [ ] Word-wrap de PDF AINDA é corretamente reunido: um parágrafo contínuo quebrado por largura de página é unido em uma linha lógica única (comportamento legítimo preservado).
- [ ] Hífens literais são preservados: uma linha terminando em `-` que faz parte de um termo (`e-commerce`, `pós-graduação`) NÃO tem o hífen removido nem as palavras coladas indevidamente.
- [ ] Existe um conjunto de golden-file tests cobrindo os 4 cenários acima (lista não-bullet, heading, word-wrap legítimo, hífen literal), com entrada bruta e saída esperada versionadas.
- [ ] Nenhuma regressão na normalização de documentos já processados corretamente (parágrafos simples continuam intactos).

## Tasks / Subtasks
- [ ] Localizar a função: `grep -rn "_clean_markdown" backend/` para confirmar arquivo e linha exatos.
- [ ] Mapear a heurística atual de join de linhas e identificar onde a decisão de "juntar" é tomada (a condição que hoje é agressiva demais).
- [ ] Tornar o join conservador: só fundir duas linhas quando ambas pertencem ao MESMO parágrafo de corpo de texto — ou seja, a linha atual não é heading, não é item de lista (bullet ou não-bullet detectável por padrão de prefixo/indentação) e a linha anterior não termina em pontuação de fim de bloco.
- [ ] Tratar hifenização de forma segura: só colapsar `palavra-\npalavra` em `palavrapalavra` quando houver evidência de quebra por word-wrap (ex.: minúscula+`-` no fim de linha seguida de minúscula); preservar hífen quando o termo é claramente composto/literal. Na dúvida, PRESERVAR o hífen.
- [ ] Criar diretório de golden files com pares input/output para os 4 cenários (lista não-bullet, heading, word-wrap, hífen literal) + 1 caso de parágrafo simples (controle de não-regressão).
- [ ] Implementar/atualizar o teste de regressão que roda `_clean_markdown` sobre cada golden input e compara byte-a-byte com o output esperado.
- [ ] Rodar a suíte completa de testes do módulo de ingestão para garantir ausência de regressão.

## Dev Notes
- **Arquivos:** função `_clean_markdown` no backend de ingestão/normalização (confirmar via `grep -rn "_clean_markdown" backend/`); novo diretório de golden files (ex.: `backend/tests/golden/clean_markdown/`) com `*_input.md` / `*_expected.md`; arquivo de teste de regressão correspondente (ex.: `backend/tests/test_clean_markdown.py`).
- **Abordagem:** substituir a regra de join "una sempre que houver quebra de linha" por uma regra de allow-list — junte SOMENTE quando ambas as linhas são corpo de parágrafo contínuo. Detectar e proteger explicitamente: (a) headings (`^#{1,6}\s` ou linha-título curta), (b) itens de lista bullet e não-bullet (prefixo `-`/`*`/`\d+\.`/indentação), (c) hífen literal de fim de linha. O word-wrap permanece o único caso que dispara o merge. Golden-file testing garante que qualquer mudança futura na heurística seja detectada por diff explícito.
- **Riscos de regressão:** `_clean_markdown` está no caminho de ingestão de todo material textual que alimenta o tutor — afeta tanto a renderização para o aluno quanto o contexto enviado ao LLM. Blast radius: qualquer chamador da pipeline de normalização de PDF/Markdown. Uma regra mais conservadora reduz fusões indevidas, mas pode deixar de juntar word-wraps em casos-limite ambíguos; os golden files de word-wrap legítimo cobrem esse risco. Verificar com Grep quem chama `_clean_markdown` antes de editar e confirmar que nenhum consumidor dependia do comportamento agressivo anterior.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde
- [ ] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [ ] Golden-file tests dos 4 cenários (lista não-bullet, heading, word-wrap, hífen literal) + caso de controle versionados e passando; comparação byte-a-byte do output de `_clean_markdown`.

## QA Results
_(a preencher pelo @qa)_
