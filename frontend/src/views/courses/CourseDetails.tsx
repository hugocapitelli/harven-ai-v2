// @ts-nocheck
import { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { coursesApi, chaptersApi, contentsApi } from '../../services/api';
import { cn } from '../../lib/utils';
import type { UserRole, Chapter, Content } from '../../types';

interface CourseDetailsProps { userRole: UserRole }

export default function CourseDetails({ userRole }: CourseDetailsProps) {
  const navigate = useNavigate();
  const { courseId } = useParams<{ courseId: string }>();
  const isInstructor = userRole === 'INSTRUCTOR' || userRole === 'ADMIN';

  const [course, setCourse] = useState<Record<string, unknown> | null>(null);
  const [modules, setModules] = useState<(Chapter & { contents?: Content[] })[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState('content');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<{ type: 'content' | 'module'; id: string } | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    (async () => {
      if (!courseId) { setLoading(false); return; }
      try {
        const [courseData, chaptersData] = await Promise.all([
          coursesApi.get(courseId, ctrl.signal),
          chaptersApi.list(courseId),
        ]);
        if (ctrl.signal.aborted) return;
        setCourse(courseData);
        const chapters = Array.isArray(chaptersData) ? chaptersData : [];
        // Load contents for each chapter
        const withContents = await Promise.all(
          chapters.map(async (ch) => {
            try {
              const contents = await contentsApi.list(ch.id);
              return { ...ch, contents: Array.isArray(contents) ? contents : [] };
            } catch { return { ...ch, contents: [] }; }
          })
        );
        setModules(withContents);
      } catch { if (!ctrl.signal.aborted) setCourse(null); }
      finally { if (!ctrl.signal.aborted) setLoading(false); }
    })();
    return () => ctrl.abort();
  }, [courseId]);

  const reload = async () => {
    if (!courseId) return;
    const [c, ch] = await Promise.all([coursesApi.get(courseId), chaptersApi.list(courseId)]);
    setCourse(c);
    const chapters = Array.isArray(ch) ? ch : [];
    const withContents = await Promise.all(
      chapters.map(async (chap) => {
        try {
          const contents = await contentsApi.list(chap.id);
          return { ...chap, contents: Array.isArray(contents) ? contents : [] };
        } catch { return { ...chap, contents: [] }; }
      })
    );
    setModules(withContents);
  };

  const addModule = async () => {
    if (!courseId) return;
    try { await chaptersApi.create(courseId, { title: `Novo Modulo ${modules.length + 1}`, description: '', order: modules.length + 1 }); reload(); } catch { toast.error('Erro ao criar modulo'); }
  };

  const saveModuleTitle = async (id: string) => {
    try { await chaptersApi.update(id, { title: editTitle }); reload(); } catch { toast.error('Erro ao salvar'); }
    setEditingId(null);
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    try {
      if (deleteTarget.type === 'content') await contentsApi.delete(deleteTarget.id);
      else await chaptersApi.delete(deleteTarget.id);
      reload();
    } catch { toast.error('Erro ao excluir'); }
    setDeleteTarget(null);
  };

  const tabs = [
    { id: 'content', label: 'Conteudo', icon: 'list_alt' },
    { id: 'about', label: 'Sobre', icon: 'info' },
    { id: 'resources', label: 'Recursos', icon: 'folder_open' },
    { id: 'discussion', label: 'Discussao', icon: 'forum' },
  ];

  if (loading) return (
    <div className="flex flex-col min-h-full bg-background">
      <div className="h-64 bg-gray-200 animate-pulse" />
      <div className="max-w-6xl mx-auto w-full px-8 py-8 space-y-6">
        <div className="h-12 bg-gray-200 animate-pulse rounded-xl" />
        {[1,2,3].map(i => <div key={i} className="h-20 bg-gray-200 animate-pulse rounded-xl" />)}
      </div>
    </div>
  );

  if (!course) return (
    <div className="flex items-center justify-center h-full"><div className="text-center"><span className="material-symbols-outlined text-6xl text-gray-300 mb-4">search_off</span><p className="text-lg font-bold text-gray-600">Curso nao encontrado</p><button onClick={() => navigate(-1)} className="mt-4 text-sm text-primary font-bold">Voltar</button></div></div>
  );

  return (
    <div className="max-w-7xl mx-auto p-8 flex flex-col gap-8 animate-in fade-in duration-500">
      {/* Header Banner */}
      <div className="relative rounded-xl overflow-hidden bg-accent text-accent-foreground p-8">
        {(course.image || course.image_url) && (
          <img src={String(course.image || course.image_url)} alt="" className="absolute inset-0 w-full h-full object-cover opacity-20" />
        )}
        <div className="relative z-10">
          <div className="flex items-center justify-between mb-4">
            <button onClick={() => navigate(-1)} className="flex items-center gap-1 text-accent-foreground/70 hover:text-accent-foreground text-sm">
              <span className="material-symbols-outlined text-[16px]">arrow_back</span> Voltar
            </button>
            {isInstructor && (
              <button onClick={() => navigate(`/courses/${courseId}/edit`)} className="text-accent-foreground/50 hover:text-primary transition-colors">
                <span className="material-symbols-outlined">settings</span>
              </button>
            )}
          </div>
          <h1 className="text-3xl font-display font-bold">{String(course.title)}</h1>
          <p className="text-sm opacity-70 mt-1">Instrutor &bull; {String(course.status || 'Ativo')}</p>
        </div>
      </div>

      <div className="flex flex-col gap-8">
        {/* Tabs */}
        <div className="bg-white rounded-xl border border-harven-border p-1.5 shadow-sm flex overflow-x-auto no-scrollbar">
          {tabs.map(tab => (
            <button key={tab.id} onClick={() => setActiveTab(tab.id)} className={cn('flex-1 flex items-center justify-center gap-2 px-6 py-3 rounded-lg text-sm font-bold transition-all whitespace-nowrap', activeTab === tab.id ? 'bg-harven-dark text-white shadow-md' : 'text-gray-500 hover:bg-gray-50')}>
              <span className={cn('material-symbols-outlined text-[18px]', activeTab === tab.id ? 'text-primary' : 'text-gray-400')}>{tab.icon}</span>{tab.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="min-h-[400px]">
          {activeTab === 'content' && (
            <div className="space-y-4">
              {isInstructor && <button onClick={addModule} className="w-full border-2 border-dashed border-gray-300 rounded-xl p-4 flex items-center justify-center gap-2 text-gray-400 font-bold hover:border-primary hover:text-primary-dark transition-all"><span className="material-symbols-outlined">add_circle</span>Adicionar Novo Modulo</button>}
              {modules.map(mod => {
                const isExpanded = expandedId === mod.id;
                const isEditing = editingId === mod.id;
                return (
                  <div key={mod.id} className={cn('bg-white rounded-xl border overflow-hidden transition-all', isExpanded ? 'border-primary/50 ring-1 ring-primary/20 shadow-md' : 'border-harven-border hover:border-gray-300')}>
                    <div className="p-6 flex justify-between items-center cursor-pointer hover:bg-gray-50 select-none" onClick={() => !isEditing && setExpandedId(isExpanded ? null : mod.id)}>
                      <div className="flex items-center gap-4 w-full">
                        <div className={cn('size-10 rounded-full flex items-center justify-center transition-all', isExpanded ? 'bg-primary text-harven-dark rotate-180' : 'bg-harven-bg')}><span className="material-symbols-outlined">expand_more</span></div>
                        {isEditing ? (
                          <div className="flex gap-2" onClick={e => e.stopPropagation()}>
                            <input value={editTitle} onChange={e => setEditTitle(e.target.value)} className="bg-harven-bg border border-primary/50 rounded px-2 py-1 text-lg font-bold" autoFocus />
                            <button onClick={() => saveModuleTitle(mod.id)} className="bg-primary px-3 py-1 rounded text-xs font-bold text-harven-dark">Salvar</button>
                            <button onClick={() => setEditingId(null)} className="bg-gray-200 px-3 py-1 rounded text-xs font-bold">Cancelar</button>
                          </div>
                        ) : (
                          <div className="flex-1"><h4 className="font-bold text-lg">{mod.title}</h4><p className="text-xs text-gray-500 uppercase">{mod.contents?.length ?? 0} Aulas</p></div>
                        )}
                        {isInstructor && !isEditing && <button onClick={e => { e.stopPropagation(); setEditingId(mod.id); setEditTitle(mod.title); }} className="p-1 hover:bg-harven-bg rounded text-gray-300 hover:text-primary-dark"><span className="material-symbols-outlined text-[16px]">edit</span></button>}
                      </div>
                    </div>
                    {isExpanded && (
                      <div className="border-t border-harven-border bg-harven-bg/30 divide-y divide-harven-border">
                        {mod.contents?.map(content => (
                          <div key={content.id} onClick={() => navigate(`/course/${courseId}/chapter/${mod.id}/content/${content.id}`)} className="p-5 flex justify-between items-center cursor-pointer hover:bg-white border-l-4 border-l-transparent hover:border-l-primary transition-all">
                            <div className="flex items-center gap-4">
                              <span className="material-symbols-outlined text-gray-400">{content.type === 'VIDEO' ? 'play_circle' : content.type === 'AUDIO' ? 'headphones' : 'article'}</span>
                              <div><p className="text-sm font-bold">{content.title}</p><p className="text-[10px] text-gray-400 uppercase">{content.type}</p></div>
                            </div>
                            {isInstructor && (
                              <div className="flex gap-2">
                                <button onClick={e => { e.stopPropagation(); navigate(`/course/${courseId}/chapter/${mod.id}/content/${content.id}/revision`); }} className="p-1.5 bg-white border rounded-lg text-gray-400 hover:text-blue-500"><span className="material-symbols-outlined text-[16px]">edit</span></button>
                                <button onClick={e => { e.stopPropagation(); setDeleteTarget({ type: 'content', id: content.id }); }} className="p-1.5 bg-white border rounded-lg text-gray-400 hover:text-red-500"><span className="material-symbols-outlined text-[16px]">delete</span></button>
                              </div>
                            )}
                          </div>
                        ))}
                        {isInstructor && <button onClick={() => navigate(`/course/${courseId}/chapter/${mod.id}/new-content`)} className="w-full py-3 text-xs font-bold text-gray-400 uppercase hover:text-primary-dark flex items-center justify-center gap-2"><span className="material-symbols-outlined text-[16px]">add</span>Adicionar Aula</button>}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
          {activeTab === 'about' && <div className="bg-white p-8 rounded-xl border border-harven-border"><h3 className="text-xl font-display font-bold mb-4">Sobre o Curso</h3><p className="text-gray-600 leading-relaxed">{String(course.description || 'Sem descricao.')}</p></div>}
          {activeTab === 'resources' && <div className="bg-white p-8 rounded-xl border border-harven-border text-center"><span className="material-symbols-outlined text-5xl text-gray-300 mb-3">folder_open</span><p className="text-gray-500 font-medium">Nenhum recurso disponivel</p></div>}
          {activeTab === 'discussion' && <div className="bg-white p-8 rounded-xl border border-harven-border text-center"><span className="material-symbols-outlined text-5xl text-gray-300 mb-3">forum</span><p className="text-gray-500 font-medium">Em breve</p></div>}
        </div>
      </div>

      {/* Delete Confirm */}
      {deleteTarget && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={() => setDeleteTarget(null)}>
          <div className="bg-white rounded-2xl shadow-2xl max-w-sm w-full p-6" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-bold mb-2">Excluir {deleteTarget.type === 'content' ? 'Conteudo' : 'Modulo'}</h3>
            <p className="text-sm text-gray-500 mb-6">Tem certeza? Esta acao nao pode ser desfeita.</p>
            <div className="flex gap-2">
              <button onClick={() => setDeleteTarget(null)} className="flex-1 py-2 rounded-lg border text-sm font-bold">Cancelar</button>
              <button onClick={confirmDelete} className="flex-1 py-2 rounded-lg bg-red-500 text-white text-sm font-bold">Excluir</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
