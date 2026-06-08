---
id: POD-2
epic: EPIC-PODCAST
phase: 4
status: Draft
severity: HIGH
terminal: Backend & Infra
complexity: medium
depends_on: [POD-1]
bug_refs: [8, 33]
---
# POD-2: Wire chunk-and-concatenate em `_run_tts_job` e `tts_generate` sync

## Story
Como aluno do tutor Harven.AI gerando o áudio (podcast) de um capítulo longo, quero que a narração seja sintetizada por inteiro em um único MP3 válido, para que eu ouça o conteúdo completo sem truncamento silencioso quando o texto ultrapassa o limite de caracteres do provedor de TTS.

## Contexto (do bug sweep)
Os itens **#8** e **#33** do bug sweep apontam que o pipeline de geração de áudio do tutor envia o texto da narração para o provedor de TTS em **uma única chamada**, sem dividir (chunk) o conteúdo quando ele excede o teto de caracteres aceito pela API de síntese (tipicamente ~4.000–10.000 chars dependendo do provedor).

Efeitos verificados:
- **#8** — Em capítulos longos (>10k caracteres de narração), a síntese é **truncada silenciosamente**: ou o provedor retorna erro 400/413 (texto longo demais) e o job falha, ou só os primeiros N caracteres são vocalizados e o restante da narração é perdido. O aluno recebe um MP3 que cobre apenas o início do capítulo, sem nenhum sinal de erro.
- **#33** — A lógica de chunk-and-concatenate (dividir o texto em pedaços, sintetizar cada pedaço e concatenar os bytes MP3 resultantes) introduzida em **POD-1** está disponível como helper, mas **não está conectada** nos dois caminhos de produção que efetivamente sintetizam áudio: o job assíncrono `_run_tts_job` e o caminho síncrono `tts_generate`. Ambos ainda chamam o provedor diretamente com o texto inteiro.

Pontos de código (caminhos a corrigir — confirmar paths exatos durante a implementação):
- `backend/app/services/tts_service.py` → `_run_tts_job(...)` (worker assíncrono do job) — chama síntese com texto único.
- `backend/app/services/tts_service.py` → `tts_generate(...)` (caminho síncrono) — idem.
- Helper de chunking entregue por POD-1 (ex.: `chunk_text(...)` / `synthesize_chunks_and_concat(...)`) — **não consumido** por nenhum dos dois.

Impacto: alunos com material denso (a maioria dos capítulos reais) não conseguem usar o podcast — funcionalidade central percebida como quebrada.

## Acceptance Criteria
- [ ] Dado um capítulo cuja narração ultrapassa o limite de caracteres do provedor (>10k chars), quando o áudio é gerado via `_run_tts_job`, então o resultado é **um único arquivo MP3 válido** cuja narração cobre o capítulo **inteiro** (início ao fim), sem truncamento.
- [ ] O mesmo comportamento vale para o caminho síncrono `tts_generate`: capítulo >10k → MP3 único válido cobrindo a narração completa.
- [ ] O MP3 resultante **decodifica sem erro** (ex.: validado com `pydub`/`mutagen`/`ffprobe`) e sua **duração ≈ soma das durações** dos chunks individuais (tolerância de ±2s ou ±1% para overhead de header/junção).
- [ ] A ordem dos chunks é preservada na concatenação (a narração não fica fora de ordem nem com pedaços faltando).
- [ ] **Regression-pin** dos estilos curtos: a geração de áudio para `summary` e `explanation` (textos que cabem em um único chunk) continua produzindo exatamente um MP3 válido, sem regressão de duração nem de qualidade — o caminho de chunk único permanece equivalente ao comportamento atual.
- [ ] Falha na síntese de **qualquer** chunk não produz um MP3 parcial silencioso: o job vai para estado de erro (ou propaga exceção no caminho síncrono) — nunca retorna "done" com áudio incompleto.
- [ ] O helper de chunking de POD-1 é a **única** rota de síntese em ambos os caminhos (sem chamada direta remanescente ao provedor com texto inteiro).

## Tasks / Subtasks
- [ ] Em `backend/app/services/tts_service.py`, localizar `_run_tts_job(...)` e substituir a chamada direta de síntese pela rota de chunk-and-concatenate exposta por POD-1.
- [ ] Em `backend/app/services/tts_service.py`, fazer o mesmo em `tts_generate(...)` (caminho síncrono), reutilizando o mesmo helper — evitar duplicar a lógica de chunking entre os dois caminhos (extrair função compartilhada se necessário).
- [ ] Garantir que o texto enviado ao chunker é a narração final já montada (mesmo texto que hoje é passado ao provedor), preservando voz/idioma/parâmetros de síntese por chunk.
- [ ] Concatenar os bytes MP3 dos chunks em ordem em um único buffer/arquivo de saída, mantendo o mesmo contrato de retorno (bytes/URL) que os callers já esperam.
- [ ] Tratar falha por chunk: abortar a concatenação e sinalizar erro do job / propagar exceção no síncrono (não persistir áudio parcial).
- [ ] Escrever teste de regressão (falha-antes/passa-depois): capítulo sintético >10k chars → assert MP3 decodifica e `len(audio) ≈ Σ chunks`; ambos os caminhos (`_run_tts_job` e `tts_generate`) cobertos.
- [ ] Escrever teste de regression-pin para `summary`/`explanation` (texto curto, 1 chunk) garantindo paridade com o comportamento atual.
- [ ] Rodar a suíte de TTS/podcast existente para confirmar ausência de regressão nos callers.

## Dev Notes
- **Arquivos:**
  - `backend/app/services/tts_service.py` — `_run_tts_job(...)` e `tts_generate(...)` (dois caminhos a religar).
  - Helper de chunking de POD-1 no mesmo módulo (ex.: `chunk_text` / `synthesize_chunks_and_concat`) — confirmar nome exato.
  - Testes: `backend/tests/` (suíte de TTS/podcast existente).
- **Abordagem:** POD-1 já entregou e testou o helper de chunk-and-concatenate isoladamente. Esta story é puramente de **wiring**: trocar, nos dois pontos de produção, a chamada única ao provedor pela rota com chunking, sem reescrever a lógica de divisão/concatenação. Idealmente, extrair um único ponto de entrada compartilhado (`_synthesize(text, voice, ...) -> bytes`) que ambos os caminhos consomem, para garantir paridade e evitar drift futuro entre o async e o sync.
- **Riscos de regressão:**
  - **Blast radius:** todo consumo de áudio do tutor passa por `tts_service`. `_run_tts_job` é chamado pelo dispatcher de jobs assíncronos (e por TTSJOB-2 quando aterrissar); `tts_generate` é o caminho síncrono usado por endpoints/legado. Mudar a montagem do MP3 afeta `summary`, `explanation` e `podcast` simultaneamente — daí o regression-pin obrigatório dos estilos curtos.
  - Concatenação ingênua de MP3s pode gerar artefatos de header (gaps/cliques na junção) se os chunks usarem parâmetros de encoding divergentes — manter bitrate/sample-rate consistentes entre chunks; preferir o método de concatenação validado em POD-1.
  - Falha parcial silenciosa é o pior cenário (mascararia o bug original com outra cara) — o caminho de erro precisa ser explícito e testado.
  - **Dependência:** bloqueado por **POD-1** (helper de chunking). Downstream: POD-3 (persistência de `audio_url`) e POD-4 (timeouts/dedup) assumem `_run_tts_job` já produzindo MP3 completo.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: capítulo >10k → MP3 único válido com duração ≈ soma dos chunks, em `_run_tts_job` e `tts_generate`.
- [ ] Sem regressão na suíte de segurança.
- [ ] QA Gate: PASS ou CONCERNS.
- [ ] Regression-pin de `summary`/`explanation` verde (paridade com comportamento atual, 1 chunk).
- [ ] Nenhuma chamada direta ao provedor com texto inteiro remanescente em `tts_service.py` — ambos os caminhos passam pelo helper de POD-1.
- [ ] Falha de síntese em qualquer chunk resulta em estado de erro/exceção (nunca "done" com áudio parcial), coberta por teste.

## QA Results
_(a preencher pelo @qa)_
