import React, { useState } from 'react';
import { Sliders, Layers, X, AlertCircle } from 'lucide-react';
import { Button } from '../../../components/common/Button';

export interface CategoryOption {
  id: string;
  label: string;
  desc: string;
}

export interface ConnectorConfigModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (maxItems: number, categories: string[], syncFreq?: string) => Promise<void>;
  connectorId: string;
  connectorName: string;
  logoUrl?: string;
  initialMaxItems?: number;
  initialCategories?: string[];
  initialSyncFreq?: string;
  isLocked?: boolean;
}

const CONNECTOR_CATEGORIES: Record<string, { label: string; itemNoun: string; options: CategoryOption[] }> = {
  gmail: {
    label: 'Mail Categories & Folders',
    itemNoun: 'Emails',
    options: [
      { id: 'INBOX', label: 'Inbox', desc: 'Primary customer correspondence & inquiries' },
      { id: 'SENT', label: 'Sent', desc: 'Outbound sales responses & agent proposals' },
      { id: 'PROMOTIONS', label: 'Promotions', desc: 'Marketing campaigns & vendor newsletters' },
      { id: 'SOCIAL', label: 'Social', desc: 'Platform notifications & network updates' },
      { id: 'ALL', label: 'All Mail', desc: 'Exhaustive indexing across entire mailbox' },
    ],
  },
  gdrive: {
    label: 'Storage Scopes & File Types',
    itemNoun: 'Documents',
    options: [
      { id: 'MY_DRIVE', label: 'My Drive', desc: 'Personal documents, presentations & notes' },
      { id: 'SHARED', label: 'Shared with Me', desc: 'Team collaborator sheets, contracts & PDFs' },
      { id: 'CONTRACTS', label: 'Contracts & Legal', desc: 'Client MSAs, NDAs & service proposals' },
      { id: 'REPORTS', label: 'Financial & Reports', desc: 'Quarterly spreadsheets, budgets & metrics' },
      { id: 'ALL', label: 'All Cloud Files', desc: 'Complete organizational drive index' },
    ],
  },
  calendar: {
    label: 'Calendar Event Categories',
    itemNoun: 'Events',
    options: [
      { id: 'PRIMARY', label: 'Primary Calendar', desc: 'Direct 1-on-1 calls, meetings & client demos' },
      { id: 'TEAM', label: 'Team Standups', desc: 'Sprint syncs, project reviews & internal events' },
      { id: 'APPOINTMENTS', label: 'Client Appointments', desc: 'External sales discovery & vendor calls' },
      { id: 'RECURRING', label: 'Recurring Schedules', desc: 'Weekly reviews, monthly all-hands & rituals' },
      { id: 'ALL', label: 'All Calendars', desc: 'Exhaustive indexing across all calendar schedules' },
    ],
  },
  slack: {
    label: 'Slack Channel Scopes',
    itemNoun: 'Threads',
    options: [
      { id: 'GENERAL', label: 'Company Announcements', desc: 'Organization-wide updates & townhall threads' },
      { id: 'SALES', label: 'Sales & Inbound Leads', desc: 'Deal negotiations, lead qualifications & wins' },
      { id: 'SUPPORT', label: 'Customer Support', desc: 'Bug triage, client escalation & feedback' },
      { id: 'TEAM', label: 'Team Collaboration', desc: 'Engineering, product and operations channels' },
      { id: 'ALL', label: 'All Public Channels', desc: 'Exhaustive indexing across all open discussions' },
    ],
  },
  notion: {
    label: 'Notion Database & Wiki Scopes',
    itemNoun: 'Pages',
    options: [
      { id: 'SPECS', label: 'Product Specs & PRDs', desc: 'Feature documentation, technical architecture' },
      { id: 'WIKIS', label: 'Internal Wikis & FAQs', desc: 'Company handbook, runbooks & playbooks' },
      { id: 'ROADMAPS', label: 'Roadmap & Task Boards', desc: 'Sprint boards, milestones & delivery tracking' },
      { id: 'MEETING_NOTES', label: 'Meeting Minutes', desc: 'Customer call logs, sprint retro summaries' },
      { id: 'ALL', label: 'All Workspaces', desc: 'Full workspace crawl and page tree indexing' },
    ],
  },
};

export const ConnectorConfigModal: React.FC<ConnectorConfigModalProps> = ({
  isOpen,
  onClose,
  onSave,
  connectorId,
  connectorName,
  logoUrl,
  initialMaxItems = 10,
  initialCategories = [],
  initialSyncFreq = '30m',
  isLocked = false,
}) => {
  const meta = CONNECTOR_CATEGORIES[connectorId.toLowerCase()] || CONNECTOR_CATEGORIES.gmail;

  const defaultCategory = meta.options[0]?.id || 'INBOX';
  const [maxItems, setMaxItems] = useState<number>(initialMaxItems);
  const [selectedCategories, setSelectedCategories] = useState<string[]>(
    initialCategories.length > 0 ? initialCategories : [defaultCategory]
  );
  const [syncFreq, setSyncFreq] = useState<string>(initialSyncFreq);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  if (!isOpen) return null;

  const toggleCategory = (catId: string) => {
    if (catId === 'ALL') {
      setSelectedCategories(['ALL']);
      return;
    }
    let updated = selectedCategories.filter((c) => c !== 'ALL');
    if (updated.includes(catId)) {
      if (updated.length > 1) {
        updated = updated.filter((c) => c !== catId);
      }
    } else {
      updated.push(catId);
    }
    setSelectedCategories(updated);
  };

  const handleFormSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isLocked) {
      setErrorMsg('Cannot modify configuration while synchronization is actively in progress.');
      return;
    }
    setIsSubmitting(true);
    setErrorMsg(null);
    try {
      await onSave(maxItems, selectedCategories, syncFreq);
      onClose();
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail || err?.message || 'Failed to save configuration.');
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

      {/* Modal Card with increased width (max-w-2xl) */}
      <div className="relative w-full max-w-2xl bg-card border border-border rounded-2xl shadow-2xl z-10 animate-in zoom-in-95 duration-200 overflow-hidden text-left flex flex-col max-h-[90vh]">
        {/* Header with real SVG brand icon */}
        <div className="p-6 border-b border-border/80 flex justify-between items-start bg-muted/20">
          <div className="flex items-center gap-3.5">
            <div className="w-12 h-12 rounded-xl bg-muted/50 border border-border flex items-center justify-center shadow-3xs p-2.5">
              {logoUrl ? (
                <img src={logoUrl} alt={connectorName} className="w-full h-full object-contain" />
              ) : (
                <span className="font-bold text-sm text-primary">{connectorName.slice(0, 2).toUpperCase()}</span>
              )}
            </div>
            <div>
              <h3 className="font-serif text-xl font-bold text-foreground">Configure {connectorName} Sync</h3>
              <p className="text-xs text-muted-foreground mt-0.5">
                Define batch limits, indexing scopes, and synchronization parameters for {connectorName}.
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
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>Sync active: configuration is locked until the current synchronization batch completes.</span>
          </div>
        )}

        {/* Form Body */}
        <form onSubmit={handleFormSubmit} className="p-6 space-y-6 overflow-y-auto flex-1">
          {errorMsg && (
            <div className="p-3.5 bg-destructive/10 border border-destructive/20 rounded-xl text-xs text-destructive flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{errorMsg}</span>
            </div>
          )}

          {/* Setting 1: Maximum Items Per Sync Batch */}
          <div className="space-y-3 bg-muted/20 border border-border/70 rounded-xl p-4">
            <div className="flex justify-between items-center">
              <label className="text-xs font-bold text-foreground flex items-center gap-1.5">
                <Sliders className="w-3.5 h-3.5 text-primary" />
                <span>Maximum {meta.itemNoun} Per Sync Batch</span>
              </label>
              <span className="text-xs font-mono font-bold px-3 py-1 bg-primary/10 text-primary border border-primary/20 rounded-md">
                {maxItems} {meta.itemNoun}
              </span>
            </div>

            <div className="space-y-2 pt-1">
              <input
                type="range"
                min={1}
                max={30}
                value={maxItems}
                disabled={isLocked}
                onChange={(e) => setMaxItems(Number(e.target.value))}
                className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary disabled:opacity-50"
              />
              <div className="flex justify-between text-[11px] font-mono text-muted-foreground">
                <span>Min: 1</span>
                <span>Default: 10</span>
                <span>Max: 30</span>
              </div>
            </div>

            <p className="text-[11px] text-muted-foreground leading-relaxed">
              Items are processed in parallel sub-batches of <strong>5 at a time</strong> with strict rate-limit protection and memory vector indexing.
            </p>
          </div>

          {/* Setting 2: Included Categories / Folders */}
          <div className="space-y-3">
            <div className="flex justify-between items-center">
              <label className="text-xs font-bold text-foreground flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5 text-primary" />
                <span>{meta.label}</span>
              </label>
              <span className="text-[11px] font-mono text-muted-foreground font-semibold">
                {selectedCategories.length} selected
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              {meta.options.map((cat) => {
                const isSelected = selectedCategories.includes(cat.id);
                return (
                  <button
                    key={cat.id}
                    type="button"
                    disabled={isLocked}
                    onClick={() => toggleCategory(cat.id)}
                    className={`p-3.5 rounded-xl border text-left transition-all flex items-start justify-between cursor-pointer ${
                      isSelected
                        ? 'bg-primary/10 border-primary/40 text-foreground shadow-3xs'
                        : 'bg-muted/30 border-border hover:border-primary/30 text-muted-foreground'
                    } ${isLocked ? 'opacity-50 cursor-not-allowed' : ''}`}
                  >
                    <div className="space-y-0.5 pr-2">
                      <p className="text-xs font-bold text-foreground">{cat.label}</p>
                      <p className="text-[11px] text-muted-foreground leading-snug">{cat.desc}</p>
                    </div>
                    <div
                      className={`w-4 h-4 rounded-md border flex items-center justify-center shrink-0 mt-0.5 ${
                        isSelected
                          ? 'bg-primary border-primary text-primary-foreground'
                          : 'border-border bg-background'
                      }`}
                    >
                      {isSelected && <span className="text-[10px] font-bold">✓</span>}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Setting 3: Sync Frequency Option */}
          <div className="space-y-2">
            <label className="text-xs font-bold text-foreground">
              Synchronization Schedule
            </label>
            <select
              value={syncFreq}
              disabled={isLocked}
              onChange={(e) => setSyncFreq(e.target.value)}
              className="w-full bg-background border border-border rounded-xl p-2.5 text-xs font-semibold focus:outline-none focus:ring-1 focus:ring-primary cursor-pointer disabled:opacity-50"
            >
              <option value="realtime">Real-time Webhook (Instant indexing on change)</option>
              <option value="30m">30-Minute Auto-Sync Interval</option>
              <option value="hourly">Hourly Interval Scrape</option>
              <option value="daily">Daily Cron Sequence (02:00 AM)</option>
            </select>
          </div>

          {/* Bottom Actions */}
          <div className="pt-4 flex justify-end gap-2 border-t border-border/60">
            <Button variant="outline" type="button" onClick={onClose} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button
              variant="primary"
              type="submit"
              isLoading={isSubmitting}
              loadingText="Saving & Starting..."
              disabled={isLocked || selectedCategories.length === 0}
            >
              Save & Start Synchronization
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default ConnectorConfigModal;
