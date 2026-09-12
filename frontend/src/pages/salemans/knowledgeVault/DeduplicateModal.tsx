import React, { useEffect, useState, useCallback } from 'react';
import { Layers, Trash2, X, Loader2, CheckCircle2, AlertTriangle } from 'lucide-react';
import { Button } from '../../../components/common/Button';
import { useToast } from '../../../context/ToastContext';
import { knowledgeVaultApi, type DedupResult } from '../../../api/knowledgeVaultApi';

interface DeduplicateModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** Called after duplicates are actually removed, so the vault can reload. */
  onCleaned: (removedCount: number) => void;
}

export const DeduplicateModal: React.FC<DeduplicateModalProps> = ({ isOpen, onClose, onCleaned }) => {
  const toast = useToast();
  const [preview, setPreview] = useState<DedupResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isRemoving, setIsRemoving] = useState(false);
  const [error, setError] = useState('');

  const loadPreview = useCallback(async () => {
    setIsLoading(true);
    setError('');
    try {
      const result = await knowledgeVaultApi.deduplicateDocuments(false);
      setPreview(result);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || 'Failed to scan for duplicates.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      setPreview(null);
      loadPreview();
    }
  }, [isOpen, loadPreview]);

  const handleRemove = useCallback(async () => {
    setIsRemoving(true);
    setError('');
    try {
      const result = await knowledgeVaultApi.deduplicateDocuments(true);
      toast.success(result.message, 'Duplicates Removed');
      onCleaned(result.removed_documents);
      onClose();
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || 'Failed to remove duplicates.';
      setError(msg);
      toast.error(msg, 'Cleanup Failed');
    } finally {
      setIsRemoving(false);
    }
  }, [toast, onCleaned, onClose]);

  if (!isOpen) return null;

  const removable = preview?.removable_documents ?? 0;
  const groups = preview?.details ?? [];
  const isBusy = isLoading || isRemoving;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-background/80 backdrop-blur-sm animate-in fade-in duration-200"
      onClick={() => !isBusy && onClose()}
    >
      <div
        className="bg-card border border-border rounded-2xl max-w-lg w-full p-6 shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200 space-y-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between">
          <div className="w-11 h-11 rounded-xl bg-amber-500/10 text-amber-500 flex items-center justify-center shrink-0">
            <Layers className="w-6 h-6" />
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isBusy}
            className="p-1 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
            aria-label="Close dialog"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div>
          <h3 className="font-serif text-lg font-bold text-foreground">Clean Up Duplicate Documents</h3>
          <p className="text-xs text-muted-foreground mt-2 leading-relaxed">
            Documents with identical content are grouped together. The best copy of each (most
            vector chunks, most recently indexed) is kept and the rest are permanently removed
            along with their vector embeddings.
          </p>
        </div>

        {/* Body */}
        {isLoading ? (
          <div className="flex items-center justify-center gap-2 py-8 text-muted-foreground">
            <Loader2 className="w-5 h-5 animate-spin" />
            <span className="text-sm">Scanning your vault for duplicates…</span>
          </div>
        ) : error && !preview ? (
          <div className="flex items-start gap-2 p-3 bg-rose-500/10 border border-rose-500/20 rounded-xl text-rose-600 dark:text-rose-400">
            <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
            <p className="text-xs leading-relaxed">{error}</p>
          </div>
        ) : removable === 0 ? (
          <div className="flex items-center gap-2 p-4 bg-emerald-500/10 border border-emerald-500/20 rounded-xl text-emerald-600 dark:text-emerald-400">
            <CheckCircle2 className="w-5 h-5 shrink-0" />
            <p className="text-sm font-medium">No duplicate documents found — your vault is clean.</p>
          </div>
        ) : (
          <>
            <div className="p-3 bg-muted/40 rounded-xl border border-border/60">
              <p className="text-xs font-mono text-foreground/80">
                <span className="font-bold">{removable}</span> duplicate document(s) across{' '}
                <span className="font-bold">{groups.length}</span> group(s) will be removed.
              </p>
            </div>
            <div className="max-h-60 overflow-y-auto space-y-2 pr-1">
              {groups.map((g) => (
                <div key={g.kept_doc_id} className="p-3 rounded-xl border border-border/60 bg-background/40">
                  <p className="text-sm font-semibold text-foreground truncate" title={g.name}>
                    {g.name || g.kept_doc_id}
                  </p>
                  <p className="text-[11px] text-emerald-600 dark:text-emerald-400 mt-1 font-mono">
                    Keep: {g.kept_doc_id} · {g.kept_chunks ?? 0} chunks
                  </p>
                  <p className="text-[11px] text-rose-600 dark:text-rose-400 mt-0.5 font-mono">
                    Remove {g.removed.length}:{' '}
                    {g.removed
                      .map((r) => `${r.doc_id} (${r.chunks} chunks${r.status ? `, ${r.status}` : ''})`)
                      .join(', ')}
                  </p>
                </div>
              ))}
            </div>
            {error && <p className="text-xs text-rose-600 dark:text-rose-400">{error}</p>}
          </>
        )}

        {/* Footer */}
        <div className="flex justify-end gap-2.5 pt-2">
          <Button type="button" variant="outline" onClick={onClose} disabled={isBusy}>
            {removable === 0 ? 'Close' : 'Cancel'}
          </Button>
          {removable > 0 && (
            <Button
              type="button"
              onClick={handleRemove}
              isLoading={isRemoving}
              loadingText="Removing…"
              disabled={isLoading}
              className="bg-rose-600 hover:bg-rose-700 text-white border-transparent"
              icon={<Trash2 className="w-4 h-4" />}
            >
              Remove {removable} Duplicate{removable === 1 ? '' : 's'}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
};
