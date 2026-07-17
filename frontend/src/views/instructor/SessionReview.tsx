import { useState, useEffect, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { sessionReviewsApi, chatSessionsApi, usersApi } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import { Button } from '../../components/ui/Button';
import { Card, CardContent, CardHeader } from '../../components/ui/Card';
import { Badge } from '../../components/ui/Badge';
import { Avatar } from '../../components/ui/Avatar';
import { Skeleton, SkeletonText } from '../../components/ui/Skeleton';
import { Textarea } from '../../components/ui/Textarea';
import { PageHeader } from '../../components/ui/PageHeader';
import type { ChatMessage, SessionReview as SessionReviewType } from '../../types';

interface SessionData {
  id: string;
  user_id: string;
  student_name: string;
  content_title?: string;
  status: string;
  created_at: string;
}

const statusLabel = (status: string) => {
  switch (status) {
    case 'pending': return { text: 'Pendente', variant: 'warning' as const };
    case 'pending_student': return { text: 'Aguardando aluno', variant: 'warning' as const };
    case 'reviewed': return { text: 'Avaliado', variant: 'success' as const };
    case 'replied': return { text: 'Respondido', variant: 'success' as const };
    case 'closed': return { text: 'Encerrado', variant: 'outline' as const };
    case 'active': return { text: 'Em andamento', variant: 'outline' as const };
    case 'completed': return { text: 'Concluída', variant: 'success' as const };
    default: return { text: status, variant: 'outline' as const };
  }
};

// GRD-1: the per-session grade is 0–10 (step 0.5), matching
// ``session_reviews.rating`` and the gradebook composition. The old 1–5 star
// picker silently capped every grade at 5.0/10 and deflated the composed grade.
function GradeInput({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const quick = [0, 2, 4, 6, 8, 10];
  const clamp = (v: number) => Math.min(10, Math.max(0, v));
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-3">
        <input
          type="number"
          min="0"
          max="10"
          step="0.5"
          value={Number.isFinite(value) ? value : 0}
          onChange={(e) => {
            const parsed = parseFloat(e.target.value);
            onChange(Number.isNaN(parsed) ? 0 : clamp(parsed));
          }}
          className="w-24 text-center text-2xl font-bold border border-harven-border rounded-lg px-3 py-2 bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          aria-label="Nota de 0 a 10"
        />
        <span className="text-sm text-muted-foreground">/ 10</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {quick.map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => onChange(n)}
            className={`h-7 min-w-[28px] px-2 rounded-md text-xs font-medium transition-colors ${
              value === n
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted text-muted-foreground hover:bg-accent hover:text-accent-foreground'
            }`}
            aria-label={`Nota ${n}`}
          >
            {n}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function SessionReview() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  useAuth();
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const [session, setSession] = useState<SessionData | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [review, setReview] = useState<SessionReviewType | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  // GRD-1: null = "not graded yet"; 0 is a VALID grade on the 0–10 scale, so it
  // can no longer double as the empty sentinel.
  const [rating, setRating] = useState<number | null>(null);
  const [feedback, setFeedback] = useState('');
  const [instructorMessage, setInstructorMessage] = useState('');

  useEffect(() => {
    if (!sessionId) return;
    const controller = new AbortController();
    const load = async () => {
      try {
        setLoading(true);
        const [msgs, reviewData, sessionData] = await Promise.all([
          chatSessionsApi.getMessages(sessionId),
          sessionReviewsApi.get(sessionId).catch(() => null),
          // GET /messages devolve só a lista; a sessão (status, user_id, data)
          // vem de GET /chat-sessions/{id}.
          chatSessionsApi.get(sessionId).catch(() => null),
        ]);
        if (controller.signal.aborted) return;

        const messageList = Array.isArray(msgs) ? msgs : (msgs as Record<string, unknown>)?.messages ?? [];
        setMessages(messageList as ChatMessage[]);

        if (reviewData && typeof reviewData === 'object') {
          const r = Array.isArray(reviewData) ? reviewData[0] : reviewData;
          if (r) {
            setReview(r as SessionReviewType);
            setRating(r.rating ?? null);
            setFeedback(r.feedback ?? '');
          }
        }

        const sessionInfo = (sessionData ?? (msgs as Record<string, unknown>)?.session ?? null) as Record<string, unknown> | null;
        if (sessionInfo) {
          let studentName = (sessionInfo.student_name as string | undefined) ?? '';
          if (!studentName && sessionInfo.user_id) {
            const u = await usersApi.get(String(sessionInfo.user_id)).catch(() => null);
            studentName = ((u as Record<string, unknown> | null)?.name as string | undefined) ?? '';
          }
          if (controller.signal.aborted) return;
          setSession({ ...(sessionInfo as unknown as SessionData), student_name: studentName || 'Aluno' });
        }
      } catch (err) {
        if (controller.signal.aborted) return;
        console.error('Error loading session:', err);
        toast.error('Erro ao carregar sessão.');
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    load();
    return () => controller.abort();
  }, [sessionId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSubmitReview = async () => {
    if (!sessionId || rating == null) { toast.error('Informe uma nota de 0 a 10.'); return; }
    setSubmitting(true);
    try {
      const payload = { rating, feedback };
      if (review) {
        await sessionReviewsApi.update(sessionId, payload as Record<string, unknown>);
        toast.success('Avaliação atualizada.');
      } else {
        await sessionReviewsApi.create(sessionId, payload as Record<string, unknown>);
        toast.success('Avaliação enviada.');
      }
      navigate(-1);
    } catch {
      toast.error('Erro ao enviar avaliação.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleSendMessage = async () => {
    if (!sessionId || !instructorMessage.trim()) return;
    setSubmitting(true);
    try {
      await chatSessionsApi.addMessage(sessionId, { role: 'instructor', content: instructorMessage.trim() } as Record<string, unknown>);
      setMessages((prev) => [...prev, {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: instructorMessage.trim(),
        created_at: new Date().toISOString(),
        is_ai: false,
      }]);
      setInstructorMessage('');
      toast.success('Mensagem enviada.');
    } catch {
      toast.error('Erro ao enviar mensagem.');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto p-8 grid grid-cols-[1fr_380px] gap-6 h-[calc(100vh-100px)]">
        <div className="flex flex-col gap-3"><Skeleton className="h-16 w-full" /><SkeletonText lines={12} /></div>
        <div className="flex flex-col gap-3"><Skeleton className="h-8 w-32" /><Skeleton className="h-32 w-full" /><Skeleton className="h-40 w-full" /></div>
      </div>
    );
  }

  const status = statusLabel(review?.status ?? session?.status ?? 'pending');

  return (
    <div className="max-w-7xl mx-auto p-8 animate-in fade-in duration-500">
      <PageHeader
        title="Revisão de Sessão"
        subtitle={`${session?.student_name ?? 'Aluno'}${session?.content_title ? ' · ' + session.content_title : ''}`}
        backAction={{ onClick: () => navigate(-1) }}
        breadcrumbs={[
          { label: 'Disciplinas', onClick: () => navigate('/instructor') },
          { label: session?.student_name ?? 'Aluno' },
          { label: 'Sessão' },
        ]}
        actions={<Badge variant={status.variant}>{status.text}</Badge>}
        constrained={false}
      />

      <div className="grid grid-cols-[1fr_380px] gap-6" style={{ height: 'calc(100vh - 220px)' }}>
        {/* Left: Conversation */}
        <Card className="flex flex-col overflow-hidden">
          <CardHeader className="shrink-0 py-3">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-primary">forum</span>
              <h2 className="text-sm font-semibold text-foreground">Conversa Socrática</h2>
              <span className="text-xs text-muted-foreground">({messages.length} mensagens)</span>
            </div>
          </CardHeader>
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {messages.map((msg) => {
              const isStudent = msg.role === 'user';
              return (
                <div key={msg.id} className={`flex gap-3 ${isStudent ? '' : 'flex-row-reverse'}`}>
                  <Avatar
                    fallback={isStudent ? 'AL' : 'IA'}
                    size="sm"
                    className={isStudent ? 'bg-harven-dark/10' : 'bg-accent'}
                  />
                  <div
                    className={`max-w-[75%] rounded-xl px-4 py-3 text-sm ${
                      isStudent
                        ? 'bg-muted text-foreground rounded-tl-sm'
                        : 'bg-accent text-accent-foreground rounded-tr-sm'
                    }`}
                  >
                    <p className="whitespace-pre-wrap">{msg.content}</p>
                    <p className="text-[10px] opacity-50 mt-1">
                      {new Date(msg.created_at).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}
                    </p>
                  </div>
                </div>
              );
            })}
            <div ref={messagesEndRef} />
          </div>

          {/* Instructor message input */}
          <div className="p-4 border-t border-border flex gap-2">
            <input
              value={instructorMessage}
              onChange={(e) => setInstructorMessage(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSendMessage()}
              placeholder="Enviar mensagem ao aluno..."
              className="flex-1 bg-harven-bg border-none rounded-lg text-sm px-4 py-2 focus:ring-1 focus:ring-primary"
            />
            <Button size="icon" onClick={handleSendMessage} disabled={submitting || !instructorMessage.trim()}>
              <span className="material-symbols-outlined text-[18px]">send</span>
            </Button>
          </div>
        </Card>

        {/* Right: Review Panel */}
        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader className="py-3">
              <h2 className="text-sm font-semibold text-foreground">Avaliação</h2>
            </CardHeader>
            <CardContent className="flex flex-col gap-5">
              <div>
                <label className="block text-[11px] font-medium text-muted-foreground uppercase tracking-wide mb-2">Nota (0–10)</label>
                <GradeInput value={rating ?? 0} onChange={setRating} />
              </div>

              <Textarea
                label="Feedback"
                rows={6}
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                placeholder="Observações sobre a performance do aluno nesta sessão socrática..."
              />

              <Button onClick={handleSubmitReview} disabled={submitting || rating == null} fullWidth>
                {submitting ? 'Enviando...' : review ? 'Atualizar Avaliação' : 'Enviar Avaliação'}
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="text-xs text-muted-foreground space-y-2">
              <div className="flex justify-between">
                <span>Status da sessão</span>
                <Badge variant={status.variant} className="text-[9px]">{status.text}</Badge>
              </div>
              <div className="flex justify-between">
                <span>Mensagens</span>
                <span className="font-bold text-foreground">{messages.length}</span>
              </div>
              <div className="flex justify-between">
                <span>Criada em</span>
                <span className="font-bold text-foreground">
                  {session?.created_at ? new Date(session.created_at).toLocaleDateString('pt-BR') : '—'}
                </span>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
