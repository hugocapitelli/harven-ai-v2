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

const TABS = [
  { id: 'profile', label: 'Perfil', icon: 'person' },
  { id: 'security', label: 'Segurança', icon: 'lock' },
  { id: 'notifications', label: 'Notificações', icon: 'notifications' },
];

function Toggle({ checked, onChange, label, description }: { checked: boolean; onChange: (v: boolean) => void; label: string; description?: string }) {
  return (
    <label className="flex items-center justify-between py-3 border-b border-border last:border-0 cursor-pointer">
      <div>
        <span className="text-sm font-medium text-foreground">{label}</span>
        {description && <p className="text-xs text-muted-foreground mt-0.5">{description}</p>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative h-6 w-11 rounded-full transition-colors shrink-0 ${checked ? 'bg-primary' : 'bg-muted'}`}
      >
        <span className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-5' : ''}`} />
      </button>
    </label>
  );
}

export default function AccountSettings() {
  const { user } = useAuth();
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

  // Notifications
  const [notifPrefs, setNotifPrefs] = useState({
    email_new_content: true,
    email_reviews: true,
    email_achievements: true,
    push_messages: true,
    push_reminders: false,
  });

  const handleSaveProfile = async () => {
    if (!user?.id || !name.trim()) { toast.error('Nome é obrigatório.'); return; }
    setSaving(true);
    try {
      await usersApi.update(user.id, { name, email, title, bio } as Record<string, unknown>);
      const savedUser = JSON.parse(sessionStorage.getItem('user-data') ?? '{}');
      sessionStorage.setItem('user-data', JSON.stringify({ ...savedUser, name, email, title, bio }));
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
      const result = await usersApi.uploadAvatar(user.id, file);
      const url = result.avatar_url ?? result.url;
      if (url) {
        setAvatarPreview(url);
        const savedUser = JSON.parse(sessionStorage.getItem('user-data') ?? '{}');
        sessionStorage.setItem('user-data', JSON.stringify({ ...savedUser, avatar_url: url }));
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
      await usersApi.update(user.id, { current_password: currentPassword, password: newPassword } as Record<string, unknown>);
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

  const handleSaveNotifications = async () => {
    if (!user?.id) return;
    setSaving(true);
    try {
      await usersApi.update(user.id, { notification_preferences: notifPrefs } as Record<string, unknown>);
      toast.success('Preferências salvas.');
    } catch {
      toast.error('Erro ao salvar preferências.');
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
              <label className="block text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Bio</label>
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
          <CardHeader><h2 className="text-sm font-bold text-foreground">Alterar Senha</h2></CardHeader>
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

      {/* Tab: Notifications */}
      {activeTab === 'notifications' && (
        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader><h2 className="text-sm font-bold text-foreground">Email</h2></CardHeader>
            <CardContent>
              <Toggle
                label="Novo conteúdo disponível"
                description="Receber email quando novos materiais forem publicados"
                checked={notifPrefs.email_new_content}
                onChange={(v) => setNotifPrefs((p) => ({ ...p, email_new_content: v }))}
              />
              <Toggle
                label="Avaliações de sessões"
                description="Receber email quando uma sessão for avaliada"
                checked={notifPrefs.email_reviews}
                onChange={(v) => setNotifPrefs((p) => ({ ...p, email_reviews: v }))}
              />
              <Toggle
                label="Conquistas desbloqueadas"
                description="Receber email ao desbloquear uma conquista"
                checked={notifPrefs.email_achievements}
                onChange={(v) => setNotifPrefs((p) => ({ ...p, email_achievements: v }))}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader><h2 className="text-sm font-bold text-foreground">Push</h2></CardHeader>
            <CardContent>
              <Toggle
                label="Mensagens"
                description="Notificações de novas mensagens"
                checked={notifPrefs.push_messages}
                onChange={(v) => setNotifPrefs((p) => ({ ...p, push_messages: v }))}
              />
              <Toggle
                label="Lembretes de estudo"
                description="Lembretes diários para estudar"
                checked={notifPrefs.push_reminders}
                onChange={(v) => setNotifPrefs((p) => ({ ...p, push_reminders: v }))}
              />
            </CardContent>
          </Card>

          <Button onClick={handleSaveNotifications} disabled={saving}>
            {saving ? 'Salvando...' : 'Salvar Preferências'}
          </Button>
        </div>
      )}
    </div>
  );
}
