// @ts-nocheck
import { useState, useEffect, useCallback } from 'react';
import { toast } from 'sonner';
import { useSearchParams } from 'react-router-dom';
import { adminApi } from '../../services/api';
import { Button } from '../../components/ui/Button';
import { Card, CardContent, CardHeader } from '../../components/ui/Card';
import { Input } from '../../components/ui/Input';
import { Select } from '../../components/ui/Select';
import { Badge } from '../../components/ui/Badge';
import { Tabs } from '../../components/ui/Tabs';
import { Skeleton, SkeletonText } from '../../components/ui/Skeleton';
import type { SystemSettings as SettingsType } from '../../types';

interface Backup {
  id: string;
  filename: string;
  size: string;
  created_at: string;
}

interface PerfMetrics {
  uptime?: string;
  ram_usage?: number;
  cpu_usage?: number;
  disk_usage?: number;
}

interface LogEntry {
  id: string;
  type: string;
  message: string;
  author?: string;
  created_at: string;
}

const TABS = [
  { id: 'general', label: 'Geral', icon: 'tune' },
  { id: 'security', label: 'Segurança', icon: 'shield' },
  { id: 'backups', label: 'Backups', icon: 'backup' },
  { id: 'performance', label: 'Performance', icon: 'monitoring' },
  { id: 'logs', label: 'Logs', icon: 'description' },
];

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="flex items-center justify-between py-2 cursor-pointer">
      <span className="text-sm text-foreground">{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative h-6 w-11 rounded-full transition-colors ${checked ? 'bg-primary' : 'bg-muted'}`}
      >
        <span className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-5' : ''}`} />
      </button>
    </label>
  );
}

export default function SystemSettings() {
  const [searchParams] = useSearchParams();
  const [activeTab, setActiveTab] = useState(searchParams.get('tab') ?? 'general');
  const [settings, setSettings] = useState<Partial<SettingsType>>({});
  const [originalSettings, setOriginalSettings] = useState<Partial<SettingsType>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [backups, setBackups] = useState<Backup[]>([]);
  const [perf, setPerf] = useState<PerfMetrics>({});
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [logSearch, setLogSearch] = useState('');
  const [logType, setLogType] = useState('all');
  const [storageStats, setStorageStats] = useState<Record<string, unknown>>({});

  const isDirty = JSON.stringify(settings) !== JSON.stringify(originalSettings);

  const loadSettings = useCallback(async (controller: AbortController) => {
    try {
      setLoading(true);
      const data = await adminApi.getSettings();
      if (controller.signal.aborted) return;
      const s = data ?? {};
      setSettings(s);
      setOriginalSettings(s);
    } catch {
      if (controller.signal.aborted) return;
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    loadSettings(controller);
    return () => controller.abort();
  }, [loadSettings]);

  useEffect(() => {
    if (activeTab === 'backups') adminApi.listBackups().then((d) => setBackups(Array.isArray(d) ? d : [])).catch(() => {});
    if (activeTab === 'performance') {
      adminApi.getPerformance().then(setPerf).catch(() => {});
      adminApi.getStorageStats().then((d) => setStorageStats(d ?? {})).catch(() => {});
    }
    if (activeTab === 'logs') adminApi.getLogs().then((d) => setLogs(Array.isArray(d) ? d : [])).catch(() => {});
  }, [activeTab]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await adminApi.updateSettings(settings as Record<string, unknown>);
      setOriginalSettings({ ...settings });
      toast.success('Configurações salvas.');
    } catch { toast.error('Erro ao salvar.'); }
    finally { setSaving(false); }
  };

  const handleLogoUpload = async (type: 'logo' | 'login-logo', file: File) => {
    try {
      const fn = type === 'logo' ? adminApi.uploadLogo : adminApi.uploadLoginLogo;
      const result = await fn(file);
      const key = type === 'logo' ? 'logo_url' : 'login_logo_url';
      setSettings((s) => ({ ...s, [key]: result.url ?? result[key] }));
      toast.success('Logo atualizado.');
    } catch { toast.error('Erro no upload.'); }
  };

  const handleSearchLogs = async () => {
    try {
      const data = logSearch
        ? await adminApi.searchLogs(logSearch, logType !== 'all' ? logType : undefined)
        : await adminApi.getLogs({ log_type: logType !== 'all' ? logType : undefined } as Record<string, string>);
      setLogs(Array.isArray(data) ? data : []);
    } catch { toast.error('Erro na busca.'); }
  };

  const handleExportLogs = async () => {
    try {
      const blob = await adminApi.exportLogs('csv');
      const url = URL.createObjectURL(blob as unknown as Blob);
      const a = document.createElement('a');
      a.href = url; a.download = 'logs.csv'; a.click();
      URL.revokeObjectURL(url);
    } catch { toast.error('Erro ao exportar.'); }
  };

  const set = (key: string, value: unknown) => setSettings((s) => ({ ...s, [key]: value }));

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto p-8 flex flex-col gap-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-10 w-96" />
        <SkeletonText lines={12} />
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto p-8 flex flex-col gap-6 animate-in fade-in duration-500">
      {/* Sticky Save Header */}
      <div className="sticky top-0 z-10 bg-background/95 backdrop-blur-sm -mx-8 px-8 py-4 border-b border-border flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-display font-bold text-foreground">Configurações do Sistema</h1>
          {isDirty && <p className="text-xs text-harven-gold font-medium mt-0.5">Alterações não salvas</p>}
        </div>
        <Button onClick={handleSave} disabled={saving || !isDirty}>
          {saving ? 'Salvando...' : 'Salvar Alterações'}
        </Button>
      </div>

      <Tabs items={TABS} activeTab={activeTab} onChange={setActiveTab} ariaLabel="Seções de configuração" />

      {/* Tab: General */}
      {activeTab === 'general' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card>
            <CardHeader><h2 className="text-sm font-bold text-foreground">Plataforma</h2></CardHeader>
            <CardContent className="flex flex-col gap-4">
              <Input label="Nome da Plataforma" value={settings.platform_name ?? ''} onChange={(e) => set('platform_name', e.target.value)} />
              <Input label="Email de Suporte" type="email" value={settings.support_email ?? ''} onChange={(e) => set('support_email', e.target.value)} />
              <div className="space-y-1.5">
                <label className="block text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Cor Primária</label>
                <div className="flex items-center gap-3">
                  <input type="color" value={settings.primary_color ?? '#d0ff00'} onChange={(e) => set('primary_color', e.target.value)} className="h-10 w-10 rounded-lg border border-border cursor-pointer" />
                  <Input value={settings.primary_color ?? '#d0ff00'} onChange={(e) => set('primary_color', e.target.value)} containerClassName="flex-1" />
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><h2 className="text-sm font-bold text-foreground">Logos</h2></CardHeader>
            <CardContent className="flex flex-col gap-4">
              {(['logo', 'login-logo'] as const).map((type) => {
                const key = type === 'logo' ? 'logo_url' : 'login_logo_url';
                const label = type === 'logo' ? 'Logo Principal' : 'Logo da Tela de Login';
                return (
                  <div key={type} className="flex items-center gap-4">
                    <div className="h-16 w-16 rounded-lg bg-muted flex items-center justify-center overflow-hidden shrink-0">
                      {settings[key] ? <img src={settings[key] as string} alt="" className="h-full w-full object-contain" /> : <span className="material-symbols-outlined text-muted-foreground">image</span>}
                    </div>
                    <div>
                      <p className="text-xs font-bold text-muted-foreground uppercase tracking-widest mb-1">{label}</p>
                      <label className="cursor-pointer inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline">
                        <input type="file" accept="image/*" className="hidden" onChange={(e) => e.target.files?.[0] && handleLogoUpload(type, e.target.files[0])} />
                        <span className="material-symbols-outlined text-[14px]">upload</span> Alterar
                      </label>
                    </div>
                  </div>
                );
              })}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><h2 className="text-sm font-bold text-foreground">Módulos</h2></CardHeader>
            <CardContent>
              <Toggle label="Tutor IA (Socrático)" checked={settings.ai_tutor_enabled ?? false} onChange={(v) => set('ai_tutor_enabled', v)} />
              <Toggle label="Gamificação" checked={settings.gamification_enabled ?? false} onChange={(v) => set('gamification_enabled', v)} />
              <Toggle label="Modo Escuro" checked={settings.dark_mode_enabled ?? false} onChange={(v) => set('dark_mode_enabled', v)} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader><h2 className="text-sm font-bold text-foreground">Quotas e Armazenamento</h2></CardHeader>
            <CardContent className="flex flex-col gap-4">
              <Input label="Tokens por Resposta (max)" type="number" value={String(settings.max_tokens_per_response ?? 2048)} onChange={(e) => set('max_tokens_per_response', Number(e.target.value))} />
              <Input label="Upload Máximo (MB)" type="number" value={String(settings.max_upload_mb ?? 50)} onChange={(e) => set('max_upload_mb', Number(e.target.value))} />
              <Input label="Limite Diário de Tokens" type="number" value={String(settings.daily_token_limit ?? 100000)} onChange={(e) => set('daily_token_limit', Number(e.target.value))} />
              {storageStats && (
                <div className="text-xs text-muted-foreground">
                  Armazenamento: {String(storageStats.used ?? '—')} / {String(storageStats.total ?? '—')}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* Tab: Security */}
      {activeTab === 'security' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card>
            <CardHeader><h2 className="text-sm font-bold text-foreground">Política de Senhas</h2></CardHeader>
            <CardContent className="flex flex-col gap-4">
              <Input label="Tamanho Mínimo" type="number" value={String(settings.min_password_length ?? 8)} onChange={(e) => set('min_password_length', Number(e.target.value))} />
              <Toggle label="Exigir Caracteres Especiais" checked={settings.require_special_chars ?? false} onChange={(v) => set('require_special_chars', v)} />
              <Input label="Expiração (dias)" type="number" value={String(settings.password_expiration_days ?? 90)} onChange={(e) => set('password_expiration_days', Number(e.target.value))} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader><h2 className="text-sm font-bold text-foreground">Sessão</h2></CardHeader>
            <CardContent className="flex flex-col gap-4">
              <Input label="Timeout de Sessão (minutos)" type="number" value={String(settings.session_timeout ?? 60)} onChange={(e) => set('session_timeout', Number(e.target.value))} />
              <Button variant="destructive" onClick={async () => {
                try { await adminApi.forceLogoutAll(); toast.success('Todos os usuários foram deslogados.'); } catch { toast.error('Erro.'); }
              }}>
                <span className="material-symbols-outlined text-[16px] mr-1">logout</span> Forçar Logout Geral
              </Button>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Tab: Backups */}
      {activeTab === 'backups' && (
        <Card>
          <CardHeader className="flex items-center justify-between">
            <h2 className="text-sm font-bold text-foreground">Backups</h2>
            <Button size="sm" onClick={async () => {
              try { await adminApi.createBackup(); toast.success('Backup criado.'); const d = await adminApi.listBackups(); setBackups(Array.isArray(d) ? d : []); } catch { toast.error('Erro.'); }
            }}>
              <span className="material-symbols-outlined text-[16px] mr-1">add</span> Criar Backup
            </Button>
          </CardHeader>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left px-4 py-2 text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Arquivo</th>
                  <th className="text-left px-4 py-2 text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Tamanho</th>
                  <th className="text-left px-4 py-2 text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Data</th>
                  <th className="text-right px-4 py-2 text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Ações</th>
                </tr>
              </thead>
              <tbody>
                {backups.length === 0 ? (
                  <tr><td colSpan={4} className="px-4 py-8 text-center text-muted-foreground">Nenhum backup disponível.</td></tr>
                ) : (
                  backups.map((b) => (
                    <tr key={b.id} className="border-b border-border last:border-0 hover:bg-muted/50">
                      <td className="px-4 py-2 font-mono text-xs text-foreground">{b.filename}</td>
                      <td className="px-4 py-2 text-muted-foreground">{b.size}</td>
                      <td className="px-4 py-2 text-muted-foreground text-xs">{new Date(b.created_at).toLocaleString('pt-BR')}</td>
                      <td className="px-4 py-2 text-right">
                        <div className="flex justify-end gap-1">
                          <Button variant="ghost" size="icon" onClick={() => adminApi.downloadBackup(b.id)} aria-label="Download">
                            <span className="material-symbols-outlined text-[18px]">download</span>
                          </Button>
                          <Button variant="destructive" size="icon" onClick={async () => {
                            try { await adminApi.deleteBackup(b.id); setBackups((prev) => prev.filter((x) => x.id !== b.id)); toast.success('Backup excluído.'); } catch { toast.error('Erro.'); }
                          }} aria-label="Excluir">
                            <span className="material-symbols-outlined text-[18px]">delete</span>
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Tab: Performance */}
      {activeTab === 'performance' && (
        <div className="flex flex-col gap-6">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              { icon: 'timer', label: 'Uptime', value: perf.uptime ?? '—', color: 'text-green-500' },
              { icon: 'memory', label: 'RAM', value: perf.ram_usage != null ? `${perf.ram_usage}%` : '—', color: 'text-blue-500' },
              { icon: 'developer_board', label: 'CPU', value: perf.cpu_usage != null ? `${perf.cpu_usage}%` : '—', color: 'text-orange-500' },
              { icon: 'storage', label: 'Disco', value: perf.disk_usage != null ? `${perf.disk_usage}%` : '—', color: 'text-purple-500' },
            ].map((m) => (
              <Card key={m.label}>
                <CardContent className="flex items-center gap-3">
                  <span className={`material-symbols-outlined text-[28px] ${m.color}`}>{m.icon}</span>
                  <div>
                    <p className="text-xl font-bold text-foreground">{m.value}</p>
                    <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">{m.label}</p>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
          <Card>
            <CardHeader><h2 className="text-sm font-bold text-foreground">Cache</h2></CardHeader>
            <CardContent>
              <Button variant="outline" onClick={async () => {
                try { await adminApi.clearCache(); toast.success('Cache limpo.'); } catch { toast.error('Erro.'); }
              }}>
                <span className="material-symbols-outlined text-[16px] mr-1">cached</span> Limpar Cache
              </Button>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Tab: Logs */}
      {activeTab === 'logs' && (
        <Card>
          <CardHeader className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-3 flex-1">
              <Input icon="search" placeholder="Buscar logs..." value={logSearch} onChange={(e) => setLogSearch(e.target.value)} containerClassName="flex-1 max-w-sm" />
              <Select value={logType} onChange={(e) => setLogType(e.target.value)} containerClassName="w-36">
                <option value="all">Todos</option>
                <option value="info">Info</option>
                <option value="warning">Warning</option>
                <option value="error">Error</option>
              </Select>
              <Button variant="outline" size="sm" onClick={handleSearchLogs}>Filtrar</Button>
            </div>
            <Button variant="outline" size="sm" onClick={handleExportLogs}>
              <span className="material-symbols-outlined text-[16px] mr-1">download</span> Exportar CSV
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
                  <tr><td colSpan={4} className="px-4 py-8 text-center text-muted-foreground">Nenhum log encontrado.</td></tr>
                ) : (
                  logs.map((log) => (
                    <tr key={log.id} className="border-b border-border last:border-0 hover:bg-muted/50">
                      <td className="px-4 py-2">
                        <Badge variant={log.type === 'error' ? 'danger' : log.type === 'warning' ? 'warning' : 'outline'}>{log.type}</Badge>
                      </td>
                      <td className="px-4 py-2 text-foreground max-w-md truncate">{log.message}</td>
                      <td className="px-4 py-2 text-muted-foreground">{log.author ?? '—'}</td>
                      <td className="px-4 py-2 text-muted-foreground text-xs">{new Date(log.created_at).toLocaleString('pt-BR')}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
