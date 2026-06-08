import React from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { Sparkles } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useAppDispatch } from '../../store';
import { clearActiveRole } from '../../store/roleSlice';

export interface SidebarItem {
  id: string;
  label: string;
  icon: LucideIcon;
  path: string;
}

interface SidebarProps {
  logo: {
    title: string;
    subtitle: string;
  };
  items: SidebarItem[];
  bottomItems?: SidebarItem[];
  actionButton?: {
    label: string;
    onClick: () => void;
    icon?: LucideIcon;
  };
  isOpen?: boolean;
  onClose?: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  logo,
  items,
  bottomItems = [],
  actionButton,
  isOpen = true,
  onClose,
}) => {
  const navigate = useNavigate();
  const dispatch = useAppDispatch();

  const handleExitPersona = () => {
    dispatch(clearActiveRole());
    navigate('/select-role');
  };

  return (
    <>
      {/* Mobile Backdrop Overlay */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/40 backdrop-blur-sm z-40 md:hidden animate-in fade-in duration-200"
          onClick={onClose}
        />
      )}

      {/* Sidebar Navigation Panel */}
      <aside
        className={`fixed inset-y-0 left-0 flex flex-col h-screen w-64 bg-sidebar border-r border-border rounded-r-xl shadow-sm z-50 transition-all duration-300 md:sticky md:translate-x-0 ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Header Branding */}
        <div className="px-6 py-6 mb-4 flex items-center justify-between border-b border-border/40">
          <div>
            <h1 className="font-serif text-2xl font-bold text-primary tracking-tight">
              {logo.title}
            </h1>
            <p className="text-xs font-medium text-muted-foreground/80 tracking-wider uppercase">
              {logo.subtitle}
            </p>
          </div>
          <button
            onClick={handleExitPersona}
            className="p-1.5 rounded-lg border border-border/60 hover:bg-muted text-muted-foreground transition-all duration-200 active:scale-95"
            title="Switch Persona"
          >
            <Sparkles className="w-4 h-4" />
          </button>
        </div>

        {/* Primary Menu Items */}
        <nav className="flex-1 space-y-1.5 px-3 overflow-y-auto">
          {items.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.id}
                to={item.path}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-4 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 active:scale-98 ${
                    isActive
                      ? 'bg-primary/10 text-primary font-bold shadow-2xs border border-primary/10'
                      : 'text-muted-foreground hover:bg-muted hover:text-foreground border border-transparent'
                  }`
                }
                onClick={onClose}
              >
                <Icon className="w-5 h-5 shrink-0" />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>

        {/* Action Button & Bottom Section Items */}
        <div className="px-3 py-4 mt-auto border-t border-border/50 bg-sidebar/50 space-y-3">
          {actionButton && (
            <button
              onClick={actionButton.onClick}
              className="w-full bg-primary text-primary-foreground font-semibold py-3 px-4 rounded-xl shadow-sm hover:opacity-95 active:scale-95 transition-all duration-200 flex items-center justify-center gap-2 text-sm"
            >
              {actionButton.icon && <actionButton.icon className="w-4 h-4" />}
              <span>{actionButton.label}</span>
            </button>
          )}

          {bottomItems.length > 0 && (
            <div className="space-y-1">
              {bottomItems.map((item) => {
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.id}
                    to={item.path}
                    className={({ isActive }) =>
                      `flex items-center gap-3 px-4 py-2 rounded-xl text-sm font-medium transition-all duration-200 ${
                        isActive
                          ? 'bg-primary/15 text-primary font-bold shadow-2xs'
                          : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                      }`
                    }
                    onClick={onClose}
                  >
                    <Icon className="w-4 h-4 shrink-0" />
                    <span className="text-xs">{item.label}</span>
                  </NavLink>
                );
              })}
            </div>
          )}
        </div>
      </aside>
    </>
  );
};
