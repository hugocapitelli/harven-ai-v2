---
id: CDC-7
epic: EPIC-CLEANUP
phase: 5
status: Draft
severity: MEDIUM
terminal: UX/UI & Design
complexity: low
depends_on: []
bug_refs: [62]
---
# CDC-7: Corrigir ttsApi.generate cliente morto para contrato JSON-body

## Story
Como desenvolvedor frontend integrando o tutor de voz da Harven.AI, quero que `ttsApi.generate` envie a requisição no contrato real esperado pelo backend (body JSON `{text, voice}`), para que a síntese de voz funcione de fato em vez de quebrar silenciosamente por um cliente desalinhado e morto.

## Contexto (do bug sweep)
Item #62 do bug sweep: o método `ttsApi.generate` no cliente de API do frontend está "morto" — ele monta a chamada usando o contrato errado (query params e/ou shape divergente) e por isso nunca aciona corretamente o endpoint de TTS do backend. Além disso, injeta um valor default de voz `'alloy'` no cliente, escondendo o contrato real e mascarando ausência de seleção de voz. O endpoint real de geração de áudio espera um body JSON com `{ text, voice }`. Resultado: a chamada de geração de TTS falha ou retorna comportamento inesperado, deixando o recurso de voz inoperante para o usuário final. Os demais métodos de `ttsApi` (que não `generate`) funcionam e não devem ser alterados.

## Acceptance Criteria
- [ ] `ttsApi.generate` envia a requisição com body JSON `{ text, voice }` (POST com `Content-Type: application/json`), e NÃO usa query params para esses campos.
- [ ] O cliente NÃO injeta mais o default `'alloy'` para `voice` — o valor de voz vem do chamador; se ausente, segue o contrato do backend (não é silenciosamente preenchido pelo cliente).
- [ ] A chamada efetiva atinge o endpoint de TTS correto do backend e a resposta de áudio é consumida com sucesso pelo fluxo que invoca `ttsApi.generate`.
- [ ] Todos os demais métodos de `ttsApi` permanecem inalterados (mesma assinatura, mesmo comportamento, sem regressão).
- [ ] Nenhuma mudança de contrato no backend é introduzida — a correção é exclusivamente no cliente frontend para alinhar ao contrato já existente.

## Tasks / Subtasks
- [ ] Localizar a definição de `ttsApi.generate` no cliente de API do frontend (arquivo do módulo `ttsApi` / api client) e confirmar o shape atual (query params + default `'alloy'`).
- [ ] Reescrever `generate` para POST com body JSON `{ text, voice }` e header `Content-Type: application/json`, removendo a montagem via params.
- [ ] Remover o default `'alloy'` para `voice`; encaminhar o valor recebido do chamador sem substituição silenciosa.
- [ ] Verificar o(s) chamador(es) de `ttsApi.generate` (componente/hook do tutor de voz) para garantir que passam `text` e `voice` conforme o novo contrato.
- [ ] Confirmar, lendo o endpoint TTS do backend, que o contrato esperado é body JSON `{ text, voice }` e que a URL/rota usada pelo cliente está correta.
- [ ] Garantir que os demais métodos de `ttsApi` não foram tocados (diff cirúrgico apenas em `generate`).

## Dev Notes
- **Arquivos:** cliente de API do frontend onde reside `ttsApi` (módulo de api client do frontend — ex.: `lib/api/tts*` ou equivalente); chamador(es) do tutor de voz que invocam `ttsApi.generate`; endpoint TTS do backend (apenas leitura, para confirmar contrato — não alterar).
- **Abordagem:** Mudança cirúrgica de baixo risco isolada ao método `generate`: trocar a montagem de query params por `fetch`/cliente HTTP com `method: 'POST'`, `headers: { 'Content-Type': 'application/json' }` e `body: JSON.stringify({ text, voice })`. Remover o fallback `voice = 'alloy'` para que o cliente não invente valor.
- **Riscos de regressão:** Blast radius pequeno — apenas o(s) chamador(es) de `ttsApi.generate` (fluxo de voz do tutor). Risco de regressão se algum chamador dependia implicitamente do default `'alloy'`; mitigar verificando que todo chamador passa `voice` explicitamente. Não há impacto nos demais métodos de `ttsApi` pois não são tocados.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde — comprovando que `generate` agora posta body JSON `{text, voice}` e atinge o endpoint correto.
- [ ] Sem regressão na suíte de segurança.
- [ ] QA Gate: PASS ou CONCERNS.
- [ ] Confirmado via inspeção de diff que `generate` não usa mais query params, não injeta default `'alloy'`, e que nenhum outro método de `ttsApi` foi modificado.

## QA Results
_(a preencher pelo @qa)_
