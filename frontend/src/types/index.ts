// ─── User ────────────────────────────────────────────────────────────────────

export type UserRole = 'ADMIN' | 'INSTRUCTOR' | 'STUDENT';

export interface User {
  id: string;
  name: string;
  email: string;
  ra: string;
  role: UserRole;
  avatar_url?: string;
  title?: string;
  bio?: string;
  created_at?: string;
}

// ─── Auth ────────────────────────────────────────────────────────────────────

export interface LoginRequest {
  ra: string;
  password: string;
}

export interface LoginResponse {
  token: string;
  user: User;
}

// ─── Settings ────────────────────────────────────────────────────────────────

export interface SystemSettings {
  id?: string;
  platform_name: string;
  institution_name?: string;
  institution_logo?: string;
  login_logo?: string;
  login_bg?: string;
  primary_color: string;
  secondary_color: string;
  accent_color: string;
  ai_provider?: string;
  ai_model?: string;
  max_upload_mb: number;
  gamification_enabled: boolean;
  certificates_enabled: boolean;
  socratic_enabled: boolean;
  session_timeout: number;
  created_at?: string;
  updated_at?: string;
}

// ─── Notification ────────────────────────────────────────────────────────────

export interface Notification {
  id: string;
  title: string;
  message: string;
  read: boolean;
  created_at: string;
}

// ─── Navigation ──────────────────────────────────────────────────────────────

export interface NavItem {
  label: string;
  path: string;
  icon: string;
}
