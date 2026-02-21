-- Migration: Add pitch_templates table
-- Apply to Supabase (PostgreSQL) production database

CREATE TABLE IF NOT EXISTS pitch_templates (
    id          VARCHAR(36) PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    body        TEXT NOT NULL,
    category    VARCHAR(50) NOT NULL DEFAULT 'initial',
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
