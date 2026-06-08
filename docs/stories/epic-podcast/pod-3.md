---
id: POD-3
epic: EPIC-PODCAST
phase: 4
status: Draft
severity: HIGH
terminal: Backend & Infra
complexity: low
depends_on: [POD-2]
bug_refs: [34]
---
# POD-3: Persistência de `audio_url` autoritativa + reuso do cliente Supabase compartilhado

## Story
Como engenheiro de backend responsável pelo pipeline de TTS/podcast, quero que a persistência do `audio_url` seja autoritativa — só marcando o job como concluído quando o `UPDATE` no banco realmente gravar — e que o fluxo reutilize o cliente Supabase compartilhado em vez de instanciar um cliente por job, para que o usuário nunca veja um estado `done` fantasma com áudio inacessível e o frontend exiba erro real quando a persistência falhar.

## Contexto (do bug sweep)
Item de bug **#34**: o pipeline de síntese de áudio (podcast/TTS) marca o job como `done` mesmo quando o `UPDATE` da coluna `audio_url` no banco falha após esgotar os retries. O resultado é um "done fantasma": o job aparece concluído para o cliente, mas a URL do áudio nunca foi persistida — gerando áudio órfão (storage gravado, ponteiro perdido) e quebra silenciosa na hora de recarregar/reproduzir.

Dois defeitos concretos no fluxo de finalização do job de áudio (serviço de podcast/TTS no backend):
1. **Estado `done` desacoplado da persistência:** o código define o status terminal `done` independentemente do sucesso do `UPDATE` de `audio_url`. Após os retries de gravação falharem, deveria registrar `error`/`persisted=false`, mas registra sucesso.
2. **Cliente Supabase por-job:** cada execução de síntese cria sua própria instância do cliente Supabase ao invés de reusar o cliente compartilhado/injetado da aplicação — fonte de inconsistência de configuração, conexões desperdiçadas e divergência de credenciais entre o cliente de leitura e o de escrita.

Impacto downstream no frontend: ao receber `status: done` sem `audio_url` válido, a UI dispara o **success toast** ("áudio gerado") mesmo sem áudio reproduzível, mascarando a falha em vez de mostrar erro acionável.

## Acceptance Criteria
- [ ] Quando o `UPDATE` de `audio_url` no banco falhar após esgotar todos os retries, o job é finalizado com status terminal `error` (e/ou `persisted=false`) — **nunca** `done`.
- [ ] O status `done` só é atribuído quando o `UPDATE` de `audio_url` confirmar a gravação (linha afetada / retorno de sucesso do Supabase).
- [ ] O fluxo de síntese de áudio reutiliza o **cliente Supabase compartilhado** da aplicação; nenhum cliente Supabase é instanciado por-job no caminho de podcast/TTS.
- [ ] O contrato de resposta do job expõe o desfecho de persistência (ex.: `status` terminal + `persisted: boolean`/`audio_url: string|null`) de forma que o frontend distingue "concluído com áudio" de "falhou ao persistir".
- [ ] No frontend, quando o job retorna sem `audio_url` persistido (`error`/`persisted=false`/`audio_url` nulo), a UI exibe **mensagem de erro acionável** e **NÃO** dispara o success toast de "áudio gerado".
- [ ] No caminho feliz (UPDATE bem-sucedido), o comportamento atual é preservado: `done` + `audio_url` válido + success toast.

## Tasks / Subtasks
- [ ] Localizar o serviço de síntese de áudio/podcast no backend (job runner de TTS, ex.: `backend/app/services/podcast_service.py` / `tts_service.py`) e identificar o ponto onde o status `done` é definido.
- [ ] Refatorar a finalização do job: capturar o resultado do `UPDATE` de `audio_url`; em sucesso → `done` + `audio_url`; em falha após retries → `error`/`persisted=false`, sem gravar `done`.
- [ ] Garantir que a falha de persistência seja logada com contexto (job_id, content_id, audio_type, erro) para diagnóstico.
- [ ] Substituir a criação de cliente Supabase por-job pela injeção/reuso do cliente compartilhado da app (ex.: `get_supabase_client()` / dependência já existente usada nos demais services).
- [ ] Ajustar o schema/serialização da resposta do job para carregar o desfecho de persistência (`persisted`/`audio_url` nulo em falha).
- [ ] No frontend (componente/handler que consome o resultado do job de podcast/TTS), ramificar pelo desfecho: success toast somente com `audio_url` persistido; caso contrário, erro acionável.
- [ ] Escrever teste de regressão backend: simular `UPDATE` falhando após retries → assert status `error`/`persisted=false`, nunca `done`.
- [ ] Escrever/ajustar teste frontend: resposta sem `audio_url` → assert erro exibido e nenhum success toast.

## Dev Notes
- **Arquivos:**
  - Backend — serviço de síntese de áudio/podcast (job runner de TTS) onde o status terminal é definido e onde o `UPDATE` de `audio_url` ocorre (ex.: `backend/app/services/podcast_service.py` / `backend/app/services/tts_service.py`).
  - Backend — provider do cliente Supabase compartilhado (ex.: `backend/app/db/supabase.py` / `backend/app/core/clients.py`) a ser reutilizado.
  - Backend — schema/serializer da resposta do job (ex.: `backend/app/schemas/podcast.py`).
  - Frontend — handler/componente que consome o resultado do job de podcast/TTS e dispara o toast (ex.: `frontend/src/components/Podcast/*` ou hook de polling de TTS).
- **Abordagem:** Tornar a persistência **autoritativa** — o status terminal é derivado do resultado real do `UPDATE`, não definido antes/independente dele. Centralizar o acesso ao Supabase no cliente compartilhado (consistência de config/credenciais e economia de conexões). Propagar o desfecho de persistência até o frontend para que a UX reflita a verdade (erro vs. sucesso).
- **Riscos de regressão:** O blast radius é o caminho de geração de áudio/podcast. Tocar na finalização do job afeta todos os consumidores do status terminal (poller de TTS — ver TTSJOB-3/TTSJOB-4 — e o reload de conteúdo). Trocar o cliente Supabase por-job pelo compartilhado pode alterar contexto de auth/RLS se o cliente por-job usava credenciais distintas; validar que escrita de `audio_url` continua autorizada com o cliente compartilhado. Mudança no contrato de resposta exige sincronizar frontend (toast) para não quebrar o caminho feliz. Depende de **POD-2** (estrutura de job/contrato base já estabilizada).

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: `UPDATE` falho após retries não produz `done`.
- [ ] Sem regressão na suíte de segurança.
- [ ] QA Gate: PASS ou CONCERNS.
- [ ] Nenhum cliente Supabase instanciado por-job no caminho de podcast/TTS (verificado por grep/teste).
- [ ] Frontend: success toast aparece somente com `audio_url` persistido; falha de persistência exibe erro acionável.
- [ ] Caminho feliz (UPDATE OK) preservado: `done` + `audio_url` + toast de sucesso.

## QA Results
_(a preencher pelo @qa)_
