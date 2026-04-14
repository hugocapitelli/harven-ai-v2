// @ts-nocheck
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { disciplinesApi } from '../../services/api';
import { Button } from '../../components/ui/Button';
import { Card, CardContent } from '../../components/ui/Card';
import { Input } from '../../components/ui/Input';
import { Badge } from '../../components/ui/Badge';
import { Skeleton, SkeletonCard } from '../../components/ui/Skeleton';
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
        setDisciplines(Array.isArray(data) ? data : []);
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
    (d.title ?? '').toLowerCase().includes(search.toLowerCase()) ||
    (d.code ?? '').toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="max-w-7xl mx-auto p-8 flex flex-col gap-8 animate-in fade-in duration-500">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-display font-bold text-foreground">Minhas Disciplinas</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {loading ? '...' : `${filtered.length} disciplina${filtered.length !== 1 ? 's' : ''}`}
          </p>
        </div>
        <Button onClick={() => navigate('/instructor/discipline/new')}>
          <span className="material-symbols-outlined text-[18px] mr-2">add</span>
          Nova Disciplina
        </Button>
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-3">
        <Input
          icon="search"
          placeholder="Buscar disciplina..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          containerClassName="flex-1 max-w-sm"
        />
        <div className="flex border border-border rounded-lg overflow-hidden">
          <button
            onClick={() => setViewMode('grid')}
            className={`p-2 ${viewMode === 'grid' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'}`}
            aria-label="Visualização em grade"
          >
            <span className="material-symbols-outlined text-[20px]">grid_view</span>
          </button>
          <button
            onClick={() => setViewMode('list')}
            className={`p-2 ${viewMode === 'list' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'}`}
            aria-label="Visualização em lista"
          >
            <span className="material-symbols-outlined text-[20px]">view_list</span>
          </button>
        </div>
      </div>

      {/* Content */}
      {loading ? (
        <div className={viewMode === 'grid' ? 'grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4' : 'flex flex-col gap-3'}>
          {Array.from({ length: 6 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <Card className="p-12 text-center">
          <span className="material-symbols-outlined text-5xl text-muted-foreground mb-3 block">school</span>
          <p className="text-muted-foreground font-medium">
            {search ? 'Nenhuma disciplina encontrada.' : 'Nenhuma disciplina cadastrada.'}
          </p>
        </Card>
      ) : viewMode === 'grid' ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((d) => (
            <Card key={d.id} hoverEffect onClick={() => navigate(`/instructor/discipline/${d.id}`)}>
              {d.image && (
                <div className="h-32 bg-muted overflow-hidden">
                  <img src={d.image} alt={d.title} className="w-full h-full object-cover" />
                </div>
              )}
              <CardContent className="flex flex-col gap-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <h3 className="font-display font-bold text-foreground truncate">{d.title}</h3>
                    {d.code && <p className="text-xs text-muted-foreground mt-0.5">{d.code}</p>}
                  </div>
                  <Badge variant={statusVariant(d.status)}>{d.status ?? 'Ativo'}</Badge>
                </div>
                <div className="flex items-center gap-4 text-xs text-muted-foreground">
                  <span className="inline-flex items-center gap-1">
                    <span className="material-symbols-outlined text-[16px]">menu_book</span>
                    {d.courses_count ?? 0} cursos
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <span className="material-symbols-outlined text-[16px]">group</span>
                    {d.students ?? 0} alunos
                  </span>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {filtered.map((d) => (
            <Card
              key={d.id}
              hoverEffect
              onClick={() => navigate(`/instructor/discipline/${d.id}`)}
              className="flex items-center gap-4 p-4"
            >
              <div className="h-12 w-12 rounded-lg bg-muted flex items-center justify-center shrink-0 overflow-hidden">
                {d.image ? (
                  <img src={d.image} alt="" className="h-full w-full object-cover" />
                ) : (
                  <span className="material-symbols-outlined text-muted-foreground">school</span>
                )}
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="font-display font-bold text-foreground truncate">{d.title}</h3>
                <p className="text-xs text-muted-foreground">{d.code ?? '—'} · {d.department ?? '—'}</p>
              </div>
              <div className="flex items-center gap-4 text-xs text-muted-foreground shrink-0">
                <span className="inline-flex items-center gap-1">
                  <span className="material-symbols-outlined text-[16px]">menu_book</span>
                  {d.courses_count ?? 0}
                </span>
                <span className="inline-flex items-center gap-1">
                  <span className="material-symbols-outlined text-[16px]">group</span>
                  {d.students ?? 0}
                </span>
              </div>
              <Badge variant={statusVariant(d.status)}>{d.status ?? 'Ativo'}</Badge>
              <span className="material-symbols-outlined text-muted-foreground text-[20px]">chevron_right</span>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
