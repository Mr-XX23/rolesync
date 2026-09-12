import React, { useState } from 'react';
import { X, Globe, Link2, AlertCircle } from 'lucide-react';
import { Button } from '../../../components/common/Button';
import { useToast } from '../../../context/ToastContext';
import { knowledgeVaultApi, type KnowledgeDocument } from '../../../api/knowledgeVaultApi';

interface IngestUrlModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (newDoc: KnowledgeDocument) => void;
}

export const IngestUrlModal: React.FC<IngestUrlModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
}) => {
  const toast = useToast();
  const [url, setUrl] = useState('');
  const [title, setTitle] = useState('');
  const [category, setCategory] = useState('WEB_DOCUMENT');
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen) return null;

  const validateUrl = (value: string): boolean => {
    try {
      const parsed = new URL(value);
      return parsed.protocol === 'http:' || parsed.protocol === 'https:';
    } catch {
      return false;
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmedUrl = url.trim();

    if (!trimmedUrl) {
      setError('Please provide a valid web URL.');
      return;
    }

    if (!validateUrl(trimmedUrl)) {
      setError('Invalid URL format. Please make sure it starts with http:// or https://');
      return;
    }

    setError('');
    setIsSubmitting(true);

    try {
      const doc = await knowledgeVaultApi.ingestUrl(
        trimmedUrl,
        title.trim() || undefined,
        category
      );
      toast.success(
        `URL queued for automated parsing and vector embedding.`,
        'Ingestion Scheduled'
      );
      onSuccess(doc);
      handleClose();
    } catch (err: any) {
      console.error('[IngestUrlModal] Ingestion error:', err);
      const msg = err.message || 'Failed to queue URL for ingestion.';
      setError(msg);
      toast.error(msg, 'Ingestion Failed');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClose = () => {
    // Ingestion is in flight — don't allow the modal to be dismissed (backdrop,
    // X, or Cancel) so the crawl/index job can't be orphaned mid-request.
    if (isSubmitting) return;
    setUrl('');
    setTitle('');
    setError('');
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-background/80 backdrop-blur-sm animate-in fade-in duration-200"
      onClick={handleClose}
    >
      <div
        className="bg-card border border-border rounded-2xl max-w-lg w-full shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border bg-muted/30">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary/10 text-primary flex items-center justify-center shadow-2xs">
              <Globe className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-serif text-lg font-bold text-foreground">
                Ingest Business Webpage
              </h3>
              <p className="text-xs text-muted-foreground">
                Crawl, normalize, and vectorize live documentation or pricing pages.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleClose}
            disabled={isSubmitting}
            className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-muted-foreground"
            aria-label="Close modal"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="flex items-start gap-2.5 p-3 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-600 dark:text-rose-400 text-xs">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {/* URL Input */}
          <div className="space-y-1.5">
            <label htmlFor="target-url-input" className="text-xs font-semibold text-foreground flex items-center gap-1.5">
              <Link2 className="w-3.5 h-3.5 text-primary" />
              Target Web URL <span className="text-rose-500">*</span>
            </label>
            <input
              id="target-url-input"
              type="url"
              placeholder="https://enterprise.acme.com/pricing-guide"
              value={url}
              onChange={(e) => {
                setUrl(e.target.value);
                if (error) setError('');
              }}
              required
              className="w-full bg-background border border-border rounded-xl px-3.5 py-2.5 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary"
              autoFocus
            />
            <p className="text-[10px] text-muted-foreground">
              HTML scripts and style blocks are sanitized; main text will be hierarchical chunked.
            </p>
          </div>

          {/* Title Input */}
          <div className="space-y-1.5">
            <label htmlFor="doc-title-input" className="text-xs font-semibold text-foreground">
              Document Display Name <span className="text-muted-foreground font-normal">(Optional)</span>
            </label>
            <input
              id="doc-title-input"
              type="text"
              placeholder="e.g. Acme 2026 Enterprise Pricing & Tiers"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full bg-background border border-border rounded-xl px-3.5 py-2.5 text-xs focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary"
            />
          </div>

          {/* Category Selector */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-foreground">
              Intelligence Category
            </label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full bg-background border border-border rounded-xl px-3 py-2 text-xs font-medium focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary"
            >
              <option value="WEB_DOCUMENT">Web Document / General Wiki</option>
              <option value="PRICING_CATALOG">Pricing Catalog & Tiers</option>
              <option value="COMPLIANCE_POLICY">Compliance & Security Policy</option>
              <option value="API_REFERENCE">API & Technical Reference</option>
            </select>
          </div>

          {/* Footer Buttons */}
          <div className="pt-4 border-t border-border/60 flex justify-end gap-2.5">
            <Button
              type="button"
              variant="outline"
              onClick={handleClose}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              isLoading={isSubmitting}
              loadingText="Crawling & Indexing..."
            >
              Start URL Ingestion
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};
