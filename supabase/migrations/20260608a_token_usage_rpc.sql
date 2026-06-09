-- ===========================================================================
-- MIGRATION (TKN-1) — DDL: read index + atomic token-usage increment RPC
-- ===========================================================================
-- bug_refs: #12 (in-memory _user_token_cache token throttle -> volatile, not
--           shared across workers, trivially reset on restart).
--
-- Adds the DATA LAYER for a persistent, concurrency-safe daily token budget:
--   (1) a read index on token_usage (user_id, usage_date) for get_today_usage;
--   (2) increment_token_usage(...) — an ATOMIC upsert (INSERT ... ON CONFLICT
--       DO UPDATE) that guarantees exactly 1 row per (user_id, usage_date) even
--       under concurrent writes and RETURNS the new running total so TKN-2
--       (TokenUsageRepository.add_usage) avoids a second round-trip.
--
-- The token_usage table itself ALREADY EXISTS (supabase/migrations/
-- 20260414_init.sql:299-306) with id TEXT PRIMARY KEY DEFAULT
-- uuid_generate_v4()::text and UNIQUE(user_id, usage_date). This migration is
-- PURELY ADDITIVE — it does NOT alter the table definition.
--
-- Apply MANUALLY in the Supabase SQL Editor (this repo has no CLI migration
-- runner). IDEMPOTENT (CREATE INDEX IF NOT EXISTS / CREATE OR REPLACE FUNCTION):
-- safe to apply and re-apply with no error. Additive, introduces NO new RLS
-- policy (the backend uses a service_role client that bypasses RLS, mirroring
-- ADR SEC-CHAT-5 — SECURITY DEFINER lets the RPC run with the owner's rights
-- when invoked via RPC by the service-role client).

-- ---------------------------------------------------------------------------
-- 1. Read index on (user_id, usage_date).
--    UNIQUE(user_id, usage_date) already enforces uniqueness; this explicit
--    index covers the daily read path (get_today_usage / TKN-2). IF NOT EXISTS
--    makes it inert should the unique constraint's implicit index already match.
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_token_usage_user_date
    ON token_usage (user_id, usage_date);

-- ---------------------------------------------------------------------------
-- 2. RPC increment_token_usage — atomic daily counter (resolves #12 data layer).
--    INSERT ... ON CONFLICT (user_id, usage_date) DO UPDATE adds the delta in a
--    single statement: N concurrent calls for the same (user_id, usage_date)
--    accumulate EXACTLY the sum (no read-modify-write, no lost updates), leaving
--    exactly 1 row. Distinct usage_date values for the same user yield distinct
--    rows (one per day). id is omitted from the INSERT so it falls back to the
--    table DEFAULT uuid_generate_v4()::text. RETURNING tokens_used hands back the
--    new running total for TKN-2 (add_usage) without a second query.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION increment_token_usage(
    p_user_id TEXT,
    p_usage_date DATE,
    p_tokens INTEGER
)
RETURNS INTEGER
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    INSERT INTO token_usage (user_id, usage_date, tokens_used)
    VALUES (p_user_id, p_usage_date, p_tokens)
    ON CONFLICT (user_id, usage_date)
    DO UPDATE SET tokens_used = token_usage.tokens_used + EXCLUDED.tokens_used
    RETURNING tokens_used;
$$;

-- Post-migration verification (run MANUALLY in the Supabase SQL Editor):
--   -- index present:
--   SELECT indexname FROM pg_indexes
--   WHERE tablename = 'token_usage' AND indexname = 'idx_token_usage_user_date';
--   -- RPC present:
--   SELECT proname FROM pg_proc WHERE proname = 'increment_token_usage';
--   -- atomic accumulation -> exactly 1 row, tokens_used == sum:
--   SELECT increment_token_usage('<user_id>', CURRENT_DATE, 100);  -- -> 100
--   SELECT increment_token_usage('<user_id>', CURRENT_DATE, 50);   -- -> 150
--   SELECT count(*), tokens_used FROM token_usage
--   WHERE user_id = '<user_id>' AND usage_date = CURRENT_DATE GROUP BY tokens_used;
--   -- distinct days -> 2 rows:
--   SELECT increment_token_usage('<user_id>', CURRENT_DATE - 1, 10);
--   SELECT usage_date, tokens_used FROM token_usage WHERE user_id = '<user_id>';
--   -- idempotency: re-running this whole file produces no error.
