import { useState, useEffect, useRef, useCallback } from 'react';
import { cn } from '../../lib/utils';

interface SearchInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  debounceMs?: number;
  loading?: boolean;
  className?: string;
}

function SearchInput({
  value,
  onChange,
  placeholder = 'Buscar...',
  debounceMs = 300,
  loading,
  className,
}: SearchInputProps) {
  const [internal, setInternal] = useState(value);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    setInternal(value);
  }, [value]);

  const handleChange = useCallback(
    (v: string) => {
      setInternal(v);
      clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => onChange(v), debounceMs);
    },
    [onChange, debounceMs]
  );

  useEffect(() => {
    return () => clearTimeout(timerRef.current);
  }, []);

  return (
    <div className={cn('relative', className)}>
      <span className="material-symbols-outlined pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-lg text-gray-500">
        {loading ? 'progress_activity' : 'search'}
      </span>
      <input
        type="text"
        value={internal}
        onChange={(e) => handleChange(e.target.value)}
        placeholder={placeholder}
        className={cn(
          'w-full rounded-lg border border-harven-border bg-harven-bg pl-10 pr-9 py-2.5 text-sm text-foreground placeholder:text-gray-500 transition-colors duration-150 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20',
          loading && '[&>span]:animate-spin'
        )}
      />
      {internal.length > 0 && !loading && (
        <button
          type="button"
          onClick={() => handleChange('')}
          className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-foreground transition-colors"
          aria-label="Limpar busca"
        >
          <span className="material-symbols-outlined text-lg">close</span>
        </button>
      )}
    </div>
  );
}

export { SearchInput };
export type { SearchInputProps };
