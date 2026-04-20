import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { cn } from '@/lib/utils';
import { contentsApi, aiApi } from '@/services/api';

type ContentType = 'TEXT' | 'VIDEO' | 'AUDIO';
type Method = 'ai' | 'manual';
type AiStage = 'connecting' | 'analyzing' | 'generating' | 'done';

interface QuestionDraft {
  id: string;
  question: string;
  expected_answer: string;
  difficulty: 'easy' | 'medium' | 'hard';
}

const FILE_ACCEPT: Record<ContentType, string> = {
  TEXT: '.pdf,.doc,.docx,.txt,.md,.html',
  VIDEO: '.mp4,.mov,.webm',
  AUDIO: '.mp3,.wav,.ogg',
};

const FILE_MAX: Record<ContentType, number> = {
  TEXT: 50 * 1024 * 1024,
  VIDEO: 500 * 1024 * 1024,
  AUDIO: 100 * 1024 * 1024,
};

const TYPE_META: Record<ContentType, { icon: string; label: string; color: string }> = {
  TEXT: { icon: 'article', label: 'Documento', color: 'border-green-400 bg-green-50 text-green-700' },
  VIDEO: { icon: 'play_circle', label: 'Vídeo', color: 'border-blue-400 bg-blue-50 text-blue-700' },
  AUDIO: { icon: 'headphones', label: 'Áudio', color: 'border-purple-400 bg-purple-50 text-purple-700' },
};

const AI_STAGES: { key: AiStage; label: string; icon: string }[] = [
  { key: 'connecting', label: 'Conectando ao modelo de IA...', icon: 'cloud_sync' },
  { key: 'analyzing', label: 'Analisando conteúdo...', icon: 'search' },
  { key: 'generating', label: 'Gerando perguntas socráticas...', icon: 'psychology' },
  { key: 'done', label: 'Processamento concluído!', icon: 'check_circle' },
];

const DIFFICULTY_COLORS: Record<string, string> = {
  easy: 'bg-green-100 text-green-700',
  medium: 'bg-yellow-100 text-yellow-700',
  hard: 'bg-red-100 text-red-700',
};

function uid() {
  return Math.random().toString(36).slice(2, 10);
}

export default function ContentCreation() {
  const { courseId, chapterId } = useParams<{ courseId: string; chapterId: string }>();
  const navigate = useNavigate();
  const abortRef = useRef<AbortController | null>(null);

  // Wizard step
  const [step, setStep] = useState<1 | 2 | 3>(1);

  // Step 1 — Upload
  const [contentType, setContentType] = useState<ContentType>('TEXT');
  const [files, setFiles] = useState<File[]>([]);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadingIdx, setUploadingIdx] = useState(-1);
  const [uploading, setUploading] = useState(false);
  const [uploadedContentId, setUploadedContentId] = useState<string | null>(null);
  const [, setUploadedIds] = useState<string[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Step 2 — Method
  const [method, setMethod] = useState<Method | null>(null);

  // Step 3a — AI processing
  const [aiStage, setAiStage] = useState<AiStage>('connecting');

  // Step 3b — Manual
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [questions, setQuestions] = useState<QuestionDraft[]>([]);
  const [saving, setSaving] = useState(false);

  // Cleanup
  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  // ---- Step 1 handlers ----
  const addFiles = (incoming: FileList | File[]) => {
    const valid = Array.from(incoming).filter((f) => f.size <= FILE_MAX[contentType]);
    if (valid.length) setFiles((prev) => [...prev, ...valid]);
  };

  const removeFile = (idx: number) => setFiles((prev) => prev.filter((_, i) => i !== idx));

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragActive(false);
      addFiles(e.dataTransfer.files);
    },
    [contentType],
  );

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.length) addFiles(e.target.files);
    e.target.value = '';
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const fileIcon = (name: string) => {
    const ext = name.split('.').pop()?.toLowerCase() ?? '';
    if (['pdf'].includes(ext)) return 'picture_as_pdf';
    if (['doc', 'docx'].includes(ext)) return 'description';
    if (['mp4', 'mov', 'webm'].includes(ext)) return 'movie';
    if (['mp3', 'wav', 'ogg'].includes(ext)) return 'audio_file';
    if (['png', 'jpg', 'jpeg', 'gif'].includes(ext)) return 'image';
    return 'insert_drive_file';
  };

  const handleUpload = async () => {
    if (!files.length || !chapterId) return;
    setUploading(true);
    const ids: string[] = [];
    try {
      for (let i = 0; i < files.length; i++) {
        setUploadingIdx(i);
        setUploadProgress(0);
        const f = files[i]!;
        const result = await contentsApi.uploadFile(chapterId, f, setUploadProgress);
        const cId = result?.id ?? result?.content_id ?? result?.data?.id;
        if (cId) ids.push(cId);
      }
      setUploadedIds(ids);
      setUploadedContentId(ids[0] ?? null);
      setStep(2);
    } catch (err) {
      console.error('Upload failed', err);
    } finally {
      setUploading(false);
      setUploadingIdx(-1);
    }
  };

  // ---- Step 2 handler ----
  const handleMethodSelect = (m: Method) => {
    setMethod(m);
    setStep(3);
    if (m === 'ai') startAiProcessing();
  };

  // ---- Step 3a — AI processing ----
  const startAiProcessing = async () => {
    if (!uploadedContentId) return;
    abortRef.current = new AbortController();
    setAiStage('connecting');

    try {
      await new Promise((r) => setTimeout(r, 1200));
      setAiStage('analyzing');
      await new Promise((r) => setTimeout(r, 1500));
      setAiStage('generating');

      await aiApi.generateQuestions({ content_id: uploadedContentId, chapter_content: body ?? '', chapter_title: title, max_questions: 3 });
      setAiStage('done');

      setTimeout(() => {
        navigate(
          `/courses/${courseId}/chapters/${chapterId}/content/${uploadedContentId}/revision`,
        );
      }, 1000);
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        console.error('AI processing failed', err);
        setMethod('manual');
      }
    }
  };

  // ---- Step 3b — Manual ----
  const addQuestion = () => {
    setQuestions((q) => [
      ...q,
      { id: uid(), question: '', expected_answer: '', difficulty: 'medium' },
    ]);
  };

  const removeQuestion = (id: string) => {
    setQuestions((q) => q.filter((x) => x.id !== id));
  };

  const updateQuestion = (id: string, patch: Partial<QuestionDraft>) => {
    setQuestions((q) => q.map((x) => (x.id === id ? { ...x, ...patch } : x)));
  };

  const handleManualSave = async () => {
    if (!chapterId) return;
    setSaving(true);
    try {
      let contentId = uploadedContentId;
      if (!contentId) {
        const result = await contentsApi.create(chapterId, {
          title,
          body,
          content_type: contentType,
        });
        contentId = result?.id ?? result?.data?.id;
      } else {
        await contentsApi.update(contentId, { title, body });
      }

      if (contentId && questions.length > 0) {
        await aiApi.generateQuestions({ content_id: contentId, chapter_content: body ?? '', chapter_title: title, max_questions: questions.length });
      }

      navigate(
        `/courses/${courseId}/chapters/${chapterId}/content/${contentId}/revision`,
      );
    } catch (err) {
      console.error('Save failed', err);
    } finally {
      setSaving(false);
    }
  };

  // ---- Step indicators ----
  const steps = [
    { num: 1, label: 'Upload' },
    { num: 2, label: 'Método' },
    { num: 3, label: method === 'ai' ? 'Processamento' : 'Edição Manual' },
  ];

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      {/* Header */}
      <h1 className="font-display text-2xl font-bold text-foreground">Novo Conteúdo</h1>
      <p className="mt-1 text-sm text-muted-foreground">Adicione material ao capítulo.</p>

      {/* Step indicator */}
      <div className="mt-6 flex items-center gap-2">
        {steps.map((s, i) => (
          <div key={s.num} className="flex items-center gap-2">
            <div
              className={cn(
                'flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold transition-colors',
                step >= s.num
                  ? 'bg-harven-primary text-harven-dark'
                  : 'bg-muted text-muted-foreground',
              )}
            >
              {step > s.num ? (
                <span className="material-symbols-outlined text-base">check</span>
              ) : (
                s.num
              )}
            </div>
            <span
              className={cn(
                'text-sm font-medium',
                step >= s.num ? 'text-foreground' : 'text-muted-foreground',
              )}
            >
              {s.label}
            </span>
            {i < steps.length - 1 && (
              <div className={cn('mx-2 h-px w-8', step > s.num ? 'bg-harven-primary' : 'bg-border')} />
            )}
          </div>
        ))}
      </div>

      {/* ========== STEP 1: Upload ========== */}
      {step === 1 && (
        <div className="mt-8 space-y-6">
          {/* Type selector */}
          <div>
            <label className="mb-2 block text-sm font-medium text-foreground">Tipo de conteúdo</label>
            <div className="flex gap-3">
              {(Object.entries(TYPE_META) as [ContentType, (typeof TYPE_META)[ContentType]][]).map(
                ([key, meta]) => (
                  <button
                    key={key}
                    onClick={() => {
                      setContentType(key);
                      setFiles([]);
                    }}
                    className={cn(
                      'flex items-center gap-2 rounded-xl border-2 px-4 py-2.5 text-sm font-medium transition-all',
                      contentType === key ? meta.color : 'border-border bg-card text-muted-foreground hover:border-muted-foreground/30',
                    )}
                  >
                    <span className="material-symbols-outlined text-lg">{meta.icon}</span>
                    {meta.label}
                  </button>
                ),
              )}
            </div>
          </div>

          {/* Selected files */}
          {files.length > 0 && (
            <div className="space-y-2">
              {files.map((f, i) => (
                <div key={`${f.name}-${i}`} className={cn(
                  'flex items-center gap-3 rounded-xl border bg-card p-3 transition-all',
                  uploading && uploadingIdx === i ? 'border-harven-primary' : 'border-border',
                )}>
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-muted">
                    <span className="material-symbols-outlined text-xl text-muted-foreground">{fileIcon(f.name)}</span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-foreground truncate">{f.name}</p>
                    <p className="text-xs text-muted-foreground">{formatSize(f.size)}</p>
                    {uploading && uploadingIdx === i && (
                      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted">
                        <div className="h-full rounded-full bg-harven-primary transition-all duration-300" style={{ width: `${uploadProgress}%` }} />
                      </div>
                    )}
                  </div>
                  {uploading && uploadingIdx === i ? (
                    <span className="text-xs font-medium text-harven-primary">{uploadProgress}%</span>
                  ) : uploading && i < uploadingIdx ? (
                    <span className="material-symbols-outlined text-lg text-green-500">check_circle</span>
                  ) : !uploading ? (
                    <button onClick={() => removeFile(i)} className="text-muted-foreground hover:text-destructive transition-colors">
                      <span className="material-symbols-outlined text-lg">close</span>
                    </button>
                  ) : null}
                </div>
              ))}
            </div>
          )}

          {/* Drop zone */}
          <div
            onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
            onDragLeave={() => setDragActive(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={cn(
              'flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed transition-colors',
              files.length > 0 ? 'py-8' : 'py-16',
              dragActive ? 'border-harven-primary bg-harven-primary/5' : 'border-border hover:border-muted-foreground/40',
            )}
          >
            <input ref={fileInputRef} type="file" accept={FILE_ACCEPT[contentType]} onChange={handleFileSelect} className="hidden" multiple />
            <span className="material-symbols-outlined text-4xl text-muted-foreground/40">
              {files.length > 0 ? 'add_circle_outline' : 'cloud_upload'}
            </span>
            <p className="mt-2 text-sm font-medium text-foreground">
              {files.length > 0 ? 'Adicionar mais arquivos' : 'Arraste arquivos ou clique para selecionar'}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Máximo {Math.round(FILE_MAX[contentType] / (1024 * 1024))}MB &middot; {FILE_ACCEPT[contentType]}
            </p>
          </div>

          {/* Next */}
          <button
            disabled={!files.length || uploading}
            onClick={handleUpload}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-harven-primary px-6 py-3 text-sm font-semibold text-harven-dark transition-colors hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-40"
          >
            {uploading ? `Enviando ${uploadingIdx + 1} de ${files.length}...` : `Enviar ${files.length > 1 ? `${files.length} arquivos` : ''} e Continuar`}
            <span className="material-symbols-outlined text-lg">arrow_forward</span>
          </button>
        </div>
      )}

      {/* ========== STEP 2: Method ========== */}
      {step === 2 && (
        <div className="mt-8 space-y-4">
          <p className="text-sm text-muted-foreground">Como deseja processar este conteúdo?</p>

          <button
            onClick={() => handleMethodSelect('ai')}
            className="group flex w-full items-start gap-4 rounded-2xl border-2 border-border bg-card p-6 text-left transition-all hover:border-harven-primary hover:shadow-sm"
          >
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-purple-100">
              <span className="material-symbols-outlined text-2xl text-purple-600">auto_awesome</span>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <p className="font-semibold text-foreground">Processamento com IA</p>
                <span className="rounded-full bg-purple-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-purple-700">
                  BETA
                </span>
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                A IA analisa o material, extrai texto e gera perguntas socráticas automaticamente.
              </p>
            </div>
          </button>

          <button
            onClick={() => handleMethodSelect('manual')}
            className="group flex w-full items-start gap-4 rounded-2xl border-2 border-border bg-card p-6 text-left transition-all hover:border-harven-primary hover:shadow-sm"
          >
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-green-100">
              <span className="material-symbols-outlined text-2xl text-green-600">edit_note</span>
            </div>
            <div>
              <p className="font-semibold text-foreground">Edição Manual</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Escreva o conteúdo e crie perguntas socráticas manualmente.
              </p>
            </div>
          </button>

          <button
            onClick={() => {
              setStep(1);
              setFiles([]);
              setUploadedContentId(null);
              setUploadedIds([]);
            }}
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            &larr; Voltar
          </button>
        </div>
      )}

      {/* ========== STEP 3a: AI Processing ========== */}
      {step === 3 && method === 'ai' && (
        <div className="mt-12 flex flex-col items-center text-center">
          <div className="relative">
            <div className="flex h-20 w-20 items-center justify-center rounded-full bg-purple-100">
              <span className="material-symbols-outlined animate-pulse text-4xl text-purple-600">
                auto_awesome
              </span>
            </div>
            {aiStage !== 'done' && (
              <div className="absolute -inset-2 animate-ping rounded-full border-2 border-purple-300 opacity-20" />
            )}
          </div>

          <div className="mt-8 w-full max-w-sm space-y-4">
            {AI_STAGES.map((s) => {
              const stageIdx = AI_STAGES.findIndex((x) => x.key === aiStage);
              const thisIdx = AI_STAGES.findIndex((x) => x.key === s.key);
              const isDone = thisIdx < stageIdx || aiStage === 'done';
              const isCurrent = s.key === aiStage && aiStage !== 'done';
              const isPending = thisIdx > stageIdx && aiStage !== 'done';

              return (
                <div
                  key={s.key}
                  className={cn(
                    'flex items-center gap-3 rounded-xl px-4 py-3 text-sm transition-all',
                    isDone && 'bg-green-50 text-green-700',
                    isCurrent && 'bg-purple-50 text-purple-700 font-medium',
                    isPending && 'text-muted-foreground/50',
                  )}
                >
                  <span className="material-symbols-outlined text-lg">
                    {isDone ? 'check_circle' : isCurrent ? s.icon : 'radio_button_unchecked'}
                  </span>
                  {s.label}
                  {isCurrent && (
                    <div className="ml-auto h-4 w-4 animate-spin rounded-full border-2 border-purple-300 border-t-purple-600" />
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ========== STEP 3b: Manual Editing ========== */}
      {step === 3 && method === 'manual' && (
        <div className="mt-8 space-y-6">
          {/* Title */}
          <div>
            <label className="mb-1.5 block text-sm font-medium text-foreground">Título</label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Nome do conteúdo"
              className="w-full rounded-xl border border-border bg-card px-4 py-2.5 text-sm text-foreground placeholder:text-muted-foreground focus:border-harven-primary focus:outline-none focus:ring-2 focus:ring-harven-primary/20"
            />
          </div>

          {/* Body */}
          <div>
            <label className="mb-1.5 block text-sm font-medium text-foreground">Conteúdo</label>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={12}
              placeholder="Escreva ou cole o conteúdo aqui..."
              className="w-full rounded-xl border border-border bg-card px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground focus:border-harven-primary focus:outline-none focus:ring-2 focus:ring-harven-primary/20"
            />
          </div>

          {/* Socratic Questions */}
          <div>
            <div className="flex items-center justify-between">
              <label className="text-sm font-medium text-foreground">Perguntas Socráticas</label>
              <button
                onClick={addQuestion}
                className="flex items-center gap-1 rounded-lg bg-muted px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted/80"
              >
                <span className="material-symbols-outlined text-sm">add</span>
                Adicionar
              </button>
            </div>

            {questions.length === 0 && (
              <p className="mt-3 text-xs text-muted-foreground">
                Nenhuma pergunta ainda. Adicione perguntas para guiar o estudo socrático.
              </p>
            )}

            <div className="mt-3 space-y-3">
              {questions.map((q, i) => (
                <div key={q.id} className="rounded-xl border border-border bg-card p-4">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-muted-foreground">
                      Pergunta {i + 1}
                    </span>
                    <div className="flex items-center gap-2">
                      <select
                        value={q.difficulty}
                        onChange={(e) =>
                          updateQuestion(q.id, {
                            difficulty: e.target.value as 'easy' | 'medium' | 'hard',
                          })
                        }
                        className={cn(
                          'rounded-lg px-2 py-1 text-xs font-medium border-0',
                          DIFFICULTY_COLORS[q.difficulty],
                        )}
                      >
                        <option value="easy">Fácil</option>
                        <option value="medium">Médio</option>
                        <option value="hard">Difícil</option>
                      </select>
                      <button
                        onClick={() => removeQuestion(q.id)}
                        className="text-muted-foreground hover:text-destructive transition-colors"
                      >
                        <span className="material-symbols-outlined text-lg">close</span>
                      </button>
                    </div>
                  </div>
                  <input
                    value={q.question}
                    onChange={(e) => updateQuestion(q.id, { question: e.target.value })}
                    placeholder="Escreva a pergunta..."
                    className="mt-2 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-harven-primary focus:outline-none"
                  />
                  <input
                    value={q.expected_answer}
                    onChange={(e) => updateQuestion(q.id, { expected_answer: e.target.value })}
                    placeholder="Resposta esperada (opcional)"
                    className="mt-2 w-full rounded-lg border border-border bg-background px-3 py-2 text-xs text-muted-foreground placeholder:text-muted-foreground focus:border-harven-primary focus:outline-none"
                  />
                </div>
              ))}
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-3 pt-2">
            <button
              onClick={() => {
                setStep(2);
                setMethod(null);
              }}
              className="rounded-xl border border-border px-5 py-2.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted"
            >
              Voltar
            </button>
            <button
              disabled={saving || !title.trim()}
              onClick={handleManualSave}
              className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-harven-primary px-6 py-2.5 text-sm font-semibold text-harven-dark transition-colors hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-40"
            >
              {saving ? 'Salvando...' : 'Salvar e Revisar'}
              <span className="material-symbols-outlined text-lg">check</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
