// @ts-nocheck
import { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { coursesApi, chaptersApi, contentsApi, uploadApi } from '../../services/api';
import { cn } from '../../lib/utils';
import type { UserRole, Chapter, Content } from '../../types';

interface CourseEditProps { userRole: UserRole }

export default function CourseEdit({ userRole: _userRole }: CourseEditProps) {
  const navigate = useNavigate();
  const { courseId } = useParams<{ courseId: string }>();
  const [course, setCourse] = useState<Record<string, unknown> | null>(null);
  const [modules, setModules] = useState<(Chapter & { contents?: Content[] })[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [sideTab, setSideTab] = useState<'structure' | 'settings'>('structure');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState({ title: '', description: '' });
  const [deleteTarget, setDeleteTarget] = useState<{ type: string; id: string } | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    (async () => {
      if (!courseId) { setLoading(false); return; }
      try {
        const [c, ch] = await Promise.all([coursesApi.get(courseId, ctrl.signal), chaptersApi.list(courseId)]);
        if (ctrl.signal.aborted) return;
        setCourse(c);
        setModules(Array.isArray(ch) ? ch : []);
        setEditForm({ title: String(c?.title ?? ''), description: String(c?.description ?? '') });
      } catch { /* handled */ }
      finally { if (!ctrl.signal.aborted) setLoading(false); }
    })();
    return () => ctrl.abort();
  }, [courseId]);

  const reload = async () => {
    if (!courseId) return;
    const ch = await chaptersApi.list(courseId);
    setModules(Array.isArray(ch) ? ch : []);
  };

  const save = async () => {
    if (!courseId) return;
    setSaving(true);
    try {
      await coursesApi.update(courseId, editForm);
      setCourse(prev => prev ? { ...prev, ...editForm } : prev);
      setDirty(false);
      toast.success('Curso salvo');
    } catch { toast.error('Erro ao salvar'); }
    finally { setSaving(false); }
  };

  const addModule = async () => {
    if (!courseId) return;
    try { await chaptersApi.create(courseId, { title: `Novo Modulo ${modules.length + 1}`, description: '', order: modules.length + 1 }); reload(); } catch { toast.error('Erro ao criar modulo'); }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    try {
      if (deleteTarget.type === 'content') await contentsApi.delete(deleteTarget.id);
      else if (deleteTarget.type === 'module') await chaptersApi.delete(deleteTarget.id);
      else if (deleteTarget.type === 'course' && courseId) { await coursesApi.delete(courseId); navigate('/instructor'); return; }
      reload();
    } catch { toast.error('Erro ao excluir'); }
    setDeleteTarget(null);
  };

  const handleImageUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !courseId) return;
    try {
      const res = await uploadApi.upload(file, 'image');
      const url = res?.url ?? res?.file_url;
      if (url) {
        await coursesApi.update(courseId, { image_url: url });
        setCourse(prev => prev ? { ...prev, image_url: url } : prev);
        toast.success('Imagem atualizada');
      }
    } catch { toast.error('Erro ao fazer upload'); }
  };

  if (loading) return (
    <div className="flex flex-col h-full bg-background">
      <div className="h-16 bg-gray-200 animate-pulse" />
      <div className="flex flex-1"><div className="w-64 bg-gray-100 animate-pulse" /><div className="flex-1 p-8 space-y-4">{[1,2,3].map(i => <div key={i} className="h-20 bg-gray-200 animate-pulse rounded-xl" />)}</div></div>
    </div>
  );

  return (
    <div className="flex flex-col h-full bg-background animate-in fade-in duration-300">
      {/* Sticky Header */}
      <div className="sticky top-0 z-10 h-16 bg-white border-b border-harven-border flex items-center justify-between px-6 flex-shrink-0">
        <div className="flex items-center gap-4">
          <button onClick={() => navigate(-1)} className="text-gray-400 hover:text-foreground"><span className="material-symbols-outlined">arrow_back</span></button>
          <h1 className="font-display font-bold text-lg truncate">{editForm.title || 'Editar Curso'}</h1>
          <span className={cn('text-[10px] font-bold px-2 py-0.5 rounded uppercase', course?.status === 'published' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500')}>{course?.status === 'published' ? 'Publicado' : 'Rascunho'}</span>
        </div>
        <button onClick={save} disabled={saving} className="relative bg-primary hover:bg-primary-dark text-harven-dark font-bold px-5 py-2 rounded-lg text-xs uppercase tracking-widest disabled:opacity-50 transition-all">
          {saving ? 'Salvando...' : 'Salvar'}
          {dirty && <span className="absolute -top-1 -right-1 size-3 bg-red-500 rounded-full" />}
        </button>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <div className="w-64 bg-white border-r border-harven-border flex-shrink-0 flex flex-col">
          <div className="flex border-b border-harven-border">
            {(['structure', 'settings'] as const).map(tab => (
              <button key={tab} onClick={() => setSideTab(tab)} className={cn('flex-1 py-3 text-xs font-bold uppercase transition-colors', sideTab === tab ? 'text-foreground border-b-2 border-primary' : 'text-muted-foreground')}>
                {tab === 'structure' ? 'Estrutura' : 'Config'}
              </button>
            ))}
          </div>
          <div className="flex-1 overflow-y-auto p-4">
            {sideTab === 'structure' && (
              <div className="space-y-2">
                {modules.map(mod => (
                  <div key={mod.id}>
                    <div onClick={() => setExpandedId(expandedId === mod.id ? null : mod.id)} className="flex items-center gap-2 p-2 rounded-lg hover:bg-harven-bg cursor-pointer group">
                      <span className="material-symbols-outlined text-[16px] text-gray-400">drag_indicator</span>
                      <span className="text-sm font-medium flex-1 truncate">{mod.title}</span>
                      <span className={cn('material-symbols-outlined text-[16px] transition-transform', expandedId === mod.id && 'rotate-180')}>expand_more</span>
                    </div>
                    {expandedId === mod.id && mod.contents?.map(c => (
                      <div key={c.id} className="pl-8 py-1.5 flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground cursor-pointer" onClick={() => navigate(`/course/${courseId}/chapter/${mod.id}/content/${c.id}/revision`)}>
                        <span className="material-symbols-outlined text-[14px]">{c.type === 'VIDEO' ? 'play_circle' : c.type === 'AUDIO' ? 'headphones' : 'article'}</span>
                        <span className="truncate">{c.title}</span>
                      </div>
                    ))}
                  </div>
                ))}
                <button onClick={addModule} className="w-full py-2 text-xs font-bold text-gray-400 hover:text-primary-dark flex items-center justify-center gap-1"><span className="material-symbols-outlined text-[14px]">add</span>Modulo</button>
              </div>
            )}
            {sideTab === 'settings' && (
              <div className="space-y-4">
                <div><label className="text-[10px] font-bold uppercase text-gray-400">Titulo</label><input value={editForm.title} onChange={e => { setEditForm({...editForm, title: e.target.value}); setDirty(true); }} className="w-full bg-harven-bg border-none rounded-lg px-3 py-2 text-sm focus:ring-1 focus:ring-primary mt-1" /></div>
                <div><label className="text-[10px] font-bold uppercase text-gray-400">Descricao</label><textarea value={editForm.description} onChange={e => { setEditForm({...editForm, description: e.target.value}); setDirty(true); }} rows={4} className="w-full bg-harven-bg border-none rounded-lg px-3 py-2 text-sm focus:ring-1 focus:ring-primary mt-1 resize-none" /></div>
                <div>
                  <label className="text-[10px] font-bold uppercase text-gray-400">Capa</label>
                  {(course?.image_url || course?.image) && <img src={String(course.image_url || course.image)} alt="" className="w-full h-32 object-cover rounded-lg mt-1" />}
                  <input type="file" accept="image/*" onChange={handleImageUpload} className="mt-2 text-xs" />
                </div>
                <div className="border-t border-red-200 pt-4 mt-4">
                  <p className="text-xs text-red-500 font-bold uppercase mb-2">Zona de Perigo</p>
                  <button onClick={() => setDeleteTarget({ type: 'course', id: courseId! })} className="w-full py-2 rounded-lg border border-red-300 text-red-500 text-xs font-bold hover:bg-red-50">Excluir Curso</button>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Main */}
        <div className="flex-1 overflow-y-auto p-8">
          <div className="max-w-4xl mx-auto space-y-4">
            {modules.map(mod => (
              <div key={mod.id} className="bg-white rounded-xl border border-harven-border p-6">
                <div className="flex justify-between items-center mb-4">
                  <h3 className="font-bold text-lg">{mod.title}</h3>
                  <div className="flex gap-2">
                    <button onClick={() => navigate(`/course/${courseId}/chapter/${mod.id}/new-content`)} className="text-xs font-bold text-primary-dark flex items-center gap-1"><span className="material-symbols-outlined text-[14px]">add</span>Aula</button>
                    <button onClick={() => setDeleteTarget({ type: 'module', id: mod.id })} className="text-gray-300 hover:text-red-500"><span className="material-symbols-outlined text-[16px]">delete</span></button>
                  </div>
                </div>
                {mod.contents && mod.contents.length > 0 ? (
                  <div className="space-y-2">
                    {mod.contents.map(c => (
                      <div key={c.id} className="flex items-center gap-3 p-3 rounded-lg hover:bg-harven-bg group">
                        <span className="material-symbols-outlined text-gray-400 text-[18px]">{c.type === 'VIDEO' ? 'play_circle' : c.type === 'AUDIO' ? 'headphones' : 'article'}</span>
                        <span className="text-sm flex-1">{c.title}</span>
                        <button onClick={() => setDeleteTarget({ type: 'content', id: c.id })} className="opacity-0 group-hover:opacity-100 text-gray-300 hover:text-red-500 transition-opacity"><span className="material-symbols-outlined text-[16px]">delete</span></button>
                      </div>
                    ))}
                  </div>
                ) : <p className="text-sm text-muted-foreground">Nenhum conteudo neste modulo.</p>}
              </div>
            ))}
          </div>
        </div>
      </div>

      {deleteTarget && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={() => setDeleteTarget(null)}>
          <div className="bg-white rounded-2xl shadow-2xl max-w-sm w-full p-6" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-bold mb-2">Confirmar Exclusao</h3>
            <p className="text-sm text-gray-500 mb-6">Esta acao nao pode ser desfeita.</p>
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
