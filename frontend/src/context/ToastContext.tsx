import React, { createContext, useContext, useState, useCallback } from 'react';
import { CheckCircle2, AlertCircle, Info, AlertTriangle, X } from 'lucide-react';

export type ToastType = 'success' | 'error' | 'info' | 'warning';

export interface ToastItem {
  id: string;
  type: ToastType;
  message: string;
  title?: string;
  duration?: number;
}

interface ToastContextType {
  showToast: (type: ToastType, message: string, title?: string, duration?: number) => void;
  success: (message: string, title?: string, duration?: number) => void;
  error: (message: string, title?: string, duration?: number) => void;
  info: (message: string, title?: string, duration?: number) => void;
  warning: (message: string, title?: string, duration?: number) => void;
  removeToast: (id: string) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const showToast = useCallback(
    (type: ToastType, message: string, title?: string, duration = 4000) => {
      const id = `${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
      const newToast: ToastItem = { id, type, message, title, duration };

      setToasts((prev) => [...prev, newToast]);

      if (duration > 0) {
        setTimeout(() => {
          removeToast(id);
        }, duration);
      }
    },
    [removeToast]
  );

  const success = useCallback(
    (message: string, title?: string, duration?: number) => {
      showToast('success', message, title, duration);
    },
    [showToast]
  );

  const error = useCallback(
    (message: string, title?: string, duration?: number) => {
      showToast('error', message, title, duration);
    },
    [showToast]
  );

  const info = useCallback(
    (message: string, title?: string, duration?: number) => {
      showToast('info', message, title, duration);
    },
    [showToast]
  );

  const warning = useCallback(
    (message: string, title?: string, duration?: number) => {
      showToast('warning', message, title, duration);
    },
    [showToast]
  );

  return (
    <ToastContext.Provider value={{ showToast, success, error, info, warning, removeToast }}>
      {children}
      {/* Global Floating Toast Container */}
      <div className="fixed bottom-6 right-6 z-9999 flex flex-col gap-2.5 max-w-md w-full pointer-events-none px-4 sm:px-0">
        {toasts.map((t) => {
          let bgStyle = 'bg-card border-border text-foreground';
          let icon = <Info className="w-5 h-5 text-primary shrink-0" />;

          if (t.type === 'success') {
            bgStyle = 'bg-emerald-950/90 border-emerald-500/40 text-emerald-100 dark:bg-emerald-950/90';
            icon = <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />;
          } else if (t.type === 'error') {
            bgStyle = 'bg-rose-950/90 border-rose-500/40 text-rose-100 dark:bg-rose-950/90';
            icon = <AlertCircle className="w-5 h-5 text-rose-400 shrink-0" />;
          } else if (t.type === 'warning') {
            bgStyle = 'bg-amber-950/90 border-amber-500/40 text-amber-100 dark:bg-amber-950/90';
            icon = <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0" />;
          } else if (t.type === 'info') {
            bgStyle = 'bg-card/95 border-primary/40 text-foreground dark:bg-card/95';
            icon = <Info className="w-5 h-5 text-primary shrink-0" />;
          }

          return (
            <div
              key={t.id}
              className={`pointer-events-auto flex items-start gap-3 p-4 rounded-xl border shadow-xl backdrop-blur-md animate-in slide-in-from-bottom-5 fade-in duration-300 transition-all ${bgStyle}`}
              role="alert"
            >
              {icon}
              <div className="flex-1 space-y-0.5 pr-2">
                {t.title && (
                  <h5 className="font-bold text-xs font-serif tracking-wide">{t.title}</h5>
                )}
                <p className="text-xs leading-relaxed opacity-95">{t.message}</p>
              </div>
              <button
                type="button"
                onClick={() => removeToast(t.id)}
                className="p-1 rounded-lg opacity-70 hover:opacity-100 transition-opacity cursor-pointer text-inherit"
                aria-label="Close notification"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
};

export const useToast = (): ToastContextType => {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
};
