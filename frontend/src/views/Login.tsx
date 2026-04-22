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
      {/* Left branding */}
      <div className="hidden md:flex w-1/2 bg-harven-dark relative flex-col overflow-hidden">
        <img src="/harven-login-bg.jpg" alt="" className="absolute inset-0 w-full h-full object-cover opacity-30" />
        <div className="absolute inset-0 bg-gradient-to-t from-harven-dark/90 via-harven-dark/40 to-harven-dark/70" />
        {/* Logo top-left */}
        <div className="relative z-10 p-8">
          <img src="/harven-logo-white.svg" alt="Harven" className="h-12 object-contain" />
        </div>
        {/* Center text */}
        <div className="relative z-10 flex-1 flex flex-col items-start justify-end px-12 pb-16">
          <h2 className="text-4xl font-display font-bold"><span className="text-primary">Tutor Harven</span> <span className="text-white">IA</span></h2>
          <p className="text-gray-400 text-sm max-w-sm mt-3">Plataforma de aprendizado com inteligência artificial</p>
        </div>
      </div>

      {/* Right form */}
      <div className="flex-1 flex items-center justify-center p-8 bg-white">
        <div className="w-full max-w-sm">
          <div className="md:hidden mb-8 text-center">
            <img src="/harven-logo.svg" alt="Harven" className="h-10 mx-auto" />
          </div>
          <h1 className="text-2xl font-display font-bold text-harven-dark mb-1">Entrar</h1>
          <p className="text-sm text-muted-foreground mb-8">Acesse com seu RA e senha</p>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="space-y-1.5">
              <label htmlFor="ra" className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">RA / Matricula</label>
              <input
                id="ra"
                type="text"
                value={ra}
                onChange={(e) => setRa(e.target.value)}
                className="w-full bg-harven-bg border-none rounded-lg px-4 py-2.5 text-sm text-harven-dark focus:ring-1 focus:ring-primary transition-all"
                placeholder="Digite seu RA"
                required
                autoFocus
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="pw" className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Senha</label>
              <div className="relative">
                <input
                  id="pw"
                  type={showPw ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full bg-harven-bg border-none rounded-lg px-4 py-2.5 pr-10 text-sm text-harven-dark focus:ring-1 focus:ring-primary transition-all"
                  placeholder="Digite sua senha"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPw(!showPw)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-harven-dark transition-colors"
                  tabIndex={-1}
                >
                  <span className="material-symbols-outlined text-[20px]">{showPw ? 'visibility_off' : 'visibility'}</span>
                </button>
              </div>
            </div>

            {error && (
              <div className="bg-red-50 border border-red-200 text-red-600 text-xs font-medium rounded-lg px-3 py-2">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-primary hover:bg-primary-dark text-harven-dark font-bold py-2.5 rounded-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed text-sm uppercase tracking-widest shadow-lg shadow-primary/20"
            >
              {loading ? 'Entrando...' : 'Entrar'}
            </button>
          </form>

          <div className="mt-6 flex justify-between text-xs text-muted-foreground">
            <a href="#" className="hover:text-harven-dark transition-colors">Esqueceu a senha?</a>
            <a href="#" className="hover:text-harven-dark transition-colors">Primeiro acesso?</a>
          </div>
        </div>
      </div>
    </div>
  );
}
