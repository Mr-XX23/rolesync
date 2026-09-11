import React, { useState, useEffect } from 'react';
import { X, ArrowRightLeft, AlertCircle, CheckCircle2, Loader2, ArrowRight } from 'lucide-react';
import {
  catalogApi,
  type Variant,
  type Location,
  type Product,
} from '../../../api/catalogApi';
import { useToast } from '../../../context/ToastContext';

interface TransferStockModalProps {
  isOpen: boolean;
  onClose: () => void;
  onStockTransferred: () => void;
  variants: Variant[];
  products: Product[];
  locations: Location[];
  initialSku?: string;
  initialFromLocationId?: string;
}

export const TransferStockModal: React.FC<TransferStockModalProps> = ({
  isOpen,
  onClose,
  onStockTransferred,
  variants,
  products,
  locations,
  initialSku,
  initialFromLocationId,
}) => {
  const toast = useToast();

  const [selectedSku, setSelectedSku] = useState<string>('');
  const [fromLocationId, setFromLocationId] = useState<string>('');
  const [toLocationId, setToLocationId] = useState<string>('');
  const [quantity, setQuantity] = useState<number>(1);
  const [note, setNote] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      setSelectedSku(initialSku || (variants[0]?.sku ?? ''));
      setFromLocationId(initialFromLocationId || (locations[0]?.id ?? ''));
      setToLocationId(locations.length > 1 ? locations[1].id : (locations[0]?.id ?? ''));
      setQuantity(1);
      setNote('');
      setErrorMessage(null);
    }
  }, [isOpen, initialSku, initialFromLocationId, variants, locations]);

  if (!isOpen) return null;

  const getVariantLabel = (v: Variant) => {
    const p = products.find((prod) => prod.id === v.product_id);
    const summary = v.option_values.map((ov) => ov.value).join(' / ');
    return `${v.sku} - ${p?.name || 'Product'}${summary ? ` (${summary})` : ''}`;
  };

  const handleTransfer = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedSku) {
      setErrorMessage('Please select a SKU to transfer.');
      return;
    }
    if (!fromLocationId || !toLocationId) {
      setErrorMessage('Please select source and destination locations.');
      return;
    }
    if (fromLocationId === toLocationId) {
      setErrorMessage('Source and destination locations must be different.');
      return;
    }
    if (quantity <= 0) {
      setErrorMessage('Quantity must be greater than zero.');
      return;
    }

    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      await catalogApi.transferStock({
        sku: selectedSku,
        from_location_id: fromLocationId,
        to_location_id: toLocationId,
        qty: quantity,
        note: note.trim() || undefined,
      });

      const fromLoc = locations.find((l) => l.id === fromLocationId)?.name || 'Source';
      const toLoc = locations.find((l) => l.id === toLocationId)?.name || 'Destination';

      toast.success(
        `Transferred ${quantity} unit(s) of ${selectedSku} from ${fromLoc} to ${toLoc}.`,
        'Transfer Complete'
      );

      onStockTransferred();
      onClose();
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Transfer failed.';
      setErrorMessage(msg);
      toast.error(msg, 'Transfer Error');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs animate-in fade-in duration-200">
      <div className="relative w-full max-w-lg bg-card border border-border/80 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="px-6 py-4 border-b border-border/60 flex items-center justify-between bg-card/80">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
              <ArrowRightLeft className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-semibold text-foreground text-base">Transfer Stock Between Locations</h3>
              <p className="text-xs text-muted-foreground">
                Atomic cross-location balance transfer with paired ledger entries
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleTransfer} className="p-6 space-y-4 overflow-y-auto">
          {errorMessage && (
            <div className="p-3 rounded-xl bg-destructive/10 border border-destructive/25 text-destructive text-xs flex items-start gap-2">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{errorMessage}</span>
            </div>
          )}

          {/* SKU Selection */}
          <div>
            <label className="block text-xs font-medium text-foreground mb-1.5">
              Select Variant (SKU)
            </label>
            <select
              value={selectedSku}
              onChange={(e) => setSelectedSku(e.target.value)}
              required
              className="w-full px-3 py-2 text-xs rounded-xl bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40 font-mono"
            >
              {variants.map((v) => (
                <option key={v.id} value={v.sku}>
                  {getVariantLabel(v)}
                </option>
              ))}
            </select>
          </div>

          {/* From & To Locations */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 items-center">
            <div>
              <label className="block text-xs font-medium text-foreground mb-1.5">
                From Location (Source)
              </label>
              <select
                value={fromLocationId}
                onChange={(e) => setFromLocationId(e.target.value)}
                required
                className="w-full px-3 py-2 text-xs rounded-xl bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40"
              >
                {locations.map((loc) => (
                  <option key={loc.id} value={loc.id}>
                    {loc.name} ({loc.type})
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-foreground mb-1.5">
                To Location (Destination)
              </label>
              <select
                value={toLocationId}
                onChange={(e) => setToLocationId(e.target.value)}
                required
                className="w-full px-3 py-2 text-xs rounded-xl bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40"
              >
                {locations.map((loc) => (
                  <option key={loc.id} value={loc.id}>
                    {loc.name} ({loc.type})
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Quantity */}
          <div>
            <label className="block text-xs font-medium text-foreground mb-1.5">
              Units to Transfer
            </label>
            <input
              type="number"
              min="1"
              value={quantity}
              onChange={(e) => setQuantity(parseInt(e.target.value) || 1)}
              required
              className="w-full px-3 py-2 text-xs rounded-xl bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40 font-mono"
            />
          </div>

          {/* Note */}
          <div>
            <label className="block text-xs font-medium text-foreground mb-1.5">
              Transfer Reason / Note (Optional)
            </label>
            <textarea
              rows={2}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. Replenishing retail storefront stock from central distribution center"
              className="w-full px-3 py-2 text-xs rounded-xl bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40 resize-none"
            />
          </div>

          {/* Transfer Visual Preview */}
          <div className="p-3.5 rounded-xl bg-muted/40 border border-border/60 flex items-center justify-between text-xs">
            <div className="text-muted-foreground truncate">
              Source: <span className="text-foreground font-semibold">{locations.find((l) => l.id === fromLocationId)?.name || 'Select'}</span>
            </div>
            <ArrowRight className="w-4 h-4 text-primary shrink-0 mx-2" />
            <div className="text-muted-foreground truncate">
              Dest: <span className="text-foreground font-semibold">{locations.find((l) => l.id === toLocationId)?.name || 'Select'}</span>
            </div>
          </div>

          {/* Footer Actions */}
          <div className="pt-3 border-t border-border/60 flex items-center justify-end gap-2.5">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-xs font-medium rounded-xl border border-border/70 hover:bg-muted/50 text-muted-foreground hover:text-foreground transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-4 py-2 text-xs font-semibold rounded-xl bg-primary text-primary-foreground hover:opacity-95 active:scale-98 transition-all flex items-center gap-2 shadow-xs disabled:opacity-50"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  Executing Transfer...
                </>
              ) : (
                <>
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  Commit Stock Transfer
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
