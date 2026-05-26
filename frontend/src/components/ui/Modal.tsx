import { HTMLAttributes, forwardRef, useEffect, useRef } from 'react';
import { cn } from '../../lib/utils';

/* ─── Modal.Root ─── */

interface ModalRootProps {
  open: boolean;
  onClose: () => void;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  children: React.ReactNode;
  className?: string;
}

const sizeMap = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-xl',
};

function ModalRoot({ open, onClose, size = 'md', children, className }: ModalRootProps) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<Element | null>(null);

  // Capture the trigger element on open
  useEffect(() => {
    if (open) {
      triggerRef.current = document.activeElement;
    }
  }, [open]);

  // Restore focus on close
  useEffect(() => {
    if (!open && triggerRef.current instanceof HTMLElement) {
      triggerRef.current.focus();
      triggerRef.current = null;
    }
  }, [open]);

  // Escape key
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  // Focus trap
  useEffect(() => {
    if (!open) return;
    const overlay = overlayRef.current;
    if (!overlay) return;

    const focusable = overlay.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    first?.focus();

    const trap = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return;
      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    overlay.addEventListener('keydown', trap);
    return () => overlay.removeEventListener('keydown', trap);
  }, [open]);

  // Prevent body scroll
  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => { document.body.style.overflow = ''; };
  }, [open]);

  if (!open) return null;

  return (
    <div ref={overlayRef} className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm animate-[fadeIn_150ms_ease-out]"
        onClick={onClose}
        aria-hidden="true"
      />
      {/* Dialog */}
      <div
        className={cn(
          'relative w-full rounded-xl border border-harven-border bg-card shadow-xl animate-[modalIn_200ms_ease-out]',
          sizeMap[size],
          className
        )}
      >
        {children}
      </div>
    </div>
  );
}

/* ─── Modal.Header ─── */

interface ModalHeaderProps extends HTMLAttributes<HTMLDivElement> {
  title: string;
  onClose?: () => void;
}

const ModalHeader = forwardRef<HTMLDivElement, ModalHeaderProps>(
  ({ title, onClose, className, children, ...props }, ref) => (
    <div ref={ref} className={cn('flex items-center justify-between p-6 border-b border-harven-border', className)} {...props}>
      <h2 className="font-display text-lg font-bold text-foreground">{title}</h2>
      {children}
      {onClose && (
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg p-1 text-gray-400 hover:text-foreground hover:bg-harven-bg transition-colors"
          aria-label="Fechar"
        >
          <span className="material-symbols-outlined text-xl">close</span>
        </button>
      )}
    </div>
  )
);
ModalHeader.displayName = 'ModalHeader';

/* ─── Modal.Body ─── */

const ModalBody = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, children, ...props }, ref) => (
    <div ref={ref} className={cn('p-6', className)} {...props}>
      {children}
    </div>
  )
);
ModalBody.displayName = 'ModalBody';

/* ─── Modal.Footer ─── */

const ModalFooter = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, children, ...props }, ref) => (
    <div ref={ref} className={cn('flex items-center justify-end gap-3 p-6 pt-0', className)} {...props}>
      {children}
    </div>
  )
);
ModalFooter.displayName = 'ModalFooter';

/* ─── Exports ─── */

const Modal = {
  Root: ModalRoot,
  Header: ModalHeader,
  Body: ModalBody,
  Footer: ModalFooter,
};

export { Modal, ModalRoot, ModalHeader, ModalBody, ModalFooter };
export type { ModalRootProps, ModalHeaderProps };
