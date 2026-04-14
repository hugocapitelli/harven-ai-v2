import { useState, ImgHTMLAttributes } from 'react';
import { cn } from '../../lib/utils';

type AvatarSize = 'sm' | 'md' | 'lg' | 'xl';

interface AvatarProps extends Omit<ImgHTMLAttributes<HTMLImageElement>, 'size'> {
  src?: string | null;
  fallback?: string;
  size?: AvatarSize;
}

const sizeStyles: Record<AvatarSize, string> = {
  sm: 'h-8 w-8 text-xs',
  md: 'h-10 w-10 text-sm',
  lg: 'h-14 w-14 text-lg',
  xl: 'h-20 w-20 text-xl',
};

function getInitials(name: string): string {
  return name.slice(0, 2).toUpperCase();
}

function Avatar({ src, fallback = '?', size = 'md', className, alt, ...props }: AvatarProps) {
  const [hasError, setHasError] = useState(false);
  const showImage = src && !hasError;

  return (
    <div
      className={cn(
        'relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-primary/20 text-primary font-semibold',
        sizeStyles[size],
        className
      )}
    >
      {showImage ? (
        <img
          src={src}
          alt={alt || fallback}
          className="h-full w-full object-cover"
          onError={() => setHasError(true)}
          {...props}
        />
      ) : (
        <span aria-hidden="true">{getInitials(fallback)}</span>
      )}
    </div>
  );
}

export { Avatar };
export type { AvatarProps, AvatarSize };
