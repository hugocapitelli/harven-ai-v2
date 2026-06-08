-- ===========================================================================
-- MIGRATION B (TPP-1) — DDL: partial UNIQUE index + atomic-state RPCs
-- ===========================================================================
-- bug_refs: #7 (duplicate chat_sessions -> permanent 500 via maybe_single),
--           #40 (total_messages read-modify-write -> lost updates / drift).
--
-- *** ORDER IS INVIOLABLE: APPLY 20260603a_dedupe_backfill.sql (A) FIRST ***
-- Migration A collapses every duplicate (user_id, content_id) group to a single
-- keeper and asserts zero duplicates remain. This file (B) then enforces that
-- invariant at the DB level and ships the two SECURITY DEFINER RPCs that TPP-2
-- (upsert) and TPP-3 (atomic increment) consume.
--
-- Apply MANUALLY in the Supabase SQL Editor. Idempotent (IF NOT EXISTS /
-- CREATE OR REPLACE), additive, and introduces NO new RLS policy (the backend
-- uses a service_role client that bypasses RLS — ADR SEC-CHAT-5).
--
-- IMPORTANT — CREATE INDEX CONCURRENTLY cannot run inside a transaction block.
-- Run the CREATE UNIQUE INDEX CONCURRENTLY statement on its own (do NOT wrap it
-- in BEGIN/COMMIT). The RPCs below CAN be run together.

-- ---------------------------------------------------------------------------
-- 1. Partial UNIQUE index on (user_id, content_id) WHERE content_id IS NOT NULL.
--    Partial so free-chat sessions (content_id NULL) may legitimately coexist.
--    Enforces the invariant even for writers outside the upsert RPC.
--    NOTE: a session whose status is terminal ('completed') still occupies the
--    (user_id, content_id) slot; the create-or-get route (TPP-2) handles the
--    "new attempt after completion" case at the application layer (a completed
--    row is left untouched and resumed/returned, never duplicated).
-- ---------------------------------------------------------------------------
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS ux_chat_sessions_user_content
    ON chat_sessions (user_id, content_id)
    WHERE content_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 2. RPC upsert_chat_session — race-free create-or-get (resolves #7).
--    Two concurrent calls for the same (user_id, content_id) return the SAME
--    row (never two, never a 500). p_user_id is a SERVER-SIDE parameter derived
--    from the authenticated identity by the caller (routes_ai.py passes the JWT
--    subject, NEVER body.user_id). ON CONFLICT DO UPDATE (no-op touch of
--    updated_at) guarantees RETURNING yields the surviving row on both the
--    insert and the conflict path.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION upsert_chat_session(
    p_user_id TEXT,
    p_content_id TEXT
)
RETURNS chat_sessions
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row chat_sessions;
BEGIN
    INSERT INTO chat_sessions (user_id, content_id, status, total_messages)
    VALUES (p_user_id, p_content_id, 'active', 0)
    ON CONFLICT (user_id, content_id) WHERE content_id IS NOT NULL
    DO UPDATE SET updated_at = now()
    RETURNING * INTO v_row;

    RETURN v_row;
END;
$$;

-- ---------------------------------------------------------------------------
-- 3. RPC increment_chat_session_messages — atomic counter (resolves #40).
--    Single UPDATE ... SET total_messages = total_messages + 1. N concurrent
--    calls increment EXACTLY N times (no read-modify-write, no lost updates).
--    This is the ONLY writer of total_messages (chat_repo.persist_turn, TPP-3).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION increment_chat_session_messages(
    p_session_id TEXT
)
RETURNS INTEGER
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    UPDATE chat_sessions
    SET total_messages = total_messages + 1,
        updated_at = now()
    WHERE id = p_session_id
    RETURNING total_messages;
$$;

-- Post-migration verification (run manually):
--   -- unique index present:
--   SELECT indexname FROM pg_indexes
--   WHERE tablename = 'chat_sessions' AND indexname = 'ux_chat_sessions_user_content';
--   -- RPCs present:
--   SELECT proname FROM pg_proc
--   WHERE proname IN ('upsert_chat_session', 'increment_chat_session_messages');
--   -- concurrent inserts of the same pair -> exactly 1 row, no error:
--   SELECT upsert_chat_session('some-user', 'some-content');  -- twice -> same id
--   -- N increments -> +N exactly:
--   SELECT increment_chat_session_messages('<session_id>');
