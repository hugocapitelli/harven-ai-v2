// @ts-nocheck
import { useState, useMemo, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { coursesApi, usersApi } from '../../services/api';
import { cn } from '../../lib/utils';
import type { UserRole } from '../../types';

interface CourseListProps { userRole: UserRole }

export default function CourseList({ userRole }: CourseListProps) {
  const navigate = useNavigate();
  const [courses, setCourses] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [activeTab, setActiveTab] = useState('Todos');
  const [selectedCategory, setSelectedCategory] = useState('Todas');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newCourse, setNewCourse] = useState({ title: '', instructor_id: '', category: 'Geral' });
  const [isCreating, setIsCreating] = useState(false);
  const [instructors, setInstructors] = useState<Array<{ id: string; name: string }>>([]);

  useEffect(() => {
    const ctrl = new AbortController();
    (async () => {
      try {
        const data = await coursesApi.list(ctrl.signal);
        if (ctrl.signal.aborted) return;
        setCourses(Array.isArray(data) ? data.filter((c: Record<string, unknown>) => c.title && String(c.title).trim()) : []);
      } catch { if (!ctrl.signal.aborted) console.error('Erro ao buscar cursos'); }
      finally { if (!ctrl.signal.aborted) setLoading(false); }
    })();
    return () => ctrl.abort();
  }, []);

  // Load instructors list when admin opens the create modal
  useEffect(() => {
    if (!showCreateModal || userRole !== 'ADMIN') return;
    (async () => {
      try {
        const res = await usersApi.list({ role: 'INSTRUCTOR', per_page: 100 });
        const users = Array.isArray(res?.data) ? res.data : (Array.isArray(res) ? res : []);
        setInstructors(users.map((u: Record<string, unknown>) => ({ id: String(u.id), name: String(u.name) })));
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
      setCourses(Array.isArray(data) ? data.filter((c: Record<string, unknown>) => c.title && String(c.title).trim()) : []);
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
        <div>
          <h2 className="text-3xl font-display font-bold text-foreground">Meus Estudos</h2>
          <p className="text-muted-foreground mt-1">Explore seu catalogo e continue aprendendo.</p>
        </div>
        <div className="flex items-end gap-3 w-full md:w-auto">
          <div className="relative flex-1 md:w-64">
            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-[18px]">search</span>
            <input value={searchTerm} onChange={e => setSearchTerm(e.target.value)} placeholder="Buscar materiais..." className="w-full bg-harven-bg border-none rounded-lg pl-10 pr-4 py-2 text-sm focus:ring-1 focus:ring-primary" />
          </div>
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

        {(userRole === 'INSTRUCTOR' || userRole === 'ADMIN') && (
          <div onClick={() => setShowCreateModal(true)} className="flex flex-col items-center justify-center p-6 gap-4 text-center border-2 border-dashed border-gray-300 rounded-xl bg-muted/20 min-h-[300px] cursor-pointer hover:border-primary hover:bg-white transition-all">
            <div className="size-12 rounded-full bg-muted flex items-center justify-center"><span className="material-symbols-outlined text-muted-foreground">add</span></div>
            <p className="text-sm font-bold">Criar Novo Curso</p>
          </div>
        )}
      </div>

      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
          <div className="bg-white rounded-xl shadow-xl p-6 w-full max-w-md">
            <h3 className="text-xl font-bold mb-4">Novo Curso</h3>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="text-[10px] font-bold uppercase text-gray-400">Titulo</label>
                <input value={newCourse.title} onChange={e => setNewCourse({...newCourse, title: e.target.value})} className="w-full bg-harven-bg border-none rounded-lg px-4 py-2 text-sm focus:ring-1 focus:ring-primary mt-1" required />
              </div>
              {userRole === 'ADMIN' && (
                <div>
                  <label className="text-[10px] font-bold uppercase text-gray-400">Atribuir ao Instrutor</label>
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
              <div className="flex gap-2 pt-4">
                <button type="button" onClick={() => setShowCreateModal(false)} className="flex-1 py-2 rounded-lg border border-harven-border text-sm font-bold hover:bg-gray-50">Cancelar</button>
                <button type="submit" disabled={isCreating} className="flex-1 py-2 rounded-lg bg-primary text-harven-dark text-sm font-bold disabled:opacity-50">{isCreating ? 'Criando...' : 'Criar'}</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
