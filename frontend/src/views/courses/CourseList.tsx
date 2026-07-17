// @ts-nocheck
import { useState, useMemo, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { coursesApi, usersApi, userStatsApi } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import { unwrapList } from '../../lib/utils';
import { cn } from '../../lib/utils';
import { EmptyState } from '../../components/ui/EmptyState';
import { SearchInput } from '../../components/ui/SearchInput';
import { PageHeader } from '../../components/ui/PageHeader';
import { Modal } from '../../components/ui/Modal';
import { Button } from '../../components/ui/Button';
import type { UserRole } from '../../types';

interface CourseListProps { userRole: UserRole }

export default function CourseList({ userRole }: CourseListProps) {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [courses, setCourses] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [activeTab, setActiveTab] = useState('Todos');
  const [selectedCategory, setSelectedCategory] = useState('Todas');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newCourse, setNewCourse] = useState({ title: '', instructor_id: '', category: 'Geral' });
  const [isCreating, setIsCreating] = useState(false);
  const [instructors, setInstructors] = useState<Array<{ id: string; name: string }>>([]);

  // Catalogo do aluno: enquanto o backend nao filtra a listagem por matricula
  // (em andamento no terminal Byte), o front NAO pode exibir curso em rascunho
  // para STUDENT. Filtro defensivo e idempotente: quando o backend passar a
  // filtrar, este predicado apenas deixa de remover itens (nao depende de
  // course.progress nem de campo inexistente).
  const visibleToRole = (c: Record<string, unknown>) => {
    if (userRole !== 'STUDENT') return true;
    const status = String(c.status ?? '').toLowerCase();
    return status === '' || status === 'published' || status === 'active';
  };

  // Progresso real por conteudo concluido: o objeto course do backend nao traz
  // `progress` — a fonte e /users/{id}/courses/{courseId}/progress.
  const attachProgress = async (list: Record<string, unknown>[]) => {
    if (!user?.id) return list;
    return Promise.all(list.map(async (course) => {
      try {
        const p = await userStatsApi.getCourseProgress(user.id, String(course.id));
        return { ...course, progress: Math.round(Number(p?.progress_percent ?? 0)) };
      } catch {
        return course;
      }
    }));
  };

  useEffect(() => {
    const ctrl = new AbortController();
    (async () => {
      try {
        const data = await coursesApi.list(ctrl.signal);
        if (ctrl.signal.aborted) return;
        const list = unwrapList<Record<string, unknown>>(data).filter((c) => c.title && String(c.title).trim()).filter(visibleToRole);
        const withProgress = await attachProgress(list);
        if (ctrl.signal.aborted) return;
        setCourses(withProgress);
      } catch { if (!ctrl.signal.aborted) console.error('Erro ao buscar cursos'); }
      finally { if (!ctrl.signal.aborted) setLoading(false); }
    })();
    return () => ctrl.abort();
  }, [user?.id]);

  // Load instructors list when admin opens the create modal
  useEffect(() => {
    if (!showCreateModal || userRole !== 'ADMIN') return;
    (async () => {
      try {
        const res = await usersApi.list({ role: 'INSTRUCTOR', per_page: 100 });
        const users = unwrapList<Record<string, unknown>>(res);
        setInstructors(users.map((u) => ({ id: String(u.id), name: String(u.name) })));
      } catch { toast.error('Erro ao carregar instrutores'); }
    })();
  }, [showCreateModal, userRole]);

  const categories = useMemo(() => ['Todas', ...new Set(courses.map(c => String(c.category || 'Geral')))], [courses]);

  const filtered = useMemo(() => {
    return courses.filter(course => {
      const progress = Number(course.progress ?? 0);
      const status = progress >= 100 ? 'Concluído' : progress > 0 ? 'Em Andamento' : 'Não Iniciado';
      const matchesTab = activeTab === 'Todos' || activeTab === status || (activeTab === 'Favoritos' && course.isFavorite) || (activeTab === 'Não Iniciados' && status === 'Não Iniciado');
      const q = searchTerm.toLowerCase();
      const matchesSearch = !q || String(course.title ?? '').toLowerCase().includes(q) || String(course.instructor ?? '').toLowerCase().includes(q);
      const matchesCat = selectedCategory === 'Todas' || course.category === selectedCategory;
      return matchesTab && matchesSearch && matchesCat;
    });
  }, [courses, activeTab, searchTerm, selectedCategory]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsCreating(true);
    try {
      const payload: Record<string, unknown> = { title: newCourse.title, status: 'draft' };
      if (newCourse.instructor_id) payload.instructor_id = newCourse.instructor_id;
      await coursesApi.create(payload);
      const data = await coursesApi.list();
      setCourses(await attachProgress(unwrapList<Record<string, unknown>>(data).filter((c) => c.title && String(c.title).trim()).filter(visibleToRole)));
      setShowCreateModal(false);
      setNewCourse({ title: '', instructor_id: '', category: 'Geral' });
      toast.success('Curso criado com sucesso');
    } catch { toast.error('Erro ao criar curso'); }
    finally { setIsCreating(false); }
  };

  const tabs = ['Todos', 'Em Andamento', 'Não Iniciados', 'Concluídos', 'Favoritos'];

  if (loading) return (
    <div className="max-w-7xl mx-auto p-8 space-y-8">
      <div className="h-8 w-48 bg-gray-200 animate-pulse rounded" />
      <div className="h-10 w-full bg-gray-200 animate-pulse rounded-lg" />
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
        {[1,2,3,4,5,6].map(i => <div key={i} className="rounded-xl border p-4 space-y-3"><div className="h-40 bg-gray-200 animate-pulse rounded-lg" /><div className="h-4 w-3/4 bg-gray-200 animate-pulse rounded" /><div className="h-3 w-1/2 bg-gray-200 animate-pulse rounded" /><div className="h-2 w-full bg-gray-200 animate-pulse rounded" /></div>)}
      </div>
    </div>
  );

  return (
    <div className="max-w-7xl mx-auto p-8 space-y-8 animate-in fade-in duration-500">
      <div className="flex flex-col md:flex-row justify-between items-end gap-6">
        <PageHeader
          title="Meus Estudos"
          subtitle="Explore seu catálogo e continue aprendendo."
          constrained={false}
          className="mb-0"
        />
        <div className="flex items-end gap-3 w-full md:w-auto">
          <SearchInput
            value={searchTerm}
            onChange={setSearchTerm}
            placeholder="Buscar materiais..."
            className="flex-1 md:w-64"
          />
          <select value={selectedCategory} onChange={e => setSelectedCategory(e.target.value)} className="bg-harven-bg border-none rounded-lg px-4 py-2 text-sm focus:ring-1 focus:ring-primary">
            {categories.map(c => <option key={c}>{c}</option>)}
          </select>
        </div>
      </div>

      <div className="flex bg-muted rounded-lg p-1 gap-1 overflow-x-auto no-scrollbar">
        {tabs.map(tab => (
          <button key={tab} onClick={() => setActiveTab(tab)} className={cn('px-4 py-2 text-xs font-bold rounded-md whitespace-nowrap transition-colors', activeTab === tab ? 'bg-white text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground')}>{tab}</button>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
        {filtered.length === 0 && (
          <div className="col-span-full">
            <EmptyState
              icon="school"
              title={searchTerm ? 'Nenhum curso encontrado.' : 'Nenhum curso disponível ainda.'}
              description={searchTerm ? 'Tente outro termo de busca.' : 'Os cursos aparecerão aqui quando disponíveis.'}
              size="lg"
            />
          </div>
        )}
        {filtered.map(course => {
          const progress = Number(course.progress ?? 0);
          return (
            <div key={String(course.id)} onClick={() => navigate(`/course/${course.id}`)} className="bg-white rounded-xl border border-harven-border shadow-sm overflow-hidden cursor-pointer hover:border-primary/50 transition-colors group">
              <div className="relative h-40 bg-muted overflow-hidden">
                {course.image || course.image_url ? <img src={String(course.image || course.image_url)} alt="" className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500" /> : <div className="w-full h-full bg-gradient-to-br from-harven-dark to-harven-sidebar flex items-center justify-center"><span className="material-symbols-outlined text-primary/30 text-[64px]">school</span></div>}
                {course.category && <span className="absolute top-3 right-3 bg-white/90 backdrop-blur text-foreground text-[10px] font-bold px-2 py-0.5 rounded">{String(course.category)}</span>}
                {progress >= 100 && <div className="absolute inset-0 bg-black/60 flex items-center justify-center"><span className="bg-primary text-harven-dark text-xs font-bold px-2 py-1 rounded flex items-center gap-1"><span className="material-symbols-outlined text-[14px] fill-1">check_circle</span>Concluido</span></div>}
              </div>
              <div className="p-5 space-y-3">
                <h3 className="font-display font-bold text-foreground line-clamp-2 group-hover:text-primary-dark transition-colors">{String(course.title)}</h3>
                {course.instructor && <p className="text-xs text-muted-foreground flex items-center gap-1"><span className="material-symbols-outlined text-[14px]">school</span>{String(course.instructor)}</p>}
                <div className="space-y-1 mt-auto pt-3">
                  <div className="flex justify-between text-[10px] font-bold uppercase tracking-wider"><span className="text-muted-foreground">Progresso</span><span>{progress}%</span></div>
                  <div className="h-1.5 bg-muted rounded-full overflow-hidden"><div className="h-full bg-primary rounded-full transition-all" style={{ width: `${progress}%` }} /></div>
                </div>
                <div className="flex justify-between items-center"><span className="text-[10px] font-bold text-muted-foreground uppercase">{Number(course.total_modules ?? 0)} Modulos</span><span className="text-xs font-bold hover:text-primary-dark">{progress > 0 ? 'Continuar' : 'Iniciar'}</span></div>
              </div>
            </div>
          );
        })}

        {/* Course creation is admin-only and happens in /admin/classes (ClassManagement) */}
      </div>

      <Modal.Root open={showCreateModal} onClose={() => setShowCreateModal(false)} size="md">
        <Modal.Header title="Novo Curso" onClose={() => setShowCreateModal(false)} />
        <Modal.Body>
          <form id="create-course-form" onSubmit={handleCreate} className="space-y-4">
            <div>
              <label className="text-[11px] font-medium uppercase text-gray-400">Titulo</label>
              <input value={newCourse.title} onChange={e => setNewCourse({...newCourse, title: e.target.value})} className="w-full bg-harven-bg border-none rounded-lg px-4 py-2 text-sm focus:ring-1 focus:ring-primary mt-1" required />
            </div>
            {userRole === 'ADMIN' && (
              <div>
                <label className="text-[11px] font-medium uppercase text-gray-400">Atribuir ao Instrutor</label>
                <select
                  value={newCourse.instructor_id}
                  onChange={e => setNewCourse({...newCourse, instructor_id: e.target.value})}
                  className="w-full bg-harven-bg border-none rounded-lg px-4 py-2 text-sm focus:ring-1 focus:ring-primary mt-1"
                >
                  <option value="">Selecione um instrutor (opcional)</option>
                  {instructors.map(i => (
                    <option key={i.id} value={i.id}>{i.name}</option>
                  ))}
                </select>
                {instructors.length === 0 && (
                  <p className="text-[10px] text-gray-400 mt-1">Nenhum instrutor cadastrado. Crie um em Usuarios.</p>
                )}
              </div>
            )}
          </form>
        </Modal.Body>
        <Modal.Footer>
          <Button variant="outline" onClick={() => setShowCreateModal(false)}>Cancelar</Button>
          <Button type="submit" form="create-course-form" disabled={isCreating}>
            {isCreating ? 'Criando...' : 'Criar'}
          </Button>
        </Modal.Footer>
      </Modal.Root>
    </div>
  );
}
