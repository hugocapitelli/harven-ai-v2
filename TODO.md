# Harven AI V2 — Pendências

## Backend (precisa corrigir para startar)
- [ ] `repositories/admin_repo.py` linha 3: trocar `from models.admin import` → `from models.settings import`
- [ ] Grep por `models.admin` em todos os .py e corrigir para `models.settings`
- [ ] Testar: `JWT_SECRET_KEY=test OPENAI_API_KEY=test python3 -c "from main import app"`
- [ ] Corrigir TODOS os import errors até startar limpo

## Frontend (precisa corrigir para buildar)
- [ ] TypeScript errors em views/courses/ (ContentRevision, CourseDetails, CourseEdit, CourseList)
- [ ] Errors: unknown→ReactNode, wrong arg count em API calls
- [ ] Testar: `npm run build` deve passar limpo

## Infra
- [ ] Docker Compose: ports issue (Generic encontrou)
- [ ] Frontend Dockerfile: melhorar envsubst pattern

## Deploy
- [ ] Criar novo Supabase project (Hugo precisa fazer)
- [ ] Criar repo GitHub
- [ ] Commit + push
- [ ] Configurar EasyPanel
