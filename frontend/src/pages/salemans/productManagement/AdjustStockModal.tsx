import React, { useState, useEffect, useRef } from 'react';
import { X, Package, AlertCircle, CheckCircle2, Loader2, ChevronDown, Search } from 'lucide-react';
import {
  catalogApi,
  type Variant,
  type Location,
  type Product,
} from '../../../api/catalogApi';
import { useToast } from '../../../context/ToastContext';

interface AdjustStockModalProps {
  isOpen: boolean;
  onClose: () => void;
  onStockUpdated: () => void;
  variants: Variant[];
  products: Product[];
  locations: Location[];
  initialVariantId?: string;
  initialLocationId?: string;
}

/* ─── Reusable custom dropdown (stays inside modal) ─── */
interface DropdownOption {
  value: string;
  label: string;
  sub?: string;
}

const CustomSelect: React.FC<{
  options: DropdownOption[];
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  searchable?: boolean;
}> = ({ options, value, onChange, placeholder = 'Select…', searchable = false }) => {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const ref = useRef<HTMLDivElement>(null);

  // close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const selected = options.find((o) => o.value === value);
  const filtered = search
    ? options.filter(
        (o) =>
          o.label.toLowerCase().includes(search.toLowerCase()) ||
          (o.sub && o.sub.toLowerCase().includes(search.toLowerCase()))
      )
    : options;

  return (
    <div ref={ref} className="relative">
      {/* Trigger button */}
      <button
        type="button"
        onClick={() => {
          setOpen(!open);
          setSearch('');
        }}
        className="w-full px-3 py-2.5 text-xs rounded-xl bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40 flex items-center justify-between gap-2 cursor-pointer text-left"
      >
        <span className="truncate">
          {selected ? selected.label : placeholder}
        </span>
        <ChevronDown className={`w-3.5 h-3.5 shrink-0 text-muted-foreground transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {/* Dropdown list */}
      {open && (
        <div className="absolute left-0 right-0 top-full mt-1 z-50 bg-card border border-border/80 rounded-xl shadow-lg overflow-hidden">
          {searchable && (
            <div className="p-2 border-b border-border/60">
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search…"
                  autoFocus
                  className="w-full pl-8 pr-3 py-2 text-xs rounded-lg bg-background border border-border/60 text-foreground focus:outline-hidden focus:ring-1 focus:ring-primary/40"
                />
              </div>
            </div>
          )}
          <div className="max-h-48 overflow-y-auto">
            {filtered.length === 0 ? (
              <div className="px-3 py-4 text-xs text-muted-foreground text-center">
                No results found
              </div>
            ) : (
              filtered.map((o) => (
                <button
                  key={o.value}
                  type="button"
                  onClick={() => {
                    onChange(o.value);
                    setOpen(false);
                    setSearch('');
                  }}
                  className={`w-full text-left px-3 py-2.5 text-xs hover:bg-muted/60 transition-colors cursor-pointer border-b border-border/30 last:border-b-0 ${
                    o.value === value ? 'bg-primary/10 text-primary font-semibold' : 'text-foreground'
                  }`}
                >
                  <div className="truncate">{o.label}</div>
                  {o.sub && (
                    <div className="text-[11px] text-muted-foreground truncate mt-0.5">{o.sub}</div>
                  )}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
};

/* ─── Main Modal ─── */
export const AdjustStockModal: React.FC<AdjustStockModalProps> = ({
  isOpen,
  onClose,
  onStockUpdated,
  variants,
  products,
  locations,
  initialVariantId,
  initialLocationId,
}) => {
  const toast = useToast();

  const [selectedVariantId, setSelectedVariantId] = useState<string>('');
  const [selectedLocationId, setSelectedLocationId] = useState<string>('');
  const [quantityValue, setQuantityValue] = useState<number>(0);
  const [reason, setReason] = useState<'RESTOCK' | 'SALE' | 'ADJUST' | 'DAMAGE'>('RESTOCK');
  const [note, setNote] = useState<string>('');
  const [refId, setRefId] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      setSelectedVariantId(initialVariantId || (variants[0]?.id ?? ''));
      setSelectedLocationId(initialLocationId || (locations[0]?.id ?? ''));
      setQuantityValue(0);
      setReason('RESTOCK');
      setNote('');
      setRefId('');
      setErrorMessage(null);
    }
  }, [isOpen, initialVariantId, initialLocationId, variants, locations]);

  if (!isOpen) return null;

  // Build product options for dropdown
  const productOptions: DropdownOption[] = variants.map((v) => {
    const p = products.find((prod) => prod.id === v.product_id);
    const name = p?.name || 'Product';
    const opts = v.option_values.map((ov) => ov.value).join(' / ');
    return {
      value: v.id,
      label: opts ? `${name} — ${opts}` : name,
      sub: `SKU: ${v.sku}`,
    };
  });

  // Build location options for dropdown
  const locationOptions: DropdownOption[] = locations.map((loc) => ({
    value: loc.id,
    label: loc.name,
    sub: loc.type,
  }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedVariantId || !selectedLocationId) {
      setErrorMessage('Please select a product and a location.');
      return;
    }
    if (quantityValue < 0) {
      setErrorMessage('Stock quantity cannot be negative.');
      return;
    }

    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      await catalogApi.setStock({
        variant_id: selectedVariantId,
        location_id: selectedLocationId,
        qty: quantityValue,
        reason: reason === 'RESTOCK' ? 'RESTOCK' : 'ADJUST',
        ref_id: refId.trim() || undefined,
        note: note.trim() || undefined,
      });
      toast.success(`Stock updated to ${quantityValue} units.`, 'Stock Updated');

      onStockUpdated();
      onClose();
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Failed to update stock.';
      setErrorMessage(msg);
      toast.error(msg, 'Update Failed');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs animate-in fade-in duration-200">
      <div className="relative w-full max-w-xl bg-card border border-border/80 rounded-2xl shadow-2xl overflow-visible flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="px-6 py-4 border-b border-border/60 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
              <Package className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-semibold text-foreground text-base">Update Stock</h3>
              <p className="text-xs text-muted-foreground">
                Set the stock quantity for a product at a location
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-5 overflow-y-auto">
          {errorMessage && (
            <div className="p-3 rounded-xl bg-destructive/10 border border-destructive/25 text-destructive text-xs flex items-start gap-2">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{errorMessage}</span>
            </div>
          )}

          {/* Product Selection — custom searchable dropdown */}
          <div>
            <label className="block text-xs font-medium text-foreground mb-1.5">
              Product
            </label>
            <CustomSelect
              options={productOptions}
              value={selectedVariantId}
              onChange={setSelectedVariantId}
              placeholder="Select a product…"
              searchable
            />
          </div>

          {/* Location Selection — custom dropdown */}
          <div>
            <label className="block text-xs font-medium text-foreground mb-1.5">
              Warehouse / Hub
            </label>
            <CustomSelect
              options={locationOptions}
              value={selectedLocationId}
              onChange={setSelectedLocationId}
              placeholder="Select a location…"
            />
          </div>

          {/* Quantity & Reason side by side */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-foreground mb-1.5">
                Quantity
              </label>
              <input
                type="number"
                min="0"
                value={quantityValue}
                onChange={(e) => setQuantityValue(parseInt(e.target.value) || 0)}
                required
                className="w-full px-3 py-2.5 text-xs rounded-xl bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40"
                placeholder="e.g. 100"
              />
              <span className="text-[11px] text-muted-foreground mt-1 block">
                Total units at this location
              </span>
            </div>

            <div>
              <label className="block text-xs font-medium text-foreground mb-1.5">
                Reason
              </label>
              <select
                value={reason}
                onChange={(e) => setReason(e.target.value as any)}
                className="w-full px-3 py-2.5 text-xs rounded-xl bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40"
              >
                <option value="RESTOCK">New Stock Received</option>
                <option value="SALE">Sold / Shipped</option>
                <option value="ADJUST">Count Correction</option>
                <option value="DAMAGE">Damaged / Lost</option>
              </select>
            </div>
          </div>

          {/* Reference & Note */}
          <div>
            <label className="block text-xs font-medium text-foreground mb-1.5">
              Reference <span className="text-muted-foreground font-normal">(optional)</span>
            </label>
            <input
              type="text"
              value={refId}
              onChange={(e) => setRefId(e.target.value)}
              placeholder="e.g. PO-89410, Invoice #1234"
              className="w-full px-3 py-2.5 text-xs rounded-xl bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-foreground mb-1.5">
              Note <span className="text-muted-foreground font-normal">(optional)</span>
            </label>
            <textarea
              rows={2}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. Received shipment from supplier"
              className="w-full px-3 py-2.5 text-xs rounded-xl bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40 resize-none"
            />
          </div>

          {/* Footer Actions */}
          <div className="pt-3 border-t border-border/60 flex items-center justify-end gap-2.5">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2.5 text-xs font-medium rounded-xl border border-border/70 hover:bg-muted/50 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-5 py-2.5 text-xs font-semibold rounded-xl bg-primary text-primary-foreground hover:opacity-95 active:scale-98 transition-all flex items-center gap-2 shadow-xs disabled:opacity-50 cursor-pointer"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  Update Stock
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
