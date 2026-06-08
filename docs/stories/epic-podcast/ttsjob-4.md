---
id: TTSJOB-4
epic: EPIC-PODCAST
phase: 4
status: Draft
severity: HIGH
terminal: UX/UI & Design
complexity: low
depends_on: [TTSJOB-3]
bug_refs: [38, 39]
---
# TTSJOB-4: Poller TTS resiliente a 404 transiente / restart durante polling

## Story
Como usuário aguardando a geração do áudio de um podcast, quero que o polling de status do job de TTS sobreviva a um 404 transiente ou a um restart do backend durante a espera, para que eu não fique preso num estado de erro permanente e ainda receba o áudio quando ele estiver pronto.

## Contexto (do bug sweep)
Durante a fase de geração assíncrona de TTS, o frontend faz polling contínuo do endpoint de status do job. Os itens #38 e #39 do bug sweep documentam dois modos de falha do poller atual:

- **#38 — 404 transiente colapsa o poller:** se o backend responde 404 uma única vez no meio do polling (por exemplo durante um redeploy/restart, race entre criação do job e a primeira leitura, ou cold start do worker), o poller trata o 404 como erro terminal e para imediatamente. O usuário é jogado num estado de "falha" mesmo quando o job ainda está vivo e o áudio será gerado segundos depois. O job real continua no backend, mas a UI nunca mais o consulta.
- **#39 — restart durante polling perde o resultado:** quando o backend reinicia enquanto o polling está ativo, a sequência de respostas pode intercalar erros de rede / 404 / 5xx transientes. Sem tolerância a falhas transientes nem fallback, o poller desiste e o usuário não recebe o áudio que já está disponível em `content.audio_url` (campo persistido no conteúdo quando o job conclui), forçando-o a recarregar a página manualmente para descobrir que o áudio existia.

Impacto: experiência quebrada na funcionalidade de podcast — usuário vê erro quando deveria ver áudio pronto. Severidade HIGH por afetar o caminho feliz principal do produto sob condições operacionais normais (deploys, restarts, cold starts).

## Acceptance Criteria
- [ ] Um único 404 no meio do polling NÃO colapsa o poller: o poller continua tentando dentro do limite de tolerância configurado, sem expor erro terminal ao usuário.
- [ ] Um 404 **persistente** (após N tentativas consecutivas excedidas) faz o poller parar de consultar o job e usar o fallback `content.audio_url` quando esse campo estiver populado; se o áudio estiver disponível via fallback, o usuário recebe o áudio em vez de um erro.
- [ ] Erros transientes (404, timeout de rede, 5xx) são tolerados até **N vezes consecutivas** (N configurável, default explícito definido no Dev) antes de o poller considerar falha real; o contador de transientes é resetado a cada resposta de sucesso (200).
- [ ] O estado do poller distingue explicitamente os cenários e expõe um `status` legível pela UI: `polling` (em andamento), `transient_error` (erro transiente tolerado, ainda tentando), `completed` (job concluído), `fallback` (job não encontrado mas áudio recuperado via `content.audio_url`) e `failed` (falha real após esgotar tolerância e sem fallback disponível).
- [ ] A UI consome o `status` exposto para diferenciar um 404 transiente (sem alarme visível) de uma falha real (mensagem de erro), nunca mostrando erro ao usuário enquanto o poller ainda está em janela de tolerância.

## Tasks / Subtasks
- [ ] Localizar a função/hook de polling de status do job TTS no frontend (hook de podcast / componente do player de áudio) e o endpoint de status consumido.
- [ ] Introduzir um contador de tentativas transientes consecutivas e uma constante `MAX_TRANSIENT_RETRIES` (N) com valor default explícito; resetar o contador em toda resposta 200.
- [ ] Tratar 404 como transiente enquanto `transientCount < N`; só promover a falha terminal quando o limite for excedido.
- [ ] Ao exceder o limite de 404 persistente, consultar o campo `content.audio_url` do conteúdo já carregado; se presente, transicionar para `status: 'fallback'` e entregar o áudio; caso contrário transicionar para `status: 'failed'`.
- [ ] Tratar erros de rede e 5xx pela mesma lógica de tolerância transiente (mesmo contador), para cobrir o cenário de restart do backend (#39).
- [ ] Expor um campo `status` (enum `polling | transient_error | completed | fallback | failed`) no retorno do hook/estado do poller.
- [ ] Ajustar o componente de UI que renderiza o estado do podcast para mapear cada `status` ao tratamento visual correto (loading discreto para `transient_error`, áudio para `completed`/`fallback`, erro só para `failed`).
- [ ] Adicionar teste de regressão que simule a sequência de respostas: 200 → 404 (único) → 200 (não colapsa); e a sequência 404…404 persistente com `content.audio_url` presente (cai em `fallback`).

## Dev Notes
- **Arquivos:** hook/serviço de polling de status do TTS no frontend (`apps/web` — hook de podcast/player de áudio) e o componente de UI que renderiza o estado do podcast; endpoint de status do job no backend (apenas leitura/confirmação do contrato de resposta, não alteração). Confirmar paths exatos via grep por "audio_url" e pelo nome do endpoint de status do job antes de editar.
- **Abordagem:** mudança localizada e de baixo risco no cliente — adicionar uma máquina de estados leve no poller com (a) tolerância a falhas transientes via contador consecutivo resetável, (b) fallback determinístico para `content.audio_url` em caso de 404 persistente, e (c) um enum de `status` que torna explícito para a UI a diferença entre "transiente, aguarde" e "falha real". Depende de TTSJOB-3 estar concluída (estado/contrato do job estabilizado upstream); reusar o contrato definido lá em vez de criar campos novos.
- **Riscos de regressão:** blast radius restrito ao fluxo de podcast/TTS. Quem chama o código tocado: o componente do player de podcast e qualquer tela que renderize o estado de geração de áudio. Risco principal é mascarar uma falha real por excesso de tolerância — mitigado por N pequeno e default explícito, e pela transição clara para `failed` quando sem fallback. Garantir que o reset do contador em 200 não esconda um job que oscila entre sucesso e 404 indefinidamente (a transição para `completed`/`fallback` deve sempre vencer).

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: cobre o 404 único (não colapsa) e o 404 persistente com fallback `content.audio_url`.
- [ ] Sem regressão na suíte de segurança.
- [ ] QA Gate: PASS ou CONCERNS.
- [ ] O `status` do poller é consumido pela UI e nenhum erro é exibido ao usuário durante a janela de tolerância transiente; o áudio é entregue via fallback quando o job some mas `content.audio_url` existe.

## QA Results
_(a preencher pelo @qa)_
