import React, { useState } from 'react';
import { Search, LogOut, Menu, User, Settings, ChevronDown } from 'lucide-react';
import { useAppDispatch, useAppSelector } from '../../store';
import { logoutUser } from '../../store/authSlice';
import { clearActiveRole } from '../../store/roleSlice';
import { setModalOpen } from '../../store/taskSlice';

interface HeaderProps {
  onMenuToggle: () => void;
  searchPlaceholder?: string;
}

export const Header: React.FC<HeaderProps> = ({
  onMenuToggle,
  searchPlaceholder = 'Search synchronization mesh...',
}) => {
  const dispatch = useAppDispatch();
  const { user } = useAppSelector((state) => state.auth);
  const [profileOpen, setProfileOpen] = useState(false);

  const handleLogout = () => {
    dispatch(logoutUser());
    dispatch(clearActiveRole());
  };

  return (
    <header className="flex justify-between items-center px-4 md:px-8 border-b border-border bg-card h-16 shadow-2xs sticky top-0 z-40">
      {/* Mobile Toggle & Search */}
      <div className="flex items-center gap-4 flex-1">
        <button
          onClick={onMenuToggle}
          className="p-1.5 rounded-lg border border-border/80 text-muted-foreground hover:text-foreground md:hidden active:scale-95 transition-all"
        >
          <Menu className="w-5 h-5" />
        </button>

        <div className="relative w-full max-w-xs md:max-w-md hidden sm:block">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/60 w-4 h-4" />
          <input
            className="bg-background border border-border/70 rounded-full pl-9 pr-4 py-3 w-full focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary text-xs font-medium placeholder-muted-foreground/50 transition-all duration-300"
            placeholder={searchPlaceholder}
            type="text"
          />
        </div>
      </div>

      {/* Action Mesh and Operator Section */}
      <div className="flex items-center gap-4">
        {/* Live Vector Mesh Node Status */}
        <div className="hidden lg:flex items-center gap-2 px-3 py-1.5 bg-emerald-500/10 dark:bg-emerald-500/5 rounded-full border border-emerald-500/25">
          <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse"></span>
          <span className="font-mono text-[9px] text-emerald-700 dark:text-emerald-400 font-bold uppercase tracking-wider">
            pgvector Node: ACTIVE
          </span>
        </div>

        {/* Deploy Trigger */}
        <button
          onClick={() => dispatch(setModalOpen(true))}
          className="text-primary font-bold text-xs bg-primary/10 border border-primary/20 px-3.5 py-1.5 rounded-xl hover:bg-primary/20 active:scale-95 transition-all cursor-pointer shadow-2xs"
        >
          Deploy Agent
        </button>

        {/* Separator */}
        <span className="h-6 w-px bg-border/80 hidden sm:block" />

        {/* Profile Control Grid */}
        <div className="relative">
          <button
            onClick={() => setProfileOpen(!profileOpen)}
            className="flex items-center gap-1.5 p-1 rounded-full hover:bg-muted border border-transparent hover:border-border/60 transition-all duration-200"
          >
            <div className="h-7 w-7 rounded-full overflow-hidden bg-primary/20 border border-primary/15 flex items-center justify-center font-bold text-xs text-primary">
              {user?.email ? user.email.slice(0, 2).toUpperCase() : 'OP'}
            </div>
            <ChevronDown className={`w-3.5 h-3.5 text-muted-foreground transition-transform duration-300 ${profileOpen ? 'rotate-180' : ''}`} />
          </button>

          {/* Profile Dropdown Panel */}
          {profileOpen && (
            <>
              <div
                className="fixed inset-0 z-40"
                onClick={() => setProfileOpen(false)}
              />
              <div className="absolute right-0 mt-2.5 w-56 bg-card border border-border rounded-xl shadow-md p-2 z-50 animate-in fade-in slide-in-from-top-2 duration-200">
                <div className="px-3.5 py-2 border-b border-border/60 mb-1.5">
                  <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest leading-none mb-1">
                    operator account
                  </p>
                  <p className="text-xs font-semibold text-foreground font-mono truncate break-all leading-tight">
                    {user?.email || 'operator@rolesync.ai'}
                  </p>
                </div>

                <div className="space-y-0.5">
                  <button
                    onClick={() => {
                      setProfileOpen(false);
                      alert('Redirecting to Account Settings...');
                    }}
                    className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted transition-all duration-150"
                  >
                    <User className="w-4 h-4 text-muted-foreground" />
                    <span>Profile Panel</span>
                  </button>

                  <button
                    onClick={() => {
                      setProfileOpen(false);
                      alert('System Diagnostics running: Vector clusters nominal.');
                    }}
                    className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted transition-all duration-150"
                  >
                    <Settings className="w-4 h-4 text-muted-foreground" />
                    <span>System Settings</span>
                  </button>
                </div>

                <div className="border-t border-border/60 my-1.5 pt-1.5">
                  <button
                    onClick={() => {
                      setProfileOpen(false);
                      handleLogout();
                    }}
                    className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-semibold text-destructive hover:bg-destructive/10 transition-all duration-150"
                  >
                    <LogOut className="w-4 h-4" />
                    <span>Terminate Session</span>
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  );
};
