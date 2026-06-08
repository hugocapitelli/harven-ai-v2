---
id: FILE-1
epic: EPIC-FILES
phase: 4
status: Draft
severity: HIGH
terminal: Backend & Infra
complexity: medium
depends_on: []
bug_refs: [9, 51, 52]
---
# FILE-1: Resultado de extração estruturado + suporte .pptx + rejeição explícita .doc

## Story
Como aluno/professor que faz upload de materiais no tutor Harven.AI, quero que a extração de texto retorne um resultado estruturado com status claro (sucesso, vazio, não suportado, falha), para que arquivos `.pptx` sejam aceitos, `.doc` sejam rejeitados de forma acionável, e nenhum upload derrube o processamento silenciosamente ou com erro genérico.

## Contexto (do bug sweep)
Os itens #9, #51 e #52 do BUG-SWEEP descrevem falhas no pipeline de extração de texto:

- **#9 — `.doc` aceito sem suporte real:** o legado roteia `.doc` (binário OLE2 antigo) para o mesmo caminho que `.docx`, mas `python-docx` não lê `.doc`. O resultado é uma exceção engolida ou texto vazio, sem sinalizar ao usuário que o formato não é suportado. O usuário acha que enviou material válido quando nada foi indexado.
- **#51 — Resultado de extração não estruturado:** `extract()` retorna `str` cru (ou `None`/`""`), sem distinguir "extração bem-sucedida mas vazia" de "falha de parsing" de "formato não suportado". Callers não conseguem decidir o que mostrar; PDF escaneado (sem camada de texto) retorna `""` indistinguível de erro. A ausência de status impede a UI gracioso planejada em FILE-4.
- **#52 — `.pptx` não extraído + crash em formato inesperado:** `.pptx` não tem branch de extração — cai no `else` genérico e/ou lança exceção não tratada, derrubando o request com 500. Faltava a dependência `python-pptx` e o dispatch correspondente.

Impacto combinado: uploads aparentemente bem-sucedidos não geram contexto para o tutor (#9, #51), e formatos legítimos como `.pptx` quebram o endpoint (#52). O caller legado consome `extract_text()` esperando `Optional[str]` e não pode ser quebrado nesta story.

## Acceptance Criteria
- [ ] `extract()` passa a retornar um resultado estruturado com campo `status` ∈ `{ok, empty, unsupported, failed}` e um campo opcional `detail` (mensagem acionável) — além do texto extraído quando aplicável.
- [ ] `.pptx` é extraído via `python-pptx` (dependência adicionada e pinada) e retorna `status=ok` com o texto concatenado dos slides quando há conteúdo textual.
- [ ] `.doc` (binário antigo OLE2) retorna `status=unsupported` com `detail` acionável (ex.: "Formato .doc não suportado — reenvie como .docx ou .pdf"), **sem** tentar parsear como `.docx` e **sem** lançar exceção.
- [ ] PDF escaneado / arquivo sem camada de texto retorna `status=empty` (extração ocorreu, mas não há texto), distinguível de `failed`.
- [ ] Qualquer exceção durante a extração (parser corrompido, arquivo malformado) é capturada e mapeada para `status=failed` com `detail` — **nenhum crash / 500** propaga ao endpoint.
- [ ] `extract_text()` mantém assinatura `Optional[str]` para callers legados: retorna o texto quando `status=ok`, e `None` (ou `""` conforme contrato atual) para os demais status, sem quebrar quem já consome o retorno antigo.
- [ ] `status=ok` só é retornado quando há texto não-vazio efetivamente extraído.

## Tasks / Subtasks
- [ ] Definir o tipo de resultado estruturado (dataclass/`TypedDict` ou enum de status) no módulo de extração do backend (`backend/app/services/file_extraction.py` ou equivalente — confirmar path real no repo).
- [ ] Refatorar `extract()` para dispatch por tipo com retorno estruturado: branch `.pdf`, `.docx`, `.txt/.md`, e novo branch `.pptx`.
- [ ] Adicionar branch `.pptx` usando `python-pptx`, concatenando texto de shapes/slides; vazio → `status=empty`.
- [ ] Adicionar tratamento explícito de `.doc` → `status=unsupported` com `detail` (interceptar antes do branch `.docx`).
- [ ] Mapear PDF/arquivo sem texto extraível para `status=empty`.
- [ ] Envolver cada parser em `try/except` mapeando exceção → `status=failed` + `detail`, logando o erro original.
- [ ] Reescrever `extract_text()` como wrapper fino sobre `extract()`, preservando `Optional[str]`.
- [ ] Adicionar `python-pptx` ao `requirements.txt`/`pyproject.toml` com versão pinada.
- [ ] Testes de regressão por cenário (ver DoD).

## Dev Notes
- **Arquivos:** módulo de extração de texto do backend (provável `backend/app/services/file_extraction.py` ou similar — localizar `def extract` / `def extract_text` antes de editar); manifesto de dependências (`requirements.txt` ou `pyproject.toml`); fixtures de teste com amostras `.pptx`, `.doc`, PDF escaneado.
- **Abordagem:** introduzir um resultado estruturado (status + texto + detail) como retorno canônico de `extract()`, mantendo `extract_text()` como shim de compatibilidade que devolve `Optional[str]`. Dispatch por extensão/tipo com branch dedicado por formato e `try/except` por parser para garantir ausência de 500. `.doc` é interceptado explicitamente como `unsupported` antes de cair no parser de `.docx`.
- **Riscos de regressão:** `extract()` e `extract_text()` são chamados pelo fluxo de upload do tutor (endpoint de upload de material) e potencialmente por jobs de indexação. Quem hoje espera `str`/`None` de `extract_text()` NÃO pode quebrar — por isso o shim de compatibilidade é mandatório. FILE-2, FILE-3 e FILE-4 dependem desta story (FILE-4 surfaceia `extraction_status` na resposta), então o contrato de status definido aqui é load-bearing para o resto do epic. Adicionar `python-pptx` exige rebuild da imagem/ambiente — coordenar com deploy.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde
- [ ] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [ ] Testes cobrindo os 5 desfechos: `.pptx` com texto → `ok`; `.doc` → `unsupported` (sem exceção); PDF escaneado → `empty`; arquivo corrompido → `failed` (sem 500); `extract_text()` retornando `Optional[str]` para um caller legado.
- [ ] `python-pptx` adicionado e pinado no manifesto de dependências.

## QA Results
_(a preencher pelo @qa)_
