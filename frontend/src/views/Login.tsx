import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth, getDefaultRoute } from '../contexts/AuthContext';
export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [ra, setRa] = useState('');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(ra, password);
      const userData = JSON.parse(sessionStorage.getItem('user-data') ?? '{}');
      navigate(getDefaultRoute(userData.role ?? 'STUDENT'), { replace: true });
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? 'RA ou senha invalidos');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-screen flex">
      {/* Left branding — hero panel */}
      <div className="hidden md:flex w-[55%] bg-harven-dark relative flex-col overflow-hidden">
        <img src="/harven-login-bg.jpg" alt="" className="absolute inset-0 w-full h-full object-cover opacity-25" />
        <div className="absolute inset-0 bg-gradient-to-t from-harven-dark via-harven-dark/50 to-harven-dark/60" />

        {/* Logo */}
        <div className="relative z-10 p-10">
          <img src="/harven-logo-white.svg" alt="Harven" className="h-14 object-contain" />
        </div>

        {/* Hero content */}
        <div className="relative z-10 flex-1 flex flex-col items-start justify-end px-14 pb-14">
          <h2 className="text-5xl font-display font-bold leading-tight">
            <span className="text-primary">Tutor Harven</span>{' '}
            <span className="text-white">IA</span>
          </h2>
          <p className="text-gray-400 text-base max-w-md mt-4 leading-relaxed">
            Diálogos socráticos guiados por inteligência artificial. Aprendizado ativo, personalizado e mensurável.
          </p>

          {/* Feature pills */}
          <div className="flex flex-wrap gap-3 mt-8">
            {[
              { icon: 'forum', text: 'Método Socrático' },
              { icon: 'school', text: 'Ensino Ativo' },
              { icon: 'emoji_events', text: 'Gamificação' },
            ].map((f) => (
              <div key={f.text} className="flex items-center gap-2 bg-white/5 backdrop-blur-sm border border-white/10 rounded-full px-4 py-2">
                <span className="material-symbols-outlined text-primary text-[16px]">{f.icon}</span>
                <span className="text-white/70 text-sm">{f.text}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right form panel */}
      <div className="flex-1 flex items-center justify-center p-8 bg-white">
        <div className="w-full max-w-md">
          {/* Mobile logo */}
          <div className="md:hidden mb-10 text-center">
            <img src="/harven-logo.svg" alt="Harven" className="h-12 mx-auto" />
          </div>

          {/* Welcome text */}
          <div className="mb-10">
            <h1 className="text-3xl font-display font-bold text-harven-dark">Bem-vindo de volta</h1>
            <p className="text-base text-muted-foreground mt-2">Acesse com seu RA e senha para continuar</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-6">
            <div className="space-y-2">
              <label htmlFor="ra" className="text-xs font-semibold text-gray-500 uppercase tracking-wider">RA / Matrícula</label>
              <div className="relative">
                <span className="absolute left-4 top-1/2 -translate-y-1/2 material-symbols-outlined text-gray-400 text-[20px]">badge</span>
                <input
                  id="ra"
                  type="text"
                  value={ra}
                  onChange={(e) => setRa(e.target.value)}
                  className="w-full bg-gray-50 border border-gray-200 rounded-xl pl-12 pr-4 py-3.5 text-sm text-harven-dark placeholder:text-gray-400 focus:ring-2 focus:ring-primary/30 focus:border-primary transition-all"
                  placeholder="Digite seu RA"
                  required
                  autoFocus
                />
              </div>
            </div>

            <div className="space-y-2">
              <label htmlFor="pw" className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Senha</label>
              <div className="relative">
                <span className="absolute left-4 top-1/2 -translate-y-1/2 material-symbols-outlined text-gray-400 text-[20px]">lock</span>
                <input
                  id="pw"
                  type={showPw ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full bg-gray-50 border border-gray-200 rounded-xl pl-12 pr-12 py-3.5 text-sm text-harven-dark placeholder:text-gray-400 focus:ring-2 focus:ring-primary/30 focus:border-primary transition-all"
                  placeholder="Digite sua senha"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPw(!showPw)}
                  className="absolute right-4 top-1/2 -translate-y-1/2 text-gray-400 hover:text-harven-dark transition-colors"
                  tabIndex={-1}
                >
                  <span className="material-symbols-outlined text-[20px]">{showPw ? 'visibility_off' : 'visibility'}</span>
                </button>
              </div>
            </div>

            {error && (
              <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-600 text-sm font-medium rounded-xl px-4 py-3">
                <span className="material-symbols-outlined text-[18px]">error</span>
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-primary hover:bg-primary/90 text-harven-dark font-bold py-3.5 rounded-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed text-sm uppercase tracking-widest shadow-lg shadow-primary/25 hover:shadow-xl hover:shadow-primary/30 hover:-translate-y-0.5 active:translate-y-0"
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="animate-spin material-symbols-outlined text-[18px]">progress_activity</span>
                  Entrando...
                </span>
              ) : 'Entrar'}
            </button>
          </form>

          <div className="mt-8 flex justify-between text-sm text-muted-foreground">
            <a href="#" className="hover:text-harven-dark transition-colors">Esqueceu a senha?</a>
            <a href="#" className="hover:text-harven-dark transition-colors">Primeiro acesso?</a>
          </div>

          {/* Footer */}
          <div className="mt-16 text-center">
            <p className="text-xs text-gray-300">Harven Agribusiness School &copy; 2026</p>
          </div>
        </div>
      </div>
    </div>
  );
}
