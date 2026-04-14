// @ts-nocheck
import { useState, useEffect, useCallback, useRef } from 'react';
import { toast } from 'sonner';
import { disciplinesApi, coursesApi, usersApi } from '../../services/api';
import { Button } from '../../components/ui/Button';
import { Card, CardContent } from '../../components/ui/Card';
import { Input } from '../../components/ui/Input';
import { Badge } from '../../components/ui/Badge';
import { Tabs } from '../../components/ui/Tabs';
import { Avatar } from '../../components/ui/Avatar';
import { Skeleton, SkeletonCard } from '../../components/ui/Skeleton';
import type { Discipline, Course, User } from '../../types';

type ViewMode = 'grid' | 'list';
type EditTab = 'info' | 'materials' | 'teachers' | 'students';

interface EditState {
  open: boolean;
  discipline: Discipline | null;
  tab: EditTab;
}

const EDIT_TABS = [
  { id: 'info', label: 'Info', icon: 'info' },
  { id: 'materials', label: 'Materiais', icon: 'menu_book' },
  { id: 'teachers', label: 'Professores', icon: 'school' },
  { id: 'students', label: 'Alunos', icon: 'group' },
];

export default function ClassManagement() {
  const [disciplines, setDisciplines] = useState<Discipline[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [viewMode, setViewMode] = useState<ViewMode>('grid');
  const [editState, setEditState] = useState<EditState>({ open: false, discipline: null, tab: 'info' });
  const [saving, setSaving] = useState(false);

  // Edit form state
  const [editForm, setEditForm] = useState({ title: '', code: '', department: '' });
  const [courses, setCourses] = useState<Course[]>([]);
  const [teachers, setTeachers] = useState<User[]>([]);
  const [students, setStudents] = useState<User[]>([]);
  const [allUsers, setAllUsers] = useState<User[]>([]);
  const [userSearch, setUserSearch] = useState('');
  const [confirmAction, setConfirmAction] = useState<{ type: string; id: string; label: string } | null>(null);
  const csvRef = useRef<HTMLInputElement>(null);

  const loadDisciplines = useCallback(async (controller: AbortController) => {
    try {
      setLoading(true);
      const data = await disciplinesApi.list();
      if (controller.signal.aborted) return;
      setDisciplines(Array.isArray(data) ? data : []);
    } catch {
      if (controller.signal.aborted) return;
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    loadDisciplines(controller);
    return () => controller.abort();
  }, [loadDisciplines]);

  const openEdit = async (disc: Discipline) => {
    setEditForm({ title: disc.title, code: disc.code ?? '', department: disc.department ?? '' });
    setEditState({ open: true, discipline: disc, tab: 'info' });
    try {
      const [c, t, s, u] = await Promise.all([
        coursesApi.listByClass(disc.id).catch(() => []),
        disciplinesApi.getTeachers(disc.id).catch(() => []),
        disciplinesApi.getStudents(disc.id).catch(() => []),
        usersApi.list().catch(() => []),
      ]);
      setCourses(Array.isArray(c) ? c : []);
      setTeachers(Array.isArray(t) ? t : []);
      setStudents(Array.isArray(s) ? s : []);
      setAllUsers(Array.isArray(u) ? u : []);
    } catch {}
  };

  const handleSaveInfo = async () => {
    if (!editState.discipline) return;
    setSaving(true);
    try {
      await disciplinesApi.update(editState.discipline.id, editForm as Record<string, unknown>);
      toast.success('Turma atualizada.');
      const controller = new AbortController();
      loadDisciplines(controller);
    } catch { toast.error('Erro ao salvar.'); }
    finally { setSaving(false); }
  };

  const handleCreate = async () => {
    setSaving(true);
    try {
      const created = await disciplinesApi.create({ title: 'Nova Turma', code: '', department: '' });
      toast.success('Turma criada.');
      const disc = created as Discipline;
      openEdit(disc);
      const controller = new AbortController();
      loadDisciplines(controller);
    } catch { toast.error('Erro ao criar turma.'); }
    finally { setSaving(false); }
  };

  const handleAddTeacher = async (userId: string) => {
    if (!editState.discipline) return;
    try {
      await disciplinesApi.addTeacher(editState.discipline.id, userId);
      const user = allUsers.find((u) => u.id === userId);
      if (user) setTeachers((prev) => [...prev, user]);
      toast.success('Professor adicionado.');
    } catch { toast.error('Erro ao adicionar professor.'); }
  };

  const handleRemoveTeacher = async (userId: string) => {
    if (!editState.discipline) return;
    try {
      await disciplinesApi.removeTeacher(editState.discipline.id, userId);
      setTeachers((prev) => prev.filter((t) => t.id !== userId));
      toast.success('Professor removido.');
      setConfirmAction(null);
    } catch { toast.error('Erro ao remover.'); }
  };

  const handleAddStudent = async (userId: string) => {
    if (!editState.discipline) return;
    try {
      await disciplinesApi.addStudent(editState.discipline.id, userId);
      const user = allUsers.find((u) => u.id === userId);
      if (user) setStudents((prev) => [...prev, user]);
      toast.success('Aluno adicionado.');
    } catch { toast.error('Erro ao adicionar aluno.'); }
  };

  const handleRemoveStudent = async (userId: string) => {
    if (!editState.discipline) return;
    try {
      await disciplinesApi.removeStudent(editState.discipline.id, userId);
      setStudents((prev) => prev.filter((s) => s.id !== userId));
      toast.success('Aluno removido.');
      setConfirmAction(null);
    } catch { toast.error('Erro ao remover.'); }
  };

  const handleCsvStudents = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !editState.discipline) return;
    const text = await file.text();
    const ras = text.trim().split('\n').slice(1).map((l) => l.split(',')[0]?.trim()).filter(Boolean);
    if (ras.length === 0) { toast.error('CSV vazio.'); return; }
    setSaving(true);
    try {
      await disciplinesApi.addStudentsBatch(editState.discipline.id, ras.map((ra) => ({ ra })) as Record<string, unknown>[]);
      toast.success(`${ras.length} alunos importados.`);
      const s = await disciplinesApi.getStudents(editState.discipline.id);
      setStudents(Array.isArray(s) ? s : []);
    } catch { toast.error('Erro na importação.'); }
    finally { setSaving(false); if (csvRef.current) csvRef.current.value = ''; }
  };

  const handleDeleteCourse = async (courseId: string) => {
    try {
      await coursesApi.delete(courseId);
      setCourses((prev) => prev.filter((c) => c.id !== courseId));
      toast.success('Curso excluído.');
      setConfirmAction(null);
    } catch { toast.error('Erro ao excluir.'); }
  };

  const filtered = disciplines.filter(
    (d) => d.title.toLowerCase().includes(search.toLowerCase()) || (d.code ?? '').toLowerCase().includes(search.toLowerCase()),
  );

  const availableTeachers = allUsers.filter(
    (u) => u.role === 'INSTRUCTOR' && !teachers.some((t) => t.id === u.id) && u.name.toLowerCase().includes(userSearch.toLowerCase()),
  );

  const availableStudents = allUsers.filter(
    (u) => u.role === 'STUDENT' && !students.some((s) => s.id === u.id) && u.name.toLowerCase().includes(userSearch.toLowerCase()),
  );

  return (
    <div className="max-w-7xl mx-auto p-8 flex flex-col gap-6 animate-in fade-in duration-500">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-display font-bold text-foreground">Gestão de Turmas</h1>
          <p className="text-sm text-muted-foreground mt-1">{loading ? '...' : `${filtered.length} turma(s)`}</p>
        </div>
        <Button onClick={handleCreate} disabled={saving}>
          <span className="material-symbols-outlined text-[18px] mr-2">add</span> Nova Turma
        </Button>
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-3">
        <Input icon="search" placeholder="Buscar turma..." value={search} onChange={(e) => setSearch(e.target.value)} containerClassName="flex-1 max-w-sm" />
        <div className="flex border border-border rounded-lg overflow-hidden">
          <button onClick={() => setViewMode('grid')} className={`p-2 ${viewMode === 'grid' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'}`}>
            <span className="material-symbols-outlined text-[20px]">grid_view</span>
          </button>
          <button onClick={() => setViewMode('list')} className={`p-2 ${viewMode === 'list' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'}`}>
            <span className="material-symbols-outlined text-[20px]">view_list</span>
          </button>
        </div>
      </div>

      {/* Grid / List */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">{Array.from({ length: 6 }).map((_, i) => <SkeletonCard key={i} />)}</div>
      ) : filtered.length === 0 ? (
        <Card className="p-12 text-center">
          <span className="material-symbols-outlined text-5xl text-muted-foreground mb-3 block">school</span>
          <p className="text-muted-foreground">{search ? 'Nenhuma turma encontrada.' : 'Nenhuma turma cadastrada.'}</p>
        </Card>
      ) : viewMode === 'grid' ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((d) => (
            <Card key={d.id} hoverEffect onClick={() => openEdit(d)}>
              <CardContent className="flex flex-col gap-2">
                <div className="flex items-center gap-2">
                  <div className="h-10 w-10 rounded-lg bg-accent flex items-center justify-center">
                    <span className="material-symbols-outlined text-primary text-[20px]">{d.icon ?? 'school'}</span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="font-display font-bold text-foreground truncate">{d.title}</h3>
                    <p className="text-xs text-muted-foreground">{d.code ?? '—'}</p>
                  </div>
                </div>
                <div className="flex gap-3 text-xs text-muted-foreground">
                  <span className="inline-flex items-center gap-1"><span className="material-symbols-outlined text-[14px]">menu_book</span>{d.courses_count ?? 0}</span>
                  <span className="inline-flex items-center gap-1"><span className="material-symbols-outlined text-[14px]">group</span>{d.students ?? 0}</span>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {filtered.map((d) => (
            <Card key={d.id} hoverEffect onClick={() => openEdit(d)} className="flex items-center gap-4 p-4">
              <div className="h-10 w-10 rounded-lg bg-accent flex items-center justify-center shrink-0">
                <span className="material-symbols-outlined text-primary">{d.icon ?? 'school'}</span>
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="font-display font-bold text-foreground truncate">{d.title}</h3>
                <p className="text-xs text-muted-foreground">{d.code ?? '—'} · {d.department ?? '—'}</p>
              </div>
              <span className="text-xs text-muted-foreground">{d.courses_count ?? 0} cursos · {d.students ?? 0} alunos</span>
              <span className="material-symbols-outlined text-muted-foreground">chevron_right</span>
            </Card>
          ))}
        </div>
      )}

      {/* Edit Modal */}
      {editState.open && editState.discipline && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="fixed inset-0 bg-black/50" onClick={() => setEditState({ open: false, discipline: null, tab: 'info' })} />
          <div className="relative bg-card rounded-xl shadow-xl w-full max-w-3xl mx-4 max-h-[85vh] flex flex-col" role="dialog" aria-modal="true">
            <div className="p-6 border-b border-border flex items-center justify-between shrink-0">
              <h3 className="text-lg font-display font-bold text-foreground">{editState.discipline.title}</h3>
              <Button variant="ghost" size="icon" onClick={() => setEditState({ open: false, discipline: null, tab: 'info' })}>
                <span className="material-symbols-outlined">close</span>
              </Button>
            </div>

            <div className="px-6 pt-4 shrink-0">
              <Tabs items={EDIT_TABS} activeTab={editState.tab} onChange={(t) => { setEditState((s) => ({ ...s, tab: t as EditTab })); setUserSearch(''); }} />
            </div>

            <div className="flex-1 overflow-y-auto p-6">
              {/* Tab: Info */}
              {editState.tab === 'info' && (
                <div className="flex flex-col gap-4 max-w-md">
                  <Input label="Nome" value={editForm.title} onChange={(e) => setEditForm((f) => ({ ...f, title: e.target.value }))} />
                  <Input label="Código" value={editForm.code} onChange={(e) => setEditForm((f) => ({ ...f, code: e.target.value }))} />
                  <Input label="Departamento" value={editForm.department} onChange={(e) => setEditForm((f) => ({ ...f, department: e.target.value }))} />
                  <Button onClick={handleSaveInfo} disabled={saving}>{saving ? 'Salvando...' : 'Salvar'}</Button>
                </div>
              )}

              {/* Tab: Materials */}
              {editState.tab === 'materials' && (
                <div className="flex flex-col gap-3">
                  <div className="flex justify-between items-center">
                    <p className="text-sm font-bold text-foreground">{courses.length} curso(s)</p>
                    <Button size="sm" onClick={async () => {
                      try {
                        await coursesApi.create({ title: 'Novo Curso', discipline_id: editState.discipline!.id } as Record<string, unknown>);
                        const c = await coursesApi.listByClass(editState.discipline!.id);
                        setCourses(Array.isArray(c) ? c : []);
                        toast.success('Curso criado.');
                      } catch { toast.error('Erro.'); }
                    }}>
                      <span className="material-symbols-outlined text-[16px] mr-1">add</span> Curso
                    </Button>
                  </div>
                  {courses.map((c) => (
                    <Card key={c.id} className="flex items-center gap-3 p-3">
                      <span className="material-symbols-outlined text-muted-foreground">auto_stories</span>
                      <span className="flex-1 text-sm font-medium text-foreground truncate">{c.title}</span>
                      <Button variant="destructive" size="icon" onClick={() => setConfirmAction({ type: 'delete-course', id: c.id, label: c.title })}>
                        <span className="material-symbols-outlined text-[16px]">delete</span>
                      </Button>
                    </Card>
                  ))}
                </div>
              )}

              {/* Tab: Teachers */}
              {editState.tab === 'teachers' && (
                <div className="flex flex-col gap-4">
                  <Input icon="search" placeholder="Buscar professor..." value={userSearch} onChange={(e) => setUserSearch(e.target.value)} />
                  {userSearch && availableTeachers.length > 0 && (
                    <div className="border border-border rounded-lg max-h-40 overflow-y-auto">
                      {availableTeachers.slice(0, 10).map((u) => (
                        <button key={u.id} onClick={() => handleAddTeacher(u.id)} className="flex items-center gap-2 w-full px-3 py-2 text-sm hover:bg-muted transition-colors">
                          <Avatar fallback={u.name} size="sm" src={u.avatar_url} />
                          <span className="text-foreground">{u.name}</span>
                          <span className="material-symbols-outlined text-primary ml-auto text-[18px]">add</span>
                        </button>
                      ))}
                    </div>
                  )}
                  <div className="flex flex-col gap-2">
                    {teachers.map((t) => (
                      <Card key={t.id} className="flex items-center gap-3 p-3">
                        <Avatar fallback={t.name} size="sm" src={t.avatar_url} />
                        <div className="flex-1"><p className="text-sm font-medium text-foreground">{t.name}</p><p className="text-xs text-muted-foreground">{t.email}</p></div>
                        <Button variant="destructive" size="icon" onClick={() => setConfirmAction({ type: 'remove-teacher', id: t.id, label: t.name })}>
                          <span className="material-symbols-outlined text-[16px]">close</span>
                        </Button>
                      </Card>
                    ))}
                    {teachers.length === 0 && <p className="text-sm text-muted-foreground text-center py-4">Nenhum professor vinculado.</p>}
                  </div>
                </div>
              )}

              {/* Tab: Students */}
              {editState.tab === 'students' && (
                <div className="flex flex-col gap-4">
                  <div className="flex gap-2">
                    <Input icon="search" placeholder="Buscar aluno..." value={userSearch} onChange={(e) => setUserSearch(e.target.value)} containerClassName="flex-1" />
                    <input ref={csvRef} type="file" accept=".csv" className="hidden" onChange={handleCsvStudents} />
                    <Button variant="outline" size="sm" onClick={() => csvRef.current?.click()}>
                      <span className="material-symbols-outlined text-[16px] mr-1">upload_file</span> CSV
                    </Button>
                  </div>
                  {userSearch && availableStudents.length > 0 && (
                    <div className="border border-border rounded-lg max-h-40 overflow-y-auto">
                      {availableStudents.slice(0, 10).map((u) => (
                        <button key={u.id} onClick={() => handleAddStudent(u.id)} className="flex items-center gap-2 w-full px-3 py-2 text-sm hover:bg-muted transition-colors">
                          <Avatar fallback={u.name} size="sm" src={u.avatar_url} />
                          <span className="text-foreground">{u.name}</span>
                          <span className="material-symbols-outlined text-primary ml-auto text-[18px]">add</span>
                        </button>
                      ))}
                    </div>
                  )}
                  <div className="flex flex-col gap-2">
                    {students.map((s) => (
                      <Card key={s.id} className="flex items-center gap-3 p-3">
                        <Avatar fallback={s.name} size="sm" src={s.avatar_url} />
                        <div className="flex-1"><p className="text-sm font-medium text-foreground">{s.name}</p><p className="text-xs text-muted-foreground">{s.email}</p></div>
                        <Button variant="destructive" size="icon" onClick={() => setConfirmAction({ type: 'remove-student', id: s.id, label: s.name })}>
                          <span className="material-symbols-outlined text-[16px]">close</span>
                        </Button>
                      </Card>
                    ))}
                    {students.length === 0 && <p className="text-sm text-muted-foreground text-center py-4">Nenhum aluno vinculado.</p>}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Confirm Dialog */}
      {confirmAction && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center">
          <div className="fixed inset-0 bg-black/50" onClick={() => setConfirmAction(null)} />
          <div className="relative bg-card rounded-xl shadow-xl p-6 w-full max-w-sm mx-4" role="alertdialog" aria-modal="true">
            <h3 className="text-lg font-bold text-foreground mb-2">Confirmar</h3>
            <p className="text-sm text-muted-foreground mb-6">
              {confirmAction.type === 'delete-course' && `Excluir o curso "${confirmAction.label}"? Essa ação não pode ser desfeita.`}
              {confirmAction.type === 'remove-teacher' && `Remover ${confirmAction.label} como professor?`}
              {confirmAction.type === 'remove-student' && `Remover ${confirmAction.label} da turma?`}
            </p>
            <div className="flex justify-end gap-3">
              <Button variant="outline" onClick={() => setConfirmAction(null)}>Cancelar</Button>
              <Button
                variant="destructive"
                onClick={() => {
                  if (confirmAction.type === 'delete-course') handleDeleteCourse(confirmAction.id);
                  else if (confirmAction.type === 'remove-teacher') handleRemoveTeacher(confirmAction.id);
                  else if (confirmAction.type === 'remove-student') handleRemoveStudent(confirmAction.id);
                }}
              >
                Confirmar
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
