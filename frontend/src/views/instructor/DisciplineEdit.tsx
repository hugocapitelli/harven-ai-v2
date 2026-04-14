// @ts-nocheck
import { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { disciplinesApi, coursesApi } from '../../services/api';
import { Button } from '../../components/ui/Button';
import { Card, CardContent, CardHeader } from '../../components/ui/Card';
import { Input } from '../../components/ui/Input';
import { Badge } from '../../components/ui/Badge';
import { Skeleton, SkeletonText } from '../../components/ui/Skeleton';
import type { Discipline, Course } from '../../types';

type SidebarTab = 'materials' | 'settings';

interface CourseForm {
  title: string;
  description: string;
}

const EMPTY_COURSE: CourseForm = { title: '', description: '' };

export default function DisciplineEdit() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const isNew = id === 'new';

  const [discipline, setDiscipline] = useState<Partial<Discipline>>({ title: '', code: '', department: '', image: '' });
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>('materials');
  const [courseModal, setCourseModal] = useState<{ open: boolean; editing: Course | null }>({ open: false, editing: null });
  const [courseForm, setCourseForm] = useState<CourseForm>(EMPTY_COURSE);
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const loadData = useCallback(async (controller: AbortController) => {
    if (isNew || !id) return;
    try {
      setLoading(true);
      const [disc, courseList] = await Promise.all([
        disciplinesApi.get(id),
        coursesApi.listByClass(id).catch(() => []),
      ]);
      if (controller.signal.aborted) return;
      setDiscipline(disc);
      setCourses(Array.isArray(courseList) ? courseList : []);
      if (disc.image) setImagePreview(disc.image);
    } catch {
      if (controller.signal.aborted) return;
      toast.error('Erro ao carregar disciplina.');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [id, isNew]);

  useEffect(() => {
    const controller = new AbortController();
    loadData(controller);
    return () => controller.abort();
  }, [loadData]);

  const handleSaveDiscipline = async () => {
    if (!discipline.title?.trim()) { toast.error('Título é obrigatório.'); return; }
    setSaving(true);
    try {
      if (isNew) {
        const created = await disciplinesApi.create(discipline as Record<string, unknown>);
        toast.success('Disciplina criada.');
        navigate(`/instructor/discipline/${created.id}`, { replace: true });
      } else if (id) {
        await disciplinesApi.update(id, discipline as Record<string, unknown>);
        toast.success('Disciplina atualizada.');
      }
    } catch {
      toast.error('Erro ao salvar.');
    } finally {
      setSaving(false);
    }
  };

  const handleImageChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImageFile(file);
    setImagePreview(URL.createObjectURL(file));
  };

  const handleSaveCourse = async () => {
    if (!courseForm.title.trim()) { toast.error('Título obrigatório.'); return; }
    setSaving(true);
    try {
      if (courseModal.editing) {
        await coursesApi.update(courseModal.editing.id, courseForm as Record<string, unknown>);
        toast.success('Curso atualizado.');
      } else if (id) {
        await coursesApi.create({ ...courseForm, discipline_id: id } as Record<string, unknown>);
        toast.success('Curso criado.');
      }
      setCourseModal({ open: false, editing: null });
      setCourseForm(EMPTY_COURSE);
      const controller = new AbortController();
      loadData(controller);
    } catch {
      toast.error('Erro ao salvar curso.');
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteCourse = async (courseId: string) => {
    try {
      await coursesApi.delete(courseId);
      toast.success('Curso excluído.');
      setCourses((prev) => prev.filter((c) => c.id !== courseId));
      setConfirmDelete(null);
    } catch {
      toast.error('Erro ao excluir curso.');
    }
  };

  const openEditCourse = (course: Course) => {
    setCourseForm({ title: course.title, description: course.description ?? '' });
    setCourseModal({ open: true, editing: course });
  };

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto p-8 grid grid-cols-[240px_1fr] gap-6">
        <div className="flex flex-col gap-2"><Skeleton className="h-10 w-full" /><Skeleton className="h-10 w-full" /></div>
        <div className="flex flex-col gap-4"><Skeleton className="h-8 w-48" /><SkeletonText lines={8} /></div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto p-8 animate-in fade-in duration-500">
      {/* Top bar */}
      <div className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" onClick={() => navigate(-1)}>
            <span className="material-symbols-outlined">arrow_back</span>
          </Button>
          <div>
            <h1 className="text-xl font-display font-bold text-foreground">{isNew ? 'Nova Disciplina' : discipline.title}</h1>
            {discipline.code && <p className="text-xs text-muted-foreground">{discipline.code}</p>}
          </div>
        </div>
        <Button onClick={handleSaveDiscipline} disabled={saving}>
          {saving ? 'Salvando...' : 'Salvar'}
        </Button>
      </div>

      <div className="grid grid-cols-[220px_1fr] gap-8">
        {/* Sidebar */}
        <nav className="flex flex-col gap-1">
          {[
            { id: 'materials' as SidebarTab, icon: 'menu_book', label: 'Materiais' },
            { id: 'settings' as SidebarTab, icon: 'settings', label: 'Configurações' },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setSidebarTab(tab.id)}
              className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                sidebarTab === tab.id ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'
              }`}
            >
              <span className="material-symbols-outlined text-[18px]">{tab.icon}</span>
              {tab.label}
            </button>
          ))}
        </nav>

        {/* Content */}
        <div>
          {sidebarTab === 'materials' && (
            <div className="flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-display font-bold text-foreground">Cursos</h2>
                <Button size="sm" onClick={() => { setCourseForm(EMPTY_COURSE); setCourseModal({ open: true, editing: null }); }}>
                  <span className="material-symbols-outlined text-[16px] mr-1">add</span> Novo Curso
                </Button>
              </div>

              {courses.length === 0 ? (
                <Card className="p-8 text-center">
                  <span className="material-symbols-outlined text-4xl text-muted-foreground mb-2 block">menu_book</span>
                  <p className="text-muted-foreground">Nenhum curso nesta disciplina.</p>
                </Card>
              ) : (
                <div className="flex flex-col gap-3">
                  {courses.map((c) => (
                    <Card key={c.id} className="flex items-center gap-4 p-4">
                      <div className="h-12 w-12 rounded-lg bg-muted flex items-center justify-center shrink-0 overflow-hidden">
                        {c.image_url ? (
                          <img src={c.image_url} alt="" className="h-full w-full object-cover" />
                        ) : (
                          <span className="material-symbols-outlined text-muted-foreground">auto_stories</span>
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="font-medium text-foreground truncate">{c.title}</h3>
                        <p className="text-xs text-muted-foreground">{c.chapters_count ?? 0} capítulos</p>
                      </div>
                      <div className="flex gap-1 shrink-0">
                        <Button variant="ghost" size="icon" onClick={() => navigate(`/instructor/course/${c.id}`)}>
                          <span className="material-symbols-outlined text-[18px]">visibility</span>
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => openEditCourse(c)}>
                          <span className="material-symbols-outlined text-[18px]">edit</span>
                        </Button>
                        <Button variant="destructive" size="icon" onClick={() => setConfirmDelete(c.id)}>
                          <span className="material-symbols-outlined text-[18px]">delete</span>
                        </Button>
                      </div>
                    </Card>
                  ))}
                </div>
              )}
            </div>
          )}

          {sidebarTab === 'settings' && (
            <div className="flex flex-col gap-6 max-w-xl">
              <Input
                label="Título"
                value={discipline.title ?? ''}
                onChange={(e) => setDiscipline((d) => ({ ...d, title: e.target.value }))}
              />
              <div className="grid grid-cols-2 gap-4">
                <Input
                  label="Código"
                  placeholder="Ex.: CS101"
                  value={discipline.code ?? ''}
                  onChange={(e) => setDiscipline((d) => ({ ...d, code: e.target.value }))}
                />
                <Input
                  label="Departamento"
                  placeholder="Ex.: Ciência da Computação"
                  value={discipline.department ?? ''}
                  onChange={(e) => setDiscipline((d) => ({ ...d, department: e.target.value }))}
                />
              </div>

              <div className="space-y-1.5">
                <label className="block text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Descrição</label>
                <textarea
                  rows={4}
                  value={(discipline as Record<string, unknown>).description as string ?? ''}
                  onChange={(e) => setDiscipline((d) => ({ ...d, description: e.target.value }))}
                  className="w-full bg-harven-bg border-none rounded-lg text-sm text-foreground placeholder-gray-400 focus:ring-1 focus:ring-primary transition-all px-4 py-2 resize-none"
                  placeholder="Descreva a disciplina..."
                />
              </div>

              <div className="space-y-1.5">
                <label className="block text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Imagem de Capa</label>
                <div className="flex items-center gap-4">
                  {imagePreview ? (
                    <div className="h-24 w-40 rounded-lg overflow-hidden bg-muted">
                      <img src={imagePreview} alt="Preview" className="h-full w-full object-cover" />
                    </div>
                  ) : (
                    <div className="h-24 w-40 rounded-lg bg-muted flex items-center justify-center">
                      <span className="material-symbols-outlined text-muted-foreground text-3xl">image</span>
                    </div>
                  )}
                  <label className="cursor-pointer">
                    <input type="file" accept="image/*" className="hidden" onChange={handleImageChange} />
                    <span className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-border text-sm font-medium text-foreground hover:bg-muted transition-colors">
                      <span className="material-symbols-outlined text-[16px]">upload</span>
                      Alterar Imagem
                    </span>
                  </label>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Course Modal */}
      {courseModal.open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="fixed inset-0 bg-black/50" onClick={() => setCourseModal({ open: false, editing: null })} />
          <div className="relative bg-card rounded-xl shadow-xl p-6 w-full max-w-md mx-4" role="dialog" aria-modal="true">
            <h3 className="text-lg font-display font-bold text-foreground mb-4">
              {courseModal.editing ? 'Editar Curso' : 'Novo Curso'}
            </h3>
            <div className="flex flex-col gap-4">
              <Input label="Título" value={courseForm.title} onChange={(e) => setCourseForm((f) => ({ ...f, title: e.target.value }))} autoFocus />
              <div className="space-y-1.5">
                <label className="block text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Descrição</label>
                <textarea
                  rows={3}
                  value={courseForm.description}
                  onChange={(e) => setCourseForm((f) => ({ ...f, description: e.target.value }))}
                  className="w-full bg-harven-bg border-none rounded-lg text-sm text-foreground placeholder-gray-400 focus:ring-1 focus:ring-primary px-4 py-2 resize-none"
                />
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <Button variant="outline" onClick={() => setCourseModal({ open: false, editing: null })}>Cancelar</Button>
              <Button onClick={handleSaveCourse} disabled={saving || !courseForm.title.trim()}>
                {saving ? 'Salvando...' : courseModal.editing ? 'Atualizar' : 'Criar'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirm */}
      {confirmDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="fixed inset-0 bg-black/50" onClick={() => setConfirmDelete(null)} />
          <div className="relative bg-card rounded-xl shadow-xl p-6 w-full max-w-sm mx-4" role="alertdialog" aria-modal="true">
            <h3 className="text-lg font-bold text-foreground mb-2">Excluir Curso</h3>
            <p className="text-sm text-muted-foreground mb-6">Essa ação não pode ser desfeita. Deseja continuar?</p>
            <div className="flex justify-end gap-3">
              <Button variant="outline" onClick={() => setConfirmDelete(null)}>Cancelar</Button>
              <Button variant="destructive" onClick={() => handleDeleteCourse(confirmDelete)}>Excluir</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
