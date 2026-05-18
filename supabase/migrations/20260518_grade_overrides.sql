-- ============================================
-- Grade Overrides table for professor manual grading
-- ============================================
CREATE TABLE IF NOT EXISTS grade_overrides (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    discipline_id TEXT NOT NULL REFERENCES disciplines(id) ON DELETE CASCADE,
    student_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    grade DOUBLE PRECISION NOT NULL CHECK (grade >= 0 AND grade <= 10),
    graded_by TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (discipline_id, student_id, course_id)
);

-- Index for fast gradebook queries
CREATE INDEX IF NOT EXISTS idx_grade_overrides_discipline ON grade_overrides(discipline_id);
CREATE INDEX IF NOT EXISTS idx_grade_overrides_student ON grade_overrides(student_id);
