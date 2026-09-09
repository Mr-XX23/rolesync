import React, { useState, useEffect, useRef } from 'react';
import {
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
  ShieldAlert,
  FolderOpen,
  Calendar as CalendarIcon,
  MessageSquare,
  FileText,
  FileSpreadsheet,
  Image as ImageIcon,
  FileCode,
  File,
  Trash2,
  Database,
  BrainCircuit,
  AlertOctagon,
  RotateCcw,
} from 'lucide-react';

import { Button } from '../../../components/common/Button';
import { connectorApi, type GmailActivity, type GmailActivityItem } from '../../../api/connectorApi';

interface ConnectorActivityModalProps {
  isOpen: boolean;
  onClose: () => void;
  userId?: string;
  source?: string;
  sourceName?: string;
  logoUrl?: string;
  onDataPurged?: () => void;
}

export const ConnectorActivityModal: React.FC<ConnectorActivityModalProps> = ({
  isOpen,
  onClose,
  userId = 'usr_active',
  source = 'gmail',
  sourceName = 'Gmail',
  logoUrl,
  onDataPurged,
}) => {
  const [activities, setActivities] = useState<GmailActivity[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);

  // Guard against race conditions and stale in-flight fetches
  const activeFetchIdRef = useRef<number>(0);

  // Purge Confirmation & Progress State
  const [showPurgeConfirm, setShowPurgeConfirm] = useState<boolean>(false);
  const [isPurging, setIsPurging] = useState<boolean>(false);
  const [dataSummary, setDataSummary] = useState<any>(null);
  const [isLoadingSummary, setIsLoadingSummary] = useState<boolean>(false);
  const [notification, setNotification] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [isRetryingFailed, setIsRetryingFailed] = useState<boolean>(false);

  const handleRetryFailedItems = async () => {
    setIsRetryingFailed(true);
    try {
      const res = await connectorApi.retryFailedItems(source, userId);
      const count = res?.retried_count ?? 0;
      setNotification({
        type: 'success',
        message: count > 0 
          ? `Successfully queued ${count} failed item(s) for immediate retry.`
          : (res?.message || 'Queued failed items for retry.')
      });
      await fetchActivities();
    } catch (err: any) {
      console.error(`Failed to retry failed items for ${source}:`, err);
      setNotification({
        type: 'error',
        message: err?.response?.data?.detail || err?.message || 'Failed to retry failed items. Please try again.'
      });
    } finally {
      setIsRetryingFailed(false);
    }
  };

  const fetchActivities = async () => {
    const fetchId = ++activeFetchIdRef.current;
    setIsLoading(true);
    try {
      const [actRes, sumRes] = await Promise.allSettled([
        connectorApi.getSourceActivities(source, userId, 20),
        connectorApi.getSourceDataSummary(source, userId),
      ]);

      // If source switched or a newer fetch started, discard response
      if (fetchId !== activeFetchIdRef.current) return;

      if (actRes.status === 'fulfilled') {
        const actList = actRes.value.activities || [];
        setActivities(actList);
        if (actList.length > 0 && !expandedJobId) {
          setExpandedJobId(actList[0].job_id);
        }
      } else {
        setActivities([]);
      }

      if (sumRes.status === 'fulfilled') {
        setDataSummary(sumRes.value.summary || null);
      }
    } catch (err) {
      if (fetchId === activeFetchIdRef.current) {
        console.error(`Failed to fetch ${sourceName} sync activities:`, err);
      }
    } finally {
      if (fetchId === activeFetchIdRef.current) {
        setIsLoading(false);
      }
    }
  };

  const openPurgeConfirmation = async () => {
    setShowPurgeConfirm(true);
    setIsLoadingSummary(true);
    try {
      const res = await connectorApi.getSourceDataSummary(source, userId);
      setDataSummary(res.summary || null);
    } catch (err) {
      console.error("Failed to fetch data summary for purge preview:", err);
    } finally {
      setIsLoadingSummary(false);
    }
  };

  const handleExecutePurge = async () => {
    setIsPurging(true);
    try {
      const res = await connectorApi.purgeSourceData(source, userId);
      setActivities([]);
      setDataSummary({
        synced_messages_count: 0,
        vector_records_count: 0,
        activities_count: 0,
      });
      setNotification({
        type: 'success',
        message: res.message || 'All raw data, vector embeddings, and activity logs have been successfully deleted.'
      });
      setShowPurgeConfirm(false);
      onDataPurged?.();
    } catch (err: any) {
      console.error("Failed to purge connector data:", err);
      setNotification({
        type: 'error',
        message: err?.response?.data?.detail || 'Failed to delete connector data. Please try again.'
      });
    } finally {
      setIsPurging(false);
    }
  };

  // Auto-dismiss notification banner after 5 seconds
  useEffect(() => {
    if (notification) {
      const timer = setTimeout(() => {
        setNotification(null);
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [notification]);

  // Keyboard accessibility: Escape key to close
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  useEffect(() => {
    if (isOpen) {
      setNotification(null);
      setActivities([]);
      setDataSummary(null);
      fetchActivities();

      const pollInterval = setInterval(() => {
        connectorApi
          .getSourceActivities(source, userId, 20)
          .then((res) => {
            if (res?.activities) {
              setActivities(res.activities);
            }
          })
          .catch(() => {});

        connectorApi
          .getSourceDataSummary(source, userId)
          .then((res) => {
            if (res?.summary) {
              setDataSummary(res.summary);
            }
          })
          .catch(() => {});
      }, 3500);

      return () => {
        clearInterval(pollInterval);
        activeFetchIdRef.current++;
      };
    }
  }, [isOpen, userId, source]);

  if (!isOpen) return null;

  // Aggregate metrics (Harmonize with all-time cumulative database totals for 100% card consistency)
  const dbSyncedCount = dataSummary?.synced_messages_count ?? 0;
  const recentProcessed = activities.reduce((acc, act) => acc + (act.metrics?.processed || 0), 0);
  const recentSucceeded = activities.reduce((acc, act) => acc + (act.metrics?.succeeded || 0), 0);
  const recentSkipped = activities.reduce((acc, act) => acc + (act.metrics?.skipped || 0), 0);
  const recentFailed = activities.reduce((acc, act) => acc + (act.metrics?.failed || 0), 0);

  const totalProcessed = Math.max(dbSyncedCount, recentProcessed);
  const totalSucceeded = Math.max(dbSyncedCount, recentSucceeded);
  const totalSkipped = recentSkipped;
  const totalFailed = recentFailed;

  const hasData =
    activities.length > 0 ||
    totalProcessed > 0 ||
    (dataSummary &&
      ((dataSummary.synced_messages_count || 0) > 0 ||
        (dataSummary.vector_records_count || 0) > 0 ||
        (dataSummary.activities_count || 0) > 0));

  const toggleExpand = (jobId: string) => {
    setExpandedJobId((prev) => (prev === jobId ? null : jobId));
  };

  const getSourceIcon = () => {
    switch (source.toLowerCase()) {
      case 'gdrive':
      case 'googledrive':
        return <FolderOpen className="w-5 h-5 text-emerald-500" />;
      case 'calendar':
      case 'googlecalendar':
        return <CalendarIcon className="w-5 h-5 text-blue-500" />;
      case 'slack':
        return <MessageSquare className="w-5 h-5 text-purple-500" />;
      case 'notion':
        return <FileText className="w-5 h-5 text-neutral-400" />;
      default:
        return <Mail className="w-5 h-5 text-primary" />;
    }
  };

  const getItemIcon = () => {
    switch (source.toLowerCase()) {
      case 'gdrive':
      case 'googledrive':
        return <FolderOpen className="w-3.5 h-3.5 text-emerald-500 shrink-0" />;
      case 'calendar':
      case 'googlecalendar':
        return <CalendarIcon className="w-3.5 h-3.5 text-blue-500 shrink-0" />;
      case 'slack':
        return <MessageSquare className="w-3.5 h-3.5 text-purple-500 shrink-0" />;
      case 'notion':
        return <FileText className="w-3.5 h-3.5 text-neutral-400 shrink-0" />;
      default:
        return <Mail className="w-3.5 h-3.5 text-primary shrink-0" />;
    }
  };

  const isGDrive = source.toLowerCase() === 'gdrive' || source.toLowerCase() === 'googledrive';

  const formatMimeType = (mime?: string, name?: string) => {
    if (!mime) return 'Document';
    const m = mime.toLowerCase();
    const n = (name || '').toLowerCase();
    if (m.includes('spreadsheet') || m.includes('sheet') || n.endsWith('.xlsx') || n.endsWith('.csv')) return 'Google Spreadsheet';
    if (m.includes('presentation') || m.includes('powerpoint') || n.endsWith('.pptx')) return 'Google Slides';
    if (m.includes('document') || m.includes('word') || n.endsWith('.docx') || n.endsWith('.doc')) return 'Google Doc';
    if (m.includes('pdf') || n.endsWith('.pdf')) return 'PDF Document';
    if (m.startsWith('image/') || n.match(/\.(png|jpg|jpeg|webp|gif|svg)$/)) return 'Image File';
    if (m.includes('csv') || n.endsWith('.csv')) return 'CSV Data';
    if (m.includes('json') || n.endsWith('.json')) return 'JSON File';
    if (m.includes('video/') || n.match(/\.(mp4|mov|avi|mkv)$/)) return 'Video Media';
    if (m.includes('audio/') || n.match(/\.(mp3|wav|m4a)$/)) return 'Audio Recording';
    if (m.startsWith('text/') || n.endsWith('.txt')) return 'Text Document';
    return mime.split('/').pop()?.toUpperCase() || 'Document';
  };

  const formatBytes = (bytes?: number) => {
    if (!bytes || bytes <= 0) return null;
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  };

  const getFileIcon = (mime?: string, name?: string) => {
    const m = (mime || '').toLowerCase();
    const n = (name || '').toLowerCase();
    if (m.includes('spreadsheet') || m.includes('sheet') || n.endsWith('.xlsx') || n.endsWith('.csv')) {
      return <FileSpreadsheet className="w-3.5 h-3.5 text-emerald-500 shrink-0" />;
    }
    if (m.includes('document') || m.includes('word') || n.endsWith('.docx') || n.endsWith('.doc')) {
      return <FileText className="w-3.5 h-3.5 text-blue-500 shrink-0" />;
    }
    if (m.includes('presentation') || m.includes('powerpoint') || n.endsWith('.pptx')) {
      return <FileText className="w-3.5 h-3.5 text-amber-500 shrink-0" />;
    }
    if (m.includes('pdf') || n.endsWith('.pdf')) {
      return <FileText className="w-3.5 h-3.5 text-rose-500 shrink-0" />;
    }
    if (m.startsWith('image/') || n.match(/\.(png|jpg|jpeg|webp|gif|svg)$/)) {
      return <ImageIcon className="w-3.5 h-3.5 text-purple-500 shrink-0" />;
    }
    if (m.includes('json') || m.includes('code') || n.match(/\.(json|py|js|ts|html)$/)) {
      return <FileCode className="w-3.5 h-3.5 text-amber-500 shrink-0" />;
    }
    return <File className="w-3.5 h-3.5 text-muted-foreground shrink-0" />;
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
        return type || 'Live Sync';
    }
  };

  const getSourceDescription = () => {
    switch (source.toLowerCase()) {
      case 'gdrive':
      case 'googledrive':
        return 'Audit trail of Google Drive file ingestions, document chunking, and vector index records.';
      case 'calendar':
      case 'googlecalendar':
        return 'Audit trail of calendar event syncs, attendee lists, agendas, and meeting summaries.';
      case 'slack':
        return 'Audit trail of Slack channel message syncs, transcripts, and support conversational threads.';
      case 'notion':
        return 'Audit trail of Notion page trees, markdown blocks, and workspace knowledge vectors.';
      default:
        return 'Audit trail of email sync runs, LlamaParse attachments, and deduplication records.';
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
      <div className="relative w-full max-w-4xl bg-card border border-border rounded-2xl shadow-2xl z-10 animate-in zoom-in-95 duration-200 overflow-hidden text-left flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="p-6 border-b border-border flex justify-between items-center bg-muted/20">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center shadow-3xs p-2">
              {logoUrl ? (
                <img src={logoUrl} alt={sourceName} className="w-6 h-6 object-contain" />
              ) : (
                getSourceIcon()
              )}
            </div>
            <div>
              <h3 className="font-serif text-lg font-bold text-foreground">{sourceName} Synchronization Activity</h3>
              <p className="text-xs text-muted-foreground">
                {getSourceDescription()}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {totalFailed > 0 && (
              <Button
                variant="outline"
                onClick={handleRetryFailedItems}
                disabled={isRetryingFailed || isPurging}
                className="text-xs py-1.5 px-3 border-destructive/40 bg-destructive/10 text-destructive hover:bg-destructive hover:text-destructive-foreground transition-all flex items-center gap-1.5"
                title={`Retry ${totalFailed} Failed Item(s)`}
              >
                <RotateCcw className={`w-3.5 h-3.5 ${isRetryingFailed ? 'animate-spin' : ''}`} />
                <span>Retry Failed ({totalFailed})</span>
              </Button>
            )}
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
          {isLoading ? (
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
                    role="button"
                    tabIndex={0}
                    aria-expanded={isExpanded}
                    onClick={() => toggleExpand(act.job_id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        toggleExpand(act.job_id);
                      }
                    }}
                    className="p-4 flex flex-col sm:flex-row justify-between sm:items-center gap-3 cursor-pointer hover:bg-muted/30 transition-colors focus:outline-none focus:ring-1 focus:ring-primary/40 rounded-t-xl"
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
                        Items Processed in this batch ({act.items?.length || 0})
                      </p>
                      {act.items && act.items.length > 0 ? (
                        act.items.map((item: GmailActivityItem, idx: number) => {
                          const itemName = item.filename || item.name || item.subject || 'Untitled Document';
                          const isDriveItem = isGDrive || Boolean(item.filename || item.mime_type || item.file_size !== undefined);

                          return (
                            <div
                              key={idx}
                              className="bg-card border border-border/80 rounded-lg p-3 flex flex-col sm:flex-row justify-between sm:items-center gap-2 text-xs"
                            >
                              <div className="space-y-1 min-w-0 flex-1">
                                <p className="font-semibold text-foreground flex items-center gap-1.5 truncate">
                                  {isDriveItem ? getFileIcon(item.mime_type, itemName) : getItemIcon()}
                                  <span className="truncate">{itemName}</span>
                                </p>

                                {isDriveItem ? (
                                  <div className="flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground font-mono">
                                    <span className="px-1.5 py-0.5 rounded bg-muted/80 border border-border text-foreground/80 font-medium">
                                      {formatMimeType(item.mime_type, itemName)}
                                    </span>
                                    {formatBytes(item.file_size) && (
                                      <span>• {formatBytes(item.file_size)}</span>
                                    )}
                                    {item.file_id && (
                                      <span className="text-muted-foreground/60 truncate max-w-[150px]" title={item.file_id}>
                                        • ID: {item.file_id.length > 16 ? `${item.file_id.slice(0, 7)}...${item.file_id.slice(-5)}` : item.file_id}
                                      </span>
                                    )}
                                    {item.synced_at && (
                                      <span>• {new Date(item.synced_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                                    )}
                                  </div>
                                ) : (
                                  <>
                                    <div className="flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground font-mono">
                                      {item.channel_name && (
                                        <span className="px-1.5 py-0.5 rounded bg-purple-500/10 border border-purple-500/30 text-purple-700 dark:text-purple-300 font-medium">
                                          #{item.channel_name}
                                        </span>
                                      )}
                                      {item.entity_type && (
                                        <span className="px-1.5 py-0.5 rounded bg-muted border border-border text-foreground/80 font-medium uppercase">
                                          {item.entity_type}
                                        </span>
                                      )}
                                      {item.sender && (
                                        <span>From / Origin: {item.sender}</span>
                                      )}
                                      {item.synced_at && (
                                        <span>• {new Date(item.synced_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                                      )}
                                    </div>
                                    {item.attachment_summary && (
                                      <p className="text-[10px] text-muted-foreground flex items-center gap-1">
                                        <Paperclip className="w-3 h-3 text-primary/70 shrink-0" />
                                        <span>{item.attachment_summary}</span>
                                      </p>
                                    )}
                                  </>
                                )}

                                {item.error_message && (
                                  <p className="text-[10px] text-destructive flex items-center gap-1 mt-0.5">
                                    <ShieldAlert className="w-3 h-3 shrink-0" />
                                    <span>{item.error_message}</span>
                                  </p>
                                )}
                              </div>

                              <span
                                className={`text-[9px] font-mono font-bold uppercase px-2 py-0.5 rounded border shrink-0 self-start sm:self-center ${
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
                          );
                        })

                      ) : (
                        <p className="text-xs text-muted-foreground italic">No items recorded in this batch.</p>
                      )}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>

        {/* Notification Toast / Banner */}
        {notification && (
          <div
            className={`mx-6 mt-4 p-3 rounded-xl border flex items-center justify-between text-xs animate-in slide-in-from-top-2 ${
              notification.type === 'success'
                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-700 dark:text-emerald-300'
                : 'bg-destructive/10 border-destructive/30 text-destructive'
            }`}
          >
            <div className="flex items-center gap-2">
              {notification.type === 'success' ? (
                <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
              ) : (
                <AlertOctagon className="w-4 h-4 shrink-0 text-destructive" />
              )}
              <span>{notification.message}</span>
            </div>
            <button
              onClick={() => setNotification(null)}
              className="p-1 hover:opacity-75 rounded transition-opacity"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Footer */}
        <div className="p-4 border-t border-border bg-muted/10 flex items-center justify-between">
          <button
            type="button"
            onClick={openPurgeConfirmation}
            disabled={isPurging || isLoading || !hasData}
            className="px-3.5 py-2 rounded-xl text-xs font-semibold border border-destructive/30 bg-destructive/10 text-destructive hover:bg-destructive hover:text-destructive-foreground transition-all flex items-center gap-2 shadow-3xs disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-destructive/10 disabled:hover:text-destructive cursor-pointer"
            title={
              !hasData
                ? "No data available to delete"
                : "Permanently delete all raw records, vector memories, and activity logs across MongoDB & PostgreSQL"
            }
          >
            <Trash2 className="w-3.5 h-3.5 shrink-0" />
            <span>Delete All Data</span>
          </button>

          <div className="flex items-center gap-2">
            {totalFailed > 0 && (
              <Button
                variant="outline"
                onClick={handleRetryFailedItems}
                disabled={isRetryingFailed || isPurging}
                className="text-xs border-destructive/40 bg-destructive/10 text-destructive hover:bg-destructive hover:text-destructive-foreground transition-all flex items-center gap-1.5"
              >
                <RotateCcw className={`w-3.5 h-3.5 ${isRetryingFailed ? 'animate-spin' : ''}`} />
                <span>Retry {totalFailed} Failed Items</span>
              </Button>
            )}
            <Button variant="outline" onClick={onClose} disabled={isPurging}>
              Close
            </Button>
          </div>
        </div>

        {/* Deletion Blocking Overlay */}
        {isPurging && (
          <div className="absolute inset-0 bg-card/90 backdrop-blur-xs z-50 flex flex-col items-center justify-center p-6 text-center animate-in fade-in duration-200">
            <div className="w-14 h-14 rounded-2xl bg-destructive/10 border border-destructive/20 flex items-center justify-center shadow-lg mb-4">
              <Loader2 className="w-7 h-7 animate-spin text-destructive" />
            </div>
            <h4 className="text-base font-bold text-foreground">Purging All Data Across Databases...</h4>
            <p className="text-xs text-muted-foreground mt-1 max-w-md">
              Deleting raw messages, vector embeddings, deduplication state, and activity logs from MongoDB and PostgreSQL. All actions are blocked until completion.
            </p>
          </div>
        )}

        {/* Pre-Deletion Calculation & Confirmation Modal */}
        {showPurgeConfirm && (
          <div className="fixed inset-0 z-60 flex items-center justify-center p-4">
            {/* Inner Backdrop */}
            <div
              className="absolute inset-0 bg-black/60 backdrop-blur-xs animate-in fade-in duration-200"
              onClick={() => !isPurging && setShowPurgeConfirm(false)}
            />

            {/* Inner Confirmation Card */}
            <div className="relative w-full max-w-lg bg-card border border-destructive/30 rounded-2xl shadow-2xl z-10 animate-in zoom-in-95 duration-200 overflow-hidden text-left p-6 space-y-4">
              {/* Confirm Header */}
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 rounded-xl bg-destructive/10 border border-destructive/30 flex items-center justify-center shrink-0 text-destructive">
                  <Trash2 className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-foreground">Delete All {sourceName} Data</h3>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Review the calculation below before proceeding. This will wipe all ingested raw data and vector memory for this connector.
                  </p>
                </div>
              </div>

              {/* Data Calculation Breakdown Cards */}
              <div className="grid grid-cols-2 gap-2.5 p-3 rounded-xl bg-muted/20 border border-border/80 text-xs">
                <div className="bg-card border border-border p-2.5 rounded-lg">
                  <div className="flex items-center gap-1.5 text-muted-foreground">
                    <Database className="w-3.5 h-3.5 text-primary" />
                    <span className="text-[10px] font-mono uppercase font-bold">Raw Records (MongoDB)</span>
                  </div>
                  <p className="text-sm font-bold text-foreground mt-1">
                    {isLoadingSummary ? (
                      <Loader2 className="w-3 h-3 animate-spin inline text-primary" />
                    ) : (
                      dataSummary?.synced_messages_count ?? totalProcessed
                    )}{' '}
                    <span className="text-[10px] font-normal text-muted-foreground">items</span>
                  </p>
                </div>

                <div className="bg-card border border-border p-2.5 rounded-lg">
                  <div className="flex items-center gap-1.5 text-muted-foreground">
                    <BrainCircuit className="w-3.5 h-3.5 text-purple-500" />
                    <span className="text-[10px] font-mono uppercase font-bold">Vector Memories</span>
                  </div>
                  <p className="text-sm font-bold text-foreground mt-1">
                    {isLoadingSummary ? (
                      <Loader2 className="w-3 h-3 animate-spin inline text-purple-500" />
                    ) : (
                      dataSummary?.vector_records_count ?? totalSucceeded
                    )}{' '}
                    <span className="text-[10px] font-normal text-muted-foreground">embeddings</span>
                  </p>
                </div>

                <div className="bg-card border border-border p-2.5 rounded-lg">
                  <div className="flex items-center gap-1.5 text-muted-foreground">
                    <Clock className="w-3.5 h-3.5 text-amber-500" />
                    <span className="text-[10px] font-mono uppercase font-bold">Activity Runs</span>
                  </div>
                  <p className="text-sm font-bold text-foreground mt-1">
                    {isLoadingSummary ? (
                      <Loader2 className="w-3 h-3 animate-spin inline text-amber-500" />
                    ) : (
                      dataSummary?.activities_count ?? activities.length
                    )}{' '}
                    <span className="text-[10px] font-normal text-muted-foreground">logs</span>
                  </p>
                </div>

                <div className="bg-card border border-border p-2.5 rounded-lg">
                  <div className="flex items-center gap-1.5 text-muted-foreground">
                    <RefreshCw className="w-3.5 h-3.5 text-emerald-500" />
                    <span className="text-[10px] font-mono uppercase font-bold">Sync State</span>
                  </div>
                  <p className="text-sm font-bold text-emerald-600 dark:text-emerald-400 mt-1">
                    Reset to 0
                  </p>
                </div>
              </div>

              {/* Warning Callout Banner */}
              <div className="p-3 rounded-xl bg-destructive/10 border border-destructive/20 flex items-start gap-2.5 text-xs text-destructive">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                <div>
                  <p className="font-bold">Permanent & Irreversible Action</p>
                  <p className="text-[11px] opacity-90 mt-0.5">
                    This will permanently delete all raw records, vector memories, and sync history across PostgreSQL and MongoDB. This action cannot be undone.
                  </p>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex items-center justify-end gap-2.5 pt-2">
                <Button
                  variant="outline"
                  onClick={() => setShowPurgeConfirm(false)}
                  disabled={isPurging}
                >
                  Cancel
                </Button>
                <button
                  type="button"
                  onClick={handleExecutePurge}
                  disabled={isPurging}
                  className="px-4 py-2 rounded-xl text-xs font-bold bg-destructive text-destructive-foreground hover:bg-destructive/90 transition-all flex items-center gap-1.5 cursor-pointer shadow-md disabled:opacity-50"
                >
                  {isPurging ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      <span>Deleting...</span>
                    </>
                  ) : (
                    <>
                      <Trash2 className="w-3.5 h-3.5" />
                      <span>Delete Now</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export const GmailSyncActivityModal = ConnectorActivityModal;
export default ConnectorActivityModal;
