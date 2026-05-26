import { cn } from '../../lib/utils';

interface BreadcrumbItem {
  label: string;
  onClick?: () => void;
}

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  backAction?: {
    label?: string;
    onClick: () => void;
  };
  breadcrumbs?: BreadcrumbItem[];
  actions?: React.ReactNode;
  constrained?: boolean;
  className?: string;
}

function PageHeader({
  title,
  subtitle,
  backAction,
  breadcrumbs,
  actions,
  constrained = true,
  className,
}: PageHeaderProps) {
  return (
    <div className={cn('mb-8', constrained && 'max-w-7xl mx-auto', className)}>
      {/* Breadcrumbs */}
      {breadcrumbs && breadcrumbs.length > 0 && (
        <nav aria-label="Breadcrumb" className="mb-3">
          <ol className="flex items-center gap-1 text-xs text-muted-foreground">
            {breadcrumbs.map((item, i) => {
              const isLast = i === breadcrumbs.length - 1;
              return (
                <li key={i} className="flex items-center gap-1">
                  {i > 0 && (
                    <span className="material-symbols-outlined text-sm text-gray-400">chevron_right</span>
                  )}
                  {isLast || !item.onClick ? (
                    <span className={cn(isLast && 'text-foreground font-medium')}>
                      {item.label}
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={item.onClick}
                      className="hover:text-foreground transition-colors"
                    >
                      {item.label}
                    </button>
                  )}
                </li>
              );
            })}
          </ol>
        </nav>
      )}

      {/* Header row */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          {backAction && (
            <button
              type="button"
              onClick={backAction.onClick}
              className="inline-flex items-center gap-1 rounded-lg p-2 text-gray-400 hover:text-foreground hover:bg-harven-bg transition-colors"
              aria-label={backAction.label || 'Voltar'}
            >
              <span className="material-symbols-outlined text-xl">arrow_back</span>
            </button>
          )}
          <div>
            <h1 className="font-display text-2xl font-bold text-foreground">{title}</h1>
            {subtitle && (
              <p className="mt-0.5 text-sm text-muted-foreground">{subtitle}</p>
            )}
          </div>
        </div>

        {actions && (
          <div className="flex items-center gap-2 shrink-0">
            {actions}
          </div>
        )}
      </div>
    </div>
  );
}

export { PageHeader };
export type { PageHeaderProps, BreadcrumbItem };
