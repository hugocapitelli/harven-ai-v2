# Harven AI V2 — Pendências

## Backend
- [x] Import errors corrigidos — `from main import app` passa limpo
- [x] Todos os models/ corretos (settings.py, não admin.py)

## Frontend
- [x] TypeScript errors corrigidos — `npx tsc --noEmit` zero erros
- [x] Build passa limpo — `npm run build` OK (658ms)

## Infra
- [x] Dockerfile.frontend: multi-stage build limpo, usa nginx.conf externo
- [x] nginx.conf: SPA routing, security headers, caching correto
- [x] docker-compose.yml: OK (backend:8000, frontend:3000→80)
- [x] Dockerfile backend: OK (Python 3.11, uvicorn, healthcheck)

## Deploy
- [ ] Configurar Supabase project (Hugo precisa criar ou confirmar existente)
- [ ] Configurar .env no EasyPanel com credenciais reais
- [ ] Deploy no EasyPanel (docker compose up)
- [ ] Verificar domínios: harven.eximiaventures.com.br + api.harven.eximiaventures.com.br
- [ ] Smoke test: login + chat Socrático + admin panel
