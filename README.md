# Harven AI V2 — Plataforma de Detecção de IA

Plataforma para verificar autenticidade de textos acadêmicos. Analisa documentos e identifica conteúdo gerado por IA com múltiplos métodos de detecção.

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Backend | Python · FastAPI |
| Frontend | React · Vite · TypeScript |
| Database | Supabase (PostgreSQL + Auth + Storage) |
| Deploy | Docker Compose · EasyPanel · Traefik |

## Setup Local

```bash
# 1. Clone o repositório
git clone git@github.com:eximIA-Ventures/harven-ai-v2.git
cd harven-ai-v2

# 2. Configure variáveis de ambiente
cp .env.example .env
# Preencha as variáveis no .env

# 3. Suba os containers
docker compose up -d

# 4. Acesse
# Frontend: http://localhost:3000
# Backend:  http://localhost:8000
# Health:   http://localhost:8000/health
```

## Deploy — EasyPanel

**VPS:** `76.13.82.199`

**Domínios:**
- Frontend: `harven.eximiaventures.com.br`
- API: `api.harven.eximiaventures.com.br`

**Setup:**
1. Criar app no EasyPanel com source Git
2. Configurar variáveis de ambiente (copiar de `.env.example`)
3. Traefik reverse proxy gerencia SSL automático via Let's Encrypt
4. Health check configurado em `/health` (backend)

**Atualização:**
```bash
git push origin main
# EasyPanel detecta push e rebuilda automaticamente
```
