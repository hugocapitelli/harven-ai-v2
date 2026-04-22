// @ts-nocheck
import { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { useAuth } from '../../contexts/AuthContext';
import { disciplinesApi, coursesApi } from '../../services/api';
import { unwrapList } from '../../lib/utils';
import { Button } from '../../components/ui/Button';
import { Card, CardContent, CardHeader } from '../../components/ui/Card';
import { Input } from '../../components/ui/Input';
import { Badge } from '../../components/ui/Badge';
import { Tabs } from '../../components/ui/Tabs';
import { Avatar } from '../../components/ui/Avatar';
import { Progress } from '../../components/ui/Progress';
import { Skeleton, SkeletonCard, SkeletonText } from '../../components/ui/Skeleton';
import type { Discipline, Course } from '../../types';

interface StudentStat {
  id: string;
  name: string;
  email: string;
  avatar_url?: string;
  progress: number;
  grade?: number;
  sessions_count?: number;
}

interface SessionEntry {
  id: string;
  student_name: string;
  content_title?: string;
  total_messages: number;
  status: string;
  created_at: string;
  review?: { rating: number; status: string } | null;
}

const TABS = [
  { id: 'disciplinas', label: 'Disciplinas', icon: 'menu_book' },
  { id: 'alunos', label: 'Alunos', icon: 'group' },
  { id: 'notas', label: 'Quadro de Notas', icon: 'grade' },
  { id: 'conversas', label: 'Conversas', icon: 'forum' },
];

function StarRating({ value }: { value: number }) {
  return (
    <div className="flex gap-0.5">
      {[1, 2, 3, 4, 5].map((star) => (
        <span
          key={star}
          className={`material-symbols-outlined text-[16px] ${star <= value ? 'fill-1 text-harven-gold' : 'text-muted'}`}
        >
          star
        </span>
      ))}
    </div>
  );
}

export default function InstructorDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();

  const [discipline, setDiscipline] = useState<Discipline | null>(null);
  const [courses, setCourses] = useState<Course[]>([]);
  const [students, setStudents] = useState<StudentStat[]>([]);
  const [sessions, setSessions] = useState<SessionEntry[]>([]);
  const [stats, setStats] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('disciplinas');
  const [search, setSearch] = useState('');
  const [showAddCourse, setShowAddCourse] = useState(false);
  const [newCourseTitle, setNewCourseTitle] = useState('');
  const [saving, setSaving] = useState(false);

  const load = useCallback(async (controller: AbortController) => {
    if (!id) return;
    try {
      setLoading(true);
      const [disc, courseList, studentStats, discStats] = await Promise.all([
        disciplinesApi.get(id),
        coursesApi.listByClass(id),
        disciplinesApi.getStudentsStats(id).catch(() => []),
        disciplinesApi.getStats(id).catch(() => ({})),
      ]);
      if (controller.signal.aborted) return;
      setDiscipline(disc);
      setCourses(unwrapList(courseList));
      const sStats = (studentStats && typeof studentStats === 'object' && 'students' in studentStats) ? (studentStats as any).students : unwrapList(studentStats);
      setStudents(Array.isArray(sStats) ? sStats : []);
      setStats(discStats ?? {});
    } catch (err) {
      if (controller.signal.aborted) return;
      console.error('Error loading discipline:', err);
      toast.error('Erro ao carregar disciplina.');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    const controller = new AbortController();
    load(controller);
    return () => controller.abort();
  }, [load]);

  useEffect(() => {
    if (activeTab !== 'conversas' || !id) return;
    const controller = new AbortController();
    disciplinesApi.getSessions(id).then((data) => {
      if (!controller.signal.aborted) setSessions(unwrapList(data));
    }).catch(() => {});
    return () => controller.abort();
  }, [activeTab, id]);

  const handleAddCourse = async () => {
    if (!id || !newCourseTitle.trim()) return;
    setSaving(true);
    try {
      await coursesApi.createInClass(id, { title: newCourseTitle.trim(), status: 'draft' });
      toast.success('Curso adicionado.');
      setShowAddCourse(false);
      setNewCourseTitle('');
      const controller = new AbortController();
      load(controller);
    } catch {
      toast.error('Erro ao criar curso.');
    } finally {
      setSaving(false);
    }
  };

  const filterBySearch = <T extends Record<string, unknown>>(items: T[], keys: string[]) =>
    items.filter((item) =>
      keys.some((k) => String(item[k] ?? '').toLowerCase().includes(search.toLowerCase())),
    );

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto p-8 flex flex-col gap-6">
        <Skeleton className="h-40 w-full rounded-xl" />
        <Skeleton className="h-10 w-64" />
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => <SkeletonCard key={i} />)}
        </div>
      </div>
    );
  }

  if (!discipline) {
    return (
      <div className="max-w-7xl mx-auto p-8 text-center">
        <p className="text-muted-foreground">Disciplina não encontrada.</p>
        <Button variant="outline" className="mt-4" onClick={() => navigate('/instructor')}>Voltar</Button>
      </div>
    );
  }

  const filteredCourses = filterBySearch(courses, ['title']);
  const filteredStudents = filterBySearch(students, ['name', 'email']);
  const filteredSessions = filterBySearch(sessions, ['student_name', 'content_title']);

  return (
    <div className="max-w-7xl mx-auto p-8 flex flex-col gap-8 animate-in fade-in duration-500">
      {/* Header Banner */}
      <div className="relative rounded-xl overflow-hidden bg-accent text-accent-foreground p-8">
        {discipline.image && (
          <img src={discipline.image} alt="" className="absolute inset-0 w-full h-full object-cover opacity-20" />
        )}
        <div className="relative z-10">
          <Button variant="ghost" size="sm" className="mb-4 text-accent-foreground/70" onClick={() => navigate('/instructor')}>
            <span className="material-symbols-outlined text-[16px] mr-1">arrow_back</span> Voltar
          </Button>
          <h1 className="text-3xl font-display font-bold">{discipline.name}</h1>
          {discipline.code && <p className="text-sm opacity-70 mt-1">{discipline.code} · {discipline.department ?? ''}</p>}
          <div className="flex gap-4 mt-6">
            {[
              { icon: 'menu_book', label: 'Cursos', value: stats.courses_count ?? courses.length },
              { icon: 'group', label: 'Alunos', value: stats.students_count ?? students.length },
              { icon: 'forum', label: 'Conversas', value: stats.sessions_count ?? sessions.length },
              { icon: 'trending_up', label: 'Progresso Médio', value: `${stats.avg_progress ?? 0}%` },
            ].map((s) => (
              <Card key={s.label} className="bg-white/10 border-white/20 backdrop-blur-sm px-4 py-3">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-[20px] text-primary">{s.icon}</span>
                  <div>
                    <p className="text-lg font-bold text-white">{s.value}</p>
                    <p className="text-[10px] uppercase tracking-widest text-white/60">{s.label}</p>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <Tabs items={TABS} activeTab={activeTab} onChange={setActiveTab} ariaLabel="Seções da disciplina" />
        <div className="flex items-center gap-3">
          <Input
            icon="search"
            placeholder="Buscar..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            containerClassName="w-64"
          />
          {activeTab === 'disciplinas' && (
            <Button size="sm" onClick={() => setShowAddCourse(true)}>
              <span className="material-symbols-outlined text-[16px] mr-1">add</span> Curso
            </Button>
          )}
        </div>
      </div>

      {/* Tab: Disciplinas (courses) */}
      {activeTab === 'disciplinas' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredCourses.length === 0 ? (
            <Card className="col-span-full p-8 text-center">
              <span className="material-symbols-outlined text-4xl text-muted-foreground mb-2 block">menu_book</span>
              <p className="text-muted-foreground">Nenhum curso encontrado.</p>
            </Card>
          ) : (
            filteredCourses.map((c) => (
              <Card key={c.id} hoverEffect onClick={() => navigate(`/course/${c.id}`)}>
                {c.image_url && (
                  <div className="h-32 bg-muted overflow-hidden">
                    <img src={c.image_url} alt="" className="w-full h-full object-cover" />
                  </div>
                )}
                <CardContent>
                  <h3 className="font-display font-bold text-foreground">{c.title}</h3>
                  {c.description && (
                    <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{c.description}</p>
                  )}
                  <div className="flex items-center gap-3 mt-3 text-xs text-muted-foreground">
                    <span className="inline-flex items-center gap-1">
                      <span className="material-symbols-outlined text-[14px]">library_books</span>
                      {c.chapters_count ?? 0} capítulos
                    </span>
                    <Badge variant={c.status === 'Ativo' ? 'success' : 'outline'}>{c.status ?? 'Ativo'}</Badge>
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </div>
      )}

      {/* Tab: Alunos */}
      {activeTab === 'alunos' && (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left px-4 py-3 text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Aluno</th>
                  <th className="text-left px-4 py-3 text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Progresso</th>
                  <th className="text-left px-4 py-3 text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Nota</th>
                  <th className="text-left px-4 py-3 text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Sessões</th>
                </tr>
              </thead>
              <tbody>
                {filteredStudents.length === 0 ? (
                  <tr><td colSpan={4} className="px-4 py-8 text-center text-muted-foreground">Nenhum aluno encontrado.</td></tr>
                ) : (
                  filteredStudents.map((s) => (
                    <tr key={s.id} className="border-b border-border last:border-0 hover:bg-muted/50 transition-colors">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          <Avatar src={s.avatar_url} fallback={s.name} size="sm" />
                          <div>
                            <p className="font-medium text-foreground">{s.name}</p>
                            <p className="text-xs text-muted-foreground">{s.email}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2 w-32">
                          <Progress value={s.progress} className="flex-1" />
                          <span className="text-xs text-muted-foreground">{s.progress}%</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 font-bold text-foreground">{s.grade != null ? s.grade.toFixed(1) : '—'}</td>
                      <td className="px-4 py-3 text-muted-foreground">{s.sessions_count ?? 0}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Tab: Quadro de Notas */}
      {activeTab === 'notas' && (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left px-4 py-3 text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Aluno</th>
                  {courses.slice(0, 8).map((c) => (
                    <th key={c.id} className="text-center px-3 py-3 text-[10px] font-bold text-muted-foreground uppercase tracking-widest max-w-[120px] truncate">
                      {c.title}
                    </th>
                  ))}
                  <th className="text-center px-4 py-3 text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Média</th>
                </tr>
              </thead>
              <tbody>
                {filteredStudents.length === 0 ? (
                  <tr><td colSpan={courses.length + 2} className="px-4 py-8 text-center text-muted-foreground">Nenhum dado disponível.</td></tr>
                ) : (
                  filteredStudents.map((s) => (
                    <tr key={s.id} className="border-b border-border last:border-0 hover:bg-muted/50">
                      <td className="px-4 py-3 font-medium text-foreground">{s.name}</td>
                      {courses.slice(0, 8).map((c) => (
                        <td key={c.id} className="px-3 py-3 text-center">
                          <StarRating value={Math.round(Math.random() * 5)} />
                        </td>
                      ))}
                      <td className="px-4 py-3 text-center font-bold text-foreground">{s.grade != null ? s.grade.toFixed(1) : '—'}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Tab: Conversas */}
      {activeTab === 'conversas' && (
        <div className="flex flex-col gap-3">
          {filteredSessions.length === 0 ? (
            <Card className="p-8 text-center">
              <span className="material-symbols-outlined text-4xl text-muted-foreground mb-2 block">forum</span>
              <p className="text-muted-foreground">Nenhuma conversa socrática encontrada.</p>
            </Card>
          ) : (
            filteredSessions.map((s) => (
              <Card key={s.id} className="p-4 flex items-center gap-4 hover:border-primary/50 transition-colors">
                <div className="h-10 w-10 rounded-full bg-accent flex items-center justify-center shrink-0">
                  <span className="material-symbols-outlined text-primary text-[20px]">forum</span>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="font-medium text-foreground truncate">{s.student_name}</p>
                    <Badge variant={s.review ? 'success' : 'warning'}>
                      {s.review ? 'Avaliado' : 'Pendente'}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground truncate mt-0.5">
                    {s.content_title ?? 'Sem conteúdo'} · {s.total_messages} mensagens
                  </p>
                </div>
                {s.review && <StarRating value={s.review.rating} />}
                <Button variant="outline" size="sm" onClick={() => navigate(`/session/${s.id}/review`)}>
                  <span className="material-symbols-outlined text-[16px] mr-1">rate_review</span>
                  {s.review ? 'Ver' : 'Avaliar'}
                </Button>
              </Card>
            ))
          )}
        </div>
      )}

      {/* Add Course Modal */}
      {showAddCourse && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="fixed inset-0 bg-black/50" onClick={() => setShowAddCourse(false)} />
          <div className="relative bg-card rounded-xl shadow-xl p-6 w-full max-w-md mx-4" role="dialog" aria-modal="true">
            <h3 className="text-lg font-display font-bold text-foreground mb-4">Adicionar Curso</h3>
            <Input
              label="Título do Curso"
              placeholder="Ex.: Introdução à Inteligência Artificial"
              value={newCourseTitle}
              onChange={(e) => setNewCourseTitle(e.target.value)}
              autoFocus
            />
            <div className="flex justify-end gap-3 mt-6">
              <Button variant="outline" onClick={() => setShowAddCourse(false)}>Cancelar</Button>
              <Button onClick={handleAddCourse} disabled={saving || !newCourseTitle.trim()}>
                {saving ? 'Criando...' : 'Criar Curso'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
