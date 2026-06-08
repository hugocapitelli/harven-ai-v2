---
id: AI-HARD-0
epic: EPIC-AI
phase: 4
status: Draft
severity: HIGH
terminal: Backend & Infra
complexity: low
depends_on: []
bug_refs: [29, 30, 32]
---
# AI-HARD-0: Scaffold de teste + modelos Pydantic de contrato (AIDetectionResult, TesterVerdict)

## Story
Como engenheiro de backend do tutor Harven.AI, quero um scaffold de teste e modelos Pydantic que validem e coajam o contrato de saída do detector de IA e do Tester (quality gate), para que defeitos de contrato dos itens #29, #30 e #32 sejam corrigidos sobre uma base testável, em vez de confiar verbatim em JSON não validado vindo do LLM.

## Contexto (do bug sweep)
Esta story é a fundação (scaffold + contratos) que habilita AI-HARD-1..5. Hoje o `ai_service.py` consome a saída do modelo sem validação de contrato, gerando três classes de defeito documentadas no bug sweep:

- **#30 — `detect_ai_content` confia em saída não validada** (`backend/services/ai_service.py:485-498`): `probability`/`confidence`/`verdict` são lidos verbatim (`parsed.get(...)`, l.485-488) e usados em `probability > 0.70` (l.497) e `round(probability, 2)` (l.504) FORA do try/except. Consequências: (a) `'0.8' > 0.70` ou `None > 0.70` → TypeError não capturado → HTTP 500; (b) numérico fora de range (ex.: `1.5`) não clampado → probability nonsense + flag espúria contra o aluno; (c) `verdict` não restrito ao enum (`likely_human|uncertain|likely_ai`, ver l.88).
- **#29 — `probability` ausente vira fallback benigno** (`backend/services/ai_service.py:144-152, 485-486`): `parsed.get("probability", 0.3)` faz JSON válido sem a chave produzir veredito quase-limpo silencioso, em vez de cair na heurística.
- **#32 — Tester fail-open fabrica APPROVED** (`backend/services/ai_service.py:615-633`): `except (json.JSONDecodeError, Exception)` engole tudo e retorna `{verdict: "APPROVED", score: 0.80}` (l.633). Qualquer falha de parse/transporte vira carimbo APPROVED. O enum do Tester é `APPROVED|NEEDS_REVISION|REJECTED` (ver l.119).

Esta story NÃO reescreve os call-sites — ela cria os modelos de contrato (`AIDetectionResult`, `TesterVerdict`) com coerção/clamp/enum + o helper `_parse_model_json` que retorna `None` (não levanta) em JSON inválido, e o scaffold de testes que prova o comportamento esperado. As stories AI-HARD-1/2 consomem esses modelos para fechar os defeitos.

## Acceptance Criteria
- [ ] `AIDetectionResult` (Pydantic) coage `probability` string numérica → float: `'0.8'` → `0.8`.
- [ ] `AIDetectionResult` clampa `probability` ao range `[0.0, 1.0]`: `1.5` → `1.0` e valor negativo → `0.0`.
- [ ] `AIDetectionResult` valida `verdict` contra o enum `likely_human|uncertain|likely_ai` e `confidence` contra `low|medium|high`; valor fora do enum → `ValidationError`.
- [ ] `TesterVerdict` (Pydantic) valida `verdict` contra o enum `APPROVED|NEEDS_REVISION|REJECTED`; valor fora do enum → `ValidationError`; `score` clampado a `[0.0, 1.0]`.
- [ ] Helper `_parse_model_json(raw, model_cls)` retorna `None` (NÃO levanta) quando o JSON é inválido/malformado; retorna a instância validada quando o JSON é bom; propaga `None` quando o JSON é válido mas falha a validação do modelo (decisão documentada no Dev Notes).
- [ ] Scaffold de teste (`pytest`) existe e roda isolado do LLM real (sem chamadas de rede), cobrindo cada AC acima como caso de regressão (falha-antes / passa-depois).

## Tasks / Subtasks
- [ ] Criar módulo de contratos `backend/services/ai_contracts.py` (ou seção equivalente em `ai_service.py`, decidir no Dev) com:
  - [ ] `class VerdictEnum(str, Enum)` = `likely_human|uncertain|likely_ai` e `class ConfidenceEnum(str, Enum)` = `low|medium|high` (espelhando `ai_service.py:88`).
  - [ ] `class TesterVerdictEnum(str, Enum)` = `APPROVED|NEEDS_REVISION|REJECTED` (espelhando `ai_service.py:119`).
  - [ ] `class AIDetectionResult(BaseModel)` com `probability: float` (validador de coerção str→float + clamp `[0,1]`), `verdict: VerdictEnum`, `confidence: ConfidenceEnum`.
  - [ ] `class TesterVerdict(BaseModel)` com `verdict: TesterVerdictEnum`, `score: float` (clamp `[0,1]`), `criteria` opcional.
  - [ ] Helper `_parse_model_json(raw: str, model_cls) -> Optional[BaseModel]` envolvendo `json.loads` + `model_cls(**data)`; captura `json.JSONDecodeError` e `ValidationError` retornando `None`.
- [ ] Criar scaffold de testes `backend/tests/test_ai_contracts.py` com fixtures de payloads (válido, coerção, clamp, enum inválido, JSON malformado) e asserts por AC.
- [ ] Garantir `pytest` configurado para rodar o arquivo (verificar `backend/pytest.ini`/`conftest.py`; criar `conftest.py` mínimo se ausente, sem tocar config de produção).
- [ ] NÃO alterar os call-sites `detect_ai_content` (l.485-498) nem `validate_response` (l.615-633) nesta story — apenas referenciá-los nos comentários como consumidores futuros (AI-HARD-1/2).

## Dev Notes
- **Arquivos:**
  - Novo: `backend/services/ai_contracts.py` (modelos + `_parse_model_json`).
  - Novo: `backend/tests/test_ai_contracts.py` (scaffold de regressão).
  - Novo (se ausente): `backend/tests/conftest.py` / `backend/conftest.py`.
  - Referência (NÃO editar nesta story): `backend/services/ai_service.py:88` (enum detector), `:119` (enum tester), `:485-498` (consumidor #30), `:615-633` (consumidor #32).
- **Abordagem:** Pydantic v2 — usar `field_validator(..., mode="before")` para coerção str→float em `probability`/`score`, e validador pós para clamp em `[0,1]`. Enums como `str, Enum` para serializar como string e rejeitar valores fora do conjunto via `ValidationError`. `_parse_model_json` é o único ponto que decide "JSON ruim → None"; o caller (AI-HARD-1/2) decide o fallback (heurística para detector; `NEEDS_REVISION` para tester). Testes 100% offline (sem `_call_openai`, sem rede).
- **Riscos de regressão:** Baixo. Story é aditiva — cria módulo e testes novos, sem modificar fluxo de produção. Blast radius nesta story = nulo em runtime. Os consumidores futuros (`detect_ai_content`, `validate_response`, rota em `backend/routes_ai.py`) só são tocados em AI-HARD-1/2/4/5; o contrato aqui é o ponto de acoplamento que essas stories importarão, então mudanças de assinatura nos modelos devem ser estáveis (nomes de campo e enums fixados conforme `ai_service.py`).

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde — cada AC tem caso correspondente em `test_ai_contracts.py`.
- [ ] Sem regressão na suíte de segurança / suíte existente do backend (`pytest backend/` permanece verde).
- [ ] QA Gate: PASS ou CONCERNS.
- [ ] Modelos `AIDetectionResult` e `TesterVerdict` + `_parse_model_json` exportados e importáveis pelas stories AI-HARD-1..5 (assinatura estável documentada no módulo).

## QA Results
_(a preencher pelo @qa)_
