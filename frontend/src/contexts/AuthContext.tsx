import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';
import { authApi } from '../services/api';
import type { User, UserRole } from '../types';
import { safeJsonParse } from '../lib/utils';

interface AuthState {
  user: User | null;
  token: string | null;
  loading: boolean;
  login: (ra: string, password: string) => Promise<void>;
  logout: () => void;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const savedToken = sessionStorage.getItem('harven-access-token');
    const savedUser = safeJsonParse<User | null>('user-data', null);
    if (savedToken && savedUser) {
      setToken(savedToken);
      setUser(savedUser);
    }
    setLoading(false);
  }, []);

  const login = useCallback(async (ra: string, password: string) => {
    const data = await authApi.login(ra, password);
    const accessToken = data.access_token as string;
    const userData = data.user as User;
    sessionStorage.setItem('harven-access-token', accessToken);
    sessionStorage.setItem('user-data', JSON.stringify(userData));
    setToken(accessToken);
    setUser(userData);
  }, []);

  const logout = useCallback(() => {
    sessionStorage.removeItem('harven-access-token');
    sessionStorage.removeItem('user-data');
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, token, loading, login, logout, isAuthenticated: !!token }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

export function handleLtiCallback(searchParams: URLSearchParams): { token: string; user: User } | null {
  const ltiToken = searchParams.get('lti_token');
  const ltiUser = searchParams.get('lti_user');
  if (!ltiToken || !ltiUser) return null;
  try {
    const user = JSON.parse(decodeURIComponent(ltiUser)) as User;
    sessionStorage.setItem('harven-access-token', ltiToken);
    sessionStorage.setItem('user-data', JSON.stringify(user));
    return { token: ltiToken, user };
  } catch {
    return null;
  }
}

export function getDefaultRoute(role: UserRole): string {
  switch (role) {
    case 'ADMIN': return '/admin';
    case 'INSTRUCTOR':
    case 'TEACHER':
      return '/instructor';
    default: return '/dashboard';
  }
}
