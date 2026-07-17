import { useState, useEffect } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { userStatsApi } from '../../services/api';
import { Card, CardContent, CardHeader } from '../../components/ui/Card';
import { Avatar } from '../../components/ui/Avatar';
import { Badge } from '../../components/ui/Badge';
import { Progress } from '../../components/ui/Progress';
import { Skeleton, SkeletonCard, SkeletonText } from '../../components/ui/Skeleton';
import { unwrapList } from '../../lib/utils';
import type { Achievement } from '../../types';

// Chaves REAIS de GET /users/{id}/stats (routes_admin.py user_stats) — as
// antigas total_courses/total_hours/avg_score nao existem e zeravam o perfil.
interface UserStats {
  courses_completed?: number;
  hours_studied?: number;
  average_score?: number;
  streak_days?: number;
  total_points?: number;
}

interface Activity {
  id: string;
  type: string;
  description: string;
  created_at: string;
  icon?: string;
}

interface Certificate {
  id: string;
  title: string;
  course_name?: string;
  issued_at: string;
  url?: string;
}

const ROLE_LABELS: Record<string, string> = { STUDENT: 'Aluno', INSTRUCTOR: 'Professor', TEACHER: 'Professor', ADMIN: 'Administrador' };
const ROLE_VARIANT: Record<string, 'default' | 'success' | 'danger'> = { STUDENT: 'default', INSTRUCTOR: 'success', TEACHER: 'success', ADMIN: 'danger' };

const RARITY_COLORS: Record<string, string> = {
  comum: 'border-gray-300 bg-gray-50',
  raro: 'border-harven-dark/30 bg-harven-dark/5',
  epico: 'border-harven-gold/30 bg-harven-gold/5',
  lendario: 'border-harven-gold bg-yellow-50',
};

const ACTIVITY_ICONS: Record<string, string> = {
  course_completed: 'school',
  chapter_completed: 'menu_book',
  achievement_unlocked: 'emoji_events',
  session_completed: 'forum',
  login: 'login',
};

export default function UserProfile() {
  const { user } = useAuth();
  const [stats, setStats] = useState<UserStats>({});
  const [activities, setActivities] = useState<Activity[]>([]);
  const [certificates, setCertificates] = useState<Certificate[]>([]);
  const [achievements, setAchievements] = useState<Achievement[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user?.id) return;
    const controller = new AbortController();
    const load = async () => {
      try {
        setLoading(true);
        const [s, a, c, ach] = await Promise.all([
          userStatsApi.getStats(user.id).catch(() => ({})),
          userStatsApi.getActivities(user.id).catch(() => []),
          userStatsApi.getCertificates(user.id).catch(() => []),
          userStatsApi.getAchievements(user.id).catch(() => []),
        ]);
        if (controller.signal.aborted) return;
        setStats(s ?? {});
        // activities/certificates/achievements chegam como envelope {data:[...]}
        // — Array.isArray no envelope zerava as tres listas. Mapeia tambem os
        // campos reais (activity_type; certificate_number; name em conquistas).
        setActivities(unwrapList<Record<string, unknown>>(a).map((r) => ({
          id: String(r.id ?? ''),
          type: String(r.activity_type ?? r.type ?? '').toLowerCase(),
          description: String(r.description ?? ''),
          created_at: String(r.created_at ?? ''),
        })));
        setCertificates(unwrapList<Record<string, unknown>>(c).map((r) => ({
          id: String(r.id ?? ''),
          title: String(r.title ?? r.certificate_number ?? 'Certificado'),
          course_name: (r.course_name as string) ?? undefined,
          issued_at: String(r.issued_at ?? ''),
          url: (r.url as string) ?? undefined,
        })));
        setAchievements(unwrapList<Record<string, unknown>>(ach).map((r) => ({
          id: String(r.id ?? ''),
          title: String(r.name ?? r.title ?? 'Conquista'),
          description: (r.description as string) ?? '',
          icon: String(r.icon ?? 'emoji_events'),
          category: String(r.category ?? 'jornada'),
          rarity: (String(r.rarity ?? 'comum').toLowerCase() as Achievement['rarity']),
          points: Number(r.points ?? 0),
          unlocked: true,
          progress: 1,
          target: 1,
          progress_percent: 100,
        })));
      } catch {
        if (controller.signal.aborted) return;
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    load();
    return () => controller.abort();
  }, [user?.id]);

  if (loading) {
    return (
      <div className="max-w-5xl mx-auto p-8 flex flex-col gap-6">
        <div className="flex gap-6"><Skeleton className="h-20 w-20 rounded-full" /><SkeletonText lines={3} /></div>
        <div className="grid grid-cols-4 gap-4">{Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)}</div>
        <SkeletonText lines={8} />
      </div>
    );
  }

  const statCards = [
    { icon: 'menu_book', label: 'Cursos', value: stats.courses_completed ?? 0 },
    { icon: 'schedule', label: 'Horas', value: stats.hours_studied ?? 0 },
    { icon: 'workspace_premium', label: 'Certificados', value: certificates.length },
    { icon: 'stars', label: 'Score', value: stats.average_score != null ? `${stats.average_score}%` : '—' },
  ];

  // Nivel derivado de total_points (100 pts/nivel, mesma regra de StudentAchievements)
  // — o backend nao devolve level/xp/next_level_xp.
  const totalPoints = stats.total_points ?? 0;
  const level = Math.floor(totalPoints / 100) + 1;
  const levelProgress = totalPoints % 100;

  const unlockedAchievements = achievements.filter((a) => a.unlocked);
  const lockedAchievements = achievements.filter((a) => !a.unlocked);

  return (
    <div className="max-w-5xl mx-auto p-8 flex flex-col gap-8 animate-in fade-in duration-500">
      {/* Profile Card */}
      <Card>
        <CardContent className="flex items-center gap-6 py-8">
          <Avatar src={user?.avatar_url} fallback={user?.name ?? '?'} size="xl" />
          <div className="flex-1">
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-display font-bold text-foreground">{user?.name}</h1>
              <Badge variant={ROLE_VARIANT[user?.role ?? 'STUDENT']}>{ROLE_LABELS[user?.role ?? 'STUDENT']}</Badge>
            </div>
            <p className="text-sm text-muted-foreground mt-1">{user?.email}</p>
            {user?.bio && <p className="text-sm text-foreground mt-3">{user.bio}</p>}

            {/* Level Progress */}
            <div className="mt-4 max-w-xs">
              <div className="flex items-center justify-between text-xs mb-1">
                <span className="font-bold text-foreground">Nível {level}</span>
                <span className="text-muted-foreground">{totalPoints} / {level * 100} XP</span>
              </div>
              <Progress value={levelProgress} />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {statCards.map((s) => (
          <Card key={s.label}>
            <CardContent className="text-center py-6">
              <span className="material-symbols-outlined text-[32px] text-primary mb-2 block">{s.icon}</span>
              <p className="text-2xl font-bold text-foreground">{s.value}</p>
              <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">{s.label}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Activity */}
        <Card>
          <CardHeader><h2 className="text-sm font-semibold text-foreground">Atividade Recente</h2></CardHeader>
          <CardContent>
            {activities.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">Nenhuma atividade registrada.</p>
            ) : (
              <div className="relative pl-6">
                <div className="absolute left-2.5 top-0 bottom-0 w-px bg-border" />
                {activities.slice(0, 10).map((a) => (
                  <div key={a.id} className="relative pb-4 last:pb-0">
                    <div className="absolute -left-3.5 top-1 h-5 w-5 rounded-full bg-muted flex items-center justify-center">
                      <span className="material-symbols-outlined text-[12px] text-primary">
                        {ACTIVITY_ICONS[a.type] ?? 'circle'}
                      </span>
                    </div>
                    <div className="ml-4">
                      <p className="text-sm text-foreground">{a.description}</p>
                      <p className="text-[10px] text-muted-foreground mt-0.5">
                        {new Date(a.created_at).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Certificates */}
        <Card>
          <CardHeader><h2 className="text-sm font-semibold text-foreground">Certificados</h2></CardHeader>
          <CardContent>
            {certificates.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">Nenhum certificado emitido.</p>
            ) : (
              <div className="flex flex-col gap-3">
                {certificates.map((c) => (
                  <div key={c.id} className="flex items-center gap-3 p-3 rounded-lg bg-muted/50">
                    <div className="h-10 w-10 rounded-lg bg-harven-gold/10 flex items-center justify-center shrink-0">
                      <span className="material-symbols-outlined text-harven-gold text-[20px]">workspace_premium</span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-foreground truncate">{c.title}</p>
                      <p className="text-xs text-muted-foreground">{c.course_name ?? ''} · {new Date(c.issued_at).toLocaleDateString('pt-BR')}</p>
                    </div>
                    {c.url && (
                      <a href={c.url} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline text-xs font-bold">
                        Ver
                      </a>
                    )}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Achievements */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-foreground">Conquistas</h2>
            <span className="text-xs text-muted-foreground">{unlockedAchievements.length} / {achievements.length}</span>
          </div>
        </CardHeader>
        <CardContent>
          {achievements.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-4">Nenhuma conquista disponível.</p>
          ) : (
            <>
              {unlockedAchievements.length > 0 && (
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3 mb-6">
                  {unlockedAchievements.map((a) => (
                    <div
                      key={a.id}
                      className={`p-4 rounded-xl border-2 text-center ${RARITY_COLORS[a.rarity] ?? 'border-gray-300 bg-gray-50'}`}
                    >
                      <span className="material-symbols-outlined text-3xl block mb-1">{a.icon}</span>
                      <p className="text-xs font-bold text-foreground">{a.title}</p>
                      <Badge variant="outline" className="mt-1 text-[8px]">{a.rarity}</Badge>
                      <p className="text-[10px] text-muted-foreground mt-1">+{a.points} XP</p>
                    </div>
                  ))}
                </div>
              )}

              {lockedAchievements.length > 0 && (
                <>
                  <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-3">Bloqueadas</p>
                  <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                    {lockedAchievements.map((a) => (
                      <div key={a.id} className="p-4 rounded-xl border border-border bg-muted/30 text-center opacity-60">
                        <span className="material-symbols-outlined text-3xl block mb-1 grayscale">{a.icon}</span>
                        <p className="text-xs font-bold text-foreground">{a.title}</p>
                        {a.target > 0 && (
                          <div className="mt-2">
                            <Progress value={a.progress_percent} className="h-1" />
                            <p className="text-[9px] text-muted-foreground mt-1">{a.progress}/{a.target}</p>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
