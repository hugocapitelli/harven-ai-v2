---
id: CDC-6
epic: EPIC-CLEANUP
phase: 5
status: Draft
severity: MEDIUM
terminal: Backend & Infra
complexity: low
depends_on: []
bug_refs: [62]
---
# CDC-6: Deletar schemas/ai.py + schemas/chat.py mortos e remover imports do __init__

## Story
Como mantenedor do backend Harven.AI, quero remover os módulos `schemas/ai.py` e `schemas/chat.py` que estão mortos (não consumidos por nenhuma rota ou serviço ativo) e limpar suas referências no `schemas/__init__.py`, para reduzir a superfície de código morto, evitar confusão sobre qual schema é o canônico e impedir que esses módulos ressuscitem silenciosamente em futuras edições.

## Contexto (do bug sweep)
Item #62 do bug sweep identificou code/contract drift acumulado no backend, incluindo módulos de schema mortos. Os arquivos `backend/app/schemas/ai.py` e `backend/app/schemas/chat.py` definem modelos Pydantic que não são mais importados por nenhuma rota, serviço ou dependência ativa — os contratos vivos de IA/chat migraram para outros módulos de schema. Apesar de mortos, eles permanecem importados/re-exportados em `backend/app/schemas/__init__.py`, o que: (1) infla a superfície de manutenção, (2) cria ambiguidade sobre qual schema é o canônico, e (3) pode ser inadvertidamente reintroduzido em handlers novos, recriando contratos divergentes. Impacto: dívida técnica e risco de drift de contrato, sem efeito em runtime hoje (o código não é exercido), por isso a severidade é MEDIUM e a complexidade low.

## Acceptance Criteria
- [ ] `backend/app/schemas/ai.py` e `backend/app/schemas/chat.py` deletados do repositório.
- [ ] `backend/app/schemas/__init__.py` não importa nem re-exporta nada de `ai` ou `chat`; o módulo importa limpo (sem `ImportError`/`NameError`).
- [ ] Confirmado por grep que NENHUM outro módulo do backend (`backend/app/**`) ainda faz `from app.schemas.ai import ...`, `from app.schemas.chat import ...`, `import app.schemas.ai`, `import app.schemas.chat` ou `from .ai`/`from .chat` dentro de `schemas/`. Se algum consumidor residual existir, a story é bloqueada e escalada (presunção é que estão mortos — validar antes de deletar).
- [ ] App boota: `from app.main import app` (ou import equivalente do entrypoint FastAPI) executa sem erro após a remoção.
- [ ] Contrato OpenAPI inalterado: o `openapi.json` gerado pelo app é idêntico ao baseline (mesmos paths, schemas/components e operações) — confirma que os módulos eram de fato mortos e nenhuma rota dependia deles.
- [ ] CI grep guard adicionado que falha o pipeline se `schemas/ai.py`, `schemas/chat.py` ou qualquer import desses módulos reaparecer (proteção anti-ressurreição).

## Tasks / Subtasks
- [ ] Verificar morte do código: rodar grep em `backend/app/` por `schemas.ai`, `schemas.chat`, `from .ai`, `from .chat`, `import ai`, `import chat` (escopado ao pacote `schemas`) e confirmar que os únicos hits estão dentro de `schemas/ai.py`, `schemas/chat.py` e `schemas/__init__.py`.
- [ ] Capturar baseline do OpenAPI antes da mudança: gerar `openapi.json` a partir do app atual e salvar como referência temporária para diff.
- [ ] Remover de `backend/app/schemas/__init__.py` todas as linhas de `import`/re-export referentes a `ai` e `chat` (e remover esses nomes de qualquer `__all__` se presente).
- [ ] Deletar `backend/app/schemas/ai.py` e `backend/app/schemas/chat.py` (`git rm`).
- [ ] Bootar o app localmente e confirmar import limpo do entrypoint.
- [ ] Regenerar `openapi.json` pós-mudança e diffar contra o baseline — confirmar diff vazio.
- [ ] Adicionar guard de CI (ex.: step no workflow de CI do backend, ou pre-commit) que executa grep e falha se `schemas/ai.py`/`schemas/chat.py` existirem ou se houver import de `app.schemas.ai`/`app.schemas.chat` no código.
- [ ] Atualizar o item #62 do bug sweep marcando a sub-parte de schemas mortos como resolvida.

## Dev Notes
- **Arquivos:** `backend/app/schemas/ai.py` (deletar), `backend/app/schemas/chat.py` (deletar), `backend/app/schemas/__init__.py` (remover imports/re-exports), workflow de CI do backend (ex.: `.github/workflows/*.yml` ou config de pre-commit — adicionar grep guard). Confirmar os caminhos reais no repo antes de editar.
- **Abordagem:** Mudança puramente subtrativa (via negativa). Primeiro PROVAR que o código é morto via grep escopado, depois deletar e validar que o boot do app e o OpenAPI permanecem idênticos. O OpenAPI diff vazio é a evidência objetiva de que nenhum contrato vivo dependia desses schemas. O CI guard transforma a limpeza em invariante permanente.
- **Riscos de regressão:** Baixíssimo se a verificação de morte for rigorosa. Blast radius esperado = zero (módulos não consumidos). O único risco real é deletar algo que ainda tem um consumidor escondido — mitigado pelo grep mandatório no AC e pelo OpenAPI diff. Se houver re-export indireto em `__init__` consumido por terceiros (ex.: `from app.schemas import SomeAiModel`), o grep deve pegar; caso pegue um consumidor vivo, PARAR e escalar em vez de deletar. Não tocar em nenhum outro schema do pacote.

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde: teste/smoke que importa o entrypoint do app e valida que o boot ocorre sem `ImportError` referente a `ai`/`chat`.
- [ ] Sem regressão na suíte de segurança.
- [ ] QA Gate: PASS ou CONCERNS.
- [ ] OpenAPI pós-mudança byte-equivalente ao baseline (diff vazio) e CI grep guard ativo e comprovadamente falhando se os módulos/imports ressurgirem.
- [ ] `git status` confirma exatamente 3 arquivos tocados (2 deleções + `__init__.py`) mais a config de CI, sem deltas inesperados.

## QA Results
_(a preencher pelo @qa)_
