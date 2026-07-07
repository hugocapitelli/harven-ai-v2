---
id: POD-6
epic: EPIC-PODCAST
phase: 4
status: InReview
severity: HIGH
terminal: Backend & Infra
complexity: low
depends_on: [POD-3]
bug_refs: [35, 772]
---
# POD-6: Persistir/recuperar áudio por estilo (corrigir mapping summary-only no reload)

## Story
Como aluno da Harven.AI que gera áudios em estilos diferentes (podcast, summary, explanation) para um mesmo capítulo, quero que cada áudio seja persistido e recuperado pelo seu estilo real, para que ao recarregar a página o podcast volte no slot de podcast (e não no de summary) e múltiplos estilos coexistam sem se sobrescrever.

## Contexto (do bug sweep)
O reader assume que todo `audio_url` persistido é do estilo summary. Em `ChapterReader.tsx:219-224`, `content.audio_url` é mapeado para `ttsUrls.summary` **independentemente do estilo realmente gerado** (item 772 do bug sweep). Isso ocorre porque a tabela `contents` só guarda `audio_url`, sem registrar **qual** `audio_type` produziu aquela URL — a coluna `contents.audio_type` simplesmente não existe no schema (gap apontado no review do roadmap, linha 427 do REMEDIATION-ROADMAP: "`contents.audio_type` faltante — POD-6 e o deferral de media-read precisam da coluna mas nenhum cluster a adicionava").

Impacto concreto:
- Aluno gera um **podcast** → ao recarregar, o áudio aparece no slot **summary**, induzindo a UX a oferecer "gerar podcast" novamente (re-gasto de tokens LLM+TTS) e exibindo o áudio errado no lugar errado.
- Estilos não coexistem: como há apenas um campo `audio_url`, a geração de um segundo estilo sobrescreve o primeiro (último a persistir vence), em vez de manter podcast e summary lado a lado.
- O contrato de leitura não consegue keyar o áudio por estilo, perpetuando o descasamento entre o que foi gerado e o que o reader renderiza.

Defeito correlato (item 35, `contents.audio_url` engolido em try/except no worker) é tratado em outra story; aqui o foco é **persistir o estilo junto da URL e recuperar por estilo**, eliminando o mapeamento summary-only.

## Acceptance Criteria
- [ ] Existe migração SQL que adiciona a coluna `contents.audio_type` (text, nullable, com CHECK `audio_type IN ('podcast','summary','explanation')` ou equivalente), idempotente (`ADD COLUMN IF NOT EXISTS`), sem default destrutivo para rows existentes.
- [ ] Ao concluir um job TTS, o backend persiste **tanto** `contents.audio_url` **quanto** `contents.audio_type` com o estilo realmente gerado, na mesma transação/UPDATE.
- [ ] No reload, o endpoint de leitura retorna `audio_type` junto de `audio_url`, e o reader mapeia o áudio para o slot correto pelo `audio_type` real — um podcast recarrega no slot **podcast**, não em `ttsUrls.summary`.
- [ ] Múltiplos estilos coexistem: gerar summary após um podcast (ou vice-versa) **não** sobrescreve o áudio do outro estilo; ambos ficam recuperáveis após reload.
- [ ] **Sem regressão para `audio_url` legado:** rows pré-migração com `audio_url` populado e `audio_type` nulo continuam carregando — fallback documentado e determinístico (ex.: `audio_type` ausente → tratar como `summary`, comportamento atual, evitando quebrar áudios existentes).
- [ ] `ChapterReader.tsx:219-224` deixa de hardcodar `ttsUrls.summary`; o mapeamento passa a derivar do `audio_type` retornado pelo contrato.

## Tasks / Subtasks
- [ ] Criar migração em `supabase/migrations/` (ou diretório de migrações do projeto) adicionando `contents.audio_type` com CHECK constraint e `IF NOT EXISTS`; validar rollback/idempotência.
- [ ] No worker/handler de TTS (mesmo arquivo onde `contents.audio_url = ...` é persistido — `_run_tts_job`), incluir `audio_type` no payload de UPDATE para `contents`.
- [ ] Atualizar o(s) endpoint(s) de leitura de conteúdo para retornar `audio_type` na row (ajustar o serializer/contrato que hoje devolve `audio_url`).
- [ ] Atualizar `ChapterReader.tsx` (linhas ~219-224) para keyar o áudio por `audio_type` (montar `ttsUrls[content.audio_type ?? 'summary'] = content.audio_url`) em vez de forçar `summary`.
- [ ] Adicionar fallback explícito para `audio_type` nulo (legado) → `summary`, com comentário no código justificando.
- [ ] Verificar que a geração de um segundo estilo não faz UPDATE destrutivo do estilo anterior (confirmar modelagem: se um único `audio_url` por row, alinhar com POD-3; se múltiplos, garantir storage por estilo).

## Dev Notes
- **Arquivos:**
  - Migração: `/Users/hugocapitelli/Dev/eximia/harven-ai-v2/supabase/migrations/` (nova migração `*_add_contents_audio_type.sql`).
  - Backend TTS/persistência: handler `_run_tts_job` (mesmo local do `contents.audio_url = ...`) e o endpoint/serializer de leitura de `contents`.
  - Frontend: `ChapterReader.tsx` (mapeamento `ttsUrls`, linhas ~219-224).
- **Abordagem:** Adicionar `contents.audio_type` via migração idempotente; persistir o estilo junto da URL no fim do job; expor `audio_type` no contrato de leitura; e no reader derivar o slot do `audio_type` real, com fallback `summary` para o legado. Mudança de baixa complexidade (uma coluna + um campo no UPDATE + um campo no contrato + ajuste de mapping), mas que destrava a coexistência de estilos e corrige o reload errado.
- **Riscos de regressão:**
  - **Blast radius backend:** qualquer consumidor da row `contents` que monte o objeto de leitura; o UPDATE em `_run_tts_job` é compartilhado por todos os estilos — garantir que `summary`/`explanation` continuem persistindo seus próprios tipos.
  - **Blast radius frontend:** `ChapterReader` é a única superfície de renderização de áudio por estilo; mudar o mapping afeta os três slots (`podcast`/`summary`/`explanation`).
  - **Legado:** rows com `audio_url` e `audio_type` nulo (geradas antes da migração) — sem o fallback `→ summary`, deixariam de renderizar. CHECK constraint deve permitir NULL para não bloquear rows existentes.
  - **Dependência POD-3:** o branch `podcast` precisa estar gerando/persistindo corretamente (POD-3) para que o `audio_type='podcast'` faça sentido ponta a ponta; por isso `depends_on: [POD-3]`.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: gerar podcast → reload → áudio aparece no slot podcast (não summary); e summary+podcast coexistem após reload.
- [ ] Sem regressão na suíte de segurança (a persistência por estilo não introduz leitura/escrita cruzada de áudio; autorização do read/write de `contents` inalterada).
- [ ] QA Gate: PASS ou CONCERNS
- [ ] Migração `contents.audio_type` aplicada e idempotente (re-rodar não falha); rows legadas com `audio_type` nulo seguem carregando via fallback `summary`.

## QA Results
_(a preencher pelo @qa)_
