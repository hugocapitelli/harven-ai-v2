// @ts-nocheck
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { disciplinesApi, dashboardApi } from '../../services/api';
import { unwrapList } from '../../lib/utils';
import { Button } from '../../components/ui/Button';
import { Card, CardContent } from '../../components/ui/Card';
import { Badge } from '../../components/ui/Badge';
import { Skeleton, SkeletonCard } from '../../components/ui/Skeleton';
import { EmptyState } from '../../components/ui/EmptyState';
import { SearchInput } from '../../components/ui/SearchInput';
import { PageHeader } from '../../components/ui/PageHeader';
import type { Discipline } from '../../types';

type ViewMode = 'grid' | 'list';

const statusVariant = (status?: string) => {
  switch (status) {
    case 'Ativo': return 'success';
    case 'Rascunho': return 'warning';
    case 'Arquivado': return 'danger';
    default: return 'outline';
  }
};

/* Brand-aligned solid color palette for discipline cards without images */
const CARD_COLORS = [
  'bg-harven-dark',
  'bg-[#2a4528]',
  'bg-[#3d6339]',
  'bg-harven-gold',
  'bg-harven-dark',
  'bg-[#2a4528]',
];

const ICONS = ['school', 'biotech', 'psychology', 'architecture', 'science', 'balance'];

export default function InstructorList() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [disciplines, setDisciplines] = useState<Discipline[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [viewMode, setViewMode] = useState<ViewMode>('grid');

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        setLoading(true);
        const data = await disciplinesApi.list();
        if (controller.signal.aborted) return;
        const list: Discipline[] = unwrapList(data);

        // Enrich each discipline with real counts from /classes/{id}/stats
        const enriched = await Promise.all(
          list.map(async (disc) => {
            try {
              const st: any = await dashboardApi.getClassStats(disc.id);
              return {
                ...disc,
                courses_count: st?.course_count ?? disc.courses_count,
                students: st?.student_count ?? disc.students,
              };
            } catch {
              return disc;
            }
          }),
        );
        if (controller.signal.aborted) return;
        setDisciplines(enriched);
      } catch (err) {
        if (controller.signal.aborted) return;
        console.error('Failed to load disciplines:', err);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    load();
    return () => controller.abort();
  }, [user]);

  const filtered = disciplines.filter((d) =>
    (d.name ?? '').toLowerCase().includes(search.toLowerCase()) ||
    (d.code ?? '').toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="max-w-7xl mx-auto px-6 py-10 flex flex-col gap-10 animate-in fade-in duration-500">
      <PageHeader
        title="Minhas Disciplinas"
        subtitle={loading ? 'Carregando...' : `${filtered.length} disciplina${filtered.length !== 1 ? 's' : ''} ativa${filtered.length !== 1 ? 's' : ''}`}
        constrained={false}
      />

      {/* Toolbar */}
      <div className="flex items-center gap-4">
        <SearchInput
          placeholder="Buscar disciplina..."
          value={search}
          onChange={setSearch}
          className="flex-1 max-w-lg"
        />
        <div className="flex border border-border rounded-lg overflow-hidden">
          <button
            onClick={() => setViewMode('grid')}
            className={`p-2.5 transition-colors ${viewMode === 'grid' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'}`}
            aria-label="Visualização em grade"
          >
            <span className="material-symbols-outlined text-[22px]">grid_view</span>
          </button>
          <button
            onClick={() => setViewMode('list')}
            className={`p-2.5 transition-colors ${viewMode === 'list' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'}`}
            aria-label="Visualização em lista"
          >
            <span className="material-symbols-outlined text-[22px]">view_list</span>
          </button>
        </div>
      </div>

      {/* Content */}
      {loading ? (
        <div className={viewMode === 'grid' ? 'grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6' : 'flex flex-col gap-4'}>
          {Array.from({ length: 6 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <Card className="col-span-full">
          <EmptyState
            icon="school"
            title={search ? 'Nenhuma disciplina encontrada.' : 'Nenhuma disciplina cadastrada ainda.'}
            description={search ? 'Tente outro termo de busca.' : 'As disciplinas aparecerão aqui quando forem atribuídas a você.'}
            size="lg"
          />
        </Card>
      ) : viewMode === 'grid' ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
          {filtered.map((d, idx) => (
            <Card
              key={d.id}
              hoverEffect
              onClick={() => navigate(`/instructor/class/${d.id}`)}
              className="overflow-hidden group cursor-pointer"
            >
              {/* Card header — image or gradient */}
              {d.image ? (
                <div className="h-40 overflow-hidden">
                  <img src={d.image} alt={d.name} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" />
                </div>
              ) : (
                <div className={`h-40 ${CARD_COLORS[idx % CARD_COLORS.length]} flex items-center justify-center relative overflow-hidden hover:opacity-90 transition-opacity`}>
                  <span className="material-symbols-outlined text-white/30 text-[72px] group-hover:scale-110 transition-transform duration-300">
                    {ICONS[idx % ICONS.length]}
                  </span>
                </div>
              )}

              {/* Card body */}
              <CardContent className="p-6 flex flex-col gap-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="text-lg font-display font-bold text-foreground leading-tight line-clamp-2">{d.name}</h3>
                    {d.code && <p className="text-sm text-muted-foreground mt-1">{d.code}</p>}
                  </div>
                  <Badge variant={statusVariant(d.status)} className="shrink-0">{d.status ?? 'Ativo'}</Badge>
                </div>

                <div className="flex items-center gap-6 text-sm text-muted-foreground pt-2 border-t border-border">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="material-symbols-outlined text-[18px] text-primary">menu_book</span>
                    <span className="font-medium text-foreground">{d.courses_count ?? 0}</span> cursos
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="material-symbols-outlined text-[18px] text-primary">group</span>
                    <span className="font-medium text-foreground">{d.students ?? 0}</span> alunos
                  </span>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        /* List view */
        <div className="flex flex-col gap-3">
          {filtered.map((d, idx) => (
            <Card
              key={d.id}
              hoverEffect
              onClick={() => navigate(`/instructor/class/${d.id}`)}
              className="flex items-center gap-5 p-5 cursor-pointer group"
            >
              {/* Icon placeholder */}
              <div className={`h-14 w-14 rounded-xl ${CARD_COLORS[idx % CARD_COLORS.length]} flex items-center justify-center shrink-0 overflow-hidden`}>
                {d.image ? (
                  <img src={d.image} alt="" className="h-full w-full object-cover" />
                ) : (
                  <span className="material-symbols-outlined text-white/70 text-[28px]">{ICONS[idx % ICONS.length]}</span>
                )}
              </div>

              {/* Info */}
              <div className="flex-1 min-w-0">
                <h3 className="text-base font-display font-bold text-foreground truncate group-hover:text-primary transition-colors">{d.name}</h3>
                <p className="text-sm text-muted-foreground mt-0.5">{d.code ?? '—'}</p>
              </div>

              {/* Counts */}
              <div className="flex items-center gap-6 text-sm text-muted-foreground shrink-0">
                <span className="inline-flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-[18px]">menu_book</span>
                  <span className="font-medium text-foreground">{d.courses_count ?? 0}</span>
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-[18px]">group</span>
                  <span className="font-medium text-foreground">{d.students ?? 0}</span>
                </span>
              </div>

              <Badge variant={statusVariant(d.status)}>{d.status ?? 'Ativo'}</Badge>
              <span className="material-symbols-outlined text-muted-foreground/50 text-[22px] group-hover:text-primary transition-colors">chevron_right</span>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
