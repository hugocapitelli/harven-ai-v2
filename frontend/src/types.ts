// Harven AI v2 — Platform Type Definitions

export type UserRole = 'STUDENT' | 'INSTRUCTOR' | 'TEACHER' | 'ADMIN';

export interface User {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  avatar_url?: string;
  ra?: string;
  title?: string;
  bio?: string;
}

export interface Course {
  id: string;
  title: string;
  instructor?: string;
  description?: string;
  image?: string;
  image_url?: string;
  category?: string;
  progress?: number;
  status?: string;
  total_modules?: number;
  isFavorite?: boolean;
  chapters_count?: number;
}

export interface Discipline {
  id: string;
  name: string;
  title?: string;
  code?: string;
  department?: string;
  image?: string;
  icon?: string;
  status?: string;
  courses_count?: number;
  students?: number;
}

export interface Chapter {
  id: string;
  title: string;
  description?: string;
  order: number;
  course_id?: string;
  contents?: Content[];
}

export interface Content {
  id: string;
  title: string;
  type: 'TEXT' | 'VIDEO' | 'AUDIO';
  body?: string;
  file_url?: string;
  extracted_text?: string;
  completed?: boolean;
  completed_at?: string;
  chapter_id?: string;
}

export interface Question {
  id: string;
  question: string;
  expected_answer?: string;
  difficulty?: 'easy' | 'medium' | 'hard';
  type?: string;
  skill?: string;
  content_id?: string;
}

export interface SystemSettings {
  platform_name?: string;
  logo_url?: string;
  login_logo_url?: string;
  login_bg_url?: string;
  primary_color?: string;
  ai_tutor_enabled?: boolean;
  gamification_enabled?: boolean;
  dark_mode_enabled?: boolean;
  max_tokens_per_response?: number;
  max_upload_mb?: number;
  daily_token_limit?: number;
  session_timeout?: number;
  min_password_length?: number;
  require_special_chars?: boolean;
  password_expiration_days?: number;
  support_email?: string;
}

export interface Achievement {
  id: string;
  title: string;
  description?: string;
  icon: string;
  category: string;
  rarity: 'comum' | 'raro' | 'epico' | 'lendario';
  points: number;
  unlocked: boolean;
  progress: number;
  target: number;
  progress_percent: number;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  is_ai?: boolean;
}

export interface SessionReview {
  id: string;
  session_id: string;
  rating: number;
  feedback?: string;
  status: string;
  reviewer_name?: string;
  created_at?: string;
}

export interface Notification {
  id: string;
  title: string;
  message: string;
  read: boolean;
  created_at: string;
  type?: string;
}
