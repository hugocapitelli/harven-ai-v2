import { cn } from '../../lib/utils';
import { Button } from './Button';

interface EmptyStateProps {
  icon: string;
  title: string;
  description?: string;
  action?: {
    label: string;
    onClick: () => void;
    variant?: 'primary' | 'outline';
  };
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

const sizeStyles = {
  sm: { container: 'py-8', icon: 'text-4xl', title: 'text-sm' },
  md: { container: 'py-12', icon: 'text-5xl', title: 'text-base' },
  lg: { container: 'py-16', icon: 'text-6xl', title: 'text-lg' },
};

function EmptyState({ icon, title, description, action, size = 'md', className }: EmptyStateProps) {
  const s = sizeStyles[size];

  return (
    <div className={cn('flex flex-col items-center justify-center text-center', s.container, className)}>
      <span className={cn('material-symbols-outlined mb-3 text-gray-300', s.icon)}>
        {icon}
      </span>
      <p className={cn('font-display font-bold text-gray-400', s.title)}>{title}</p>
      {description && (
        <p className="mt-1 max-w-sm text-xs text-gray-500">{description}</p>
      )}
      {action && (
        <div className="mt-4">
          <Button variant={action.variant || 'primary'} size="sm" onClick={action.onClick}>
            {action.label}
          </Button>
        </div>
      )}
    </div>
  );
}

export { EmptyState };
export type { EmptyStateProps };
