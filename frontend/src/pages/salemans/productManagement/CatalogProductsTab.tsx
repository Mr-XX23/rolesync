import React, { useState, useMemo, useEffect, useRef } from 'react';
import {
  Search,
  LayoutGrid,
  Table as TableIcon,
  Package,
  ChevronRight,
  ChevronLeft,
  ChevronsLeft,
  ChevronsRight,
  Plus,
  Trash2,
  Sparkles,
  Zap,
  Loader2,
} from 'lucide-react';
import {
  catalogApi,
  type Product,
  type Category,
  type Variant,
} from '../../../api/catalogApi';

interface CatalogProductsTabProps {
  products: Product[];
  categories: Category[];
  variants: Variant[];
  productStockMap?: Record<string, number>;
  isLoading: boolean;
  onOpenWizard: () => void;
  onOpenCsvImport: () => void;
  onSelectProduct: (productId: string) => void;
  onDeleteProduct?: (product: Product) => void;
  onCheckStock: (sku: string) => void;
}

export const CatalogProductsTab: React.FC<CatalogProductsTabProps> = ({
  products,
  categories,
  variants,
  productStockMap,
  isLoading,
  onOpenWizard,
  onOpenCsvImport,
  onSelectProduct,
  onDeleteProduct,
  onCheckStock,
}) => {
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [categoryFilter, setCategoryFilter] = useState<string>('ALL');
  const [typeFilter, setTypeFilter] = useState<string>('ALL');
  const [statusFilter, setStatusFilter] = useState<string>('ALL');
  const [inStockOnly, setInStockOnly] = useState<boolean>(false);
  const [viewMode, setViewMode] = useState<'grid' | 'table'>('table');

  // AI Semantic Search State
  const [isAiSearching, setIsAiSearching] = useState<boolean>(false);
  const [aiExpandedTerms, setAiExpandedTerms] = useState<string[]>([]);

  // Pagination State (60 products per page)
  const ITEMS_PER_PAGE = 60;
  const [currentPage, setCurrentPage] = useState<number>(1);
  const tableContainerRef = useRef<HTMLDivElement>(null);

  // Variant lookup by product
  const variantsByProduct = useMemo(() => {
    const map: Record<string, Variant[]> = {};
    for (const v of variants) {
      if (!map[v.product_id]) map[v.product_id] = [];
      map[v.product_id].push(v);
    }
    return map;
  }, [variants]);

  // OpenRouter Semantic Search Trigger
  const handleTriggerAiSearch = async () => {
    if (!searchQuery.trim()) return;
    setIsAiSearching(true);
    try {
      const res = await catalogApi.semanticSearch({ query: searchQuery.trim(), limit: 30 });
      if (res.expanded_terms && res.expanded_terms.length > 0) {
        setAiExpandedTerms(res.expanded_terms);
      }
    } catch (err) {
      console.warn('AI semantic search fallback:', err);
    } finally {
      setIsAiSearching(false);
    }
  };

  // Multi-token relevance scoring & matched terms for smart search
  const smartSearchScores = useMemo(() => {
    if (!searchQuery.trim() && aiExpandedTerms.length === 0) {
      return new Map<string, { score: number; matchedTerms: string[] }>();
    }

    const queryTokens = searchQuery
      .toLowerCase()
      .split(/[\s,.;:!?\-\_]+/)
      .filter((t) => t.length > 1);

    const allTokens = Array.from(new Set([...queryTokens, ...aiExpandedTerms.map((t) => t.toLowerCase())]));
    const scores = new Map<string, { score: number; matchedTerms: string[] }>();
    const fullQueryLower = searchQuery.toLowerCase().trim();

    for (const prod of products) {
      let score = 0;
      const matchedTerms: string[] = [];
      const nameLower = prod.name.toLowerCase();
      const descLower = (prod.description || '').toLowerCase();
      const catLower = prod.category.toLowerCase();
      const subcatLower = (prod.subcategory || '').toLowerCase();
      const valPropLower = (prod.value_proposition || '').toLowerCase();
      const keywordsLower = prod.keywords?.map((k) => k.toLowerCase()) || [];
      const useCasesLower = prod.use_cases?.map((u) => u.toLowerCase()) || [];
      const industriesLower = prod.target_industries?.map((i) => i.toLowerCase()) || [];
      const prodVariants = variantsByProduct[prod.id] || [];
      const skusLower = prodVariants.map((v) => v.sku.toLowerCase());

      if (fullQueryLower && nameLower.includes(fullQueryLower)) {
        score += 30;
        matchedTerms.push(prod.name);
      }
      for (const sku of skusLower) {
        if (fullQueryLower && sku.includes(fullQueryLower)) {
          score += 35;
          matchedTerms.push(sku);
        }
      }

      for (const token of allTokens) {
        if (nameLower.includes(token)) {
          score += 15;
          matchedTerms.push(token);
        }
        for (const sku of skusLower) {
          if (sku.includes(token)) {
            score += 15;
            matchedTerms.push(sku);
          }
        }
        if (catLower.includes(token) || subcatLower.includes(token)) {
          score += 10;
          matchedTerms.push(prod.category);
        }
        for (const kw of keywordsLower) {
          if (kw.includes(token)) {
            score += 10;
            matchedTerms.push(kw);
          }
        }
        for (const uc of useCasesLower) {
          if (uc.includes(token)) {
            score += 12;
            matchedTerms.push(uc);
          }
        }
        if (valPropLower.includes(token)) {
          score += 8;
          matchedTerms.push('value prop');
        }
        for (const ind of industriesLower) {
          if (ind.includes(token)) {
            score += 6;
            matchedTerms.push(ind);
          }
        }
        if (descLower.includes(token)) {
          score += 4;
        }
      }

      if (score > 0) {
        scores.set(prod.id, {
          score,
          matchedTerms: Array.from(new Set(matchedTerms)).slice(0, 3),
        });
      }
    }

    return scores;
  }, [searchQuery, aiExpandedTerms, products, variantsByProduct]);

  // Filtered & Relevance Ranked Products
  const filteredProducts = useMemo(() => {
    const hasSearch = Boolean(searchQuery.trim() || aiExpandedTerms.length > 0);

    const matches = products.filter((prod) => {
      // Status filter
      if (statusFilter !== 'ALL' && prod.status !== statusFilter) {
        return false;
      }
      // Type filter
      if (typeFilter !== 'ALL' && prod.type !== typeFilter) {
        return false;
      }
      // Category filter
      if (categoryFilter !== 'ALL' && prod.category !== categoryFilter) {
        return false;
      }

      // Smart Search filter
      if (hasSearch && !smartSearchScores.has(prod.id)) {
        return false;
      }

      // In-stock only filter
      if (inStockOnly) {
        if (productStockMap && productStockMap[prod.id] !== undefined) {
          if (productStockMap[prod.id] <= 0) return false;
        } else {
          const prodVariants = variantsByProduct[prod.id] || [];
          if (prodVariants.length === 0) return false;
        }
      }

      return true;
    });

    if (hasSearch) {
      return matches.sort((a, b) => {
        const scoreA = smartSearchScores.get(a.id)?.score || 0;
        const scoreB = smartSearchScores.get(b.id)?.score || 0;
        return scoreB - scoreA;
      });
    }

    return matches;
  }, [products, categoryFilter, typeFilter, statusFilter, searchQuery, aiExpandedTerms, smartSearchScores, inStockOnly, variantsByProduct, productStockMap]);

  // Pagination Computations & Edge Cases
  const totalPages = Math.max(1, Math.ceil(filteredProducts.length / ITEMS_PER_PAGE));

  // Reset to page 1 whenever any filter or search changes
  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, categoryFilter, typeFilter, statusFilter, inStockOnly]);

  // Clamp current page if total pages decreases below current page
  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
  }, [currentPage, totalPages]);

  // Paginated slice for current page (60 items max)
  const paginatedProducts = useMemo(() => {
    const startIndex = (currentPage - 1) * ITEMS_PER_PAGE;
    return filteredProducts.slice(startIndex, startIndex + ITEMS_PER_PAGE);
  }, [filteredProducts, currentPage]);

  const handlePageChange = (newPage: number) => {
    const targetPage = Math.max(1, Math.min(newPage, totalPages));
    setCurrentPage(targetPage);
    if (tableContainerRef.current) {
      tableContainerRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  const getPageNumbers = (current: number, total: number): (number | string)[] => {
    if (total <= 7) {
      return Array.from({ length: total }, (_, i) => i + 1);
    }
    if (current <= 4) {
      return [1, 2, 3, 4, 5, '...', total];
    }
    if (current >= total - 3) {
      return [1, '...', total - 4, total - 3, total - 2, total - 1, total];
    }
    return [1, '...', current - 1, current, current + 1, '...', total];
  };

  return (
    <div ref={tableContainerRef} className="space-y-6 animate-in fade-in duration-300">
      {/* Search & Filter Toolbar */}
      <div className="p-4 rounded-2xl bg-card border border-border/80 shadow-xs space-y-3">
        <div className="flex flex-col md:flex-row items-stretch md:items-center gap-3">
          {/* Search Input - large, comfortable h-10 with AI assist */}
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                if (!e.target.value) setAiExpandedTerms([]);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleTriggerAiSearch();
              }}
              placeholder="Natural search by name, SKU, keywords, pain points, or customer prompts..."
              className="w-full pl-10 pr-24 py-2.5 text-xs rounded-xl bg-background border border-border/80 text-foreground placeholder:text-muted-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40 h-10 shadow-xs"
            />
            <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => {
                    setSearchQuery('');
                    setAiExpandedTerms([]);
                  }}
                  className="p-1 text-muted-foreground hover:text-foreground text-xs rounded-md cursor-pointer"
                  title="Clear Search"
                >
                  &times;
                </button>
              )}
              <button
                type="button"
                onClick={handleTriggerAiSearch}
                disabled={!searchQuery.trim() || isAiSearching}
                className="h-7 px-2 text-[11px] font-semibold rounded-lg bg-primary/10 hover:bg-primary/20 text-primary border border-primary/20 flex items-center gap-1 cursor-pointer disabled:opacity-30 transition-colors"
                title="AI Smart Search via OpenRouter (Expands synonyms & customer intent)"
              >
                {isAiSearching ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <Sparkles className="w-3 h-3 text-primary" />
                )}
                AI Match
              </button>
            </div>
          </div>

          {/* Filters - scaled to h-10 with proportional padding */}
          <div className="flex flex-wrap items-center gap-2">
            {/* Category Dropdown */}
            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              className="h-10 px-3.5 text-xs rounded-xl bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40 font-medium cursor-pointer shadow-xs"
            >
              <option value="ALL">All Categories</option>
              {categories.map((c) => (
                <option key={c.id} value={c.key}>
                  {c.label}
                </option>
              ))}
            </select>

            {/* Type Dropdown */}
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="h-10 px-3.5 text-xs rounded-xl bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40 font-medium cursor-pointer shadow-xs"
            >
              <option value="ALL">All Types</option>
              <option value="PRODUCT">PRODUCT</option>
              <option value="SERVICE">SERVICE</option>
            </select>

            {/* Status Dropdown */}
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="h-10 px-3.5 text-xs rounded-xl bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40 font-medium cursor-pointer shadow-xs"
            >
              <option value="ALL">All Statuses</option>
              <option value="ACTIVE">ACTIVE</option>
              <option value="DRAFT">DRAFT</option>
              <option value="RETIRED">RETIRED</option>
            </select>

            {/* In-Stock Only Toggle */}
            <button
              type="button"
              onClick={() => setInStockOnly(!inStockOnly)}
              className={`h-10 px-3.5 text-xs rounded-xl border transition-colors font-medium flex items-center gap-2 cursor-pointer shadow-xs ${
                inStockOnly
                  ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30'
                  : 'bg-background border-border/80 text-muted-foreground hover:text-foreground'
              }`}
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  inStockOnly ? 'bg-emerald-500' : 'bg-muted-foreground/40'
                }`}
              />
              In-Stock Only
            </button>

            {/* View Mode Toggle */}
            <div className="flex h-10 p-1 items-center rounded-xl bg-muted/50 border border-border/60 ml-auto">
              <button
                onClick={() => setViewMode('grid')}
                className={`h-full px-2.5 rounded-lg flex items-center justify-center transition-colors cursor-pointer ${
                  viewMode === 'grid'
                    ? 'bg-card text-foreground shadow-2xs'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
                title="Grid Card View"
              >
                <LayoutGrid className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => setViewMode('table')}
                className={`h-full px-2.5 rounded-lg flex items-center justify-center transition-colors cursor-pointer ${
                  viewMode === 'table'
                    ? 'bg-card text-foreground shadow-2xs'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
                title="Data Table View"
              >
                <TableIcon className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>

        {/* AI Semantic Expanded Terms Strip */}
        {aiExpandedTerms.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 pt-1 text-xs">
            <span className="text-muted-foreground flex items-center gap-1 font-mono text-[11px]">
              <Sparkles className="w-3 h-3 text-primary" />
              AI Semantic Match:
            </span>
            {aiExpandedTerms.map((term, i) => (
              <span
                key={i}
                className="px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20 text-[10px] font-mono font-medium"
              >
                {term}
              </span>
            ))}
            <button
              type="button"
              onClick={() => setAiExpandedTerms([])}
              className="text-[10px] text-muted-foreground hover:text-foreground underline ml-1 cursor-pointer"
            >
              Clear
            </button>
          </div>
        )}

        {/* Status Count Summary Bar with Clean Page Controls */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between text-xs text-muted-foreground pt-2.5 border-t border-border/50 gap-2">
          <div className="flex items-center gap-2.5 flex-wrap">
            <span>
              Showing{' '}
              <strong className="text-foreground font-semibold">
                {filteredProducts.length === 0
                  ? '0'
                  : `${(currentPage - 1) * ITEMS_PER_PAGE + 1}–${Math.min(
                      currentPage * ITEMS_PER_PAGE,
                      filteredProducts.length
                    )}`}
              </strong>{' '}
              of <strong className="text-foreground font-semibold">{filteredProducts.length}</strong> products
              {filteredProducts.length !== products.length && (
                <span className="text-muted-foreground ml-1">
                  (filtered from {products.length} total)
                </span>
              )}
            </span>

            {totalPages > 1 && (
              <div className="flex items-center gap-1.5 pl-2 border-l border-border/60">
                <span className="text-xs px-2.5 py-0.5 rounded-lg bg-muted text-foreground font-semibold">
                  Page {currentPage} of {totalPages}
                </span>
                <button
                  onClick={() => handlePageChange(currentPage - 1)}
                  disabled={currentPage <= 1}
                  className="p-1 rounded-lg border border-border/80 bg-background hover:bg-muted text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer"
                  title="Previous page"
                >
                  <ChevronLeft className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => handlePageChange(currentPage + 1)}
                  disabled={currentPage >= totalPages}
                  className="p-1 rounded-lg border border-border/80 bg-background hover:bg-muted text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer"
                  title="Next page"
                >
                  <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
            )}
          </div>
          {(categoryFilter !== 'ALL' ||
            typeFilter !== 'ALL' ||
            statusFilter !== 'ALL' ||
            inStockOnly ||
            searchQuery) && (
            <button
              onClick={() => {
                setCategoryFilter('ALL');
                setTypeFilter('ALL');
                setStatusFilter('ALL');
                setInStockOnly(false);
                setSearchQuery('');
              }}
              className="text-primary hover:underline font-semibold cursor-pointer text-xs"
            >
              Reset Filters
            </button>
          )}
        </div>
      </div>

      {/* Product Content View */}
      {isLoading ? (
        <div className="py-24 text-center space-y-3">
          <div className="w-10 h-10 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-xs text-muted-foreground">Synchronizing product catalog...</p>
        </div>
      ) : filteredProducts.length === 0 ? (
        /* Empty State */
        <div className="py-20 text-center rounded-2xl border border-dashed border-border/80 bg-card/40 space-y-4 max-w-lg mx-auto p-6">
          <div className="w-12 h-12 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary mx-auto">
            <Package className="w-6 h-6" />
          </div>
          <div className="space-y-1">
            <h4 className="font-serif text-base font-bold text-foreground">
              {searchQuery || categoryFilter !== 'ALL'
                ? 'No matching catalog items'
                : 'Your catalog is empty'}
            </h4>
            <p className="text-xs text-muted-foreground max-w-sm mx-auto">
              {searchQuery || categoryFilter !== 'ALL'
                ? 'Try adjusting your filters, searching different keywords, or reset filters.'
                : 'Create your first product with the 5-step wizard or import your existing catalog via CSV.'}
            </p>
          </div>
          <div className="flex items-center justify-center gap-2 pt-2">
            <button
              onClick={onOpenWizard}
              className="px-4 py-2 text-xs font-semibold rounded-xl bg-primary text-primary-foreground hover:opacity-95 shadow-xs flex items-center gap-1.5"
            >
              <Plus className="w-3.5 h-3.5" />
              Launch Product Wizard
            </button>
            <button
              onClick={onOpenCsvImport}
              className="px-4 py-2 text-xs font-medium rounded-xl border border-border/80 hover:bg-muted text-foreground transition-colors"
            >
              Import CSV
            </button>
          </div>
        </div>
      ) : viewMode === 'grid' ? (
        /* GRID CARDS VIEW */
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {paginatedProducts.map((product) => {
            const prodVariants = variantsByProduct[product.id] || [];
            const prices = prodVariants.map((v) => Number(v.price)).filter((p) => !isNaN(p));
            const minPrice = prices.length > 0 ? Math.min(...prices) : 0;
            const maxPrice = prices.length > 0 ? Math.max(...prices) : 0;

            return (
              <div
                key={product.id}
                className="group relative rounded-2xl border border-border/80 bg-card hover:border-primary/40 hover:shadow-md transition-all duration-200 overflow-hidden flex flex-col justify-between"
              >
                <div className="p-5 space-y-3">
                  {/* Card Header */}
                  <div className="flex items-start justify-between gap-2">
                    <div className="space-y-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span
                          className={`text-[9px] font-mono px-2 py-0.5 rounded-md font-bold uppercase tracking-wider ${
                            product.type === 'PRODUCT'
                              ? 'bg-primary/10 text-primary border border-primary/20'
                              : 'bg-indigo-500/10 text-indigo-500 border border-indigo-500/20'
                          }`}
                        >
                          {product.type}
                        </span>
                        <span
                          className={`text-[9px] font-mono px-2 py-0.5 rounded-md font-bold uppercase tracking-wider flex items-center gap-1 ${
                            product.status === 'ACTIVE'
                              ? 'bg-emerald-500/10 text-emerald-500 border border-emerald-500/20'
                              : product.status === 'DRAFT'
                              ? 'bg-amber-500/10 text-amber-500 border border-amber-500/20'
                              : 'bg-slate-500/10 text-slate-400 border border-slate-500/20'
                          }`}
                        >
                          <span
                            className={`w-1.5 h-1.5 rounded-full ${
                              product.status === 'ACTIVE'
                                ? 'bg-emerald-500'
                                : product.status === 'DRAFT'
                                ? 'bg-amber-500'
                                : 'bg-slate-400'
                            }`}
                          />
                          {product.status}
                        </span>
                      </div>
                      <h4 className="font-serif text-base font-bold text-foreground leading-snug truncate group-hover:text-primary transition-colors">
                        {product.name}
                      </h4>
                    </div>

                    {/* Price Range & Sellable Stock */}
                    <div className="text-right shrink-0">
                      <span className="text-sm font-mono font-bold text-foreground block">
                        {minPrice === maxPrice
                          ? `$${minPrice.toFixed(2)}`
                          : `$${minPrice.toFixed(2)} - $${maxPrice.toFixed(2)}`}
                      </span>
                      <span className="text-[10px] text-muted-foreground font-mono block">
                        {prodVariants.length} SKU{prodVariants.length !== 1 ? 's' : ''}
                      </span>
                      {productStockMap && productStockMap[product.id] !== undefined && (
                        <span
                          className={`inline-block mt-1 text-[10px] font-mono px-1.5 py-0.2 rounded font-semibold border ${
                            productStockMap[product.id] > 0
                              ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20'
                              : 'bg-destructive/10 text-destructive border-destructive/20'
                          }`}
                        >
                          {productStockMap[product.id]} in stock
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Category & Subcategory */}
                  <div className="text-xs text-muted-foreground flex items-center gap-1.5">
                    <span className="font-medium text-foreground">{product.category}</span>
                    {product.subcategory && (
                      <>
                        <span>/</span>
                        <span>{product.subcategory}</span>
                      </>
                    )}
                  </div>

                  {/* Description Preview */}
                  {product.description && (
                    <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed">
                      {product.description}
                    </p>
                  )}

                  {/* AI Findability Chips */}
                  {(product.keywords?.length > 0 || product.use_cases?.length > 0) && (
                    <div className="flex flex-wrap gap-1 pt-1">
                      {product.keywords?.slice(0, 3).map((kw, i) => (
                        <span
                          key={i}
                          className="text-[10px] px-2 py-0.5 rounded-md bg-muted/60 text-muted-foreground font-mono"
                        >
                          #{kw}
                        </span>
                      ))}
                      {product.use_cases?.slice(0, 2).map((uc, i) => (
                        <span
                          key={i}
                          className="text-[10px] px-2 py-0.5 rounded-md bg-emerald-500/5 text-emerald-600 dark:text-emerald-400 border border-emerald-500/15"
                        >
                          {uc}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Smart Search Match Highlight */}
                  {smartSearchScores.has(product.id) && smartSearchScores.get(product.id)!.matchedTerms.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1 pt-1 border-t border-border/40">
                      <span className="text-[10px] text-muted-foreground font-mono">Matched:</span>
                      {smartSearchScores.get(product.id)!.matchedTerms.map((term, i) => (
                        <span
                          key={i}
                          className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20"
                        >
                          ✓ {term}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Discount guardrails if configured */}
                  {(product.min_discount_pct > 0 || product.max_discount_pct > 0) && (
                    <div className="text-[10px] font-mono text-muted-foreground">
                      Discount Guardrail: {product.min_discount_pct}% - {product.max_discount_pct}%
                    </div>
                  )}
                </div>

                {/* Card Footer Actions */}
                <div className="px-5 py-3 border-t border-border/60 bg-muted/20 flex items-center justify-between text-xs">
                  <button
                    onClick={() => onSelectProduct(product.id)}
                    className="font-semibold text-primary hover:underline flex items-center gap-1 cursor-pointer"
                  >
                    View / Edit Specs
                    <ChevronRight className="w-3.5 h-3.5" />
                  </button>

                  <div className="flex items-center gap-1.5">
                    {prodVariants[0] && (
                      <button
                        onClick={() => onCheckStock(prodVariants[0].sku)}
                        className="px-2 py-1 rounded-lg text-[11px] font-semibold bg-primary/10 hover:bg-primary/20 text-primary border border-primary/20 transition-colors cursor-pointer flex items-center gap-1"
                        title="Check Deal Stock & Multi-Hub Fulfillment Feasibility"
                      >
                        <Zap className="w-3 h-3" />
                        Deal Stock
                      </button>
                    )}
                    {onDeleteProduct && (
                      <button
                        onClick={() => onDeleteProduct(product)}
                        className="p-1.5 rounded-lg text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors cursor-pointer"
                        title={product.status === 'RETIRED' ? 'Permanently Delete Product' : 'Delete or Retire Product'}
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        /* TABLE VIEW */
        <div className="rounded-2xl border border-border/80 bg-card overflow-hidden shadow-xs">
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left">
              <thead className="bg-muted/40 text-muted-foreground uppercase text-[10px] border-b border-border/70">
                <tr>
                  <th className="px-4 py-3">Product Name & Type</th>
                  <th className="px-4 py-3">Category</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">SKUs / Variants</th>
                  <th className="px-4 py-3">Price Range</th>
                  <th className="px-4 py-3">Sellable Stock</th>
                  <th className="px-4 py-3">AI Intel & Tags</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {paginatedProducts.map((product) => {
                  const prodVariants = variantsByProduct[product.id] || [];
                  const prices = prodVariants
                    .map((v) => Number(v.price))
                    .filter((p) => !isNaN(p));
                  const minPrice = prices.length > 0 ? Math.min(...prices) : 0;
                  const maxPrice = prices.length > 0 ? Math.max(...prices) : 0;
                  const sellableUnits = productStockMap?.[product.id] ?? 0;

                  return (
                    <tr
                      key={product.id}
                      className="hover:bg-muted/20 transition-colors group cursor-pointer"
                      onClick={() => onSelectProduct(product.id)}
                    >
                      <td className="px-4 py-3.5">
                        <div className="font-semibold text-foreground group-hover:text-primary transition-colors">
                          {product.name}
                        </div>
                        <span className="text-[10px] font-mono text-muted-foreground">
                          {product.type}
                        </span>
                      </td>
                      <td className="px-4 py-3.5 text-foreground font-medium">
                        {product.category}
                        {product.subcategory && (
                          <span className="text-muted-foreground font-normal block text-[11px]">
                            {product.subcategory}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3.5">
                        <span
                          className={`text-[9px] font-mono px-2 py-0.5 rounded-md font-bold uppercase ${
                            product.status === 'ACTIVE'
                              ? 'bg-emerald-500/10 text-emerald-500 border border-emerald-500/20'
                              : product.status === 'DRAFT'
                              ? 'bg-amber-500/10 text-amber-500 border border-amber-500/20'
                              : 'bg-slate-500/10 text-slate-400 border border-slate-500/20'
                          }`}
                        >
                          {product.status}
                        </span>
                      </td>
                      <td className="px-4 py-3.5 font-mono font-semibold text-foreground">
                        {prodVariants.length} SKU{prodVariants.length !== 1 ? 's' : ''}
                      </td>
                      <td className="px-4 py-3.5 font-mono font-bold text-foreground">
                        {minPrice === maxPrice
                          ? `$${minPrice.toFixed(2)}`
                          : `$${minPrice.toFixed(2)} - $${maxPrice.toFixed(2)}`}
                      </td>
                      <td className="px-4 py-3.5">
                        <span
                          className={`inline-block font-mono text-xs font-semibold px-2 py-0.5 rounded-md ${
                            sellableUnits > 0
                              ? 'bg-emerald-500/10 text-emerald-500 border border-emerald-500/20'
                              : 'bg-muted/60 text-muted-foreground'
                          }`}
                        >
                          {sellableUnits} units
                        </span>
                      </td>
                      <td className="px-4 py-3.5">
                        <div className="flex flex-wrap gap-1 max-w-xs">
                          {smartSearchScores.has(product.id) && smartSearchScores.get(product.id)!.matchedTerms.length > 0 ? (
                            smartSearchScores.get(product.id)!.matchedTerms.map((term, i) => (
                              <span
                                key={i}
                                className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20"
                              >
                                ✓ {term}
                              </span>
                            ))
                          ) : (
                            <>
                              {product.keywords?.slice(0, 2).map((k, i) => (
                                <span
                                  key={i}
                                  className="text-[10px] px-1.5 py-0.2 rounded bg-muted text-muted-foreground font-mono"
                                >
                                  {k}
                                </span>
                              ))}
                              {product.use_cases?.slice(0, 1).map((u, i) => (
                                <span
                                  key={i}
                                  className="text-[10px] px-1.5 py-0.2 rounded bg-emerald-500/10 text-emerald-500 font-medium"
                                >
                                  {u}
                                </span>
                              ))}
                            </>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3.5 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          {prodVariants[0] && (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                onCheckStock(prodVariants[0].sku);
                              }}
                              className="px-2 py-1 text-xs font-semibold rounded-lg bg-primary/10 hover:bg-primary/20 text-primary border border-primary/20 transition-colors cursor-pointer flex items-center gap-1"
                              title="Check Deal Stock & Multi-Hub Fulfillment Feasibility"
                            >
                              <Zap className="w-3 h-3" />
                              Deal Stock
                            </button>
                          )}
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              onSelectProduct(product.id);
                            }}
                            className="px-2.5 py-1 text-xs font-semibold rounded-lg bg-muted hover:bg-muted/80 text-foreground transition-colors cursor-pointer"
                          >
                            Edit
                          </button>
                          {onDeleteProduct && (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                onDeleteProduct(product);
                              }}
                              className="p-1 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded transition-colors cursor-pointer"
                              title={product.status === 'RETIRED' ? 'Permanently Delete Product' : 'Delete or Retire Product'}
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Pagination Controls */}
      {filteredProducts.length > 0 && (
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 px-4 py-3.5 rounded-2xl bg-card border border-border/80 shadow-xs text-xs">
          <div className="flex items-center gap-2 text-muted-foreground">
            <span>
              Showing{' '}
              <strong className="text-foreground">
                {(currentPage - 1) * ITEMS_PER_PAGE + 1}–
                {Math.min(currentPage * ITEMS_PER_PAGE, filteredProducts.length)}
              </strong>{' '}
              of <strong className="text-foreground">{filteredProducts.length}</strong> products
            </span>
            <span className="text-[10px] px-2 py-0.5 rounded-md bg-muted text-muted-foreground font-mono">
              60 / page
            </span>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => handlePageChange(1)}
                disabled={currentPage === 1}
                title="First page"
                className="p-1.5 rounded-xl border border-border/80 hover:bg-muted/70 text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer"
              >
                <ChevronsLeft className="w-4 h-4" />
              </button>
              <button
                onClick={() => handlePageChange(currentPage - 1)}
                disabled={currentPage === 1}
                title="Previous page"
                className="p-1.5 rounded-xl border border-border/80 hover:bg-muted/70 text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>

              <div className="flex items-center gap-1 mx-1">
                {getPageNumbers(currentPage, totalPages).map((p, idx) => {
                  if (p === '...') {
                    return (
                      <span
                        key={`ellipsis-${idx}`}
                        className="px-2 py-1 text-muted-foreground select-none"
                      >
                        ...
                      </span>
                    );
                  }
                  const pageNum = p as number;
                  const isActive = pageNum === currentPage;
                  return (
                    <button
                      key={pageNum}
                      onClick={() => handlePageChange(pageNum)}
                      className={`min-w-8 h-8 px-2.5 rounded-xl text-xs font-semibold transition-all cursor-pointer ${
                        isActive
                          ? 'bg-primary text-primary-foreground shadow-xs font-bold'
                          : 'border border-border/80 hover:bg-muted/70 text-foreground'
                      }`}
                    >
                      {pageNum}
                    </button>
                  );
                })}
              </div>

              <button
                onClick={() => handlePageChange(currentPage + 1)}
                disabled={currentPage === totalPages}
                title="Next page"
                className="p-1.5 rounded-xl border border-border/80 hover:bg-muted/70 text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
              <button
                onClick={() => handlePageChange(totalPages)}
                disabled={currentPage === totalPages}
                title="Last page"
                className="p-1.5 rounded-xl border border-border/80 hover:bg-muted/70 text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer"
              >
                <ChevronsRight className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
