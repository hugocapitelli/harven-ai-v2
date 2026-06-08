---
id: CFG-4
epic: EPIC-CLEANUP
phase: 5
status: Draft
severity: MEDIUM
terminal: Backend & Infra
complexity: low
depends_on: []
bug_refs: [62]
---
# CFG-4: Boot-guard de env obrigatório em produção

## Story
Como operador de plataforma responsável pelo deploy no EasyPanel, quero que a aplicação se recuse a subir (fail-closed) quando variáveis de ambiente críticas (`SUPABASE_URL`/`SUPABASE_KEY`) estiverem vazias em produção, para que uma configuração incompleta vire um erro de boot explícito e auditável, em vez de uma falha silenciosa em runtime que atinge usuários reais.

## Contexto (do bug sweep)
O bug item **#62** documenta que a aplicação inicializa o cliente Supabase mesmo quando `SUPABASE_URL`/`SUPABASE_KEY` estão ausentes ou vazios. Hoje não há validação de boot: o `lifespan` em `backend/app/main.py` sobe normalmente, e a ausência de credenciais só se manifesta como erro tardio na primeira requisição que tenta acessar o banco (cliente Supabase apontando para URL vazia → exceções de runtime, 500s, comportamento indefinido). Isso transforma um erro de configuração — que deveria ser fatal e imediato — em uma degradação difusa em produção. O roadmap classifica isso como **boot-guard fail-closed (#3/CFG-4)**: a aplicação deve recusar o boot se o env estiver incompleto. O check de **força/segredo do JWT** NÃO é escopo desta story — está explicitamente delegado a **SEC-ATO-2** para evitar duplicação de validação no lifespan.

## Acceptance Criteria
- [ ] Existe a função `_validate_required_env()` em `backend/app/main.py` que, quando o ambiente é produção, faz `raise` (ex.: `RuntimeError`/`SystemExit`) com mensagem clara listando qual(is) variável(is) está(ão) vazia(s) caso `SUPABASE_URL` ou `SUPABASE_KEY` estejam ausentes ou string vazia.
- [ ] Em ambiente de desenvolvimento (não-produção), `_validate_required_env()` é **no-op** — não levanta exceção mesmo com env incompleto (permite desenvolvimento local sem credenciais reais).
- [ ] A detecção de "produção" usa o mesmo sinal de ambiente já adotado pelo backend (ex.: `ENVIRONMENT`/`APP_ENV` em `backend/app/config.py`/settings) — sem introduzir uma nova convenção divergente.
- [ ] `_validate_required_env()` é chamado no `lifespan` (startup) de `backend/app/main.py`, ANTES da inicialização do cliente Supabase, de forma que um env inválido em produção impeça o boot.
- [ ] Em produção com `SUPABASE_URL` e `SUPABASE_KEY` preenchidos, o boot prossegue normalmente (sem falso-positivo).
- [ ] A validação **não** inclui checagem de força/segredo de JWT — esse desfecho é responsabilidade de SEC-ATO-2; CFG-4 valida apenas as variáveis Supabase obrigatórias.

## Tasks / Subtasks
- [ ] Em `backend/app/main.py`, implementar `_validate_required_env()` que lê o ambiente via settings (`backend/app/config.py`) e, se produção, valida presença não-vazia de `SUPABASE_URL` e `SUPABASE_KEY`; agregar todas as faltantes numa única mensagem antes do `raise`.
- [ ] Garantir o no-op em dev: retornar cedo (`return`) quando o ambiente não for produção.
- [ ] Inserir a chamada de `_validate_required_env()` no início do `lifespan` em `backend/app/main.py`, ANTES de qualquer criação do cliente Supabase. Coordenar com SEC-ATO (JWT assert) e SEC-ROT (seed) para a ordem dos três inserts no lifespan (ver roadmap §4 — `main.py` lifespan single-owner por região).
- [ ] Confirmar via leitura de `backend/app/config.py` qual é o nome canônico das variáveis Supabase e do flag de ambiente, evitando hardcode de nomes divergentes.
- [ ] Adicionar teste de regressão (falha-antes / passa-depois) que: (a) em produção com env vazio, o startup falha com exceção; (b) em produção com env preenchido, o startup passa; (c) em dev com env vazio, o startup passa (no-op).

## Dev Notes
- **Arquivos:** `backend/app/main.py` (lifespan + `_validate_required_env`), `backend/app/config.py`/settings (fonte do flag de ambiente e dos nomes das variáveis Supabase).
- **Abordagem:** Fail-closed em produção, fail-open em dev. Função pura de validação, sem efeitos colaterais além do `raise`. Detecção de ambiente reutiliza o sinal já existente no backend. Escopo cirúrgico: apenas `SUPABASE_URL`/`SUPABASE_KEY`; força de JWT fica para SEC-ATO-2.
- **Riscos de regressão:** Blast radius concentrado no `lifespan` de `main.py` — região compartilhada com SEC-ATO (JWT assert) e SEC-ROT (seed). Single-owner por região exige coordenar os 3 inserts no lifespan (roadmap §4) para evitar conflito de merge. Risco operacional: validar que o env do EasyPanel está corretamente preenchido ANTES do merge — caso contrário o boot-guard fail-closed vira outage em produção (roadmap §risco "Boot-guard fail-closed #3/CFG-4"). Sem dependências de código upstream (`depends_on: []`).

## Definition of Done
- [ ] Teste de regressão (falha-antes / passa-depois) verde
- [ ] Sem regressão na suíte de segurança
- [ ] QA Gate: PASS ou CONCERNS
- [ ] Confirmado em revisão que CFG-4 NÃO valida força de JWT (delegado a SEC-ATO-2) e que o no-op em dev preserva o fluxo de desenvolvimento local sem credenciais; coordenação dos 3 inserts no lifespan (CFG-4 + SEC-ATO + SEC-ROT) registrada/validada.

## QA Results
_(a preencher pelo @qa)_
