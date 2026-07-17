import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { disciplinesApi, coursesApi, userStatsApi } from '../../services/api';
import { unwrapList } from '../../lib/utils';
import { StatCard } from '../../components/ui/StatCard';
import { EmptyState } from '../../components/ui/EmptyState';
import { PageHeader } from '../../components/ui/PageHeader';

interface StatItem { label: string; value: string | number; icon: string }

export default function StudentDashboard() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [stats, setStats] = useState<StatItem[]>([]);
  const [courses, setCourses] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const ctrl = new AbortController();
    (async () => {
      try {
        if (!user) return;
        // O aluno le /users/{id}/stats (proprio) — /dashboard/stats e o agregado
        // admin e devolve chaves que nao existem para o aluno (dashboard zerado).
        const [statsData, disciplinesData] = await Promise.all([
          userStatsApi.getStats(user.id),
          disciplinesApi.list(),
        ]);
        if (ctrl.signal.aborted) return;

        setStats([
          { label: 'Cursos Concluidos', value: statsData?.courses_completed ?? 0, icon: 'menu_book' },
          { label: 'Horas Estudadas', value: `${statsData?.hours_studied ?? 0}h`, icon: 'schedule' },
          { label: 'Media Geral', value: statsData?.average_score?.toFixed?.(1) ?? '-', icon: 'trending_up' },
          { label: 'Pontos', value: statsData?.total_points ?? 0, icon: 'emoji_events' },
        ]);

        // N+1 sequencial derrubava o tempo de load com muitas disciplinas —
        // as listagens sao independentes, buscar em paralelo.
        const disciplines = unwrapList<Record<string, unknown>>(disciplinesData);
        const perDiscipline = await Promise.all(disciplines.map(async (d): Promise<Record<string, unknown>[]> => {
          try {
            const c = await coursesApi.listByClass(d.id as string);
            return unwrapList<Record<string, unknown>>(c).map((course) => ({ ...course, disciplineName: d.name ?? d.title }));
          } catch { return []; }
        }));
        if (ctrl.signal.aborted) return;
        const allCourses: Record<string, unknown>[] = perDiscipline.flat();
        // Progresso real por conteudo concluido — o objeto course do backend nao
        // traz `progress`; a fonte e /users/{id}/courses/{courseId}/progress.
        const withProgress = await Promise.all(allCourses.map(async (course) => {
          try {
            const p = await userStatsApi.getCourseProgress(user.id, course.id as string);
            return { ...course, progress: Math.round(Number(p?.progress_percent ?? 0)) };
          } catch {
            return { ...course, progress: Number(course.progress ?? 0) };
          }
        }));
        if (ctrl.signal.aborted) return;
        setCourses(withProgress);
      } catch {
        if (!ctrl.signal.aborted) console.error('Erro ao carregar dashboard');
      } finally {
        if (!ctrl.signal.aborted) setLoading(false);
      }
    })();
    return () => ctrl.abort();
  }, [user]);

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto p-8 space-y-8">
        <div className="space-y-2">
          <div className="h-8 w-64 bg-gray-200 animate-pulse rounded" />
          <div className="h-4 w-48 bg-gray-200 animate-pulse rounded" />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map(i => <div key={i} className="h-24 bg-gray-200 animate-pulse rounded-xl" />)}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {[1, 2, 3].map(i => (
            <div key={i} className="rounded-xl border p-4 space-y-3">
              <div className="h-40 bg-gray-200 animate-pulse rounded-lg" />
              <div className="h-4 w-3/4 bg-gray-200 animate-pulse rounded" />
              <div className="h-3 w-1/2 bg-gray-200 animate-pulse rounded" />
              <div className="h-2 w-full bg-gray-200 animate-pulse rounded" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto p-8 space-y-8 animate-in fade-in duration-500">
      <PageHeader
        title={`Bem-vindo de volta, ${user?.name?.split(' ')[0]}!`}
        subtitle="Continue de onde parou."
        constrained={false}
      />

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {stats.map((s, i) => (
          <StatCard key={s.label} icon={s.icon} value={s.value} label={s.label} variant={i === 0 ? 'highlight' : 'default'} />
        ))}
      </div>

      {/* Courses */}
      <div className="space-y-4">
        <h2 className="text-xl font-display font-semibold text-foreground">Minhas Disciplinas</h2>
        {courses.length === 0 ? (
          <div className="bg-white rounded-2xl border border-harven-border">
            <EmptyState icon="school" title="Nenhum curso encontrado" description="Voce ainda nao esta matriculado em nenhuma disciplina." />
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {courses.map((course) => (
              <div
                key={course.id as string}
                onClick={() => navigate(`/course/${course.id}`)}
                className="bg-white rounded-xl border border-harven-border shadow-sm overflow-hidden cursor-pointer hover:border-primary/50 transition-colors group"
              >
                <div className="h-40 bg-muted overflow-hidden">
                  {(course.image || course.image_url) ? (
                    <img src={(course.image || course.image_url) as string} alt={(course.title as string) ?? ''} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500" />
                  ) : (
                    <div className="w-full h-full bg-gradient-to-br from-harven-dark to-harven-sidebar flex items-center justify-center">
                      <span className="material-symbols-outlined text-primary/30 text-[64px]">school</span>
                    </div>
                  )}
                </div>
                <div className="p-5 space-y-3">
                  <h3 className="font-display font-bold text-foreground line-clamp-2 group-hover:text-primary-dark transition-colors">{course.title as string}</h3>
                  <p className="text-xs text-muted-foreground">{(course.disciplineName as string) ?? 'Disciplina'}</p>
                  <div className="space-y-1">
                    <div className="flex justify-between text-[10px] font-bold uppercase tracking-wider">
                      <span className="text-muted-foreground">Progresso</span>
                      <span className="text-foreground">{(course.progress as number) ?? 0}%</span>
                    </div>
                    <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                      <div className="h-full bg-primary rounded-full transition-all" style={{ width: `${(course.progress as number) ?? 0}%` }} />
                    </div>
                  </div>
                  <div className="flex justify-between items-center pt-1">
                    <span className="text-[10px] font-bold text-muted-foreground uppercase">{(course.chapters_count as number) ?? 0} Modulos</span>
                    <span className="text-xs font-bold text-foreground hover:text-primary-dark">{(course.progress as number) ?? 0 > 0 ? 'Continuar' : 'Iniciar'}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
