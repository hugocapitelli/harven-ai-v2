import { useState, useEffect } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useSettings } from '../contexts/SettingsContext';
import { notificationsApi } from '../services/api';
import { cn, unwrapList } from '../lib/utils';
import type { ReactNode } from 'react';

// --- Sidebar ---
const instructorNav = [
  { to: '/instructor', icon: 'school', label: 'Minhas Disciplinas' },
  { to: '/courses', icon: 'menu_book', label: 'Cursos' },
];

const roleLabels: Record<string, string> = {
  STUDENT: 'Aluno',
  INSTRUCTOR: 'Professor',
  TEACHER: 'Professor',
  ADMIN: 'Administrador',
};

const APP_VERSION = 'v2.0';

const navItems: Record<string, { to: string; icon: string; label: string; requireGamification?: boolean }[]> = {
  STUDENT: [
    { to: '/dashboard', icon: 'home', label: 'Dashboard' },
    { to: '/courses', icon: 'school', label: 'Meus Estudos' },
    { to: '/history', icon: 'history', label: 'Historico' },
    { to: '/achievements', icon: 'emoji_events', label: 'Conquistas', requireGamification: true },
  ],
  INSTRUCTOR: instructorNav,
  TEACHER: instructorNav,
  ADMIN: [
    { to: '/admin', icon: 'dashboard', label: 'Console' },
    { to: '/admin/classes', icon: 'groups', label: 'Turmas' },
    { to: '/admin/users', icon: 'people', label: 'Usuarios' },
    { to: '/admin/settings', icon: 'settings', label: 'Configuracoes' },
  ],
};

function Sidebar({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  const { user } = useAuth();
  const { settings } = useSettings();
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => { onClose(); }, [location.pathname]);

  useEffect(() => {
    const onEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    if (isOpen) window.addEventListener('keydown', onEsc);
    return () => window.removeEventListener('keydown', onEsc);
  }, [isOpen, onClose]);

  if (!user) return null;
  const items = navItems[user.role] ?? [];
  const roleLabel = roleLabels[user.role] ?? user.role;
  const initials = user.name?.slice(0, 2).toUpperCase() ?? '?';

  return (
    <>
      {isOpen && <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-40 md:hidden" onClick={onClose} />}
      <aside
        role="navigation"
        aria-label="Menu principal"
        className={cn(
          'fixed top-0 left-0 h-full w-64 bg-harven-sidebar text-white flex flex-col z-50',
          'border-r border-white/[0.06] shadow-2xl shadow-black/20 transition-transform duration-300 ease-out',
          'md:translate-x-0',
          isOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        {/* Brand */}
        <div className="h-16 flex items-center px-6 border-b border-white/[0.06] flex-shrink-0">
          <img
            src={settings.logo_url || '/harven-logo-white.svg'}
            alt={settings.platform_name || 'Harven'}
            className="h-7 w-auto object-contain"
          />
        </div>

        {/* Navigation */}
        <nav className="flex-1 py-5 px-3 overflow-y-auto no-scrollbar">
          <p className="px-3 mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-white/30">
            Navegação
          </p>
          <div className="space-y-1">
            {items.map((item) => {
              if ('requireGamification' in item && item.requireGamification && !settings.gamification_enabled) return null;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === '/dashboard' || item.to === '/admin' || item.to === '/instructor'}
                  className={({ isActive }) => cn(
                    'group relative flex items-center gap-3 pl-4 pr-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-150',
                    isActive
                      ? 'bg-primary/[0.12] text-white'
                      : 'text-white/55 hover:text-white hover:bg-white/[0.04]',
                  )}
                >
                  {({ isActive }) => (
                    <>
                      <span
                        aria-hidden
                        className={cn(
                          'absolute left-0 top-1/2 -translate-y-1/2 h-5 w-1 rounded-r-full bg-primary transition-all duration-150',
                          isActive ? 'opacity-100 scale-y-100' : 'opacity-0 scale-y-0',
                        )}
                      />
                      <span
                        className={cn(
                          'material-symbols-outlined text-[20px] transition-colors flex-shrink-0',
                          isActive ? 'text-primary fill-1' : 'text-white/45 group-hover:text-white/80',
                        )}
                      >
                        {item.icon}
                      </span>
                      <span className="truncate">{item.label}</span>
                    </>
                  )}
                </NavLink>
              );
            })}
          </div>
        </nav>

        {/* User footer */}
        <div className="mt-auto border-t border-white/[0.06] p-3 flex-shrink-0">
          <button
            onClick={() => navigate('/profile')}
            className="w-full flex items-center gap-3 px-2 py-2 rounded-lg hover:bg-white/[0.05] transition-colors group text-left"
          >
            <span className="size-9 rounded-full bg-primary/15 ring-1 ring-primary/25 flex items-center justify-center text-primary text-xs font-bold flex-shrink-0 overflow-hidden">
              {user.avatar_url
                ? <img src={user.avatar_url} alt={user.name} className="size-full object-cover" />
                : initials}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-medium text-white truncate font-display">{user.name}</span>
              <span className="block text-xs text-white/45 truncate">{roleLabel}</span>
            </span>
            <span className="material-symbols-outlined text-[18px] text-white/25 group-hover:text-white/60 transition-colors flex-shrink-0">
              chevron_right
            </span>
          </button>
          <p className="mt-2.5 text-center text-[10px] tracking-wide text-white/25">
            {settings.platform_name || 'Harven AI'} · {APP_VERSION}
          </p>
        </div>
      </aside>
    </>
  );
}

// --- Header ---
interface NotificationItem {
  id: string;
  title: string;
  message?: string | null;
  type?: string | null;
  link?: string | null;
  read: boolean;
  created_at?: string;
}

function Header({ onToggleSidebar }: { onToggleSidebar: () => void }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [showMenu, setShowMenu] = useState(false);
  const [showNotifications, setShowNotifications] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);

  useEffect(() => {
    if (!user) return;
    notificationsApi.list(user.id).then((data) => {
      const list = unwrapList<NotificationItem>(data);
      setNotifications(list);
      setUnreadCount(list.filter((n) => !n.read).length);
    }).catch(() => {});
  }, [user]);

  const handleNotificationClick = async (item: NotificationItem) => {
    if (!item.read) {
      try {
        await notificationsApi.markRead(item.id);
        setNotifications((prev) => prev.map((n) => (n.id === item.id ? { ...n, read: true } : n)));
        setUnreadCount((prev) => Math.max(0, prev - 1));
      } catch {
        // silent — optimistic update already reflected in UI intent
      }
    }
    setShowNotifications(false);
    if (item.link) navigate(item.link);
  };

  return (
    <header className="h-16 bg-white border-b border-border flex items-center justify-between px-6 flex-shrink-0">
      <div className="flex items-center gap-3">
        <button onClick={onToggleSidebar} className="md:hidden text-foreground" aria-label="Menu">
          <span className="material-symbols-outlined">menu</span>
        </button>
      </div>
      <div className="flex items-center gap-4">
        <div className="relative">
          <button
            onClick={() => setShowNotifications((v) => !v)}
            className="relative text-muted-foreground hover:text-foreground transition-colors"
            aria-label="Notificacoes"
            aria-expanded={showNotifications}
          >
            <span className="material-symbols-outlined">notifications</span>
            {unreadCount > 0 && (
              <span className="absolute -top-1 -right-1 size-4 bg-destructive text-white text-[9px] rounded-full flex items-center justify-center font-bold">
                {unreadCount > 9 ? '9+' : unreadCount}
              </span>
            )}
          </button>
          {showNotifications && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setShowNotifications(false)} />
              <div className="absolute right-0 top-12 w-80 max-h-96 overflow-y-auto bg-white border border-border rounded-xl shadow-lg z-50 py-2">
                {notifications.length === 0 ? (
                  <p className="px-4 py-6 text-sm text-muted-foreground text-center">Nenhuma notificacao</p>
                ) : (
                  notifications.map((n) => (
                    <button
                      key={n.id}
                      onClick={() => handleNotificationClick(n)}
                      className={cn(
                        'w-full text-left px-4 py-2.5 text-sm hover:bg-muted transition-colors flex flex-col gap-0.5',
                        !n.read && 'bg-primary/5',
                      )}
                    >
                      <span className="font-medium text-foreground flex items-center gap-2">
                        {!n.read && <span className="size-1.5 rounded-full bg-primary flex-shrink-0" />}
                        {n.title}
                      </span>
                      {n.message && <span className="text-xs text-muted-foreground line-clamp-2">{n.message}</span>}
                    </button>
                  ))
                )}
              </div>
            </>
          )}
        </div>
        <div className="relative">
          <button onClick={() => setShowMenu(!showMenu)} className="flex items-center gap-2" aria-expanded={showMenu}>
            <div className="size-8 rounded-full bg-harven-dark flex items-center justify-center text-primary text-xs font-bold">
              {user?.name?.slice(0, 2).toUpperCase() ?? '?'}
            </div>
          </button>
          {showMenu && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setShowMenu(false)} />
              <div className="absolute right-0 top-12 w-48 bg-white border border-border rounded-xl shadow-lg z-50 py-2">
                <button onClick={() => { setShowMenu(false); navigate('/profile'); }} className="w-full text-left px-4 py-2 text-sm hover:bg-muted transition-colors flex items-center gap-2">
                  <span className="material-symbols-outlined text-[18px]">person</span> Perfil
                </button>
                <button onClick={() => { setShowMenu(false); navigate('/account'); }} className="w-full text-left px-4 py-2 text-sm hover:bg-muted transition-colors flex items-center gap-2">
                  <span className="material-symbols-outlined text-[18px]">settings</span> Conta
                </button>
                <div className="border-t border-border my-1" />
                <button onClick={() => { setShowMenu(false); logout(); navigate('/login'); }} className="w-full text-left px-4 py-2 text-sm text-destructive hover:bg-red-50 transition-colors flex items-center gap-2">
                  <span className="material-symbols-outlined text-[18px]">logout</span> Sair
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  );
}

// --- Layout ---
export default function Layout({ children }: { children: ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="h-screen flex bg-background">
      <Sidebar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="flex-1 flex flex-col md:ml-64 min-w-0">
        <Header onToggleSidebar={() => setSidebarOpen(!sidebarOpen)} />
        <main className="flex-1 overflow-y-auto animate-page-enter">{children}</main>
      </div>
    </div>
  );
}
