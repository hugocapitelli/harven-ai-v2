// @ts-nocheck
import { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import ReactMarkdown from 'react-markdown';
import { contentsApi, questionsApi, aiApi } from '../../services/api';
import { cn } from '../../lib/utils';
import type { Content, Question } from '../../types';

const difficultyMap = { easy: 'Facil', medium: 'Medio', hard: 'Dificil' } as const;
const difficultyColors = { easy: 'bg-green-100 text-green-700', medium: 'bg-yellow-100 text-yellow-700', hard: 'bg-red-100 text-red-700' } as const;

export default function ContentRevision() {
  const navigate = useNavigate();
  const { courseId, chapterId, contentId } = useParams<{ courseId: string; chapterId: string; contentId: string }>();
  const [content, setContent] = useState<Content | null>(null);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    (async () => {
      if (!contentId) { setLoading(false); return; }
      try {
        const [c, q] = await Promise.all([contentsApi.get(contentId), questionsApi.list(contentId)]);
        if (ctrl.signal.aborted) return;
        setContent(c); setQuestions(Array.isArray(q) ? q : []);
      } catch { /* handled */ }
      finally { if (!ctrl.signal.aborted) setLoading(false); }
    })();
    return () => ctrl.abort();
  }, [contentId]);

  const updateQuestion = (id: string, field: string, value: string) => {
    setQuestions(prev => prev.map(q => q.id === id ? { ...q, [field]: value } : q));
  };

  const cycleDifficulty = (id: string) => {
    const order: ('easy' | 'medium' | 'hard')[] = ['easy', 'medium', 'hard'];
    setQuestions(prev => prev.map(q => {
      if (q.id !== id) return q;
      const idx = order.indexOf(q.difficulty ?? 'easy');
      return { ...q, difficulty: order[(idx + 1) % 3] };
    }));
  };

  const deleteQuestion = (id: string) => {
    setQuestions(prev => prev.filter(q => q.id !== id));
  };

  const addQuestion = () => {
    setQuestions(prev => [...prev, { id: `new-${Date.now()}`, question: '', expected_answer: '', difficulty: 'easy', content_id: contentId }]);
  };

  const save = async () => {
    setSaving(true);
    try {
      await questionsApi.updateBatch(questions);
      toast.success('Questoes salvas');
    } catch { toast.error('Erro ao salvar'); }
    finally { setSaving(false); }
  };

  const reprocess = async () => {
    if (!contentId) return;
    setReprocessing(true);
    try {
      const result = await aiApi.generateQuestions({
        content_id: contentId,
        chapter_content: content?.body || content?.extracted_text || '',
        chapter_title: content?.title || '',
        max_questions: 5,
      });
      if (result?.questions) {
        const mapped = result.questions.map((q: Record<string, unknown>, i: number) => ({
          id: q.id || `ai-${i}`,
          question: q.question || q.text || '',
          expected_answer: q.expected_answer || q.followup_prompts?.[0] || '',
          difficulty: q.difficulty || 'medium',
          skill: q.skill || '',
        }));
        setQuestions(mapped);
      }
      toast.success('Questoes regeneradas pela IA');
    } catch { toast.error('Erro no reprocessamento'); }
    finally { setReprocessing(false); }
  };

  const publish = async () => {
    await save();
    toast.success('Conteudo aprovado e publicado!');
    navigate(`/course/${courseId}/chapter/${chapterId}/content/${contentId}`);
  };

  if (loading) return (
    <div className="flex h-full"><div className="flex-1 p-8 space-y-4">{[1,2,3].map(i => <div key={i} className="h-32 bg-gray-200 animate-pulse rounded-xl" />)}</div><div className="w-96 p-8 space-y-4">{[1,2].map(i => <div key={i} className="h-40 bg-gray-200 animate-pulse rounded-xl" />)}</div></div>
  );

  return (
    <div className="flex flex-col h-full animate-in fade-in duration-300">
      {/* Header */}
      <div className="h-14 bg-white border-b border-harven-border flex items-center justify-between px-6 flex-shrink-0">
        <div className="flex items-center gap-4">
          <button onClick={() => navigate(-1)} className="text-gray-400 hover:text-foreground"><span className="material-symbols-outlined">arrow_back</span></button>
          <h1 className="font-bold truncate">{content?.title ?? 'Revisao'}</h1>
          <span className="text-xs text-muted-foreground">{questions.length} questoes</span>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => navigate(-1)} className="px-3 py-1.5 text-xs font-bold border rounded-lg hover:bg-gray-50">Descartar</button>
          <button onClick={reprocess} disabled={reprocessing} className="px-3 py-1.5 text-xs font-bold border rounded-lg hover:bg-gray-50 flex items-center gap-1 disabled:opacity-50">
            <span className="material-symbols-outlined text-[14px]">auto_awesome</span>{reprocessing ? 'Processando...' : 'Reprocessar IA'}
          </button>
          <button onClick={publish} disabled={saving} className="px-4 py-1.5 bg-primary text-harven-dark text-xs font-bold rounded-lg disabled:opacity-50">Aprovar e Publicar</button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Left: Source Material */}
        <div className="flex-1 overflow-y-auto p-6 bg-harven-bg/50">
          <div className="max-w-2xl mx-auto space-y-4">
            <h3 className="text-sm font-bold uppercase text-gray-400">Material Fonte</h3>
            {content?.file_url && (
              <div className="bg-white rounded-xl border border-harven-border overflow-hidden">
                {content.type === 'VIDEO' ? <video controls className="w-full" src={content.file_url}><track kind="captions" /></video>
                 : content.type === 'AUDIO' ? <div className="p-4"><audio controls className="w-full" src={content.file_url} /></div>
                 : <iframe src={content.file_url} className="w-full h-[500px]" title="Arquivo" />}
              </div>
            )}
            {(content?.body || content?.extracted_text) && (
              <div className="bg-white rounded-xl border border-harven-border p-6">
                <h4 className="text-xs font-bold uppercase text-gray-400 mb-3">Texto Extraido</h4>
                <div className="prose prose-sm max-w-none text-sm text-gray-700">
                  <ReactMarkdown>{content.body || content.extracted_text || ''}</ReactMarkdown>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right: Questions Editor */}
        <div className="w-[480px] border-l border-harven-border bg-white overflow-y-auto p-6 flex-shrink-0">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-bold uppercase text-gray-400">Questoes Socraticas</h3>
            <button onClick={addQuestion} className="text-xs font-bold text-primary-dark flex items-center gap-1"><span className="material-symbols-outlined text-[14px]">add</span>Adicionar</button>
          </div>
          <div className="space-y-4">
            {questions.map((q, idx) => (
              <div key={q.id} className="border border-harven-border rounded-xl p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-gray-400">Questao {idx + 1}</span>
                  <div className="flex items-center gap-2">
                    <button onClick={() => cycleDifficulty(q.id)} className={cn('text-[10px] font-bold px-2 py-0.5 rounded cursor-pointer', difficultyColors[q.difficulty ?? 'easy'])}>
                      {difficultyMap[q.difficulty ?? 'easy']}
                    </button>
                    <button onClick={() => deleteQuestion(q.id)} className="text-gray-300 hover:text-red-500"><span className="material-symbols-outlined text-[16px]">delete</span></button>
                  </div>
                </div>
                <textarea value={q.question} onChange={e => updateQuestion(q.id, 'question', e.target.value)} rows={2} placeholder="Pergunta..." className="w-full bg-harven-bg border-none rounded-lg px-3 py-2 text-sm resize-none focus:ring-1 focus:ring-primary" />
                <textarea value={q.expected_answer ?? ''} onChange={e => updateQuestion(q.id, 'expected_answer', e.target.value)} rows={2} placeholder="Resposta esperada (opcional)..." className="w-full bg-harven-bg border-none rounded-lg px-3 py-2 text-sm resize-none focus:ring-1 focus:ring-primary" />
              </div>
            ))}
            {questions.length === 0 && (
              <div className="text-center py-8"><span className="material-symbols-outlined text-4xl text-gray-300">quiz</span><p className="text-sm text-gray-400 mt-2">Nenhuma questao. Adicione ou use a IA.</p></div>
            )}
          </div>
          <button onClick={save} disabled={saving} className="w-full mt-6 bg-harven-dark text-white font-bold py-3 rounded-xl disabled:opacity-50">{saving ? 'Salvando...' : 'Salvar Questoes'}</button>
        </div>
      </div>
    </div>
  );
}
