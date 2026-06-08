-- Migration G (SEC-ROT-1) — Durable, rotatable JWT signing secret in the DB.
--
-- Root cause (bug #3 / #22): the JWT signing secret lived only in an env var
-- with a public default ("change-me-in-production"), and admin "force logout"
-- tried to rotate it by rewriting .env — silently ignored because docker-compose
-- injects env vars that outrank the .env file in pydantic-settings precedence.
--
-- This migration gives the secret a durable home (system_settings) so it can be
-- read by a provider (SEC-ROT-1) and rotated in-place (SEC-ROT-3) without a
-- restart. Both columns are NULLABLE and carry NO plaintext default: the secret
-- only ever materialises at runtime via seed-on-NULL from the bootstrap env var.
-- Storing a literal default here would re-introduce the very public-secret
-- vulnerability we are closing.

ALTER TABLE system_settings
    ADD COLUMN IF NOT EXISTS jwt_secret TEXT,
    ADD COLUMN IF NOT EXISTS jwt_secret_rotated_at TIMESTAMPTZ;
