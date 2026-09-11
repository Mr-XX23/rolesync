import React, { useState, useEffect, useRef } from 'react';
import {
  X,
  Sparkles,
  CheckCircle2,
  ChevronRight,
  ChevronLeft,
  Plus,
  Trash2,
  AlertCircle,
  Loader2,
  Boxes,
} from 'lucide-react';
import {
  catalogApi,
  type Category,
  type Location,
  type ProductOptionCreate,
  type VariantCreate,
} from '../../../api/catalogApi';
import { useToast } from '../../../context/ToastContext';

interface ProductWizardModalProps {
  isOpen: boolean;
  onClose: () => void;
  onProductCreated: () => void;
  categories: Category[];
  locations: Location[];
}

interface DynamicOptionAxis {
  id: string;
  name: string;
  values: string[];
}

interface EditableVariantCandidate {
  id: string;
  enabled: boolean;
  option_values: { optionName: string; value: string }[];
  sku: string;
  price: number;
  currency: string;
  barcode: string;
  weight?: number;
  initialStockByLocation: Record<string, number>;
  reorderAtByLocation: Record<string, number>;
}

export const ProductWizardModal: React.FC<ProductWizardModalProps> = ({
  isOpen,
  onClose,
  onProductCreated,
  categories,
  locations,
}) => {
  const toast = useToast();

  // Wizard Step (1 to 5)
  const [currentStep, setCurrentStep] = useState<number>(1);

  // Step 1: Concept & AI Intel
  const [name, setName] = useState<string>('');
  const [type, setType] = useState<'PRODUCT' | 'SERVICE'>('PRODUCT');
  const [category, setCategory] = useState<string>('');
  const [customCategory, setCustomCategory] = useState<string>('');
  const [subcategory, setSubcategory] = useState<string>('');
  const [description, setDescription] = useState<string>('');
  const [keywords, setKeywords] = useState<string[]>([]);
  const [keywordInput, setKeywordInput] = useState<string>('');
  const [useCases, setUseCases] = useState<string[]>([]);
  const [useCaseInput, setUseCaseInput] = useState<string>('');
  const [targetIndustries, setTargetIndustries] = useState<string[]>([]);
  const [targetIndustryInput, setTargetIndustryInput] = useState<string>('');
  const [valueProposition, setValueProposition] = useState<string>('');
  const [idealCustomerProfile, setIdealCustomerProfile] = useState<string>('');
  const [minDiscountStr, setMinDiscountStr] = useState<string>('0');
  const [maxDiscountStr, setMaxDiscountStr] = useState<string>('0');
  const [discountErrors, setDiscountErrors] = useState<{ min?: string; max?: string }>({});

  // AI Generation State
  const [isAiGenerating, setIsAiGenerating] = useState<boolean>(false);

  // Step 2: Dynamic Option Axes
  const [options, setOptions] = useState<DynamicOptionAxis[]>([
    { id: '1', name: 'Color', values: ['Black', 'White'] },
    { id: '2', name: 'Size', values: ['S', 'M', 'L'] },
  ]);
  const [newAxisName, setNewAxisName] = useState<string>('');
  const [axisValueInputs, setAxisValueInputs] = useState<Record<string, string>>({});

  // Step 3: Variant Grid
  const [variantsList, setVariantsList] = useState<EditableVariantCandidate[]>([]);
  const [bulkPrice, setBulkPrice] = useState<number>(199.99);

  // Step 4: Multi-Location Initial Stock Bulk
  const [bulkStockLocId, setBulkStockLocId] = useState<string>('');
  const [bulkStockQty, setBulkStockQty] = useState<number>(50);

  // Step 5: Persistence Status Engine
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [persistStep, setPersistStep] = useState<string>('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Synchronized scroll refs to keep Header (Menu) and List perfectly aligned without vertical scrollbar on header
  const step3HeaderRef = useRef<HTMLDivElement>(null);
  const step3BodyRef = useRef<HTMLDivElement>(null);
  const step4HeaderRef = useRef<HTMLDivElement>(null);
  const step4BodyRef = useRef<HTMLDivElement>(null);

  // Reset all state back to initial blank step 1
  const resetWizardState = () => {
    setCurrentStep(1);
    setName('');
    setType('PRODUCT');
    setCategory('');
    setCustomCategory('');
    setSubcategory('');
    setDescription('');
    setKeywords([]);
    setKeywordInput('');
    setUseCases([]);
    setUseCaseInput('');
    setTargetIndustries([]);
    setTargetIndustryInput('');
    setValueProposition('');
    setIdealCustomerProfile('');
    setMinDiscountStr('0');
    setMaxDiscountStr('0');
    setDiscountErrors({});
    setIsAiGenerating(false);
    setOptions([
      { id: '1', name: 'Color', values: ['Black', 'White'] },
      { id: '2', name: 'Size', values: ['S', 'M', 'L'] },
    ]);
    setNewAxisName('');
    setAxisValueInputs({});
    setVariantsList([]);
    setBulkPrice(199.99);
    setBulkStockLocId('');
    setBulkStockQty(50);
    setIsSubmitting(false);
    setPersistStep('');
    setErrorMessage(null);
  };

  const handleCloseModal = () => {
    if (isAiGenerating || isSubmitting) return;
    resetWizardState();
    onClose();
  };

  // Automatically clear inputs whenever wizard is opened
  useEffect(() => {
    if (isOpen) {
      resetWizardState();
    }
  }, [isOpen]);

  if (!isOpen) return null;

  // Helper to parse custom category with comma/space separation
  const parseCustomCategoryInput = (raw: string) => {
    if (!raw.includes(',')) {
      return { category: raw.trim(), subcategory: '' };
    }
    const parts = raw.split(',');
    const cat = parts[0].trim();
    const sub = parts.slice(1).join(',').trim();
    return { category: cat, subcategory: sub };
  };

  const parsedCustom = parseCustomCategoryInput(customCategory);
  const activeCategory = category === '__custom__' ? parsedCustom.category : category;
  const activeSubcategory = category === '__custom__' ? (parsedCustom.subcategory || subcategory.trim()) : subcategory.trim();

  // Client-side SQL injection sanitization test
  const SQL_INJECTION_PATTERN = /(\b(UNION(\s+ALL)?|SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|EXEC(UTE)?)\b[\s\S]*?\b(FROM|INTO|TABLE|DATABASE|WHERE|SET|VALUES)\b)|(--|\bOR\b\s+['"0-9]+=['"0-9]+|\bAND\b\s+['"0-9]+=['"0-9]+|;\s*(DROP|SELECT|INSERT|UPDATE|DELETE))/i;

  const validateSecurity = (val: string, fieldName: string): string | null => {
    if (SQL_INJECTION_PATTERN.test(val)) {
      return `Unsafe SQL injection pattern detected in ${fieldName}.`;
    }
    return null;
  };

  // Threshold readiness check for AI auto-generation
  const isAiEligible =
    name.trim().length >= 3 &&
    Boolean(type) &&
    Boolean(activeCategory.trim()) &&
    description.trim().length >= 200;

  // AI Findability Auto-Generator with mandatory thresholds
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
    if (!activeCategory.trim()) {
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
      validateSecurity(activeCategory, 'Category') ||
      validateSecurity(activeSubcategory, 'Subcategory') ||
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
        category: activeCategory.trim(),
        subcategory: activeSubcategory.trim() || undefined,
        description: description.trim(),
      });

      if (generated.keywords && generated.keywords.length > 0) {
        setKeywords(generated.keywords);
      }
      if (generated.use_cases && generated.use_cases.length > 0) {
        setUseCases(generated.use_cases);
      }
      if (generated.target_industries && generated.target_industries.length > 0) {
        setTargetIndustries(generated.target_industries);
      }
      if (generated.value_proposition) {
        setValueProposition(generated.value_proposition);
      }
      if (generated.ideal_customer_profile) {
        setIdealCustomerProfile(generated.ideal_customer_profile);
      }
      if (generated.min_discount_pct !== undefined && generated.min_discount_pct !== null) {
        setMinDiscountStr(String(generated.min_discount_pct));
      }
      if (generated.max_discount_pct !== undefined && generated.max_discount_pct !== null) {
        setMaxDiscountStr(String(generated.max_discount_pct));
      }

      toast.success('AI successfully populated findability keywords, use cases & ICP!', 'AI Intelligence Generated');
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Failed to generate AI intelligence.';
      toast.error(msg, 'AI Generation Failed');
    } finally {
      setIsAiGenerating(false);
    }
  };

  // Helper to generate Cartesian product
  const computeCartesianCandidates = (axes: DynamicOptionAxis[], prodName: string) => {
    const validAxes = axes.filter((a) => a.name.trim() && a.values.length > 0);
    if (validAxes.length === 0) {
      // Default single variant
      const cleanSku = (prodName || 'PROD')
        .replace(/[^a-zA-Z0-9]/g, '-')
        .toUpperCase()
        .slice(0, 16);
      return [
        {
          id: 'single-1',
          enabled: true,
          option_values: [],
          sku: `${cleanSku}-STD`,
          price: 99.0,
          currency: 'USD',
          barcode: '',
          initialStockByLocation: {},
          reorderAtByLocation: {},
        },
      ];
    }

    const cartesian = (items: DynamicOptionAxis[]): { optionName: string; value: string }[][] => {
      if (items.length === 0) return [[]];
      const [first, ...rest] = items;
      const restCombos = cartesian(rest);
      const results: { optionName: string; value: string }[][] = [];
      for (const val of first.values) {
        for (const r of restCombos) {
          results.push([{ optionName: first.name, value: val }, ...r]);
        }
      }
      return results;
    };

    const combinations = cartesian(validAxes);
    const cleanPrefix = (prodName || 'PROD')
      .replace(/[^a-zA-Z0-9]/g, '-')
      .toUpperCase()
      .slice(0, 12);

    return combinations.map((combo, idx) => {
      const skuSuffix = combo
        .map((c) => c.value.replace(/[^a-zA-Z0-9]/g, '').toUpperCase().slice(0, 4))
        .join('-');
      return {
        id: `var-${idx}-${Date.now()}`,
        enabled: true,
        option_values: combo,
        sku: `${cleanPrefix}-${skuSuffix}`,
        price: 149.0,
        currency: 'USD',
        barcode: '',
        initialStockByLocation: {},
        reorderAtByLocation: {},
      };
    });
  };

  // Step 2 Handlers
  const handleAddAxis = () => {
    if (newAxisName.trim()) {
      setOptions([
        ...options,
        { id: String(Date.now()), name: newAxisName.trim(), values: [] },
      ]);
      setNewAxisName('');
    }
  };

  const handleRemoveAxis = (axisId: string) => {
    setOptions(options.filter((o) => o.id !== axisId));
  };

  const handleAddOptionValue = (axisId: string) => {
    const val = axisValueInputs[axisId]?.trim();
    if (!val) return;
    setOptions(
      options.map((o) =>
        o.id === axisId && !o.values.includes(val)
          ? { ...o, values: [...o.values, val] }
          : o
      )
    );
    setAxisValueInputs({ ...axisValueInputs, [axisId]: '' });
  };

  const handleRemoveOptionValue = (axisId: string, valueToRemove: string) => {
    setOptions(
      options.map((o) =>
        o.id === axisId
          ? { ...o, values: o.values.filter((v) => v !== valueToRemove) }
          : o
      )
    );
  };

  // Navigating to Step 3: compute Cartesian candidate grid
  const handleGoToStep3 = () => {
    const candidates = computeCartesianCandidates(options, name);
    setVariantsList(candidates);
    setCurrentStep(3);
  };

  // Bulk Apply Price in Step 3
  const handleApplyBulkPrice = () => {
    setVariantsList(
      variantsList.map((v) => (v.enabled ? { ...v, price: bulkPrice } : v))
    );
    toast.success(`Applied $${bulkPrice.toFixed(2)} to all enabled variants.`, 'Price Updated');
  };

  // Bulk Apply Stock in Step 4
  const handleApplyBulkStock = () => {
    if (!bulkStockLocId) {
      toast.warning('Please select a target location for bulk stock apply.');
      return;
    }
    setVariantsList(
      variantsList.map((v) =>
        v.enabled
          ? {
              ...v,
              initialStockByLocation: {
                ...v.initialStockByLocation,
                [bulkStockLocId]: bulkStockQty,
              },
            }
          : v
      )
    );
    const locName = locations.find((l) => l.id === bulkStockLocId)?.name || 'Location';
    toast.success(
      `Set ${bulkStockQty} units at ${locName} for all enabled variants.`,
      'Stock Preset Applied'
    );
  };

  // Step 5: Launch Sequential Persistence Pipeline
  const handleSaveAndLaunch = async () => {
    setIsSubmitting(true);
    setErrorMessage(null);

    // Validate inputs & lengths
    if (name.trim().length < 3) {
      setErrorMessage('Product / Service Name must be at least 3 characters.');
      setIsSubmitting(false);
      return;
    }
    if (name.trim().length > 255) {
      setErrorMessage('Product / Service Name cannot exceed 255 characters.');
      setIsSubmitting(false);
      return;
    }
    if (!activeCategory.trim()) {
      setErrorMessage('Primary Category is required.');
      setIsSubmitting(false);
      return;
    }
    if (activeCategory.length > 100) {
      setErrorMessage('Category cannot exceed 100 characters.');
      setIsSubmitting(false);
      return;
    }
    if (activeSubcategory && activeSubcategory.length > 100) {
      setErrorMessage('Subcategory cannot exceed 100 characters.');
      setIsSubmitting(false);
      return;
    }
    if (description && description.length > 10000) {
      setErrorMessage('Description cannot exceed 10,000 characters.');
      setIsSubmitting(false);
      return;
    }
    if (valueProposition && valueProposition.length > 5000) {
      setErrorMessage('Value Proposition cannot exceed 5,000 characters.');
      setIsSubmitting(false);
      return;
    }
    if (idealCustomerProfile && idealCustomerProfile.length > 5000) {
      setErrorMessage('Ideal Customer Profile cannot exceed 5,000 characters.');
      setIsSubmitting(false);
      return;
    }

    // SQL Injection Security Validation
    const secErr =
      validateSecurity(name, 'Product Name') ||
      validateSecurity(activeCategory, 'Category') ||
      validateSecurity(activeSubcategory, 'Subcategory') ||
      validateSecurity(description, 'Description') ||
      validateSecurity(valueProposition, 'Value Proposition') ||
      validateSecurity(idealCustomerProfile, 'Ideal Customer Profile');
    if (secErr) {
      setErrorMessage(secErr);
      setIsSubmitting(false);
      return;
    }

    for (const kw of keywords) {
      const err = validateSecurity(kw, 'Keyword');
      if (err) { setErrorMessage(err); setIsSubmitting(false); return; }
    }
    for (const uc of useCases) {
      const err = validateSecurity(uc, 'Use Case');
      if (err) { setErrorMessage(err); setIsSubmitting(false); return; }
    }
    for (const ti of targetIndustries) {
      const err = validateSecurity(ti, 'Target Industry');
      if (err) { setErrorMessage(err); setIsSubmitting(false); return; }
    }

    const enabledVariants = variantsList.filter((v) => v.enabled);
    if (enabledVariants.length === 0) {
      setErrorMessage('At least one variant must be enabled to create product.');
      setIsSubmitting(false);
      return;
    }

    for (const v of enabledVariants) {
      const vErr = validateSecurity(v.sku, 'Variant SKU') || validateSecurity(v.barcode, 'Barcode');
      if (vErr) {
        setErrorMessage(vErr);
        setIsSubmitting(false);
        return;
      }
    }

    try {
      // 1. Create Product & ensure category
      setPersistStep('1/4: Registering Product Concept in Catalog...');

      let finalCategoryKey = activeCategory;
      if (category === '__custom__' && activeCategory) {
        const generatedKey = activeCategory
          .toLowerCase()
          .replace(/[^a-z0-9]/g, '_')
          .slice(0, 50);
        try {
          await catalogApi.createCategory({
            key: generatedKey,
            label: activeCategory,
          });
          finalCategoryKey = generatedKey;
        } catch {
          finalCategoryKey = generatedKey;
        }
      }

      const parsedMinDiscount = Math.max(0, Math.min(100, parseFloat(minDiscountStr) || 0));
      const parsedMaxDiscount = Math.max(0, Math.min(100, parseFloat(maxDiscountStr) || 0));

      const productInput = {
        name: name.trim(),
        type,
        category: finalCategoryKey,
        subcategory: activeSubcategory || undefined,
        status: 'ACTIVE' as const,
        description: description.trim() || undefined,
        keywords,
        use_cases: useCases,
        target_industries: targetIndustries,
        value_proposition: valueProposition.trim() || undefined,
        ideal_customer_profile: idealCustomerProfile.trim() || undefined,
        min_discount_pct: parsedMinDiscount,
        max_discount_pct: parsedMaxDiscount,
      };

      const createdProduct = await catalogApi.createProduct(productInput);
      const productId = createdProduct.id;

      // 2. Set Product Options (if any)
      const validOptions: ProductOptionCreate[] = options
        .filter((o) => o.name.trim() && o.values.length > 0)
        .map((o, idx) => ({
          name: o.name.trim(),
          position: idx,
          values: o.values.map((v, vIdx) => ({ value: v, position: vIdx })),
        }));

      let persistedOptions = createdProduct.options || [];
      if (validOptions.length > 0) {
        setPersistStep('2/4: Configuring Multi-Axis Option Matrix...');
        persistedOptions = await catalogApi.setProductOptions(productId, validOptions);
      }

      // Map option values to their generated UUIDs
      const valueNameToIdMap: Record<string, string> = {};
      persistedOptions.forEach((opt) => {
        opt.values.forEach((v) => {
          valueNameToIdMap[`${opt.name}:${v.value}`] = v.id;
        });
      });

      // 3. Upsert Enabled Variants
      setPersistStep('3/4: Creating Variants and SKUs in Database...');
      const variantsToCreate: VariantCreate[] = enabledVariants.map((v) => {
        const optionValueIds: string[] = [];
        v.option_values.forEach((ov) => {
          const matchedId = valueNameToIdMap[`${ov.optionName}:${ov.value}`];
          if (matchedId) optionValueIds.push(matchedId);
        });

        return {
          sku: v.sku.trim(),
          barcode: v.barcode.trim() || undefined,
          price: v.price,
          currency: v.currency,
          weight: v.weight,
          status: 'ACTIVE' as const,
          option_value_ids: optionValueIds,
        };
      });

      const persistedVariants = await catalogApi.upsertVariants(productId, variantsToCreate);

      // 4. Initial Stock Allocation
      setPersistStep('4/4: Initializing Stock Levels in Ledger...');
      const skuToVariantMap: Record<string, string> = {};
      persistedVariants.forEach((pv) => {
        skuToVariantMap[pv.sku] = pv.id;
      });

      const stockItemsToSet: Array<{
        variant_id: string;
        location_id: string;
        qty: number;
        reason: 'RESTOCK';
        note: string;
      }> = [];

      for (const variantCandidate of enabledVariants) {
        const variantId = skuToVariantMap[variantCandidate.sku];
        if (!variantId) continue;

        for (const [locId, qty] of Object.entries(variantCandidate.initialStockByLocation)) {
          if (qty > 0) {
            stockItemsToSet.push({
              variant_id: variantId,
              location_id: locId,
              qty,
              reason: 'RESTOCK',
              note: 'Initial Stock Genesis Allocation via Creation Wizard',
            });
          }
        }
      }

      if (stockItemsToSet.length > 0) {
        try {
          await catalogApi.batchSetStock(stockItemsToSet);
        } catch (batchStockErr) {
          console.warn('[ProductWizardModal] Batch stock set failed, falling back to sequential calls:', batchStockErr);
          for (const item of stockItemsToSet) {
            try {
              await catalogApi.setStock(item);
            } catch (stockErr) {
              console.warn(`Failed to set stock for variant ${item.variant_id} at ${item.location_id}:`, stockErr);
            }
          }
        }
      }

      toast.success(
        `Successfully created "${createdProduct.name}" with ${persistedVariants.length} variants!`,
        'Catalog Launch Successful'
      );
      resetWizardState();
      onProductCreated();
      onClose();
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Creation pipeline failed.';
      setErrorMessage(msg);
      toast.error(msg, 'Launch Failed');
    } finally {
      setIsSubmitting(false);
      setPersistStep('');
    }
  };

  const stepsHeader = [
    { num: 1, title: 'Concept & AI Intel' },
    { num: 2, title: 'Options & Attributes' },
    { num: 3, title: 'Variant Grid' },
    { num: 4, title: 'Initial Stock' },
    { num: 5, title: 'Review & Save' },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs animate-in fade-in duration-200">
      <div className="relative w-full max-w-5xl bg-card border border-border/80 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[92vh]">
        {/* Top Header */}
        <div className="px-6 py-4 border-b border-border/60 flex items-center justify-between bg-card/80">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
              <Boxes className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-foreground tracking-wide font-sans">
                Product Creation Wizard
              </h3>
              <p className="text-xs text-muted-foreground">
                Create products, configure variant options, and set multi-location stock
              </p>
            </div>
          </div>
          <button
            onClick={handleCloseModal}
            disabled={isAiGenerating || isSubmitting}
            title={isAiGenerating ? 'Generating AI intelligence, please wait...' : 'Close Wizard'}
            className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Stepper Bar */}
        <div className="px-6 py-3 border-b border-border/60 bg-muted/20 flex items-center justify-between overflow-x-auto gap-2">
          {stepsHeader.map((st) => (
            <div
              key={st.num}
              className={`flex items-center gap-2 shrink-0 ${
                currentStep === st.num
                  ? 'text-primary font-bold'
                  : currentStep > st.num
                  ? 'text-foreground'
                  : 'text-muted-foreground/60'
              }`}
            >
              <div
                className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-mono font-bold transition-all ${
                  currentStep === st.num
                    ? 'bg-primary text-primary-foreground shadow-xs'
                    : currentStep > st.num
                    ? 'bg-emerald-500/20 text-emerald-500 border border-emerald-500/40'
                    : 'bg-muted text-muted-foreground'
                }`}
              >
                {currentStep > st.num ? '✓' : st.num}
              </div>
              <span className="text-xs truncate">{st.title}</span>
              {st.num < 5 && <ChevronRight className="w-3.5 h-3.5 text-muted-foreground/40 ml-1" />}
            </div>
          ))}
        </div>

        {/* Wizard Step Body */}
        <div className="p-6 overflow-y-auto flex-1 space-y-5">
          {errorMessage && (
            <div className="p-3.5 rounded-xl bg-destructive/10 border border-destructive/25 text-destructive text-xs flex items-start gap-2">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{errorMessage}</span>
            </div>
          )}

          {/* STEP 1: CONCEPT & AI FINDABILITY */}
          {currentStep === 1 && (
            <div className="space-y-5 animate-in fade-in duration-200">
              {/* AI Generating Alert Banner */}
              {isAiGenerating && (
                <div className="p-3.5 rounded-xl bg-primary/10 border border-primary/30 text-primary text-xs flex items-center gap-3 animate-pulse">
                  <Loader2 className="w-4 h-4 animate-spin shrink-0" />
                  <div className="flex-1 font-medium">
                    AI Agent is analyzing title, type, category & description to generate keywords, use cases, target industries, and ideal customer profile...
                  </div>
                  <span className="text-[10px] uppercase font-mono tracking-wider font-semibold opacity-70">
                    Locked
                  </span>
                </div>
              )}

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div className="sm:col-span-2">
                  <label className="block text-xs font-semibold text-foreground mb-2">
                    Product / Service Title *
                  </label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    disabled={isAiGenerating}
                    maxLength={255}
                    required
                    placeholder="e.g. Aeron Ergonomic Executive Chair (min 3 chars)"
                    className="w-full px-4 py-3 text-sm rounded-xl bg-background border border-border/80 text-foreground placeholder:text-muted-foreground/60 focus:outline-hidden focus:ring-2 focus:ring-primary/40 disabled:opacity-50 disabled:cursor-not-allowed"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-foreground mb-2">
                    Catalog Item Type
                  </label>
                  <select
                    value={type}
                    onChange={(e) => setType(e.target.value as any)}
                    disabled={isAiGenerating}
                    className="w-full px-4 py-3 text-sm rounded-xl bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <option value="PRODUCT">PRODUCT (Physical Good)</option>
                    <option value="SERVICE">SERVICE (Subscription / Labor)</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-foreground mb-2">
                    Category *
                  </label>
                  <select
                    value={category}
                    onChange={(e) => setCategory(e.target.value)}
                    disabled={isAiGenerating}
                    className="w-full px-4 py-3 text-sm rounded-xl bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <option value="">Select Controlled Category</option>
                    {categories.map((c) => (
                      <option key={c.id} value={c.key}>
                        {c.label} ({c.key})
                      </option>
                    ))}
                    <option value="__custom__">+ Add Custom Category</option>
                  </select>
                </div>

                {category === '__custom__' ? (
                  <div>
                    <label className="block text-xs font-semibold text-foreground mb-2">
                      New Category Key * (e.g. Category, Subcategory)
                    </label>
                    <input
                      type="text"
                      value={customCategory}
                      onChange={(e) => setCustomCategory(e.target.value)}
                      disabled={isAiGenerating}
                      maxLength={100}
                      placeholder="e.g. Ear bud, TWS (use comma to split category & subcategory)"
                      className="w-full px-4 py-3 text-sm rounded-xl bg-background border border-border/80 text-foreground placeholder:text-muted-foreground/60 focus:outline-hidden focus:ring-2 focus:ring-primary/40 disabled:opacity-50 disabled:cursor-not-allowed"
                    />
                    {customCategory.includes(',') && (
                      <div className="mt-2 flex items-center gap-2 text-xs animate-in fade-in flex-wrap">
                        <span className="px-2.5 py-1 rounded-lg bg-primary/10 text-primary border border-primary/20 font-medium flex items-center gap-1.5">
                          <span>📁 Category:</span>
                          <strong>{parseCustomCategoryInput(customCategory).category || '—'}</strong>
                        </span>
                        <span className="text-muted-foreground/60">•</span>
                        <span className="px-2.5 py-1 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium flex items-center gap-1.5">
                          <span>🏷️ Subcategory:</span>
                          <strong>{parseCustomCategoryInput(customCategory).subcategory || '—'}</strong>
                        </span>
                      </div>
                    )}
                  </div>
                ) : (
                  <div>
                    <label className="block text-xs font-semibold text-foreground mb-2">
                      Subcategory (Optional)
                    </label>
                    <input
                      type="text"
                      value={subcategory}
                      onChange={(e) => setSubcategory(e.target.value)}
                      disabled={isAiGenerating}
                      maxLength={100}
                      placeholder="e.g. executive_seating (not required)"
                      className="w-full px-4 py-3 text-sm rounded-xl bg-background border border-border/80 text-foreground placeholder:text-muted-foreground/60 focus:outline-hidden focus:ring-2 focus:ring-primary/40 disabled:opacity-50 disabled:cursor-not-allowed"
                    />
                  </div>
                )}
              </div>

              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="block text-xs font-semibold text-foreground">
                    Product Description *
                  </label>
                  <span className="text-[11px] text-muted-foreground">
                    Detailed specs, materials, and selling points
                  </span>
                </div>
                <textarea
                  rows={5}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  disabled={isAiGenerating}
                  maxLength={10000}
                  placeholder="Detailed description of features, materials, technical specifications, and warranty coverage... (Minimum 200 characters required to Auto-Generate with AI)"
                  className="w-full min-h-[130px] px-4 py-3 text-sm rounded-xl bg-background border border-border/80 text-foreground placeholder:text-muted-foreground/60 focus:outline-hidden focus:ring-2 focus:ring-primary/40 resize-y leading-relaxed disabled:opacity-50 disabled:cursor-not-allowed"
                />
                <div className="flex items-center justify-between text-xs mt-1.5 px-1">
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

              {/* AI Findability Fields */}
              <div className="p-4 rounded-xl bg-muted/20 border border-border/70 space-y-4">
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <div className="flex items-center gap-2 text-xs font-semibold text-foreground uppercase tracking-wider">
                    <Sparkles className="w-4 h-4 text-primary" />
                    AI Agent Findability & Sales Knowledge
                  </div>
                  <div className="flex items-center gap-2">
                    {!isAiEligible && (
                      <span className="text-[11px] text-amber-500 font-medium hidden sm:inline">
                        {name.trim().length < 3
                          ? 'Name (min 3 chars)'
                          : !activeCategory.trim()
                          ? 'Primary category required'
                          : description.trim().length < 200
                          ? `Description (${description.trim().length}/200)`
                          : ''}
                      </span>
                    )}
                    <button
                      type="button"
                      onClick={handleGenerateAiFindability}
                      disabled={isAiGenerating}
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
                          <span>Generating Intelligence...</span>
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

                {/* Keywords Tags */}
                <div>
                  <label className="block text-xs font-semibold text-foreground mb-2">
                    Search Keywords (press Enter to add)
                  </label>
                  <div className="flex gap-2 mb-2">
                    <input
                      type="text"
                      value={keywordInput}
                      onChange={(e) => setKeywordInput(e.target.value)}
                      disabled={isAiGenerating}
                      maxLength={255}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          if (!isAiGenerating && keywordInput.trim() && !keywords.includes(keywordInput.trim())) {
                            setKeywords([...keywords, keywordInput.trim()]);
                            setKeywordInput('');
                          }
                        }
                      }}
                      placeholder="e.g. mesh back, posture, desk chair"
                      className="flex-1 px-4 py-2.5 text-sm rounded-xl bg-background border border-border/80 text-foreground placeholder:text-muted-foreground/60 focus:outline-hidden focus:ring-2 focus:ring-primary/40 disabled:opacity-50 disabled:cursor-not-allowed"
                    />
                    <button
                      type="button"
                      disabled={isAiGenerating}
                      onClick={() => {
                        if (keywordInput.trim() && !keywords.includes(keywordInput.trim())) {
                          setKeywords([...keywords, keywordInput.trim()]);
                          setKeywordInput('');
                        }
                      }}
                      className="px-4 py-2 text-xs rounded-xl bg-muted text-foreground font-semibold hover:bg-muted/80 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Add
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {keywords.map((kw, idx) => (
                      <span
                        key={idx}
                        className="text-xs px-2.5 py-1 rounded-md bg-primary/10 text-primary border border-primary/20 flex items-center gap-1.5 font-medium"
                      >
                        {kw}
                        <button
                          type="button"
                          disabled={isAiGenerating}
                          onClick={() => setKeywords(keywords.filter((_, i) => i !== idx))}
                          className="hover:text-destructive text-sm disabled:opacity-50 disabled:pointer-events-none"
                        >
                          &times;
                        </button>
                      </span>
                    ))}
                  </div>
                </div>

                {/* Use Cases Tags */}
                <div>
                  <label className="block text-xs font-semibold text-foreground mb-2">
                    Key Use Cases (press Enter to add)
                  </label>
                  <div className="flex gap-2 mb-2">
                    <input
                      type="text"
                      value={useCaseInput}
                      onChange={(e) => setUseCaseInput(e.target.value)}
                      disabled={isAiGenerating}
                      maxLength={255}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          if (!isAiGenerating && useCaseInput.trim() && !useCases.includes(useCaseInput.trim())) {
                            setUseCases([...useCases, useCaseInput.trim()]);
                            setUseCaseInput('');
                          }
                        }
                      }}
                      placeholder="e.g. 8+ hour continuous desk work, lower back pain relief"
                      className="flex-1 px-4 py-2.5 text-sm rounded-xl bg-background border border-border/80 text-foreground placeholder:text-muted-foreground/60 focus:outline-hidden focus:ring-2 focus:ring-primary/40 disabled:opacity-50 disabled:cursor-not-allowed"
                    />
                    <button
                      type="button"
                      disabled={isAiGenerating}
                      onClick={() => {
                        if (useCaseInput.trim() && !useCases.includes(useCaseInput.trim())) {
                          setUseCases([...useCases, useCaseInput.trim()]);
                          setUseCaseInput('');
                        }
                      }}
                      className="px-4 py-2 text-xs rounded-xl bg-muted text-foreground font-semibold hover:bg-muted/80 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Add
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {useCases.map((uc, idx) => (
                      <span
                        key={idx}
                        className="text-xs px-2.5 py-1 rounded-md bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20 flex items-center gap-1.5 font-medium"
                      >
                        {uc}
                        <button
                          type="button"
                          disabled={isAiGenerating}
                          onClick={() => setUseCases(useCases.filter((_, i) => i !== idx))}
                          className="hover:text-destructive text-sm disabled:opacity-50 disabled:pointer-events-none"
                        >
                          &times;
                        </button>
                      </span>
                    ))}
                  </div>
                </div>

                {/* Target Industries Tags */}
                <div>
                  <label className="block text-xs font-semibold text-foreground mb-2">
                    Target Industries (press Enter to add)
                  </label>
                  <div className="flex gap-2 mb-2">
                    <input
                      type="text"
                      value={targetIndustryInput}
                      onChange={(e) => setTargetIndustryInput(e.target.value)}
                      disabled={isAiGenerating}
                      maxLength={255}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          if (!isAiGenerating && targetIndustryInput.trim() && !targetIndustries.includes(targetIndustryInput.trim())) {
                            setTargetIndustries([...targetIndustries, targetIndustryInput.trim()]);
                            setTargetIndustryInput('');
                          }
                        }
                      }}
                      placeholder="e.g. Tech, Healthcare, Architecture"
                      className="flex-1 px-4 py-2.5 text-sm rounded-xl bg-background border border-border/80 text-foreground placeholder:text-muted-foreground/60 focus:outline-hidden focus:ring-2 focus:ring-primary/40 disabled:opacity-50 disabled:cursor-not-allowed"
                    />
                    <button
                      type="button"
                      disabled={isAiGenerating}
                      onClick={() => {
                        if (targetIndustryInput.trim() && !targetIndustries.includes(targetIndustryInput.trim())) {
                          setTargetIndustries([...targetIndustries, targetIndustryInput.trim()]);
                          setTargetIndustryInput('');
                        }
                      }}
                      className="px-4 py-2 text-xs rounded-xl bg-muted text-foreground font-semibold hover:bg-muted/80 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Add
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {targetIndustries.map((ti, tiIdx) => (
                      <span
                        key={tiIdx}
                        className="text-xs px-2.5 py-1 rounded-md bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 border border-indigo-500/20 flex items-center gap-1.5 font-medium"
                      >
                        {ti}
                        <button
                          type="button"
                          disabled={isAiGenerating}
                          onClick={() => setTargetIndustries(targetIndustries.filter((_, i) => i !== tiIdx))}
                          className="hover:text-destructive text-sm disabled:opacity-50 disabled:pointer-events-none"
                        >
                          &times;
                        </button>
                      </span>
                    ))}
                  </div>
                </div>

                {/* Value Proposition */}
                <div>
                  <label className="block text-xs font-semibold text-foreground mb-2">
                    Value Proposition Statement
                  </label>
                  <textarea
                    rows={2}
                    value={valueProposition}
                    onChange={(e) => setValueProposition(e.target.value)}
                    disabled={isAiGenerating}
                    maxLength={5000}
                    placeholder="e.g. Reduces lumbar fatigue by 40% with patented dynamic spine mesh"
                    className="w-full px-4 py-2.5 text-sm rounded-xl bg-background border border-border/80 text-foreground placeholder:text-muted-foreground/60 focus:outline-hidden focus:ring-2 focus:ring-primary/40 resize-none disabled:opacity-50 disabled:cursor-not-allowed"
                  />
                </div>

                {/* Ideal Customer Profile */}
                <div>
                  <label className="block text-xs font-semibold text-foreground mb-2">
                    Ideal Customer Profile (ICP)
                  </label>
                  <textarea
                    rows={2}
                    value={idealCustomerProfile}
                    onChange={(e) => setIdealCustomerProfile(e.target.value)}
                    disabled={isAiGenerating}
                    maxLength={5000}
                    placeholder="e.g. Mid-to-enterprise tech companies outfitting ergonomic remote workforces"
                    className="w-full px-4 py-2.5 text-sm rounded-xl bg-background border border-border/80 text-foreground placeholder:text-muted-foreground/60 focus:outline-hidden focus:ring-2 focus:ring-primary/40 resize-none disabled:opacity-50 disabled:cursor-not-allowed"
                  />
                </div>

                {/* Discount Guardrails - String Inputs without number controllers */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-1">
                  <div>
                    <label className="block text-xs font-semibold text-foreground mb-2">
                      Min Discount Allowance (%)
                    </label>
                    <div className="relative">
                      <input
                        type="text"
                        inputMode="decimal"
                        value={minDiscountStr}
                        disabled={isAiGenerating}
                        onChange={(e) => {
                          const sanitized = e.target.value.replace(/[^0-9.]/g, '');
                          setMinDiscountStr(sanitized);
                          const num = parseFloat(sanitized);
                          if (sanitized && (isNaN(num) || num < 0 || num > 100)) {
                            setDiscountErrors((prev) => ({ ...prev, min: 'Must be between 0% and 100%' }));
                          } else {
                            setDiscountErrors((prev) => ({ ...prev, min: undefined }));
                          }
                        }}
                        placeholder="0"
                        className={`w-full px-4 py-3 pr-8 text-sm rounded-xl bg-background border ${
                          discountErrors.min ? 'border-destructive' : 'border-border/80'
                        } text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40 disabled:opacity-50 disabled:cursor-not-allowed`}
                      />
                      <span className="absolute right-3.5 top-1/2 -translate-y-1/2 text-xs font-bold text-muted-foreground pointer-events-none">
                        %
                      </span>
                    </div>
                    {discountErrors.min && (
                      <p className="text-[11px] text-destructive mt-1 flex items-center gap-1">
                        <AlertCircle className="w-3 h-3" />
                        {discountErrors.min}
                      </p>
                    )}
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-foreground mb-2">
                      Max Deal Discount Guardrail (%)
                    </label>
                    <div className="relative">
                      <input
                        type="text"
                        inputMode="decimal"
                        value={maxDiscountStr}
                        disabled={isAiGenerating}
                        onChange={(e) => {
                          const sanitized = e.target.value.replace(/[^0-9.]/g, '');
                          setMaxDiscountStr(sanitized);
                          const num = parseFloat(sanitized);
                          if (sanitized && (isNaN(num) || num < 0 || num > 100)) {
                            setDiscountErrors((prev) => ({ ...prev, max: 'Must be between 0% and 100%' }));
                          } else {
                            setDiscountErrors((prev) => ({ ...prev, max: undefined }));
                          }
                        }}
                        placeholder="0"
                        className={`w-full px-4 py-3 pr-8 text-sm rounded-xl bg-background border ${
                          discountErrors.max ? 'border-destructive' : 'border-border/80'
                        } text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40 disabled:opacity-50 disabled:cursor-not-allowed`}
                      />
                      <span className="absolute right-3.5 top-1/2 -translate-y-1/2 text-xs font-bold text-muted-foreground pointer-events-none">
                        %
                      </span>
                    </div>
                    {discountErrors.max && (
                      <p className="text-[11px] text-destructive mt-1 flex items-center gap-1">
                        <AlertCircle className="w-3 h-3" />
                        {discountErrors.max}
                      </p>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* STEP 2: DEFINE OPTIONS */}
          {currentStep === 2 && (
            <div className="space-y-5 animate-in fade-in duration-200">
              <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
                <div>
                  <h4 className="text-base font-bold text-foreground tracking-wide font-sans">
                    Product Options & Attributes
                  </h4>
                  <p className="text-xs text-muted-foreground">
                    Add variation choices like Size, Color, or Material to generate variants.
                  </p>
                </div>
                {/* Candidate multiplier counter - crisp and visible */}
                <div className="px-4 py-2 rounded-xl bg-primary/15 border border-primary/35 text-primary text-xs font-sans font-bold flex items-center gap-2 shadow-xs tracking-wide">
                  <Sparkles className="w-4 h-4 text-primary" />
                  <span className="text-sm font-extrabold text-foreground">
                    {options
                      .filter((o) => o.values.length > 0)
                      .map((o) => o.values.length)
                      .reduce((a, b) => a * b, options.some((o) => o.values.length > 0) ? 1 : 0)}
                  </span>
                  <span>
                    {options
                      .filter((o) => o.values.length > 0)
                      .map((o) => o.values.length)
                      .reduce((a, b) => a * b, options.some((o) => o.values.length > 0) ? 1 : 0) === 1
                      ? 'Candidate Expected'
                      : 'Candidates Expected'}
                  </span>
                </div>
              </div>

              {/* Add New Axis Bar */}
              <div className="p-4 rounded-xl bg-muted/30 border border-border/70 flex flex-col sm:flex-row gap-3 items-stretch sm:items-center">
                <input
                  type="text"
                  value={newAxisName}
                  onChange={(e) => setNewAxisName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      if (newAxisName.trim()) {
                        handleAddAxis();
                      }
                    }
                  }}
                  placeholder="e.g. Material, Edition, Voltage, Storage..."
                  className="flex-1 px-4 py-3 text-sm rounded-xl bg-background border border-border/80 text-foreground placeholder:text-muted-foreground/60 focus:outline-hidden focus:ring-2 focus:ring-primary/40"
                />
                <button
                  type="button"
                  disabled={!newAxisName.trim()}
                  onClick={handleAddAxis}
                  className="px-5 py-3 text-xs font-semibold rounded-xl bg-primary text-primary-foreground hover:opacity-95 active:scale-98 flex items-center justify-center gap-2 shadow-xs cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed transition-all shrink-0"
                >
                  <Plus className="w-4 h-4" />
                  Add Option Axis
                </button>
              </div>

              {/* Existing Axes List */}
              <div className="space-y-4">
                {options.map((axis) => (
                  <div
                    key={axis.id}
                    className="p-5 rounded-xl border border-border/80 bg-background space-y-4 shadow-2xs"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-xs text-foreground uppercase tracking-wider font-mono">
                        Axis: {axis.name}
                      </span>
                      <button
                        type="button"
                        onClick={() => handleRemoveAxis(axis.id)}
                        className="text-xs text-destructive hover:underline flex items-center gap-1.5 font-medium transition-colors"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                        Remove Axis
                      </button>
                    </div>

                    {/* Value input */}
                    <div className="flex flex-col sm:flex-row gap-2.5">
                      <input
                        type="text"
                        value={axisValueInputs[axis.id] || ''}
                        onChange={(e) =>
                          setAxisValueInputs({ ...axisValueInputs, [axis.id]: e.target.value })
                        }
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault();
                            handleAddOptionValue(axis.id);
                          }
                        }}
                        placeholder={`Type a ${axis.name} value and press Enter (e.g. ${
                          axis.name === 'Size' ? 'XL' : axis.name === 'Color' ? 'Silver' : 'Standard'
                        })`}
                        className="flex-1 px-4 py-2.5 text-sm rounded-xl bg-muted/30 border border-border/80 text-foreground placeholder:text-muted-foreground/60 focus:outline-hidden focus:ring-2 focus:ring-primary/40"
                      />
                      <button
                        type="button"
                        disabled={!axisValueInputs[axis.id]?.trim()}
                        onClick={() => handleAddOptionValue(axis.id)}
                        className="px-4 py-2.5 text-xs font-semibold rounded-xl bg-muted hover:bg-muted/80 text-foreground disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
                      >
                        Add Value
                      </button>
                    </div>

                    {/* Tags List */}
                    <div className="flex flex-wrap gap-2 pt-1">
                      {axis.values.length === 0 ? (
                        <span className="text-xs text-muted-foreground italic">
                          No values yet. Add at least one value to generate variants for this axis.
                        </span>
                      ) : (
                        axis.values.map((v) => (
                          <span
                            key={v}
                            className="px-3 py-1.5 rounded-lg bg-card border border-border/80 font-mono text-xs font-medium text-foreground flex items-center gap-2 shadow-2xs"
                          >
                            {v}
                            <button
                              type="button"
                              onClick={() => handleRemoveOptionValue(axis.id, v)}
                              className="text-muted-foreground hover:text-destructive text-sm font-bold leading-none"
                            >
                              &times;
                            </button>
                          </span>
                        ))
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* STEP 3: VARIANT GRID GENERATOR */}
          {currentStep === 3 && (
            <div className="space-y-5 animate-in fade-in duration-200">
              <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
                <div>
                  <h4 className="text-base font-bold text-foreground tracking-wide font-sans">
                    Variant Review & Pricing
                  </h4>
                  <p className="text-xs text-muted-foreground">
                    Enable the combinations you sell, adjust individual SKUs, set prices and barcodes.
                  </p>
                </div>

                {/* Bulk Price Apply Toolbar */}
                <div className="flex items-center gap-2.5 p-2 rounded-xl bg-muted/40 border border-border/70">
                  <span className="text-xs text-muted-foreground font-medium pl-1">
                    Bulk Price ($):
                  </span>
                  <input
                    type="number"
                    step="0.01"
                    value={bulkPrice}
                    onChange={(e) => setBulkPrice(parseFloat(e.target.value) || 0)}
                    className="w-24 px-3 py-1.5 text-xs font-mono font-medium rounded-lg bg-background border border-border/80 text-foreground text-center focus:outline-hidden focus:ring-2 focus:ring-primary/40 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                  />
                  <button
                    type="button"
                    onClick={handleApplyBulkPrice}
                    className="px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-primary text-primary-foreground hover:opacity-95 active:scale-98 transition-all shadow-2xs"
                  >
                    Apply All
                  </button>
                </div>
              </div>

              {/* Variant Grid Table Container */}
              <div className="border border-border/80 rounded-xl overflow-hidden bg-card shadow-xs">
                {/* Fixed Top Header (Menu) - Completely separated, no vertical scroll */}
                <div
                  ref={step3HeaderRef}
                  className="overflow-x-hidden overflow-y-hidden bg-muted/90 border-b border-border select-none"
                >
                  <table className="w-full text-sm text-left border-collapse table-fixed" style={{ minWidth: '940px' }}>
                    <colgroup>
                      <col style={{ width: '52px' }} />
                      <col style={{ width: '240px' }} />
                      <col style={{ width: '240px' }} />
                      <col style={{ width: '140px' }} />
                      <col style={{ width: '150px' }} />
                      <col style={{ width: '118px' }} />
                    </colgroup>
                    <thead>
                      <tr className="bg-muted/90 text-[11px] font-bold text-foreground uppercase tracking-wider">
                        <th className="px-4 py-3 text-center">
                          <input
                            type="checkbox"
                            checked={variantsList.length > 0 && variantsList.every((v) => v.enabled)}
                            onChange={(e) =>
                              setVariantsList(
                                variantsList.map((v) => ({ ...v, enabled: e.target.checked }))
                              )
                            }
                            className="w-4 h-4 rounded accent-primary cursor-pointer"
                          />
                        </th>
                        <th className="px-4 py-3">
                          Option Dimensions
                        </th>
                        <th className="px-4 py-3">
                          SKU *
                        </th>
                        <th className="px-4 py-3">
                          Price (USD) *
                        </th>
                        <th className="px-4 py-3">
                          Barcode
                        </th>
                        <th className="px-4 py-3">
                          Weight (kg)
                        </th>
                      </tr>
                    </thead>
                  </table>
                </div>

                {/* Scrollable Variant List - Vertical scroll strictly below the header */}
                <div
                  ref={step3BodyRef}
                  onScroll={(e) => {
                    if (step3HeaderRef.current) {
                      step3HeaderRef.current.scrollLeft = e.currentTarget.scrollLeft;
                    }
                  }}
                  className="overflow-x-auto overflow-y-auto max-h-[360px] bg-background"
                >
                  <table className="w-full text-sm text-left border-collapse table-fixed" style={{ minWidth: '940px' }}>
                    <colgroup>
                      <col style={{ width: '52px' }} />
                      <col style={{ width: '240px' }} />
                      <col style={{ width: '240px' }} />
                      <col style={{ width: '140px' }} />
                      <col style={{ width: '150px' }} />
                      <col style={{ width: '118px' }} />
                    </colgroup>
                    <tbody className="divide-y divide-border/60">
                      {variantsList.map((variant) => (
                        <tr
                          key={variant.id}
                          className={`hover:bg-muted/30 transition-colors ${!variant.enabled ? 'opacity-40' : ''}`}
                        >
                          <td className="px-4 py-3 text-center">
                            <input
                              type="checkbox"
                              checked={variant.enabled}
                              onChange={(e) =>
                                setVariantsList(
                                  variantsList.map((v) =>
                                    v.id === variant.id ? { ...v, enabled: e.target.checked } : v
                                  )
                                )
                              }
                              className="w-4 h-4 rounded accent-primary cursor-pointer"
                            />
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex flex-wrap gap-1.5 font-mono">
                              {variant.option_values.map((ov, i) => (
                                <span
                                  key={i}
                                  className="px-2.5 py-1 rounded-md bg-card border border-border/80 text-xs text-foreground shadow-2xs font-medium"
                                >
                                  {ov.optionName}: <strong className="text-primary">{ov.value}</strong>
                                </span>
                              ))}
                            </div>
                          </td>
                          <td className="px-4 py-3">
                            <input
                              type="text"
                              value={variant.sku}
                              disabled={!variant.enabled}
                              onChange={(e) =>
                                setVariantsList(
                                  variantsList.map((v) =>
                                    v.id === variant.id ? { ...v, sku: e.target.value } : v
                                  )
                                )
                              }
                              className="w-full px-3 py-2 text-xs font-mono font-medium rounded-lg bg-card border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40 disabled:opacity-50"
                            />
                          </td>
                          <td className="px-4 py-3">
                            <input
                              type="number"
                              step="0.01"
                              value={variant.price}
                              disabled={!variant.enabled}
                              onChange={(e) =>
                                setVariantsList(
                                  variantsList.map((v) =>
                                    v.id === variant.id
                                      ? { ...v, price: parseFloat(e.target.value) || 0 }
                                      : v
                                  )
                                )
                              }
                              className="w-full px-3 py-2 text-xs font-mono font-medium rounded-lg bg-card border border-border/80 text-foreground text-center focus:outline-hidden focus:ring-2 focus:ring-primary/40 disabled:opacity-50 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                            />
                          </td>
                          <td className="px-4 py-3">
                            <input
                              type="text"
                              value={variant.barcode}
                              disabled={!variant.enabled}
                              onChange={(e) =>
                                setVariantsList(
                                  variantsList.map((v) =>
                                    v.id === variant.id ? { ...v, barcode: e.target.value } : v
                                  )
                                )
                              }
                              placeholder="e.g. 0123456789"
                              className="w-full px-3 py-2 text-xs font-mono rounded-lg bg-card border border-border/80 text-foreground placeholder:text-muted-foreground/50 focus:outline-hidden focus:ring-2 focus:ring-primary/40 disabled:opacity-50"
                            />
                          </td>
                          <td className="px-4 py-3">
                            <input
                              type="number"
                              step="0.1"
                              value={variant.weight || ''}
                              disabled={!variant.enabled}
                              onChange={(e) =>
                                setVariantsList(
                                  variantsList.map((v) =>
                                    v.id === variant.id
                                      ? { ...v, weight: parseFloat(e.target.value) || undefined }
                                      : v
                                  )
                                )
                              }
                              placeholder="kg"
                              className="w-full px-3 py-2 text-xs font-mono rounded-lg bg-card border border-border/80 text-foreground text-center placeholder:text-muted-foreground/50 focus:outline-hidden focus:ring-2 focus:ring-primary/40 disabled:opacity-50 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Clean Summary Footer Bar */}
                <div className="px-4 py-2.5 bg-muted/40 border-t border-border/60 flex items-center justify-between text-xs text-muted-foreground">
                  <span>
                    Total Variants: <strong className="text-foreground">{variantsList.length}</strong> ({variantsList.filter((v) => v.enabled).length} active)
                  </span>
                  <span>
                    Scroll table horizontally if additional columns are hidden
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* STEP 4: MULTI-LOCATION INITIAL STOCK */}
          {currentStep === 4 && (
            <div className="space-y-5 animate-in fade-in duration-200">
              <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
                <div>
                  <h4 className="text-base font-bold text-foreground tracking-wide font-sans">
                    Initial Stock per Location
                  </h4>
                  <p className="text-xs text-muted-foreground">
                    Set starting inventory quantities across your fulfillment centers and retail locations.
                  </p>
                </div>

                {/* Bulk Stock Apply Toolbar */}
                <div className="flex items-center gap-2.5 p-2 rounded-xl bg-muted/40 border border-border/70">
                  <select
                    value={bulkStockLocId}
                    onChange={(e) => setBulkStockLocId(e.target.value)}
                    className="px-3 py-1.5 text-xs rounded-lg bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40"
                  >
                    <option value="">Select Target Location</option>
                    {locations.map((loc) => (
                      <option key={loc.id} value={loc.id}>
                        {loc.name}
                      </option>
                    ))}
                  </select>
                  <input
                    type="number"
                    min="0"
                    value={bulkStockQty}
                    onChange={(e) => setBulkStockQty(parseInt(e.target.value) || 0)}
                    placeholder="Qty"
                    className="w-20 px-3 py-1.5 text-xs font-mono font-medium text-center rounded-lg bg-background border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                  />
                  <button
                    type="button"
                    onClick={handleApplyBulkStock}
                    className="px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-primary text-primary-foreground hover:opacity-95 active:scale-98 transition-all shadow-2xs"
                  >
                    Set All
                  </button>
                </div>
              </div>

              {/* Matrix Table Container */}
              <div className="border border-border/80 rounded-xl overflow-hidden bg-card shadow-xs">
                {/* Fixed Top Header (Menu) - Completely separated, no vertical scroll */}
                <div
                  ref={step4HeaderRef}
                  className="overflow-x-hidden overflow-y-hidden bg-muted/90 border-b border-border select-none"
                >
                  <table
                    className="w-full text-sm text-left border-collapse table-fixed"
                    style={{ minWidth: `${Math.max(760, 240 + 200 + locations.length * 150)}px` }}
                  >
                    <colgroup>
                      <col style={{ width: '240px' }} />
                      <col style={{ width: '200px' }} />
                      {locations.map((loc) => (
                        <col key={loc.id} style={{ width: '150px' }} />
                      ))}
                    </colgroup>
                    <thead>
                      <tr className="bg-muted/90">
                        <th className="px-4 py-3 text-[11px] font-bold text-foreground uppercase tracking-wider">
                          Variant SKU
                        </th>
                        <th className="px-4 py-3 text-[11px] font-bold text-foreground uppercase tracking-wider">
                          Options
                        </th>
                        {locations.map((loc) => (
                          <th
                            key={loc.id}
                            className="px-4 py-3 text-center"
                          >
                            <div className="font-bold text-foreground text-xs">{loc.name}</div>
                            <div className="text-[10px] text-muted-foreground uppercase font-normal font-mono mt-0.5">
                              {loc.type}
                            </div>
                          </th>
                        ))}
                      </tr>
                    </thead>
                  </table>
                </div>

                {/* Scrollable Matrix List - Vertical scroll strictly below the header */}
                <div
                  ref={step4BodyRef}
                  onScroll={(e) => {
                    if (step4HeaderRef.current) {
                      step4HeaderRef.current.scrollLeft = e.currentTarget.scrollLeft;
                    }
                  }}
                  className="overflow-x-auto overflow-y-auto max-h-[360px] bg-background"
                >
                  <table
                    className="w-full text-sm text-left border-collapse table-fixed"
                    style={{ minWidth: `${Math.max(760, 240 + 200 + locations.length * 150)}px` }}
                  >
                    <colgroup>
                      <col style={{ width: '240px' }} />
                      <col style={{ width: '200px' }} />
                      {locations.map((loc) => (
                        <col key={loc.id} style={{ width: '150px' }} />
                      ))}
                    </colgroup>
                    <tbody className="divide-y divide-border/60">
                      {variantsList
                        .filter((v) => v.enabled)
                        .map((variant) => (
                          <tr key={variant.id} className="hover:bg-muted/30 transition-colors">
                            <td className="px-4 py-3 font-mono font-bold text-foreground text-xs truncate">
                              {variant.sku}
                            </td>
                            <td className="px-4 py-3 text-muted-foreground font-mono text-xs">
                              <div className="flex flex-wrap gap-1">
                                {variant.option_values.map((ov, i) => (
                                  <span
                                    key={i}
                                    className="px-2 py-0.5 rounded-md bg-muted/60 text-foreground font-medium text-[11px]"
                                  >
                                    {ov.value}
                                  </span>
                                ))}
                              </div>
                            </td>
                            {locations.map((loc) => (
                              <td key={loc.id} className="px-4 py-3 text-center">
                                <input
                                  type="text"
                                  inputMode="numeric"
                                  value={
                                    variant.initialStockByLocation[loc.id] !== undefined
                                      ? variant.initialStockByLocation[loc.id]
                                      : 0
                                  }
                                  onChange={(e) => {
                                    const raw = e.target.value.replace(/[^0-9]/g, '');
                                    const val = raw === '' ? 0 : parseInt(raw, 10);
                                    setVariantsList(
                                      variantsList.map((v) =>
                                        v.id === variant.id
                                          ? {
                                              ...v,
                                              initialStockByLocation: {
                                                ...v.initialStockByLocation,
                                                [loc.id]: val,
                                              },
                                            }
                                          : v
                                      )
                                    );
                                  }}
                                  className="w-20 px-3 py-1.5 text-xs font-mono font-bold text-center rounded-lg bg-card border border-border/80 text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary/40 shadow-2xs"
                                />
                              </td>
                            ))}
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>

                {/* Clean Summary Footer Bar */}
                <div className="px-4 py-2.5 bg-muted/40 border-t border-border/60 flex items-center justify-between text-xs text-muted-foreground">
                  <span>
                    Locations: <strong className="text-foreground">{locations.length}</strong> | Total Stock Allocated:{' '}
                    <strong className="text-primary">
                      {variantsList
                        .filter((v) => v.enabled)
                        .reduce(
                          (acc, v) =>
                            acc +
                            Object.values(v.initialStockByLocation).reduce((sum, q) => sum + q, 0),
                          0
                        )}{' '}
                      units
                    </strong>
                  </span>
                  <span>
                    Scroll horizontally to inspect all fulfillment centers
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* STEP 5: REVIEW & LAUNCH */}
          {currentStep === 5 && (
            <div className="space-y-5 animate-in fade-in duration-200">
              <div className="p-4 rounded-xl bg-primary/10 border border-primary/20 space-y-1">
                <h4 className="text-base font-bold text-foreground tracking-wide font-sans">
                  Final Product Review
                </h4>
                <p className="text-xs text-muted-foreground">
                  Review your product details, variant combinations, and initial stock before saving.
                </p>
              </div>

              {/* Summary Cards */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
                <div className="p-3 rounded-xl border border-border/70 bg-card space-y-1">
                  <span className="text-muted-foreground text-[11px]">Product Concept</span>
                  <div className="font-bold text-foreground text-sm truncate">{name}</div>
                  <div className="text-muted-foreground">
                    Category: <strong className="text-foreground">{activeCategory}</strong>
                  </div>
                  <div className="text-muted-foreground">
                    Type: <strong className="text-foreground">{type}</strong>
                  </div>
                </div>

                <div className="p-3 rounded-xl border border-border/70 bg-card space-y-1">
                  <span className="text-muted-foreground text-[11px]">Variant Count</span>
                  <div className="font-bold text-emerald-500 text-sm">
                    {variantsList.filter((v) => v.enabled).length} SKUs Enabled
                  </div>
                  <div className="text-muted-foreground">
                    Option Axes: {options.filter((o) => o.values.length > 0).length} dimensions
                  </div>
                  <div className="text-muted-foreground">
                    Pricing: $
                    {Math.min(...variantsList.filter((v) => v.enabled).map((v) => v.price)).toFixed(
                      2
                    )}{' '}
                    - $
                    {Math.max(...variantsList.filter((v) => v.enabled).map((v) => v.price)).toFixed(
                      2
                    )}
                  </div>
                </div>

                <div className="p-3 rounded-xl border border-border/70 bg-card space-y-1">
                  <span className="text-muted-foreground text-[11px]">Initial Stock Allocation</span>
                  <div className="font-bold text-primary text-sm">
                    {variantsList
                      .filter((v) => v.enabled)
                      .reduce(
                        (acc, v) =>
                          acc +
                          Object.values(v.initialStockByLocation).reduce((sum, q) => sum + q, 0),
                        0
                      )}{' '}
                    Units Total
                  </div>
                  <div className="text-muted-foreground">
                    Distributed across {locations.length} fulfillment nodes
                  </div>
                </div>
              </div>

              {/* Progress visualizer during persistence */}
              {isSubmitting && (
                <div className="p-4 rounded-xl border border-primary/40 bg-primary/5 space-y-2 text-center">
                  <Loader2 className="w-6 h-6 animate-spin text-primary mx-auto" />
                  <span className="text-xs font-semibold text-foreground block">
                    {persistStep}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Wizard Footer Controls */}
        <div className="px-6 py-4 border-t border-border/60 flex items-center justify-between bg-card/80">
          <button
            type="button"
            disabled={currentStep === 1 || isSubmitting || isAiGenerating}
            onClick={() => setCurrentStep((prev) => Math.max(1, prev - 1))}
            className="px-4 py-2 text-xs font-medium rounded-xl border border-border/70 hover:bg-muted/50 text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1.5 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <ChevronLeft className="w-4 h-4" />
            Back
          </button>

          <div className="flex items-center gap-2">
            {currentStep < 5 ? (
              <button
                type="button"
                disabled={isAiGenerating}
                onClick={() => {
                  if (currentStep === 1) {
                    if (!name.trim()) {
                      setErrorMessage('Please provide a product name.');
                      return;
                    }
                    if (!activeCategory) {
                      setErrorMessage('Please select or specify a category.');
                      return;
                    }
                    setErrorMessage(null);
                    setCurrentStep(2);
                  } else if (currentStep === 2) {
                    const validAxes = options.filter((o) => o.name.trim() && o.values.length > 0);
                    if (validAxes.length === 0) {
                      setErrorMessage(
                        'At least one option axis with values (e.g. Size, Color, or Edition) is required for variant generation.'
                      );
                      return;
                    }
                    setErrorMessage(null);
                    handleGoToStep3();
                  } else {
                    setCurrentStep((prev) => prev + 1);
                  }
                }}
                className="px-4 py-2 text-xs font-semibold rounded-xl bg-primary text-primary-foreground hover:opacity-95 active:scale-98 transition-all flex items-center gap-1.5 shadow-xs disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Next Step
                <ChevronRight className="w-4 h-4" />
              </button>
            ) : (
              <button
                type="button"
                onClick={handleSaveAndLaunch}
                disabled={isSubmitting}
                className="px-5 py-2 text-xs font-semibold rounded-xl bg-primary text-primary-foreground hover:opacity-95 active:scale-98 transition-all flex items-center gap-2 shadow-xs disabled:opacity-50"
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Launching Product Pipeline...
                  </>
                ) : (
                  <>
                    <CheckCircle2 className="w-4 h-4" />
                    Launch & Save Product
                  </>
                )}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
