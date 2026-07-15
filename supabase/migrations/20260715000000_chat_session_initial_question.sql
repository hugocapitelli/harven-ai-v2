-- ===========================================================================
-- MIGRATION (SOC-1) — DDL: chat_sessions.initial_question_text
-- ===========================================================================
-- goal_ref: docs/goals/GOAL-pergunta-unica.md
-- story:    docs/stories/epic-socratic/SOC-1.story.md
--
-- Persists which "Pergunta para Reflexão" a student committed to when the
-- socratic session was created. The choice is written ONCE on creation and is
-- the durable source of truth for the frontend lock: the other questions stay
-- disabled while an ``active`` session exists, and the chosen one offers
-- "Retomar Sessão" instead of a fresh dialogue.
--
-- Apply MANUALLY in the Supabase SQL Editor. Idempotent (IF NOT EXISTS),
-- additive, nullable (legacy rows keep NULL until backfilled on first resume
-- that carries a question — first-write-wins, app layer), and introduces NO new
-- RLS policy (the backend uses a service_role client that bypasses RLS —
-- ADR SEC-CHAT-5).
--
-- ORDER: this migration MUST be applied BEFORE the routes_ai.py code that reads
-- and writes the column ships (repo convention: schema before the code that
-- consumes it).
-- ---------------------------------------------------------------------------
ALTER TABLE chat_sessions
    ADD COLUMN IF NOT EXISTS initial_question_text TEXT;

-- Post-migration verification (run manually):
--   SELECT column_name FROM information_schema.columns
--   WHERE table_name = 'chat_sessions' AND column_name = 'initial_question_text';
