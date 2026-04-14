-- ============================================
-- Harven AI Platform v2 — Supabase Schema
-- Run this in the Supabase SQL Editor
-- ============================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- USERS
-- ============================================
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    ra VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    role VARCHAR(20) NOT NULL DEFAULT 'STUDENT',
    password_hash VARCHAR(255),
    avatar_url VARCHAR(500),
    moodle_user_id VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_ra ON users(ra);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

-- ============================================
-- DISCIPLINES
-- ============================================
CREATE TABLE IF NOT EXISTS disciplines (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    name VARCHAR(255) NOT NULL,
    code VARCHAR(50) UNIQUE NOT NULL,
    semester VARCHAR(20),
    description TEXT,
    image_url VARCHAR(500),
    jacad_code VARCHAR(50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS discipline_teachers (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    discipline_id TEXT NOT NULL REFERENCES disciplines(id) ON DELETE CASCADE,
    teacher_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(discipline_id, teacher_id)
);

CREATE TABLE IF NOT EXISTS discipline_students (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    discipline_id TEXT NOT NULL REFERENCES disciplines(id) ON DELETE CASCADE,
    student_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(discipline_id, student_id)
);

-- ============================================
-- COURSES
-- ============================================
CREATE TABLE IF NOT EXISTS courses (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    instructor_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    discipline_id TEXT REFERENCES disciplines(id) ON DELETE SET NULL,
    image_url VARCHAR(500),
    status VARCHAR(20) DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================
-- CHAPTERS
-- ============================================
CREATE TABLE IF NOT EXISTS chapters (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    "order" INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================
-- CONTENTS
-- ============================================
CREATE TABLE IF NOT EXISTS contents (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    content_type VARCHAR(50) NOT NULL,
    body TEXT,
    media_url VARCHAR(500),
    audio_url VARCHAR(500),
    "order" INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================
-- QUESTIONS
-- ============================================
CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    content_id TEXT NOT NULL REFERENCES contents(id) ON DELETE CASCADE,
    question_text TEXT NOT NULL,
    expected_answer TEXT,
    difficulty VARCHAR(20),
    skill VARCHAR(100),
    followup_prompts JSONB,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================
-- CHAT
-- ============================================
CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content_id TEXT REFERENCES contents(id) ON DELETE SET NULL,
    status VARCHAR(20) DEFAULT 'active',
    total_messages INTEGER DEFAULT 0,
    performance_score DOUBLE PRECISION,
    moodle_export_id VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    agent_type VARCHAR(50),
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================
-- SYSTEM SETTINGS
-- ============================================
CREATE TABLE IF NOT EXISTS system_settings (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    platform_name VARCHAR(255),
    base_url VARCHAR(500),
    primary_color VARCHAR(20),
    logo_url VARCHAR(500),
    login_logo_url VARCHAR(500),
    login_bg_url VARCHAR(500),
    ai_tutor_enabled BOOLEAN DEFAULT true,
    gamification_enabled BOOLEAN DEFAULT true,
    dark_mode_enabled BOOLEAN DEFAULT false,
    openai_key VARCHAR(500),
    moodle_url VARCHAR(500),
    moodle_token VARCHAR(500),
    smtp_password VARCHAR(500),
    jacad_api_key VARCHAR(500),
    lti_shared_secret VARCHAR(500),
    max_token_limit INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================
-- SYSTEM LOGS
-- ============================================
CREATE TABLE IF NOT EXISTS system_logs (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    message TEXT,
    author VARCHAR(255),
    status VARCHAR(50),
    log_type VARCHAR(50),
    details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================
-- SYSTEM BACKUPS
-- ============================================
CREATE TABLE IF NOT EXISTS system_backups (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    filename VARCHAR(255) NOT NULL,
    size INTEGER,
    records_count INTEGER,
    status VARCHAR(50) DEFAULT 'completed',
    storage_path VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================
-- NOTIFICATIONS
-- ============================================
CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    message TEXT,
    notification_type VARCHAR(50),
    link VARCHAR(500),
    is_read BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id);

-- ============================================
-- GAMIFICATION
-- ============================================
CREATE TABLE IF NOT EXISTS user_activities (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    activity_type VARCHAR(50) NOT NULL,
    description TEXT,
    points INTEGER DEFAULT 0,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_stats (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id TEXT UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    courses_completed INTEGER DEFAULT 0,
    hours_studied DOUBLE PRECISION DEFAULT 0.0,
    average_score DOUBLE PRECISION DEFAULT 0.0,
    streak_days INTEGER DEFAULT 0,
    total_points INTEGER DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_achievements (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    icon VARCHAR(100),
    category VARCHAR(50),
    rarity VARCHAR(20),
    points INTEGER DEFAULT 0,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    unlocked_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS certificates (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    certificate_number VARCHAR(100) UNIQUE NOT NULL,
    issued_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS course_progress (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    progress_percent DOUBLE PRECISION DEFAULT 0.0,
    completed_contents INTEGER DEFAULT 0,
    total_contents INTEGER DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, course_id)
);

-- ============================================
-- INTEGRATIONS
-- ============================================
CREATE TABLE IF NOT EXISTS external_mappings (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    entity_type VARCHAR(50) NOT NULL,
    local_id TEXT NOT NULL,
    external_id TEXT NOT NULL,
    external_system VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS moodle_ratings (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    session_id TEXT NOT NULL,
    student_id TEXT NOT NULL,
    teacher_id TEXT NOT NULL,
    rating DOUBLE PRECISION,
    feedback TEXT,
    rated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS integration_logs (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    system VARCHAR(50) NOT NULL,
    operation VARCHAR(100) NOT NULL,
    direction VARCHAR(20),
    status VARCHAR(20) NOT NULL,
    records_processed INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS token_usage (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    usage_date DATE NOT NULL,
    tokens_used INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, usage_date)
);

CREATE TABLE IF NOT EXISTS session_reviews (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    reviewer_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rating DOUBLE PRECISION,
    feedback TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    student_reply TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================
-- SEED: Admin user (password: admin123)
-- ============================================
INSERT INTO users (id, ra, name, email, role, password_hash)
VALUES (
    gen_random_uuid()::text,
    'admin',
    'Administrador',
    'admin@harven.ai',
    'ADMIN',
    '$2b$12$G1JgH9Ut8Fp6XKHSRxc82e23a8cWsOL/jIXXO/NZV0ld1p42x8z6q'
)
ON CONFLICT (ra) DO NOTHING;

-- ============================================
-- SEED: Default settings
-- ============================================
INSERT INTO system_settings (id, platform_name, ai_tutor_enabled, gamification_enabled)
VALUES (gen_random_uuid()::text, 'Harven.AI', true, true)
ON CONFLICT DO NOTHING;
