// @ts-nocheck
import { useState, useEffect, useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { disciplinesApi } from '../../services/api';
import { unwrapList } from '../../lib/utils';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Badge } from '../../components/ui/Badge';
import { Skeleton } from '../../components/ui/Skeleton';
import { EmptyState } from '../../components/ui/EmptyState';
import { PageHeader } from '../../components/ui/PageHeader';

// GRD-1 drill-down: the professor's view of ONE student inside a discipline.
// Lists the student's Socratic sessions grouped by course -> chapter, each with
// the current per-session rating and an action to read the conversation and
// grade it (reusing the existing /session/:sessionId/review screen — never
// duplicated). The composed course/overall grade lives in the gradebook and is
// summarised here as read-only context.

interface SessionEntry {
  id: string;
  user_id: string;
  user_name?: string;
  content_id?: string;
  content_title?: string;
  chapter_id?: string | null;
  chapter_title?: string;
  course_id?: string | null;
  course_title?: string;
  status?: string;
  total_messages?: number;
  review_status?: string | null;
  rating?: number | null;
  created_at?: string;
}

interface CourseGrade {
  course_id: string;
  title?: string;
  avg_rating?: number | null;
  override_grade?: number | null;
  final_grade?: number | null;
}

const fmtGrade = (v?: number | null) => (v != null ? Number(v).toFixed(1) : '—');

export default function StudentGradeDetail() {
  const { id, studentId } = useParams<{ id: string; studentId: string }>();
  const navigate = useNavigate();

  const [sessions, setSessions] = useState<SessionEntry[]>([]);
  const [courseGrades, setCourseGrades] = useState<CourseGrade[]>([]);
  const [overallAvg, setOverallAvg] = useState<number | null>(null);
  const [studentName, setStudentName] = useState<string>('');
  const [loading, setLoading] = useState(true);

  const loadAll = async (controller: AbortController) => {
    if (!id || !studentId) return;
    try {
      setLoading(true);
      const [sessionsRes, gradebook] = await Promise.all([
        disciplinesApi.getSessions(id, { studentId }),
        disciplinesApi.getGradebook(id).catch(() => null),
      ]);
      if (controller.signal.aborted) return;

      const rows = unwrapList<SessionEntry>(sessionsRes);
      setSessions(rows);
      if (rows[0]?.user_name) setStudentName(rows[0].user_name);

      const students = (gradebook as { students?: any[] } | null)?.students ?? [];
      const me = students.find((s) => s.id === studentId);
      if (me) {
        setCourseGrades(me.courses ?? []);
        setOverallAvg(me.overall_avg ?? null);
        if (me.name) setStudentName(me.name);
      }
    } catch (err) {
      if (controller.signal.aborted) return;
      console.error('Error loading student grade detail:', err);
      toast.error('Erro ao carregar o perfil do aluno.');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    loadAll(controller);
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, studentId]);

  const gradeByCourse = useMemo(() => {
    const m: Record<string, CourseGrade> = {};
    for (const c of courseGrades) m[c.course_id] = c;
    return m;
  }, [courseGrades]);

  // Group sessions: course -> chapter -> sessions[]
  const grouped = useMemo(() => {
    const byCourse: Record<string, { courseId: string; title: string; chapters: Record<string, { chapterId: string; title: string; items: SessionEntry[] }> }> = {};
    for (const s of sessions) {
      const courseId = s.course_id ?? '__none__';
      const courseTitle = s.course_title ?? 'Sem curso';
      const chapterId = s.chapter_id ?? '__none__';
      const chapterTitle = s.chapter_title ?? 'Sem capítulo';
      if (!byCourse[courseId]) byCourse[courseId] = { courseId, title: courseTitle, chapters: {} };
      if (!byCourse[courseId].chapters[chapterId]) byCourse[courseId].chapters[chapterId] = { chapterId, title: chapterTitle, items: [] };
      byCourse[courseId].chapters[chapterId].items.push(s);
    }
    return Object.values(byCourse);
  }, [sessions]);

  if (loading) {
    return (
      <div className="max-w-5xl mx-auto p-8 flex flex-col gap-6">
        <Skeleton className="h-32 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto p-8 flex flex-col gap-6 animate-in fade-in duration-500">
      <PageHeader
        title={studentName || 'Aluno'}
        subtitle="Perfil de avaliação socrática · notas compostas por interação"
        backAction={{ onClick: () => navigate(`/instructor/class/${id}`) }}
        breadcrumbs={[
          { label: 'Disciplinas', onClick: () => navigate('/instructor') },
          { label: 'Turma', onClick: () => navigate(`/instructor/class/${id}`) },
          { label: studentName || 'Aluno' },
        ]}
        actions={
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Média geral</span>
            <Badge variant={overallAvg != null ? 'success' : 'outline'} className="text-sm font-bold">{fmtGrade(overallAvg)}</Badge>
          </div>
        }
        constrained={false}
      />

      {grouped.length === 0 ? (
        <Card>
          <EmptyState
            icon="forum"
            title="Nenhuma sessão socrática deste aluno."
            description="As notas se compõem à medida que o aluno realiza interações e você as avalia."
          />
        </Card>
      ) : (
        grouped.map((course) => {
          const g = gradeByCourse[course.courseId];
          return (
            <Card key={course.courseId} className="overflow-hidden">
              <div className="flex items-center justify-between px-5 py-3 border-b border-border bg-muted/30">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="material-symbols-outlined text-[18px] text-primary">menu_book</span>
                  <h3 className="font-display font-bold text-foreground truncate">{course.title}</h3>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="text-[11px] text-muted-foreground uppercase tracking-wide">Nota do curso</span>
                  <Badge variant={g?.final_grade != null ? 'success' : 'outline'} className="font-bold">
                    {fmtGrade(g?.final_grade)}
                  </Badge>
                </div>
              </div>

              {Object.values(course.chapters).map((chapter) => (
                <div key={chapter.chapterId}>
                  <p className="px-5 pt-3 pb-1 text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
                    {chapter.title}
                  </p>
                  <div className="divide-y divide-border">
                    {chapter.items.map((s) => (
                      <div key={s.id} className="flex items-center gap-4 px-5 py-3 hover:bg-muted/40 transition-colors">
                        <div className="h-9 w-9 rounded-full bg-accent flex items-center justify-center shrink-0">
                          <span className="material-symbols-outlined text-primary text-[18px]">forum</span>
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-foreground truncate">{s.content_title ?? 'Sem conteúdo'}</p>
                          <p className="text-xs text-muted-foreground mt-0.5">
                            {s.total_messages ?? 0} mensagens
                            {s.status ? ` · ${s.status}` : ''}
                          </p>
                        </div>
                        <div className="flex items-center gap-1.5 shrink-0">
                          <span className="text-[11px] text-muted-foreground uppercase tracking-wide">Nota</span>
                          <Badge variant={s.rating != null ? 'success' : 'warning'} className="font-bold">
                            {s.rating != null ? Number(s.rating).toFixed(1) : '—'}
                          </Badge>
                        </div>
                        <Button variant="outline" size="sm" onClick={() => navigate(`/session/${s.id}/review`)}>
                          <span className="material-symbols-outlined text-[16px] mr-1">rate_review</span>
                          {s.rating != null ? 'Rever' : 'Avaliar'}
                        </Button>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </Card>
          );
        })
      )}
    </div>
  );
}
