import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';
import { publicApi, adminApi } from '../services/api';
import type { SystemSettings } from '../types';

const defaults: SystemSettings = {
  platform_name: 'Harven',
  primary_color: '#d0ff00',
  session_timeout: 3600,
  ai_tutor_enabled: true,
  gamification_enabled: true,
  dark_mode_enabled: false,
  max_upload_mb: 500,
  max_tokens_per_response: 2048,
  daily_token_limit: 50000,
  min_password_length: 8,
  require_special_chars: false,
  password_expiration_days: 0,
};

interface SettingsState {
  settings: SystemSettings;
  loading: boolean;
  refreshSettings: () => Promise<void>;
  updateSettings: (partial: Partial<SystemSettings>) => Promise<void>;
}

const SettingsContext = createContext<SettingsState | null>(null);

function applyCssVars(s: SystemSettings) {
  const root = document.documentElement;
  if (s.primary_color) {
    root.style.setProperty('--color-primary', s.primary_color);
    root.style.setProperty('--color-harven-primary', s.primary_color);
    root.style.setProperty('--color-ring', s.primary_color);
  }
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<SystemSettings>(defaults);
  const [loading, setLoading] = useState(true);

  const refreshSettings = useCallback(async () => {
    try {
      const data = await publicApi.getSettings();
      const merged = { ...defaults, ...data };
      setSettings(merged);
      applyCssVars(merged);
    } catch {
      setSettings(defaults);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refreshSettings(); }, [refreshSettings]);

  const updateSettings = useCallback(async (partial: Partial<SystemSettings>) => {
    const merged = { ...settings, ...partial };
    setSettings(merged);
    applyCssVars(merged);
    await adminApi.updateSettings(merged);
  }, [settings]);

  return (
    <SettingsContext.Provider value={{ settings, loading, refreshSettings, updateSettings }}>
      {children}
    </SettingsContext.Provider>
  );
}

export function useSettings() {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error('useSettings must be used within SettingsProvider');
  return ctx;
}
