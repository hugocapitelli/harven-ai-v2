---
id: TTSJOB-3
epic: EPIC-PODCAST
phase: 4
status: InReview
severity: HIGH
terminal: UX/UI & Design
complexity: low
depends_on: [TTSJOB-2]
bug_refs: [38, 39]
---
# TTSJOB-3: Poller TTS — poll imediato, budget maior, fallback content.audio_url no timeout

## Story
Como aluno que solicita a geração do podcast (TTS) de um conteúdo, quero que o poller verifique o resultado imediatamente e por tempo suficiente, com fallback robusto quando o job já concluiu mas o status não chega a tempo, para que o áudio apareça assim que estiver pronto e o botão de geração não fique travado em estado de "gerando" indefinidamente.

## Contexto (do bug sweep)
O poller de status do TTS no frontend apresenta dois defeitos que produzem falsos negativos e UI travada (itens #38 e #39 do BUG-SWEEP-2026-06-03.md):

- **#38 — Primeiro poll só em t = intervalo, budget curto + sem fallback:** o loop de polling dorme ANTES do primeiro `fetch`, então a primeira verificação só acontece após o intervalo (ex.: t=3s/5s) em vez de t=0. Combinado com um número de tentativas pequeno (budget total curto, abaixo de ~5min), jobs de TTS que demoram um pouco mais estouram o limite de tentativas e o usuário recebe "falha" mesmo quando o áudio foi gerado com sucesso. Não há fallback: ao exaurir as tentativas, o poller simplesmente desiste sem re-consultar o registro do `content`.
- **#39 — `setGeneratingTts(null)` não está no `finally` + style do áudio incorreto:** o reset do estado de loading (`setGeneratingTts(null)`) ocorre apenas no caminho de sucesso. Se o polling lança/timeout/erro de rede, o estado `generatingTts` nunca é zerado e o botão fica preso em "gerando" para sempre. Além disso, quando o áudio é finalmente exposto na UI, o `style`/variante de player aplicado não corresponde ao tipo correto do conteúdo de áudio gerado.

Impacto: experiência quebrada e enganosa — o aluno vê "falha" ou um spinner eterno enquanto o podcast já está disponível no banco (`content.audio_url`), gerando suporte e retrabalho.

## Acceptance Criteria
- [ ] **Poll imediato (t=0):** a primeira verificação de status do job TTS ocorre imediatamente no início do polling (antes de qualquer `sleep`/`setTimeout`), e só então o loop passa a dormir o intervalo entre tentativas subsequentes.
- [ ] **Budget nomeado (~5min):** o orçamento total de polling é uma constante nomeada e legível (ex.: `TTS_POLL_BUDGET_MS = 5 * 60 * 1000` derivando `maxAttempts = budget / intervalMs`), totalizando aproximadamente 5 minutos — não um número mágico curto. O cálculo de tentativas é coerente com o intervalo configurado.
- [ ] **Fallback no timeout (re-fetch do content):** ao exaurir o budget de tentativas sem status terminal, o poller faz um re-fetch final do registro do `content`; se `content.audio_url` estiver presente, o resultado é tratado como **sucesso** (áudio exibido), e não como falha.
- [ ] **Style/variante de player correto:** quando o áudio é exposto, a UI aplica o `style`/variante de player correto correspondente ao conteúdo de áudio gerado (sem reutilizar variante de outro tipo de conteúdo).
- [ ] **`setGeneratingTts(null)` no `finally`:** o reset do estado de loading acontece em um bloco `finally`, garantindo que o botão saia de "gerando" em TODOS os desfechos — sucesso, falha, timeout, erro de rede ou exceção.
- [ ] **Sem regressão de UX:** o caminho feliz (job conclui rápido) continua exibindo o áudio normalmente, e o caminho de falha real (job falhou de fato e sem `audio_url`) exibe mensagem de erro apropriada e libera o botão.

## Tasks / Subtasks
- [ ] Localizar a função de polling de TTS no frontend (handler do botão "gerar podcast/áudio" e o loop de `fetch` de status) e o estado `generatingTts` correspondente.
- [ ] Reordenar o loop para executar o **primeiro `fetch` em t=0**, movendo o `sleep`/`await delay(interval)` para o FIM da iteração (poll → checa → dorme), não o início.
- [ ] Extrair o budget de polling para uma constante nomeada (~5min) e derivar `maxAttempts` a partir do intervalo, removendo números mágicos.
- [ ] Implementar o **fallback de timeout**: ao esgotar tentativas, re-buscar o registro do `content` e, se `content.audio_url` existir, resolver como sucesso e renderizar o player.
- [ ] Corrigir a atribuição do `style`/variante do player de áudio para refletir o tipo correto do conteúdo gerado.
- [ ] Envolver a lógica de polling em `try/catch/finally` e mover `setGeneratingTts(null)` para o `finally`.
- [ ] Validar manualmente os 3 desfechos: conclui rápido (sucesso), demora mas conclui dentro de ~5min via poll, e conclui após timeout (recuperado via fallback `content.audio_url`).

## Dev Notes
- **Arquivos:** frontend do Harven.AI v2 — componente/hook que dispara a geração de TTS e faz o polling de status (handler `generatingTts` / `setGeneratingTts` + loop de `fetch` do status do job e do registro `content`). Confirmar paths exatos via grep por `generatingTts` / `setGeneratingTts` / `audio_url` no repositório antes de editar. Depende de TTSJOB-2 (contrato/persistência do job e do `content.audio_url` no backend).
- **Abordagem:** inverter a ordem poll-then-sleep para sleep-then-poll → poll-then-sleep (primeira checagem em t=0); orçamento de polling nomeado (~5min) com `maxAttempts` derivado do intervalo; no esgotamento, re-fetch do `content` e tratar `audio_url` presente como sucesso; corrigir o `style` do player; centralizar o reset de loading no `finally`.
- **Riscos de regressão:** blast radius restrito ao frontend de geração de áudio/podcast (botão "gerar áudio" e player). Quem chama: a tela de detalhe/leitura de conteúdo que renderiza o botão TTS. Risco baixo — mudança comportamental no fluxo de polling e no reset de estado; verificar que o caminho de falha real (sem `audio_url`) ainda mostra erro e não fica preso, e que o intervalo aumentado de budget não causa excesso de requisições (intervalo entre polls inalterado, apenas o total de tentativas cresce).

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde — cobrindo: (a) primeira chamada de poll em t=0, (b) sucesso via fallback `content.audio_url` no timeout, (c) `setGeneratingTts(null)` chamado em todos os desfechos.
- [ ] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [ ] Verificação manual dos 3 cenários (sucesso rápido, sucesso por poll dentro de ~5min, sucesso por fallback pós-timeout) e do desfecho de falha real (erro exibido + botão liberado).

## QA Results
_(a preencher pelo @qa)_
