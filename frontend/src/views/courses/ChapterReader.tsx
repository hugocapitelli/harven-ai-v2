// @ts-nocheck
import { useState, useEffect, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import DOMPurify from 'dompurify';
import { contentsApi, questionsApi, aiApi, chatSessionsApi } from '../../services/api';
import { cn } from '../../lib/utils';
import type { Content, Question, ChatMessage } from '../../types';

export default function ChapterReader() {
  const navigate = useNavigate();
  const { courseId, chapterId, contentId } = useParams<{ courseId: string; chapterId: string; contentId: string }>();
  const [content, setContent] = useState<Content | null>(null);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeView, setActiveView] = useState<'text' | 'file'>('text');

  // Chat state
  const [chatOpen, setChatOpen] = useState(false);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [selectedQuestion, setSelectedQuestion] = useState<string | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // Study timer
  const startTime = useRef(Date.now());
  const [studyMinutes, setStudyMinutes] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    (async () => {
      if (!contentId) { setLoading(false); return; }
      try {
        const [contentData, questionsData] = await Promise.all([
          contentsApi.get(contentId),
          questionsApi.list(contentId),
        ]);
        if (ctrl.signal.aborted) return;
        setContent(contentData);
        setQuestions(Array.isArray(questionsData) ? questionsData : []);
      } catch { if (!ctrl.signal.aborted) console.error('Erro ao carregar conteudo'); }
      finally { if (!ctrl.signal.aborted) setLoading(false); }
    })();
    return () => ctrl.abort();
  }, [contentId]);

  // Study timer
  useEffect(() => {
    const interval = setInterval(() => {
      setStudyMinutes(Math.floor((Date.now() - startTime.current) / 60000));
    }, 60000);
    return () => clearInterval(interval);
  }, []);

  // Auto-scroll chat
  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [chatMessages]);

  const startChat = async (questionText: string) => {
    setSelectedQuestion(questionText);
    setChatOpen(true);
    setChatLoading(true);
    try {
      const session = await chatSessionsApi.createOrGet({ content_id: contentId!, chapter_id: chapterId!, course_id: courseId! });
      setSessionId(session.id);
      const msgs = await chatSessionsApi.getMessages(session.id);
      if (Array.isArray(msgs) && msgs.length > 0) {
        setChatMessages(msgs);
      } else {
        const aiResponse = await aiApi.socraticDialogue(session.id, questionText);
        const newMsgs: ChatMessage[] = [
          { id: '1', role: 'user', content: questionText, created_at: new Date().toISOString() },
          { id: '2', role: 'assistant', content: aiResponse?.response ?? 'Hmm, preciso pensar sobre isso...', created_at: new Date().toISOString(), is_ai: true },
        ];
        setChatMessages(newMsgs);
      }
    } catch { toast.error('Erro ao iniciar dialogo'); }
    finally { setChatLoading(false); }
  };

  const sendMessage = async () => {
    if (!chatInput.trim() || !sessionId) return;
    const userMsg: ChatMessage = { id: String(Date.now()), role: 'user', content: chatInput, created_at: new Date().toISOString() };
    setChatMessages(prev => [...prev, userMsg]);
    setChatInput('');
    setChatLoading(true);
    try {
      await chatSessionsApi.addMessage(sessionId, { role: 'user', content: chatInput });
      const aiResponse = await aiApi.socraticDialogue(sessionId, chatInput);
      const aiMsg: ChatMessage = { id: String(Date.now() + 1), role: 'assistant', content: aiResponse?.response ?? 'Interessante ponto de vista...', created_at: new Date().toISOString(), is_ai: true };
      setChatMessages(prev => [...prev, aiMsg]);
    } catch { toast.error('Erro na resposta do tutor'); }
    finally { setChatLoading(false); }
  };

  const markComplete = async () => {
    if (!contentId) return;
    try {
      await contentsApi.update(contentId, { completed: true });
      toast.success('Conteudo marcado como concluido!');
      setContent(prev => prev ? { ...prev, completed: true } : prev);
    } catch { toast.error('Erro ao marcar como concluido'); }
  };

  if (loading) return (
    <div className="max-w-5xl mx-auto p-8 space-y-6">
      <div className="h-4 w-48 bg-gray-200 animate-pulse rounded" />
      <div className="h-8 w-96 bg-gray-200 animate-pulse rounded" />
      <div className="h-96 bg-gray-200 animate-pulse rounded-2xl" />
    </div>
  );

  if (!content) return (
    <div className="flex items-center justify-center h-full"><div className="text-center"><span className="material-symbols-outlined text-6xl text-gray-300">description</span><p className="text-gray-500 mt-2">Conteudo nao encontrado</p><button onClick={() => navigate(-1)} className="mt-4 text-primary font-bold text-sm">Voltar</button></div></div>
  );

  return (
    <div className="flex flex-col h-full animate-in fade-in duration-300">
      {/* Breadcrumb + Header */}
      <div className="bg-white border-b border-harven-border px-8 py-4 flex-shrink-0">
        <nav className="flex items-center gap-2 text-xs text-gray-400 mb-2">
          <button onClick={() => navigate(`/course/${courseId}`)} className="text-harven-gold hover:text-primary-dark">Curso</button>
          <span className="material-symbols-outlined text-[14px]">chevron_right</span>
          <button onClick={() => navigate(`/course/${courseId}/chapter/${chapterId}`)} className="text-harven-gold hover:text-primary-dark">Capitulo</button>
          <span className="material-symbols-outlined text-[14px]">chevron_right</span>
          <span className="text-foreground">{content.title}</span>
        </nav>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button onClick={() => navigate(-1)} className="text-gray-400 hover:text-foreground"><span className="material-symbols-outlined">arrow_back</span></button>
            <h1 className="text-xl font-display font-bold">{content.title}</h1>
            <span className={cn('text-[10px] font-bold px-2 py-0.5 rounded uppercase', content.type === 'VIDEO' ? 'bg-blue-100 text-blue-600' : content.type === 'AUDIO' ? 'bg-purple-100 text-purple-600' : 'bg-green-100 text-green-600')}>{content.type}</span>
          </div>
          <div className="flex items-center gap-3">
            {studyMinutes > 0 && <span className="text-xs text-muted-foreground flex items-center gap-1"><span className="material-symbols-outlined text-[14px]">schedule</span>{studyMinutes} min</span>}
            {!content.completed && <button onClick={markComplete} className="bg-primary hover:bg-primary-dark text-harven-dark font-bold px-4 py-2 rounded-lg text-xs uppercase tracking-widest">Concluir</button>}
            {content.completed && <span className="bg-green-100 text-green-700 text-xs font-bold px-3 py-1 rounded flex items-center gap-1"><span className="material-symbols-outlined text-[14px] fill-1">check_circle</span>Concluido</span>}
          </div>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Main Content */}
        <div className="flex-1 overflow-y-auto p-8">
          <div className="max-w-3xl mx-auto space-y-8">
            {/* View toggle */}
            {content.type === 'TEXT' && content.file_url && (
              <div className="flex bg-muted rounded-lg p-1 gap-1 w-fit">
                <button onClick={() => setActiveView('text')} className={cn('px-3 py-1.5 text-xs font-bold rounded-md', activeView === 'text' ? 'bg-white shadow-sm' : 'text-muted-foreground')}>Modo Leitura</button>
                <button onClick={() => setActiveView('file')} className={cn('px-3 py-1.5 text-xs font-bold rounded-md', activeView === 'file' ? 'bg-white shadow-sm' : 'text-muted-foreground')}>Arquivo Original</button>
              </div>
            )}

            {/* Content render */}
            {content.type === 'VIDEO' && content.file_url && (
              <video controls className="w-full rounded-xl shadow-lg" src={content.file_url}><track kind="captions" /></video>
            )}
            {content.type === 'AUDIO' && content.file_url && (
              <div className="bg-white rounded-xl border border-harven-border p-6"><audio controls className="w-full" src={content.file_url} /></div>
            )}
            {(content.type === 'TEXT' || activeView === 'text') && (content.body || content.extracted_text) && (
              <div className="bg-white rounded-xl border border-harven-border p-8 prose prose-sm max-w-none" dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(content.body || content.extracted_text || '') }} />
            )}
            {activeView === 'file' && content.file_url && content.type === 'TEXT' && (
              <iframe src={content.file_url} className="w-full h-[600px] rounded-xl border" title="Arquivo" />
            )}

            {/* Socratic Questions */}
            {questions.length > 0 && (
              <div className="space-y-4">
                <h3 className="text-lg font-display font-bold flex items-center gap-2"><span className="material-symbols-outlined text-harven-gold">psychology</span>Questoes Socraticas</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  {questions.map(q => (
                    <button key={q.id} onClick={() => startChat(q.question)} disabled={!!selectedQuestion} className={cn('text-left p-4 rounded-xl border transition-all', selectedQuestion === q.question ? 'border-primary bg-primary/5' : 'border-harven-border hover:border-primary/50 bg-white')}>
                      <span className="material-symbols-outlined text-harven-gold text-[20px] mb-2">help</span>
                      <p className="text-sm font-medium line-clamp-3">{q.question}</p>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Chat Panel */}
        {chatOpen && (
          <div className="w-96 border-l border-harven-border bg-white flex flex-col flex-shrink-0">
            <div className="h-14 flex items-center justify-between px-4 border-b border-harven-border">
              <div className="flex items-center gap-2"><span className="material-symbols-outlined text-harven-gold">psychology</span><span className="text-sm font-bold">Tutor Socratico</span></div>
              <button onClick={() => setChatOpen(false)} className="text-gray-400 hover:text-foreground"><span className="material-symbols-outlined text-[20px]">close</span></button>
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {chatMessages.map(msg => (
                <div key={msg.id} className={cn('flex', msg.role === 'user' ? 'justify-end' : 'justify-start')}>
                  <div className={cn('max-w-[80%] rounded-xl px-4 py-2 text-sm', msg.role === 'user' ? 'bg-primary text-harven-dark' : 'bg-harven-bg text-foreground')}>
                    {msg.content}
                  </div>
                </div>
              ))}
              {chatLoading && <div className="flex justify-start"><div className="bg-harven-bg rounded-xl px-4 py-2 text-sm text-gray-400">Pensando<span className="animate-pulse">...</span></div></div>}
              <div ref={chatEndRef} />
            </div>
            <div className="p-4 border-t border-harven-border">
              <div className="flex gap-2">
                <input value={chatInput} onChange={e => setChatInput(e.target.value)} onKeyDown={e => e.key === 'Enter' && !e.shiftKey && sendMessage()} placeholder="Sua resposta..." className="flex-1 bg-harven-bg border-none rounded-lg px-4 py-2 text-sm focus:ring-1 focus:ring-primary" />
                <button onClick={sendMessage} disabled={chatLoading || !chatInput.trim()} className="bg-primary hover:bg-primary-dark text-harven-dark p-2 rounded-lg disabled:opacity-50"><span className="material-symbols-outlined text-[20px]">send</span></button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
