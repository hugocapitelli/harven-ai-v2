import { BrowserRouter, Routes, Route, Navigate, useNavigate, useLocation, useSearchParams } from 'react-router-dom';
import { Suspense, lazy, useEffect, useRef } from 'react';
import { Toaster, toast } from 'sonner';
import { AuthProvider, useAuth, handleLtiCallback, getDefaultRoute } from './contexts/AuthContext';
import { SettingsProvider, useSettings } from './contexts/SettingsContext';
import Layout from './components/Layout';

const Login = lazy(() => import('./views/Login'));
const StudentDashboard = lazy(() => import('./views/student/StudentDashboard'));
const StudentAchievements = lazy(() => import('./views/student/StudentAchievements'));
const StudentHistory = lazy(() => import('./views/student/StudentHistory'));

const PageLoader = () => (
  <div className="flex items-center justify-center h-screen bg-background">
    <div className="animate-pulse flex flex-col items-center gap-3">
      <div className="size-10 rounded-full bg-primary/30" />
      <div className="h-2 w-24 bg-muted rounded" />
    </div>
  </div>
);

function AppRoutes() {
  const { user, isAuthenticated, loading: authLoading, logout } = useAuth();
  const { settings, loading: settingsLoading } = useSettings();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const lastActivity = useRef(Date.now());

  // LTI callback
  useEffect(() => {
    if (location.pathname === '/lti-callback') {
      const result = handleLtiCallback(searchParams);
      if (result) {
        navigate(getDefaultRoute(result.user.role), { replace: true });
      } else {
        navigate('/login', { replace: true });
      }
    }
  }, [location.pathname, searchParams, navigate]);

  // Idle timeout
  useEffect(() => {
    if (!isAuthenticated || !settings.session_timeout) return;
    const timeoutMs = (settings.session_timeout ?? 3600) * 1000;
    const warnAt = timeoutMs * 0.85;

    const resetTimer = () => { lastActivity.current = Date.now(); };
    window.addEventListener('mousemove', resetTimer);
    window.addEventListener('keydown', resetTimer);

    const interval = setInterval(() => {
      const elapsed = Date.now() - lastActivity.current;
      if (elapsed >= timeoutMs) {
        logout();
        navigate('/login', { replace: true });
        toast.error('Sessao expirada por inatividade');
      } else if (elapsed >= warnAt) {
        toast.warning('Sua sessao expirara em breve por inatividade');
      }
    }, 30000);

    return () => {
      window.removeEventListener('mousemove', resetTimer);
      window.removeEventListener('keydown', resetTimer);
      clearInterval(interval);
    };
  }, [isAuthenticated, settings.session_timeout, logout, navigate]);

  if (authLoading || settingsLoading) return <PageLoader />;

  if (!isAuthenticated) {
    return (
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/lti-callback" element={<PageLoader />} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </Suspense>
    );
  }

  return (
    <Layout>
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route path="/" element={<Navigate to={getDefaultRoute(user!.role)} replace />} />
          <Route path="/dashboard" element={<StudentDashboard />} />
          <Route path="/achievements" element={settings.gamification_enabled ? <StudentAchievements /> : <Navigate to="/dashboard" replace />} />
          <Route path="/history" element={<StudentHistory />} />
          <Route path="/login" element={<Navigate to={getDefaultRoute(user!.role)} replace />} />
          <Route path="*" element={<Navigate to={getDefaultRoute(user!.role)} replace />} />
        </Routes>
      </Suspense>
    </Layout>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <SettingsProvider>
          <AppRoutes />
          <Toaster position="top-right" richColors closeButton />
        </SettingsProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
