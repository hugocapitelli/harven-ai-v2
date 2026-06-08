---
id: CDC-8
epic: EPIC-CLEANUP
phase: 5
status: Draft
severity: MEDIUM
terminal: UX/UI & Design
complexity: medium
depends_on: [MEDIA-2]
bug_refs: [62]
---
# CDC-8: AbortController no send-message do ChapterReader

## Story
Como aluno usando o tutor de IA dentro de um capítulo, quero que a requisição ao LLM seja cancelada automaticamente quando eu saio da tela (unmount) ou navego para outro capítulo, para não receber toasts de erro falsos, não disparar `setState` em componente desmontado e não desperdiçar respostas de chamadas que não interessam mais.

## Contexto (do bug sweep)
Item de bug **#62** — `apps/frontend/src/components/ChapterReader.tsx`. A função de envio de mensagem ao tutor (`sendMessage` / handler do chat do capítulo) dispara a chamada LLM via `axios` sem associar um `AbortController`. Consequências observadas:

- **setState tardio:** ao desmontar o `ChapterReader` (navegação para outro capítulo, fechar leitor) enquanto a requisição ao LLM ainda está pendente, o `.then`/`await` resolve depois e executa `setState` em um componente já desmontado, gerando warning de memory leak no React e potencial atualização de estado órfão.
- **Toast de erro falso:** quando a requisição é interrompida pela navegação, o `catch` trata o erro genérico de rede e dispara um toast de erro ao aluno, mesmo que o "erro" tenha sido apenas o usuário ter saído da tela de propósito.
- **Cancelamento não diferenciado:** não há distinção entre um cancelamento intencional (`axios` `CanceledError` / `AbortError`) e uma falha real de rede/servidor — ambos caem no mesmo `catch` e viram toast.

Impacto: ruído de UX (toasts indevidos), warnings de leak no console e chamadas LLM que continuam consumindo recurso após perderem relevância. Severidade MEDIUM.

> **Dependência:** esta story rebaseia sobre **MEDIA-2** (remoção do `@ts-nocheck` em `ChapterReader.tsx`). MEDIA-2 deve ser concluída e mergeada antes, pois o arquivo passa a ser type-checked — o `AbortController`/`AbortSignal` introduzido aqui já deve respeitar a tipagem restaurada. Ver roadmap, seção "Arquivos com múltiplas stories" (linha 337): `TPP-6, SF-1/2/3, POD frontend, CDC-8 rebaseiam`.

## Acceptance Criteria
- [ ] O handler de envio de mensagem ao tutor em `ChapterReader.tsx` cria um `AbortController` e passa seu `signal` para a chamada `axios` (via `{ signal }` no config do request).
- [ ] No `useEffect` de cleanup (ou equivalente no unmount), o controller pendente é abortado via `controller.abort()`, cancelando a chamada LLM ainda em voo.
- [ ] Ao navegar para outro capítulo ou desmontar o componente com requisição pendente, **nenhum** `setState` é executado após o unmount (sem warning "Can't perform a React state update on an unmounted component" / sem update órfão).
- [ ] Cancelamento intencional (`axios.isCancel(err)` / `err.name === 'CanceledError'` / `AbortError`) é detectado no `catch` e **não** dispara toast de erro ao aluno.
- [ ] Uma falha real (timeout, 5xx, erro de rede genuíno) continua disparando o toast de erro normalmente — o cancelamento não silencia erros legítimos.
- [ ] Se o aluno disparar um novo envio antes da resposta anterior chegar, o request anterior é abortado e substituído (sem race de respostas fora de ordem) — comportamento explícito e testado.
- [ ] Código respeita a tipagem restaurada por MEDIA-2 (sem reintroduzir `@ts-nocheck` ou `any` no controller/signal).

## Tasks / Subtasks
- [ ] Confirmar que MEDIA-2 está mergeada (`ChapterReader.tsx` sem `@ts-nocheck`); se não, bloquear e sinalizar.
- [ ] Em `apps/frontend/src/components/ChapterReader.tsx`, localizar o handler de envio ao tutor (`sendMessage`/handler do chat) e a chamada `axios`.
- [ ] Introduzir uma `ref` (`useRef<AbortController | null>`) para guardar o controller da requisição em voo.
- [ ] No início do envio: abortar o controller anterior (se existir), criar um novo `AbortController`, salvar na ref e passar `signal: controller.signal` no config do `axios`.
- [ ] Antes de qualquer `setState` no `.then`/`finally`, garantir que o request não foi abortado (checar `signal.aborted` ou guarda de "mounted").
- [ ] No `catch`: usar `axios.isCancel(err)` (ou checagem de `CanceledError`/`AbortError`) e fazer `return` cedo, sem toast, quando for cancelamento; manter o toast apenas para erros reais.
- [ ] Adicionar/ajustar o `useEffect` de cleanup para chamar `controllerRef.current?.abort()` no unmount.
- [ ] Atualizar a tipagem do estado/handlers conforme o `tsc` exigir (pós-MEDIA-2).
- [ ] Escrever teste de regressão (React Testing Library): renderizar `ChapterReader`, disparar envio, desmontar antes da resolução do mock, e assertar que (a) nenhum toast de erro foi chamado e (b) nenhum warning de setState pós-unmount ocorre.

## Dev Notes
- **Arquivos:** `apps/frontend/src/components/ChapterReader.tsx` (alvo único). Possível helper de toast em `apps/frontend/src/components/ui/` ou hook de toast existente — reutilizar, não criar novo.
- **Abordagem:** padrão `AbortController` + `useRef` para guardar o controller corrente + cancelamento no cleanup do `useEffect`. Distinguir cancelamento de erro real com `axios.isCancel` no `catch` (axios moderno também expõe `CanceledError`). Guard de "mounted"/`signal.aborted` antes de `setState`.
- **Riscos de regressão:** o blast radius é local ao `ChapterReader` — o `sendMessage` é interno ao componente do leitor de capítulo do tutor. Atenção a (1) ordem com MEDIA-2 (este arquivo é compartilhado por TPP-6, SF-1/2/3 e POD frontend, todos rebaseando — coordenar merge para evitar conflito); (2) não abortar requisições legítimas em re-render (a ref evita recriar/abortar indevidamente); (3) garantir que o toast de erro real continue funcionando para não mascarar falhas do tutor.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde
- [ ] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [ ] Manual: navegar para fora do capítulo com resposta do tutor pendente NÃO mostra toast de erro e NÃO gera warning de setState no console; falha real do tutor (mock 500) ainda mostra toast.
- [ ] MEDIA-2 confirmada como pré-requisito mergeado; nenhum `@ts-nocheck` reintroduzido em `ChapterReader.tsx`.

## QA Results
_(a preencher pelo @qa)_
