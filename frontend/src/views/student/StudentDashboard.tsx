import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { dashboardApi, disciplinesApi, coursesApi } from '../../services/api';
import { cn, unwrapList } from '../../lib/utils';

interface StatItem { label: string; value: string | number; icon: string; color: string }

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
        const [statsData, disciplinesData] = await Promise.all([
          dashboardApi.getStats(user.id),
          disciplinesApi.list(),
        ]);
        if (ctrl.signal.aborted) return;

        setStats([
          { label: 'Cursos em Andamento', value: statsData?.courses_in_progress ?? 0, icon: 'menu_book', color: 'text-blue-500' },
          { label: 'Horas Estudadas', value: `${statsData?.hours_studied ?? 0}h`, icon: 'schedule', color: 'text-green-500' },
          { label: 'Media Geral', value: statsData?.average_score?.toFixed?.(1) ?? '-', icon: 'trending_up', color: 'text-orange-500' },
          { label: 'Conquistas', value: statsData?.achievements_count ?? 0, icon: 'emoji_events', color: 'text-yellow-500' },
        ]);

        const allCourses: Record<string, unknown>[] = [];
        const disciplines = unwrapList<Record<string, unknown>>(disciplinesData);
        for (const d of disciplines) {
          try {
            const c = await coursesApi.listByClass(d.id as string);
            if (ctrl.signal.aborted) return;
            const courseList = unwrapList<Record<string, unknown>>(c);
            allCourses.push(...courseList.map((course) => ({ ...course, disciplineName: d.name ?? d.title })));
          } catch { /* skip */ }
        }
        setCourses(allCourses);
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
      <div>
        <h1 className="text-3xl font-display font-bold text-foreground">Bem-vindo de volta, {user?.name?.split(' ')[0]}!</h1>
        <p className="text-muted-foreground mt-1">Continue de onde parou.</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {stats.map((s) => (
          <div key={s.label} className="bg-white rounded-xl border border-harven-border p-4 flex items-center gap-4 shadow-sm">
            <div className={cn('size-12 rounded-xl bg-gray-100 flex items-center justify-center', s.color)}>
              <span className="material-symbols-outlined text-[24px]">{s.icon}</span>
            </div>
            <div>
              <p className="text-2xl font-display font-bold text-foreground">{s.value}</p>
              <p className="text-[10px] text-muted-foreground uppercase tracking-wider">{s.label}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Courses */}
      <div className="space-y-4">
        <h2 className="text-xl font-display font-bold text-foreground">Minhas Disciplinas</h2>
        {courses.length === 0 ? (
          <div className="text-center py-16 bg-white rounded-2xl border border-harven-border">
            <span className="material-symbols-outlined text-5xl text-gray-300 mb-3">school</span>
            <p className="text-gray-500 font-medium">Nenhum curso encontrado</p>
            <p className="text-xs text-gray-400 mt-1">Voce ainda nao esta matriculado em nenhuma disciplina.</p>
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
