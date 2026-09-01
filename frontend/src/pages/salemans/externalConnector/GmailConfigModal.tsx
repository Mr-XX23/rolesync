import React, { useState } from 'react';
import { Mail, Check, AlertCircle, Layers, Sliders, ShieldCheck, X } from 'lucide-react';
import { Button } from '../../../components/common/Button';

interface GmailConfigModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (maxEmails: number, categories: string[]) => Promise<void>;
  initialMaxEmails?: number;
  initialCategories?: string[];
  isLocked?: boolean;
}

const CATEGORY_OPTIONS = [
  { id: 'INBOX', label: 'Inbox', desc: 'Primary customer correspondence & inquiries' },
  { id: 'SENT', label: 'Sent', desc: 'Outbound sales responses & agent proposals' },
  { id: 'PROMOTIONS', label: 'Promotions', desc: 'Marketing campaigns & vendor newsletters' },
  { id: 'SOCIAL', label: 'Social', desc: 'Platform notifications & network updates' },
  { id: 'ALL', label: 'All Mail', desc: 'Exhaustive indexing across entire mailbox' },
];

export const GmailConfigModal: React.FC<GmailConfigModalProps> = ({
  isOpen,
  onClose,
  onSave,
  initialMaxEmails = 10,
  initialCategories = ['INBOX'],
  isLocked = false,
}) => {
  const [maxEmails, setMaxEmails] = useState<number>(initialMaxEmails);
  const [selectedCategories, setSelectedCategories] = useState<string[]>(
    initialCategories.length > 0 ? initialCategories : ['INBOX']
  );
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
      await onSave(maxEmails, selectedCategories);
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
        className="absolute inset-0 bg-black/50 backdrop-blur-xs transition-opacity duration-300 animate-in fade-in"
        onClick={onClose}
      />

      {/* Modal Card */}
      <div className="relative w-full max-w-lg bg-card border border-border rounded-2xl shadow-2xl z-10 animate-in zoom-in-95 duration-200 overflow-hidden text-left">
        {/* Header */}
        <div className="p-6 border-b border-border/80 flex justify-between items-start bg-muted/20">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-red-50 dark:bg-red-950/40 border border-red-200/50 dark:border-red-800/40 flex items-center justify-center shadow-3xs">
              <Mail className="w-5 h-5 text-red-500" />
            </div>
            <div>
              <h3 className="font-serif text-lg font-bold text-foreground">Configure Gmail Sync</h3>
              <p className="text-xs text-muted-foreground">
                Define batch sizes, category scopes, and backfill parameters.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg border border-border/60 hover:bg-muted text-muted-foreground hover:text-foreground transition-all"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Lock Warning Banner */}
        {isLocked && (
          <div className="bg-amber-500/10 border-y border-amber-500/20 px-6 py-2.5 flex items-center gap-2 text-xs font-semibold text-amber-600 dark:text-amber-400">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>Sync active: configuration is locked until current batch completes.</span>
          </div>
        )}

        {/* Form Body */}
        <form onSubmit={handleFormSubmit} className="p-6 space-y-6 max-h-[75vh] overflow-y-auto">
          {errorMsg && (
            <div className="p-3 bg-destructive/10 border border-destructive/20 rounded-xl text-xs text-destructive flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{errorMsg}</span>
            </div>
          )}

          {/* Setting 1: Max Emails Per Sync */}
          <div className="space-y-3">
            <div className="flex justify-between items-center">
              <label className="text-xs font-bold text-foreground flex items-center gap-1.5">
                <Sliders className="w-3.5 h-3.5 text-primary" />
                <span>Maximum Emails Per Sync</span>
              </label>
              <span className="text-xs font-mono font-bold px-2.5 py-0.5 bg-primary/10 text-primary border border-primary/20 rounded-md">
                {maxEmails} Emails
              </span>
            </div>

            <div className="space-y-2">
              <input
                type="range"
                min={1}
                max={30}
                value={maxEmails}
                disabled={isLocked}
                onChange={(e) => setMaxEmails(Number(e.target.value))}
                className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary disabled:opacity-50"
              />
              <div className="flex justify-between text-[10px] font-mono text-muted-foreground">
                <span>Min: 1</span>
                <span>Default: 10</span>
                <span>Max: 30</span>
              </div>
            </div>

            <p className="text-[11px] text-muted-foreground leading-relaxed">
              Emails are processed internally in parallel sub-batches of <strong>5 at a time</strong> to prevent rate limiting and optimize attachment parsing.
            </p>
          </div>

          {/* Setting 2: Categories / Labels */}
          <div className="space-y-3">
            <div className="flex justify-between items-center">
              <label className="text-xs font-bold text-foreground flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5 text-primary" />
                <span>Included Mail Categories</span>
              </label>
              <span className="text-[10px] font-mono text-muted-foreground font-semibold">
                {selectedCategories.length} selected
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {CATEGORY_OPTIONS.map((cat) => {
                const isSelected = selectedCategories.includes(cat.id);
                return (
                  <button
                    key={cat.id}
                    type="button"
                    disabled={isLocked}
                    onClick={() => toggleCategory(cat.id)}
                    className={`p-3 rounded-xl border text-left transition-all flex items-start justify-between cursor-pointer ${
                      isSelected
                        ? 'bg-primary/10 border-primary/40 text-foreground shadow-3xs'
                        : 'bg-muted/30 border-border hover:border-primary/30 text-muted-foreground'
                    } ${isLocked ? 'opacity-50 cursor-not-allowed' : ''}`}
                  >
                    <div className="space-y-0.5 pr-2">
                      <p className="text-xs font-bold text-foreground">{cat.label}</p>
                      <p className="text-[10px] text-muted-foreground leading-tight">{cat.desc}</p>
                    </div>
                    <div
                      className={`w-4 h-4 rounded-md border flex items-center justify-center shrink-0 mt-0.5 ${
                        isSelected
                          ? 'bg-primary border-primary text-primary-foreground'
                          : 'border-border bg-background'
                      }`}
                    >
                      {isSelected && <Check className="w-3 h-3 stroke-[3]" />}
                    </div>
                  </button>
                );
              })}
            </div>
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              Selecting multiple categories will broaden the email discovery scope across your folders.
            </p>
          </div>

          {/* Information Badges */}
          <div className="bg-muted/40 border border-border/80 rounded-xl p-4 space-y-2 text-[11px] text-muted-foreground">
            <div className="flex items-center gap-2 font-semibold text-foreground">
              <ShieldCheck className="w-4 h-4 text-emerald-500 shrink-0" />
              <span>Production Pipeline Safeguards</span>
            </div>
            <ul className="space-y-1 list-disc pl-5">
              <li><strong>90-Day Backfill:</strong> Syncs newest to oldest within 90 days.</li>
              <li><strong>LlamaParse (25MB Limit):</strong> Attachments &le; 25MB are parsed and combined with the parent email. Attachments &gt; 25MB are skipped without failing the email.</li>
              <li><strong>Zero Duplicates:</strong> Strict deduplication by message ID across manual, auto, and webhook events.</li>
            </ul>
          </div>

          {/* Bottom Actions */}
          <div className="pt-2 flex justify-end gap-2 border-t border-border/60">
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
              Save & Start Initial Sync
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default GmailConfigModal;
