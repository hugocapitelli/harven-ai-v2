import { useState, useRef, useCallback, KeyboardEvent } from 'react';
import { cn } from '../../lib/utils';

type TabItem = string | { id: string; label: string; icon?: string };

interface TabsProps {
  items: TabItem[];
  value?: string;
  defaultValue?: string;
  onChange?: (value: string) => void;
  className?: string;
}

function getTabId(item: TabItem): string {
  return typeof item === 'string' ? item : item.id;
}

function getTabLabel(item: TabItem): string {
  return typeof item === 'string' ? item : item.label;
}

function getTabIcon(item: TabItem): string | undefined {
  return typeof item === 'string' ? undefined : item.icon;
}

function Tabs({ items, value, defaultValue, onChange, className }: TabsProps) {
  const [internalValue, setInternalValue] = useState(
    defaultValue || getTabId(items[0])
  );
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const activeValue = value ?? internalValue;

  const handleSelect = useCallback(
    (id: string) => {
      if (value === undefined) setInternalValue(id);
      onChange?.(id);
    },
    [value, onChange]
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent, index: number) => {
      let nextIndex: number | null = null;

      switch (e.key) {
        case 'ArrowRight':
          nextIndex = (index + 1) % items.length;
          break;
        case 'ArrowLeft':
          nextIndex = (index - 1 + items.length) % items.length;
          break;
        case 'Home':
          nextIndex = 0;
          break;
        case 'End':
          nextIndex = items.length - 1;
          break;
        default:
          return;
      }

      e.preventDefault();
      const nextId = getTabId(items[nextIndex]);
      handleSelect(nextId);
      tabRefs.current[nextIndex]?.focus();
    },
    [items, handleSelect]
  );

  return (
    <div
      role="tablist"
      aria-orientation="horizontal"
      className={cn(
        'inline-flex items-center gap-1 rounded-lg bg-harven-bg p-1',
        className
      )}
    >
      {items.map((item, index) => {
        const id = getTabId(item);
        const label = getTabLabel(item);
        const icon = getTabIcon(item);
        const isActive = activeValue === id;

        return (
          <button
            key={id}
            ref={(el) => { tabRefs.current[index] = el; }}
            role="tab"
            aria-selected={isActive}
            tabIndex={isActive ? 0 : -1}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-primary/50',
              isActive
                ? 'bg-harven-card text-white shadow-sm'
                : 'text-gray-400 hover:bg-harven-card/50 hover:text-gray-200'
            )}
            onClick={() => handleSelect(id)}
            onKeyDown={(e) => handleKeyDown(e, index)}
          >
            {icon && (
              <span className="material-symbols-outlined text-base">{icon}</span>
            )}
            {label}
          </button>
        );
      })}
    </div>
  );
}

export { Tabs };
export type { TabsProps, TabItem };
