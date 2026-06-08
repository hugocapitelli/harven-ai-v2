-- ===========================================================================
-- MIGRATION A (TPP-1) — DATA dedupe + reparent + message sequence backfill
-- ===========================================================================
-- bug_refs: #7 (duplicate chat_sessions -> permanent 500), #40 (counter drift),
--           message-ordering tiebreaker (TPP-3 / TPP-4 read path).
--
-- *** ORDER IS INVIOLABLE: APPLY THIS (A) BEFORE 20260603b_unique_constraints.sql ***
-- Apply MANUALLY in the Supabase SQL Editor. This file is DATA-ONLY save for the
-- additive, idempotent ``chat_messages.sequence`` column (an additive column is
-- safe inside a normal transaction; it is NOT the CONCURRENTLY index of MIG B).
--
-- Why A must precede B: MIGRATION B creates a partial UNIQUE INDEX on
-- (user_id, content_id) WHERE content_id IS NOT NULL. If pre-existing duplicate
-- sessions remain, that index creation FAILS. A collapses every duplicate group
-- to a single "keeper" row and reparents all dependent rows onto it FIRST, with a
-- gate that asserts zero duplicates remain.
--
-- Idempotency: re-running A is a safe no-op — once duplicates are collapsed the
-- keeper CTE finds nothing to reparent/delete, and the column add is IF NOT EXISTS.
-- No new RLS policy is introduced (service_role client bypasses RLS — ADR SEC-CHAT-5).

BEGIN;

-- ---------------------------------------------------------------------------
-- 0. Additive, idempotent message-sequence column (stable ordering tiebreaker).
--    Used by chat_repo.get_session_messages / persist_turn so two turns sharing
--    a microsecond ``created_at`` never reorder in the transcript or export.
-- ---------------------------------------------------------------------------
ALTER TABLE chat_messages
    ADD COLUMN IF NOT EXISTS sequence BIGINT;

-- Backfill ``sequence`` deterministically per session by (created_at, id). Only
-- rows still NULL are touched, so re-runs are a no-op.
WITH ordered AS (
    SELECT
        id,
        row_number() OVER (
            PARTITION BY session_id
            ORDER BY created_at ASC, id ASC
        ) AS rn
    FROM chat_messages
    WHERE sequence IS NULL
)
UPDATE chat_messages m
SET sequence = ordered.rn
FROM ordered
WHERE m.id = ordered.id
  AND m.sequence IS NULL;

-- ---------------------------------------------------------------------------
-- 1. Identify the KEEPER per (user_id, content_id) group with content_id NOT NULL.
--    Keeper rule: most messages first, tiebreak the OLDEST created_at, then id.
-- ---------------------------------------------------------------------------
CREATE TEMPORARY TABLE _tpp1_keepers ON COMMIT DROP AS
WITH counts AS (
    SELECT s.id AS session_id,
           s.user_id,
           s.content_id,
           s.created_at,
           (SELECT count(*) FROM chat_messages cm WHERE cm.session_id = s.id) AS msg_count
    FROM chat_sessions s
    WHERE s.content_id IS NOT NULL
),
ranked AS (
    SELECT session_id,
           user_id,
           content_id,
           row_number() OVER (
               PARTITION BY user_id, content_id
               ORDER BY msg_count DESC, created_at ASC, session_id ASC
           ) AS rn
    FROM counts
)
SELECT r.session_id AS keeper_id, r.user_id, r.content_id
FROM ranked r
WHERE r.rn = 1;

-- Map every LOSER session -> its group keeper.
CREATE TEMPORARY TABLE _tpp1_losers ON COMMIT DROP AS
SELECT s.id AS loser_id, k.keeper_id
FROM chat_sessions s
JOIN _tpp1_keepers k
  ON k.user_id = s.user_id
 AND k.content_id = s.content_id
WHERE s.content_id IS NOT NULL
  AND s.id <> k.keeper_id;

-- ---------------------------------------------------------------------------
-- 2. REPARENT all dependents of the losers onto the keeper (reparent BEFORE delete
--    so no dependent row is ever orphaned / lost). Covers EVERY table holding a
--    FK to chat_sessions.id: chat_messages, session_reviews, moodle_ratings.
--    Guarded with to_regclass so a missing optional table is skipped, not fatal.
-- ---------------------------------------------------------------------------
UPDATE chat_messages cm
SET session_id = l.keeper_id
FROM _tpp1_losers l
WHERE cm.session_id = l.loser_id;

DO $$
BEGIN
    IF to_regclass('public.session_reviews') IS NOT NULL THEN
        EXECUTE '
            UPDATE session_reviews sr
            SET session_id = l.keeper_id
            FROM _tpp1_losers l
            WHERE sr.session_id = l.loser_id';
    END IF;
    IF to_regclass('public.moodle_ratings') IS NOT NULL THEN
        EXECUTE '
            UPDATE moodle_ratings mr
            SET session_id = l.keeper_id
            FROM _tpp1_losers l
            WHERE mr.session_id = l.loser_id';
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 3. DELETE the now-empty loser sessions (dependents already reparented).
-- ---------------------------------------------------------------------------
DELETE FROM chat_sessions s
USING _tpp1_losers l
WHERE s.id = l.loser_id;

-- ---------------------------------------------------------------------------
-- 4. GATE: zero duplicate groups must remain, else MIGRATION B's unique index
--    would fail. Abort the whole migration (transaction) if any survive.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    dup_groups INTEGER;
BEGIN
    SELECT count(*) INTO dup_groups
    FROM (
        SELECT user_id, content_id
        FROM chat_sessions
        WHERE content_id IS NOT NULL
        GROUP BY user_id, content_id
        HAVING count(*) > 1
    ) d;

    IF dup_groups > 0 THEN
        RAISE EXCEPTION
            'TPP-1 MIGRATION A gate failed: % duplicate (user_id, content_id) group(s) remain — do NOT run MIGRATION B', dup_groups;
    END IF;
END $$;

COMMIT;

-- Post-migration verification (run manually, expect 0 rows):
--   SELECT user_id, content_id, count(*)
--   FROM chat_sessions WHERE content_id IS NOT NULL
--   GROUP BY user_id, content_id HAVING count(*) > 1;
--
-- And confirm zero data loss — these counts must be identical before/after:
--   SELECT count(*) FROM chat_messages;
--   SELECT count(*) FROM session_reviews;   -- if table exists
--   SELECT count(*) FROM moodle_ratings;    -- if table exists
