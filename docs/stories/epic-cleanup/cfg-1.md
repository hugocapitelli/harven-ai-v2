---
id: CFG-1
epic: EPIC-CLEANUP
phase: 5
status: Draft
severity: MEDIUM
terminal: Backend & Infra
complexity: low
depends_on: []
bug_refs: [48]
---
# CFG-1: Sentry init env-driven e guarded

## Story
Como engenheiro de Backend & Infra, quero que a inicialização do Sentry seja controlada por variável de ambiente e protegida contra DSN vazio/hardcoded, para evitar vazamento de credencial no repositório, garantir observabilidade correta entre ambientes (dev/staging/prod) e não inicializar telemetria sem necessidade.

## Contexto (do bug sweep)
Item #48 do BUG-SWEEP-2026-06-03.md: o backend inicializa o Sentry com um DSN hardcoded no código-fonte, sem guarda condicional por variável de ambiente. Isso gera dois problemas concretos:

1. **Vazamento de credencial:** o DSN do Sentry está versionado em texto plano no repositório. Mesmo sendo um "ingest key" público, ele expõe o projeto Sentry a poluição/abuse de eventos por terceiros e deve ser tratado como segredo rotacionável.
2. **Init incondicional:** o `sentry_sdk.init()` roda sempre, mesmo em ambientes de desenvolvimento/local ou em CI, onde não há (nem deveria haver) DSN configurado. Sem guarda por `SENTRY_DSN` não-vazio, o init pode disparar com DSN vazio/inválido ou enviar eventos indevidos.

Impacto: MEDIUM — não quebra runtime de usuário final, mas é risco de segurança (segredo exposto) + ruído de telemetria entre ambientes. Probabilidade de regressão: baixa (mudança isolada no bootstrap).

## Acceptance Criteria
- [ ] `sentry_sdk.init()` é executado **somente** quando `SENTRY_DSN` está presente **e** não-vazio (após `.strip()`); com DSN ausente/vazio, o init é pulado e o app sobe normalmente sem telemetria.
- [ ] Nenhum DSN do Sentry permanece hardcoded no código-fonte; o valor passa a vir exclusivamente de `os.getenv("SENTRY_DSN")` (ou equivalente do settings).
- [ ] `backend/.env.example` documenta a variável com a linha `SENTRY_DSN=` (vazia por padrão) e um comentário curto explicando que init só ocorre quando preenchida.
- [ ] O `sentry_sdk.init()` ocorre **acima/antes** da criação/instanciação do app (FastAPI/ASGI), de forma que a instrumentação capture o ciclo de vida da aplicação desde o boot.
- [ ] Existe uma **nota operacional** (em `backend/.env.example` e/ou no roadmap/ops docs) instruindo a **rotacionar o DSN exposto** no painel do Sentry, dado que o valor antigo esteve versionado.
- [ ] Quando `SENTRY_DSN` está vazio em ambiente local/CI, não há nenhuma chamada de rede para o Sentry no boot (verificável por ausência de eventos de erro de init).

## Tasks / Subtasks
- [ ] Localizar a chamada atual de `sentry_sdk.init(...)` no bootstrap do backend (provável `backend/app/main.py` ou módulo de configuração/observabilidade do backend) e identificar o DSN hardcoded.
- [ ] Substituir o DSN literal por leitura de ambiente: `dsn = os.getenv("SENTRY_DSN", "").strip()`.
- [ ] Envolver o init em guarda condicional: `if dsn: sentry_sdk.init(dsn=dsn, ...)`; caso contrário, pular silenciosamente (opcionalmente log de nível INFO informando que o Sentry está desabilitado).
- [ ] Garantir que o bloco de init esteja posicionado **antes** da instanciação do app (`app = FastAPI(...)`) no fluxo de import/boot.
- [ ] Editar `backend/.env.example` adicionando `SENTRY_DSN=` com comentário (ex.: `# Sentry DSN — deixe vazio para desabilitar a telemetria; init só ocorre se preenchido`).
- [ ] Adicionar nota de ops (em `backend/.env.example` como comentário e referenciar no roadmap) orientando a **rotacionar o DSN antigo** no Sentry, pois esteve commitado.
- [ ] Confirmar que `SENTRY_DSN` não está em nenhum arquivo versionado com valor real (grep no repo por trecho do DSN antigo / por `sentry_sdk.init`).

## Dev Notes
- **Arquivos:**
  - `backend/app/main.py` (ou módulo de bootstrap/observabilidade onde `sentry_sdk.init` é chamado — confirmar via grep `sentry_sdk.init`).
  - `backend/.env.example` (documentação da variável + nota de ops).
  - Eventual `backend/app/core/config.py`/settings, se o projeto centraliza env vars em Pydantic Settings — nesse caso expor `SENTRY_DSN: str | None` ali.
- **Abordagem:** Mover o DSN de literal hardcoded para `os.getenv("SENTRY_DSN", "").strip()`, guardar o init com `if dsn:`, e manter o init no topo do módulo de entrada (antes do `app = FastAPI(...)`). Documentar a env em `.env.example` com valor vazio. A mudança é aditiva/defensiva — sem DSN o comportamento passa a ser "não inicializa", que é o desejado em dev/CI.
- **Riscos de regressão:** Blast radius baixo e localizado no bootstrap do backend. Quem depende: o módulo de entrada do app e qualquer middleware/integração do Sentry registrada após o init. Em produção, é obrigatório que `SENTRY_DSN` esteja setado no ambiente do EasyPanel/VPS — caso contrário a telemetria de prod deixa de funcionar (validar que o deploy injeta a env). Verificar também se há captura manual de exceções dependendo de `sentry_sdk` estar inicializado; com guarda, chamadas de capture viram no-op quando DSN ausente (comportamento esperado do SDK).

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde
- [ ] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [ ] Boot do backend sem `SENTRY_DSN` (dev/CI) sobe sem inicializar Sentry e sem erros; com `SENTRY_DSN` setado, o init ocorre acima do app; nenhum DSN hardcoded remanescente no repo; `backend/.env.example` documenta `SENTRY_DSN=` e contém a nota de rotação do DSN exposto.

## QA Results
_(a preencher pelo @qa)_
