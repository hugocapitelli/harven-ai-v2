import { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import axios from 'axios';
import { toast } from 'sonner';
import ReactMarkdown from 'react-markdown';
import DOMPurify from 'dompurify';
import {
  contentsApi,
  questionsApi,
  aiApi,
  chatSessionsApi,
  ttsApi,
  userStatsApi,
} from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import { cn } from '../../lib/utils';
import type { Content, ContentType, Question, ChatMessage, UserRole } from '../../types';

interface ChapterReaderProps {
  userRole?: UserRole;
}

type ViewMode = 'text' | 'file';
type TtsStyle = 'podcast' | 'summary' | 'explanation';

const MAX_INTERACTIONS = 3;
const STUDY_SAVE_INTERVAL_MS = 5 * 60 * 1000; // 5 min

// Keys are the NORMALIZED (lowercase) content types from the shared contract.
// `normalizeType` collapses any legacy uppercase value onto these keys.
const TYPE_BADGE: Record<string, string> = {
  video: 'bg-harven-dark/10 text-harven-dark',
  audio: 'bg-harven-gold/10 text-harven-gold',
  image: 'bg-blue-100 text-blue-600',
  text: 'bg-green-100 text-green-600',
};

// Human-facing label per normalized type (badge text).
const TYPE_LABEL: Record<string, string> = {
  video: 'VIDEO',
  audio: 'AUDIO',
  image: 'IMAGEM',
  text: 'TEXTO',
  pdf: 'PDF',
  summary: 'RESUMO',
};

// The contract already normalizes `type` to lowercase, but the union still admits
// legacy uppercase literals (see types.ts). Fold everything to lowercase so the
// render branches and badge lookups have a single canonical value to match on.
function normalizeType(type: ContentType | undefined): string {
  return (type ?? 'text').toString().toLowerCase();
}

const TTS_LABEL: Record<TtsStyle, { label: string; icon: string; desc: string }> = {
  podcast: { label: 'Podcast', icon: 'podcasts', desc: 'Conversacional, ~10 min' },
  summary: { label: 'Resumo', icon: 'summarize', desc: 'Pontos-chave, ~3 min' },
  explanation: { label: 'Explicacao', icon: 'record_voice_over', desc: 'Didatica, ~5 min' },
};

// ---------- TTS polling (TTSJOB-3 / TTSJOB-4) ----------
//
// Named budget instead of a magic loop-count: ~5 min total, polled every 3s,
// with the FIRST check happening at t=0 (poll -> check -> sleep, not the
// inverse). `maxAttempts` is derived from the budget so the two constants
// never drift apart.
const TTS_POLL_INTERVAL_MS = 3000;
const TTS_POLL_BUDGET_MS = 5 * 60 * 1000; // ~5 min
const TTS_POLL_MAX_ATTEMPTS = Math.ceil(TTS_POLL_BUDGET_MS / TTS_POLL_INTERVAL_MS);
// A single 404/network/5xx blip (e.g. a redeploy mid-poll) must NOT collapse
// the poller (bug #38/#39). Tolerate up to N CONSECUTIVE transient failures —
// the counter resets on every 200 — before falling back.
const TTS_MAX_TRANSIENT_RETRIES = 3;

/** True for a 404, a network error (no response), or a 5xx — the failure
 * modes a backend restart/redeploy produces mid-poll. A 4xx other than 404
 * (e.g. 401/403) is NOT transient — the interceptor already redirects on 401,
 * and 403 signals a real ownership problem, not a blip. */
function isTransientPollError(err: unknown): boolean {
  if (!axios.isAxiosError(err)) return false;
  const status = err.response?.status;
  if (status === undefined) return true; // network/timeout — no response at all
  return status === 404 || status >= 500;
}

function isRateLimitError(err: unknown): boolean {
  return axios.isAxiosError(err) && err.response?.status === 429;
}

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
  const { user } = useAuth();
  const { courseId, chapterId, contentId } = useParams<{
    courseId: string;
    chapterId: string;
    contentId: string;
  }>();
  const isInstructor = userRole === 'INSTRUCTOR' || userRole === 'ADMIN';

  const [content, setContent] = useState<Content | null>(null);
  // Per-student completion is progress, NOT catalog state. This local flag reflects
  // "this student has completed this content" for idempotent, non-reclickable UI.
  // It is seeded from the catalog `completed` flag on load (best-effort) and set on
  // a successful (or soft-success 503) completeContent call — we NEVER write it back
  // to the shared catalog via contentsApi.update.
  const [completed, setCompleted] = useState(false);
  const [completing, setCompleting] = useState(false);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeView, setActiveView] = useState<ViewMode>('text');

  // Student view toggle
  const [studentView, setStudentView] = useState(false);

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
  // SOC-1: the DURABLE lock. Hydrated from the persisted session on load and kept
  // across ``closeChat``/reload (unlike ``selectedQuestion``, which is local modal
  // state). Non-null only while an ``active`` socratic session exists for this
  // content; a ``completed`` session leaves it null so the questions re-enable
  // (SEC-CHAT-3 new-attempt). It is the source of truth for which question is
  // committed and which "Retomar Sessão" reopens.
  const [activeSession, setActiveSession] = useState<{
    id: string;
    initialQuestionText: string | null;
  } | null>(null);
  // GRD-3 (refazer): when the content's most-recent session is ``completed`` (a real
  // finished attempt OR a phantom completed-with-0-turns — GRD-2), we remember it so
  // the panel can offer "Refazer sessão". Its ``initialQuestionText`` lets the new
  // attempt reuse the same fixed question (SOC-1 contract) without a re-pick.
  const [completedSession, setCompletedSession] = useState<{
    id: string;
    initialQuestionText: string | null;
  } | null>(null);
  // TPP-6: pacing/finalization are now the SERVER's source of truth (TPP-5). We
  // store the last ``session_status`` returned by the socratic route instead of
  // deriving the count locally. ``null`` until the first turn resolves.
  const [sessionStatus, setSessionStatus] = useState<{
    interactions_remaining: number;
    should_finalize: boolean;
  } | null>(null);
  // Completion gate: "the student exhausted all socratic interactions for this
  // content". Persisted per user+content in localStorage so the unlock survives
  // a page reload (chat history is not re-hydrated on mount).
  const [tutorDone, setTutorDone] = useState(false);
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
        const [contentData, questionsData, sessionData] = await Promise.all([
          contentsApi.get(contentId),
          questionsApi.list(contentId),
          // SOC-1: hydrate the durable question lock. ``by-content`` 404s when the
          // student has no session for this content — that is the "unlocked" case,
          // not an error, so it must never break the chapter load.
          chatSessionsApi.byContent(contentId).catch(() => null),
        ]);
        if (ctrl.signal.aborted) return;
        setContent(contentData);
        // SOC-1: only an ``active`` session locks the questions. ``completed`` (or a
        // missing session) leaves everything enabled so a new attempt can start
        // fresh with its own question (SEC-CHAT-3).
        if (sessionData && sessionData.status === 'active') {
          setActiveSession({
            id: sessionData.id ?? sessionData.session_id,
            initialQuestionText: sessionData.initial_question_text ?? null,
          });
          setCompletedSession(null);
        } else if (sessionData && sessionData.status === 'completed') {
          // GRD-3: the latest attempt is done — remember it so the panel offers
          // "Refazer sessão" (works for a phantom completed-0-turns session too).
          setActiveSession(null);
          setCompletedSession({
            id: sessionData.id ?? sessionData.session_id,
            initialQuestionText: sessionData.initial_question_text ?? null,
          });
          // Cross-device unlock: a session ``completed`` no SERVIDOR prova que o
          // aluno ja esgotou as interacoes — o gate nao pode depender so do
          // localStorage (outro device obrigava a refazer as 3 interacoes).
          // Hidrata o flag e persiste localmente para os proximos loads.
          setTutorDone(true);
          if (user?.id && contentId) {
            try {
              localStorage.setItem(`harven_socratic_done:${user.id}:${contentId}`, '1');
            } catch { /* best-effort — o flag em memoria ja destrava esta visita */ }
          }
        } else {
          setActiveSession(null);
          setCompletedSession(null);
        }
        // Seed the per-student completion badge from the catalog flag as a best-effort
        // hint (idempotent UI on re-entry). Authoritative per-user progress lives in the
        // progress table via completeContent; this only avoids a blank badge on load.
        setCompleted(Boolean(contentData?.completed));
        setEditTitle(contentData?.title ?? '');
        setEditBody(contentData?.body ?? contentData?.extracted_text ?? '');
        // Pre-populate TTS player if audio was previously generated.
        // TTSJOB-3: `contents.audio_type` (migration 20260707000002) records WHICH
        // style produced this `audio_url` — legacy rows predate the column and
        // come back null/undefined, so they fall back to 'summary' (documented
        // fallback in the migration's Dev Notes). Never hardcode the slot.
        if (contentData?.audio_url) {
          const apiBase = import.meta.env.VITE_API_URL || '';
          const fullUrl = contentData.audio_url.startsWith('/') ? `${apiBase}${contentData.audio_url}` : contentData.audio_url;
          const style: TtsStyle =
            contentData.audio_type === 'podcast' || contentData.audio_type === 'explanation'
              ? contentData.audio_type
              : 'summary';
          setTtsUrls((prev) => ({ ...prev, [style]: fullUrl }));
        }
        const rawQ = Array.isArray(questionsData) ? questionsData : [];
        setQuestions(
          rawQ.map((raw): Question => {
            const item = raw as Record<string, unknown>;
            return {
              ...item,
              id: String(item.id ?? ''),
              question: String(item.question ?? item.question_text ?? ''),
              expected_answer:
                item.expected_answer != null ? String(item.expected_answer) : '',
            } as Question;
          }),
        );
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

  // TPP-6: SERVER is the source of truth for pacing/finalization. Prefer the last
  // ``session_status`` from the socratic route (TPP-5). The local user-message
  // count is only an optimistic fallback BEFORE the first server reply arrives, so
  // the badge isn't blank on open — it is never the authority once the server speaks.
  const localUsed = chatMessages.filter((m) => m.role === 'user').length;
  const remainingInteractions =
    sessionStatus != null
      ? sessionStatus.interactions_remaining
      : Math.max(0, MAX_INTERACTIONS - localUsed);
  const sessionFinalized = sessionStatus?.should_finalize === true;

  // SOC-1: the committed question, durable across close/reload. The persisted
  // ``active`` session is the authority; ``selectedQuestion`` only covers the
  // brief in-flight window between clicking a question and the server echoing it
  // back on the very first start. When null, all questions are enabled.
  const lockedQuestion = activeSession?.initialQuestionText ?? selectedQuestion;

  // Completion gate: when the content has socratic questions, the student must
  // exhaust ALL tutor interactions (MAX_INTERACTIONS) before marking the content
  // as completed. Contents without questions keep the legacy behavior.
  const tutorDoneKey = user?.id && contentId ? `harven_socratic_done:${user.id}:${contentId}` : null;

  // Seed the persisted flag when user/content resolve (and on content change).
  useEffect(() => {
    if (!tutorDoneKey) {
      setTutorDone(false);
      return;
    }
    try {
      setTutorDone(localStorage.getItem(tutorDoneKey) === '1');
    } catch {
      setTutorDone(false);
    }
  }, [tutorDoneKey]);

  // Persist the unlock the moment the server reports zero interactions left.
  useEffect(() => {
    if (sessionStatus != null && sessionStatus.interactions_remaining <= 0) {
      setTutorDone(true);
      // SOC-1: the session reached its end (server-driven). Release the durable
      // lock so the questions re-enable for a fresh attempt (SEC-CHAT-3) — the
      // next ``startChat`` will create a NEW session with the newly chosen question.
      setActiveSession(null);
      if (tutorDoneKey) {
        try {
          localStorage.setItem(tutorDoneKey, '1');
        } catch {
          // best-effort only — the in-memory flag still unlocks this visit
        }
      }
    }
  }, [sessionStatus, tutorDoneKey]);

  const tutorPending = questions.length > 0 && !tutorDone && remainingInteractions > 0;
  const tutorUsed = Math.min(MAX_INTERACTIONS, MAX_INTERACTIONS - remainingInteractions);

  // Pull the server ``session_status`` out of a socratic response, tolerating the
  // same nesting variants ``extractAiText`` handles.
  const extractSessionStatus = (
    r: unknown,
  ): { interactions_remaining: number; should_finalize: boolean } | null => {
    if (r && typeof r === 'object') {
      const o = r as Record<string, unknown>;
      const ss = o.session_status;
      if (ss && typeof ss === 'object') {
        const s = ss as Record<string, unknown>;
        const remaining = s.interactions_remaining;
        const finalize = s.should_finalize;
        if (typeof remaining === 'number') {
          return {
            interactions_remaining: remaining,
            should_finalize: finalize === true,
          };
        }
      }
    }
    return null;
  };

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

  // SOC-1 (revises H3 / bug #21): closing the chat tears down the MODAL state
  // (messages, input, pacing, transient selection) but NO LONGER clears the
  // DURABLE lock. Bug #21's original fix re-enabled every question on close by
  // resetting the local ``selectedQuestion`` gate; that is exactly what this goal
  // reverts — while an ``active`` session exists (``activeSession``), the other
  // questions stay disabled and the chosen one offers "Retomar Sessão" after
  // close. The lock lives in ``activeSession`` (persisted), so it survives close
  // and reload; it is cleared only when the session completes (see below).
  const closeChat = () => {
    setChatOpen(false);
    setSelectedQuestion(null);
    setSessionId(null);
    setChatMessages([]);
    setSessionStatus(null);
    setChatInput('');
  };

  const startChat = async (questionText: string) => {
    if (!contentId || !chapterId || !courseId) return;
    setChatMessages([]);
    setSessionStatus(null); // TPP-6: reset server pacing for the new session
    setSelectedQuestion(questionText);
    setChatOpen(true);
    setChatLoading(true);
    try {
      // SOC-1: send the committed question so it is persisted on creation.
      const session = await chatSessionsApi.createOrGet({
        content_id: contentId,
        chapter_id: chapterId,
        course_id: courseId,
        initial_question_text: questionText,
      });
      const sid = session?.id ?? session?.session_id;
      setSessionId(sid);
      // SOC-1: the SERVER's stored question is the source of truth (first-write-wins
      // means a returning session may echo a DIFFERENT, original question than the
      // one just clicked). Adopt it and register the durable lock.
      const serverQuestion = session?.initial_question_text ?? questionText;
      setSelectedQuestion(serverQuestion);
      setActiveSession({ id: sid, initialQuestionText: serverQuestion });

      // AI starts the dialogue — student doesn't send the question as a message.
      // TPP-6: do NOT hardcode interactions_remaining — the server derives pacing
      // from the persisted message count (TPP-5).
      const aiResponse = await aiApi.socraticDialogue({
        student_message: `Quero explorar a seguinte questão: ${serverQuestion}`,
        chapter_content: content?.body || content?.extracted_text || '',
        initial_question: { text: serverQuestion },
        session_id: sid,
        // GRD-4: this is the opening trigger, not a student answer — it must NOT
        // consume an interaction. The server skips counting the kickoff turn.
        is_kickoff: true,
      });
      // TPP-6: adopt the server's pacing/finalization as the source of truth.
      setSessionStatus(extractSessionStatus(aiResponse));
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

  // GRD-3: "Refazer sessão" — the student is trapped on a ``completed`` session (a
  // finished attempt OR a phantom completed-with-0-turns) with no path back to the
  // questions. This starts a FRESH attempt: it clears the durable + local "done"
  // state (including the ``tutorDone`` localStorage flag that would otherwise keep
  // the panel in a finished state), then delegates to ``startChat`` — which hits the
  // create-or-get endpoint. Because the most-recent session is ``completed``, the
  // backend creates a NEW session row (SEC-CHAT-3 new-attempt), preserving the old
  // one in history for the teacher's grading drill-down (GRD-1). SOC-1 contract: the
  // question is fixed per content, so the new attempt reuses the completed session's
  // ``initialQuestionText`` when known; otherwise the student picks from the list.
  const restartChat = async (questionOverride?: string) => {
    const question =
      questionOverride ??
      completedSession?.initialQuestionText ??
      activeSession?.initialQuestionText ??
      selectedQuestion;
    // Clear the durable "done" state so the panel leaves the finished view.
    setTutorDone(false);
    if (tutorDoneKey) {
      try {
        localStorage.removeItem(tutorDoneKey);
      } catch {
        // best-effort — the in-memory flag reset already unlocks this visit
      }
    }
    setCompletedSession(null);
    setActiveSession(null);
    setSelectedQuestion(null);
    setSessionStatus(null);
    setChatMessages([]);
    // With a completed most-recent session, startChat's create-or-get yields a NEW
    // session (never reactivating the completed one — SEC-CHAT-3). If we know the
    // fixed question, reuse it and open the chat straight away; otherwise fall back
    // to the question list (close the chat so the buttons show, unlocked).
    if (question) {
      await startChat(question);
    } else {
      setChatOpen(false);
    }
  };

  // SOC-1: reopen the EXISTING active session with its persisted transcript. This
  // is the "Retomar Sessão" path — it must NOT fire the socratic kickoff ("Quero
  // explorar a seguinte questão...") again and must NOT create a new session. The
  // kickoff runs ONLY in ``startChat`` for a freshly created session; here we just
  // hydrate history via ``getMessages``. Pacing/finalization are re-derived by the
  // server on the student's NEXT turn (TPP-5/TPP-6), so we don't fabricate them.
  const resumeChat = async () => {
    const sid = activeSession?.id;
    if (!sid) return;
    setChatMessages([]);
    setSessionStatus(null);
    setSelectedQuestion(activeSession?.initialQuestionText ?? null);
    setSessionId(sid);
    setChatOpen(true);
    setChatLoading(true);
    try {
      const history = await chatSessionsApi.getMessages(sid);
      const rows = Array.isArray(history) ? history : [];
      setChatMessages(
        rows.map((raw): ChatMessage => {
          const m = raw as Record<string, unknown>;
          const role = m.role === 'assistant' ? 'assistant' : 'user';
          return {
            id: String(m.id ?? `${role}-${m.created_at ?? Date.now()}`),
            role,
            content: String(m.content ?? ''),
            created_at: String(m.created_at ?? new Date().toISOString()),
            is_ai: role === 'assistant',
          };
        }),
      );
    } catch (err) {
      console.error('Chat resume error:', err);
      toast.error('Erro ao retomar a sessão');
    } finally {
      setChatLoading(false);
    }
  };

  const sendMessage = async () => {
    if (!chatInput.trim() || !sessionId || remainingInteractions <= 0 || sessionFinalized)
      return;
    const text = chatInput.trim();
    const userMsg: ChatMessage = {
      id: String(Date.now()),
      role: 'user',
      content: text,
      created_at: new Date().toISOString(),
    };
    // Optimistic UI: show the student's bubble immediately. The SERVER persists the
    // turn (TPP-4) and owns the count — we never call addMessage here anymore.
    setChatMessages((prev) => [...prev, userMsg]);
    setChatInput('');
    setChatLoading(true);
    try {
      // TPP-6: the student turn is persisted EXCLUSIVELY server-side inside the
      // socratic route (TPP-4). The previous chatSessionsApi.addMessage('user')
      // call was a SECOND persistence of the same turn → removed to stop the
      // double-count. Pacing (interactions_remaining) is also derived server-side
      // (TPP-5), so it is no longer sent.
      const aiResponse = await aiApi.socraticDialogue({
        student_message: text,
        chapter_content: content?.body || content?.extracted_text || '',
        initial_question: { text: selectedQuestion || '' },
        session_id: sessionId,
        conversation_history: chatMessages.map((m) => ({ role: m.role, content: m.content })),
      });
      // TPP-6: adopt the server pacing/finalization from this turn.
      setSessionStatus(extractSessionStatus(aiResponse));
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

  // Re-fetch the `content` row and, if `audio_url` is present, resolve as a
  // SUCCESS via fallback (TTSJOB-3 AC3 / TTSJOB-4 AC2) instead of a terminal
  // failure. Used both when the polling budget is exhausted and when 404s
  // persist past the transient-tolerance window. Returns whether the
  // fallback recovered an audio URL.
  const resolveTtsViaContentFallback = async (style: TtsStyle): Promise<boolean> => {
    if (!contentId) return false;
    try {
      const fresh = await contentsApi.get(contentId);
      const rawUrl = fresh?.audio_url;
      if (!rawUrl) return false;
      const apiBase = import.meta.env.VITE_API_URL || '';
      const fullUrl = rawUrl.startsWith('/') ? `${apiBase}${rawUrl}` : rawUrl;
      setContent((c) => (c ? { ...c, audio_url: rawUrl, audio_type: fresh.audio_type } : c));
      setTtsUrls((prev) => ({ ...prev, [style]: fullUrl }));
      toast.success(`${TTS_LABEL[style].label} gerado`);
      return true;
    } catch {
      return false;
    }
  };

  const handleGenerateTts = async (style: TtsStyle) => {
    if (!contentId) return;
    setGeneratingTts(style);
    try {
      const startResult = await ttsApi.generateSummary(contentId, style);
      const jobId = startResult?.job_id;
      if (!jobId) { toast.error('Erro ao iniciar geracao'); return; }

      const apiBase = import.meta.env.VITE_API_URL || '';
      let transientCount = 0;

      // Poll-then-sleep (TTSJOB-3 AC1): the FIRST status check happens at
      // t=0, before any wait — a job that finishes fast is picked up
      // immediately instead of waiting a full interval for no reason.
      for (let attempt = 0; attempt < TTS_POLL_MAX_ATTEMPTS; attempt++) {
        try {
          const status = await ttsApi.pollJob(jobId);
          transientCount = 0; // any 200 resets the transient-failure window

          if (status?.status === 'done') {
            const rawUrl = status.audio_url;
            const fullUrl = rawUrl?.startsWith('/') ? `${apiBase}${rawUrl}` : rawUrl;
            setTtsUrls((prev) => ({ ...prev, [style]: fullUrl }));
            toast.success(`${TTS_LABEL[style].label} gerado`);
            return;
          }
          if (status?.status === 'error') {
            // A REAL terminal failure from the backend still deserves one last
            // chance at the content fallback — the job may have written
            // audio_url before reporting `error` on a race.
            if (await resolveTtsViaContentFallback(style)) return;
            toast.error(status.detail || 'Erro na geracao de audio');
            return;
          }
          // status === 'processing' (or unrecognized): keep polling.
        } catch (err) {
          if (isRateLimitError(err)) {
            toast.error('Muitas geracoes de audio simultaneas — aguarde e tente novamente.');
            return;
          }
          if (!isTransientPollError(err)) throw err; // real, non-transient error

          transientCount += 1;
          // #38/#39: a single 404/network/5xx blip (redeploy/restart, cold
          // start, race between job creation and first read) must NOT
          // collapse the poller. Tolerate up to TTS_MAX_TRANSIENT_RETRIES
          // CONSECUTIVE misses before giving up on this job and moving to
          // the content fallback.
          if (transientCount > TTS_MAX_TRANSIENT_RETRIES) {
            if (await resolveTtsViaContentFallback(style)) return;
            toast.error('Erro ao consultar geracao de audio — tente novamente.');
            return;
          }
        }
        await new Promise((r) => setTimeout(r, TTS_POLL_INTERVAL_MS));
      }

      // Budget exhausted without a terminal status: the job may already have
      // finished server-side even though polling never caught up — re-fetch
      // `content` before declaring failure (TTSJOB-3 AC3).
      if (await resolveTtsViaContentFallback(style)) return;
      toast.error('Tempo esgotado — tente novamente em instantes.');
    } catch (err) {
      // The 429 concurrency cap is emitted ONLY by the START endpoint
      // (ttsApi.generateSummary at line 627, backend routes_ai.py:1095) — its
      // rejection lands HERE, in the outer catch, not in the poll loop (the
      // status endpoint never returns 429). Surface the specific guidance
      // instead of the generic failure toast.
      if (isRateLimitError(err)) {
        toast.error('Muitas geracoes de audio simultaneas — aguarde e tente novamente.');
        return;
      }
      toast.error('Erro ao gerar audio');
    } finally {
      // #39: reset the loading state on EVERY exit path (success, real
      // failure, timeout, network error, exception) so the button never
      // stays stuck on "gerando".
      setGeneratingTts(null);
    }
  };

  // ---- Mark complete ----
  //
  // B2 (bug #24): completion is PER-STUDENT progress, not catalog state. We call
  // userStatsApi.completeContent(user.id, courseId, contentId) — scoped to the
  // authenticated user's id (from the auth session, never from props/mutable UI) —
  // plus chatSessionsApi.complete(sessionId) to close any active socratic session.
  // We NEVER call contentsApi.update({ completed }): that would contaminate the shared
  // catalog for every student. A 503 (progress table absent) is treated as SOFT-SUCCESS:
  // the visual completion proceeds and we log the graceful degradation for diagnosis.

  const markComplete = async () => {
    if (!contentId || !courseId || !user?.id || completing || completed) return;
    if (tutorPending) {
      toast.error(`Finalize as ${MAX_INTERACTIONS} interacoes com o Tutor Socratico antes de concluir (${tutorUsed}/${MAX_INTERACTIONS}).`);
      return;
    }
    setCompleting(true);
    try {
      await userStatsApi.completeContent(user.id, courseId, contentId);
      setCompleted(true);
      toast.success('Conteudo marcado como concluido!');
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 503) {
        // Soft-success: optional progress/certificate tables are not provisioned.
        // Complete visually and record the degradation instead of blocking the student.
        console.warn(
          '[ChapterReader] completeContent degraded gracefully (503, progress table absent) — treating as soft-success',
        );
        setCompleted(true);
        toast.success('Conteudo marcado como concluido!');
      } else {
        toast.error('Erro ao marcar como concluido');
        setCompleting(false);
        return;
      }
    }
    // Close the associated chat session (best-effort — never blocks completion).
    if (sessionId) {
      try {
        await chatSessionsApi.complete(sessionId);
      } catch {
        console.warn('[ChapterReader] chatSessionsApi.complete failed (non-blocking)');
      }
    }
    setCompleting(false);
    // NOTE (out of scope, documented follow-up): course-completion certificate
    // emission (userStatsApi.issueCertificate) is intentionally NOT wired here.
    // See docs/stories/epic-front/sf-3.md — course-completion detection is a
    // separate follow-up; this handler closes per-content completion only.
  };

  // ---- Reprocess with AI ----

  const [reprocessing, setReprocessing] = useState(false);

  const handleReprocess = async () => {
    if (!contentId || !content?.body) return;
    setReprocessing(true);
    try {
      // H4 (bug #23): route through the shared, authenticated axios instance
      // (aiApi.reprocessContent → POST /api/ai/reprocess-content). The previous raw
      // fetch read sessionStorage.getItem('access_token') — the WRONG key (the real
      // session token lives under 'harven-access-token' and is injected by the axios
      // interceptor), so the request reached the backend without a valid credential.
      const data = await aiApi.reprocessContent(contentId) as { body?: string } | null;
      if (data?.body) {
        setContent((prev) => (prev ? { ...prev, body: data.body } : prev));
        toast.success('Conteudo reprocessado com IA!');
      } else {
        toast.info('IA nao conseguiu melhorar o conteudo.');
      }
    } catch {
      toast.error('Erro ao reprocessar com IA');
    } finally {
      setReprocessing(false);
    }
  };

  // ---- Save progress (instructor) ----

  const [savingProgress, setSavingProgress] = useState(false);

  const handleSaveProgress = async () => {
    if (!contentId || !content) return;
    setSavingProgress(true);
    try {
      await contentsApi.update(contentId, { body: content.body });
      toast.success('Progresso salvo!');
    } catch {
      toast.error('Erro ao salvar progresso');
    } finally {
      setSavingProgress(false);
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
            onClick={() => navigate(`/course/${courseId}/chapter/${chapterId}`)}
            className="mt-4 text-primary font-bold text-sm"
          >
            Voltar
          </button>
        </div>
      </div>
    );
  }

  const hasFile = Boolean(content.file_url);
  // Canonical lowercase type for all render branches / badge lookups (contract is
  // already normalized; this folds any residual legacy uppercase to be safe).
  const normType = normalizeType(content.type);

  // UI mode guards
  const showInstructorUI = isInstructor && !studentView;
  const isStudentExperience = !isInstructor || studentView;

  return (
    <div className="flex flex-col h-full animate-in fade-in duration-300">
      {/* Breadcrumb + Header */}
      <div className={cn(
        'bg-white border-b border-harven-border flex-shrink-0',
        isStudentExperience ? 'px-8 py-5' : 'px-8 py-4',
      )}>
        {/* Breadcrumb — hidden for student experience */}
        {!isStudentExperience && (
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
        )}

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4 min-w-0 flex-1">
            <button
              onClick={() => navigate(`/course/${courseId}/chapter/${chapterId}`)}
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
              <h1 className={cn(
                'font-display font-bold truncate',
                isStudentExperience ? 'text-2xl' : 'text-xl',
              )}>
                {content.title}
              </h1>
            )}
            <span
              className={cn(
                'text-[10px] font-bold px-2 py-0.5 rounded uppercase shrink-0',
                TYPE_BADGE[normType] ?? TYPE_BADGE.text,
              )}
            >
              {TYPE_LABEL[normType] ?? normType.toUpperCase()}
            </span>
          </div>

          <div className={cn(
            'flex items-center shrink-0',
            isStudentExperience ? 'gap-2' : 'gap-3',
          )}>
            {/* Study timer — hidden for student experience */}
            {!isStudentExperience && studyMinutes > 0 && (
              <span className="text-xs text-muted-foreground flex items-center gap-1">
                <span className="material-symbols-outlined text-[14px]">schedule</span>
                {studyMinutes} min
              </span>
            )}

            {isInstructor && (
              <button
                onClick={() => setStudentView(v => !v)}
                className={`flex items-center gap-1.5 border rounded-lg px-3 py-2 text-xs uppercase tracking-widest font-bold transition-colors ${
                  studentView
                    ? 'bg-harven-dark/10 border-harven-dark/30 text-harven-dark'
                    : 'border-harven-border bg-white hover:bg-harven-bg text-foreground'
                }`}
              >
                <span className="material-symbols-outlined text-[16px]">{studentView ? 'visibility_off' : 'visibility'}</span>
                {studentView ? 'Visao Professor' : 'Visao Aluno'}
              </button>
            )}

            {showInstructorUI && !editing && (
              <>
                {/* Reprocess with AI */}
                <button
                  onClick={handleReprocess}
                  disabled={reprocessing}
                  className="flex items-center gap-1.5 border border-harven-dark/30 bg-harven-dark/10 hover:bg-harven-dark/20 text-harven-dark font-bold px-3 py-2 rounded-lg text-xs uppercase tracking-widest transition-colors disabled:opacity-50"
                  title="Reprocessar texto com IA para melhorar formatação"
                >
                  <span className={`material-symbols-outlined text-[16px] ${reprocessing ? 'animate-spin' : ''}`}>
                    {reprocessing ? 'progress_activity' : 'auto_fix_high'}
                  </span>
                  {reprocessing ? 'Processando...' : 'Reprocessar IA'}
                </button>

                {/* Save progress */}
                <button
                  onClick={handleSaveProgress}
                  disabled={savingProgress}
                  className="flex items-center gap-1.5 border border-harven-border bg-white hover:bg-harven-bg text-foreground font-bold px-3 py-2 rounded-lg text-xs uppercase tracking-widest transition-colors disabled:opacity-50"
                  title="Salvar alterações no conteúdo"
                >
                  <span className={`material-symbols-outlined text-[16px] ${savingProgress ? 'animate-spin' : ''}`}>
                    {savingProgress ? 'progress_activity' : 'save'}
                  </span>
                  {savingProgress ? 'Salvando...' : 'Salvar'}
                </button>

                {/* Edit mode */}
                {normType === 'text' && (
                  <button
                    onClick={() => setEditing(true)}
                    className="flex items-center gap-1 border border-harven-border bg-white hover:bg-harven-bg text-foreground font-bold px-3 py-2 rounded-lg text-xs uppercase tracking-widest transition-colors"
                  >
                    <span className="material-symbols-outlined text-[16px]">edit</span>
                    Editar
                  </button>
                )}
              </>
            )}

            {/* Concluir — prominent in student experience. Idempotent, non-reclickable:
                once completed (success or 503 soft-success) the button becomes a badge. */}
            {!completed && !editing && (
              <button
                onClick={markComplete}
                disabled={completing || tutorPending}
                title={tutorPending ? `Finalize as ${MAX_INTERACTIONS} interacoes com o Tutor Socratico para liberar a conclusao` : undefined}
                className={cn(
                  'bg-primary hover:bg-primary-dark text-harven-dark font-bold rounded-lg text-xs uppercase tracking-widest transition-colors disabled:opacity-50 disabled:cursor-not-allowed',
                  isStudentExperience
                    ? 'px-8 py-2.5 text-sm'
                    : 'px-4 py-2',
                )}
              >
                {completing
                  ? 'Concluindo...'
                  : tutorPending
                    ? `Tutor Socratico ${tutorUsed}/${MAX_INTERACTIONS} para concluir`
                    : 'Concluir'}
              </button>
            )}
            {completed && (
              <span className={cn(
                'bg-green-100 text-green-700 font-bold rounded flex items-center gap-1',
                isStudentExperience
                  ? 'text-sm px-4 py-1.5'
                  : 'text-xs px-3 py-1',
              )}>
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
                {normType === 'text' && hasFile && !editing && (
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
                {normType === 'video' && (
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
                {normType === 'audio' && (
                  <div className="bg-white rounded-xl border border-harven-border p-6">
                    <div className="flex items-center gap-4 mb-4">
                      <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-harven-gold/10">
                        <span className="material-symbols-outlined text-3xl text-harven-gold">
                          headphones
                        </span>
                      </div>
                      <div className="min-w-0">
                        <p className="text-xs text-muted-foreground">Audio</p>
                        <p className="font-medium truncate">{content.title}</p>
                      </div>
                    </div>
                    {content.file_url || content.audio_url ? (
                      <audio
                        controls
                        className="w-full"
                        src={content.file_url || content.audio_url}
                        preload="metadata"
                      />
                    ) : (
                      <p className="text-sm text-muted-foreground">Audio indisponivel.</p>
                    )}
                  </div>
                )}

                {/* Image */}
                {normType === 'image' && (
                  <div className="bg-white rounded-xl border border-harven-border p-4">
                    {content.file_url ? (
                      <img
                        src={content.file_url}
                        alt={content.title}
                        className="w-full rounded-xl object-contain"
                      />
                    ) : (
                      <div className="aspect-video flex items-center justify-center bg-gray-100 text-muted-foreground rounded-xl">
                        Imagem indisponivel
                      </div>
                    )}
                  </div>
                )}

                {/* Text — editing */}
                {normType === 'text' && editing && (
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
                  <article className="bg-white rounded-xl border border-harven-border px-10 py-8 prose prose-lg prose-headings:text-harven-dark prose-headings:font-display prose-headings:mt-8 prose-headings:mb-4 prose-strong:text-gray-800 prose-p:text-gray-700 prose-p:leading-7 prose-table:text-xs max-w-none leading-relaxed">
                    <ReactMarkdown>{content.body || content.extracted_text || ''}</ReactMarkdown>
                  </article>
                )}

                {/* Text — HTML fallback (legacy content) */}
                {normType === 'text' && !editing && activeView === 'text' && sanitizedHtml && !(content?.body || content?.extracted_text) && (
                  <article
                    className="bg-white rounded-xl border border-harven-border p-8 prose prose-sm max-w-none"
                    dangerouslySetInnerHTML={{ __html: htmlWithAnchors }}
                  />
                )}

                {/* Empty state — only for text-like content (media types render their
                    own player/fallback above, so no spurious "no text" notice there). */}
                {(normType === 'text' || normType === 'pdf' || normType === 'summary') &&
                  !editing && activeView === 'text' && !sanitizedHtml && !(content?.body || content?.extracted_text) && (
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
                {normType === 'text' && !editing && activeView === 'file' && hasFile && (
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
                      <p className="text-sm text-muted-foreground mt-2">
                        Selecione uma pergunta para iniciar o diálogo com o tutor IA.
                      </p>
                    </div>

                    {/* GRD-3: the content's most-recent session is completed (a finished
                        attempt or a phantom completed-with-0-turns) and the chat is closed
                        — surface an explicit "Refazer sessão" so the student is never
                        trapped without a path back to the tutor. Starts a fresh attempt
                        (new session row) with the same fixed question when known. */}
                    {completedSession && !activeSession && !chatOpen && (
                      <div className="flex items-center justify-between gap-3 rounded-xl border border-primary/30 bg-primary/5 px-4 py-3">
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-foreground">Sessão anterior concluída</p>
                          <p className="text-xs text-muted-foreground mt-0.5">
                            Você já concluiu esta sessão. Refaça para conversar novamente com o tutor.
                          </p>
                        </div>
                        <button
                          onClick={() => restartChat()}
                          disabled={chatLoading}
                          className="flex items-center gap-1.5 shrink-0 bg-primary hover:bg-primary-dark text-harven-dark font-bold rounded-lg text-xs uppercase tracking-widest px-4 py-2.5 transition-colors disabled:opacity-50"
                        >
                          <span className="material-symbols-outlined text-[16px]">restart_alt</span>
                          Refazer sessao
                        </button>
                      </div>
                    )}
                    <div className="space-y-3">
                      {questions.slice(0, 5).map((q, idx) => {
                        const diff = q.difficulty ?? 'medium';
                        const diffLabel = diff === 'easy' ? 'Fácil' : diff === 'hard' ? 'Difícil' : 'Médio';
                        const diffStyle =
                          diff === 'easy'
                            ? 'bg-green-100 text-green-700 border-green-200'
                            : diff === 'hard'
                              ? 'bg-red-100 text-red-700 border-red-200'
                              : 'bg-orange-100 text-orange-700 border-orange-200';
                        const diffIcon = diff === 'easy' ? 'sentiment_satisfied' : diff === 'hard' ? 'local_fire_department' : 'psychology';
                        // SOC-1: gate on the DURABLE lock (``lockedQuestion``), not the
                        // transient local selection. ``isSelected`` = this is the
                        // committed question. ``isDisabledByLock`` = another question is
                        // committed, so this one is blocked. ``canResume`` = the committed
                        // question, with a live session, while the chat is closed → offer
                        // "Retomar Sessão" instead of a fresh dialogue.
                        const isSelected = lockedQuestion === q.question;
                        const isDisabledByLock = Boolean(lockedQuestion && lockedQuestion !== q.question);
                        const canResume = isSelected && Boolean(activeSession) && !chatOpen;
                        return (
                          <button
                            key={q.id}
                            onClick={() => {
                              if (isDisabledByLock) return;
                              if (canResume) {
                                resumeChat();
                              } else if (!lockedQuestion) {
                                startChat(q.question);
                              }
                            }}
                            disabled={isDisabledByLock}
                            className={cn(
                              'w-full text-left px-5 py-4 rounded-xl border-2 transition-all group',
                              isSelected
                                ? 'border-primary bg-primary/5 shadow-sm'
                                : lockedQuestion
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
                                {/* SOC-1: the committed question, chat closed → the CTA
                                    is "Retomar Sessão" (reopens the same session), not a
                                    fresh-dialogue arrow. */}
                                {canResume ? (
                                  <span className="flex items-center gap-1 text-[11px] font-bold px-2 py-1 rounded-full bg-primary/10 text-primary border border-primary/30">
                                    <span className="material-symbols-outlined text-[13px]">history</span>
                                    Retomar Sessão
                                  </span>
                                ) : (
                                  <span className={cn(
                                    'material-symbols-outlined text-[18px] transition-colors',
                                    isSelected ? 'text-primary' : 'text-gray-300 group-hover:text-primary/60'
                                  )}>
                                    arrow_forward
                                  </span>
                                )}
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
                  {normType === 'text' && toc.length > 0 && !editing && (
                    <TableOfContents items={toc} activeId={activeTocId} />
                  )}

                  {/* TTS card — students see player only, instructors see player + generate */}
                  {!editing && (Object.keys(ttsUrls).length > 0 || !isStudentExperience) && (
                    <div className="rounded-xl border border-harven-border bg-white overflow-hidden">
                      <div className="border-t-4 border-harven-gold" />
                      <div className="p-4">
                        <div className="mb-3 flex items-center gap-2">
                          <span className="material-symbols-outlined text-harven-gold">
                            {isStudentExperience ? 'headphones' : 'mic'}
                          </span>
                          <p className="text-sm font-bold">
                            {isStudentExperience ? 'Audio do conteudo' : 'Gerar audio'}
                          </p>
                        </div>
                        <p className="mb-3 text-xs text-muted-foreground">
                          Escute o conteudo em diferentes formatos.
                        </p>
                        <div className="space-y-2">
                          {(Object.keys(TTS_LABEL) as TtsStyle[]).map((style) => {
                            const meta = TTS_LABEL[style];
                            const isGen = generatingTts === style;
                            const url = ttsUrls[style];
                            // Students only see audio that exists; instructors see generate buttons too
                            if (!url && isStudentExperience) return null;
                            return (
                              <div key={style}>
                                {url ? (
                                  <div className="rounded-lg border border-harven-border p-2">
                                    <div className="mb-1 flex items-center justify-between">
                                      <p className="text-xs font-bold">{meta.label}</p>
                                      {!isStudentExperience && (
                                        <button
                                          type="button"
                                          disabled={Boolean(generatingTts)}
                                          onClick={() => { setTtsUrls((prev) => { const next = { ...prev }; delete next[style]; return next; }); handleGenerateTts(style); }}
                                          className="inline-flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
                                        >
                                          <span className="material-symbols-outlined text-sm">refresh</span>
                                          Regerar
                                        </button>
                                      )}
                                    </div>
                                    <audio
                                      src={url.startsWith('http') ? url : `${import.meta.env.VITE_API_URL || ''}${url}`}
                                      controls
                                      className="w-full h-8"
                                      onError={() => {
                                        // Dead file (e.g. container redeploy wiped /uploads):
                                        // drop the slot so students never see a broken player
                                        // and instructors get the generate button back.
                                        setTtsUrls((prev) => {
                                          const next = { ...prev };
                                          delete next[style];
                                          return next;
                                        });
                                      }}
                                    />
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
                    </div>
                  )}

                  {/* Status card */}
                  <div className={cn(
                    'rounded-xl p-4 text-white',
                    completed ? 'bg-gradient-to-br from-green-700 to-green-900' : 'bg-harven-dark',
                  )}>
                    <p className="text-[10px] uppercase tracking-wider text-white/60">Status</p>
                    <p className="mt-1 font-display text-lg font-bold">
                      {completed ? 'Concluido' : 'Em andamento'}
                    </p>
                    {completed ? (
                      <div className="mt-2 flex items-center gap-2 text-sm text-green-200">
                        <span className="material-symbols-outlined text-[18px] fill-1">check_circle</span>
                        Bom trabalho!
                      </div>
                    ) : (
                      <div className="mt-3">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="h-2 w-2 rounded-full bg-primary animate-pulse" />
                          <p className="text-xs text-white/80">Leitura em progresso</p>
                        </div>
                        <p className="text-[10px] text-white/50">
                          Tempo de estudo registrado automaticamente.
                        </p>
                      </div>
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
                  onClick={closeChat}
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
              {sessionFinalized || remainingInteractions <= 0 ? (
                // TPP-6: the server signalled the end of the session (should_finalize)
                // — the closing synthesis is the last assistant bubble above; disable
                // further input. No new turns once the server finalizes.
                // GRD-3: offer "Refazer sessão" so the student is never trapped on a
                // finished (or phantom) session — it starts a fresh attempt with the
                // same fixed question (the current ``selectedQuestion``), preserving
                // the completed session in the teacher's history.
                <div className="flex flex-col gap-2">
                  <div className="rounded-lg bg-destructive/10 px-3 py-2 text-xs text-destructive text-center">
                    {sessionFinalized
                      ? 'Sessao concluida. Veja a sintese de fechamento acima.'
                      : 'Limite de interacoes atingido nesta sessao.'}
                  </div>
                  <button
                    onClick={() => restartChat(selectedQuestion ?? undefined)}
                    disabled={chatLoading}
                    className="flex items-center justify-center gap-1.5 w-full bg-primary hover:bg-primary-dark text-harven-dark font-bold rounded-lg text-xs uppercase tracking-widest px-4 py-2.5 transition-colors disabled:opacity-50"
                  >
                    <span className="material-symbols-outlined text-[16px]">restart_alt</span>
                    Refazer sessao
                  </button>
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
