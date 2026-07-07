-- Migration (TTSJOB-1) — Durable `tts_jobs` table + supporting indexes.
--
-- Root cause (bug sweep #34, #58, #59): the TTS/podcast job lifecycle lives
-- ONLY in an in-memory dict in the backend process (`_tts_jobs` in
-- `routes_ai.py`). A process restart/deploy silently drops every
-- `processing`/`pending` job, there is no durable `user_id` to enforce
-- ownership on read, and terminal jobs (`done`/`error`) are never swept —
-- no TTL, no garbage collection.
--
-- This migration creates the durable foundation only (schema + indexes).
-- Wiring the worker/endpoints to read/write through this table instead of
-- the in-memory dict is a follow-up story; this migration does not change
-- any existing runtime behaviour.
--
-- Idempotent: safe to run twice (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX
-- IF NOT EXISTS`). Aditivo: creates a brand new table, touches nothing else.
-- `id` is TEXT (matches every other primary key in this schema, e.g.
-- `contents.id`, `users.id` — see `supabase/migrations/20260414_init.sql`),
-- populated by the application (`job_id = uuid4().hex`), not `gen_random_uuid()`,
-- since jobs are created by the async endpoint before any DB round-trip.
--
-- No RLS: enforcement of `(content_id, user_id)` ownership is done in the
-- application layer via `TtsJobRepository`, matching this project's existing
-- "no RLS, app-layer enforcement" convention (see `tts_jobs` sibling tables).

CREATE TABLE IF NOT EXISTS tts_jobs (
    id TEXT PRIMARY KEY,
    content_id TEXT REFERENCES contents(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    audio_type TEXT NOT NULL DEFAULT 'summary'
        CHECK (audio_type IN ('podcast', 'summary', 'explanation')),
    status TEXT NOT NULL DEFAULT 'processing'
        CHECK (status IN ('processing', 'done', 'error')),
    audio_url VARCHAR(500),
    error TEXT,
    duration_estimate VARCHAR(50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Read-by-dono: `get_for_content(content_id, user_id)` always filters on both
-- columns together (IDOR guard — never `content_id` alone).
CREATE INDEX IF NOT EXISTS idx_tts_jobs_content_user
    ON tts_jobs(content_id, user_id);

-- Sweep/status queries (`sweep_expired`, dashboards) filter by status first.
CREATE INDEX IF NOT EXISTS idx_tts_jobs_status
    ON tts_jobs(status);

-- Per-user status queries (`count_active_for_user`).
CREATE INDEX IF NOT EXISTS idx_tts_jobs_user_status
    ON tts_jobs(user_id, status);

-- TTL sweep ordering.
CREATE INDEX IF NOT EXISTS idx_tts_jobs_updated_at
    ON tts_jobs(updated_at);
