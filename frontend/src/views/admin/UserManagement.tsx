// @ts-nocheck
import { useState, useEffect, useRef } from 'react';
import { toast } from 'sonner';
import { usersApi } from '../../services/api';
import { unwrapList } from '../../lib/utils';
import { Button } from '../../components/ui/Button';
import { Card, CardHeader } from '../../components/ui/Card';
import { Input } from '../../components/ui/Input';
import { Select } from '../../components/ui/Select';
import { Badge } from '../../components/ui/Badge';
import { Avatar } from '../../components/ui/Avatar';
import { Skeleton } from '../../components/ui/Skeleton';
import { EmptyState } from '../../components/ui/EmptyState';
import { Modal } from '../../components/ui/Modal';
import { SearchInput } from '../../components/ui/SearchInput';
import { PageHeader } from '../../components/ui/PageHeader';
import type { User, UserRole } from '../../types';

interface ApiUser extends User {
  ra?: string;
  title?: string;
  created_at?: string;
  status?: string;
}

const ROLE_LABELS: Record<UserRole, string> = {
  STUDENT: 'Aluno',
  INSTRUCTOR: 'Professor',
  ADMIN: 'Admin',
};

const ROLE_VARIANT: Record<UserRole, 'default' | 'success' | 'warning' | 'danger'> = {
  STUDENT: 'default',
  INSTRUCTOR: 'success',
  ADMIN: 'danger',
};

const EMPTY_FORM = { name: '', ra: '', email: '', password: '', role: 'STUDENT' as UserRole, title: '' };

export default function UserManagement() {
  const [users, setUsers] = useState<ApiUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState<string>('all');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [editingUser, setEditingUser] = useState<ApiUser | null>(null);
  const csvRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        setLoading(true);
        const params = roleFilter !== 'all' ? { role: roleFilter } : undefined;
        const data = await usersApi.list(params as Record<string, string>);
        if (controller.signal.aborted) return;
        setUsers(unwrapList(data));
      } catch {
        if (controller.signal.aborted) return;
        toast.error('Erro ao carregar usuários.');
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    load();
    return () => controller.abort();
  }, [roleFilter]);

  const filtered = users.filter(
    (u) =>
      u.name.toLowerCase().includes(search.toLowerCase()) ||
      (u.email ?? '').toLowerCase().includes(search.toLowerCase()) ||
      (u.ra ?? '').toLowerCase().includes(search.toLowerCase()),
  );

  const handleCreate = async () => {
    if (!form.name.trim() || !form.email.trim() || !form.ra.trim()) {
      toast.error('Nome, RA e email são obrigatórios.');
      return;
    }
    if (!form.password.trim() || form.password.length < 6) {
      toast.error('Defina uma senha temporária (mínimo 6 caracteres).');
      return;
    }
    setSaving(true);
    try {
      await usersApi.create(form as Record<string, unknown>);
      toast.success('Usuário criado.');
      setShowCreateModal(false);
      setForm(EMPTY_FORM);
      const data = await usersApi.list();
      setUsers(unwrapList(data));
    } catch (err: any) {
      const msg = err?.response?.data?.detail || 'Erro ao criar usuário.';
      toast.error(String(msg));
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = async () => {
    if (!editingUser) return;
    setSaving(true);
    try {
      await usersApi.update(editingUser.id, form as Record<string, unknown>);
      toast.success('Usuário atualizado.');
      setEditingUser(null);
      const data = await usersApi.list();
      setUsers(unwrapList(data));
    } catch {
      toast.error('Erro ao atualizar.');
    } finally {
      setSaving(false);
    }
  };

  const handleCsvImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    const lines = text.trim().split('\n').slice(1);
    const batch = lines.map((line) => {
      const [name, ra, email, role] = line.split(',').map((s) => s.trim());
      return { name, ra, email, role: (role?.toUpperCase() || 'STUDENT') as UserRole };
    }).filter((u) => u.name && u.email);

    if (batch.length === 0) { toast.error('CSV vazio ou inválido.'); return; }
    setSaving(true);
    try {
      await usersApi.createBatch(batch as Record<string, unknown>[]);
      toast.success(`${batch.length} usuários importados.`);
      const data = await usersApi.list();
      setUsers(unwrapList(data));
    } catch (err: any) {
      const msg = err?.response?.data?.detail || 'Erro na importação.';
      toast.error(String(msg));
    } finally {
      setSaving(false);
      if (csvRef.current) csvRef.current.value = '';
    }
  };

  const openEdit = (u: ApiUser) => {
    setForm({ name: u.name, ra: u.ra ?? '', email: u.email, password: '', role: u.role, title: u.title ?? '' });
    setEditingUser(u);
  };

  return (
    <div className="max-w-7xl mx-auto p-8 flex flex-col gap-6 animate-in fade-in duration-500">
      <PageHeader
        constrained={false}
        title="Gestão de Usuários"
        subtitle={loading ? '...' : `${filtered.length} usuário(s)`}
        actions={
          <>
            <input ref={csvRef} type="file" accept=".csv" className="hidden" onChange={handleCsvImport} />
            <Button variant="outline" onClick={() => csvRef.current?.click()}>
              <span className="material-symbols-outlined text-[16px] mr-1">upload_file</span> CSV
            </Button>
            <Button onClick={() => { setForm(EMPTY_FORM); setShowCreateModal(true); }}>
              <span className="material-symbols-outlined text-[16px] mr-1">person_add</span> Novo Usuário
            </Button>
          </>
        }
      />

      {/* Filters */}
      <div className="flex items-center gap-3">
        <SearchInput
          placeholder="Buscar por nome, email ou RA..."
          value={search}
          onChange={setSearch}
          className="flex-1 max-w-md"
        />
        <div className="flex border border-border rounded-lg overflow-hidden">
          {['all', 'STUDENT', 'INSTRUCTOR', 'ADMIN'].map((r) => (
            <button
              key={r}
              onClick={() => setRoleFilter(r)}
              className={`px-3 py-2 text-xs font-bold uppercase tracking-wide transition-colors ${
                roleFilter === r ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'
              }`}
            >
              {r === 'all' ? 'Todos' : ROLE_LABELS[r as UserRole]}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <Card>
        {loading ? (
          <div className="p-4 space-y-3">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left px-4 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Usuário</th>
                  <th className="text-left px-4 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wide">RA</th>
                  <th className="text-left px-4 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Role</th>
                  <th className="text-left px-4 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Status</th>
                  <th className="text-right px-4 py-3 text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Ações</th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr><td colSpan={5}><EmptyState icon="person_off" title="Nenhum usuário encontrado" description="Tente ajustar os filtros ou criar um novo usuário" size="sm" /></td></tr>
                ) : (
                  filtered.map((u) => (
                    <tr key={u.id} className="border-b border-border last:border-0 hover:bg-muted/50 transition-colors">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          <Avatar src={u.avatar_url} fallback={u.name} size="sm" />
                          <div>
                            <p className="font-medium text-foreground">{u.name}</p>
                            <p className="text-xs text-muted-foreground">{u.email}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground font-mono text-xs">{u.ra ?? '—'}</td>
                      <td className="px-4 py-3"><Badge variant={ROLE_VARIANT[u.role]}>{ROLE_LABELS[u.role]}</Badge></td>
                      <td className="px-4 py-3">
                        <Badge variant={u.status === 'blocked' ? 'danger' : 'success'}>
                          {u.status === 'blocked' ? 'Bloqueado' : 'Ativo'}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex justify-end gap-1">
                          <Button variant="ghost" size="icon" onClick={() => openEdit(u)} aria-label="Editar">
                            <span className="material-symbols-outlined text-[18px]">edit</span>
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={async () => {
                              try {
                                await usersApi.update(u.id, { status: u.status === 'blocked' ? 'active' : 'blocked' } as Record<string, unknown>);
                                toast.success(u.status === 'blocked' ? 'Usuário desbloqueado.' : 'Usuário bloqueado.');
                                setUsers((prev) => prev.map((x) => x.id === u.id ? { ...x, status: u.status === 'blocked' ? 'active' : 'blocked' } : x));
                              } catch { toast.error('Erro.'); }
                            }}
                            aria-label={u.status === 'blocked' ? 'Desbloquear' : 'Bloquear'}
                          >
                            <span className="material-symbols-outlined text-[18px]">{u.status === 'blocked' ? 'lock_open' : 'block'}</span>
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Create / Edit Modal */}
      <Modal.Root open={showCreateModal || !!editingUser} onClose={() => { setShowCreateModal(false); setEditingUser(null); }} size="md">
        <Modal.Header
          title={editingUser ? 'Editar Usuário' : 'Novo Usuário'}
          onClose={() => { setShowCreateModal(false); setEditingUser(null); }}
        />
        <Modal.Body>
          <div className="flex flex-col gap-4">
            <Input label="Nome" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} autoFocus />
            <Input label="RA" value={form.ra} onChange={(e) => setForm((f) => ({ ...f, ra: e.target.value }))} />
            <Input label="Email" type="email" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />
            {!editingUser && (
              <Input
                label="Senha temporária"
                type="password"
                value={form.password}
                onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
              />
            )}
            <Select label="Role" value={form.role} onChange={(e) => setForm((f) => ({ ...f, role: e.target.value as UserRole }))}>
              <option value="STUDENT">Aluno</option>
              <option value="INSTRUCTOR">Professor</option>
              <option value="ADMIN">Admin</option>
            </Select>
            {form.role === 'INSTRUCTOR' && (
              <Input
                label="Título"
                placeholder="Ex.: Dr., Prof., Me."
                value={form.title}
                onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
              />
            )}
          </div>
        </Modal.Body>
        <Modal.Footer>
          <Button variant="outline" onClick={() => { setShowCreateModal(false); setEditingUser(null); }}>Cancelar</Button>
          <Button onClick={editingUser ? handleEdit : handleCreate} disabled={saving}>
            {saving ? 'Salvando...' : editingUser ? 'Atualizar' : 'Criar'}
          </Button>
        </Modal.Footer>
      </Modal.Root>
    </div>
  );
}
