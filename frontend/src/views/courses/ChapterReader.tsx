// @ts-nocheck
import { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import ReactMarkdown from 'react-markdown';
import DOMPurify from 'dompurify';
import {
  contentsApi,
  questionsApi,
  aiApi,
  chatSessionsApi,
  ttsApi,
} from '../../services/api';
import { cn } from '../../lib/utils';
import type { Content, Question, ChatMessage, UserRole } from '../../types';

interface ChapterReaderProps {
  userRole?: UserRole;
}

type ViewMode = 'text' | 'file';
type TtsStyle = 'podcast' | 'summary' | 'explanation';

const MAX_INTERACTIONS = 20;
const STUDY_SAVE_INTERVAL_MS = 5 * 60 * 1000; // 5 min

const TYPE_BADGE: Record<string, string> = {
  VIDEO: 'bg-blue-100 text-blue-600',
  AUDIO: 'bg-purple-100 text-purple-600',
  TEXT: 'bg-green-100 text-green-600',
};

const TTS_LABEL: Record<TtsStyle, { label: string; icon: string; desc: string }> = {
  podcast: { label: 'Podcast', icon: 'podcasts', desc: 'Conversacional, ~10 min' },
  summary: { label: 'Resumo', icon: 'summarize', desc: 'Pontos-chave, ~3 min' },
  explanation: { label: 'Explicacao', icon: 'record_voice_over', desc: 'Didatica, ~5 min' },
};

// ---------- Helpers ----------

function extractToc(html: string): { id: string; text: string; level: number }[] {
  if (typeof document === 'undefined' || !html) return [];
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, 'text/html');
  const nodes = Array.from(doc.querySelectorAll('h2, h3'));
  return nodes.map((n, i) => {
    const text = n.textContent?.trim() ?? '';
    const id = n.id || `toc-${i}-${text.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40)}`;
    return { id, text, level: n.tagName === 'H2' ? 2 : 3 };
  });
}

function injectTocAnchors(html: string, toc: { id: string; text: string; level: number }[]): string {
  if (toc.length === 0) return html;
  let out = html;
  toc.forEach((item) => {
    const tag = item.level === 2 ? 'h2' : 'h3';
    const escaped = item.text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const re = new RegExp(`<${tag}([^>]*)>(${escaped})</${tag}>`);
    out = out.replace(re, `<${tag}$1 id="${item.id}">$2</${tag}>`);
  });
  return out;
}

// ---------- Edit Toolbar ----------

function EditToolbar({
  onCommand,
  onSave,
  onCancel,
  saving,
}: {
  onCommand: (cmd: string) => void;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
}) {
  const buttons = [
    { cmd: 'bold', icon: 'format_bold', label: 'Negrito' },
    { cmd: 'italic', icon: 'format_italic', label: 'Italico' },
    { cmd: 'highlight', icon: 'ink_highlighter', label: 'Destacar' },
    { cmd: 'link', icon: 'link', label: 'Link' },
    { cmd: 'image', icon: 'image', label: 'Imagem' },
  ];
  return (
    <div className="sticky top-0 z-20 -mx-8 mb-4 flex items-center gap-1 border-b border-harven-border bg-white/95 px-8 py-2 backdrop-blur">
      {buttons.map((b) => (
        <button
          key={b.cmd}
          type="button"
          title={b.label}
          onClick={() => onCommand(b.cmd)}
          className="flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-harven-bg hover:text-foreground transition-colors"
        >
          <span className="material-symbols-outlined text-[18px]">{b.icon}</span>
        </button>
      ))}
      <div className="ml-auto flex items-center gap-2">
        <button
          onClick={onCancel}
          className="rounded-lg px-3 py-1.5 text-xs font-bold uppercase tracking-wider text-muted-foreground hover:bg-harven-bg transition-colors"
        >
          Cancelar
        </button>
        <button
          disabled={saving}
          onClick={onSave}
          className="flex items-center gap-1 rounded-lg bg-primary hover:bg-primary-dark px-4 py-1.5 text-xs font-bold uppercase tracking-wider text-harven-dark transition-colors disabled:opacity-50"
        >
          <span className="material-symbols-outlined text-[16px]">save</span>
          {saving ? 'Salvando...' : 'Salvar'}
        </button>
      </div>
    </div>
  );
}

// ---------- TOC ----------

function TableOfContents({
  items,
  activeId,
}: {
  items: { id: string; text: string; level: number }[];
  activeId: string | null;
}) {
  if (items.length === 0) return null;
  return (
    <nav className="rounded-xl border border-harven-border bg-white p-4">
      <p className="mb-2 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
        Neste conteudo
      </p>
      <ul className="space-y-1">
        {items.map((item) => (
          <li key={item.id}>
            <a
              href={`#${item.id}`}
              className={cn(
                'block rounded-md px-2 py-1 text-xs transition-colors',
                item.level === 3 && 'pl-4',
                activeId === item.id
                  ? 'bg-primary/10 font-medium text-foreground'
                  : 'text-muted-foreground hover:bg-harven-bg hover:text-foreground',
              )}
            >
              {item.text}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

// ==================== Main ====================

export default function ChapterReader({ userRole }: ChapterReaderProps) {
  const navigate = useNavigate();
  const { courseId, chapterId, contentId } = useParams<{
    courseId: string;
    chapterId: string;
    contentId: string;
  }>();
  const isInstructor = userRole === 'INSTRUCTOR' || userRole === 'ADMIN';

  const [content, setContent] = useState<Content | null>(null);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeView, setActiveView] = useState<ViewMode>('text');

  // Edit mode
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState('');
  const [editBody, setEditBody] = useState('');
  const [savingEdit, setSavingEdit] = useState(false);
  const editorRef = useRef<HTMLDivElement>(null);

  // Chat state
  const [chatOpen, setChatOpen] = useState(false);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [selectedQuestion, setSelectedQuestion] = useState<string | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // TTS
  const [generatingTts, setGeneratingTts] = useState<TtsStyle | null>(null);
  const [ttsUrls, setTtsUrls] = useState<Partial<Record<TtsStyle, string>>>({});

  // TOC scroll spy
  const [activeTocId, setActiveTocId] = useState<string | null>(null);

  // Study timer
  const startTime = useRef(Date.now());
  const lastSaveRef = useRef(Date.now());
  const [studyMinutes, setStudyMinutes] = useState(0);

  // ---- Load content ----
  useEffect(() => {
    const ctrl = new AbortController();
    (async () => {
      if (!contentId) {
        setLoading(false);
        return;
      }
      try {
        const [contentData, questionsData] = await Promise.all([
          contentsApi.get(contentId),
          questionsApi.list(contentId),
        ]);
        if (ctrl.signal.aborted) return;
        setContent(contentData);
        setEditTitle(contentData?.title ?? '');
        setEditBody(contentData?.body ?? contentData?.extracted_text ?? '');
        const rawQ = Array.isArray(questionsData) ? questionsData : [];
        setQuestions(rawQ.map((item: Record<string, unknown>) => ({
          ...item,
          question: item.question || item.question_text || '',
          expected_answer: item.expected_answer || '',
        })));
      } catch {
        if (!ctrl.signal.aborted) {
          toast.error('Erro ao carregar conteudo');
          console.error('Erro ao carregar conteudo');
        }
      } finally {
        if (!ctrl.signal.aborted) setLoading(false);
      }
    })();
    return () => ctrl.abort();
  }, [contentId]);

  // ---- Study timer + auto-save every 5 min ----
  useEffect(() => {
    if (!contentId) return;

    const tickInterval = setInterval(() => {
      setStudyMinutes(Math.floor((Date.now() - startTime.current) / 60000));
    }, 60000);

    const saveInterval = setInterval(() => {
      const elapsed = Math.floor((Date.now() - lastSaveRef.current) / 1000);
      if (elapsed > 0) {
        // TODO: backend endpoint for study time tracking not yet implemented
        lastSaveRef.current = Date.now();
      }
    }, STUDY_SAVE_INTERVAL_MS);

    const handleBeforeUnload = () => {
      const elapsed = Math.floor((Date.now() - lastSaveRef.current) / 1000);
      if (elapsed > 0 && navigator.sendBeacon) {
        navigator.sendBeacon(
          '/api/progress/study-time',
          JSON.stringify({ content_id: contentId, seconds: elapsed }),
        );
      }
    };
    window.addEventListener('beforeunload', handleBeforeUnload);

    return () => {
      clearInterval(tickInterval);
      clearInterval(saveInterval);
      window.removeEventListener('beforeunload', handleBeforeUnload);
      // TODO: backend endpoint for study time tracking not yet implemented
    };
  }, [contentId]);

  // ---- Auto-scroll chat ----
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages, chatLoading]);

  // ---- Sanitize + TOC ----
  const sanitizedHtml = useMemo(() => {
    const raw = content?.body || content?.extracted_text || '';
    if (!raw) return '';
    return DOMPurify.sanitize(raw, { ADD_ATTR: ['target', 'rel'] });
  }, [content?.body, content?.extracted_text]);

  const toc = useMemo(() => extractToc(sanitizedHtml), [sanitizedHtml]);
  const htmlWithAnchors = useMemo(
    () => injectTocAnchors(sanitizedHtml, toc),
    [sanitizedHtml, toc],
  );

  // ---- TOC scroll spy ----
  useEffect(() => {
    if (toc.length === 0 || editing) return;
    const handler = () => {
      let current: string | null = null;
      for (const item of toc) {
        const el = document.getElementById(item.id);
        if (el && el.getBoundingClientRect().top <= 120) current = item.id;
      }
      setActiveTocId(current);
    };
    handler();
    window.addEventListener('scroll', handler, { passive: true });
    return () => window.removeEventListener('scroll', handler);
  }, [toc, editing]);

  // ---- Chat handlers ----

  const interactionsUsed = chatMessages.filter((m) => m.role === 'user').length;
  const remainingInteractions = MAX_INTERACTIONS - interactionsUsed;

  const extractAiText = (r: unknown): string => {
    if (typeof r === 'string') return r;
    if (r && typeof r === 'object') {
      const o = r as Record<string, unknown>;
      // Handle nested: {response: {content: "..."}}
      if (o.response && typeof o.response === 'object') {
        const inner = o.response as Record<string, unknown>;
        if (typeof inner.content === 'string') return inner.content;
      }
      if (typeof o.response === 'string') return o.response;
      if (typeof o.content === 'string') return o.content;
      if (typeof o.message === 'string') return o.message;
    }
    return 'Vamos explorar juntos. O que você pensa?';
  };

  const startChat = async (questionText: string) => {
    if (!contentId || !chapterId || !courseId) return;
    setChatMessages([]);
    setSelectedQuestion(questionText);
    setChatOpen(true);
    setChatLoading(true);
    try {
      const session = await chatSessionsApi.createOrGet({
        content_id: contentId,
        chapter_id: chapterId,
        course_id: courseId,
      });
      const sid = session?.id ?? session?.session_id;
      setSessionId(sid);

      // AI starts the dialogue — student doesn't send the question as a message
      const aiResponse = await aiApi.socraticDialogue({
        student_message: `Quero explorar a seguinte questão: ${questionText}`,
        chapter_content: content?.body || content?.extracted_text || '',
        initial_question: { text: questionText },
        session_id: sid,
        interactions_remaining: 20,
      });
      setChatMessages([
        {
          id: '1',
          role: 'assistant',
          content: extractAiText(aiResponse),
          created_at: new Date().toISOString(),
          is_ai: true,
        },
      ]);
    } catch (err) {
      console.error('Chat start error:', err);
      // Fallback: show a starter message so the chat isn't empty
      setChatMessages([
        {
          id: '1',
          role: 'assistant',
          content: `Vamos explorar juntos: "${questionText}"\n\nO que você pensa sobre isso? Qual seria sua primeira análise?`,
          created_at: new Date().toISOString(),
          is_ai: true,
        },
      ]);
    } finally {
      setChatLoading(false);
    }
  };

  const sendMessage = async () => {
    if (!chatInput.trim() || !sessionId || remainingInteractions <= 0) return;
    const text = chatInput.trim();
    const userMsg: ChatMessage = {
      id: String(Date.now()),
      role: 'user',
      content: text,
      created_at: new Date().toISOString(),
    };
    setChatMessages((prev) => [...prev, userMsg]);
    setChatInput('');
    setChatLoading(true);
    try {
      await chatSessionsApi.addMessage(sessionId, { role: 'user', content: text });
      const aiResponse = await aiApi.socraticDialogue({
        student_message: text,
        chapter_content: content?.body || content?.extracted_text || '',
        initial_question: { text: selectedQuestion || '' },
        session_id: sessionId,
        conversation_history: chatMessages.map(m => ({ role: m.role, content: m.content })),
      });
      const aiMsg: ChatMessage = {
        id: String(Date.now() + 1),
        role: 'assistant',
        content: extractAiText(aiResponse),
        created_at: new Date().toISOString(),
        is_ai: true,
      };
      setChatMessages((prev) => [...prev, aiMsg]);
    } catch {
      toast.error('Erro na resposta do tutor');
    } finally {
      setChatLoading(false);
    }
  };

  // ---- Edit handlers ----

  const handleEditCommand = (cmd: string) => {
    if (cmd === 'link') {
      const url = window.prompt('URL do link:');
      if (url) document.execCommand('createLink', false, url);
    } else if (cmd === 'image') {
      const url = window.prompt('URL da imagem:');
      if (url) document.execCommand('insertImage', false, url);
    } else if (cmd === 'highlight') {
      document.execCommand('backColor', false, '#fff59d');
    } else {
      document.execCommand(cmd, false);
    }
    editorRef.current?.focus();
  };

  const handleSaveEdit = async () => {
    if (!contentId) return;
    setSavingEdit(true);
    try {
      const newBody = editorRef.current?.innerHTML ?? editBody;
      await contentsApi.update(contentId, { title: editTitle, body: newBody });
      setContent((c) => (c ? { ...c, title: editTitle, body: newBody } : c));
      setEditing(false);
      toast.success('Conteudo atualizado');
    } catch {
      toast.error('Erro ao salvar edicao');
    } finally {
      setSavingEdit(false);
    }
  };

  const handleCancelEdit = () => {
    setEditing(false);
    setEditTitle(content?.title ?? '');
    setEditBody(content?.body ?? content?.extracted_text ?? '');
  };

  // ---- TTS ----

  const handleGenerateTts = async (style: TtsStyle) => {
    if (!contentId) return;
    setGeneratingTts(style);
    try {
      const result = await ttsApi.generateSummary(contentId, style);
      const url = result?.audio_url ?? result?.url ?? result?.data?.audio_url;
      if (url) {
        setTtsUrls((prev) => ({ ...prev, [style]: url }));
        toast.success(`${TTS_LABEL[style].label} gerado`);
      } else {
        toast.error('Audio indisponivel');
      }
    } catch {
      toast.error('Erro ao gerar audio');
    } finally {
      setGeneratingTts(null);
    }
  };

  // ---- Mark complete ----

  const markComplete = async () => {
    if (!contentId) return;
    try {
      await contentsApi.update(contentId, { completed: true });
      toast.success('Conteudo marcado como concluido!');
      setContent((prev) => (prev ? { ...prev, completed: true } : prev));
    } catch {
      toast.error('Erro ao marcar como concluido');
    }
  };

  // ---------- Render ----------

  if (loading) {
    return (
      <div className="max-w-5xl mx-auto p-8 space-y-6">
        <div className="h-4 w-48 bg-gray-200 animate-pulse rounded" />
        <div className="h-8 w-96 bg-gray-200 animate-pulse rounded" />
        <div className="h-96 bg-gray-200 animate-pulse rounded-2xl" />
        <div className="flex gap-3">
          <div className="h-24 flex-1 bg-gray-200 animate-pulse rounded-xl" />
          <div className="h-24 flex-1 bg-gray-200 animate-pulse rounded-xl" />
          <div className="h-24 flex-1 bg-gray-200 animate-pulse rounded-xl" />
        </div>
      </div>
    );
  }

  if (!content) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <span className="material-symbols-outlined text-6xl text-gray-300">description</span>
          <p className="text-gray-500 mt-2">Conteudo nao encontrado</p>
          <button
            onClick={() => navigate(-1)}
            className="mt-4 text-primary font-bold text-sm"
          >
            Voltar
          </button>
        </div>
      </div>
    );
  }

  const hasFile = Boolean(content.file_url);

  return (
    <div className="flex flex-col h-full animate-in fade-in duration-300">
      {/* Breadcrumb + Header */}
      <div className="bg-white border-b border-harven-border px-8 py-4 flex-shrink-0">
        <nav className="flex items-center gap-2 text-xs text-gray-400 mb-2">
          <button
            onClick={() => navigate(`/course/${courseId}`)}
            className="text-harven-gold hover:text-primary-dark"
          >
            Curso
          </button>
          <span className="material-symbols-outlined text-[14px]">chevron_right</span>
          <button
            onClick={() => navigate(`/course/${courseId}/chapter/${chapterId}`)}
            className="text-harven-gold hover:text-primary-dark"
          >
            Capitulo
          </button>
          <span className="material-symbols-outlined text-[14px]">chevron_right</span>
          <span className="text-foreground">{content.title}</span>
        </nav>

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4 min-w-0 flex-1">
            <button
              onClick={() => navigate(-1)}
              className="text-gray-400 hover:text-foreground shrink-0"
            >
              <span className="material-symbols-outlined">arrow_back</span>
            </button>
            {editing ? (
              <input
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                className="flex-1 rounded-lg border border-harven-border bg-white px-3 py-1.5 text-xl font-display font-bold focus:border-primary focus:outline-none"
              />
            ) : (
              <h1 className="text-xl font-display font-bold truncate">{content.title}</h1>
            )}
            <span
              className={cn(
                'text-[10px] font-bold px-2 py-0.5 rounded uppercase shrink-0',
                TYPE_BADGE[content.type] ?? TYPE_BADGE.TEXT,
              )}
            >
              {content.type}
            </span>
          </div>

          <div className="flex items-center gap-3 shrink-0">
            {studyMinutes > 0 && (
              <span className="text-xs text-muted-foreground flex items-center gap-1">
                <span className="material-symbols-outlined text-[14px]">schedule</span>
                {studyMinutes} min
              </span>
            )}

            {isInstructor && content.type === 'TEXT' && !editing && (
              <button
                onClick={() => setEditing(true)}
                className="flex items-center gap-1 border border-harven-border bg-white hover:bg-harven-bg text-foreground font-bold px-3 py-2 rounded-lg text-xs uppercase tracking-widest transition-colors"
              >
                <span className="material-symbols-outlined text-[16px]">edit</span>
                Editar
              </button>
            )}

            {!content.completed && !editing && (
              <button
                onClick={markComplete}
                className="bg-primary hover:bg-primary-dark text-harven-dark font-bold px-4 py-2 rounded-lg text-xs uppercase tracking-widest"
              >
                Concluir
              </button>
            )}
            {content.completed && (
              <span className="bg-green-100 text-green-700 text-xs font-bold px-3 py-1 rounded flex items-center gap-1">
                <span className="material-symbols-outlined text-[14px] fill-1">check_circle</span>
                Concluido
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Main Content */}
        <div className="flex-1 overflow-y-auto p-8">
          <div className="max-w-5xl mx-auto">
            <div className="grid grid-cols-1 lg:grid-cols-[1fr_260px] gap-8">
              {/* Column: Content */}
              <div className="min-w-0 space-y-8">
                {/* Edit toolbar */}
                {editing && (
                  <EditToolbar
                    onCommand={handleEditCommand}
                    onSave={handleSaveEdit}
                    onCancel={handleCancelEdit}
                    saving={savingEdit}
                  />
                )}

                {/* View toggle */}
                {content.type === 'TEXT' && hasFile && !editing && (
                  <div className="flex bg-muted rounded-lg p-1 gap-1 w-fit">
                    <button
                      onClick={() => setActiveView('text')}
                      className={cn(
                        'px-3 py-1.5 text-xs font-bold rounded-md',
                        activeView === 'text'
                          ? 'bg-white shadow-sm'
                          : 'text-muted-foreground',
                      )}
                    >
                      Modo Leitura
                    </button>
                    <button
                      onClick={() => setActiveView('file')}
                      className={cn(
                        'px-3 py-1.5 text-xs font-bold rounded-md',
                        activeView === 'file'
                          ? 'bg-white shadow-sm'
                          : 'text-muted-foreground',
                      )}
                    >
                      Arquivo Original
                    </button>
                  </div>
                )}

                {/* Video */}
                {content.type === 'VIDEO' && (
                  <>
                    {content.file_url ? (
                      <video
                        controls
                        className="w-full rounded-xl shadow-lg"
                        src={content.file_url}
                        preload="metadata"
                      >
                        <track kind="captions" />
                      </video>
                    ) : (
                      <div className="aspect-video flex items-center justify-center bg-gray-900 text-white/60 rounded-xl">
                        Video indisponivel
                      </div>
                    )}
                  </>
                )}

                {/* Audio */}
                {content.type === 'AUDIO' && (
                  <div className="bg-white rounded-xl border border-harven-border p-6">
                    <div className="flex items-center gap-4 mb-4">
                      <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-purple-100">
                        <span className="material-symbols-outlined text-3xl text-purple-600">
                          headphones
                        </span>
                      </div>
                      <div className="min-w-0">
                        <p className="text-xs text-muted-foreground">Audio</p>
                        <p className="font-medium truncate">{content.title}</p>
                      </div>
                    </div>
                    {content.file_url ? (
                      <audio controls className="w-full" src={content.file_url} preload="metadata" />
                    ) : (
                      <p className="text-sm text-muted-foreground">Audio indisponivel.</p>
                    )}
                  </div>
                )}

                {/* Text — editing */}
                {content.type === 'TEXT' && editing && (
                  <div
                    ref={editorRef}
                    contentEditable
                    suppressContentEditableWarning
                    className="prose prose-sm max-w-none rounded-xl border border-harven-border bg-white p-8 focus:outline-none focus:ring-2 focus:ring-primary/20 min-h-[400px]"
                    dangerouslySetInnerHTML={{ __html: editBody }}
                  />
                )}

                {/* Text/PDF — read view (Markdown) */}
                {!editing && activeView === 'text' && (content?.body || content?.extracted_text) && (
                  <article className="bg-white rounded-xl border border-harven-border p-8 prose prose-sm prose-headings:text-harven-dark prose-headings:font-display prose-strong:text-gray-800 prose-table:text-xs max-w-none leading-relaxed">
                    <ReactMarkdown>{content.body || content.extracted_text || ''}</ReactMarkdown>
                  </article>
                )}

                {/* Text — HTML fallback (legacy content) */}
                {content.type === 'TEXT' && !editing && activeView === 'text' && sanitizedHtml && !(content?.body || content?.extracted_text) && (
                  <article
                    className="bg-white rounded-xl border border-harven-border p-8 prose prose-sm max-w-none"
                    dangerouslySetInnerHTML={{ __html: htmlWithAnchors }}
                  />
                )}

                {/* Empty state */}
                {!editing && activeView === 'text' && !sanitizedHtml && !(content?.body || content?.extracted_text) && (
                  <div className="bg-white rounded-xl border border-harven-border p-16 text-center">
                    <span className="material-symbols-outlined text-5xl text-gray-300">
                      description
                    </span>
                    <p className="mt-3 text-sm text-muted-foreground">
                      Nenhum conteúdo de texto disponível.
                    </p>
                  </div>
                )}

                {/* Text — file view */}
                {content.type === 'TEXT' && !editing && activeView === 'file' && hasFile && (
                  <iframe
                    src={content.file_url}
                    className="w-full h-[600px] rounded-xl border border-harven-border bg-white"
                    title="Arquivo"
                  />
                )}

                {/* Socratic Questions */}
                {questions.length > 0 && !editing && (
                  <div className="space-y-5">
                    <div>
                      <h3 className="text-lg font-display font-bold flex items-center gap-2">
                        <span className="material-symbols-outlined text-harven-gold">psychology</span>
                        Questões Socráticas
                      </h3>
                      <p className="text-sm text-muted-foreground mt-1">
                        Selecione uma pergunta para iniciar o diálogo com o tutor IA.
                      </p>
                    </div>
                    <div className="space-y-3">
                      {questions.slice(0, 5).map((q, idx) => {
                        const diff = q.difficulty ?? 'medium';
                        const diffLabel = diff === 'easy' ? 'Fácil' : diff === 'hard' ? 'Difícil' : 'Médio';
                        const diffStyle =
                          diff === 'easy'
                            ? 'bg-green-100 text-green-700 border-green-200'
                            : diff === 'hard'
                              ? 'bg-red-100 text-red-700 border-red-200'
                              : 'bg-amber-100 text-amber-700 border-amber-200';
                        const diffIcon = diff === 'easy' ? 'sentiment_satisfied' : diff === 'hard' ? 'local_fire_department' : 'psychology';
                        const isSelected = selectedQuestion === q.question;
                        return (
                          <button
                            key={q.id}
                            onClick={() => !selectedQuestion && startChat(q.question)}
                            disabled={Boolean(selectedQuestion && selectedQuestion !== q.question)}
                            className={cn(
                              'w-full text-left px-5 py-4 rounded-xl border-2 transition-all group',
                              isSelected
                                ? 'border-primary bg-primary/5 shadow-sm'
                                : selectedQuestion
                                  ? 'border-harven-border bg-gray-50 opacity-40 cursor-not-allowed'
                                  : 'border-harven-border hover:border-primary/40 hover:shadow-sm bg-white',
                            )}
                          >
                            <div className="flex items-start gap-4">
                              <div className={cn(
                                'flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold mt-0.5',
                                isSelected ? 'bg-primary text-harven-dark' : 'bg-harven-bg text-muted-foreground group-hover:bg-primary/20'
                              )}>
                                {idx + 1}
                              </div>
                              <div className="flex-1 min-w-0">
                                <p className="text-sm font-medium text-foreground leading-relaxed">{q.question}</p>
                                {q.expected_answer && (
                                  <p className="text-xs text-muted-foreground mt-2 line-clamp-1 italic">💡 {q.expected_answer}</p>
                                )}
                              </div>
                              <div className="flex items-center gap-2 shrink-0">
                                <span className={cn('flex items-center gap-1 text-[10px] font-bold px-2 py-1 rounded-full border', diffStyle)}>
                                  <span className="material-symbols-outlined text-[12px]">{diffIcon}</span>
                                  {diffLabel}
                                </span>
                                <span className={cn(
                                  'material-symbols-outlined text-[18px] transition-colors',
                                  isSelected ? 'text-primary' : 'text-gray-300 group-hover:text-primary/60'
                                )}>
                                  arrow_forward
                                </span>
                              </div>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>

              {/* Column: Sidebar */}
              <aside className="hidden lg:block">
                <div className="sticky top-8 space-y-4">
                  {/* TOC */}
                  {content.type === 'TEXT' && toc.length > 0 && !editing && (
                    <TableOfContents items={toc} activeId={activeTocId} />
                  )}

                  {/* TTS card */}
                  {!editing && (
                    <div className="rounded-xl border border-harven-border bg-white p-4">
                      <div className="mb-3 flex items-center gap-2">
                        <span className="material-symbols-outlined text-harven-gold">mic</span>
                        <p className="text-sm font-bold">Gerar audio</p>
                      </div>
                      <p className="mb-3 text-xs text-muted-foreground">
                        Escute o conteudo em diferentes formatos.
                      </p>
                      <div className="space-y-2">
                        {(Object.keys(TTS_LABEL) as TtsStyle[]).map((style) => {
                          const meta = TTS_LABEL[style];
                          const isGen = generatingTts === style;
                          const url = ttsUrls[style];
                          return (
                            <div key={style}>
                              {url ? (
                                <div className="rounded-lg border border-harven-border p-2">
                                  <p className="mb-1 text-xs font-bold">{meta.label}</p>
                                  <audio src={url} controls className="w-full h-8" />
                                </div>
                              ) : (
                                <button
                                  disabled={Boolean(generatingTts)}
                                  onClick={() => handleGenerateTts(style)}
                                  className="flex w-full items-center justify-between rounded-lg border border-harven-border hover:bg-harven-bg px-3 py-2 text-xs transition-colors disabled:opacity-50"
                                >
                                  <span className="flex items-center gap-2 min-w-0">
                                    <span className="material-symbols-outlined text-[16px] shrink-0">
                                      {meta.icon}
                                    </span>
                                    <span className="text-left min-w-0">
                                      <span className="block font-bold text-foreground">
                                        {meta.label}
                                      </span>
                                      <span className="block text-[10px] text-muted-foreground truncate">
                                        {meta.desc}
                                      </span>
                                    </span>
                                  </span>
                                  {isGen ? (
                                    <span className="h-3 w-3 animate-spin rounded-full border-2 border-primary border-t-transparent shrink-0" />
                                  ) : (
                                    <span className="material-symbols-outlined text-[16px] text-muted-foreground shrink-0">
                                      play_arrow
                                    </span>
                                  )}
                                </button>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* Status card */}
                  <div className="rounded-xl bg-harven-dark p-4 text-white">
                    <p className="text-[10px] uppercase tracking-wider text-white/60">Status</p>
                    <p className="mt-1 font-display text-lg font-bold">
                      {content.completed ? 'Concluido' : 'Em andamento'}
                    </p>
                    {content.completed ? (
                      <div className="mt-2 flex items-center gap-2 text-xs text-primary">
                        <span className="material-symbols-outlined text-[16px]">check_circle</span>
                        Bom trabalho!
                      </div>
                    ) : (
                      <p className="mt-2 text-xs text-white/60">
                        Tempo de estudo registrado automaticamente.
                      </p>
                    )}
                  </div>
                </div>
              </aside>
            </div>
          </div>
        </div>

        {/* Chat Panel */}
        {chatOpen && (
          <div className="w-96 border-l border-harven-border bg-white flex flex-col flex-shrink-0">
            <div className="h-14 flex items-center justify-between px-4 border-b border-harven-border">
              <div className="flex items-center gap-2 min-w-0">
                <span className="material-symbols-outlined text-harven-gold">psychology</span>
                <span className="text-sm font-bold truncate">Tutor Socratico</span>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <span
                  className={cn(
                    'text-xs font-bold',
                    remainingInteractions <= 3 ? 'text-destructive' : 'text-muted-foreground',
                  )}
                >
                  {remainingInteractions}/{MAX_INTERACTIONS}
                </span>
                <button
                  onClick={() => setChatOpen(false)}
                  className="text-gray-400 hover:text-foreground"
                >
                  <span className="material-symbols-outlined text-[20px]">close</span>
                </button>
              </div>
            </div>

            {selectedQuestion && (
              <div className="px-4 py-2 bg-harven-bg border-b border-harven-border">
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  Pergunta
                </p>
                <p className="text-xs text-foreground line-clamp-2">{selectedQuestion}</p>
              </div>
            )}

            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {chatMessages.map((msg) => (
                <div
                  key={msg.id}
                  className={cn(
                    'flex',
                    msg.role === 'user' ? 'justify-end' : 'justify-start',
                  )}
                >
                  <div
                    className={cn(
                      'max-w-[80%] rounded-xl px-4 py-2 text-sm',
                      msg.role === 'user'
                        ? 'bg-primary text-harven-dark'
                        : 'bg-harven-bg text-foreground',
                    )}
                  >
                    {msg.content}
                  </div>
                </div>
              ))}
              {chatLoading && (
                <div className="flex justify-start">
                  <div className="bg-harven-bg rounded-xl px-4 py-3 text-sm text-gray-400 flex gap-1">
                    <span className="h-2 w-2 animate-bounce rounded-full bg-gray-400 [animation-delay:-0.3s]" />
                    <span className="h-2 w-2 animate-bounce rounded-full bg-gray-400 [animation-delay:-0.15s]" />
                    <span className="h-2 w-2 animate-bounce rounded-full bg-gray-400" />
                  </div>
                </div>
              )}
              <div ref={chatEndRef} />
            </div>

            <div className="p-4 border-t border-harven-border">
              {remainingInteractions <= 0 ? (
                <div className="rounded-lg bg-destructive/10 px-3 py-2 text-xs text-destructive text-center">
                  Limite de interacoes atingido nesta sessao.
                </div>
              ) : (
                <div className="flex gap-2">
                  <textarea
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        sendMessage();
                      }
                    }}
                    placeholder="Sua resposta..."
                    rows={1}
                    className="flex-1 bg-harven-bg border-none rounded-lg px-4 py-2 text-sm resize-none focus:ring-1 focus:ring-primary focus:outline-none"
                  />
                  <button
                    onClick={sendMessage}
                    disabled={chatLoading || !chatInput.trim()}
                    className="bg-primary hover:bg-primary-dark text-harven-dark p-2 rounded-lg disabled:opacity-50 shrink-0"
                  >
                    <span className="material-symbols-outlined text-[20px]">send</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
