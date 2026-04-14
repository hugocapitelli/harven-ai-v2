import { useState, useEffect, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { sessionReviewsApi, chatSessionsApi } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import { Button } from '../../components/ui/Button';
import { Card, CardContent, CardHeader } from '../../components/ui/Card';
import { Badge } from '../../components/ui/Badge';
import { Avatar } from '../../components/ui/Avatar';
import { Skeleton, SkeletonText } from '../../components/ui/Skeleton';
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
    case 'reviewed': return { text: 'Avaliado', variant: 'success' as const };
    case 'replied': return { text: 'Respondido', variant: 'success' as const };
    case 'closed': return { text: 'Encerrado', variant: 'outline' as const };
    default: return { text: status, variant: 'outline' as const };
  }
};

function StarInput({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const [hover, setHover] = useState(0);
  return (
    <div className="flex gap-1" role="radiogroup" aria-label="Avaliação">
      {[1, 2, 3, 4, 5].map((star) => (
        <button
          key={star}
          type="button"
          onMouseEnter={() => setHover(star)}
          onMouseLeave={() => setHover(0)}
          onClick={() => onChange(star)}
          className="p-0.5 transition-transform hover:scale-110"
          aria-label={`${star} estrela${star !== 1 ? 's' : ''}`}
        >
          <span
            className={`material-symbols-outlined text-[28px] transition-colors ${
              star <= (hover || value) ? 'fill-1 text-harven-gold' : 'text-muted'
            }`}
          >
            star
          </span>
        </button>
      ))}
    </div>
  );
}

export default function SessionReview() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const [session, setSession] = useState<SessionData | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [review, setReview] = useState<SessionReviewType | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const [rating, setRating] = useState(0);
  const [feedback, setFeedback] = useState('');
  const [instructorMessage, setInstructorMessage] = useState('');

  useEffect(() => {
    if (!sessionId) return;
    const controller = new AbortController();
    const load = async () => {
      try {
        setLoading(true);
        const [msgs, reviewData] = await Promise.all([
          chatSessionsApi.getMessages(sessionId),
          sessionReviewsApi.list(sessionId).catch(() => null),
        ]);
        if (controller.signal.aborted) return;

        const messageList = Array.isArray(msgs) ? msgs : (msgs as Record<string, unknown>)?.messages ?? [];
        setMessages(messageList as ChatMessage[]);

        if (reviewData && typeof reviewData === 'object') {
          const r = Array.isArray(reviewData) ? reviewData[0] : reviewData;
          if (r) {
            setReview(r as SessionReviewType);
            setRating(r.rating ?? 0);
            setFeedback(r.feedback ?? '');
          }
        }

        const sessionInfo = (msgs as Record<string, unknown>)?.session ?? null;
        if (sessionInfo) setSession(sessionInfo as SessionData);
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
    if (!sessionId || rating === 0) { toast.error('Selecione uma avaliação.'); return; }
    setSubmitting(true);
    try {
      const payload = { session_id: sessionId, rating, feedback, reviewer_id: user?.id };
      if (review) {
        await sessionReviewsApi.update(review.id, payload as Record<string, unknown>);
        toast.success('Avaliação atualizada.');
      } else {
        await sessionReviewsApi.create(payload as Record<string, unknown>);
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
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <Button variant="ghost" size="icon" onClick={() => navigate(-1)}>
          <span className="material-symbols-outlined">arrow_back</span>
        </Button>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-display font-bold text-foreground">Revisão de Sessão</h1>
            <Badge variant={status.variant}>{status.text}</Badge>
          </div>
          <p className="text-sm text-muted-foreground">
            {session?.student_name ?? 'Aluno'} · {session?.content_title ?? ''}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-[1fr_380px] gap-6" style={{ height: 'calc(100vh - 220px)' }}>
        {/* Left: Conversation */}
        <Card className="flex flex-col overflow-hidden">
          <CardHeader className="shrink-0 py-3">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-primary">forum</span>
              <h2 className="text-sm font-bold text-foreground">Conversa Socrática</h2>
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
                    className={isStudent ? 'bg-blue-100' : 'bg-accent'}
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
              <h2 className="text-sm font-bold text-foreground">Avaliação</h2>
            </CardHeader>
            <CardContent className="flex flex-col gap-5">
              <div>
                <label className="block text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-2">Nota</label>
                <StarInput value={rating} onChange={setRating} />
              </div>

              <div>
                <label className="block text-[10px] font-bold text-muted-foreground uppercase tracking-widest mb-2">Feedback</label>
                <textarea
                  rows={6}
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                  placeholder="Observações sobre a performance do aluno nesta sessão socrática..."
                  className="w-full bg-harven-bg border-none rounded-lg text-sm text-foreground placeholder-gray-400 focus:ring-1 focus:ring-primary px-4 py-3 resize-none"
                />
              </div>

              <Button onClick={handleSubmitReview} disabled={submitting || rating === 0} fullWidth>
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
