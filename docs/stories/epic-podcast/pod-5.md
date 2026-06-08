---
id: POD-5
epic: EPIC-PODCAST
phase: 4
status: Draft
severity: HIGH
terminal: Backend & Infra
complexity: medium
depends_on: [POD-3]
bug_refs: [36]
---
# POD-5: Rotear áudio via StorageService (object storage + retenção local-FS)

## Story
Como aluno que gera podcasts/áudios no tutor Harven.AI, quero que o arquivo de áudio fique acessível por uma URL estável que sobreviva a redeploys e restarts, para que eu não perca o áudio recém-gerado quando a aplicação reinicia ou troca de réplica.

## Contexto (do bug sweep)
Item #36 (object storage dormant): hoje o áudio gerado (podcast/summary) é persistido apenas no filesystem local do worker e referenciado por um caminho relativo. Em ambiente EasyPanel/Docker, o filesystem do container é efêmero: qualquer redeploy ou restart descarta os arquivos, e em cenário multi-réplica uma réplica não enxerga o áudio escrito por outra. Resultado: `audio_url` aponta para um arquivo que deixa de existir, e o player do aluno quebra silenciosamente após o deploy. O roadmap (linha 211) define que POD-5 deve rotear a escrita de áudio por um `StorageService` que prefere object storage (URL estável e durável) com fallback para local-FS quando a flag está desligada, mais um sweep por TTL para limpar áudio local órfão. Conforme nota de risco do roadmap (linha 430), o backend de object storage entra **atrás de uma flag default-off**: a durabilidade multi-réplica fica dormente até a flag ser ligada (aceitável em single-worker hoje), mas o caminho de código já fica pronto e o reader já passa a lidar tanto com URL relativa quanto absoluta.

## Acceptance Criteria
- [ ] Existe um `StorageService` (camada de abstração) com método de escrita que recebe os bytes + metadados do áudio e retorna a `audio_url` a ser persistida em `contents.audio_url` (sempre `string`).
- [ ] Com a flag de object storage **ligada**, a escrita de áudio vai para o object storage e a `audio_url` retornada é uma **URL absoluta estável** que sobrevive a redeploy/restart (o arquivo continua acessível após reinício do container).
- [ ] Com a flag **desligada** (default-off), o comportamento atual de fallback local-FS é preservado e a `audio_url` permanece uma **URL/caminho relativo** — sem regressão para o fluxo single-worker em produção.
- [ ] O reader/servidor de áudio aceita tanto `audio_url` **relativa** (legado/local-FS) quanto **absoluta** (object storage) e resolve corretamente em ambos os casos — áudios já existentes (relativos) continuam tocando.
- [ ] Há um **sweep por TTL** que remove arquivos de áudio locais órfãos/expirados (apenas no caminho local-FS), sem nunca apagar áudio referenciado por uma `audio_url` ativa.
- [ ] A geração de podcast/summary continua funcionando end-to-end: gerar áudio → persistir `audio_url` → recarregar a página → o player resolve a URL e reproduz.
- [ ] Nenhum caller existente que lê `audio_url` quebra (forma do dado permanece `string`; só o conteúdo passa a poder ser absoluto).

## Tasks / Subtasks
- [ ] Criar/estender o `StorageService` no backend (`backend/app/services/storage_service.py` ou módulo de services equivalente) com a interface de escrita de áudio que retorna `audio_url` string e seleciona backend (object storage vs local-FS) conforme flag.
- [ ] Adicionar a flag de configuração (default-off) em `backend/app/core/config.py` (ex.: `OBJECT_STORAGE_ENABLED` + credenciais/bucket do object storage) e validar no boot-guard sem torná-lo fail-closed quando a flag está desligada.
- [ ] Rotear a escrita de áudio do TTS/podcast (gerada em `_run_tts_job` / serviço de áudio do podcast, dependência de POD-3) para passar pelo `StorageService` em vez de gravar direto no FS local.
- [ ] Ajustar o reader/endpoint que serve áudio (rota de mídia/áudio + frontend que monta o `src` do player) para aceitar `audio_url` relativa **e** absoluta: se absoluta, usar direto; se relativa, resolver contra o base path local como hoje.
- [ ] Implementar o sweep por TTL dos arquivos locais órfãos (job/utilitário no caminho local-FS), garantindo que só remove arquivos terminais/expirados e nunca os referenciados por `audio_url` ativa.
- [ ] Garantir persistência: a `audio_url` retornada pelo `StorageService` é gravada em `contents.audio_url` no fluxo de geração (alinhado com POD-3/POD-6).

## Dev Notes
- **Arquivos:**
  - `backend/app/services/storage_service.py` (novo/estendido — abstração de storage)
  - `backend/app/core/config.py` (flag default-off + config do object storage)
  - serviço de geração de áudio/TTS do podcast (`_run_tts_job` e serviço de podcast — herdado de POD-3)
  - endpoint/rota que serve mídia/áudio + componente do player no frontend (resolução de URL relativa vs absoluta)
- **Abordagem:** Introduzir uma indireção (`StorageService`) entre a geração de áudio e a persistência da `audio_url`. O serviço escolhe object storage (URL absoluta durável) ou local-FS (URL relativa) por flag default-off — alinhado à nota de risco do roadmap (linha 430): caminho pronto, durabilidade multi-réplica dormente até ligar a flag. O reader passa a ser agnóstico: detecta se a `audio_url` é absoluta (http/https) ou relativa e resolve cada caso. O sweep por TTL limpa apenas órfãos locais, jamais referências ativas.
- **Riscos de regressão:** O blast radius cobre todo o pipeline de áudio do podcast/summary — quem chama `_run_tts_job` (POD-3) e quem persiste/lê `audio_url` (POD-6 e os pollers TTSJOB-2/3/4 que fazem fallback para `content.audio_url`). Como POD-6 e TTSJOB dependem de `audio_url` permanecer `string`, NÃO mudar a forma do campo — apenas permitir conteúdo absoluto. Áudios legados gravados com caminho relativo DEVEM continuar tocando (reader retrocompatível). O sweep por TTL é o ponto de maior risco: uma regra de retenção mal calibrada pode apagar áudio ainda referenciado — restringir estritamente a órfãos/expirados do caminho local-FS.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: cenário "áudio gerado sobrevive a restart/redeploy quando flag ligada" e "áudio legado relativo continua resolvendo quando flag desligada".
- [ ] Sem regressão na suíte de segurança (incl. `idor_matrix` presence-check e ownership de conteúdo).
- [ ] QA Gate: PASS ou CONCERNS.
- [ ] Flag de object storage permanece **default-off** após o merge (fallback local-FS é o comportamento padrão em single-worker).
- [ ] `audio_url` permanece tipo `string` para todos os callers (POD-6, TTSJOB-2/3/4) — verificado que nenhum consumidor quebra.
- [ ] Sweep por TTL coberto por teste que prova que arquivos referenciados por `audio_url` ativa NÃO são removidos.

## QA Results
_(a preencher pelo @qa)_
