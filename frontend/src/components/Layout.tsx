import { useState, useEffect } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useSettings } from '../contexts/SettingsContext';
import { notificationsApi } from '../services/api';
import { cn } from '../lib/utils';
import type { ReactNode } from 'react';

// --- Sidebar ---
const navItems = {
  STUDENT: [
    { to: '/dashboard', icon: 'home', label: 'Dashboard' },
    { to: '/courses', icon: 'school', label: 'Meus Estudos' },
    { to: '/history', icon: 'history', label: 'Historico' },
    { to: '/achievements', icon: 'emoji_events', label: 'Conquistas', requireGamification: true },
  ],
  INSTRUCTOR: [
    { to: '/instructor', icon: 'school', label: 'Minhas Disciplinas' },
    { to: '/courses', icon: 'menu_book', label: 'Cursos' },
  ],
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

  useEffect(() => { onClose(); }, [location.pathname]);

  useEffect(() => {
    const onEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    if (isOpen) window.addEventListener('keydown', onEsc);
    return () => window.removeEventListener('keydown', onEsc);
  }, [isOpen, onClose]);

  if (!user) return null;
  const items = navItems[user.role] ?? [];

  return (
    <>
      {isOpen && <div className="fixed inset-0 bg-black/50 z-40 md:hidden" onClick={onClose} />}
      <aside
        role="navigation"
        aria-label="Menu principal"
        className={cn(
          'fixed top-0 left-0 h-full w-64 bg-harven-sidebar text-white flex flex-col z-50 transition-transform duration-300',
          'md:translate-x-0',
          isOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="h-16 flex items-center px-6 border-b border-white/10">
          {settings.logo_url ? (
            <img src={settings.logo_url} alt={settings.platform_name} className="h-8 object-contain" />
          ) : (
            <span className="font-display font-bold text-lg text-primary">{settings.platform_name ?? 'Harven'}</span>
          )}
        </div>
        <nav className="flex-1 py-4 px-3 space-y-1 overflow-y-auto">
          {items.map((item) => {
            if ('requireGamification' in item && item.requireGamification && !settings.gamification_enabled) return null;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/dashboard' || item.to === '/admin' || item.to === '/instructor'}
                className={({ isActive }) => cn(
                  'flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors',
                  isActive ? 'bg-white/10 text-primary' : 'text-gray-400 hover:text-white hover:bg-white/5',
                )}
              >
                <span className="material-symbols-outlined text-[20px]">{item.icon}</span>
                {item.label}
              </NavLink>
            );
          })}
        </nav>
      </aside>
    </>
  );
}

// --- Header ---
function Header({ onToggleSidebar }: { onToggleSidebar: () => void }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [showMenu, setShowMenu] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);

  useEffect(() => {
    if (!user) return;
    notificationsApi.list(user.id).then((data: { read: boolean }[]) => {
      setUnreadCount(Array.isArray(data) ? data.filter((n) => !n.read).length : 0);
    }).catch(() => {});
  }, [user]);

  return (
    <header className="h-16 bg-white border-b border-border flex items-center justify-between px-6 flex-shrink-0">
      <div className="flex items-center gap-3">
        <button onClick={onToggleSidebar} className="md:hidden text-foreground" aria-label="Menu">
          <span className="material-symbols-outlined">menu</span>
        </button>
      </div>
      <div className="flex items-center gap-4">
        <button className="relative text-muted-foreground hover:text-foreground transition-colors" aria-label="Notificacoes">
          <span className="material-symbols-outlined">notifications</span>
          {unreadCount > 0 && (
            <span className="absolute -top-1 -right-1 size-4 bg-destructive text-white text-[9px] rounded-full flex items-center justify-center font-bold">
              {unreadCount > 9 ? '9+' : unreadCount}
            </span>
          )}
        </button>
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
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
