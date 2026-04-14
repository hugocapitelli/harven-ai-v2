// @ts-nocheck
import { useEffect, useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { cn } from '@/lib/utils';
import { chaptersApi, contentsApi } from '@/services/api';
import type { Chapter, Content } from '@/types';

interface ChapterWithMeta extends Chapter {
  duration_label?: string;
  level?: string;
  learning_objectives?: string[];
}

const CONTENT_TYPE_META: Record<string, { icon: string; color: string; label: string }> = {
  VIDEO: { icon: 'play_circle', color: 'text-blue-600 bg-blue-50', label: 'Vídeo' },
  AUDIO: { icon: 'headphones', color: 'text-purple-600 bg-purple-50', label: 'Áudio' },
  TEXT: { icon: 'article', color: 'text-green-600 bg-green-50', label: 'Texto' },
};

const OBJECTIVE_ICONS = ['school', 'psychology', 'build', 'trending_up'];

function SkeletonBlock({ className }: { className?: string }) {
  return <div className={cn('animate-pulse rounded-lg bg-muted', className)} />;
}

function Skeleton() {
  return (
    <div className="space-y-6">
      <SkeletonBlock className="h-5 w-64" />
      <SkeletonBlock className="h-10 w-96" />
      <div className="flex gap-3">
        <SkeletonBlock className="h-8 w-24" />
        <SkeletonBlock className="h-8 w-24" />
        <SkeletonBlock className="h-8 w-24" />
      </div>
      <div className="grid grid-cols-2 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <SkeletonBlock key={i} className="h-24" />
        ))}
      </div>
      <div className="space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <SkeletonBlock key={i} className="h-20" />
        ))}
      </div>
    </div>
  );
}

export default function ChapterDetail() {
  const { courseId, chapterId } = useParams<{ courseId: string; chapterId: string }>();
  const navigate = useNavigate();

  const [chapter, setChapter] = useState<ChapterWithMeta | null>(null);
  const [contents, setContents] = useState<Content[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!courseId || !chapterId) return;
    const controller = new AbortController();

    async function load() {
      setLoading(true);
      try {
        const [chapterData, contentsData] = await Promise.all([
          chaptersApi.list(courseId!).then((chapters: Chapter[]) =>
            chapters.find((c) => c.id === chapterId) ?? null,
          ),
          contentsApi.list(chapterId!),
        ]);
        setChapter(chapterData);
        setContents(Array.isArray(contentsData) ? contentsData : contentsData?.data ?? []);
      } catch (err) {
        if ((err as Error).name !== 'AbortError') console.error(err);
      } finally {
        setLoading(false);
      }
    }

    load();
    return () => controller.abort();
  }, [courseId, chapterId]);

  const completedCount = contents.filter((c) => c.completed).length;
  const progressPct = contents.length > 0 ? Math.round((completedCount / contents.length) * 100) : 0;

  if (loading) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-8">
        <Skeleton />
      </div>
    );
  }

  if (!chapter) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-8">
        <p className="text-muted-foreground">Capítulo não encontrado.</p>
        <Link to={`/courses/${courseId}`} className="mt-4 inline-block text-sm text-primary underline">
          Voltar ao curso
        </Link>
      </div>
    );
  }

  const objectives = chapter.learning_objectives ?? [];

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      {/* Breadcrumb */}
      <nav className="mb-6 flex items-center gap-2 text-sm text-muted-foreground">
        <Link to={`/courses/${courseId}`} className="hover:text-foreground transition-colors">
          Curso
        </Link>
        <span className="material-symbols-outlined text-base">chevron_right</span>
        <span className="text-foreground font-medium">{chapter.title}</span>
      </nav>

      <div className="flex gap-8">
        {/* Main content */}
        <div className="min-w-0 flex-1">
          {/* Title */}
          <h1 className="font-display text-3xl font-bold text-foreground">{chapter.title}</h1>
          {chapter.description && (
            <p className="mt-2 text-muted-foreground">{chapter.description}</p>
          )}

          {/* Badges */}
          <div className="mt-4 flex flex-wrap gap-3">
            {chapter.duration_label && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
                <span className="material-symbols-outlined text-sm">schedule</span>
                {chapter.duration_label}
              </span>
            )}
            {chapter.level && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
                <span className="material-symbols-outlined text-sm">signal_cellular_alt</span>
                {chapter.level}
              </span>
            )}
            <span className="inline-flex items-center gap-1.5 rounded-full bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
              <span className="material-symbols-outlined text-sm">description</span>
              {contents.length} {contents.length === 1 ? 'conteúdo' : 'conteúdos'}
            </span>
          </div>

          {/* Learning Objectives */}
          {objectives.length > 0 && (
            <section className="mt-8">
              <h2 className="font-display text-lg font-semibold text-foreground">Objetivos de Aprendizagem</h2>
              <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
                {objectives.map((obj, i) => (
                  <div
                    key={i}
                    className="flex items-start gap-3 rounded-xl border border-border bg-card p-4"
                  >
                    <span className="material-symbols-outlined mt-0.5 text-primary">
                      {OBJECTIVE_ICONS[i % OBJECTIVE_ICONS.length]}
                    </span>
                    <p className="text-sm text-foreground">{obj}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Content List */}
          <section className="mt-8">
            <h2 className="font-display text-lg font-semibold text-foreground">Conteúdos</h2>

            {contents.length === 0 ? (
              <div className="mt-4 flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-border py-16 text-center">
                <span className="material-symbols-outlined text-5xl text-muted-foreground/40">folder_open</span>
                <p className="mt-3 text-sm text-muted-foreground">Nenhum conteúdo neste capítulo ainda.</p>
              </div>
            ) : (
              <div className="mt-4 space-y-3">
                {contents
                  .sort((a, b) => (a as Content & { order?: number }).order ?? 0 - ((b as Content & { order?: number }).order ?? 0))
                  .map((content, idx) => {
                    const meta = CONTENT_TYPE_META[content.type] ?? CONTENT_TYPE_META.TEXT;
                    return (
                      <button
                        key={content.id}
                        onClick={() =>
                          navigate(`/courses/${courseId}/chapters/${chapterId}/content/${content.id}`)
                        }
                        className="group relative flex w-full items-center gap-4 rounded-xl border border-border bg-card p-4 text-left transition-all hover:border-primary/40 hover:shadow-sm"
                      >
                        {/* Progress bar left */}
                        <div
                          className={cn(
                            'absolute left-0 top-0 h-full w-1 rounded-l-xl transition-colors',
                            content.completed ? 'bg-green-500' : 'bg-transparent group-hover:bg-primary/30',
                          )}
                        />

                        {/* Step number / check */}
                        <div
                          className={cn(
                            'flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-sm font-bold',
                            content.completed
                              ? 'bg-green-100 text-green-600'
                              : 'bg-muted text-muted-foreground',
                          )}
                        >
                          {content.completed ? (
                            <span className="material-symbols-outlined fill-1 text-xl">check</span>
                          ) : (
                            idx + 1
                          )}
                        </div>

                        {/* Type icon */}
                        <div className={cn('flex h-10 w-10 shrink-0 items-center justify-center rounded-lg', meta.color)}>
                          <span className="material-symbols-outlined text-xl">{meta.icon}</span>
                        </div>

                        {/* Info */}
                        <div className="min-w-0 flex-1">
                          <p className="font-medium text-foreground group-hover:text-primary-dark truncate">
                            {content.title}
                          </p>
                          <p className="text-xs text-muted-foreground">{meta.label}</p>
                        </div>

                        <span className="material-symbols-outlined text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
                          chevron_right
                        </span>
                      </button>
                    );
                  })}
              </div>
            )}
          </section>
        </div>

        {/* Right sidebar */}
        <aside className="hidden w-72 shrink-0 lg:block">
          <div className="sticky top-8 space-y-4">
            {/* Progress card */}
            <div className="rounded-2xl bg-harven-dark p-6 text-white">
              <p className="text-xs uppercase tracking-wider text-white/60">Progresso</p>
              <p className="mt-2 font-display text-4xl font-bold text-harven-primary">{progressPct}%</p>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
                <div
                  className="h-full rounded-full bg-harven-primary transition-all duration-500"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
              <p className="mt-2 text-xs text-white/60">
                {completedCount} de {contents.length} concluídos
              </p>
              {contents.length > 0 && (
                <button
                  onClick={() => {
                    const next = contents.find((c) => !c.completed) ?? contents[0];
                    navigate(`/courses/${courseId}/chapters/${chapterId}/content/${next.id}`);
                  }}
                  className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl bg-harven-primary px-4 py-2.5 text-sm font-semibold text-harven-dark transition-colors hover:bg-primary-dark"
                >
                  <span className="material-symbols-outlined text-lg">play_arrow</span>
                  {completedCount > 0 ? 'Continuar' : 'Começar'}
                </button>
              )}
            </div>

            {/* Tutor card */}
            <div className="rounded-2xl border border-border bg-card p-5">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-purple-100">
                  <span className="material-symbols-outlined text-purple-600">psychology</span>
                </div>
                <div>
                  <p className="text-sm font-semibold text-foreground">Tutor Socrático</p>
                  <p className="text-xs text-muted-foreground">IA para aprofundar o estudo</p>
                </div>
              </div>
              <p className="mt-3 text-xs text-muted-foreground">
                Ao abrir um conteúdo, você poderá interagir com o tutor socrático que faz perguntas
                para guiar seu raciocínio.
              </p>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
