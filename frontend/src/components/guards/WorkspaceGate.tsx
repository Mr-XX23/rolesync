import React, { useEffect } from 'react';
import { Loader2, RefreshCw } from 'lucide-react';
import { Button } from '../common/Button';
import { useAppDispatch, useAppSelector } from '../../store';
import { ensureWorkspace } from '../../store/workspaceSlice';

/**
 * Renders workspace-scoped pages (catalog, knowledge vault, sales agent...) only once the
 * signed-in user's active workspace is known, creating their personal workspace on first
 * use. Without this, requests would go out with no workspace.
 */
export const WorkspaceGate: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const dispatch = useAppDispatch();
  const userId = useAppSelector((state) => state.auth.user?.userId ?? null);
  const { workspaceStatus, workspaceLoadedFor, workspaceError } = useAppSelector((state) => state.workspace);
  const stale = workspaceStatus === 'ready' && workspaceLoadedFor !== userId;

  useEffect(() => {
    if (userId && (workspaceStatus === 'idle' || stale)) {
      void dispatch(ensureWorkspace(userId));
    }
  }, [dispatch, userId, workspaceStatus, stale]);

  if (workspaceStatus === 'ready' && !stale) {
    return <>{children}</>;
  }

  if (workspaceStatus === 'failed') {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-3 text-center py-16">
        <p className="text-sm font-semibold text-foreground">We couldn't load your workspace.</p>
        <p className="text-xs text-muted-foreground max-w-sm">{workspaceError}</p>
        <Button
          variant="outline"
          className="px-4 py-2 text-xs w-auto"
          onClick={() => userId && void dispatch(ensureWorkspace(userId))}
          icon={<RefreshCw className="w-3.5 h-3.5" />}
        >
          Try again
        </Button>
      </div>
    );
  }

  return (
    <div className="h-full flex items-center justify-center gap-2 text-sm text-muted-foreground py-16">
      <Loader2 className="w-4 h-4 animate-spin" />
      Loading your workspace…
    </div>
  );
};
