import React, { useState, useMemo, useEffect, useRef } from 'react';
import {
  Search,
  SlidersHorizontal,
  ArrowRightLeft,
  RotateCcw,
  Building2,
  Warehouse,
  Store,
  Truck,
  Lock,
  AlertTriangle,
  CheckCircle2,
  X,
  Layers,
  Table,
  Package,
  Boxes,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Filter,
  Zap,
} from 'lucide-react';
import {
  catalogApi,
  type Variant,
  type Location,
  type Product,
  type VariantAvailabilityResponse,
} from '../../../api/catalogApi';

interface InventoryMatrixTabProps {
  products: Product[];
  variants: Variant[];
  locations: Location[];
  parentAvailabilities?: Record<string, VariantAvailabilityResponse>;
  onOpenAdjustStock: (variantId?: string, locationId?: string) => void;
  onOpenTransferStock: (sku?: string) => void;
  onOpenDealStockCheck?: (sku?: string) => void;
  onOpenLocations?: () => void;
  onRefresh: () => void;
}

type ViewMode = 'MANAGED' | 'MATRIX';
type TypeFilter = 'ALL' | 'PRODUCT' | 'SERVICE';
type StockHealthFilter = 'ALL' | 'IN_STOCK' | 'LOW_STOCK' | 'OUT_OF_STOCK';

/* ─── Scalable Hub Distribution Cell (supports 100+ hubs cleanly) ─── */
interface HubDistributionCellProps {
  variantId: string;
  isService: boolean;
  locations: Location[];
  byLoc: { location_id: string; qty_on_hand: number; qty_reserved: number; qty_available: number }[];
  selectedLocation: Location | null;
  onOpenAdjustStock: (variantId?: string, locationId?: string) => void;
}

const HubDistributionCell: React.FC<HubDistributionCellProps> = ({
  variantId,
  isService,
  locations,
  byLoc,
  selectedLocation,
  onOpenAdjustStock,
}) => {
  const [open, setOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  // Digital services without physical warehouse footprints
  if (isService && byLoc.every((l) => l.qty_on_hand === 0)) {
    return (
      <span className="text-xs text-muted-foreground font-normal italic">
        Digital delivery (no hub stock)
      </span>
    );
  }

  // Filter hubs: show hubs with stock > 0, OR the currently selected filtered hub
  const activeHubs = locations
    .map((loc) => {
      const locData = byLoc.find((l) => l.location_id === loc.id);
      const qty = loc.sellable ? (locData?.qty_available ?? 0) : (locData?.qty_on_hand ?? 0);
      const reserved = locData?.qty_reserved ?? 0;
      return { loc, qty, reserved };
    })
    .filter((item) => item.qty > 0 || (selectedLocation && item.loc.id === selectedLocation.id));

  // If no hubs have stock
  if (activeHubs.length === 0) {
    return (
      <div className="flex items-center gap-1.5 text-xs">
        <span className="text-muted-foreground/80 italic">No stock in any hub</span>
        <button
          onClick={() => onOpenAdjustStock(variantId, selectedLocation?.id)}
          className="text-primary hover:underline font-semibold cursor-pointer text-[11px]"
        >
          • Add Stock
        </button>
      </div>
    );
  }

  // Always show the selected hub first if it's in the list, then sort by highest stock
  const sortedHubs = [...activeHubs].sort((a, b) => {
    if (selectedLocation) {
      if (a.loc.id === selectedLocation.id) return -1;
      if (b.loc.id === selectedLocation.id) return 1;
    }
    return b.qty - a.qty;
  });

  // Show top 2 hubs inline, bundle remaining into a dropdown
  const visibleHubs = sortedHubs.slice(0, 2);
  const hiddenHubs = sortedHubs.slice(2);

  return (
    <div className="relative inline-flex flex-wrap items-center gap-1.5" ref={popoverRef}>
      {visibleHubs.map(({ loc, qty, reserved }) => {
        const isSelectedLoc = selectedLocation && loc.id === selectedLocation.id;
        return (
          <button
            key={loc.id}
            onClick={() => onOpenAdjustStock(variantId, loc.id)}
            title={`Click to adjust stock at ${loc.name} (${qty} units)`}
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs transition-all cursor-pointer whitespace-nowrap ${
              isSelectedLoc
                ? 'border-primary ring-2 ring-primary/25 bg-primary/10 font-bold shadow-xs'
                : qty > 0
                ? 'border-border/80 bg-background hover:border-primary/50 hover:bg-primary/5 text-foreground'
                : 'border-border/40 bg-muted/20 text-muted-foreground/60 hover:text-muted-foreground'
            }`}
          >
            <span className={`truncate max-w-36 ${isSelectedLoc ? 'text-foreground font-semibold' : 'text-muted-foreground font-normal'}`}>
              {loc.name}
            </span>
            <span className="text-muted-foreground/30 font-normal">•</span>
            <span className={`font-semibold ${qty > 0 ? (isSelectedLoc ? 'text-primary' : 'text-foreground') : 'text-muted-foreground/50'}`}>
              {qty}
            </span>
            {reserved > 0 && (
              <span className="text-amber-500 font-medium text-[10px]" title={`${reserved} reserved`}>
                ({reserved}r)
              </span>
            )}
          </button>
        );
      })}

      {hiddenHubs.length > 0 && (
        <div className="relative inline-block">
          <button
            onClick={() => setOpen(!open)}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-border/80 bg-muted/40 hover:bg-muted text-foreground text-xs font-medium transition-colors cursor-pointer"
            title="View stock in remaining hubs"
          >
            <span>+{hiddenHubs.length} more</span>
            <ChevronDown className={`w-3 h-3 text-muted-foreground transition-transform ${open ? 'rotate-180' : ''}`} />
          </button>

          {open && (
            <div className="absolute left-0 top-full mt-1.5 z-50 w-64 bg-card border border-border/80 rounded-xl shadow-xl p-2 space-y-1 animate-in fade-in zoom-in-95 duration-150">
              <div className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground border-b border-border/50 flex items-center justify-between">
                <span>Other Hubs</span>
                <span>Stock</span>
              </div>
              <div className="max-h-48 overflow-y-auto space-y-1 pt-1">
                {hiddenHubs.map(({ loc, qty, reserved }) => (
                  <button
                    key={loc.id}
                    onClick={() => {
                      onOpenAdjustStock(variantId, loc.id);
                      setOpen(false);
                    }}
                    className="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg hover:bg-muted/60 text-xs transition-colors cursor-pointer text-left"
                    title={`Click to adjust stock at ${loc.name}`}
                  >
                    <span className="truncate text-foreground max-w-40 font-medium">{loc.name}</span>
                    <div className="flex items-center gap-1 shrink-0">
                      <span className="font-semibold text-foreground">{qty}</span>
                      {reserved > 0 && (
                        <span className="text-amber-500 text-[10px]">({reserved}r)</span>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export const InventoryMatrixTab: React.FC<InventoryMatrixTabProps> = ({
  products,
  variants,
  locations,
  parentAvailabilities,
  onOpenAdjustStock,
  onOpenTransferStock,
  onOpenDealStockCheck,
  onOpenLocations,
  onRefresh,
}) => {
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [selectedLocationFilter, setSelectedLocationFilter] = useState<string>('ALL');
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('ALL');
  const [healthFilter, setHealthFilter] = useState<StockHealthFilter>('ALL');
  const [viewMode, setViewMode] = useState<ViewMode>('MANAGED');
  const [currentPage, setCurrentPage] = useState<number>(1);
  const pageSize = 20;

  const [localAvailabilities, setLocalAvailabilities] = useState<Record<string, VariantAvailabilityResponse>>({});
  const [isLoadingAvailabilities, setIsLoadingAvailabilities] = useState<boolean>(false);

  // Map product by ID
  const productMap = useMemo(() => {
    const map: Record<string, Product> = {};
    for (const p of products) {
      map[p.id] = p;
    }
    return map;
  }, [products]);

  // Use parent availabilities if supplied, otherwise fallback to local
  const effectiveAvailabilities = useMemo(() => {
    if (parentAvailabilities && Object.keys(parentAvailabilities).length > 0) {
      return parentAvailabilities;
    }
    return localAvailabilities;
  }, [parentAvailabilities, localAvailabilities]);

  // Load live availability data for all variants if not provided by parent
  useEffect(() => {
    if (parentAvailabilities && Object.keys(parentAvailabilities).length > 0) {
      return;
    }
    if (variants.length === 0) return;

    let isMounted = true;
    const fetchAllAvailabilities = async () => {
      setIsLoadingAvailabilities(true);
      try {
        const skus = variants.map((v) => v.sku);
        const results = await catalogApi.getBatchAvailability(skus);
        if (isMounted) {
          setLocalAvailabilities(results);
        }
      } catch (err) {
        console.warn('[InventoryMatrixTab] Batch availability failed, falling back:', err);
        const results: Record<string, VariantAvailabilityResponse> = {};
        for (const v of variants.slice(0, 50)) {
          try {
            const avail = await catalogApi.getAvailability(v.sku);
            if (isMounted) {
              results[v.sku] = avail;
            }
          } catch {
            // ignore individual missing variants
          }
        }
        if (isMounted) {
          setLocalAvailabilities(results);
        }
      } finally {
        if (isMounted) {
          setIsLoadingAvailabilities(false);
        }
      }
    };

    fetchAllAvailabilities();

    return () => {
      isMounted = false;
    };
  }, [variants, parentAvailabilities]);

  // Dedicated Warehouse Metrics (per location)
  const warehouseMetrics = useMemo(() => {
    return locations.map((loc) => {
      let onHand = 0;
      let reserved = 0;
      let available = 0;
      let lowStockCount = 0;
      let outOfStockCount = 0;

      variants.forEach((v) => {
        const prod = productMap[v.product_id];
        // Physical goods typically matter most for physical hubs, but calculate for all
        if (typeFilter !== 'ALL' && prod && prod.type !== typeFilter) return;

        const av = effectiveAvailabilities[v.sku];
        const locItem = av?.by_location?.find((l) => l.location_id === loc.id);
        const locAvail = locItem?.qty_available || 0;
        const locOh = locItem?.qty_on_hand || 0;
        const locRes = locItem?.qty_reserved || 0;

        onHand += locOh;
        reserved += locRes;
        available += locAvail;

        if (locAvail <= 0) {
          outOfStockCount += 1;
        } else if (locAvail <= 5) {
          lowStockCount += 1;
        }
      });

      const utilizationRate = onHand > 0 ? Math.round((reserved / onHand) * 100) : 0;

      return {
        location: loc,
        onHand,
        reserved,
        available,
        lowStockCount,
        outOfStockCount,
        utilizationRate,
      };
    });
  }, [locations, variants, effectiveAvailabilities, productMap, typeFilter]);


  // Filter variants with search, item type, location, and health filters
  const filteredVariants = useMemo(() => {
    return variants.filter((v) => {
      const p = productMap[v.product_id];

      // Type Filter (Physical Goods vs Services)
      if (typeFilter !== 'ALL') {
        if (!p || p.type !== typeFilter) return false;
      }

      // Search Query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchSku = v.sku.toLowerCase().includes(q);
        const matchName = p?.name.toLowerCase().includes(q);
        const matchOptions = v.option_values.some((ov) => ov.value.toLowerCase().includes(q));
        if (!matchSku && !matchName && !matchOptions) return false;
      }

      const av = effectiveAvailabilities[v.sku];
      const totalAvail = av?.total_available ?? 0;

      // Location Filter: check if this SKU has stock at selected location
      if (selectedLocationFilter !== 'ALL') {
        const locItem = av?.by_location?.find((l) => l.location_id === selectedLocationFilter);
        const locAvail = locItem?.qty_available || 0;
        const locOh = locItem?.qty_on_hand || 0;

        if (healthFilter === 'IN_STOCK') {
          if (locAvail <= 0) return false;
        } else if (healthFilter === 'LOW_STOCK') {
          if (locAvail <= 0 || locAvail > 10) return false;
        } else if (healthFilter === 'OUT_OF_STOCK') {
          if (locOh > 0 || locAvail > 0) return false;
        } else {
          // healthFilter === 'ALL': show items present at this hub
          if (locOh <= 0 && locAvail <= 0) return false;
        }
      } else {
        // Overall Health Filter
        if (healthFilter === 'IN_STOCK' && totalAvail <= 0) return false;
        if (healthFilter === 'LOW_STOCK' && (totalAvail <= 0 || totalAvail > 10)) return false;
        if (healthFilter === 'OUT_OF_STOCK' && totalAvail > 0) return false;
      }

      return true;
    });
  }, [variants, searchQuery, productMap, typeFilter, healthFilter, selectedLocationFilter, effectiveAvailabilities]);

  // Reset pagination on filter changes
  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, typeFilter, healthFilter, selectedLocationFilter]);

  // Paginated variants
  const totalPages = Math.max(1, Math.ceil(filteredVariants.length / pageSize));
  const paginatedVariants = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredVariants.slice(start, start + pageSize);
  }, [filteredVariants, currentPage, pageSize]);

  // Locations to display for matrix view
  const displayLocations = useMemo(() => {
    if (selectedLocationFilter === 'ALL') return locations;
    return locations.filter((loc) => loc.id === selectedLocationFilter);
  }, [locations, selectedLocationFilter]);

  // Currently selected location object (if any)
  const selectedLocation = useMemo(() => {
    if (selectedLocationFilter === 'ALL') return null;
    return locations.find((l) => l.id === selectedLocationFilter) || null;
  }, [locations, selectedLocationFilter]);

  const getLocationIcon = (type: string) => {
    switch (type?.toUpperCase()) {
      case 'STORE':
      case 'RETAIL':
        return <Store className="w-3.5 h-3.5 text-blue-500" />;
      case 'SUPPLIER':
      case '3PL':
      case 'IN_TRANSIT':
        return <Truck className="w-3.5 h-3.5 text-purple-500" />;
      case 'WAREHOUSE':
      default:
        return <Warehouse className="w-3.5 h-3.5 text-primary" />;
    }
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      {/* Fulfillment Hubs Cards Section */}
      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3 px-1">
          <div className="flex items-center gap-2">
            <Building2 className="w-4 h-4 text-primary" />
            <h3 className="text-sm font-semibold text-foreground">
              Fulfillment Hubs & Stock Centers
            </h3>
          </div>

          {selectedLocationFilter !== 'ALL' && (
            <button
              onClick={() => setSelectedLocationFilter('ALL')}
              className="px-2.5 py-1 text-xs font-medium rounded-lg bg-primary/10 text-primary border border-primary/30 hover:bg-primary/20 transition-colors flex items-center gap-1.5 cursor-pointer"
            >
              <X className="w-3.5 h-3.5" />
              Reset Hub Filter
            </button>
          )}
        </div>

        {locations.length === 0 ? (
          <div className="p-8 rounded-2xl bg-card border border-dashed border-border text-center space-y-3 shadow-xs">
            <div className="w-12 h-12 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center mx-auto text-primary">
              <Building2 className="w-6 h-6" />
            </div>
            <div className="space-y-1">
              <h4 className="font-semibold text-base text-foreground">No Warehouses Configured</h4>
              <p className="text-xs text-muted-foreground max-w-md mx-auto">
                No stock locations are currently assigned to this workspace. Add warehouses, regional retail hubs, or 3PL facilities to begin tracking multi-point inventory.
              </p>
            </div>
            {onOpenLocations && (
              <button
                onClick={onOpenLocations}
                className="px-4 py-2 text-xs font-semibold rounded-xl bg-primary text-primary-foreground hover:opacity-95 shadow-xs cursor-pointer inline-flex items-center gap-2"
              >
                <Building2 className="w-3.5 h-3.5" />
                Configure Locations
              </button>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
            {warehouseMetrics.map((item) => {
              const loc = item.location;
              const isSelected = selectedLocationFilter === loc.id;
              const isOos = item.onHand === 0;
              const isHighAllocation = item.utilizationRate >= 30;

              return (
                <div
                  key={loc.id}
                  onClick={() => {
                    setSelectedLocationFilter((prev) => (prev === loc.id ? 'ALL' : loc.id));
                  }}
                  className={`p-4 rounded-xl border transition-all cursor-pointer shadow-xs flex flex-col justify-between gap-3 group ${
                    isSelected
                      ? 'border-primary ring-2 ring-primary/20 bg-primary/5'
                      : 'border-border/80 bg-card hover:border-border hover:bg-muted/30'
                  }`}
                  title={`Click to ${isSelected ? 'clear hub filter' : 'filter inventory to ' + loc.name}`}
                >
                  {/* Card Header: Name, Type, Priority */}
                  <div className="space-y-1">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                        {getLocationIcon(loc.type)}
                        <h4 className="font-semibold text-sm text-foreground truncate group-hover:text-primary transition-colors">
                          {loc.name}
                        </h4>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <span className="text-[11px] px-1.5 py-0.5 rounded-md bg-muted text-muted-foreground font-medium">
                          P{loc.priority}
                        </span>
                        {!loc.sellable ? (
                          <span
                            className="text-[10px] px-1.5 py-0.5 rounded-md bg-amber-500/10 text-amber-500 border border-amber-500/20 font-medium flex items-center gap-0.5"
                            title="Non-sellable facility (Quarantine/Internal)"
                          >
                            <Lock className="w-2.5 h-2.5" />
                            Internal
                          </span>
                        ) : (
                          <span className="text-[10px] px-1.5 py-0.5 rounded-md bg-emerald-500/10 text-emerald-500 border border-emerald-500/20 font-medium">
                            Sellable
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="text-xs text-muted-foreground flex items-center gap-1.5">
                      <span className="capitalize">{loc.type?.toLowerCase() || 'Facility'}</span>
                      {isSelected && (
                        <>
                          <span>•</span>
                          <span className="text-primary font-medium">Filtered</span>
                        </>
                      )}
                    </div>
                  </div>

                  {/* Main Metric Value: Available / On Hand */}
                  <div className="space-y-1.5 py-1">
                    <div className="flex items-baseline justify-between">
                      <span className="text-2xl font-bold tracking-tight text-foreground">
                        {loc.sellable ? item.available : item.onHand}
                      </span>
                      <span className="text-xs text-muted-foreground font-medium">
                        {loc.sellable ? 'sellable units' : 'internal units'}
                      </span>
                    </div>

                    <div className="flex items-center justify-between text-xs pt-1.5 border-t border-border/50 text-muted-foreground">
                      <span>{item.onHand} on-hand</span>
                      <span className={item.reserved > 0 ? 'text-amber-500 font-medium' : ''}>
                        {item.reserved} reserved {item.utilizationRate > 0 ? `(${item.utilizationRate}%)` : ''}
                      </span>
                    </div>
                  </div>

                  {/* Health Status Footer */}
                  <div className="pt-1 flex items-center justify-between text-xs">
                    {isOos ? (
                      <span className="text-muted-foreground flex items-center gap-1.5 font-medium">
                        <span className="w-2 h-2 rounded-full bg-muted-foreground/60"></span>
                        Depleted Depot
                      </span>
                    ) : item.outOfStockCount > 0 ? (
                      <span className="text-destructive flex items-center gap-1.5 font-medium">
                        <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                        {item.outOfStockCount} Out of Stock
                      </span>
                    ) : item.lowStockCount > 0 ? (
                      <span className="text-amber-500 flex items-center gap-1.5 font-medium">
                        <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                        {item.lowStockCount} Low Stock
                      </span>
                    ) : (
                      <span className="text-emerald-500 flex items-center gap-1.5 font-medium">
                        <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                        Stock Healthy
                      </span>
                    )}

                    {isHighAllocation && (
                      <span
                        className="text-[10px] px-1.5 py-0.5 rounded-md bg-amber-500/10 text-amber-500 border border-amber-500/30 font-medium"
                        title="High order commitment load at this location"
                      >
                        High Load
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Modern Control Toolbar with Filter Pills & View Mode Switcher */}
      <div className="p-4 rounded-2xl bg-card border border-border/80 shadow-xs space-y-3">
        <div className="flex flex-col lg:flex-row items-stretch lg:items-center justify-between gap-3">
          {/* Search bar - large and flexible to match CatalogProductsTab */}
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by SKU, product name, or variant..."
              className="w-full pl-10 pr-9 py-2.5 text-xs rounded-xl bg-background border border-border/80 text-foreground placeholder:text-muted-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40 h-10 shadow-xs"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 p-1 text-muted-foreground hover:text-foreground text-xs rounded-md"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          {/* Action and Utility Buttons - scaled proportionally to match input height */}
          <div className="flex items-center gap-2 flex-wrap">
            {/* View Mode Toggle */}
            <div className="flex items-center h-10 p-1 rounded-xl bg-muted/50 border border-border/60">
              <button
                onClick={() => setViewMode('MANAGED')}
                className={`h-full px-3.5 text-xs font-semibold rounded-lg transition-all flex items-center gap-1.5 cursor-pointer ${
                  viewMode === 'MANAGED'
                    ? 'bg-card text-foreground shadow-xs'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
                title="Managed Clean List with Location Badges"
              >
                <Layers className="w-3.5 h-3.5 text-primary" />
                Managed List
              </button>
              <button
                onClick={() => setViewMode('MATRIX')}
                className={`h-full px-3.5 text-xs font-semibold rounded-lg transition-all flex items-center gap-1.5 cursor-pointer ${
                  viewMode === 'MATRIX'
                    ? 'bg-card text-foreground shadow-xs'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
                title="Full Cross-Location Matrix Grid"
              >
                <Table className="w-3.5 h-3.5 text-primary" />
                Matrix Grid
              </button>
            </div>

            <button
              onClick={() => onOpenAdjustStock()}
              className="h-10 px-4 text-xs font-semibold rounded-xl bg-primary text-primary-foreground hover:opacity-95 shadow-xs flex items-center gap-2 cursor-pointer"
            >
              <SlidersHorizontal className="w-3.5 h-3.5" />
              Adjust Stock
            </button>
            <button
              onClick={() => onOpenTransferStock()}
              className="h-10 px-4 text-xs font-semibold rounded-xl border border-border/80 hover:bg-muted/60 text-foreground transition-colors flex items-center gap-2 cursor-pointer"
            >
              <ArrowRightLeft className="w-3.5 h-3.5 text-primary" />
              Transfer
            </button>
            {onOpenDealStockCheck && (
              <button
                onClick={() => onOpenDealStockCheck()}
                className="h-10 px-4 text-xs font-semibold rounded-xl border border-primary/30 text-primary hover:bg-primary/10 transition-colors flex items-center gap-2 cursor-pointer"
              >
                <Zap className="w-3.5 h-3.5 text-primary" />
                Check Deal Stock
              </button>
            )}
            <button
              onClick={onRefresh}
              className="h-10 w-10 flex items-center justify-center rounded-xl border border-border/80 hover:bg-muted text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
              title="Refresh Inventory"
            >
              <RotateCcw className={`w-4 h-4 ${isLoadingAvailabilities ? 'animate-spin text-primary' : ''}`} />
            </button>
          </div>
        </div>

        {/* Filter Pills Bar: Item Type & Stock Health & Active Hub */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-2.5 border-t border-border/50 text-xs">
          {/* Left: Type Filter Pills & Active Hub Tag */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-medium text-muted-foreground flex items-center gap-1 mr-1">
                <Filter className="w-3.5 h-3.5" /> Type:
              </span>
              <button
                onClick={() => setTypeFilter('ALL')}
                className={`px-3 py-1.5 rounded-xl font-medium transition-colors cursor-pointer ${
                  typeFilter === 'ALL'
                    ? 'bg-primary text-primary-foreground font-semibold shadow-xs'
                    : 'bg-muted/60 text-muted-foreground hover:text-foreground'
                }`}
              >
                All Items
              </button>
              <button
                onClick={() => setTypeFilter('PRODUCT')}
                className={`px-3 py-1.5 rounded-xl font-medium transition-colors cursor-pointer flex items-center gap-1.5 ${
                  typeFilter === 'PRODUCT'
                    ? 'bg-primary text-primary-foreground font-semibold shadow-xs'
                    : 'bg-muted/60 text-muted-foreground hover:text-foreground'
                }`}
              >
                <Package className="w-3.5 h-3.5" />
                Physical Goods
              </button>
              <button
                onClick={() => setTypeFilter('SERVICE')}
                className={`px-3 py-1.5 rounded-xl font-medium transition-colors cursor-pointer flex items-center gap-1.5 ${
                  typeFilter === 'SERVICE'
                    ? 'bg-primary text-primary-foreground font-semibold shadow-xs'
                    : 'bg-muted/60 text-muted-foreground hover:text-foreground'
                }`}
              >
                <Boxes className="w-3.5 h-3.5" />
                Digital & Services
              </button>
            </div>

            {selectedLocation && (
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-primary/10 border border-primary/30 text-primary text-xs font-medium">
                <Building2 className="w-3.5 h-3.5 shrink-0" />
                <span>Hub: <strong className="font-semibold">{selectedLocation.name}</strong></span>
                <button
                  onClick={() => setSelectedLocationFilter('ALL')}
                  className="p-0.5 hover:bg-primary/20 rounded-md transition-colors cursor-pointer ml-0.5"
                  title="Remove hub filter"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            )}
          </div>

          {/* Stock Health Filter Pills */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-medium text-muted-foreground mr-1">Stock Health:</span>
            <button
              onClick={() => setHealthFilter('ALL')}
              className={`px-3 py-1.5 rounded-xl font-medium transition-colors cursor-pointer ${
                healthFilter === 'ALL'
                  ? 'bg-muted font-bold text-foreground'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              All
            </button>
            <button
              onClick={() => setHealthFilter('IN_STOCK')}
              className={`px-3 py-1.5 rounded-xl font-medium transition-colors cursor-pointer flex items-center gap-1.5 ${
                healthFilter === 'IN_STOCK'
                  ? 'bg-emerald-500/15 text-emerald-600 font-bold border border-emerald-500/30'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
              In Stock
            </button>
            <button
              onClick={() => setHealthFilter('LOW_STOCK')}
              className={`px-3 py-1.5 rounded-xl font-medium transition-colors cursor-pointer flex items-center gap-1.5 ${
                healthFilter === 'LOW_STOCK'
                  ? 'bg-amber-500/15 text-amber-600 font-bold border border-amber-500/30'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-amber-500"></span>
              Low Stock (&le; 10)
            </button>
            <button
              onClick={() => setHealthFilter('OUT_OF_STOCK')}
              className={`px-3 py-1.5 rounded-xl font-medium transition-colors cursor-pointer flex items-center gap-1.5 ${
                healthFilter === 'OUT_OF_STOCK'
                  ? 'bg-destructive/15 text-destructive font-bold border border-destructive/30'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-destructive"></span>
              Out of Stock
            </button>
          </div>
        </div>
      </div>

      {/* Main Content: MANAGED VIEW or MATRIX GRID */}
      {viewMode === 'MANAGED' ? (
        /* ================== MANAGED LIST VIEW ================== */
        <div className="rounded-2xl border border-border/80 bg-card overflow-hidden shadow-xs">
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left border-collapse">
              <thead className="bg-muted text-muted-foreground uppercase text-[10px] tracking-wider border-b border-border">
                <tr>
                  <th className="px-4 py-3 min-w-56 font-semibold">SKU & Item Details</th>
                  <th className="px-3 py-3 min-w-24 font-semibold text-center">Type</th>
                  <th className="px-3 py-3 min-w-24 text-right font-semibold">Unit Price</th>
                  <th className="px-3 py-3 min-w-28 text-center font-semibold text-primary">
                    {selectedLocation ? 'Hub Stock' : 'Available Stock'}
                  </th>
                  <th className="px-4 py-3 min-w-72 font-semibold">Hub Distribution</th>
                  <th className="px-4 py-3 min-w-44 text-right font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {paginatedVariants.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="py-16 text-center text-xs text-muted-foreground space-y-2">
                      <Package className="w-8 h-8 mx-auto text-muted-foreground/40" />
                      <p>
                        {selectedLocation
                          ? `No inventory items found at ${selectedLocation.name} matching criteria.`
                          : 'No inventory items match the selected filters or search query.'}
                      </p>
                      <div className="flex items-center justify-center gap-2 pt-1">
                        {selectedLocation && (
                          <button
                            onClick={() => onOpenAdjustStock(undefined, selectedLocation.id)}
                            className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-primary text-primary-foreground hover:opacity-95 shadow-xs cursor-pointer"
                          >
                            Add Stock to {selectedLocation.name}
                          </button>
                        )}
                        {(typeFilter !== 'ALL' || healthFilter !== 'ALL' || selectedLocationFilter !== 'ALL' || searchQuery) && (
                          <button
                            onClick={() => {
                              setTypeFilter('ALL');
                              setHealthFilter('ALL');
                              setSelectedLocationFilter('ALL');
                              setSearchQuery('');
                            }}
                            className="px-3 py-1.5 text-xs font-semibold text-primary hover:underline cursor-pointer"
                          >
                            Clear all filters
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ) : (
                  paginatedVariants.map((variant) => {
                    const product = productMap[variant.product_id];
                    const avail = effectiveAvailabilities[variant.sku];
                    const totalAvail = avail?.total_available ?? 0;
                    const byLoc = avail?.by_location || [];
                    const isService = product?.type === 'SERVICE';

                    const locItem = avail?.by_location?.find((l) => l.location_id === selectedLocationFilter);
                    const locAvail = locItem?.qty_available ?? 0;
                    const locOh = locItem?.qty_on_hand ?? 0;
                    const displayAvail = selectedLocation
                      ? (selectedLocation.sellable ? locAvail : locOh)
                      : totalAvail;

                    return (
                      <tr key={variant.id} className="hover:bg-muted/20 transition-colors group">
                        {/* Item Details */}
                        <td className="px-4 py-3.5">
                          <div className="font-semibold text-foreground text-xs">
                            {variant.sku}
                          </div>
                          <div className="text-xs text-muted-foreground truncate max-w-sm mt-0.5">
                            {product?.name || 'Product'} •{' '}
                            {variant.option_values.map((ov) => ov.value).join(', ') || 'Default'}
                          </div>
                        </td>

                        {/* Type Badge - perfectly centered */}
                        <td className="px-3 py-3.5 text-center">
                          <div className="flex items-center justify-center">
                            {isService ? (
                              <span className="inline-flex items-center justify-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full bg-purple-500/10 text-purple-600 border border-purple-500/20 leading-none">
                                <Boxes className="w-3.5 h-3.5 shrink-0" />
                                <span className="translate-y-px">Service</span>
                              </span>
                            ) : (
                              <span className="inline-flex items-center justify-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full bg-blue-500/10 text-blue-600 border border-blue-500/20 leading-none">
                                <Package className="w-3.5 h-3.5 shrink-0" />
                                <span className="translate-y-px">Physical</span>
                              </span>
                            )}
                          </div>
                        </td>

                        {/* Unit Price */}
                        <td className="px-3 py-3.5 font-semibold text-foreground text-right text-xs">
                          ${Number(variant.price).toFixed(2)}
                        </td>

                        {/* Available Stock Pill - only current stock, no other hub counts */}
                        <td className="px-3 py-3.5 text-center whitespace-nowrap">
                          <span
                            className={`inline-block text-xs font-semibold px-2.5 py-1 rounded-lg border ${
                              displayAvail > 10
                                ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20'
                                : displayAvail > 0
                                ? 'bg-amber-500/10 text-amber-500 border-amber-500/20'
                                : 'bg-destructive/10 text-destructive border-destructive/20'
                            }`}
                          >
                            {displayAvail} units
                          </span>
                        </td>

                        {/* Location Distribution Chips - scalable for 100+ hubs */}
                        <td className="px-4 py-3.5">
                          <HubDistributionCell
                            variantId={variant.id}
                            isService={isService}
                            locations={locations}
                            byLoc={byLoc}
                            selectedLocation={selectedLocation}
                            onOpenAdjustStock={onOpenAdjustStock}
                          />
                        </td>

                        {/* Row Quick Actions */}
                        <td className="px-4 py-3.5 text-right whitespace-nowrap">
                          <div className="inline-flex items-center justify-end gap-2">
                            <button
                              onClick={() => onOpenAdjustStock(variant.id, selectedLocation?.id)}
                              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border/80 bg-background hover:bg-muted text-foreground text-xs font-semibold transition-colors cursor-pointer whitespace-nowrap h-8"
                              title="Adjust stock for this SKU"
                            >
                              <SlidersHorizontal className="w-3.5 h-3.5 text-muted-foreground" />
                              Adjust
                            </button>
                            <button
                              onClick={() => onOpenTransferStock(variant.sku)}
                              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-primary/30 bg-primary/5 hover:bg-primary/15 text-primary text-xs font-semibold transition-colors cursor-pointer whitespace-nowrap h-8"
                              title="Transfer stock between warehouses"
                            >
                              <ArrowRightLeft className="w-3.5 h-3.5" />
                              Transfer
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* Clean Pagination Footer */}
          <div className="p-3.5 border-t border-border flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-muted-foreground">
            <div>
              Showing <span className="font-semibold text-foreground">{paginatedVariants.length}</span> of{' '}
              <span className="font-semibold text-foreground">{filteredVariants.length}</span> matching variants (Total {variants.length})
            </div>

            <div className="flex items-center gap-2">
              <span className="text-xs font-medium mr-2">
                Page {currentPage} of {totalPages}
              </span>
              <button
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={currentPage <= 1}
                className="p-1.5 rounded-lg border border-border/80 bg-background hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
                title="Previous Page"
              >
                <ChevronLeft className="w-4 h-4 text-foreground" />
              </button>
              <button
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                disabled={currentPage >= totalPages}
                className="p-1.5 rounded-lg border border-border/80 bg-background hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
                title="Next Page"
              >
                <ChevronRight className="w-4 h-4 text-foreground" />
              </button>
            </div>
          </div>
        </div>
      ) : (
        /* ================== MATRIX GRID VIEW ================== */
        <div className="rounded-2xl border border-border/80 bg-card overflow-hidden shadow-xs">
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left border-collapse">
              <thead className="bg-muted text-muted-foreground uppercase text-[11px] font-semibold tracking-wider border-b border-border">
                <tr>
                  <th className="px-4 py-3.5 min-w-60">
                    Variant SKU & Product
                  </th>
                  <th className="px-3 py-3.5 min-w-28 text-right">Price (USD)</th>
                  <th className="px-3 py-3.5 min-w-32 text-center font-bold text-primary">
                    {selectedLocation ? `${selectedLocation.name} Avail` : 'Total Available'}
                  </th>
                  {displayLocations.map((loc) => (
                    <th key={loc.id} className="px-4 py-3.5 min-w-44 text-center">
                      <div className="font-semibold text-foreground text-xs truncate flex items-center justify-center gap-1.5">
                        {getLocationIcon(loc.type)}
                        <span>{loc.name}</span>
                      </div>
                      <div className="text-[11px] font-medium text-muted-foreground normal-case mt-0.5">
                        <span className="capitalize">{loc.type?.toLowerCase()}</span> • P{loc.priority}
                        {loc.sellable ? ' (Sellable)' : ' (Internal)'}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {paginatedVariants.length === 0 ? (
                  <tr>
                    <td
                      colSpan={3 + Math.max(1, displayLocations.length)}
                      className="py-16 text-center text-xs text-muted-foreground space-y-2"
                    >
                      <p>
                        {selectedLocation
                          ? `No variants stocked at ${selectedLocation.name} matching criteria.`
                          : 'No variants found matching criteria.'}
                      </p>
                      {selectedLocation && (
                        <button
                          onClick={() => setSelectedLocationFilter('ALL')}
                          className="text-xs font-semibold text-primary hover:underline cursor-pointer"
                        >
                          View all hubs
                        </button>
                      )}
                    </td>
                  </tr>
                ) : displayLocations.length === 0 ? (
                  <tr>
                    <td
                      colSpan={3}
                      className="py-16 text-center text-xs text-muted-foreground"
                    >
                      No warehouse locations available to display.
                    </td>
                  </tr>
                ) : (
                  paginatedVariants.map((variant) => {
                    const product = productMap[variant.product_id];
                    const avail = effectiveAvailabilities[variant.sku];
                    const totalAvail = avail?.total_available ?? 0;
                    const locMap: Record<string, { onHand: number; reserved: number; available: number }> = {};
                    avail?.by_location?.forEach((l) => {
                      locMap[l.location_id] = {
                        onHand: l.qty_on_hand,
                        reserved: l.qty_reserved,
                        available: l.qty_available,
                      };
                    });

                    const locData = selectedLocation ? locMap[selectedLocation.id] : null;
                    const displayAvail = selectedLocation
                      ? (selectedLocation.sellable ? (locData?.available ?? 0) : (locData?.onHand ?? 0))
                      : totalAvail;

                    return (
                      <tr key={variant.id} className="hover:bg-muted/15 transition-colors group">
                        <td className="px-4 py-3.5">
                          <div className="font-semibold text-foreground text-xs">
                            {variant.sku}
                          </div>
                          <div className="text-xs text-muted-foreground truncate max-w-xs mt-0.5">
                            {product?.name || 'Product'} •{' '}
                            {variant.option_values.map((ov) => ov.value).join(', ') || 'Default'}
                          </div>
                        </td>

                        <td className="px-3 py-3.5 font-semibold text-foreground text-right text-xs">
                          ${Number(variant.price).toFixed(2)}
                        </td>

                        <td className="px-3 py-3.5 text-center">
                          <span
                            className={`inline-block text-xs font-semibold px-2.5 py-1 rounded-lg border ${
                              displayAvail > 10
                                ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20'
                                : displayAvail > 0
                                ? 'bg-amber-500/10 text-amber-500 border-amber-500/20'
                                : 'bg-destructive/10 text-destructive border-destructive/20'
                            }`}
                          >
                            {displayAvail} units
                          </span>
                        </td>

                        {displayLocations.map((loc) => {
                          const locData = locMap[loc.id] || { onHand: 0, reserved: 0, available: 0 };
                          const isOos = locData.available <= 0;
                          const isLow = locData.available > 0 && locData.available <= 10;

                          return (
                            <td
                              key={loc.id}
                              className="px-3 py-3 text-center cursor-pointer hover:bg-muted/40 transition-colors"
                              onClick={() => onOpenAdjustStock(variant.id, loc.id)}
                              title={`Click to adjust stock for ${variant.sku} at ${loc.name}`}
                            >
                              <div className="inline-flex flex-col items-center">
                                {loc.sellable ? (
                                  <span
                                    className={`text-xs font-semibold px-2 py-0.5 rounded-md ${
                                      locData.available > 10
                                        ? 'text-emerald-500'
                                        : isLow
                                        ? 'text-amber-500'
                                        : isOos
                                        ? 'text-destructive/80'
                                        : 'text-muted-foreground'
                                    }`}
                                  >
                                    {locData.available} avail
                                  </span>
                                ) : (
                                  <span className="text-xs font-semibold px-2 py-0.5 rounded-md text-slate-400 bg-muted/60">
                                    {locData.onHand} internal
                                  </span>
                                )}
                                <div className="text-[11px] text-muted-foreground flex items-center gap-1 mt-0.5 font-medium">
                                  <span>{locData.onHand} on-hand</span>
                                  {locData.reserved > 0 && (
                                    <span className="text-amber-500">
                                      • {locData.reserved} res
                                    </span>
                                  )}
                                </div>
                              </div>
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* Matrix View Pagination */}
          <div className="p-3.5 border-t border-border flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-muted-foreground">
            <div>
              Showing <span className="font-semibold text-foreground">{paginatedVariants.length}</span> of{' '}
              <span className="font-semibold text-foreground">{filteredVariants.length}</span> variants
            </div>

            <div className="flex items-center gap-2">
              <span className="text-xs font-medium mr-2">
                Page {currentPage} of {totalPages}
              </span>
              <button
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={currentPage <= 1}
                className="p-1.5 rounded-lg border border-border/80 bg-background hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
                title="Previous Page"
              >
                <ChevronLeft className="w-4 h-4 text-foreground" />
              </button>
              <button
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                disabled={currentPage >= totalPages}
                className="p-1.5 rounded-lg border border-border/80 bg-background hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
                title="Next Page"
              >
                <ChevronRight className="w-4 h-4 text-foreground" />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

