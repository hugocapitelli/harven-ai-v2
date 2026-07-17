// @ts-nocheck
import { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { useAuth } from '../../contexts/AuthContext';
import { disciplinesApi, coursesApi } from '../../services/api';
import { unwrapList } from '../../lib/utils';
import { Button } from '../../components/ui/Button';
import { Card, CardContent, CardHeader } from '../../components/ui/Card';
import { Badge } from '../../components/ui/Badge';
import { Tabs } from '../../components/ui/Tabs';
import { Avatar } from '../../components/ui/Avatar';
import { Progress } from '../../components/ui/Progress';
import { Skeleton, SkeletonCard, SkeletonText } from '../../components/ui/Skeleton';
import { EmptyState } from '../../components/ui/EmptyState';
import { SearchInput } from '../../components/ui/SearchInput';
import { StatCard } from '../../components/ui/StatCard';
import { Input } from '../../components/ui/Input';
import { Modal } from '../../components/ui/Modal';
import { PageHeader } from '../../components/ui/PageHeader';
import type { Discipline, Course } from '../../types';

interface StudentStat {
  id: string;
  name: string;
  email: string;
  avatar_url?: string;
  progress?: number;
  grade?: number;
  sessions_count?: number;
}

// Shape returned by GET /disciplines/{id}/sessions (discipline-wide "Conversas").
// GRD-1: the backend returns user_name + flat rating/review_status (0–10 scale),
// never a nested { review } object; align the interface to that real contract.
interface SessionEntry {
  id: string;
  user_name?: string;
  content_title?: string;
  total_messages: number;
  status: string;
  created_at: string;
  review_status?: string | null;
  rating?: number | null;
}

// GRD-1: composed gradebook shapes (read-only, from GET /disciplines/{id}/gradebook).
interface GradebookCourse {
  course_id: string;
  title?: string;
  avg_rating?: number | null;
  override_grade?: number | null;
  final_grade?: number | null;
}
interface GradebookStudent {
  id: string;
  name?: string;
  ra?: string;
  courses: GradebookCourse[];
  overall_avg?: number | null;
}

const TABS = [
  { id: 'disciplinas', label: 'Disciplinas', icon: 'menu_book' },
  { id: 'alunos', label: 'Alunos', icon: 'group' },
  { id: 'notas', label: 'Quadro de Notas', icon: 'grade' },
  { id: 'conversas', label: 'Conversas', icon: 'forum' },
];

// GRD-1: session ratings are on the 0–10 scale (same as session_reviews.rating
// and the gradebook). Displaying them as 5 stars misrepresented the real value.
function GradeBadge({ value }: { value: number }) {
  return (
    <span className="inline-flex items-center gap-1 text-sm font-bold text-harven-gold">
      <span className="material-symbols-outlined text-[16px] fill-1">grade</span>
      {Number(value).toFixed(1)}
      <span className="text-[11px] font-normal text-muted-foreground">/10</span>
    </span>
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
  // GRD-1: composed grades come read-only from the backend gradebook; there is
  // no local grade state and no "save" — a grade is the mean of the ratings the
  // teacher gives each Socratic session (see StudentGradeDetail drill-down).
  const [gradebook, setGradebook] = useState<Record<string, GradebookStudent>>({});
  const [gradebookLoading, setGradebookLoading] = useState(false);

  // Read-only cell/row accessors over the gradebook payload.
  const courseGrade = (studentId: string, courseId: string): number | null | undefined =>
    gradebook[studentId]?.courses?.find((c) => c.course_id === courseId)?.final_grade;

  const overallGrade = (studentId: string): number | null | undefined =>
    gradebook[studentId]?.overall_avg;

  const fmtGrade = (v: number | null | undefined): string => (v != null ? Number(v).toFixed(1) : '—');

  const openStudent = (studentId: string) => navigate(`/instructor/class/${id}/student/${studentId}`);

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
    // GRD-2: pull the max page so sessions aren't hidden behind the default 20.
    disciplinesApi.getSessions(id, { perPage: 100 }).then((data) => {
      if (!controller.signal.aborted) setSessions(unwrapList(data));
    }).catch(() => {});
    return () => controller.abort();
  }, [activeTab, id]);

  // GRD-1: load composed grades when the Quadro de Notas tab opens.
  useEffect(() => {
    if (activeTab !== 'notas' || !id) return;
    const controller = new AbortController();
    setGradebookLoading(true);
    disciplinesApi.getGradebook(id).then((data) => {
      if (controller.signal.aborted) return;
      const list = (data as { students?: GradebookStudent[] })?.students ?? [];
      const map: Record<string, GradebookStudent> = {};
      for (const s of list) map[s.id] = s;
      setGradebook(map);
    }).catch(() => {
      if (!controller.signal.aborted) toast.error('Erro ao carregar as notas.');
    }).finally(() => {
      if (!controller.signal.aborted) setGradebookLoading(false);
    });
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
  const filteredSessions = filterBySearch(sessions, ['user_name', 'content_title']);

  return (
    <div className="max-w-7xl mx-auto p-8 flex flex-col gap-8 animate-in fade-in duration-500">
      <PageHeader
        title={discipline.name}
        subtitle={discipline.code ? `${discipline.code}${discipline.department ? ' · ' + discipline.department : ''}` : undefined}
        backAction={{ onClick: () => navigate('/instructor') }}
        breadcrumbs={[
          { label: 'Disciplinas', onClick: () => navigate('/instructor') },
          { label: discipline.name },
        ]}
        constrained={false}
      />

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard icon="menu_book" label="Cursos" value={stats.course_count ?? stats.courses_count ?? courses.length} />
        <StatCard icon="group" label="Alunos" value={stats.student_count ?? stats.students_count ?? students.length} />
        <StatCard icon="forum" label="Conversas" value={stats.session_count ?? stats.sessions_count ?? sessions.length} />
        <StatCard icon="trending_up" label="Progresso Médio" value={`${stats.avg_progress ?? 0}%`} variant="highlight" />
      </div>

      {/* Toolbar */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <Tabs items={TABS} activeTab={activeTab} onChange={setActiveTab} ariaLabel="Seções da disciplina" />
        <div className="flex items-center gap-3">
          <SearchInput
            placeholder="Buscar..."
            value={search}
            onChange={setSearch}
            className="w-64"
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
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {filteredCourses.length === 0 ? (
            <Card className="col-span-full">
              <EmptyState
                icon="menu_book"
                title="Nenhum curso encontrado."
                description="Clique em &quot;+ Curso&quot; para criar o primeiro."
              />
            </Card>
          ) : (
            filteredCourses.map((c, idx) => {
              const cardColors = ['bg-harven-dark','bg-[#2a4528]','bg-[#3d6339]','bg-harven-gold','bg-harven-dark'];
              const icons = ['auto_stories','psychology','science','architecture','biotech'];
              return (
                <Card key={c.id} className="overflow-hidden group">
                  {/* Card header */}
                  {c.image_url ? (
                    <div className="h-36 overflow-hidden cursor-pointer" onClick={() => navigate(`/course/${c.id}`)}>
                      <img src={c.image_url} alt="" className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" />
                    </div>
                  ) : (
                    <div
                      className={`h-36 ${cardColors[idx % cardColors.length]} flex items-center justify-center cursor-pointer overflow-hidden hover:opacity-90 transition-opacity`}
                      onClick={() => navigate(`/course/${c.id}`)}
                    >
                      <span className="material-symbols-outlined text-white/25 text-[64px] group-hover:scale-110 transition-transform duration-300">{icons[idx % icons.length]}</span>
                    </div>
                  )}

                  {/* Card body */}
                  <CardContent className="p-5">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1 cursor-pointer" onClick={() => navigate(`/course/${c.id}`)}>
                        <h3 className="text-base font-display font-bold text-foreground leading-tight line-clamp-2 group-hover:text-primary transition-colors">{c.title}</h3>
                        {c.description && (
                          <p className="text-sm text-muted-foreground mt-1.5 line-clamp-2">{c.description}</p>
                        )}
                      </div>
                      <Badge variant={c.status === 'active' || c.status === 'Ativo' ? 'success' : 'outline'} className="shrink-0 mt-0.5">
                        {c.status === 'active' ? 'Ativo' : c.status === 'draft' ? 'Rascunho' : c.status ?? 'Ativo'}
                      </Badge>
                    </div>

                    <div className="flex items-center justify-between mt-4 pt-3 border-t border-border">
                      <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
                        <span className="material-symbols-outlined text-[16px] text-primary">library_books</span>
                        <span className="font-medium text-foreground">{c.chapters_count ?? 0}</span> capítulos
                      </span>

                      {/* Actions */}
                      <div className="flex items-center gap-1">
                        <button
                          onClick={(e) => { e.stopPropagation(); navigate(`/courses/${c.id}/edit`); }}
                          className="p-1.5 rounded-md text-muted-foreground hover:text-primary hover:bg-muted transition-colors"
                          title="Editar curso"
                        >
                          <span className="material-symbols-outlined text-[18px]">edit</span>
                        </button>
                        {/* DELETE /courses é ADMIN-only no backend */}
                        {user?.role === 'ADMIN' && (
                          <button
                            onClick={async (e) => {
                              e.stopPropagation();
                              if (!confirm(`Remover "${c.title}"? Esta ação não pode ser desfeita.`)) return;
                              try {
                                await coursesApi.delete(c.id);
                                toast.success('Curso removido.');
                                const controller = new AbortController();
                                load(controller);
                              } catch { toast.error('Erro ao remover curso.'); }
                            }}
                            className="p-1.5 rounded-md text-muted-foreground hover:text-red-500 hover:bg-red-50 transition-colors"
                            title="Remover curso"
                          >
                            <span className="material-symbols-outlined text-[18px]">delete</span>
                          </button>
                        )}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              );
            })
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
                  <th className="text-left px-4 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Aluno</th>
                  <th className="text-left px-4 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Progresso</th>
                  <th className="text-left px-4 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Nota</th>
                  <th className="text-left px-4 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Sessões</th>
                </tr>
              </thead>
              <tbody>
                {filteredStudents.length === 0 ? (
                  <tr><td colSpan={4} className="px-4 py-8 text-center text-muted-foreground">Nenhum aluno encontrado.</td></tr>
                ) : (
                  filteredStudents.map((s) => (
                    <tr
                      key={s.id}
                      className="border-b border-border last:border-0 hover:bg-muted/50 transition-colors cursor-pointer"
                      onClick={() => openStudent(s.id)}
                      title="Ver sessões e avaliar"
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          <Avatar src={s.avatar_url} fallback={s.name} size="sm" />
                          <div>
                            <p className="font-medium text-foreground hover:text-primary transition-colors">{s.name}</p>
                            <p className="text-xs text-muted-foreground">{s.email}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2 w-32">
                          <Progress value={s.progress ?? 0} className="flex-1" />
                          <span className="text-xs text-muted-foreground">{s.progress ?? 0}%</span>
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

      {/* Tab: Quadro de Notas — read-only, composed from session_reviews.rating.
          A grade is the mean of the ratings the teacher gives each Socratic
          session; there is no direct entry here. Click a student to grade their
          sessions one by one (drill-down). */}
      {activeTab === 'notas' && (
        <Card>
          <div className="px-4 py-2.5 border-b border-border flex items-center gap-2 text-xs text-muted-foreground">
            <span className="material-symbols-outlined text-[16px] text-primary">info</span>
            Notas compostas pela média das avaliações de cada interação socrática. Clique num aluno para avaliar as sessões.
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left px-4 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Aluno</th>
                  {courses.slice(0, 8).map((c) => (
                    <th key={c.id} className="text-center px-3 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wide max-w-[120px] truncate">
                      {c.title}
                    </th>
                  ))}
                  <th className="text-center px-4 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Média</th>
                </tr>
              </thead>
              <tbody>
                {gradebookLoading ? (
                  <tr><td colSpan={courses.slice(0, 8).length + 2} className="px-4 py-8 text-center text-muted-foreground">Carregando notas…</td></tr>
                ) : filteredStudents.length === 0 ? (
                  <tr><td colSpan={courses.slice(0, 8).length + 2} className="px-4 py-8 text-center text-muted-foreground">Nenhum dado disponível.</td></tr>
                ) : (
                  filteredStudents.map((s) => (
                    <tr
                      key={s.id}
                      className="border-b border-border last:border-0 hover:bg-muted/50 cursor-pointer"
                      onClick={() => openStudent(s.id)}
                      title="Ver sessões e avaliar"
                    >
                      <td className="px-4 py-3 font-medium text-foreground">
                        <span className="inline-flex items-center gap-1.5 hover:text-primary transition-colors">
                          {s.name}
                          <span className="material-symbols-outlined text-[16px] opacity-40">chevron_right</span>
                        </span>
                      </td>
                      {courses.slice(0, 8).map((c) => (
                        <td key={c.id} className="px-3 py-3 text-center text-foreground">
                          {fmtGrade(courseGrade(s.id, c.id))}
                        </td>
                      ))}
                      <td className="px-4 py-3 text-center font-bold text-foreground">{fmtGrade(overallGrade(s.id))}</td>
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
            <Card>
              <EmptyState
                icon="forum"
                title="Nenhuma conversa socrática encontrada."
              />
            </Card>
          ) : (
            filteredSessions.map((s) => (
              <Card key={s.id} className="p-4 flex items-center gap-4 hover:border-primary/50 transition-colors">
                <div className="h-10 w-10 rounded-full bg-accent flex items-center justify-center shrink-0">
                  <span className="material-symbols-outlined text-primary text-[20px]">forum</span>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="font-medium text-foreground truncate">{s.user_name}</p>
                    <Badge variant={s.rating != null ? 'success' : 'warning'}>
                      {s.rating != null ? 'Avaliado' : 'Pendente'}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground truncate mt-0.5">
                    {s.content_title ?? 'Sem conteúdo'} · {s.total_messages} mensagens
                  </p>
                </div>
                {s.rating != null && <GradeBadge value={s.rating} />}
                <Button variant="outline" size="sm" onClick={() => navigate(`/session/${s.id}/review`)}>
                  <span className="material-symbols-outlined text-[16px] mr-1">rate_review</span>
                  {s.rating != null ? 'Ver' : 'Avaliar'}
                </Button>
              </Card>
            ))
          )}
        </div>
      )}

      {/* Add Course Modal */}
      <Modal.Root open={showAddCourse} onClose={() => setShowAddCourse(false)} size="md">
        <Modal.Header title="Adicionar Curso" onClose={() => setShowAddCourse(false)} />
        <Modal.Body>
          <Input
            label="Título do Curso"
            placeholder="Ex.: Introdução à Inteligência Artificial"
            value={newCourseTitle}
            onChange={(e) => setNewCourseTitle(e.target.value)}
            autoFocus
          />
        </Modal.Body>
        <Modal.Footer>
          <Button variant="outline" onClick={() => setShowAddCourse(false)}>Cancelar</Button>
          <Button onClick={handleAddCourse} disabled={saving || !newCourseTitle.trim()}>
            {saving ? 'Criando...' : 'Criar Curso'}
          </Button>
        </Modal.Footer>
      </Modal.Root>
    </div>
  );
}
