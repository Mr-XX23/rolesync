import React, { useState, useEffect, useRef } from 'react';
import { Sun, Moon, Monitor } from 'lucide-react';
import { useTheme } from './ThemeProvider';

export const ThemeToggle: React.FC = () => {
  const { theme, setTheme } = useTheme();
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  // Keyboard accessibility
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsOpen(false);
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, []);

  const getThemeIcon = (t: typeof theme) => {
    switch (t) {
      case 'light':
        return <Sun className="w-4 h-4 text-amber-500 animate-spin-slow transition-transform" />;
      case 'dark':
        return <Moon className="w-4 h-4 text-indigo-400 dark:text-primary transition-transform" />;
      case 'system':
        return <Monitor className="w-4 h-4 text-muted-foreground transition-transform" />;
    }
  };

  const getThemeLabel = (t: typeof theme) => {
    switch (t) {
      case 'light':
        return 'Light';
      case 'dark':
        return 'Dark';
      case 'system':
        return 'System';
    }
  };

  return (
    <div className="fixed top-6 right-6 z-50 font-sans" ref={dropdownRef}>
      {/* Trigger Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        aria-label={`Toggle theme (Current: ${getThemeLabel(theme)})`}
        className="flex items-center justify-center w-10 h-10 rounded-full border border-border bg-card/85 backdrop-blur-md shadow-sm hover:shadow-md hover:scale-105 active:scale-95 transition-all duration-300 cursor-pointer focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary group"
      >
        <div className="group-hover:rotate-12 transition-transform duration-300">
          {getThemeIcon(theme)}
        </div>
      </button>

      {/* Dropdown Menu */}
      {isOpen && (
        <div
          role="listbox"
          aria-label="Select theme preference"
          className="absolute right-0 mt-2.5 w-36 rounded-xl border border-border bg-card/95 backdrop-blur-lg p-1.5 shadow-[0_10px_25px_-5px_rgba(0,0,0,0.1),0_8px_16px_-6px_rgba(0,0,0,0.05)] animate-in fade-in slide-in-from-top-3 duration-200"
        >
          {(['light', 'dark', 'system'] as const).map((t) => {
            const isActive = theme === t;
            return (
              <button
                key={t}
                role="option"
                aria-selected={isActive}
                onClick={() => {
                  setTheme(t);
                  setIsOpen(false);
                }}
                className={`flex items-center gap-2.5 w-full px-3 py-2 rounded-lg text-xs font-medium text-left cursor-pointer transition-all duration-150 ${
                  isActive
                    ? 'bg-primary text-primary-foreground font-semibold shadow-xs'
                    : 'text-foreground/80 hover:bg-muted/70 hover:text-foreground'
                }`}
              >
                <span className={`shrink-0 ${isActive ? 'text-current' : ''}`}>
                  {t === 'light' && <Sun className="w-3.5 h-3.5" />}
                  {t === 'dark' && <Moon className="w-3.5 h-3.5" />}
                  {t === 'system' && <Monitor className="w-3.5 h-3.5" />}
                </span>
                <span>{getThemeLabel(t)}</span>
                {isActive && (
                  <span className="ml-auto w-1.5 h-1.5 rounded-full bg-primary-foreground"></span>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};
