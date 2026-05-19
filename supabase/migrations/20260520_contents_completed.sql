-- Add completed flag to contents table
ALTER TABLE contents ADD COLUMN IF NOT EXISTS completed BOOLEAN DEFAULT false;
ALTER TABLE contents ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
