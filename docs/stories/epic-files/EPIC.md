---
id: EPIC-FILES
title: File Extraction & Upload Integrity
status: Draft
phases: [4]
story_count: 5
---
# EPIC-FILES: File Extraction & Upload Integrity

## Objetivo

Tornar o pipeline de upload e extração de arquivos confiável, observável e à prova de abuso. Hoje a extração de texto falha silenciosamente em múltiplos eixos: `.pptx` (formato primário de aula) e `.doc` caem em um `else` que apenas loga warning e retorna `None`; o sentinela `None` confunde três resultados distintos (tipo não suportado, falha de parser, parse legítimo vazio); o despacho por extensão antes do content_type permite que binários mal rotulados sejam lidos como UTF-8 e injetados como mojibake no LLM; o upload lê o arquivo inteiro duas vezes em memória; `ValueError` de `save_file` vaza como 500 opaco; as allowlists de MIME e extensão divergem; e `delete_file` corrompe o caminho relativo com `lstrip` (char set, não prefixo) sem guarda de traversal.

Este epic substitui o sentinela `None` por um resultado de extração **estruturado** `{ok, empty, unsupported, failed}`, adiciona suporte real a `.pptx` via `python-pptx` e rejeição explícita e acionável de `.doc`, valida o tipo de arquivo por **magic bytes** e despacha pelo tipo detectado (não pelo filename do cliente), lê o buffer de upload **uma única vez** com mapeamento correto de `ValueError`→400/413, reconcilia as allowlists de MIME e extensão, corrige a corrupção de caminho em `delete_file` com `removeprefix` + guarda de traversal, e **surfacea** o `extraction_status` (com detalhe) na resposta de upload com uma UI de aviso **não-bloqueante** — garantindo que a mídia seja sempre salva mesmo quando a extração de texto falha.

Cobre os defeitos #9, #50, #51, #52, #53, #54 e #61 do BUG-SWEEP-2026-06-03.

## Critérios de Saída (Exit Criteria)

- **Extração estruturada:** `extract()` retorna status `{ok, empty, unsupported, failed}`. `.pptx` → `ok` (via python-pptx); `.doc` → `unsupported` com detalhe acionável; PDF escaneado/só-imagem → `empty`; qualquer exceção → `failed` **sem crash**. `extract_text()` mantém assinatura `Optional[str]` para callers legados.
- **Validação de tipo por magic byte:** PDF/DOCX/PPTX rotulado errado (content_type/filename divergentes do binário) → **400/415**, sem mojibake. Tipos sem magic (txt/md/csv/html) → fallback por extensão. Dispatch ocorre no **tipo detectado**, não no filename do cliente. Dependência `filetype` pinada; `X-Content-Type-Options: nosniff` nos arquivos servidos.
- **Buffer single-read + erros corretos:** o arquivo é lido **1×**; extensão inválida → **400**, oversize → **413** (nunca 500). Allowlists de MIME e extensão reconciliadas. Demais callers de `save_file` permanecem intactos.
- **`delete_file` correto e seguro:** usa `removeprefix('/uploads/')` em vez de `lstrip`; caminho resolvido e validado dentro de `base_dir`; traversal `../` rejeitado (retorna `False`, sem `unlink`).
- **Status surfaceado + UI graciosa:** a resposta de upload inclui `extraction_status` (+`detail`); `body` só é populado quando `ok`; **mídia sempre salva**; `handleUpload` exibe warning **não-bloqueante** em resultado non-ok e avança; `result.id` intacto.

## Stories

| ID | Título | Fase | Terminal | Compl. | Depende de | Severidade |
|:--|:--|:--:|:--|:--:|:--|:--:|
| FILE-1 | Resultado de extração estruturado + suporte `.pptx` + rejeição explícita `.doc` (#9, #51, #52) | 4 | Backend & Infra | med | — | HIGH |
| FILE-2 | Validação magic-byte + dispatch por tipo detectado no upload (#52, #53) | 4 | Backend & Infra | med | FILE-1 | HIGH |
| FILE-3 | Buffer de upload single-read + ValueError→400/413 + reconciliar allowlists (#50, #54) | 4 | Backend & Infra | med | FILE-1 | HIGH |
| FILE-4 | Surfacear `extraction_status` na resposta + UI de erro gracioso (#51) | 4 | UX/UI & Design | low | FILE-1, FILE-3 | HIGH |
| FILE-5 | Corrigir corrupção de path em `delete_file` + guard de traversal (#61) | 4 | Backend & Infra | low | — | HIGH |

## Sequência / Caminho Crítico interno

```
FILE-1 (extração estruturada + .pptx/.doc)
  ├──> FILE-2 (magic-byte + dispatch por tipo detectado)
  ├──> FILE-3 (single-read + ValueError→400/413 + allowlists)
  │       └──┐
  └──────────┴──> FILE-4 (surfacear extraction_status + UI graciosa)   [UX/UI & Design]

FILE-5 (delete_file removeprefix + traversal guard)   [independente — paralelizável]
```

- **FILE-1 é a fundação** do epic: estabelece o contrato `ExtractionResult {ok|empty|unsupported|failed}` que FILE-2, FILE-3 e FILE-4 consomem. Deve ser concluída primeiro.
- **FILE-2 e FILE-3 são paralelizáveis entre si** após FILE-1 — tocam superfícies distintas (sniffing/dispatch vs. buffer/allowlist/error-mapping), com coordenação no ponto de contato (a chamada de upload em `main.py`).
- **FILE-4 é o gate frontend** (cross-terminal, UX/UI & Design): depende do contrato de resposta estabilizado por FILE-1 (campos de status) e FILE-3 (mapeamento de erro 400/413). É a única story do epic fora de Backend & Infra.
- **FILE-5 é totalmente independente** (correção localizada em `storage_service.delete_file`) e pode ser desenvolvida/mesclada em qualquer ordem, sem deps de fases anteriores. O epic inteiro **não depende de fases anteriores** — é paralelizável com os demais epics da Fase 4.

## Notas de Arquitetura

**Hotspots compartilhados (coordenação obrigatória — múltiplas stories tocam os mesmos arquivos):**

- `backend/services/text_extractor.py` — FILE-1 (novo `extract()` estruturado + `_extract_pptx`/rejeição `.doc`) e FILE-2 (sniffing/dispatch por tipo detectado). FILE-1 deve aterrissar primeiro; FILE-2 estende o despacho recém-criado. Hoje `extract_text` despacha por `Path(file_path).suffix` (linha 12-27) — esse é o ponto a refatorar.
- `backend/main.py` (`upload_chapter_file`, ~linhas 1205-1248) — FILE-2 (chamar dispatch por tipo detectado), FILE-3 (single-read + try/except `ValueError`→400/413) e FILE-4 (incluir `extraction_status`+`detail` no shape de resposta). Coordenar a edição: as três modificam o mesmo handler. Ordem recomendada: FILE-3 (estrutura do read + error-mapping) → FILE-2 (sniffing antes do dispatch) → FILE-4 (campos de resposta).
- `backend/services/storage_service.py` — FILE-3 (`save_file_from_bytes` + delegação de `save_file`, reconciliar `ALLOWED_EXTENSIONS`) e FILE-5 (`delete_file` com `removeprefix` + traversal guard). Superfícies disjuntas dentro do arquivo; coordenar para evitar conflito de merge.

**Decisões compartilhadas:**

- **Contrato de extração único (FILE-1 owns):** introduzir um resultado tipado — `ExtractionResult` com `status ∈ {ok, empty, unsupported, failed}`, `text: Optional[str]` e `detail: Optional[str]`. É a fonte canônica de status para todo o epic. `extract_text()` permanece como wrapper `Optional[str]` (retorna `result.text if result.status == 'ok' else None`) para não quebrar `extract_text_from_bytes`, `extract_chapters_from_bytes` e outros callers legados.
- **Ordem de verificação no upload (canônica para FILE-2/FILE-3):** (1) validar extensão na allowlist → `ValueError`→400; (2) ler bytes **uma vez**; (3) checar tamanho → `ValueError`→413; (4) sniff magic bytes e reconciliar com content_type/extensão → divergência→400/415; (5) despachar extração pelo **tipo detectado**; (6) montar resposta com `extraction_status`. O `UploadFile` já é `SpooledTemporaryFile` (rola para disco >1MB) — o defeito #50 é o route ler 2×; a correção é um único `await file.read()` reusado para save e extração via helper `save_file_from_bytes`.
- **Reconciliação de allowlists:** `ALLOWED_EXTENSIONS` (storage_service.py) e `ALLOWED_CONTENT_TYPES`/`ALLOWED_*_TYPES` (main.py) devem ser tratadas como uma única fonte coerente. Nota crítica: `.doc` e `.pptx` constam em `ALLOWED_EXTENSIONS` hoje, mas o extractor não os tratava — a reconciliação deve refletir o suporte real pós-FILE-1 (`.pptx` ok, `.doc` unsupported mas aceito-para-salvar com status surfaceado).
- **Magic-byte (FILE-2):** usar `filetype` (ou `python-magic`) com versão **pinada** no requirements. Sniffing aplica-se a formatos com assinatura binária (PDF/DOCX/PPTX/imagens/áudio/vídeo); txt/md/csv/html não têm magic e usam fallback por extensão. Setar `X-Content-Type-Options: nosniff` (e `Content-Disposition` apropriado) nos uploads servidos via StaticFiles para mitigar content-sniffing.
- **Mídia sempre salva (FILE-4):** falha de extração de texto **nunca** deve impedir o salvamento do conteúdo/mídia. `body` só é populado quando `status == 'ok'`; em `empty`/`unsupported`/`failed`, o conteúdo é criado e a resposta carrega o status + detalhe para a UI exibir warning não-bloqueante. Isso fecha o gap de "upload 200 com body vazio sem indicação".
- **Segurança de path (FILE-5):** após `removeprefix('/uploads/')`, resolver o caminho (`Path.resolve()`) e asserir que está contido em `self.base_dir.resolve()` antes de `unlink`; rejeitar `../` (retorno `False`, sem deleção). `delete_file` parece atualmente não-chamada (bug latente de data-leak) — corrigir preventivamente, sem expandir escopo para callers.
- **Sem migração de DB neste epic:** todas as mudanças são em serviços/handlers/contrato de resposta e frontend; não há alteração de schema. Coordenação com EPIC-FRONT (cluster `media-read-contract`) é apenas de contrato de leitura (campos `body`/`media_url`), fora do escopo direto destas 5 stories.
