import React, { useState, useEffect } from 'react';
import {
  Activity,
  CheckCircle2,
  AlertTriangle,
  Clock,
  RefreshCw,
  Paperclip,
  ChevronDown,
  ChevronUp,
  X,
  Loader2,
  Mail,
  ShieldAlert
} from 'lucide-react';
import { Button } from '../../../components/common/Button';
import { connectorApi, type GmailActivity, type GmailActivityItem } from '../../../api/connectorApi';

interface GmailSyncActivityModalProps {
  isOpen: boolean;
  onClose: () => void;
  userId?: string;
}

export const GmailSyncActivityModal: React.FC<GmailSyncActivityModalProps> = ({
  isOpen,
  onClose,
  userId = 'usr_active',
}) => {
  const [activities, setActivities] = useState<GmailActivity[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);

  const fetchActivities = async () => {
    setIsLoading(true);
    try {
      const res = await connectorApi.getGmailActivities(userId, 20);
      setActivities(res.activities || []);
      if (res.activities && res.activities.length > 0 && !expandedJobId) {
        setExpandedJobId(res.activities[0].job_id);
      }
    } catch (err) {
      console.error('Failed to fetch Gmail sync activities:', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchActivities();
    }
  }, [isOpen, userId]);

  if (!isOpen) return null;

  // Aggregate metrics
  const totalProcessed = activities.reduce((acc, act) => acc + (act.metrics?.processed || 0), 0);
  const totalSucceeded = activities.reduce((acc, act) => acc + (act.metrics?.succeeded || 0), 0);
  const totalSkipped = activities.reduce((acc, act) => acc + (act.metrics?.skipped || 0), 0);
  const totalFailed = activities.reduce((acc, act) => acc + (act.metrics?.failed || 0), 0);

  const toggleExpand = (jobId: string) => {
    setExpandedJobId((prev) => (prev === jobId ? null : jobId));
  };

  const formatTriggerLabel = (type: string) => {
    switch (type) {
      case 'INITIAL_SYNC':
        return 'Initial 90-Day Backfill';
      case 'AUTO_SYNC':
        return 'Scheduled Auto-Sync';
      case 'MANUAL_SYNC':
        return 'Manual Sync Now';
      case 'RESYNC':
        return 'Resync Verification';
      case 'WEBHOOK':
        return 'Real-Time Webhook';
      default:
        return type;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-xs transition-opacity duration-300 animate-in fade-in"
        onClick={onClose}
      />

      {/* Modal Card */}
      <div className="relative w-full max-w-3xl bg-card border border-border rounded-2xl shadow-2xl z-10 animate-in zoom-in-95 duration-200 overflow-hidden text-left flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="p-6 border-b border-border flex justify-between items-center bg-muted/20">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary shadow-3xs">
              <Activity className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-serif text-lg font-bold text-foreground">Gmail Synchronization Activity</h3>
              <p className="text-xs text-muted-foreground">
                Audit trail of email sync runs, LlamaParse attachments, and deduplication records.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              onClick={fetchActivities}
              disabled={isLoading}
              className="p-2 aspect-square rounded-xl"
              title="Refresh Activity"
            >
              <RefreshCw className={`w-3.5 h-3.5 text-primary ${isLoading ? 'animate-spin' : ''}`} />
            </Button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg border border-border/60 hover:bg-muted text-muted-foreground hover:text-foreground transition-all"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Aggregate Stats Summary Bar */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 p-4 border-b border-border/60 bg-muted/10">
          <div className="bg-card border border-border p-3 rounded-xl">
            <p className="text-[10px] font-mono uppercase font-bold text-muted-foreground">Total Processed</p>
            <p className="text-base font-bold text-foreground mt-0.5">{totalProcessed}</p>
          </div>
          <div className="bg-card border border-emerald-500/30 dark:border-emerald-500/20 p-3 rounded-xl">
            <p className="text-[10px] font-mono uppercase font-bold text-emerald-600 dark:text-emerald-400">Indexed (Success)</p>
            <p className="text-base font-bold text-emerald-600 dark:text-emerald-400 mt-0.5">{totalSucceeded}</p>
          </div>
          <div className="bg-card border border-amber-500/30 dark:border-amber-500/20 p-3 rounded-xl">
            <p className="text-[10px] font-mono uppercase font-bold text-amber-600 dark:text-amber-400">Skipped (Bypassed)</p>
            <p className="text-base font-bold text-amber-600 dark:text-amber-400 mt-0.5">{totalSkipped}</p>
          </div>
          <div className="bg-card border border-destructive/30 p-3 rounded-xl">
            <p className="text-[10px] font-mono uppercase font-bold text-destructive">Failed</p>
            <p className="text-base font-bold text-destructive mt-0.5">{totalFailed}</p>
          </div>
        </div>

        {/* Activity Feed List */}
        <div className="p-6 space-y-4 overflow-y-auto flex-1">
          {isLoading && activities.length === 0 ? (
            <div className="py-12 text-center space-y-3">
              <Loader2 className="w-8 h-8 animate-spin text-primary mx-auto" />
              <p className="text-xs text-muted-foreground">Loading sync history...</p>
            </div>
          ) : activities.length === 0 ? (
            <div className="py-12 text-center space-y-2 bg-muted/20 border border-border border-dashed rounded-2xl">
              <Mail className="w-8 h-8 text-muted-foreground/60 mx-auto" />
              <p className="text-xs font-semibold text-foreground">No synchronization activity logged yet.</p>
              <p className="text-[11px] text-muted-foreground">Run a sync or wait for scheduled auto-sync to see events.</p>
            </div>
          ) : (
            activities.map((act) => {
              const isExpanded = expandedJobId === act.job_id;
              const isSuccess = act.status === 'COMPLETED';
              const isRunning = act.status === 'RUNNING';

              return (
                <div
                  key={act.activity_id || act.job_id}
                  className="bg-card border border-border rounded-xl overflow-hidden shadow-3xs transition-all"
                >
                  {/* Activity Row Header */}
                  <div
                    onClick={() => toggleExpand(act.job_id)}
                    className="p-4 flex flex-col sm:flex-row justify-between sm:items-center gap-3 cursor-pointer hover:bg-muted/30 transition-colors"
                  >
                    <div className="flex items-center gap-3">
                      <div
                        className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${
                          isRunning
                            ? 'bg-primary/10 text-primary animate-pulse'
                            : isSuccess
                            ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                            : 'bg-destructive/10 text-destructive'
                        }`}
                      >
                        {isRunning ? (
                          <RefreshCw className="w-4 h-4 animate-spin" />
                        ) : isSuccess ? (
                          <CheckCircle2 className="w-4 h-4" />
                        ) : (
                          <AlertTriangle className="w-4 h-4" />
                        )}
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-bold text-foreground">
                            {formatTriggerLabel(act.trigger_type)}
                          </span>
                          <span
                            className={`text-[9px] font-mono font-bold uppercase px-2 py-0.5 rounded-full border ${
                              isSuccess
                                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-700 dark:text-emerald-300'
                                : isRunning
                                ? 'bg-primary/10 border-primary/30 text-primary'
                                : 'bg-destructive/10 border-destructive/30 text-destructive'
                            }`}
                          >
                            {act.status}
                          </span>
                        </div>
                        <div className="flex items-center gap-2 text-[10px] font-mono text-muted-foreground mt-0.5">
                          <Clock className="w-3 h-3" />
                          <span>{new Date(act.started_at).toLocaleString()}</span>
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-4 text-xs font-mono">
                      <div className="flex items-center gap-3">
                        <span className="text-emerald-600 dark:text-emerald-400 font-bold">
                          +{act.metrics?.succeeded || 0} indexed
                        </span>
                        {act.metrics?.skipped > 0 && (
                          <span className="text-amber-600 dark:text-amber-400 font-semibold">
                            {act.metrics.skipped} skipped
                          </span>
                        )}
                        {act.metrics?.failed > 0 && (
                          <span className="text-destructive font-bold">
                            {act.metrics.failed} failed
                          </span>
                        )}
                      </div>
                      <button className="p-1 rounded text-muted-foreground hover:text-foreground">
                        {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                      </button>
                    </div>
                  </div>

                  {/* Expanded Item Level Details */}
                  {isExpanded && (
                    <div className="p-4 border-t border-border/60 bg-muted/20 space-y-2">
                      <p className="text-[10px] font-mono font-bold uppercase text-muted-foreground tracking-wider mb-2">
                        Emails Processed in this batch ({act.items?.length || 0})
                      </p>
                      {act.items && act.items.length > 0 ? (
                        act.items.map((item: GmailActivityItem, idx: number) => (
                          <div
                            key={idx}
                            className="bg-card border border-border/80 rounded-lg p-3 flex flex-col sm:flex-row justify-between sm:items-center gap-2 text-xs"
                          >
                            <div className="space-y-0.5">
                              <p className="font-semibold text-foreground flex items-center gap-1.5">
                                <Mail className="w-3.5 h-3.5 text-primary shrink-0" />
                                <span>{item.subject}</span>
                              </p>
                              <p className="text-[10px] text-muted-foreground font-mono">
                                From: {item.sender}
                              </p>
                              {item.attachment_summary && (
                                <p className="text-[10px] text-muted-foreground flex items-center gap-1">
                                  <Paperclip className="w-3 h-3 text-primary/70 shrink-0" />
                                  <span>{item.attachment_summary}</span>
                                </p>
                              )}
                              {item.error_message && (
                                <p className="text-[10px] text-destructive flex items-center gap-1">
                                  <ShieldAlert className="w-3 h-3 shrink-0" />
                                  <span>{item.error_message}</span>
                                </p>
                              )}
                            </div>

                            <span
                              className={`text-[9px] font-mono font-bold uppercase px-2 py-0.5 rounded border shrink-0 ${
                                item.status === 'SUCCESS'
                                  ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-700 dark:text-emerald-300'
                                  : item.status === 'SKIPPED'
                                  ? 'bg-amber-500/10 border-amber-500/30 text-amber-700 dark:text-amber-300'
                                  : 'bg-destructive/10 border-destructive/30 text-destructive'
                              }`}
                            >
                              {item.status}
                            </span>
                          </div>
                        ))
                      ) : (
                        <p className="text-xs text-muted-foreground italic">No email items recorded.</p>
                      )}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-border bg-muted/10 flex justify-end">
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </div>
  );
};

export default GmailSyncActivityModal;
