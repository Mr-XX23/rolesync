import React, { useState, useEffect, useMemo, useRef } from 'react';
import {
  X,
  Zap,
  CheckCircle2,
  AlertTriangle,
  Loader2,
  Building2,
  Search,
  ChevronDown,
} from 'lucide-react';
import {
  catalogApi,
  type Variant,
  type Product,
  type CheckAvailabilityResponse,
} from '../../../api/catalogApi';

interface DealStockCheckModalProps {
  isOpen: boolean;
  onClose: () => void;
  variants: Variant[];
  products: Product[];
  initialSku?: string;
}

export const DealStockCheckModal: React.FC<DealStockCheckModalProps> = ({
  isOpen,
  onClose,
  variants,
  products,
  initialSku,
}) => {
  const [selectedSku, setSelectedSku] = useState<string>('');
  const [quantity, setQuantity] = useState<number>(1);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [result, setResult] = useState<CheckAvailabilityResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Searchable dropdown state
  const [isDropdownOpen, setIsDropdownOpen] = useState<boolean>(false);
  const [dropdownSearch, setDropdownSearch] = useState<string>('');
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Map product_id to Product
  const productMap = useMemo(() => {
    const map = new Map<string, Product>();
    products.forEach((p) => map.set(p.id, p));
    return map;
  }, [products]);

  // Available selectable items
  const selectableVariants = useMemo(() => {
    return variants.map((v) => {
      const prod = productMap.get(v.product_id);
      const opts = v.option_values.map((o) => o.value).join(' / ');
      return {
        variant: v,
        productName: prod?.name || 'Unknown Product',
        productType: prod?.type || 'PRODUCT',
        optionsLabel: opts || 'Standard',
        fullLabel: `${prod?.name || 'Product'} (${v.sku}) - ${opts || 'Standard'}`,
      };
    });
  }, [variants, productMap]);

  // Filtered variants for search inside dropdown
  const filteredDropdownVariants = useMemo(() => {
    if (!dropdownSearch.trim()) return selectableVariants;
    const q = dropdownSearch.toLowerCase();
    return selectableVariants.filter(
      (item) =>
        item.variant.sku.toLowerCase().includes(q) ||
        item.productName.toLowerCase().includes(q) ||
        item.optionsLabel.toLowerCase().includes(q)
    );
  }, [selectableVariants, dropdownSearch]);

  // Selected item object
  const selectedItem = useMemo(() => {
    return selectableVariants.find((item) => item.variant.sku === selectedSku);
  }, [selectableVariants, selectedSku]);

  // Outside click listener for custom dropdown
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsDropdownOpen(false);
      }
    };
    if (isDropdownOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isDropdownOpen]);

  // Reset and set initial SKU on open
  useEffect(() => {
    if (isOpen) {
      const targetSku = initialSku || (variants.length > 0 ? variants[0].sku : '');
      setSelectedSku(targetSku);
      setQuantity(1);
      setResult(null);
      setError(null);
      setIsDropdownOpen(false);
      setDropdownSearch('');
      if (targetSku) {
        checkStock(targetSku, 1);
      }
    }
  }, [isOpen, initialSku, variants]);

  const checkStock = async (sku: string, qty: number) => {
    if (!sku) return;
    setIsLoading(true);
    setError(null);
    try {
      const res = await catalogApi.checkAvailability(sku, Math.max(1, qty));
      setResult(res);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to check deal availability.');
      setResult(null);
    } finally {
      setIsLoading(false);
    }
  };

  const handleQtyChange = (newQty: number) => {
    const clamped = Math.max(1, newQty);
    setQuantity(clamped);
    if (selectedSku) {
      checkStock(selectedSku, clamped);
    }
  };

  const handleSelectSku = (sku: string) => {
    setSelectedSku(sku);
    setIsDropdownOpen(false);
    setDropdownSearch('');
    checkStock(sku, quantity);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4 animate-in fade-in duration-200">
      <div className="bg-card border border-border/80 rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="px-6 py-4 border-b border-border/60 flex items-center justify-between bg-muted/20">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
              <Zap className="w-4 h-4" />
            </div>
            <div>
              <h3 className="font-bold text-foreground text-sm">Check Deal Stock & Fulfillment</h3>
              <p className="text-xs text-muted-foreground">
                Instant multi-hub feasibility check for customer orders
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-4 overflow-y-auto">
          {/* SKU Selector (Custom Dropdown to avoid modal overflow) */}
          <div className="space-y-1.5" ref={dropdownRef}>
            <label className="block text-xs font-semibold text-foreground">
              Product & SKU
            </label>
            <div className="relative">
              <button
                type="button"
                onClick={() => setIsDropdownOpen(!isDropdownOpen)}
                className="w-full h-10 px-3.5 text-xs rounded-xl bg-background border border-border/80 text-foreground flex items-center justify-between hover:border-primary/50 transition-colors text-left cursor-pointer"
              >
                {selectedItem ? (
                  <div className="flex items-center gap-2 truncate pr-2">
                    <span className="font-semibold truncate">{selectedItem.productName}</span>
                    <span className="font-mono text-primary text-[11px] shrink-0">[{selectedItem.variant.sku}]</span>
                    {selectedItem.optionsLabel !== 'Standard' && (
                      <span className="text-muted-foreground text-[11px] truncate shrink-0">
                        ({selectedItem.optionsLabel})
                      </span>
                    )}
                  </div>
                ) : (
                  <span className="text-muted-foreground">Select product or variant...</span>
                )}
                <ChevronDown className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
              </button>

              {isDropdownOpen && (
                <div className="absolute left-0 right-0 top-full mt-1.5 bg-card border border-border/80 rounded-xl shadow-xl z-20 max-h-56 flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-150">
                  <div className="p-2 border-b border-border/60 bg-muted/30">
                    <div className="relative">
                      <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
                      <input
                        type="text"
                        value={dropdownSearch}
                        onChange={(e) => setDropdownSearch(e.target.value)}
                        placeholder="Search SKU, product name, or variant..."
                        className="w-full pl-8 pr-3 py-1.5 text-xs bg-background border border-border/60 rounded-lg text-foreground focus:outline-hidden focus:border-primary"
                        autoFocus
                      />
                    </div>
                  </div>
                  <div className="overflow-y-auto divide-y divide-border/30">
                    {filteredDropdownVariants.length === 0 ? (
                      <div className="p-4 text-center text-xs text-muted-foreground">
                        No products or SKUs matched your search
                      </div>
                    ) : (
                      filteredDropdownVariants.map((item) => (
                        <button
                          key={item.variant.id}
                          type="button"
                          onClick={() => handleSelectSku(item.variant.sku)}
                          className={`w-full p-2.5 text-left text-xs hover:bg-muted/50 transition-colors flex items-center justify-between cursor-pointer ${
                            item.variant.sku === selectedSku ? 'bg-primary/10 text-primary font-semibold' : ''
                          }`}
                        >
                          <div className="truncate pr-2">
                            <div className="truncate font-medium">{item.productName}</div>
                            <div className="text-[11px] text-muted-foreground flex items-center gap-1.5 font-mono">
                              <span>{item.variant.sku}</span>
                              {item.optionsLabel !== 'Standard' && (
                                <span>• {item.optionsLabel}</span>
                              )}
                            </div>
                          </div>
                          <span className="text-[10px] px-1.5 py-0.5 rounded font-mono font-bold bg-muted text-muted-foreground shrink-0">
                            {item.productType}
                          </span>
                        </button>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Quantity Input */}
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-foreground">
              Deal / Order Quantity Requested
            </label>
            <div className="flex items-center gap-3">
              <input
                type="number"
                min="1"
                value={quantity}
                onChange={(e) => handleQtyChange(parseInt(e.target.value) || 1)}
                className="w-32 h-10 px-3.5 text-xs font-mono font-bold rounded-xl bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40"
              />
              <div className="flex items-center gap-1.5">
                {[5, 10, 25, 50, 100].map((preset) => (
                  <button
                    key={preset}
                    type="button"
                    onClick={() => handleQtyChange(preset)}
                    className={`h-8 px-2.5 text-xs font-mono rounded-lg border transition-colors cursor-pointer ${
                      quantity === preset
                        ? 'border-primary bg-primary/10 text-primary font-bold'
                        : 'border-border/80 hover:bg-muted/60 text-muted-foreground hover:text-foreground'
                    }`}
                  >
                    {preset}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Loading Indicator */}
          {isLoading && (
            <div className="py-8 text-center space-y-2">
              <Loader2 className="w-6 h-6 animate-spin text-primary mx-auto" />
              <p className="text-xs text-muted-foreground">Checking inventory across all hubs...</p>
            </div>
          )}

          {/* Error Notice */}
          {error && (
            <div className="p-3 rounded-xl border border-destructive/40 bg-destructive/10 text-destructive text-xs flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* Feasibility Result */}
          {result && !isLoading && (
            <div className="space-y-3 pt-2">
              {/* Status Banner */}
              <div
                className={`p-4 rounded-xl border flex items-start gap-3 ${
                  result.can_fulfill
                    ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
                    : 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300'
                }`}
              >
                {result.can_fulfill ? (
                  <CheckCircle2 className="w-5 h-5 text-emerald-500 shrink-0 mt-0.5" />
                ) : (
                  <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
                )}
                <div>
                  <h4 className="font-bold text-xs">
                    {result.can_fulfill
                      ? 'Order Can Be Fulfilled!'
                      : 'Insufficient Inventory for Requested Quantity'}
                  </h4>
                  <p className="text-xs opacity-90 mt-0.5">
                    {result.can_fulfill
                      ? `All ${result.requested_qty} units can be fulfilled. Total available in network: ${result.total_available} units.`
                      : `You requested ${result.requested_qty} units, but only ${result.total_available} units are currently available.`}
                  </p>
                </div>
              </div>

              {/* Breakdown by Location */}
              <div className="space-y-1.5 pt-1">
                <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider block">
                  Stock Distribution by Hub
                </span>
                <div className="divide-y divide-border/40 border border-border/70 rounded-xl overflow-hidden bg-background">
                  {result.by_location.length === 0 ? (
                    <div className="p-4 text-center text-xs text-muted-foreground">
                      No locations configured yet.
                    </div>
                  ) : (
                    result.by_location.map((loc) => {
                      const hasStock = loc.qty_available > 0;
                      return (
                        <div
                          key={loc.location_id}
                          className="p-3 flex items-center justify-between text-xs hover:bg-muted/30 transition-colors"
                        >
                          <div className="flex items-center gap-2.5 min-w-0 pr-2">
                            <Building2
                              className={`w-4 h-4 shrink-0 ${
                                hasStock ? 'text-primary' : 'text-muted-foreground'
                              }`}
                            />
                            <div className="truncate">
                              <div className="font-semibold truncate text-foreground">
                                {loc.location_name}
                              </div>
                              <div className="text-[10px] text-muted-foreground font-mono">
                                Priority {loc.priority} {loc.sellable ? '• Sellable' : '• Non-sellable'}
                              </div>
                            </div>
                          </div>
                          <div className="text-right shrink-0">
                            <span
                              className={`font-mono font-bold text-xs px-2 py-0.5 rounded-full ${
                                hasStock
                                  ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                                  : 'bg-muted text-muted-foreground'
                              }`}
                            >
                              {loc.qty_available} available
                            </span>
                            <div className="text-[10px] text-muted-foreground font-mono mt-0.5">
                              ({loc.qty_on_hand} on hand)
                            </div>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3.5 border-t border-border/60 bg-muted/20 flex items-center justify-end">
          <button
            onClick={onClose}
            className="h-9 px-4 text-xs font-semibold rounded-xl bg-muted hover:bg-muted/80 text-foreground transition-colors cursor-pointer"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
};
