import { useEffect, useRef, useState } from 'react';
import { cn } from '../../lib/utils';
import { Skeleton } from './Skeleton';

interface StatCardProps {
  icon: string;
  value: string | number;
  label: string;
  trend?: {
    direction: 'up' | 'down' | 'neutral';
    value: string;
  };
  loading?: boolean;
  variant?: 'default' | 'highlight';
  className?: string;
}

function useAnimatedNumber(target: number, duration = 800) {
  const [display, setDisplay] = useState(0);
  const raf = useRef<number>(undefined);

  useEffect(() => {
    if (target === 0) { setDisplay(0); return; }
    const start = performance.now();
    const from = 0;
    const animate = (now: number) => {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
      setDisplay(Math.round(from + (target - from) * eased));
      if (progress < 1) raf.current = requestAnimationFrame(animate);
    };
    raf.current = requestAnimationFrame(animate);
    return () => { if (raf.current) cancelAnimationFrame(raf.current); };
  }, [target, duration]);

  return display;
}

const trendIcon = { up: 'trending_up', down: 'trending_down', neutral: 'trending_flat' };
const trendColor = { up: 'text-green-400', down: 'text-red-400', neutral: 'text-gray-400' };

function StatCard({ icon, value, label, trend, loading, variant = 'default', className }: StatCardProps) {
  const numericValue = typeof value === 'number' ? value : parseFloat(value);
  const isNumeric = !isNaN(numericValue) && typeof value === 'number';
  const animated = useAnimatedNumber(isNumeric ? numericValue : 0);

  if (loading) {
    return (
      <div className={cn('rounded-xl border border-harven-border bg-card p-6 space-y-3', className)}>
        <Skeleton className="size-10 rounded-lg" />
        <Skeleton className="h-8 w-20" />
        <Skeleton className="h-3 w-24" />
      </div>
    );
  }

  const isHighlight = variant === 'highlight';

  return (
    <div
      className={cn(
        'rounded-xl border p-6 transition-colors duration-150',
        isHighlight
          ? 'border-harven-dark bg-harven-dark text-white'
          : 'border-harven-border bg-card',
        className
      )}
    >
      <div className={cn(
        'mb-3 inline-flex items-center justify-center size-10 rounded-lg',
        isHighlight ? 'bg-primary/20' : 'bg-harven-bg'
      )}>
        <span className={cn(
          'material-symbols-outlined text-xl',
          isHighlight ? 'text-primary' : 'text-muted-foreground'
        )}>
          {icon}
        </span>
      </div>

      <div className={cn('font-display text-3xl font-bold', isHighlight && 'text-primary')}>
        {isNumeric ? animated : value}
      </div>

      <div className="mt-1 flex items-center gap-2">
        <span className={cn('text-xs', isHighlight ? 'text-gray-300' : 'text-muted-foreground')}>
          {label}
        </span>
        {trend && (
          <span className={cn('inline-flex items-center gap-0.5 text-xs font-medium', trendColor[trend.direction])}>
            <span className="material-symbols-outlined text-sm">{trendIcon[trend.direction]}</span>
            {trend.value}
          </span>
        )}
      </div>
    </div>
  );
}

export { StatCard };
export type { StatCardProps };
