// @ts-nocheck
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { adminApi } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import { Button } from '../../components/ui/Button';
import { Card, CardContent, CardHeader } from '../../components/ui/Card';
import { Input } from '../../components/ui/Input';
import { Badge } from '../../components/ui/Badge';
import { Select } from '../../components/ui/Select';
import { Skeleton, SkeletonCard } from '../../components/ui/Skeleton';

interface DashStats {
  total_users?: number;
  total_disciplines?: number;
  avg_performance?: number;
  active_sessions?: number;
  users_growth?: Array<{ date: string; count: number }>;
}

interface LogEntry {
  id: string;
  type: string;
  message: string;
  author?: string;
  created_at: string;
}

const QUICK_ACTIONS = [
  { icon: 'person_add', label: 'Criar Usuário', route: '/admin/users' },
  { icon: 'class', label: 'Gerenciar Turmas', route: '/admin/classes' },
  { icon: 'settings', label: 'Configurações', route: '/admin/settings' },
  { icon: 'download', label: 'Backups', route: '/admin/settings?tab=backups' },
  { icon: 'shield', label: 'Segurança', route: '/admin/settings?tab=security' },
  { icon: 'monitoring', label: 'Performance', route: '/admin/settings?tab=performance' },
];

export default function AdminConsole() {
  const navigate = useNavigate();
  const { user } = useAuth();

  const [stats, setStats] = useState<DashStats>({});
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [showActionModal, setShowActionModal] = useState(false);
  const [actionType, setActionType] = useState<'announcement' | 'maintenance'>('announcement');
  const [actionMessage, setActionMessage] = useState('');
  const [actionTarget, setActionTarget] = useState('all');
  const [sending, setSending] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        setLoading(true);
        const [statsData, logsData] = await Promise.all([
          adminApi.getStats().catch(() => ({})),
          adminApi.getLogs({ limit: '10' } as Record<string, string>).catch(() => []),
        ]);
        if (controller.signal.aborted) return;
        setStats(statsData ?? {});
        setLogs(Array.isArray(logsData) ? logsData : []);
      } catch {
        if (controller.signal.aborted) return;
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    load();
    return () => controller.abort();
  }, []);

  const handleSendAction = async () => {
    if (!actionMessage.trim()) { toast.error('Mensagem é obrigatória.'); return; }
    setSending(true);
    try {
      await adminApi.createAction({
        type: actionType,
        message: actionMessage.trim(),
        target: actionTarget,
        author: user?.name ?? 'Admin',
      });
      toast.success(actionType === 'announcement' ? 'Comunicado enviado.' : 'Manutenção agendada.');
      setShowActionModal(false);
      setActionMessage('');
    } catch {
      toast.error('Erro ao enviar ação.');
    } finally {
      setSending(false);
    }
  };

  const statCards = [
    { icon: 'group', label: 'Usuários', value: stats.total_users ?? 0, color: 'text-blue-500' },
    { icon: 'school', label: 'Disciplinas', value: stats.total_disciplines ?? 0, color: 'text-green-500' },
    { icon: 'trending_up', label: 'Performance', value: `${stats.avg_performance ?? 0}%`, color: 'text-harven-gold' },
    { icon: 'sensors', label: 'Sessões Ativas', value: stats.active_sessions ?? 0, color: 'text-purple-500' },
  ];

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto p-8 flex flex-col gap-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">{Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)}</div>
        <SkeletonCard />
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto p-8 flex flex-col gap-8 animate-in fade-in duration-500">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-display font-bold text-foreground">Painel Administrativo</h1>
          <p className="text-sm text-muted-foreground mt-1">Visão geral da plataforma</p>
        </div>
        <Button onClick={() => setShowActionModal(true)}>
          <span className="material-symbols-outlined text-[18px] mr-2">campaign</span>
          Ação Global
        </Button>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {statCards.map((s) => (
          <Card key={s.label}>
            <CardContent className="flex items-center gap-4">
              <div className="h-12 w-12 rounded-lg bg-muted flex items-center justify-center">
                <span className={`material-symbols-outlined text-[24px] ${s.color}`}>{s.icon}</span>
              </div>
              <div>
                <p className="text-2xl font-bold text-foreground">{s.value}</p>
                <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">{s.label}</p>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* User Growth Chart Placeholder */}
      {stats.users_growth && stats.users_growth.length > 0 && (
        <Card>
          <CardHeader>
            <h2 className="text-sm font-bold text-foreground">Crescimento de Usuários</h2>
          </CardHeader>
          <CardContent>
            <div className="h-48 flex items-end gap-1">
              {stats.users_growth.map((point, i) => {
                const max = Math.max(...stats.users_growth!.map((p) => p.count), 1);
                const height = (point.count / max) * 100;
                return (
                  <div key={i} className="flex-1 flex flex-col items-center gap-1">
                    <div
                      className="w-full bg-primary/80 rounded-t-sm min-h-[4px] transition-all"
                      style={{ height: `${height}%` }}
                    />
                    <span className="text-[9px] text-muted-foreground">{point.date.slice(5)}</span>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Quick Actions */}
      <div>
        <h2 className="text-sm font-bold text-foreground mb-3">Ações Rápidas</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          {QUICK_ACTIONS.map((action) => (
            <Card
              key={action.label}
              hoverEffect
              onClick={() => navigate(action.route)}
              className="p-4 text-center"
            >
              <span className="material-symbols-outlined text-[28px] text-primary mb-2 block">{action.icon}</span>
              <p className="text-xs font-bold text-foreground">{action.label}</p>
            </Card>
          ))}
        </div>
      </div>

      {/* Logs */}
      <Card>
        <CardHeader className="flex items-center justify-between">
          <h2 className="text-sm font-bold text-foreground">Logs do Sistema</h2>
          <Button variant="ghost" size="sm" onClick={() => navigate('/admin/settings?tab=logs')}>
            Ver todos
          </Button>
        </CardHeader>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left px-4 py-2 text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Tipo</th>
                <th className="text-left px-4 py-2 text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Mensagem</th>
                <th className="text-left px-4 py-2 text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Autor</th>
                <th className="text-left px-4 py-2 text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Data</th>
              </tr>
            </thead>
            <tbody>
              {logs.length === 0 ? (
                <tr><td colSpan={4} className="px-4 py-6 text-center text-muted-foreground">Nenhum log registrado.</td></tr>
              ) : (
                logs.map((log) => (
                  <tr key={log.id} className="border-b border-border last:border-0 hover:bg-muted/50">
                    <td className="px-4 py-2">
                      <Badge variant={log.type === 'error' ? 'danger' : log.type === 'warning' ? 'warning' : 'outline'}>
                        {log.type}
                      </Badge>
                    </td>
                    <td className="px-4 py-2 text-foreground max-w-md truncate">{log.message}</td>
                    <td className="px-4 py-2 text-muted-foreground">{log.author ?? '—'}</td>
                    <td className="px-4 py-2 text-muted-foreground text-xs">
                      {new Date(log.created_at).toLocaleString('pt-BR')}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Global Action Modal */}
      {showActionModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="fixed inset-0 bg-black/50" onClick={() => setShowActionModal(false)} />
          <div className="relative bg-card rounded-xl shadow-xl p-6 w-full max-w-md mx-4" role="dialog" aria-modal="true">
            <h3 className="text-lg font-display font-bold text-foreground mb-4">Ação Global</h3>
            <div className="flex flex-col gap-4">
              <Select
                label="Tipo"
                value={actionType}
                onChange={(e) => setActionType(e.target.value as 'announcement' | 'maintenance')}
              >
                <option value="announcement">Comunicado</option>
                <option value="maintenance">Manutenção</option>
              </Select>
              <Select
                label="Destinatários"
                value={actionTarget}
                onChange={(e) => setActionTarget(e.target.value)}
              >
                <option value="all">Todos</option>
                <option value="students">Alunos</option>
                <option value="instructors">Professores</option>
                <option value="admins">Administradores</option>
              </Select>
              <div className="space-y-1.5">
                <label className="block text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Mensagem</label>
                <textarea
                  rows={4}
                  value={actionMessage}
                  onChange={(e) => setActionMessage(e.target.value)}
                  className="w-full bg-harven-bg border-none rounded-lg text-sm text-foreground placeholder-gray-400 focus:ring-1 focus:ring-primary px-4 py-2 resize-none"
                  placeholder="Escreva a mensagem..."
                />
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <Button variant="outline" onClick={() => setShowActionModal(false)}>Cancelar</Button>
              <Button onClick={handleSendAction} disabled={sending || !actionMessage.trim()}>
                {sending ? 'Enviando...' : 'Enviar'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
