import React, { useState, useEffect } from 'react';
import {
  X,
  Package,
  Layers,
  Sparkles,
  Trash2,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Warehouse,
} from 'lucide-react';
import {
  catalogApi,
  type ProductDetail,
  type Category,
  type Location,
  type VariantAvailabilityResponse,
} from '../../../api/catalogApi';
import { useToast } from '../../../context/ToastContext';

interface ProductDetailModalProps {
  isOpen: boolean;
  productId: string | null;
  onClose: () => void;
  onProductUpdated: () => void;
  categories: Category[];
  locations: Location[];
  onOpenAdjustStock?: (variantId: string) => void;
}

// Client-side SQL injection sanitization pattern (detects actual SQL exploit vectors without blocking natural English phrases)
const SQL_INJECTION_PATTERN = /(;\s*(DROP|SELECT|INSERT|UPDATE|DELETE|ALTER|TRUNCATE|EXEC(UTE)?)\b)|(\bUNION\s+(ALL\s+)?SELECT\b)|(?:--\s*|\/\*[\s\S]*?\*\/)|(\b(?:OR|AND)\b\s+['"0-9]+=['"0-9]+)|(\b(INSERT\s+INTO|DROP\s+TABLE|ALTER\s+TABLE|TRUNCATE\s+TABLE)\b)/i;

const validateSecurity = (val?: string | null, fieldName: string = 'Field'): string | null => {
  if (val && SQL_INJECTION_PATTERN.test(val)) {
    return `Unsafe SQL injection pattern detected in ${fieldName}.`;
  }
  return null;
};

export const ProductDetailModal: React.FC<ProductDetailModalProps> = ({
  isOpen,
  productId,
  onClose,
  onProductUpdated,
  categories,
  locations,
  onOpenAdjustStock,
}) => {
  const toast = useToast();

  const [activeTab, setActiveTab] = useState<'overview' | 'variants' | 'stock'>('overview');
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [isDeleting, setIsDeleting] = useState<boolean>(false);
  const [confirmDelete, setConfirmDelete] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isAiGenerating, setIsAiGenerating] = useState<boolean>(false);

  // Form edit states
  const [name, setName] = useState<string>('');
  const [category, setCategory] = useState<string>('');
  const [subcategory, setSubcategory] = useState<string>('');
  const [type, setType] = useState<'PRODUCT' | 'SERVICE'>('PRODUCT');
  const [status, setStatus] = useState<'DRAFT' | 'ACTIVE' | 'RETIRED'>('ACTIVE');
  const [description, setDescription] = useState<string>('');
  const [keywords, setKeywords] = useState<string[]>([]);
  const [keywordInput, setKeywordInput] = useState<string>('');
  const [useCases, setUseCases] = useState<string[]>([]);
  const [useCaseInput, setUseCaseInput] = useState<string>('');
  const [targetIndustries, setTargetIndustries] = useState<string[]>([]);
  const [targetIndustryInput, setTargetIndustryInput] = useState<string>('');
  const [valueProposition, setValueProposition] = useState<string>('');
  const [idealCustomerProfile, setIdealCustomerProfile] = useState<string>('');
  const [minDiscountPct, setMinDiscountPct] = useState<number>(0);
  const [maxDiscountPct, setMaxDiscountPct] = useState<number>(0);

  // Stock availability state
  const [availabilities, setAvailabilities] = useState<Record<string, VariantAvailabilityResponse>>({});
  const [loadingAvailabilities, setLoadingAvailabilities] = useState<boolean>(false);

  useEffect(() => {
    if (isOpen && productId) {
      loadProduct(productId);
    } else {
      setProduct(null);
      setConfirmDelete(false);
      setErrorMessage(null);
    }
  }, [isOpen, productId]);

  const loadProduct = async (id: string) => {
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const data = await catalogApi.getProduct(id);
      setProduct(data);
      setName(data.name);
      setCategory(data.category);
      setSubcategory(data.subcategory || '');
      setType(data.type);
      setStatus(data.status);
      setDescription(data.description || '');
      setKeywords(data.keywords || []);
      setUseCases(data.use_cases || []);
      setTargetIndustries(data.target_industries || []);
      setValueProposition(data.value_proposition || '');
      setIdealCustomerProfile(data.ideal_customer_profile || '');
      setMinDiscountPct(Number(data.min_discount_pct) || 0);
      setMaxDiscountPct(Number(data.max_discount_pct) || 0);

      // Fetch availabilities for all variants
      if (data.variants && data.variants.length > 0) {
        fetchVariantAvailabilities(data.variants.map((v) => v.sku));
      }
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Failed to load product.';
      setErrorMessage(msg);
      toast.error(msg, 'Load Error');
    } finally {
      setIsLoading(false);
    }
  };

  const fetchVariantAvailabilities = async (skus: string[]) => {
    if (!skus || skus.length === 0) return;
    setLoadingAvailabilities(true);
    try {
      const results = await catalogApi.getBatchAvailability(skus);
      setAvailabilities(results);
    } catch (err) {
      console.warn('[ProductDetailModal] Batch availability failed, falling back:', err);
      const results: Record<string, VariantAvailabilityResponse> = {};
      for (const sku of skus) {
        try {
          const avail = await catalogApi.getAvailability(sku);
          results[sku] = avail;
        } catch (e) {
          // ignore individual 404s
        }
      }
      setAvailabilities(results);
    } finally {
      setLoadingAvailabilities(false);
    }
  };

  if (!isOpen) return null;

  const handleAddKeyword = () => {
    if (keywordInput.trim() && !keywords.includes(keywordInput.trim())) {
      setKeywords([...keywords, keywordInput.trim()]);
      setKeywordInput('');
    }
  };

  const handleAddUseCase = () => {
    if (useCaseInput.trim() && !useCases.includes(useCaseInput.trim())) {
      setUseCases([...useCases, useCaseInput.trim()]);
      setUseCaseInput('');
    }
  };

  const handleAddTargetIndustry = () => {
    if (targetIndustryInput.trim() && !targetIndustries.includes(targetIndustryInput.trim())) {
      setTargetIndustries([...targetIndustries, targetIndustryInput.trim()]);
      setTargetIndustryInput('');
    }
  };

  // Threshold readiness check for AI auto-generation
  const isAiEligible =
    name.trim().length >= 3 &&
    Boolean(type) &&
    Boolean(category.trim()) &&
    description.trim().length >= 200;

  const handleGenerateAiFindability = async () => {
    // 1. Name Threshold (min 3 characters)
    if (name.trim().length < 3) {
      toast.warning('Product / Service Name must be at least 3 characters.', 'Name Too Short');
      return;
    }

    // 2. Type validation
    if (!type) {
      toast.warning('Please select a valid Catalog Item Type (PRODUCT or SERVICE).', 'Type Required');
      return;
    }

    // 3. Primary Category validation (Required, NOT Subcategory)
    if (!category.trim()) {
      toast.warning('Primary Category is required before AI generation.', 'Category Required');
      return;
    }

    // 4. Description Threshold (min 200 characters)
    if (description.trim().length < 200) {
      toast.warning(
        `Product Description must be at least 200 characters (currently ${description.trim().length}/200). AI requires sufficient details to craft sales intelligence.`,
        'Description Incomplete'
      );
      return;
    }

    // 5. SQL Injection & Unsafe Pattern check
    const secErr =
      validateSecurity(name, 'Product Name') ||
      validateSecurity(category, 'Category') ||
      validateSecurity(subcategory, 'Subcategory') ||
      validateSecurity(description, 'Description');
    if (secErr) {
      toast.error(secErr, 'Security Validation Failed');
      return;
    }

    setIsAiGenerating(true);
    setErrorMessage(null);
    try {
      const generated = await catalogApi.generateFindability({
        name: name.trim(),
        type,
        category: category.trim(),
        subcategory: subcategory.trim() || undefined,
        description: description.trim(),
      });

      const nextKeywords = generated.keywords && generated.keywords.length > 0 ? generated.keywords : keywords;
      const nextUseCases = generated.use_cases && generated.use_cases.length > 0 ? generated.use_cases : useCases;
      const nextTargetIndustries = generated.target_industries && generated.target_industries.length > 0 ? generated.target_industries : targetIndustries;
      const nextValueProp = generated.value_proposition || valueProposition;
      const nextIcp = generated.ideal_customer_profile || idealCustomerProfile;
      const nextMinDiscount = (generated.min_discount_pct !== undefined && generated.min_discount_pct !== null)
        ? generated.min_discount_pct
        : minDiscountPct;
      const nextMaxDiscount = (generated.max_discount_pct !== undefined && generated.max_discount_pct !== null)
        ? generated.max_discount_pct
        : maxDiscountPct;

      setKeywords(nextKeywords);
      setUseCases(nextUseCases);
      setTargetIndustries(nextTargetIndustries);
      setValueProposition(nextValueProp);
      setIdealCustomerProfile(nextIcp);
      setMinDiscountPct(nextMinDiscount);
      setMaxDiscountPct(nextMaxDiscount);

      // Auto-save to backend if productId exists
      if (productId) {
        const updated = await catalogApi.updateProduct(productId, {
          name: name.trim(),
          category: category.trim(),
          subcategory: subcategory.trim() || null,
          type,
          status,
          description: description.trim() || null,
          keywords: nextKeywords,
          use_cases: nextUseCases,
          target_industries: nextTargetIndustries,
          value_proposition: nextValueProp.trim() || null,
          ideal_customer_profile: nextIcp.trim() || null,
          min_discount_pct: nextMinDiscount,
          max_discount_pct: nextMaxDiscount,
        });

        setProduct((prev) => (prev ? { ...prev, ...updated } : updated));
        onProductUpdated();
        toast.success(
          'AI generated and saved findability keywords, use cases & ICP to catalog!',
          'AI Intelligence Generated & Saved'
        );
      } else {
        toast.success('AI populated findability keywords, use cases & ICP!', 'AI Intelligence Generated');
      }
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Failed to generate AI intelligence.';
      setErrorMessage(msg);
      toast.error(msg, 'AI Generation Failed');
    } finally {
      setIsAiGenerating(false);
    }
  };

  const handleSaveOverview = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!productId) return;

    // Validate inputs & lengths
    if (name.trim().length < 3) {
      toast.warning('Product / Service Name must be at least 3 characters.', 'Name Too Short');
      return;
    }
    if (name.trim().length > 255) {
      toast.warning('Product / Service Name cannot exceed 255 characters.', 'Name Too Long');
      return;
    }
    if (!category.trim()) {
      toast.warning('Primary Category is required.', 'Category Required');
      return;
    }
    if (category.trim().length > 100) {
      toast.warning('Category cannot exceed 100 characters.', 'Category Too Long');
      return;
    }
    if (subcategory.trim().length > 100) {
      toast.warning('Subcategory cannot exceed 100 characters.', 'Subcategory Too Long');
      return;
    }
    if (description.length > 10000) {
      toast.warning('Description cannot exceed 10,000 characters.', 'Description Too Long');
      return;
    }
    if (valueProposition.length > 5000) {
      toast.warning('Value Proposition cannot exceed 5,000 characters.', 'Value Proposition Too Long');
      return;
    }
    if (idealCustomerProfile.length > 5000) {
      toast.warning('Ideal Customer Profile cannot exceed 5,000 characters.', 'ICP Too Long');
      return;
    }

    // SQL Injection Security Validation
    const secErr =
      validateSecurity(name, 'Product Name') ||
      validateSecurity(category, 'Category') ||
      validateSecurity(subcategory, 'Subcategory') ||
      validateSecurity(description, 'Description') ||
      validateSecurity(valueProposition, 'Value Proposition') ||
      validateSecurity(idealCustomerProfile, 'Ideal Customer Profile');
    if (secErr) {
      toast.error(secErr, 'Security Validation Failed');
      return;
    }

    for (const kw of keywords) {
      const err = validateSecurity(kw, 'Keyword');
      if (err) { toast.error(err, 'Security Validation Failed'); return; }
    }
    for (const uc of useCases) {
      const err = validateSecurity(uc, 'Use Case');
      if (err) { toast.error(err, 'Security Validation Failed'); return; }
    }
    for (const ti of targetIndustries) {
      const err = validateSecurity(ti, 'Target Industry');
      if (err) { toast.error(err, 'Security Validation Failed'); return; }
    }

    setIsSaving(true);
    setErrorMessage(null);

    try {
      const updated = await catalogApi.updateProduct(productId, {
        name: name.trim(),
        category: category.trim(),
        subcategory: subcategory.trim() || null,
        type,
        status,
        description: description.trim() || null,
        keywords,
        use_cases: useCases,
        target_industries: targetIndustries,
        value_proposition: valueProposition.trim() || null,
        ideal_customer_profile: idealCustomerProfile.trim() || null,
        min_discount_pct: minDiscountPct,
        max_discount_pct: maxDiscountPct,
      });

      setProduct((prev) => (prev ? { ...prev, ...updated } : updated));
      toast.success(`Updated "${updated.name}".`, 'Changes Saved');
      onProductUpdated();
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Failed to save updates.';
      setErrorMessage(msg);
      toast.error(msg, 'Save Error');
    } finally {
      setIsSaving(false);
    }
  };

  const handleRetire = async () => {
    if (!productId || !product) return;

    setIsDeleting(true);
    try {
      await catalogApi.deleteProduct(productId, false, product.tenant_id);
      toast.success('Product soft-deleted (status set to RETIRED).', 'Product Retired');
      onProductUpdated();
      onClose();
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Failed to retire product.';
      setErrorMessage(msg);
      toast.error(msg, 'Retire Error');
    } finally {
      setIsDeleting(false);
    }
  };

  const handlePermanentDelete = async () => {
    if (!productId || !product) return;

    setIsDeleting(true);
    try {
      await catalogApi.deleteProduct(productId, true, product.tenant_id);
      toast.success(`Product "${product.name}" permanently deleted from database.`, 'Product Purged');
      onProductUpdated();
      onClose();
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Failed to delete product.';
      setErrorMessage(msg);
      toast.error(msg, 'Delete Error');
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs animate-in fade-in duration-200">
      <div className="relative w-full max-w-4xl bg-card border border-border/80 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[92vh]">
        {/* Header */}
        <div className="px-6 py-4 border-b border-border/60 flex items-center justify-between bg-card/80">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary shrink-0">
              <Package className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h3 className="font-serif text-lg font-bold text-foreground truncate">
                  {isLoading ? 'Loading Product...' : product?.name || 'Product Details'}
                </h3>
                {product && (
                  <span
                    className={`text-[10px] font-mono px-2 py-0.5 rounded-full font-bold uppercase border ${
                      product.status === 'ACTIVE'
                        ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20'
                        : product.status === 'DRAFT'
                        ? 'bg-amber-500/10 text-amber-500 border-amber-500/20'
                        : 'bg-slate-500/10 text-slate-400 border-slate-500/20'
                    }`}
                  >
                    {product.status}
                  </span>
                )}
              </div>
              <p className="text-xs text-muted-foreground truncate">
                Category: {product?.category} • ID: <span className="font-mono">{product?.id}</span>
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={isAiGenerating || isSaving || isDeleting}
            title={isAiGenerating ? 'Generating AI intelligence, please wait...' : 'Close'}
            className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tab Navigation */}
        <div className="px-6 border-b border-border/60 bg-muted/20 flex items-center gap-6">
          <button
            onClick={() => setActiveTab('overview')}
            className={`py-3 text-xs font-semibold border-b-2 flex items-center gap-2 transition-all ${
              activeTab === 'overview'
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >
            <Sparkles className="w-4 h-4" />
            Overview & AI Intel
          </button>
          <button
            onClick={() => setActiveTab('variants')}
            className={`py-3 text-xs font-semibold border-b-2 flex items-center gap-2 transition-all ${
              activeTab === 'variants'
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >
            <Layers className="w-4 h-4" />
            Variants & Options ({product?.variants?.length || 0})
          </button>
          <button
            onClick={() => setActiveTab('stock')}
            className={`py-3 text-xs font-semibold border-b-2 flex items-center gap-2 transition-all ${
              activeTab === 'stock'
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >
            <Warehouse className="w-4 h-4" />
            Live Stock Availability
          </button>
        </div>

        {/* Body Content */}
        <div className="p-6 overflow-y-auto flex-1 space-y-6">
          {errorMessage && (
            <div className="p-3.5 rounded-xl bg-destructive/10 border border-destructive/25 text-destructive text-xs flex items-start gap-2">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{errorMessage}</span>
            </div>
          )}

          {isLoading ? (
            <div className="py-16 text-center space-y-3">
              <Loader2 className="w-8 h-8 animate-spin text-primary mx-auto" />
              <p className="text-xs text-muted-foreground">Loading catalog item details...</p>
            </div>
          ) : product ? (
            <>
              {/* TAB 1: OVERVIEW & AI INTEL */}
              {activeTab === 'overview' && (
                <form onSubmit={handleSaveOverview} className="space-y-4">
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <div className="sm:col-span-2">
                      <label className="block text-xs font-medium text-foreground mb-1">
                        Product / Service Name *
                      </label>
                      <input
                        type="text"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        disabled={isAiGenerating || isSaving}
                        maxLength={255}
                        required
                        className="w-full px-3 py-2 text-xs rounded-xl bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40 disabled:opacity-50 disabled:cursor-not-allowed"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-medium text-foreground mb-1">
                        Lifecycle Status
                      </label>
                      <select
                        value={status}
                        onChange={(e) => setStatus(e.target.value as any)}
                        disabled={isAiGenerating || isSaving}
                        className="w-full px-3 py-2 text-xs rounded-xl bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        <option value="ACTIVE">ACTIVE</option>
                        <option value="DRAFT">DRAFT</option>
                        <option value="RETIRED">RETIRED</option>
                      </select>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-foreground mb-1">
                        Type
                      </label>
                      <select
                        value={type}
                        onChange={(e) => setType(e.target.value as any)}
                        disabled={isAiGenerating || isSaving}
                        className="w-full px-3 py-2 text-xs rounded-xl bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        <option value="PRODUCT">Physical Product</option>
                        <option value="SERVICE">Service / Retainer</option>
                      </select>
                    </div>

                    <div>
                      <label className="block text-xs font-medium text-foreground mb-1">
                        Primary Category *
                      </label>
                      <input
                        type="text"
                        list="detail-categories-datalist"
                        value={category}
                        onChange={(e) => setCategory(e.target.value)}
                        disabled={isAiGenerating || isSaving}
                        maxLength={100}
                        required
                        placeholder="e.g. furniture"
                        className="w-full px-3 py-2 text-xs rounded-xl bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40 disabled:opacity-50 disabled:cursor-not-allowed"
                      />
                      <datalist id="detail-categories-datalist">
                        {categories.map((c) => (
                          <option key={c.id} value={c.key}>
                            {c.label}
                          </option>
                        ))}
                      </datalist>
                    </div>

                    <div>
                      <label className="block text-xs font-medium text-foreground mb-1">
                        Subcategory (Optional)
                      </label>
                      <input
                        type="text"
                        value={subcategory}
                        onChange={(e) => setSubcategory(e.target.value)}
                        disabled={isAiGenerating || isSaving}
                        maxLength={100}
                        placeholder="e.g. office_chairs (optional)"
                        className="w-full px-3 py-2 text-xs rounded-xl bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40 disabled:opacity-50 disabled:cursor-not-allowed"
                      />
                    </div>
                  </div>

                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="block text-xs font-medium text-foreground">
                        Description *
                      </label>
                      <span className="text-[11px] text-muted-foreground">
                        Specs, materials, and selling points
                      </span>
                    </div>
                    <textarea
                      rows={3}
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      disabled={isAiGenerating || isSaving}
                      maxLength={10000}
                      placeholder="Detailed product or service description... (Minimum 200 characters required to Auto-Generate with AI)"
                      className="w-full px-3 py-2 text-xs rounded-xl bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40 resize-y disabled:opacity-50 disabled:cursor-not-allowed"
                    />
                    <div className="flex items-center justify-between text-xs mt-1 px-1">
                      <span
                        className={
                          description.trim().length >= 200
                            ? 'text-emerald-500 font-medium flex items-center gap-1'
                            : 'text-amber-500 font-medium flex items-center gap-1'
                        }
                      >
                        {description.trim().length >= 200 ? (
                          <>✓ {description.trim().length} characters (AI threshold met)</>
                        ) : (
                          <>
                            ⚠ {description.trim().length} / 200 min characters for AI Auto-Generate{' '}
                            <span className="opacity-75">
                              ({200 - description.trim().length} more needed)
                            </span>
                          </>
                        )}
                      </span>
                      <span className="text-muted-foreground font-mono text-[11px]">
                        {description.length} / 10,000
                      </span>
                    </div>
                  </div>

                  {/* AI Generating Alert Banner */}
                  {isAiGenerating && (
                    <div className="p-3 rounded-xl bg-primary/10 border border-primary/30 text-primary text-xs flex items-center gap-3 animate-pulse">
                      <Loader2 className="w-4 h-4 animate-spin shrink-0" />
                      <div className="flex-1 font-medium">
                        AI Agent is analyzing title, type, category & description to generate keywords, use cases, target industries, and ideal customer profile...
                      </div>
                      <span className="text-[10px] uppercase font-mono tracking-wider font-semibold opacity-70">
                        Locked & Saving
                      </span>
                    </div>
                  )}

                  {/* AI Findability Tags */}
                  <div className="p-4 rounded-xl bg-muted/20 border border-border/70 space-y-3">
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <span className="text-xs font-semibold text-foreground uppercase tracking-wider flex items-center gap-2">
                        <Sparkles className="w-3.5 h-3.5 text-primary" />
                        AI Findability & Sales Embeddings
                      </span>
                      <div className="flex items-center gap-2">
                        {!isAiEligible && (
                          <span className="text-[11px] text-amber-500 font-medium hidden sm:inline">
                            {name.trim().length < 3
                              ? 'Name (min 3 chars)'
                              : !category.trim()
                              ? 'Primary category required'
                              : description.trim().length < 200
                              ? `Description (${description.trim().length}/200)`
                              : ''}
                          </span>
                        )}
                        <button
                          type="button"
                          onClick={handleGenerateAiFindability}
                          disabled={isAiGenerating || isSaving}
                          title={
                            !isAiEligible
                              ? `Requires: Name (min 3 chars), Type, Primary Category, and Description (min 200 chars - currently ${description.trim().length}/200)`
                              : 'Auto-generate keywords, use cases & ICP with AI'
                          }
                          className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-all flex items-center gap-1.5 shadow-2xs ${
                            isAiEligible
                              ? 'bg-primary/10 text-primary border-primary/30 hover:bg-primary/20 active:scale-98 cursor-pointer'
                              : 'bg-muted/40 text-muted-foreground border-border/60 hover:bg-muted/60 cursor-pointer'
                          } disabled:opacity-40 disabled:cursor-not-allowed`}
                        >
                          {isAiGenerating ? (
                            <>
                              <Loader2 className="w-3.5 h-3.5 animate-spin" />
                              <span>Generating & Saving...</span>
                            </>
                          ) : (
                            <>
                              <Sparkles className="w-3.5 h-3.5 text-primary" />
                              <span>Auto-Generate with AI</span>
                            </>
                          )}
                        </button>
                      </div>
                    </div>

                    {/* Keywords */}
                    <div>
                      <label className="block text-xs font-medium text-foreground mb-1">
                        Keywords
                      </label>
                      <div className="flex gap-2 mb-2">
                        <input
                          type="text"
                          value={keywordInput}
                          onChange={(e) => setKeywordInput(e.target.value)}
                          disabled={isAiGenerating || isSaving}
                          maxLength={255}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              e.preventDefault();
                              if (!isAiGenerating && !isSaving) {
                                handleAddKeyword();
                              }
                            }
                          }}
                          placeholder="Type keyword and press Enter"
                          className="flex-1 px-3 py-1.5 text-xs rounded-xl bg-background border border-border/80 text-foreground disabled:opacity-50 disabled:cursor-not-allowed"
                        />
                        <button
                          type="button"
                          disabled={isAiGenerating || isSaving}
                          onClick={handleAddKeyword}
                          className="px-3 py-1.5 text-xs font-semibold rounded-xl bg-muted hover:bg-muted/80 text-foreground disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          Add
                        </button>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {keywords.map((kw, i) => (
                          <span
                            key={i}
                            className="text-[11px] px-2 py-0.5 rounded-md bg-primary/10 text-primary border border-primary/20 flex items-center gap-1 font-medium"
                          >
                            {kw}
                            <button
                              type="button"
                              disabled={isAiGenerating || isSaving}
                              onClick={() => setKeywords(keywords.filter((_, idx) => idx !== i))}
                              className="hover:text-destructive disabled:opacity-50 disabled:pointer-events-none"
                            >
                              &times;
                            </button>
                          </span>
                        ))}
                      </div>
                    </div>

                    {/* Use Cases */}
                    <div>
                      <label className="block text-xs font-medium text-foreground mb-1">
                        Target Use Cases
                      </label>
                      <div className="flex gap-2 mb-2">
                        <input
                          type="text"
                          value={useCaseInput}
                          onChange={(e) => setUseCaseInput(e.target.value)}
                          disabled={isAiGenerating || isSaving}
                          maxLength={255}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              e.preventDefault();
                              if (!isAiGenerating && !isSaving) {
                                handleAddUseCase();
                              }
                            }
                          }}
                          placeholder="e.g. Ergonomic lumbar support for desk jobs"
                          className="flex-1 px-3 py-1.5 text-xs rounded-xl bg-background border border-border/80 text-foreground disabled:opacity-50 disabled:cursor-not-allowed"
                        />
                        <button
                          type="button"
                          disabled={isAiGenerating || isSaving}
                          onClick={handleAddUseCase}
                          className="px-3 py-1.5 text-xs font-semibold rounded-xl bg-muted hover:bg-muted/80 text-foreground disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          Add
                        </button>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {useCases.map((uc, i) => (
                          <span
                            key={i}
                            className="text-[11px] px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20 flex items-center gap-1 font-medium"
                          >
                            {uc}
                            <button
                              type="button"
                              disabled={isAiGenerating || isSaving}
                              onClick={() => setUseCases(useCases.filter((_, idx) => idx !== i))}
                              className="hover:text-destructive disabled:opacity-50 disabled:pointer-events-none"
                            >
                              &times;
                            </button>
                          </span>
                        ))}
                      </div>
                    </div>

                    {/* Target Industries */}
                    <div>
                      <label className="block text-xs font-medium text-foreground mb-1">
                        Target Industries
                      </label>
                      <div className="flex gap-2 mb-2">
                        <input
                          type="text"
                          value={targetIndustryInput}
                          onChange={(e) => setTargetIndustryInput(e.target.value)}
                          disabled={isAiGenerating || isSaving}
                          maxLength={255}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              e.preventDefault();
                              if (!isAiGenerating && !isSaving) {
                                handleAddTargetIndustry();
                              }
                            }
                          }}
                          placeholder="e.g. Technology, Finance, Legal"
                          className="flex-1 px-3 py-1.5 text-xs rounded-xl bg-background border border-border/80 text-foreground disabled:opacity-50 disabled:cursor-not-allowed"
                        />
                        <button
                          type="button"
                          disabled={isAiGenerating || isSaving}
                          onClick={handleAddTargetIndustry}
                          className="px-3 py-1.5 text-xs font-semibold rounded-xl bg-muted hover:bg-muted/80 text-foreground disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          Add
                        </button>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {targetIndustries.map((ti, i) => (
                          <span
                            key={i}
                            className="text-[11px] px-2 py-0.5 rounded-md bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 border border-indigo-500/20 flex items-center gap-1 font-medium"
                          >
                            {ti}
                            <button
                              type="button"
                              disabled={isAiGenerating || isSaving}
                              onClick={() => setTargetIndustries(targetIndustries.filter((_, idx) => idx !== i))}
                              className="hover:text-destructive disabled:opacity-50 disabled:pointer-events-none"
                            >
                              &times;
                            </button>
                          </span>
                        ))}
                      </div>
                    </div>

                    {/* Value Prop */}
                    <div>
                      <label className="block text-xs font-medium text-foreground mb-1">
                        Value Proposition
                      </label>
                      <textarea
                        rows={2}
                        value={valueProposition}
                        onChange={(e) => setValueProposition(e.target.value)}
                        disabled={isAiGenerating || isSaving}
                        maxLength={5000}
                        placeholder="Why should the customer buy this product?"
                        className="w-full px-3 py-2 text-xs rounded-xl bg-background border border-border/80 text-foreground resize-none disabled:opacity-50 disabled:cursor-not-allowed"
                      />
                    </div>

                    {/* Ideal Customer Profile */}
                    <div>
                      <label className="block text-xs font-medium text-foreground mb-1">
                        Ideal Customer Profile (ICP)
                      </label>
                      <textarea
                        rows={2}
                        value={idealCustomerProfile}
                        onChange={(e) => setIdealCustomerProfile(e.target.value)}
                        disabled={isAiGenerating || isSaving}
                        maxLength={5000}
                        placeholder="e.g. Distributed enterprise companies requiring ergonomic workstation setups"
                        className="w-full px-3 py-2 text-xs rounded-xl bg-background border border-border/80 text-foreground resize-none disabled:opacity-50 disabled:cursor-not-allowed"
                      />
                    </div>

                    {/* Discount Guardrails */}
                    <div className="grid grid-cols-2 gap-3 pt-1">
                      <div>
                        <label className="block text-xs font-medium text-foreground mb-1">
                          Min Sales Discount (%)
                        </label>
                        <input
                          type="number"
                          min="0"
                          max="100"
                          value={minDiscountPct}
                          disabled={isAiGenerating || isSaving}
                          onChange={(e) => setMinDiscountPct(parseFloat(e.target.value) || 0)}
                          className="w-full px-3 py-2 text-xs font-mono rounded-xl bg-background border border-border/80 text-foreground disabled:opacity-50 disabled:cursor-not-allowed"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-foreground mb-1">
                          Max Sales Discount Guardrail (%)
                        </label>
                        <input
                          type="number"
                          min="0"
                          max="100"
                          value={maxDiscountPct}
                          disabled={isAiGenerating || isSaving}
                          onChange={(e) => setMaxDiscountPct(parseFloat(e.target.value) || 0)}
                          className="w-full px-3 py-2 text-xs font-mono rounded-xl bg-background border border-border/80 text-foreground disabled:opacity-50 disabled:cursor-not-allowed"
                        />
                      </div>
                    </div>
                  </div>

                  <div className="pt-2 flex justify-end gap-2">
                    <button
                      type="submit"
                      disabled={isSaving || isAiGenerating}
                      className="px-4 py-2 text-xs font-semibold rounded-xl bg-primary text-primary-foreground hover:opacity-95 flex items-center gap-1.5 shadow-xs disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {isSaving ? (
                        <>
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          Saving Changes...
                        </>
                      ) : (
                        <>
                          <CheckCircle2 className="w-3.5 h-3.5" />
                          Save Product Updates
                        </>
                      )}
                    </button>
                  </div>
                </form>
              )}

              {/* TAB 2: VARIANTS & OPTIONS */}
              {activeTab === 'variants' && (
                <div className="space-y-6">
                  {/* Options Axes */}
                  <div>
                    <h4 className="text-xs font-semibold text-foreground uppercase tracking-wider mb-2">
                      Configured Option Dimensions
                    </h4>
                    {product.options && product.options.length > 0 ? (
                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        {product.options.map((opt) => (
                          <div
                            key={opt.id}
                            className="p-3 rounded-xl border border-border/70 bg-card space-y-1.5"
                          >
                            <span className="font-semibold text-xs text-foreground block">
                              {opt.name}
                            </span>
                            <div className="flex flex-wrap gap-1">
                              {opt.values.map((v) => (
                                <span
                                  key={v.id}
                                  className="text-[10px] px-2 py-0.5 rounded-md bg-muted text-foreground font-mono"
                                >
                                  {v.value}
                                </span>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-xs text-muted-foreground p-3 rounded-xl bg-muted/20 border border-border/60">
                        No separate options configured. This product uses a single standalone SKU.
                      </div>
                    )}
                  </div>

                  {/* Variants List */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <h4 className="text-xs font-semibold text-foreground uppercase tracking-wider">
                        Active Variants & SKUs ({product.variants?.length || 0})
                      </h4>
                    </div>

                    <div className="divide-y divide-border/60 rounded-xl border border-border/80 overflow-hidden bg-background">
                      {product.variants?.map((v) => {
                        const optSummary = v.option_values.map((o) => o.value).join(', ');
                        const avail = availabilities[v.sku];
                        return (
                          <div
                            key={v.id}
                            className="p-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs"
                          >
                            <div className="space-y-1">
                              <div className="flex items-center gap-2">
                                <span className="font-mono font-bold text-foreground text-xs">
                                  {v.sku}
                                </span>
                                <span
                                  className={`text-[9px] font-mono px-1.5 py-0.2 rounded font-bold uppercase ${
                                    v.status === 'ACTIVE'
                                      ? 'bg-emerald-500/10 text-emerald-500'
                                      : 'bg-muted text-muted-foreground'
                                  }`}
                                >
                                  {v.status}
                                </span>
                              </div>
                              <div className="text-muted-foreground text-[11px]">
                                {optSummary || 'Default Option'} • Barcode:{' '}
                                <span className="font-mono">{v.barcode || 'N/A'}</span>
                              </div>
                            </div>

                            <div className="flex items-center gap-4">
                              <div className="text-right">
                                <span className="font-mono font-bold text-foreground text-xs block">
                                  ${Number(v.price).toFixed(2)} {v.currency}
                                </span>
                                <span className="text-[10px] text-muted-foreground font-mono block">
                                  {avail ? `${avail.total_available} avail` : 'Stock check...'}
                                </span>
                              </div>

                              {onOpenAdjustStock && (
                                <button
                                  type="button"
                                  onClick={() => onOpenAdjustStock(v.id)}
                                  className="px-2.5 py-1 text-[11px] font-semibold rounded-lg bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
                                >
                                  Adjust Stock
                                </button>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 3: LIVE STOCK AVAILABILITY */}
              {activeTab === 'stock' && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <h4 className="text-xs font-semibold text-foreground uppercase tracking-wider">
                        Live Cross-Location Stock Levels
                      </h4>
                      <p className="text-[11px] text-muted-foreground">
                        Availability reflects sellable stock units across active fulfillment locations
                      </p>
                    </div>
                    <button
                      onClick={() =>
                        product.variants &&
                        fetchVariantAvailabilities(product.variants.map((v) => v.sku))
                      }
                      className="px-2.5 py-1 text-xs rounded-xl bg-muted hover:bg-muted/80 text-foreground font-medium"
                    >
                      Refresh Stock
                    </button>
                  </div>

                  {loadingAvailabilities ? (
                    <div className="py-8 text-center space-y-2">
                      <Loader2 className="w-5 h-5 animate-spin text-primary mx-auto" />
                      <span className="text-xs text-muted-foreground">
                        Querying inventory ledger...
                      </span>
                    </div>
                  ) : (
                    <div className="space-y-4">
                      {product.variants?.map((variant) => {
                        const avail = availabilities[variant.sku];
                        return (
                          <div
                            key={variant.id}
                            className="p-4 rounded-xl border border-border/80 bg-background space-y-3"
                          >
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2">
                                <span className="font-mono font-bold text-xs text-foreground">
                                  {variant.sku}
                                </span>
                                <span className="text-[11px] text-muted-foreground">
                                  ({variant.option_values.map((ov) => ov.value).join(' / ') || 'Default'})
                                </span>
                              </div>
                              <div className="flex items-center gap-2">
                                <span className="text-xs font-mono font-bold text-primary">
                                  Total Available: {avail?.total_available ?? 0} units
                                </span>
                                {onOpenAdjustStock && (
                                  <button
                                    type="button"
                                    onClick={() => onOpenAdjustStock(variant.id)}
                                    className="px-2 py-0.5 text-[11px] font-semibold rounded bg-muted hover:bg-muted/80 text-foreground"
                                  >
                                    Adjust Stock
                                  </button>
                                )}
                              </div>
                            </div>

                            {/* Location Breakdown Table */}
                            {avail?.by_location && avail.by_location.length > 0 ? (
                              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                                {avail.by_location.map((loc) => (
                                  <div
                                    key={loc.location_id}
                                    className="p-2.5 rounded-lg bg-muted/30 border border-border/60 text-xs space-y-1"
                                  >
                                    <div className="flex items-center justify-between">
                                      <span className="font-semibold text-foreground truncate">
                                        {loc.location_name}
                                      </span>
                                      <span
                                        className={`font-mono text-[10px] font-bold px-1.5 py-0.2 rounded ${
                                          loc.qty_available > 0
                                            ? 'bg-emerald-500/10 text-emerald-500'
                                            : 'bg-destructive/10 text-destructive'
                                        }`}
                                      >
                                        {loc.qty_available} avail
                                      </span>
                                    </div>
                                    <div className="text-[10px] text-muted-foreground flex justify-between font-mono">
                                      <span>On Hand: {loc.qty_on_hand}</span>
                                      <span>Reserved: {loc.qty_reserved}</span>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <p className="text-xs text-muted-foreground">
                                No stock records recorded across {locations.length} fulfillment locations yet. Use "Adjust Stock" to record inbound units.
                              </p>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              {/* Danger Zone: Delete / Retire */}
              <div className="pt-6 border-t border-border/60 space-y-3">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3.5 rounded-xl border border-border/70 bg-muted/20">
                  <div>
                    <span className="text-xs font-semibold text-foreground block">
                      Product Lifecycle Removal
                    </span>
                    <p className="text-[11px] text-muted-foreground">
                      Soft-retire to deactivate while preserving ledger history, or permanently purge from database.
                    </p>
                  </div>

                  <div className="flex items-center gap-2">
                    {/* Retire Button */}
                    <button
                      type="button"
                      disabled={product?.status === 'RETIRED' || isDeleting || isSaving}
                      onClick={handleRetire}
                      className="px-3 py-1.5 text-xs font-semibold rounded-xl border border-amber-500/40 text-amber-600 dark:text-amber-400 hover:bg-amber-500/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                    >
                      {product?.status === 'RETIRED' ? 'Already Retired' : 'Retire Product'}
                    </button>

                    {/* Permanent Delete Button */}
                    {!confirmDelete ? (
                      <button
                        type="button"
                        disabled={isDeleting || isSaving}
                        onClick={() => setConfirmDelete(true)}
                        className="px-3 py-1.5 text-xs font-semibold rounded-xl border border-destructive/30 text-destructive hover:bg-destructive/10 transition-colors flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                        Permanently Delete
                      </button>
                    ) : (
                      <div className="flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => setConfirmDelete(false)}
                          className="px-2.5 py-1.5 text-xs rounded-xl border border-border text-muted-foreground hover:text-foreground cursor-pointer"
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          onClick={handlePermanentDelete}
                          disabled={isDeleting}
                          className="px-3 py-1.5 text-xs font-semibold rounded-xl bg-destructive text-destructive-foreground hover:opacity-95 transition-opacity flex items-center gap-1.5 shadow-xs cursor-pointer"
                        >
                          {isDeleting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
                          Confirm Permanent Delete
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
};
