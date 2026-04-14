/**
 * Concatena classes CSS filtrando valores falsy.
 */
export function cn(...classes: (string | boolean | undefined | null)[]): string {
  return classes.filter(Boolean).join(' ');
}

/**
 * Parse seguro de JSON armazenado em sessionStorage ou localStorage.
 * Remove a chave se o parse falhar (dados corrompidos).
 */
export function safeJsonParse<T>(key: string, fallback: T): T {
  try {
    const raw = sessionStorage.getItem(key) || localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    sessionStorage.removeItem(key);
    localStorage.removeItem(key);
    return fallback;
  }
}
