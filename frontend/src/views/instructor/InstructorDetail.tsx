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

interface SessionEntry {
  id: string;
  student_name: string;
  content_title?: string;
  total_messages: number;
  status: string;
  created_at: string;
  review?: { rating: number; status: string } | null;
}

// Grade key: "studentId::courseId"
type GradeMap = Record<string, number | undefined>;

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
  const [grades, setGrades] = useState<GradeMap>({});
  const [dirtyGrades, setDirtyGrades] = useState<Set<string>>(new Set());

  const gradeKey = (studentId: string, courseId: string) => `${studentId}::${courseId}`;

  const getGrade = (studentId: string, courseId: string): number | undefined =>
    grades[gradeKey(studentId, courseId)];

  const handleGradeChange = (studentId: string, courseId: string, value: number) => {
    const key = gradeKey(studentId, courseId);
    const clamped = Number.isNaN(value) ? undefined : Math.min(10, Math.max(0, value));
    setGrades((prev) => ({ ...prev, [key]: clamped }));
    setDirtyGrades((prev) => new Set(prev).add(key));
  };

  const computeAverage = (studentId: string): string => {
    const vals = courses.slice(0, 8).map((c) => getGrade(studentId, c.id)).filter((v): v is number => v != null);
    if (vals.length === 0) return '—';
    return (vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(1);
  };

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

      {/* Tab: Quadro de Notas */}
      {activeTab === 'notas' && (
        <Card>
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
                {filteredStudents.length === 0 ? (
                  <tr><td colSpan={courses.slice(0, 8).length + 2} className="px-4 py-8 text-center text-muted-foreground">Nenhum dado disponível.</td></tr>
                ) : (
                  filteredStudents.map((s) => (
                    <tr key={s.id} className="border-b border-border last:border-0 hover:bg-muted/50">
                      <td className="px-4 py-3 font-medium text-foreground">{s.name}</td>
                      {courses.slice(0, 8).map((c) => (
                        <td key={c.id} className="px-3 py-3 text-center">
                          <input
                            type="number"
                            min="0"
                            max="10"
                            step="0.5"
                            value={getGrade(s.id, c.id) ?? ''}
                            onChange={(e) => handleGradeChange(s.id, c.id, parseFloat(e.target.value))}
                            className="w-16 text-center border border-harven-border rounded px-2 py-1 text-sm bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                            placeholder="—"
                          />
                        </td>
                      ))}
                      <td className="px-4 py-3 text-center font-bold text-foreground">{computeAverage(s.id)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          {dirtyGrades.size > 0 && (
            <div className="flex items-center justify-end gap-3 px-4 py-3 border-t border-border">
              <span className="text-xs text-muted-foreground">{dirtyGrades.size} nota{dirtyGrades.size !== 1 ? 's' : ''} alterada{dirtyGrades.size !== 1 ? 's' : ''}</span>
              <Button size="sm" onClick={() => { setDirtyGrades(new Set()); toast.success('Notas salvas localmente.'); }}>
                <span className="material-symbols-outlined text-[16px] mr-1">save</span> Salvar Notas
              </Button>
            </div>
          )}
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
