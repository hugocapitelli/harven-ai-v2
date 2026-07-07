-- Migration (POD-6) — `contents.audio_type` records which style the current
-- `contents.audio_url` was generated as (podcast / summary / explanation).
--
-- Root cause (bug sweep item 772): the reader (`ChapterReader.tsx:219-224`)
-- hardcodes every persisted `audio_url` into the `summary` slot regardless of
-- the style actually generated, because `contents` never recorded WHICH style
-- produced that URL. A generated podcast reloads into the wrong slot, and a
-- second style generation overwrites the first (single `audio_url` column).
--
-- This migration only adds the column that lets the backend/reader disambiguate
-- by style; it does not by itself change persistence/read behaviour.
--
-- Idempotent + additive: `ADD COLUMN IF NOT EXISTS`, nullable, NO destructive
-- default for existing rows. Legacy rows keep `audio_type IS NULL` and are
-- expected to be treated as `summary` by the fallback documented in POD-6's
-- Dev Notes (application-layer concern, not this migration's).

ALTER TABLE contents
    ADD COLUMN IF NOT EXISTS audio_type TEXT
        CHECK (audio_type IN ('podcast', 'summary', 'explanation'));
