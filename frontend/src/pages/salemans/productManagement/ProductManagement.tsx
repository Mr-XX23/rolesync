import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Package,
  Plus,
  FileSpreadsheet,
  Building2,
  Layers,
  Warehouse,
  RotateCcw,
  AlertTriangle,
  Zap,
} from 'lucide-react';
import {
  catalogApi,
  type Product,
  type Category,
  type Location,
  type Variant,
  type VariantAvailabilityResponse,
} from '../../../api/catalogApi';
import { useToast } from '../../../context/ToastContext';
import { CatalogProductsTab } from './CatalogProductsTab';
import { InventoryMatrixTab } from './InventoryMatrixTab';
import { DealStockCheckModal } from './DealStockCheckModal';
import { ProductWizardModal } from './ProductWizardModal';
import { CsvImportModal } from './CsvImportModal';
import { ProductDetailModal } from './ProductDetailModal';
import { LocationsModal } from './LocationsModal';
import { AdjustStockModal } from './AdjustStockModal';
import { TransferStockModal } from './TransferStockModal';
import { DeleteProductModal } from './DeleteProductModal';

export const ProductManagement: React.FC = () => {
  const toast = useToast();

  // Active Tab (Clean 2-tab view)
  const [activeTab, setActiveTab] = useState<'catalog' | 'inventory'>('catalog');

  // Core Data States
  const [products, setProducts] = useState<Product[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [locations, setLocations] = useState<Location[]>([]);
  const [allVariants, setAllVariants] = useState<Variant[]>([]);
  const [availabilities, setAvailabilities] = useState<Record<string, VariantAvailabilityResponse>>({});
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);

  // Modals States
  const [isWizardOpen, setIsWizardOpen] = useState<boolean>(false);
  const [isCsvImportOpen, setIsCsvImportOpen] = useState<boolean>(false);
  const [isLocationsOpen, setIsLocationsOpen] = useState<boolean>(false);
  const [selectedProductId, setSelectedProductId] = useState<string | null>(null);
  const [deleteModalProduct, setDeleteModalProduct] = useState<Product | null>(null);

  // Stock Action Modals
  const [adjustStockTarget, setAdjustStockTarget] = useState<{
    isOpen: boolean;
    variantId?: string;
    locationId?: string;
  }>({ isOpen: false });

  const [transferStockTarget, setTransferStockTarget] = useState<{
    isOpen: boolean;
    sku?: string;
  }>({ isOpen: false });

  const [dealStockCheckTarget, setDealStockCheckTarget] = useState<{
    isOpen: boolean;
    sku?: string;
  }>({ isOpen: false });

  // Load All Catalog Data
  const loadCatalogData = useCallback(
    async (showToastNotice = false) => {
      try {
        const [prodsData, catsData, locsData] = await Promise.all([
          catalogApi.listProducts({ limit: 1000 }),
          catalogApi.listCategories(),
          catalogApi.listLocations(),
        ]);

        setProducts(prodsData);
        setCategories(catsData);
        setLocations(locsData);

        // Gather variants directly from product response or fallback to getProduct
        const gatheredVariants: Variant[] = [];
        const missingProductIds: string[] = [];

        prodsData.forEach((p) => {
          if (p.variants && p.variants.length > 0) {
            gatheredVariants.push(...p.variants);
          } else {
            missingProductIds.push(p.id);
          }
        });

        if (missingProductIds.length > 0 && gatheredVariants.length === 0) {
          const productDetails = await Promise.allSettled(
            missingProductIds.slice(0, 50).map((id) => catalogApi.getProduct(id))
          );
          productDetails.forEach((res) => {
            if (res.status === 'fulfilled' && res.value.variants) {
              gatheredVariants.push(...res.value.variants);
            }
          });
        }
        setAllVariants(gatheredVariants);

        // Fetch live availability for unique SKUs via single optimized batch call
        let availResults: Record<string, VariantAvailabilityResponse> = {};
        const uniqueSkus = Array.from(new Set(gatheredVariants.map((v) => v.sku)));
        if (uniqueSkus.length > 0) {
          try {
            availResults = await catalogApi.getBatchAvailability(uniqueSkus);
          } catch (batchErr) {
            console.warn('[ProductManagement] Batch availability fallback to individual queries:', batchErr);
            const fallbackPromises = await Promise.allSettled(
              uniqueSkus.slice(0, 50).map((sku) => catalogApi.getAvailability(sku))
            );
            fallbackPromises.forEach((res, i) => {
              if (res.status === 'fulfilled') {
                availResults[uniqueSkus[i]] = res.value;
              }
            });
          }
        }
        setAvailabilities(availResults);

        if (showToastNotice) {
          toast.success('Product catalog & inventory mesh synchronized.', 'Refreshed');
        }
      } catch (err) {
        console.error('[ProductManagement] Error loading catalog:', err);
        if (showToastNotice) {
          toast.error('Failed to synchronize catalog data.');
        }
      } finally {
        setIsLoading(false);
        setIsRefreshing(false);
      }
    },
    [toast]
  );

  useEffect(() => {
    loadCatalogData();
  }, [loadCatalogData]);

  // Compute Metrics
  const activeProductsCount = useMemo(
    () => products.filter((p) => p.status === 'ACTIVE').length,
    [products]
  );
  const draftProductsCount = useMemo(
    () => products.filter((p) => p.status === 'DRAFT').length,
    [products]
  );
  const retiredProductsCount = useMemo(
    () => products.filter((p) => p.status === 'RETIRED').length,
    [products]
  );

  const { totalInStockUnits, lowStockCount, outOfStockCount, productStockMap } = useMemo(() => {
    let inStock = 0;
    let low = 0;
    let oos = 0;
    const prodMap: Record<string, number> = {};

    allVariants.forEach((v) => {
      const av = availabilities[v.sku];
      const available = av?.total_available ?? 0;
      inStock += available;
      if (available === 0) {
        oos += 1;
        low += 1;
      } else if (available <= 5) {
        low += 1;
      }

      prodMap[v.product_id] = (prodMap[v.product_id] || 0) + available;
    });

    return {
      totalInStockUnits: inStock,
      lowStockCount: low,
      outOfStockCount: oos,
      productStockMap: prodMap,
    };
  }, [allVariants, availabilities]);

  const handleDeleteProduct = (product: Product) => {
    setDeleteModalProduct(product);
  };

  const handleConfirmRetire = async (product: Product) => {
    try {
      await catalogApi.deleteProduct(product.id, false, product.tenant_id);
      toast.success(`Product "${product.name}" soft-deleted (status set to RETIRED).`, 'Product Retired');
      loadCatalogData(false);
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Failed to retire product.';
      toast.error(msg, 'Error');
    }
  };

  const handleConfirmPermanentDelete = async (product: Product) => {
    try {
      await catalogApi.deleteProduct(product.id, true, product.tenant_id);
      toast.success(`Product "${product.name}" permanently deleted from database.`, 'Product Purged');
      loadCatalogData(false);
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Failed to permanently delete product.';
      toast.error(msg, 'Error');
    }
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-500 pb-20">
      {/* Page Header */}
      <section className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div className="space-y-2">
          <div className="flex items-center gap-2.5">
            <h2 className="font-serif text-3xl font-bold text-primary">
              Product & Service Management
            </h2>
          </div>
          <p className="text-sm text-muted-foreground max-w-2xl leading-relaxed">
            Manage physical products, retainers, dynamic variant matrices, and multi-location inventory ledgers. Configured with AI findability and pricing guardrails for autonomous sales agents.
          </p>
        </div>

        {/* Header Action Buttons */}
        <div className="flex flex-wrap items-center gap-2.5">
          <button
            onClick={() => {
              setIsRefreshing(true);
              loadCatalogData(true);
            }}
            disabled={isRefreshing}
            className="p-2.5 rounded-xl border border-border/80 hover:bg-muted/60 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
            title="Refresh Catalog Data"
          >
            <RotateCcw className={`w-4 h-4 ${isRefreshing ? 'animate-spin text-primary' : ''}`} />
          </button>

          <button
            onClick={() => setDealStockCheckTarget({ isOpen: true })}
            className="px-3.5 py-2 text-xs font-semibold rounded-xl border border-primary/40 bg-primary/10 hover:bg-primary/20 text-primary transition-colors flex items-center gap-2 cursor-pointer shadow-2xs"
            title="Check multi-hub stock availability and order feasibility"
          >
            <Zap className="w-4 h-4 text-primary" />
            Check Deal Stock
          </button>

          <button
            onClick={() => setIsLocationsOpen(true)}
            className="px-3.5 py-2 text-xs font-semibold rounded-xl border border-border/80 hover:bg-muted/60 text-foreground transition-colors flex items-center gap-2 cursor-pointer shadow-2xs"
          >
            <Building2 className="w-4 h-4 text-primary" />
            Locations ({locations.length})
          </button>

          <button
            onClick={() => setIsCsvImportOpen(true)}
            className="px-3.5 py-2 text-xs font-semibold rounded-xl border border-border/80 hover:bg-muted/60 text-foreground transition-colors flex items-center gap-2 cursor-pointer shadow-2xs"
          >
            <FileSpreadsheet className="w-4 h-4 text-primary" />
            Import CSV
          </button>

          <button
            onClick={() => setIsWizardOpen(true)}
            className="px-4 py-2 text-xs font-semibold rounded-xl bg-primary text-primary-foreground hover:opacity-95 active:scale-98 transition-all flex items-center gap-2 shadow-xs cursor-pointer"
          >
            <Plus className="w-4 h-4" />
            New Product
          </button>
        </div>
      </section>

      {/* Metric Cards: Total Products, Active SKUs, In-Stock Units, Low-Stock Alerts */}
      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Card 1: Total Products */}
        <div className="p-5 rounded-2xl border border-border/80 bg-card shadow-xs space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono font-bold uppercase tracking-wider text-muted-foreground">
              Total Products
            </span>
            <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
              <Package className="w-4 h-4" />
            </div>
          </div>
          <div className="text-2xl font-bold font-serif text-foreground">{products.length}</div>
          <div className="text-[11px] text-muted-foreground flex items-center gap-2">
            <span className="text-emerald-500 font-semibold">{activeProductsCount} Active</span>
            <span>•</span>
            <span className="text-amber-500 font-semibold">{draftProductsCount} Draft</span>
            {retiredProductsCount > 0 && (
              <>
                <span>•</span>
                <span className="text-slate-400 font-semibold">{retiredProductsCount} Retired</span>
              </>
            )}
          </div>
        </div>

        {/* Card 2: Active SKUs */}
        <div className="p-5 rounded-2xl border border-border/80 bg-card shadow-xs space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono font-bold uppercase tracking-wider text-muted-foreground">
              Active SKUs
            </span>
            <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
              <Layers className="w-4 h-4" />
            </div>
          </div>
          <div className="text-2xl font-bold font-serif text-foreground">{allVariants.length}</div>
          <div className="text-[11px] text-muted-foreground">
            {allVariants.filter((v) => v.status === 'ACTIVE').length} Active across {products.length} catalog items
          </div>
        </div>

        {/* Card 3: In-Stock Units */}
        <div className="p-5 rounded-2xl border border-border/80 bg-card shadow-xs space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono font-bold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
              In-Stock Units
            </span>
            <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-500">
              <Warehouse className="w-4 h-4" />
            </div>
          </div>
          <div className="text-2xl font-bold font-serif text-foreground">{totalInStockUnits}</div>
          <div className="text-[11px] text-muted-foreground">
            Sellable units across {locations.filter((l) => l.sellable).length} fulfillment hubs
          </div>
        </div>

        {/* Card 4: Low-Stock Alerts */}
        <div className="p-5 rounded-2xl border border-amber-500/30 bg-amber-500/5 shadow-xs space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono font-bold uppercase tracking-wider text-amber-500">
              Low-Stock Alerts
            </span>
            <div className="w-8 h-8 rounded-lg bg-amber-500/20 border border-amber-500/30 flex items-center justify-center text-amber-500">
              <AlertTriangle className="w-4 h-4" />
            </div>
          </div>
          <div className="text-2xl font-bold font-serif text-amber-500">{lowStockCount}</div>
          <div className="text-[11px] text-muted-foreground">
            <span className="text-destructive font-semibold">{outOfStockCount} Out of stock</span>
            {' • '}
            <span>{Math.max(0, lowStockCount - outOfStockCount)} Low stock</span>
          </div>
        </div>
      </section>

      {/* Main Tab Navigation */}
      <section className="space-y-6">
        <div className="flex items-center gap-2 border-b border-border/70 pb-px">
          <button
            onClick={() => setActiveTab('catalog')}
            className={`px-4 py-2.5 text-xs font-semibold rounded-t-xl transition-all flex items-center gap-2 cursor-pointer ${
              activeTab === 'catalog'
                ? 'bg-card border-t border-x border-border/80 text-primary shadow-xs font-bold'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted/40'
            }`}
          >
            <Package className="w-4 h-4" />
            Catalog & Products
            <span
              className={`text-[10px] font-mono px-1.5 py-0.2 rounded-full font-bold ${
                activeTab === 'catalog' ? 'bg-primary/20 text-primary' : 'bg-muted text-muted-foreground'
              }`}
            >
              {products.length}
            </span>
          </button>

          <button
            onClick={() => setActiveTab('inventory')}
            className={`px-4 py-2.5 text-xs font-semibold rounded-t-xl transition-all flex items-center gap-2 cursor-pointer ${
              activeTab === 'inventory'
                ? 'bg-card border-t border-x border-border/80 text-primary shadow-xs font-bold'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted/40'
            }`}
          >
            <Warehouse className="w-4 h-4" />
            Inventory Matrix
            <span
              className={`text-[10px] font-mono px-1.5 py-0.2 rounded-full font-bold ${
                activeTab === 'inventory' ? 'bg-primary/20 text-primary' : 'bg-muted text-muted-foreground'
              }`}
            >
              {allVariants.length}
            </span>
          </button>
        </div>

        {/* Tab Content Panes */}
        {activeTab === 'catalog' && (
          <CatalogProductsTab
            products={products}
            categories={categories}
            variants={allVariants}
            productStockMap={productStockMap}
            isLoading={isLoading}
            onOpenWizard={() => setIsWizardOpen(true)}
            onOpenCsvImport={() => setIsCsvImportOpen(true)}
            onSelectProduct={(id) => setSelectedProductId(id)}
            onDeleteProduct={handleDeleteProduct}
            onCheckStock={(sku) => setDealStockCheckTarget({ isOpen: true, sku })}
          />
        )}

        {activeTab === 'inventory' && (
          <InventoryMatrixTab
            products={products}
            variants={allVariants}
            locations={locations}
            parentAvailabilities={availabilities}
            onOpenAdjustStock={(variantId, locationId) =>
              setAdjustStockTarget({ isOpen: true, variantId, locationId })
            }
            onOpenTransferStock={(sku) => setTransferStockTarget({ isOpen: true, sku })}
            onOpenDealStockCheck={(sku) => setDealStockCheckTarget({ isOpen: true, sku })}
            onOpenLocations={() => setIsLocationsOpen(true)}
            onRefresh={() => loadCatalogData(true)}
          />
        )}
      </section>

      {/* Product Creation Wizard Modal */}
      <ProductWizardModal
        isOpen={isWizardOpen}
        onClose={() => setIsWizardOpen(false)}
        onProductCreated={() => loadCatalogData(true)}
        categories={categories}
        locations={locations}
      />

      {/* Bulk CSV Import Modal */}
      <CsvImportModal
        isOpen={isCsvImportOpen}
        onClose={() => {
          setIsCsvImportOpen(false);
          loadCatalogData(false);
        }}
        onImportCompleted={() => loadCatalogData(true)}
      />

      {/* Product Detail & Edit Modal */}
      <ProductDetailModal
        isOpen={Boolean(selectedProductId)}
        productId={selectedProductId}
        onClose={() => setSelectedProductId(null)}
        onProductUpdated={() => loadCatalogData(false)}
        categories={categories}
        locations={locations}
        onOpenAdjustStock={(variantId) => setAdjustStockTarget({ isOpen: true, variantId })}
      />

      {/* Locations Management Modal */}
      <LocationsModal
        isOpen={isLocationsOpen}
        onClose={() => setIsLocationsOpen(false)}
        locations={locations}
        onLocationsUpdated={() => loadCatalogData(false)}
      />

      {/* Quick Adjust Stock Modal */}
      <AdjustStockModal
        isOpen={adjustStockTarget.isOpen}
        onClose={() => setAdjustStockTarget({ isOpen: false })}
        onStockUpdated={() => loadCatalogData(false)}
        variants={allVariants}
        products={products}
        locations={locations}
        initialVariantId={adjustStockTarget.variantId}
        initialLocationId={adjustStockTarget.locationId}
      />

      {/* Transfer Stock Modal */}
      <TransferStockModal
        isOpen={transferStockTarget.isOpen}
        onClose={() => setTransferStockTarget({ isOpen: false })}
        onStockTransferred={() => loadCatalogData(false)}
        variants={allVariants}
        products={products}
        locations={locations}
        initialSku={transferStockTarget.sku}
      />

      {/* Deal Stock Check Modal */}
      <DealStockCheckModal
        isOpen={dealStockCheckTarget.isOpen}
        onClose={() => setDealStockCheckTarget({ isOpen: false })}
        variants={allVariants}
        products={products}
        initialSku={dealStockCheckTarget.sku}
      />


      {/* Delete / Retire Confirmation Modal */}
      <DeleteProductModal
        isOpen={Boolean(deleteModalProduct)}
        product={deleteModalProduct}
        onClose={() => setDeleteModalProduct(null)}
        onConfirmRetire={handleConfirmRetire}
        onConfirmPermanentDelete={handleConfirmPermanentDelete}
        variantCount={
          deleteModalProduct
            ? allVariants.filter((v) => v.product_id === deleteModalProduct.id).length
            : 0
        }
      />
    </div>
  );
};
