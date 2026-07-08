-- BUG-1: allow admins to block/unblock users via PUT /users/{id} {status:...}
-- Adds a status column to users with a defensive CHECK constraint.

ALTER TABLE users ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'users_status_check'
    ) THEN
        ALTER TABLE users
            ADD CONSTRAINT users_status_check CHECK (status IN ('active', 'blocked'));
    END IF;
END $$;
