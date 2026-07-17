// @ts-nocheck
import { useState, useRef } from 'react';
import { toast } from 'sonner';
import { useAuth } from '../../contexts/AuthContext';
import { usersApi } from '../../services/api';
import { Button } from '../../components/ui/Button';
import { Card, CardContent, CardHeader } from '../../components/ui/Card';
import { Input } from '../../components/ui/Input';
import { Tabs } from '../../components/ui/Tabs';
import { Avatar } from '../../components/ui/Avatar';

// Aba 'Notificações' removida: os toggles nao persistiam em lugar nenhum
// (nenhum endpoint de preferencias confirmado) — UI decorativa engana o aluno.
// Reintroduzir quando o backend expuser preferencias reais no contrato /me.
const TABS = [
  { id: 'profile', label: 'Perfil', icon: 'person' },
  { id: 'security', label: 'Segurança', icon: 'lock' },
];

export default function AccountSettings() {
  const { user, updateUser } = useAuth();
  const avatarRef = useRef<HTMLInputElement>(null);

  const [activeTab, setActiveTab] = useState('profile');
  const [saving, setSaving] = useState(false);

  // Profile
  const [name, setName] = useState(user?.name ?? '');
  const [email, setEmail] = useState(user?.email ?? '');
  const [title, setTitle] = useState(user?.title ?? '');
  const [bio, setBio] = useState(user?.bio ?? '');
  const [avatarPreview, setAvatarPreview] = useState(user?.avatar_url ?? '');

  // Security
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  const handleSaveProfile = async () => {
    if (!user?.id || !name.trim()) { toast.error('Nome é obrigatório.'); return; }
    setSaving(true);
    try {
      // PUT /users/{id} e ADMIN-only (403 para aluno) — perfil proprio usa PUT /me.
      await usersApi.updateMe({ name, email, title, bio } as Record<string, unknown>);
      updateUser({ name, email, title, bio });
      toast.success('Perfil atualizado.');
    } catch {
      toast.error('Erro ao atualizar perfil.');
    } finally {
      setSaving(false);
    }
  };

  const handleAvatarChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !user?.id) return;
    setAvatarPreview(URL.createObjectURL(file));
    try {
      // NOTE (infra follow-up, fora do escopo deste pacote): se a imagem ainda
      // falhar ao carregar após este fix, confirmar que API_BASE_URL está
      // configurada em produção (storage_service._get_base_url) OU que o proxy
      // do frontend expõe /uploads na mesma origem — sem isso, a URL retornada
      // pode ser relativa e quebrar fora do host da API.
      const result = await usersApi.uploadAvatar(user.id, file);
      const url = result.avatar_url ?? result.url;
      if (url) {
        setAvatarPreview(url);
        updateUser({ avatar_url: url });
      }
      toast.success('Avatar atualizado.');
    } catch {
      toast.error('Erro no upload do avatar.');
    }
  };

  const handleChangePassword = async () => {
    if (!user?.id) return;
    if (!currentPassword || !newPassword) { toast.error('Preencha todos os campos.'); return; }
    if (newPassword !== confirmPassword) { toast.error('As senhas não coincidem.'); return; }
    if (newPassword.length < 8) { toast.error('Senha deve ter pelo menos 8 caracteres.'); return; }
    setSaving(true);
    try {
      await usersApi.updateMe({ current_password: currentPassword, password: newPassword } as Record<string, unknown>);
      toast.success('Senha alterada.');
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } catch {
      toast.error('Erro ao alterar senha. Verifique a senha atual.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto p-8 flex flex-col gap-6 animate-in fade-in duration-500">
      <h1 className="text-2xl font-display font-bold text-foreground">Configurações da Conta</h1>

      <Tabs items={TABS} activeTab={activeTab} onChange={setActiveTab} ariaLabel="Seções da conta" />

      {/* Tab: Profile */}
      {activeTab === 'profile' && (
        <Card>
          <CardContent className="flex flex-col gap-6">
            {/* Avatar */}
            <div className="flex items-center gap-4">
              <Avatar src={avatarPreview} fallback={name} size="xl" />
              <div>
                <input ref={avatarRef} type="file" accept="image/*" className="hidden" onChange={handleAvatarChange} />
                <Button variant="outline" size="sm" onClick={() => avatarRef.current?.click()}>
                  <span className="material-symbols-outlined text-[16px] mr-1">photo_camera</span>
                  Alterar Foto
                </Button>
                <p className="text-[10px] text-muted-foreground mt-1">JPG, PNG ou GIF. Máx 2MB.</p>
              </div>
            </div>

            <Input label="Nome" value={name} onChange={(e) => setName(e.target.value)} />
            <Input label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            <Input label="RA" value={user?.ra ?? ''} disabled className="opacity-60" />
            <Input label="Título" placeholder="Ex.: Prof., Dr., Me." value={title} onChange={(e) => setTitle(e.target.value)} />

            <div className="space-y-1.5">
              <label className="block text-[11px] font-medium text-muted-foreground uppercase tracking-wide">Bio</label>
              <textarea
                rows={3}
                value={bio}
                onChange={(e) => setBio(e.target.value)}
                className="w-full bg-harven-bg border-none rounded-lg text-sm text-foreground placeholder-gray-400 focus:ring-1 focus:ring-primary px-4 py-2 resize-none"
                placeholder="Conte um pouco sobre você..."
              />
            </div>

            <Button onClick={handleSaveProfile} disabled={saving}>
              {saving ? 'Salvando...' : 'Salvar Perfil'}
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Tab: Security */}
      {activeTab === 'security' && (
        <Card>
          <CardHeader><h2 className="text-sm font-semibold text-foreground">Alterar Senha</h2></CardHeader>
          <CardContent className="flex flex-col gap-4">
            <Input
              label="Senha Atual"
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
            />
            <Input
              label="Nova Senha"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />
            <Input
              label="Confirmar Nova Senha"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
            />
            {newPassword && confirmPassword && newPassword !== confirmPassword && (
              <p className="text-xs text-destructive">As senhas não coincidem.</p>
            )}
            <Button onClick={handleChangePassword} disabled={saving || !currentPassword || !newPassword || newPassword !== confirmPassword}>
              {saving ? 'Alterando...' : 'Alterar Senha'}
            </Button>
          </CardContent>
        </Card>
      )}

    </div>
  );
}
