import React, { useState } from 'react';
import { Clock, CheckCircle2, AlertCircle, X, ShieldAlert, Sparkles, Timer, Zap, Power } from 'lucide-react';
import { Button } from '../../../components/common/Button';
import { useToast } from '../../../context/ToastContext';

export interface AutoSyncOption {
  id: string; // 'off', '2m', '30m', '1h', '6h', '24h'
  title: string;
  subtitle: string;
  intervalMinutes: number;
  badge: string;
  nextRunDesc: string;
  recommended?: boolean;
}

export const AUTO_SYNC_SCHEDULES: AutoSyncOption[] = [
  {
    id: 'off',
    title: 'Off (Manual Only)',
    subtitle: 'Disable automated polling. Data will only sync when you manually click "Sync Now".',
    intervalMinutes: 0,
    badge: 'Disabled · Default',
    nextRunDesc: 'No automated sync scheduled',
  },
  {
    id: '2m',
    title: 'Every 2 Minutes',
    subtitle: 'Rapid polling for active development, real-time testing, and continuous ingestion.',
    intervalMinutes: 2,
    badge: 'High Frequency',
    nextRunDesc: 'Next sync in ~2 minutes',
  },
  {
    id: '30m',
    title: 'Every 30 Minutes',
    subtitle: 'Standard balanced synchronization interval for regular incoming updates.',
    intervalMinutes: 30,
    badge: 'Balanced',
    nextRunDesc: 'Next sync in ~30 minutes',
    recommended: true,
  },
  {
    id: '1h',
    title: 'Every 1 Hour',
    subtitle: 'Hourly scrape capturing steady updates without high API rate pressure.',
    intervalMinutes: 60,
    badge: 'Hourly Scrape',
    nextRunDesc: 'Next sync at top of next hour',
  },
  {
    id: '6h',
    title: 'Every 6 Hours',
    subtitle: 'Periodic quad-daily sweep across business hours for regular batch processing.',
    intervalMinutes: 360,
    badge: 'Quad-Daily',
    nextRunDesc: 'Next sync in ~6 hours',
  },
  {
    id: '24h',
    title: 'Every 24 Hours (02:00 AM)',
    subtitle: 'Daily overnight cron sequence executed every morning at 02:00 AM.',
    intervalMinutes: 1440,
    badge: 'Daily Cron · 02:00 AM',
    nextRunDesc: 'Next sync tonight at 02:00 AM',
  },
];

export interface AutoSyncModalProps {
  isOpen: boolean;
  onClose: () => void;
  connectorId: string;
  connectorName: string;
  logoUrl?: string;
  currentFrequency?: string; // 'off', '2m', '30m', '1h', '6h', '24h', etc.
  initialAutoSyncEnabled?: boolean;
  initialWebhookEnabled?: boolean;
  isLocked?: boolean;
  isConnected?: boolean;
  onSaveSchedule: (
    frequency: string,
    intervalMinutes: number,
    autoSyncEnabled: boolean,
    webhookEnabled: boolean
  ) => Promise<void>;
}

export const AutoSyncModal: React.FC<AutoSyncModalProps> = ({
  isOpen,
  onClose,
  connectorId: _connectorId,
  connectorName,
  logoUrl,
  currentFrequency = 'off',
  initialAutoSyncEnabled,
  initialWebhookEnabled,
  isLocked = false,
  isConnected = true,
  onSaveSchedule,
}) => {
  const toast = useToast();

  // Normalize initial selection (defaults to 'off')
  const normalizedInitial = (() => {
    const raw = (currentFrequency || 'off').toLowerCase().replace(' auto', '').trim();
    if (['off', 'manual', 'disabled'].includes(raw)) return 'off';
    if (['2m', '30m', '1h', '6h', '24h'].includes(raw)) return raw;
    if (raw.includes('24h') || raw.includes('2 am') || raw.includes('daily')) return '24h';
    if (raw.includes('6h')) return '6h';
    if (raw.includes('1h') || raw.includes('hourly')) return '1h';
    if (raw.includes('2m')) return '2m';
    if (raw.includes('30m')) return '30m';
    return 'off';
  })();

  const [autoSyncEnabled, setAutoSyncEnabled] = useState<boolean>(() => {
    if (typeof initialAutoSyncEnabled === 'boolean') return initialAutoSyncEnabled;
    return normalizedInitial !== 'off';
  });

  const [selectedFreq, setSelectedFreq] = useState<string>(normalizedInitial);

  const [webhookEnabled, setWebhookEnabled] = useState<boolean>(() => {
    if (typeof initialWebhookEnabled === 'boolean') return initialWebhookEnabled;
    return false;
  });

  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  if (!isOpen) return null;

  const effectiveFreq = autoSyncEnabled ? (selectedFreq === 'off' ? '30m' : selectedFreq) : 'off';
  const currentOption = AUTO_SYNC_SCHEDULES.find((s) => s.id === effectiveFreq) || AUTO_SYNC_SCHEDULES[0];

  const handleToggleAutoSync = () => {
    if (autoSyncEnabled) {
      setAutoSyncEnabled(false);
      setSelectedFreq('off');
    } else {
      setAutoSyncEnabled(true);
      if (selectedFreq === 'off') {
        setSelectedFreq('30m');
      }
    }
  };

  const handleSelectSchedule = (optId: string) => {
    if (optId === 'off') {
      setAutoSyncEnabled(false);
      setSelectedFreq('off');
    } else {
      setAutoSyncEnabled(true);
      setSelectedFreq(optId);
    }
  };

  const handleApply = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isConnected) {
      const msg = `Please connect and authenticate ${connectorName} before configuring its sync schedule.`;
      setErrorMsg(msg);
      toast.warning(msg, 'Connection Required');
      return;
    }

    setIsSubmitting(true);
    setErrorMsg(null);
    try {
      const finalFreq = autoSyncEnabled ? (selectedFreq === 'off' ? '30m' : selectedFreq) : 'off';
      const finalOption = AUTO_SYNC_SCHEDULES.find((s) => s.id === finalFreq) || AUTO_SYNC_SCHEDULES[0];

      await onSaveSchedule(finalFreq, finalOption.intervalMinutes, autoSyncEnabled, webhookEnabled);
      toast.success(
        `Sync settings updated: Auto-Sync is ${autoSyncEnabled ? `ON (${finalOption.title})` : 'OFF'}, Webhooks Trigger is ${
          webhookEnabled ? 'ON' : 'OFF'
        } for ${connectorName}.`,
        'Settings Saved'
      );
      onClose();
    } catch (err: any) {
      const detail =
        err?.response?.data?.detail ||
        err?.response?.data?.message ||
        err?.message ||
        'Failed to update sync settings. Please check server connectivity.';
      setErrorMsg(detail);
      toast.error(detail, 'Save Failed');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-xs transition-opacity duration-300 animate-in fade-in"
        onClick={onClose}
      />

      {/* Modal Card */}
      <div className="relative w-full max-w-2xl bg-card border border-border rounded-2xl shadow-2xl z-10 animate-in zoom-in-95 duration-200 overflow-hidden text-left flex flex-col max-h-[92vh]">
        {/* Header */}
        <div className="p-6 border-b border-border/80 flex justify-between items-start bg-muted/20">
          <div className="flex items-center gap-3.5">
            <div className="w-12 h-12 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center shadow-3xs p-2.5">
              {logoUrl ? (
                <img src={logoUrl} alt={connectorName} className="w-full h-full object-contain" />
              ) : (
                <Clock className="w-6 h-6 text-primary" />
              )}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-serif text-xl font-bold text-foreground">Sync & Trigger Settings</h3>
                <span className="text-[10px] font-mono font-bold uppercase tracking-wider px-2 py-0.5 rounded-md bg-primary/10 text-primary border border-primary/20">
                  Cadence
                </span>
              </div>
              <p className="text-xs text-muted-foreground mt-0.5">
                Configure background polling schedule and real-time webhook push ingestion for {connectorName}.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg border border-border/60 hover:bg-muted text-muted-foreground hover:text-foreground transition-all cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Lock Warning Banner */}
        {isLocked && (
          <div className="bg-amber-500/10 border-b border-amber-500/20 px-6 py-2.5 flex items-center gap-2 text-xs font-semibold text-amber-600 dark:text-amber-400">
            <ShieldAlert className="w-4 h-4 shrink-0" />
            <span>Active sync running: Updated settings will take effect on the next scheduled cycle.</span>
          </div>
        )}

        {/* Form Body */}
        <form onSubmit={handleApply} className="p-6 space-y-6 overflow-y-auto flex-1">
          {errorMsg && (
            <div className="p-3.5 bg-destructive/10 border border-destructive/20 rounded-xl text-xs text-destructive flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{errorMsg}</span>
            </div>
          )}

          {/* OPTION 1: SCHEDULED AUTO-SYNC */}
          <div className="p-4 rounded-xl border border-border/80 bg-muted/20 space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className={`p-2 rounded-lg ${autoSyncEnabled ? 'bg-primary/15 text-primary' : 'bg-muted text-muted-foreground'}`}>
                  <Power className="w-4 h-4" />
                </div>
                <div>
                  <h4 className="text-xs font-bold text-foreground flex items-center gap-2">
                    Automated Background Sync
                    <span className={`text-[9px] font-mono px-1.5 py-0.5 rounded ${autoSyncEnabled ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 font-bold' : 'bg-muted text-muted-foreground'}`}>
                      {autoSyncEnabled ? 'ON' : 'OFF (Default)'}
                    </span>
                  </h4>
                  <p className="text-[11px] text-muted-foreground">
                    Periodically poll external accounts for new data according to an automated schedule.
                  </p>
                </div>
              </div>

              {/* Toggle Switch */}
              <button
                type="button"
                onClick={handleToggleAutoSync}
                disabled={isSubmitting}
                className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                  autoSyncEnabled ? 'bg-primary' : 'bg-muted-foreground/30'
                }`}
                role="switch"
                aria-checked={autoSyncEnabled}
              >
                <span
                  className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-background shadow-lg ring-0 transition duration-200 ease-in-out ${
                    autoSyncEnabled ? 'translate-x-5' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>

            {/* Schedule Option Cards */}
            <div className="space-y-2 pt-1 border-t border-border/60">
              <label className="text-[11px] font-bold text-foreground flex items-center justify-between pt-1">
                <span className="flex items-center gap-1.5">
                  <Timer className="w-3.5 h-3.5 text-primary" />
                  Select Schedule Frequency
                </span>
                <span className="text-[10px] font-mono text-muted-foreground">
                  Current: <strong className="text-foreground uppercase">{currentFrequency}</strong>
                </span>
              </label>

              <div className="space-y-2">
                {AUTO_SYNC_SCHEDULES.map((opt) => {
                  const isSelected = effectiveFreq === opt.id;
                  const isOff = opt.id === 'off';
                  return (
                    <button
                      key={opt.id}
                      type="button"
                      disabled={isSubmitting}
                      onClick={() => handleSelectSchedule(opt.id)}
                      className={`w-full p-3 rounded-xl border text-left transition-all flex items-start justify-between cursor-pointer group ${
                        isSelected
                          ? isOff
                            ? 'bg-amber-500/10 border-amber-500/40 text-foreground ring-1 ring-amber-500/30'
                            : 'bg-primary/10 border-primary text-foreground shadow-3xs ring-1 ring-primary/40'
                          : 'bg-card border-border hover:border-primary/40 hover:bg-muted/40 text-muted-foreground'
                      }`}
                    >
                      <div className="space-y-0.5 pr-3">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-xs font-bold text-foreground group-hover:text-primary transition-colors">
                            {opt.title}
                          </span>
                          <span
                            className={`text-[9px] font-mono font-bold px-2 py-0.5 rounded-full uppercase ${
                              isSelected
                                ? isOff
                                  ? 'bg-amber-500/20 text-amber-600 dark:text-amber-400 border border-amber-500/30'
                                  : 'bg-primary text-primary-foreground'
                                : 'bg-muted text-muted-foreground border border-border/80'
                            }`}
                          >
                            {opt.badge}
                          </span>
                          {opt.recommended && (
                            <span className="text-[9px] font-bold text-amber-500 dark:text-amber-400 flex items-center gap-0.5">
                              <Sparkles className="w-2.5 h-2.5" /> Recommended
                            </span>
                          )}
                        </div>
                        <p className="text-[11px] text-muted-foreground leading-snug">{opt.subtitle}</p>
                      </div>

                      <div
                        className={`w-5 h-5 rounded-full border flex items-center justify-center shrink-0 mt-0.5 transition-all ${
                          isSelected
                            ? isOff
                              ? 'bg-amber-500 border-amber-500 text-white'
                              : 'bg-primary border-primary text-primary-foreground'
                            : 'border-border bg-background group-hover:border-primary/50'
                        }`}
                      >
                        {isSelected && <CheckCircle2 className="w-3.5 h-3.5" />}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          {/* OPTION 2: REAL-TIME WEBHOOK TRIGGERS */}
          <div className="p-4 rounded-xl border border-border/80 bg-muted/20 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className={`p-2 rounded-lg ${webhookEnabled ? 'bg-amber-500/15 text-amber-600 dark:text-amber-400' : 'bg-muted text-muted-foreground'}`}>
                  <Zap className="w-4 h-4" />
                </div>
                <div>
                  <h4 className="text-xs font-bold text-foreground flex items-center gap-2">
                    Real-Time Webhooks Trigger
                    <span className={`text-[9px] font-mono px-1.5 py-0.5 rounded ${webhookEnabled ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 font-bold' : 'bg-muted text-muted-foreground'}`}>
                      {webhookEnabled ? 'ON' : 'OFF (Default)'}
                    </span>
                  </h4>
                  <p className="text-[11px] text-muted-foreground">
                    Instant push ingestion triggered whenever a new item is created or updated externally.
                  </p>
                </div>
              </div>

              {/* Toggle Switch */}
              <button
                type="button"
                onClick={() => setWebhookEnabled(!webhookEnabled)}
                disabled={isSubmitting}
                className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                  webhookEnabled ? 'bg-amber-500' : 'bg-muted-foreground/30'
                }`}
                role="switch"
                aria-checked={webhookEnabled}
              >
                <span
                  className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-background shadow-lg ring-0 transition duration-200 ease-in-out ${
                    webhookEnabled ? 'translate-x-5' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>

            <div className="p-2.5 rounded-lg bg-background/80 border border-border/60 text-[11px] text-muted-foreground flex items-center justify-between">
              <span>
                {webhookEnabled
                  ? 'Active: External webhooks will trigger immediate document ingestion.'
                  : 'Disabled: Real-time webhook events are ignored to save resources.'}
              </span>
              <span className="font-mono text-[10px] uppercase font-bold text-foreground">
                {webhookEnabled ? 'WEBHOOK ACTIVE' : 'WEBHOOK OFF'}
              </span>
            </div>
          </div>

          {/* Schedule Preview & Detail Box */}
          <div className="p-3.5 rounded-xl bg-muted/30 border border-border/80 flex items-center justify-between text-xs">
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4 text-primary shrink-0" />
              <div>
                <p className="font-semibold text-foreground">Estimated Cadence</p>
                <p className="text-[11px] text-muted-foreground">{currentOption.nextRunDesc}</p>
              </div>
            </div>
            <span className="font-mono text-xs font-bold px-2.5 py-1 bg-background border border-border rounded-lg text-primary">
              {currentOption.id.toUpperCase()}
            </span>
          </div>

          {/* Bottom Actions */}
          <div className="pt-3 flex justify-end gap-2 border-t border-border/60">
            <Button variant="outline" type="button" onClick={onClose} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button
              variant="primary"
              type="submit"
              isLoading={isSubmitting}
              loadingText="Saving Settings..."
              disabled={isSubmitting}
            >
              Save & Apply Settings
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default AutoSyncModal;
