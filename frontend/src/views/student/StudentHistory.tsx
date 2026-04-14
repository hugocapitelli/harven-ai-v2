import { useState, useEffect } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { userStatsApi } from '../../services/api';
import { cn } from '../../lib/utils';

interface Activity {
  id: string;
  activity_type: string;
  description?: string;
  course_name?: string;
  topic?: string;
  score?: number;
  total?: number;
  duration_minutes?: number;
  created_at: string;
}

const typeConfig: Record<string, { label: string; icon: string; color: string; bg: string }> = {
  CHAT: { label: 'Debate Socratico', icon: 'forum', color: 'text-purple-600', bg: 'bg-purple-100' },
  QUIZ: { label: 'Quiz', icon: 'quiz', color: 'text-blue-600', bg: 'bg-blue-100' },
  CONTENT: { label: 'Conteudo', icon: 'article', color: 'text-green-600', bg: 'bg-green-100' },
  COURSE: { label: 'Curso', icon: 'school', color: 'text-orange-600', bg: 'bg-orange-100' },
};

const tabs = [
  { id: 'all', label: 'Tudo' },
  { id: 'CHAT', label: 'Debates' },
  { id: 'QUIZ', label: 'Quizzes' },
  { id: 'CONTENT', label: 'Conteudos' },
];

function formatDate(iso: string) {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch { return iso; }
}

export default function StudentHistory() {
  const { user } = useAuth();
  const [activities, setActivities] = useState<Activity[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('all');

  useEffect(() => {
    const ctrl = new AbortController();
    (async () => {
      try {
        if (!user) return;
        const data = await userStatsApi.getActivities(user.id);
        if (ctrl.signal.aborted) return;
        setActivities(Array.isArray(data) ? data : []);
      } catch { /* handled */ } finally {
        if (!ctrl.signal.aborted) setLoading(false);
      }
    })();
    return () => ctrl.abort();
  }, [user]);

  const filtered = activeTab === 'all' ? activities : activities.filter(a => a.activity_type === activeTab);

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto p-8 space-y-6">
        <div className="h-8 w-48 bg-gray-200 animate-pulse rounded" />
        <div className="h-10 w-full bg-gray-200 animate-pulse rounded-lg" />
        {[1, 2, 3, 4, 5].map(i => <div key={i} className="h-20 bg-gray-200 animate-pulse rounded-xl" />)}
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-8 space-y-6 animate-in fade-in duration-500">
      <h1 className="text-3xl font-display font-bold text-foreground">Historico de Atividades</h1>

      {/* Tabs */}
      <div className="flex bg-muted rounded-lg p-1 gap-1">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn('px-4 py-2 text-xs font-bold rounded-md transition-colors', activeTab === tab.id ? 'bg-white text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground')}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="text-center py-16 bg-white rounded-2xl border border-harven-border">
          <span className="material-symbols-outlined text-5xl text-gray-300 mb-3">history</span>
          <p className="text-gray-500 font-medium">Nenhuma atividade encontrada</p>
          <p className="text-xs text-gray-400 mt-1">Suas atividades aparecerão aqui conforme voce estuda.</p>
        </div>
      ) : (
        <div className="relative">
          <div className="absolute left-6 top-0 bottom-0 w-0.5 bg-harven-border" />
          <div className="space-y-4">
            {filtered.map(activity => {
              const cfg = typeConfig[activity.activity_type] ?? typeConfig['CONTENT']!;
              const isQuiz = activity.activity_type === 'QUIZ';
              const passed = isQuiz && activity.score != null && activity.total != null && (activity.score / activity.total) >= 0.7;

              return (
                <div key={activity.id} className="relative pl-14">
                  <div className={cn('absolute left-4 top-4 size-4 rounded-full border-2 border-white z-10', cfg.bg)} />
                  <div className="bg-white rounded-xl border border-harven-border p-4 hover:border-primary/30 transition-colors">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex items-center gap-3">
                        <div className={cn('size-9 rounded-lg flex items-center justify-center', cfg.bg, cfg.color)}>
                          <span className="material-symbols-outlined text-[18px]">{cfg.icon}</span>
                        </div>
                        <div>
                          <span className={cn('text-[10px] font-bold px-2 py-0.5 rounded uppercase', cfg.bg, cfg.color)}>{cfg.label}</span>
                          <p className="text-sm font-bold text-foreground mt-1">{activity.description ?? activity.topic ?? 'Atividade'}</p>
                          {activity.course_name && <p className="text-xs text-muted-foreground">{activity.course_name}</p>}
                        </div>
                      </div>
                      <div className="text-right flex-shrink-0">
                        <p className="text-[10px] text-muted-foreground">{formatDate(activity.created_at)}</p>
                        {isQuiz && activity.score != null && (
                          <span className={cn('text-xs font-bold mt-1 inline-block px-2 py-0.5 rounded', passed ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-600')}>
                            {passed ? 'Aprovado' : 'Reprovado'} — {activity.score}/{activity.total}
                          </span>
                        )}
                        {activity.activity_type === 'CONTENT' && (
                          <span className="text-xs font-bold mt-1 inline-block px-2 py-0.5 rounded bg-green-100 text-green-700">Concluido</span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
