// @ts-nocheck
import { useState, useEffect, useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import ReactMarkdown from 'react-markdown';
import { contentsApi, questionsApi, aiApi } from '../../services/api';
import { cn } from '../../lib/utils';
import type { Content, Question } from '../../types';

const difficultyMap = { easy: 'Fácil', medium: 'Médio', hard: 'Difícil' } as const;
const difficultyColors = {
  easy: 'bg-green-100 text-green-700 border-green-200',
  medium: 'bg-amber-100 text-amber-700 border-amber-200',
  hard: 'bg-red-100 text-red-700 border-red-200',
} as const;
const difficultyIcons = { easy: 'sentiment_satisfied', medium: 'psychology', hard: 'local_fire_department' };

export default function ContentRevision() {
  const navigate = useNavigate();
  const { courseId, chapterId, contentId } = useParams<{ courseId: string; chapterId: string; contentId: string }>();
  const [content, setContent] = useState<Content | null>(null);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);

  const bodyText = content?.body || content?.extracted_text || '';
  const stats = useMemo(() => {
    const chars = bodyText.length;
    const words = bodyText.trim() ? bodyText.trim().split(/\s+/).length : 0;
    return { chars, words };
  }, [bodyText]);

  useEffect(() => {
    const ctrl = new AbortController();
    (async () => {
      if (!contentId) { setLoading(false); return; }
      try {
        const [c, q] = await Promise.all([contentsApi.get(contentId), questionsApi.list(contentId)]);
        if (ctrl.signal.aborted) return;
        setContent(c);
        const rawQ = Array.isArray(q) ? q : [];
        setQuestions(rawQ.map((item: Record<string, unknown>) => ({
          ...item,
          question: item.question || item.question_text || '',
          expected_answer: item.expected_answer || '',
        })));
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

  const deleteQuestion = (id: string) => setQuestions(prev => prev.filter(q => q.id !== id));

  const addQuestion = () => {
    setQuestions(prev => [...prev, { id: `new-${Date.now()}`, question: '', expected_answer: '', difficulty: 'medium', content_id: contentId }]);
  };

  const save = async () => {
    setSaving(true);
    try {
      await questionsApi.updateBatch(questions);
      toast.success('Questões salvas');
    } catch { toast.error('Erro ao salvar'); }
    finally { setSaving(false); }
  };

  const reprocess = async () => {
    if (!contentId) return;
    setReprocessing(true);
    try {
      const result = await aiApi.generateQuestions({
        content_id: contentId,
        chapter_content: bodyText,
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
      toast.success('Questões regeneradas pela IA');
    } catch { toast.error('Erro no reprocessamento'); }
    finally { setReprocessing(false); }
  };

  const publish = async () => {
    await save();
    try {
      await contentsApi.update(contentId!, { status: 'published' });
      toast.success('Conteúdo aprovado e publicado!');
    } catch {
      toast.success('Questões salvas!');
    }
    navigate(`/course/${courseId}/chapter/${chapterId}/content/${contentId}`);
  };

  if (loading) return (
    <div className="flex h-full">
      <div className="flex-1 p-8 space-y-4">{[1, 2, 3].map(i => <div key={i} className="h-32 bg-gray-200 animate-pulse rounded-xl" />)}</div>
      <div className="w-[480px] p-8 space-y-4">{[1, 2].map(i => <div key={i} className="h-40 bg-gray-200 animate-pulse rounded-xl" />)}</div>
    </div>
  );

  return (
    <div className="flex flex-col h-full animate-in fade-in duration-300">
      {/* Header */}
      <div className="h-14 bg-white border-b border-harven-border flex items-center justify-between px-6 flex-shrink-0">
        <div className="flex items-center gap-4">
          <button onClick={() => navigate(-1)} className="text-gray-400 hover:text-foreground">
            <span className="material-symbols-outlined">arrow_back</span>
          </button>
          <div>
            <h1 className="font-bold truncate text-sm">{content?.title ?? 'Revisão'}</h1>
            <span className="text-[10px] text-muted-foreground">{questions.length} questões · {stats.words.toLocaleString()} palavras · {stats.chars.toLocaleString()} caracteres</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => navigate(-1)} className="px-3 py-1.5 text-xs font-bold border rounded-lg hover:bg-gray-50">Descartar</button>
          <button onClick={reprocess} disabled={reprocessing} className="px-3 py-1.5 text-xs font-bold border rounded-lg hover:bg-gray-50 flex items-center gap-1 disabled:opacity-50">
            <span className="material-symbols-outlined text-[14px]">auto_awesome</span>
            {reprocessing ? 'Processando...' : 'Reprocessar IA'}
          </button>
          <button onClick={publish} disabled={saving} className="px-4 py-1.5 bg-primary text-harven-dark text-xs font-bold rounded-lg disabled:opacity-50">
            Aprovar e Publicar
          </button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Left: Source Material */}
        <div className="flex-1 overflow-y-auto p-6 bg-harven-bg/50">
          <div className="max-w-2xl mx-auto space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold uppercase text-gray-400">Material Fonte</h3>
              <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
                <span>{stats.words.toLocaleString()} palavras</span>
                <span className="text-gray-300">|</span>
                <span>{stats.chars.toLocaleString()} caracteres</span>
              </div>
            </div>

            {content?.file_url && (
              <div className="bg-white rounded-xl border border-harven-border overflow-hidden">
                {content.type === 'VIDEO' ? <video controls className="w-full" src={content.file_url}><track kind="captions" /></video>
                  : content.type === 'AUDIO' ? <div className="p-4"><audio controls className="w-full" src={content.file_url} /></div>
                  : <iframe src={content.file_url} className="w-full h-[500px]" title="Arquivo" />}
              </div>
            )}

            {bodyText && (
              <div className="bg-white rounded-xl border border-harven-border p-6">
                <div className="prose prose-sm prose-headings:text-harven-dark prose-headings:font-display prose-strong:text-gray-800 prose-table:text-xs max-w-none text-sm text-gray-700 leading-relaxed">
                  <ReactMarkdown>{bodyText}</ReactMarkdown>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right: Questions Editor */}
        <div className="w-[480px] border-l border-harven-border bg-white overflow-y-auto flex-shrink-0 flex flex-col">
          <div className="p-6 flex-1">
            <div className="flex items-center justify-between mb-5">
              <div>
                <h3 className="text-sm font-bold text-foreground">Questões Socráticas</h3>
                <p className="text-[10px] text-muted-foreground mt-0.5">{questions.length} questões geradas</p>
              </div>
              <button onClick={addQuestion} className="text-xs font-bold text-primary flex items-center gap-1 hover:underline">
                <span className="material-symbols-outlined text-[14px]">add</span>Adicionar
              </button>
            </div>

            <div className="space-y-3">
              {questions.map((q, idx) => (
                <div key={q.id} className={cn(
                  'rounded-xl border p-4 transition-all hover:shadow-sm',
                  difficultyColors[q.difficulty ?? 'medium']?.replace(/text-\S+/, '').trim() || 'border-harven-border',
                  'bg-white border-harven-border'
                )}>
                  {/* Question header */}
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <div className="flex h-6 w-6 items-center justify-center rounded-full bg-harven-dark text-[10px] font-bold text-primary">
                        {idx + 1}
                      </div>
                      <span className="text-xs font-medium text-gray-500">Questão {idx + 1}</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={() => cycleDifficulty(q.id)}
                        className={cn('flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full border cursor-pointer transition-colors', difficultyColors[q.difficulty ?? 'easy'])}
                      >
                        <span className="material-symbols-outlined text-[12px]">{difficultyIcons[q.difficulty ?? 'easy']}</span>
                        {difficultyMap[q.difficulty ?? 'easy']}
                      </button>
                      <button onClick={() => deleteQuestion(q.id)} className="text-gray-300 hover:text-red-500 transition-colors">
                        <span className="material-symbols-outlined text-[16px]">delete</span>
                      </button>
                    </div>
                  </div>

                  {/* Question text */}
                  <textarea
                    value={q.question}
                    onChange={e => updateQuestion(q.id, 'question', e.target.value)}
                    rows={3}
                    placeholder="Escreva a pergunta socrática..."
                    className="w-full bg-harven-bg/50 border border-harven-border rounded-lg px-3 py-2 text-sm text-foreground resize-none focus:ring-2 focus:ring-primary/20 focus:border-primary placeholder:text-gray-400"
                  />

                  {/* Expected answer */}
                  <div className="mt-2">
                    <label className="text-[10px] font-medium text-gray-400 uppercase tracking-wider">Resposta esperada</label>
                    <textarea
                      value={q.expected_answer ?? ''}
                      onChange={e => updateQuestion(q.id, 'expected_answer', e.target.value)}
                      rows={2}
                      placeholder="O que o aluno deveria responder..."
                      className="mt-1 w-full bg-harven-bg/30 border border-dashed border-harven-border rounded-lg px-3 py-2 text-xs text-gray-600 resize-none focus:ring-1 focus:ring-primary/20 focus:border-primary placeholder:text-gray-300"
                    />
                  </div>
                </div>
              ))}

              {questions.length === 0 && (
                <div className="text-center py-12 border-2 border-dashed border-harven-border rounded-xl">
                  <span className="material-symbols-outlined text-4xl text-gray-300">quiz</span>
                  <p className="text-sm text-gray-400 mt-2">Nenhuma questão.</p>
                  <p className="text-xs text-gray-300 mt-1">Clique "Reprocessar IA" ou adicione manualmente.</p>
                </div>
              )}
            </div>
          </div>

          {/* Fixed bottom bar */}
          <div className="p-4 border-t border-harven-border bg-gray-50/50">
            <button
              onClick={save}
              disabled={saving || questions.length === 0}
              className="w-full bg-harven-dark text-white font-bold py-3 rounded-xl disabled:opacity-40 hover:bg-harven-dark/90 transition-colors flex items-center justify-center gap-2"
            >
              <span className="material-symbols-outlined text-[18px]">save</span>
              {saving ? 'Salvando...' : 'Salvar Questões'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
