import { useState, useEffect } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { userStatsApi } from '../../services/api';
import { cn } from '../../lib/utils';
import type { Achievement } from '../../types';

const categoryInfo: Record<string, { icon: string; color: string; label: string }> = {
  jornada: { icon: 'route', color: 'text-green-500', label: 'Jornada' },
  tempo: { icon: 'schedule', color: 'text-blue-500', label: 'Tempo' },
  desempenho: { icon: 'trending_up', color: 'text-orange-500', label: 'Desempenho' },
  certificados: { icon: 'workspace_premium', color: 'text-yellow-500', label: 'Certificados' },
  consistencia: { icon: 'bolt', color: 'text-red-500', label: 'Consistencia' },
  social: { icon: 'group', color: 'text-pink-500', label: 'Social' },
  especial: { icon: 'agriculture', color: 'text-emerald-600', label: 'Agro' },
};

const rarityStyles: Record<string, string> = {
  comum: 'bg-gray-100 text-gray-600',
  raro: 'bg-blue-100 text-blue-600',
  epico: 'bg-purple-100 text-purple-600',
  lendario: 'bg-gradient-to-br from-amber-100 to-yellow-100 text-amber-600',
};

const levelTitles = ['Novato', 'Iniciante Promissor', 'Aprendiz Curioso', 'Estudioso Dedicado', 'Erudito Socratico', 'Mestre Erudito', 'Lenda Suprema'];

function getLevel(points: number) { return Math.floor(points / 100) + 1; }
function getLevelProgress(points: number) { return points % 100; }
function getLevelTitle(level: number) { return levelTitles[Math.min(level - 1, levelTitles.length - 1)] ?? 'Novato'; }

export default function StudentAchievements() {
  const { user } = useAuth();
  const [achievements, setAchievements] = useState<Achievement[]>([]);
  const [totalPoints, setTotalPoints] = useState(0);
  const [userStats, setUserStats] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'all' | 'unlocked' | 'locked'>('all');
  const [selected, setSelected] = useState<Achievement | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    (async () => {
      try {
        if (!user) return;
        const [achData, statsData] = await Promise.all([
          userStatsApi.getAchievements(user.id),
          userStatsApi.getStats(user.id),
        ]);
        if (ctrl.signal.aborted) return;
        setAchievements(achData?.achievements ?? []);
        setTotalPoints(achData?.summary?.total_points ?? 0);
        setUserStats(statsData ?? {});
      } catch { /* handled */ } finally {
        if (!ctrl.signal.aborted) setLoading(false);
      }
    })();
    return () => ctrl.abort();
  }, [user]);

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto p-8 space-y-8">
        <div className="h-56 bg-gray-200 animate-pulse rounded-2xl" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map(i => <div key={i} className="h-20 bg-gray-200 animate-pulse rounded-xl" />)}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3, 4, 5, 6].map(i => <div key={i} className="h-32 bg-gray-200 animate-pulse rounded-xl" />)}
        </div>
      </div>
    );
  }

  const level = getLevel(totalPoints);
  const progress = getLevelProgress(totalPoints);
  const unlocked = achievements.filter(a => a.unlocked);
  const filtered = activeTab === 'unlocked' ? unlocked : activeTab === 'locked' ? achievements.filter(a => !a.unlocked) : achievements;
  const closeToUnlock = achievements.filter(a => !a.unlocked && a.progress_percent >= 50).sort((a, b) => b.progress_percent - a.progress_percent).slice(0, 3);

  return (
    <div className="max-w-7xl mx-auto p-8 space-y-8 animate-in fade-in duration-500">
      {/* Hero */}
      <div className="bg-harven-dark rounded-2xl p-8 text-white relative overflow-hidden">
        <div className="absolute top-0 right-0 size-64 bg-primary/10 rounded-full blur-3xl -translate-y-1/2 translate-x-1/4" />
        <div className="relative z-10 flex flex-col md:flex-row items-center gap-8">
          <div className="relative size-32 flex-shrink-0">
            <svg className="size-full -rotate-90" viewBox="0 0 36 36">
              <path className="text-white/10" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke="currentColor" strokeWidth="3" />
              <path className="text-primary" strokeDasharray={`${progress}, 100`} d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-xs font-bold text-primary uppercase tracking-widest">Nivel</span>
              <span className="text-4xl font-display font-bold">{level}</span>
            </div>
          </div>
          <div className="flex-1 text-center md:text-left">
            <h2 className="text-3xl font-display font-bold">{getLevelTitle(level)}</h2>
            <p className="text-gray-400 text-sm mt-2">
              <strong className="text-primary">{totalPoints} pontos</strong>
              {progress > 0 && <> — faltam <strong className="text-white">{100 - progress}</strong> para o proximo nivel</>}
            </p>
            <div className="flex flex-wrap gap-4 mt-4 justify-center md:justify-start">
              <div className="bg-white/5 border border-white/10 rounded-lg px-4 py-2 flex items-center gap-3">
                <span className="material-symbols-outlined text-orange-500 fill-1">local_fire_department</span>
                <div><p className="text-[10px] text-gray-400 uppercase">Ofensiva</p><p className="text-sm font-bold">{userStats.streak_days ?? 0} dias</p></div>
              </div>
              <div className="bg-white/5 border border-white/10 rounded-lg px-4 py-2 flex items-center gap-3">
                <span className="material-symbols-outlined text-harven-gold fill-1">military_tech</span>
                <div><p className="text-[10px] text-gray-400 uppercase">Conquistas</p><p className="text-sm font-bold">{unlocked.length}/{achievements.length}</p></div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Close to Unlock */}
      {closeToUnlock.length > 0 && (
        <div className="bg-white rounded-xl border border-harven-border p-6">
          <div className="flex items-center gap-2 mb-4">
            <span className="material-symbols-outlined text-orange-500">hourglass_top</span>
            <h3 className="font-display font-bold">Quase La!</h3>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {closeToUnlock.map(a => (
              <button key={a.id} onClick={() => setSelected(a)} className="text-left p-4 rounded-xl border border-harven-border hover:border-primary/50 transition-colors">
                <div className="flex items-center gap-3 mb-2">
                  <span className="material-symbols-outlined text-gray-400">{a.icon}</span>
                  <span className="font-bold text-sm">{a.title}</span>
                </div>
                <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                  <div className="h-full bg-primary rounded-full" style={{ width: `${a.progress_percent}%` }} />
                </div>
                <p className="text-[10px] text-muted-foreground mt-1">{a.progress_percent}%</p>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Tabs + Grid */}
      <div className="flex items-center gap-4 flex-wrap">
        <h3 className="text-xl font-display font-bold">Todas as Conquistas</h3>
        <div className="flex bg-muted rounded-lg p-1 gap-1">
          {(['all', 'unlocked', 'locked'] as const).map(tab => (
            <button key={tab} onClick={() => setActiveTab(tab)} className={cn('px-3 py-1.5 text-xs font-bold rounded-md transition-colors', activeTab === tab ? 'bg-white text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground')}>
              {tab === 'all' ? `Todas (${achievements.length})` : tab === 'unlocked' ? `Obtidas (${unlocked.length})` : `Bloqueadas (${achievements.length - unlocked.length})`}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2">
          {filtered.length === 0 ? (
            <div className="text-center py-16 bg-white rounded-2xl border border-harven-border">
              <span className="material-symbols-outlined text-5xl text-gray-300 mb-3">emoji_events</span>
              <p className="text-gray-500">Nenhuma conquista encontrada</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {filtered.map(a => (
                <button key={a.id} onClick={() => setSelected(a)} className={cn('text-left p-4 rounded-xl border transition-colors', a.unlocked ? 'bg-white border-harven-border hover:border-primary/50' : 'bg-gray-50 border-gray-200 opacity-70')}>
                  <div className="flex items-center gap-3 mb-2">
                    <div className={cn('size-10 rounded-lg flex items-center justify-center', rarityStyles[a.rarity] ?? 'bg-gray-100 text-gray-500')}>
                      <span className="material-symbols-outlined">{a.unlocked ? a.icon : 'lock'}</span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-bold text-sm truncate">{a.title}</p>
                      <p className="text-[10px] text-muted-foreground uppercase">{a.rarity} — {a.points} pts</p>
                    </div>
                  </div>
                  {!a.unlocked && (
                    <div className="h-1.5 bg-muted rounded-full overflow-hidden mt-2">
                      <div className="h-full bg-primary rounded-full" style={{ width: `${a.progress_percent}%` }} />
                    </div>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Sidebar */}
        <div className="space-y-6">
          <div className="bg-white rounded-xl border border-harven-border p-6">
            <h3 className="font-display font-bold mb-4 flex items-center gap-2">
              <span className="material-symbols-outlined text-purple-500">category</span> Por Categoria
            </h3>
            <div className="space-y-3">
              {Object.entries(categoryInfo).map(([key, info]) => {
                const cat = achievements.filter(a => a.category === key);
                const catUnlocked = cat.filter(a => a.unlocked).length;
                if (cat.length === 0) return null;
                return (
                  <div key={key} className="flex items-center gap-3">
                    <div className={cn('size-8 rounded-lg bg-gray-100 flex items-center justify-center', info.color)}>
                      <span className="material-symbols-outlined text-[18px]">{info.icon}</span>
                    </div>
                    <div className="flex-1">
                      <div className="flex justify-between text-sm mb-1">
                        <span className="font-medium">{info.label}</span>
                        <span className="text-muted-foreground">{catUnlocked}/{cat.length}</span>
                      </div>
                      <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                        <div className="h-full bg-primary rounded-full" style={{ width: `${cat.length > 0 ? Math.round((catUnlocked / cat.length) * 100) : 0}%` }} />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="bg-white rounded-xl border border-harven-border p-6">
            <h3 className="font-display font-bold mb-4 flex items-center gap-2">
              <span className="material-symbols-outlined text-harven-gold">diamond</span> Por Raridade
            </h3>
            <div className="grid grid-cols-2 gap-3">
              {Object.entries(rarityStyles).map(([key, cls]) => {
                const r = achievements.filter(a => a.rarity === key);
                const u = r.filter(a => a.unlocked).length;
                return (
                  <div key={key} className={cn('p-3 rounded-xl', cls)}>
                    <p className="text-lg font-bold">{u}/{r.length}</p>
                    <p className="text-[10px] uppercase tracking-wider opacity-80">{key}</p>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Modal */}
      {selected && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={() => setSelected(null)}>
          <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-8 animate-in zoom-in-95" onClick={e => e.stopPropagation()}>
            <div className="text-center">
              <div className={cn('size-24 mx-auto rounded-2xl flex items-center justify-center mb-4', rarityStyles[selected.rarity] ?? 'bg-gray-100 text-gray-500')}>
                <span className="material-symbols-outlined text-[48px]">{selected.unlocked ? selected.icon : 'lock'}</span>
              </div>
              <h2 className="text-2xl font-display font-bold mb-2">{selected.title}</h2>
              <span className={cn('inline-block px-3 py-1 rounded-full text-xs font-bold uppercase mb-4', rarityStyles[selected.rarity])}>{selected.rarity}</span>
              <p className="text-gray-600 mb-6">{selected.description}</p>
              {!selected.unlocked && (
                <div className="mb-6">
                  <div className="flex justify-between text-sm mb-2"><span className="text-gray-500">Progresso</span><span className="font-bold">{selected.progress}/{selected.target}</span></div>
                  <div className="h-3 bg-gray-100 rounded-full overflow-hidden"><div className="h-full bg-primary rounded-full" style={{ width: `${selected.progress_percent}%` }} /></div>
                </div>
              )}
              <div className="flex items-center justify-center gap-2 text-lg"><span className="material-symbols-outlined text-yellow-500">star</span><span className="font-bold">{selected.points} pontos</span></div>
            </div>
            <button onClick={() => setSelected(null)} className="w-full mt-6 py-3 bg-harven-dark text-white font-bold rounded-xl hover:bg-black transition-colors">Fechar</button>
          </div>
        </div>
      )}
    </div>
  );
}
