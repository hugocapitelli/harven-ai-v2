import { HTMLAttributes } from 'react';
import { cn } from '../../lib/utils';

interface SkeletonProps extends HTMLAttributes<HTMLDivElement> {}

function Skeleton({ className, ...props }: SkeletonProps) {
  return (
    <div
      className={cn('animate-pulse rounded-md bg-gray-700/50', className)}
      {...props}
    />
  );
}

interface SkeletonCardProps extends HTMLAttributes<HTMLDivElement> {}

function SkeletonCard({ className, ...props }: SkeletonCardProps) {
  return (
    <div
      className={cn('rounded-xl border border-harven-border bg-harven-card p-6 space-y-4', className)}
      {...props}
    >
      <Skeleton className="h-40 w-full rounded-lg" />
      <Skeleton className="h-4 w-3/4" />
      <Skeleton className="h-4 w-1/2" />
      <Skeleton className="h-4 w-5/6" />
      <Skeleton className="h-2 w-full rounded-full" />
    </div>
  );
}

interface SkeletonTextProps extends HTMLAttributes<HTMLDivElement> {
  lines?: number;
}

function SkeletonText({ className, lines = 3, ...props }: SkeletonTextProps) {
  return (
    <div className={cn('space-y-2.5', className)} {...props}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={cn('h-4', i === lines - 1 ? 'w-2/3' : 'w-full')}
        />
      ))}
    </div>
  );
}

export { Skeleton, SkeletonCard, SkeletonText };
export type { SkeletonProps, SkeletonCardProps, SkeletonTextProps };
