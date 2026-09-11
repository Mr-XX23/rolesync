import React, { useState } from 'react';
import { X, AlertTriangle, Archive, Trash2, Loader2, ShieldCheck } from 'lucide-react';
import { type Product } from '../../../api/catalogApi';

interface DeleteProductModalProps {
  product: Product | null;
  isOpen: boolean;
  onClose: () => void;
  onConfirmRetire: (product: Product) => Promise<void>;
  onConfirmPermanentDelete: (product: Product) => Promise<void>;
  variantCount?: number;
}

export const DeleteProductModal: React.FC<DeleteProductModalProps> = ({
  product,
  isOpen,
  onClose,
  onConfirmRetire,
  onConfirmPermanentDelete,
  variantCount = 0,
}) => {
  const [loadingAction, setLoadingAction] = useState<'retire' | 'permanent' | null>(null);

  if (!isOpen || !product) return null;

  const isAlreadyRetired = product.status === 'RETIRED';

  const handleRetire = async () => {
    if (isAlreadyRetired) return;
    try {
      setLoadingAction('retire');
      await onConfirmRetire(product);
      onClose();
    } finally {
      setLoadingAction(null);
    }
  };

  const handlePermanent = async () => {
    try {
      setLoadingAction('permanent');
      await onConfirmPermanentDelete(product);
      onClose();
    } finally {
      setLoadingAction(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs animate-in fade-in duration-200">
      <div className="relative w-full max-w-lg bg-card border border-border/80 rounded-2xl shadow-2xl overflow-hidden flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-border/60 flex items-center justify-between bg-card/80">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-destructive/10 border border-destructive/20 flex items-center justify-center text-destructive">
              <Trash2 className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-foreground font-sans">
                Delete or Retire Product
              </h3>
              <p className="text-xs text-muted-foreground truncate max-w-xs sm:max-w-sm">
                {product.name}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={loadingAction !== null}
            className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content Body */}
        <div className="p-6 space-y-4">
          {/* Target Product Summary Pill */}
          <div className="p-3 rounded-xl bg-muted/40 border border-border/70 flex items-center justify-between text-xs">
            <div className="space-y-0.5 min-w-0 pr-2">
              <div className="font-bold text-foreground truncate">{product.name}</div>
              <div className="text-muted-foreground font-mono text-[11px]">
                {product.category} {product.subcategory ? `• ${product.subcategory}` : ''} • {variantCount} SKU{variantCount !== 1 ? 's' : ''}
              </div>
            </div>
            <span
              className={`text-[10px] font-mono px-2 py-0.5 rounded-md font-bold shrink-0 ${
                product.status === 'ACTIVE'
                  ? 'bg-emerald-500/10 text-emerald-500 border border-emerald-500/20'
                  : product.status === 'DRAFT'
                  ? 'bg-amber-500/10 text-amber-500 border border-amber-500/20'
                  : 'bg-slate-500/10 text-slate-400 border border-slate-500/20'
              }`}
            >
              {product.status}
            </span>
          </div>

          <p className="text-xs text-muted-foreground leading-relaxed">
            Choose how you would like to remove this product. In commercial catalogs, soft-retiring protects your sales and inventory history, while permanent deletion purges test or duplicate data.
          </p>

          {/* Option 1: Soft-Retire */}
          <div className="p-4 rounded-xl border border-amber-500/30 bg-amber-500/5 space-y-3">
            <div className="flex items-start gap-3">
              <div className="p-2 rounded-lg bg-amber-500/10 text-amber-600 dark:text-amber-400 shrink-0">
                <Archive className="w-4 h-4" />
              </div>
              <div className="flex-1 space-y-1">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-bold text-foreground">
                    1. Retire Product (Soft Delete — Recommended)
                  </h4>
                  <span className="text-[10px] font-semibold text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
                    <ShieldCheck className="w-3 h-3" /> Safe
                  </span>
                </div>
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                  Deactivates this item from sales and prevents AI agents from quoting it. Historical order records, ledger entries, and audit logs remain safe and intact.
                </p>
              </div>
            </div>

            <div className="flex justify-end pt-1">
              <button
                type="button"
                disabled={isAlreadyRetired || loadingAction !== null}
                onClick={handleRetire}
                className="px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-amber-500/15 hover:bg-amber-500/25 text-amber-700 dark:text-amber-300 border border-amber-500/30 transition-all flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
              >
                {loadingAction === 'retire' && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {isAlreadyRetired ? 'Already Retired' : 'Retire Product'}
              </button>
            </div>
          </div>

          {/* Option 2: Permanent Delete */}
          <div className="p-4 rounded-xl border border-destructive/30 bg-destructive/5 space-y-3">
            <div className="flex items-start gap-3">
              <div className="p-2 rounded-lg bg-destructive/10 text-destructive shrink-0">
                <AlertTriangle className="w-4 h-4" />
              </div>
              <div className="flex-1 space-y-1">
                <h4 className="text-xs font-bold text-destructive">
                  2. Permanently Delete (Hard Delete / Purge)
                </h4>
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                  Completely and irreversibly removes this product, all its variants, and stock records from the database forever. Ideal for clearing test data.
                </p>
              </div>
            </div>

            <div className="flex justify-end pt-1">
              <button
                type="button"
                disabled={loadingAction !== null}
                onClick={handlePermanent}
                className="px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-destructive text-destructive-foreground hover:bg-destructive/90 transition-all flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed shadow-xs cursor-pointer"
              >
                {loadingAction === 'permanent' && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                Permanently Delete
              </button>
            </div>
          </div>
        </div>

        {/* Modal Footer */}
        <div className="px-6 py-3 border-t border-border/60 bg-muted/20 flex items-center justify-end">
          <button
            type="button"
            disabled={loadingAction !== null}
            onClick={onClose}
            className="px-4 py-2 text-xs font-medium rounded-xl border border-border/70 hover:bg-muted/60 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
};
