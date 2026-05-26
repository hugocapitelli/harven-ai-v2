import { forwardRef, useId } from 'react';
import { cn } from '../../lib/utils';

interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: string;
  description?: string;
  disabled?: boolean;
  size?: 'sm' | 'md';
  className?: string;
}

const trackSize = {
  sm: 'h-5 w-9',
  md: 'h-6 w-11',
};

const knobSize = {
  sm: 'size-3.5',
  md: 'size-4',
};

const knobTranslate = {
  sm: 'translate-x-4',
  md: 'translate-x-5',
};

const Toggle = forwardRef<HTMLButtonElement, ToggleProps>(
  ({ checked, onChange, label, description, disabled, size = 'md', className }, ref) => {
    const id = useId();

    return (
      <div className={cn('flex items-start gap-3', className)}>
        <button
          ref={ref}
          id={id}
          role="switch"
          type="button"
          aria-checked={checked}
          aria-label={label}
          disabled={disabled}
          onClick={() => onChange(!checked)}
          className={cn(
            'relative inline-flex shrink-0 cursor-pointer items-center rounded-full transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-primary/50 focus:ring-offset-2 focus:ring-offset-harven-dark disabled:opacity-50 disabled:cursor-not-allowed',
            trackSize[size],
            checked ? 'bg-primary' : 'bg-gray-600'
          )}
        >
          <span
            className={cn(
              'inline-block rounded-full bg-white shadow-sm transition-transform duration-200',
              knobSize[size],
              checked ? knobTranslate[size] : 'translate-x-1'
            )}
          />
        </button>
        {(label || description) && (
          <div className="flex flex-col">
            {label && (
              <label htmlFor={id} className="text-sm font-medium text-foreground cursor-pointer">
                {label}
              </label>
            )}
            {description && (
              <p className="text-xs text-muted-foreground">{description}</p>
            )}
          </div>
        )}
      </div>
    );
  }
);

Toggle.displayName = 'Toggle';

export { Toggle };
export type { ToggleProps };
