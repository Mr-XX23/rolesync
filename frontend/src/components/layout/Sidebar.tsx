import React from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { Sparkles, Plus } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useAppDispatch } from '../../store';
import { clearActiveRole } from '../../store/roleSlice';

export interface SidebarItem {
  id: string;
  label: string;
  icon: LucideIcon;
  path: string;
  badge?: string;
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
          className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40 md:hidden animate-in fade-in duration-200"
          onClick={onClose}
        />
      )}

      {/* Sidebar Navigation Panel */}
      <aside
        className={`fixed inset-y-0 left-0 flex flex-col h-screen w-64 bg-sidebar border-r border-sidebar-border z-50 transition-all duration-300 md:sticky md:translate-x-0 ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Header Branding */}
        <div className="p-3.5 mx-3 my-3 rounded-2xl flex items-center justify-between border border-border/40 bg-card/40 backdrop-blur-xs shadow-2xs">
          <div className="flex items-center gap-3 min-w-0">
            {/* Sleek Brand Logo Icon Emblem */}
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-primary/30 via-primary/15 to-transparent border border-primary/25 flex items-center justify-center shadow-xs text-primary shrink-0">
              <Sparkles className="w-4.5 h-4.5 text-primary animate-pulse" />
            </div>
            <div className="min-w-0">
              <h1 className="font-serif text-lg font-bold text-foreground tracking-tight leading-none mb-1 truncate">
                {logo.title}
              </h1>
              <span className="font-mono text-[9px] font-bold text-muted-foreground uppercase tracking-widest block leading-none truncate">
                {logo.subtitle}
              </span>
            </div>
          </div>

          <button
            onClick={handleExitPersona}
            className="p-1.5 rounded-lg border border-border/60 hover:border-primary/30 hover:bg-primary/10 text-muted-foreground hover:text-primary transition-all duration-200 cursor-pointer group shrink-0"
            title="Switch Persona Role"
          >
            <Sparkles className="w-3.5 h-3.5 transition-transform group-hover:rotate-12" />
          </button>
        </div>

        {/* Navigation Section Title */}
        <div className="px-5 pt-2 pb-1.5 flex items-center justify-between">
          <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-muted-foreground/70">
            Platform Hub
          </span>
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500/80 animate-ping" />
        </div>

        {/* Primary Navigation Menu */}
        <nav className="flex-1 space-y-1.5 px-3 overflow-y-auto scrollbar-none">
          {items.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.id}
                to={item.path}
                className={({ isActive }) =>
                  `group relative flex items-center justify-between px-3 py-2 rounded-xl text-xs font-semibold transition-all duration-200 cursor-pointer ${
                    isActive
                      ? 'bg-card border border-border/80 shadow-xs text-foreground font-bold'
                      : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground border border-transparent'
                  }`
                }
                onClick={onClose}
              >
                {({ isActive }) => (
                  <>
                    {/* Active Left Accent Indicator Bar */}
                    {isActive && (
                      <span className="absolute -left-1 w-1.5 h-5 rounded-r-full bg-primary shadow-xs shadow-primary" />
                    )}

                    <div className="flex items-center gap-3 min-w-0">
                      {/* Styled Tactile Icon Container Badge */}
                      <div
                        className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 transition-all duration-200 ${
                          isActive
                            ? 'bg-primary/20 text-primary border border-primary/30 shadow-2xs'
                            : 'bg-muted/50 text-muted-foreground group-hover:bg-muted group-hover:text-foreground group-hover:scale-105'
                        }`}
                      >
                        <Icon className="w-4 h-4" />
                      </div>
                      <span className="truncate">{item.label}</span>
                    </div>

                    {item.badge && (
                      <span
                        className={`text-[9px] font-mono px-1.5 py-0.2 rounded-full font-bold uppercase tracking-wider ${
                          isActive
                            ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/25'
                            : 'bg-muted text-muted-foreground'
                        }`}
                      >
                        {item.badge}
                      </span>
                    )}
                  </>
                )}
              </NavLink>
            );
          })}
        </nav>

        {/* Bottom Section: Action Button + System Health + Settings/Support */}
        <div className="px-3 py-3 mt-auto border-t border-border/50 bg-sidebar/50 space-y-3">
          {/* Action Button */}
          {actionButton && (
            <button
              onClick={actionButton.onClick}
              className="w-full group relative overflow-hidden bg-primary text-primary-foreground font-semibold py-2.5 px-3.5 rounded-xl shadow-sm hover:shadow-md hover:shadow-primary/20 active:scale-98 transition-all duration-200 flex items-center justify-center gap-2 text-xs cursor-pointer border border-primary/20"
            >
              <div className="w-5 h-5 rounded-md bg-primary-foreground/15 flex items-center justify-center transition-transform group-hover:rotate-90 duration-300">
                <Plus className="w-3.5 h-3.5" />
              </div>
              <span className="tracking-tight">{actionButton.label}</span>
            </button>
          )}

          {/* Bottom Nav Items: Settings & Support */}
          {bottomItems.length > 0 && (
            <div className="space-y-1 pt-1 border-t border-border/40">
              {bottomItems.map((item) => {
                const Icon = item.icon;
                const isSettings = item.id === 'settings';
                return (
                  <NavLink
                    key={item.id}
                    to={item.path}
                    className={({ isActive }) =>
                      `group relative flex items-center gap-3 px-3 py-1.5 rounded-xl text-xs font-medium transition-all duration-150 ${
                        isActive
                          ? 'bg-muted text-foreground font-bold shadow-2xs border border-border/60'
                          : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground'
                      }`
                    }
                    onClick={onClose}
                  >
                    <div
                      className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 transition-all duration-200 ${
                        isSettings ? 'group-hover:rotate-45 duration-300' : ''
                      }`}
                    >
                      <Icon className="w-3.5 h-3.5" />
                    </div>
                    <span>{item.label}</span>
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
