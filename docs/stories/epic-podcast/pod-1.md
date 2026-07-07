---
id: POD-1
epic: EPIC-PODCAST
phase: 4
status: InReview
severity: HIGH
terminal: Backend & Infra
complexity: medium
depends_on: []
bug_refs: [8, 33]
---
# POD-1: Branch de podcast + chunking sentence-aware (matar o cap silencioso de 5000)

## Story
Como aluno da Harven.AI que solicita o áudio de um capítulo no formato podcast, quero que o sistema gere um roteiro conversacional de ~10 minutos a partir do corpo completo do conteúdo e narre o material inteiro sem cortes, para que eu possa ouvir a aula completa em vez de receber uma versão silenciosamente truncada.

## Contexto (do bug sweep)
Dois defeitos relacionados condenam o formato podcast a ser uma promessa quebrada:

- **#8 — `audio_type='podcast'` não tem branch dedicado / cai no caminho de summary.** A geração de áudio trata `podcast` como se fosse mais um resumo curto: o texto enviado ao TTS é o mesmo summary/explanation enxuto, não o corpo completo do capítulo. Resultado: o "podcast de 10 minutos" é, na prática, um clipe de poucos segundos a 1-2 minutos, sem o conteúdo conversacional expandido prometido na UI. Não existe um prompt/roteirizador específico que pegue o corpo HTML, faça strip das tags e produza um script conversacional alongado (≥1200 palavras ≈ ~10 min de narração).
- **#33 — `chunk_text` aplica um cap rígido de 5000 caracteres truncando silenciosamente o restante.** A função de chunking não divide o texto em pedaços ≤5000; ela corta no caractere 5000 e descarta o resto **sem erro, log ou aviso**. Qualquer conteúdo longo (e o podcast, por definição, é longo) perde tudo após o limite — a narração termina no meio de uma frase e o aluno nunca sabe que faltou material. O corte é cego (no meio de palavra/frase), não respeita fronteiras de sentença.

Impacto combinado: o formato podcast hoje é inutilizável — ou narra o resumo errado (#8) ou, se chegasse o corpo completo, seria decapitado em 5000 chars (#33). Esta story conserta a **fonte do roteiro** (branch de podcast) e a **mecânica de fatiamento** (chunking sentence-aware sem perda), deixando o wire/concatenação de múltiplos chunks no TTS para a POD-2.

## Acceptance Criteria
- [ ] Existe um branch dedicado para `audio_type='podcast'` na geração de áudio: quando o tipo é `podcast`, o roteiro é construído a partir do **corpo completo** do conteúdo (campo de body/HTML do capítulo), e **não** do summary/explanation.
- [ ] O corpo HTML é convertido para texto plano (HTML stripped) antes de roteirizar — sem tags, entidades decodificadas, espaços normalizados.
- [ ] O roteiro de podcast gerado tem tom **conversacional** e comprimento mínimo de **≥1200 palavras** (≈ ~10 minutos de narração) para um capítulo de tamanho típico; capítulos muito curtos geram o máximo conversacional possível sem inventar conteúdo fora do corpo.
- [ ] `chunk_text` **divide** o texto em pedaços de no máximo 5000 caracteres **sem descartar nenhum caractere** — a concatenação ordenada de todos os chunks reproduz o texto de entrada integralmente (round-trip lossless).
- [ ] O fatiamento é **sentence-aware**: os cortes ocorrem em fronteiras de sentença (ou de parágrafo) sempre que possível, nunca no meio de uma palavra; um único chunk só excede a regra de fronteira se uma sentença isolada for >5000 chars (fallback documentado).
- [ ] **Nenhum truncamento silencioso**: para qualquer entrada >5000 chars, o sistema produz N>1 chunks cobrindo 100% do texto; não há caminho de código em que conteúdo seja cortado e descartado sem retornar nos chunks.
- [ ] A duração resultante da narração corresponde ao roteiro completo (validado em POD-2 na concatenação real; aqui validado por cobertura textual: soma dos chars dos chunks == chars do roteiro).

## Tasks / Subtasks
- [ ] Localizar a função de geração de áudio/roteiro e o ponto onde `audio_type` é avaliado (provável `backend/app/services/audio.py` ou módulo `tts`/`audio_generation`); confirmar onde hoje `podcast` recai sobre o caminho de summary.
- [ ] Implementar a leitura do **corpo completo** do conteúdo (campo body/HTML do capítulo no model de conteúdo) quando `audio_type='podcast'`.
- [ ] Adicionar/usar utilitário de **HTML strip** (remover tags, decodificar entidades, normalizar whitespace) antes da roteirização.
- [ ] Criar o **branch de podcast**: prompt/roteirizador conversacional que transforma o corpo em script ≥1200 palavras, mantendo fidelidade ao conteúdo (sem inventar — alinhado ao Artigo IV No Invention).
- [ ] Reescrever `chunk_text` para **fatiar** (não truncar): loop que acumula sentenças até ≤5000 chars, fecha o chunk em fronteira de sentença/parágrafo e segue; fallback de hard-split apenas para sentença única >5000.
- [ ] Garantir round-trip lossless: `''.join(chunks) == texto_normalizado_de_entrada` (ou diferença apenas em separadores controlados e documentados).
- [ ] Remover/eliminar o cap rígido `[:5000]` que descartava o restante; substituir por log de debug informando quantos chunks foram produzidos.
- [ ] Adicionar testes de regressão (ver Definition of Done) para o branch de podcast e para o chunking sem perda.

## Dev Notes
- **Arquivos:** módulo de geração de áudio/TTS do backend — provável `backend/app/services/audio.py` (função(ões) de geração e `chunk_text`) e o ponto de roteamento por `audio_type` (summary | explanation | podcast). Model de conteúdo do capítulo (campo body/HTML) para obter o corpo completo. Confirmar caminhos exatos via grep por `chunk_text`, `audio_type`, `podcast` e `[:5000]` no início da implementação.
- **Abordagem:** separar claramente duas responsabilidades — (1) **fonte do roteiro** por tipo: `podcast` → corpo completo HTML-stripped → roteirizador conversacional ≥1200 palavras; `summary`/`explanation` → comportamento atual inalterado; (2) **mecânica de chunking**: `chunk_text` passa de truncador (`text[:5000]`) para fatiador sentence-aware lossless que retorna `list[str]` cobrindo 100% do texto. Esta story entrega a geração do roteiro correto e os chunks corretos; **a costura desses chunks no job de TTS (chunk-and-concatenate) é a POD-2** — aqui o contrato é "chunks corretos e completos saem da função".
- **Riscos de regressão:** `chunk_text` provavelmente é compartilhado pelos caminhos de `summary` e `explanation`. Mudar a assinatura (de string truncada para `list[str]`) ou o comportamento pode quebrar quem consome o retorno hoje. Blast radius: todo consumidor de `chunk_text` no pipeline de áudio (sync `tts_generate` e assíncrono `_run_tts_job`, ambos endereçados na POD-2). Mitigação: rodar `gitnexus_impact({target: "chunk_text", direction: "upstream"})` antes de editar, pinar regression de `summary`/`explanation` (mesmo MP3/duração de antes) e coordenar a transição de contrato com a POD-2 (dependente desta story). Cuidado também com capítulos sem body/HTML (fallback gracioso para summary) e com sentenças anômalas >5000 chars (hard-split documentado).

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: (a) `audio_type='podcast'` produz roteiro derivado do corpo completo com ≥1200 palavras para capítulo típico; (b) `chunk_text` em entrada >5000 chars retorna múltiplos chunks cujo join reproduz o texto integral (lossless) e cujos cortes caem em fronteira de sentença.
- [ ] Sem regressão na suíte de segurança.
- [ ] QA Gate: PASS ou CONCERNS.
- [ ] Comportamento de `summary` e `explanation` regression-pinned (output/duração idênticos ao baseline) — nenhuma quebra colateral na mudança do `chunk_text`.
- [ ] Confirmado que não existe mais nenhum caminho de truncamento silencioso (cap `[:5000]`) no pipeline de áudio; contrato de chunks completos pronto para consumo pela POD-2.

## QA Results
_(a preencher pelo @qa)_
