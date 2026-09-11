import api from './axiosInstance';
import { store } from '../store';

// ============================================================================
// Types & Interfaces
// ============================================================================

export interface Category {
  id: string;
  tenant_id: string;
  key: string;
  label: string;
  parent_key?: string | null;
}

export interface CategoryCreate {
  key: string;
  label: string;
  parent_key?: string | null;
}

export interface OptionValue {
  id: string;
  option_id: string;
  tenant_id: string;
  value: string;
  position: number;
}

export interface OptionValueCreate {
  value: string;
  position?: number;
}

export interface ProductOption {
  id: string;
  product_id: string;
  tenant_id: string;
  name: string;
  position: number;
  values: OptionValue[];
}

export interface ProductOptionCreate {
  name: string;
  position?: number;
  values: OptionValueCreate[];
}

export interface CandidateVariant {
  option_value_ids: string[];
  option_summary: Record<string, string>;
  suggested_sku?: string | null;
}

export interface CandidateGridResponse {
  product_id: string;
  candidates: CandidateVariant[];
}

export interface Variant {
  id: string;
  product_id: string;
  tenant_id: string;
  sku: string;
  barcode?: string | null;
  price: number;
  currency: string;
  weight?: number | null;
  status: 'ACTIVE' | 'RETIRED';
  created_at: string;
  updated_at: string;
  option_values: OptionValue[];
}

export interface VariantCreate {
  sku: string;
  barcode?: string | null;
  price: number;
  currency?: string;
  weight?: number | null;
  status?: 'ACTIVE' | 'RETIRED';
  option_value_ids?: string[];
}

export interface Product {
  id: string;
  tenant_id: string;
  type: 'PRODUCT' | 'SERVICE';
  name: string;
  category: string;
  subcategory?: string | null;
  status: 'DRAFT' | 'ACTIVE' | 'RETIRED';
  description?: string | null;

  // AI Findability & Sales Intel
  keywords: string[];
  use_cases: string[];
  target_industries: string[];
  ideal_customer_profile?: string | null;
  value_proposition?: string | null;
  competitors_beats: string[];
  sales_tags: string[];

  // Pricing Guardrails
  min_discount_pct: number;
  max_discount_pct: number;

  acl: string[];
  version: number;
  created_at: string;
  updated_at: string;
  variants?: Variant[];
}

export interface ProductDetail extends Product {
  options: ProductOption[];
  variants: Variant[];
}

export interface ProductCreateInput {
  type?: 'PRODUCT' | 'SERVICE';
  name: string;
  category: string;
  subcategory?: string | null;
  status?: 'DRAFT' | 'ACTIVE' | 'RETIRED';
  description?: string | null;
  keywords?: string[];
  use_cases?: string[];
  target_industries?: string[];
  ideal_customer_profile?: string | null;
  value_proposition?: string | null;
  competitors_beats?: string[];
  sales_tags?: string[];
  min_discount_pct?: number;
  max_discount_pct?: number;
  options?: ProductOptionCreate[];
}

export interface ProductUpdateInput {
  type?: 'PRODUCT' | 'SERVICE';
  name?: string;
  category?: string;
  subcategory?: string | null;
  status?: 'DRAFT' | 'ACTIVE' | 'RETIRED';
  description?: string | null;
  keywords?: string[];
  use_cases?: string[];
  target_industries?: string[];
  ideal_customer_profile?: string | null;
  value_proposition?: string | null;
  competitors_beats?: string[];
  sales_tags?: string[];
  min_discount_pct?: number;
  max_discount_pct?: number;
}

export interface Location {
  id: string;
  tenant_id: string;
  name: string;
  type: 'WAREHOUSE' | 'STORE' | 'SUPPLIER' | 'IN_TRANSIT';
  sellable: boolean;
  priority: number;
  address?: Record<string, any> | null;
  created_at: string;
}

export interface LocationCreate {
  name: string;
  type?: 'WAREHOUSE' | 'STORE' | 'SUPPLIER' | 'IN_TRANSIT';
  sellable?: boolean;
  priority?: number;
  address?: Record<string, any> | null;
}

export interface InventoryLevel {
  id: string;
  variant_id: string;
  location_id: string;
  tenant_id: string;
  qty_on_hand: number;
  qty_reserved: number;
  qty_available: number;
  reorder_at?: number | null;
}

export interface SetStockRequest {
  variant_id: string;
  location_id: string;
  qty: number;
  reason?: 'RESTOCK' | 'ADJUST';
  ref_id?: string | null;
  note?: string | null;
}

export interface AdjustStockRequest {
  variant_id: string;
  location_id: string;
  delta: number;
  reason?: 'RESTOCK' | 'SALE' | 'ADJUST' | 'DAMAGE';
  ref_id?: string | null;
  note?: string | null;
}

export interface ReserveStockRequest {
  sku: string;
  qty: number;
  location_id?: string | null;
}

export interface ReservationAllocation {
  location_id: string;
  location_name: string;
  qty: number;
}

export interface ReservationResponse {
  reservation_id: string;
  sku: string;
  requested_qty: number;
  allocated_qty: number;
  allocations: ReservationAllocation[];
}

export interface ReleaseStockResponse {
  reservation_id: string;
  released_qty: number;
  movements_count: number;
}

export interface TransferStockRequest {
  sku: string;
  from_location_id: string;
  to_location_id: string;
  qty: number;
  note?: string | null;
}

export interface TransferStockResponse {
  ref_id: string;
  sku: string;
  from_location_id: string;
  to_location_id: string;
  qty: number;
}

export interface LocationAvailability {
  location_id: string;
  location_name: string;
  sellable: boolean;
  priority: number;
  qty_on_hand: number;
  qty_reserved: number;
  qty_available: number;
}

export interface VariantAvailabilityResponse {
  variant_id: string;
  sku: string;
  total_available: number;
  by_location: LocationAvailability[];
}

export interface CheckAvailabilityResponse {
  can_fulfill: boolean;
  sku: string;
  requested_qty: number;
  total_available: number;
  location_id?: string | null;
  by_location: LocationAvailability[];
}

export interface DescribeCatalogResponse {
  categories: Category[];
  filterable_fields: string[];
  option_types: string[];
}

export interface RowValidationItem {
  row_index: number;
  valid: boolean;
  errors: string[];
  warnings: string[];
}

export interface ValidationReport {
  total_rows: number;
  valid_count: number;
  error_count: number;
  products_to_create: number;
  products_to_update: number;
  variants_to_create: number;
  variants_to_update: number;
  row_results: RowValidationItem[];
}

export interface ImportCommitRequest {
  csv_content?: string;
  skip_invalid?: boolean;
  auto_create_categories?: boolean;
}

export interface ImportCommitResponse {
  job_id: string;
  status: string;
  message: string;
}

export interface ImportJobResponse {
  job_id: string;
  tenant_id: string;
  status: 'PENDING' | 'VALIDATING' | 'COMMITTING' | 'COMPLETED' | 'FAILED';
  progress_pct: number;
  total_rows: number;
  created_count: number;
  updated_count: number;
  skipped_count: number;
  errors: string[];
  started_at?: string | null;
  completed_at?: string | null;
}

export interface ListProductsParams {
  status?: string;
  category?: string;
  subcategory?: string;
  type?: string;
  min_price?: number;
  max_price?: number;
  keywords?: string;
  target_industry?: string;
  in_stock?: boolean;
  location_id?: string;
  limit?: number;
  offset?: number;
}

export interface GenerateFindabilityInput {
  name: string;
  type: 'PRODUCT' | 'SERVICE';
  category: string;
  subcategory?: string | null;
  description: string;
}

export interface GenerateFindabilityOutput {
  keywords: string[];
  use_cases: string[];
  target_industries: string[];
  value_proposition: string;
  ideal_customer_profile: string;
  min_discount_pct: number;
  max_discount_pct: number;
}

export interface SemanticSearchInput {
  query: string;
  limit?: number;
}

export interface SemanticMatchItem {
  product_id: string;
  score: number;
  matched_terms: string[];
  rationale: string;
}

export interface SemanticSearchOutput {
  query: string;
  expanded_terms: string[];
  results: SemanticMatchItem[];
}

// ============================================================================
// Tenant Context Helper
// ============================================================================

const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/**
 * The active workspace's id, sent as `X-Tenant-Id`. Workspace pages render only after
 * `WorkspaceGate` has loaded it. There is deliberately no shared placeholder workspace to
 * fall back to: without a workspace the request is refused instead of mixing everyone's data.
 */
export function getActiveTenantId(overrideTenantId?: string): string {
  if (overrideTenantId && UUID_REGEX.test(overrideTenantId)) {
    return overrideTenantId;
  }
  try {
    const state = store.getState();
    const wsId = state.workspace?.currentWorkspace?.workspaceId;
    if (wsId && UUID_REGEX.test(wsId)) {
      return wsId;
    }
  } catch (err) {
    // ignore
  }

  let storedTenant: string | null = null;
  try {
    storedTenant = localStorage.getItem('rolesync_active_workspace_id');
  } catch {
    // storage unavailable
  }
  if (storedTenant && UUID_REGEX.test(storedTenant)) {
    return storedTenant;
  }

  return '';
}

function getHeaders(tenantId?: string) {
  return {
    'X-Tenant-Id': getActiveTenantId(tenantId),
  };
}

// ============================================================================
// Catalog API Service Methods
// ============================================================================

export const catalogApi = {
  // 1. Introspection / AI Tooling
  getCatalogDescription: async (tenantId?: string): Promise<DescribeCatalogResponse> => {
    const response = await api.get<DescribeCatalogResponse>('/catalog/describe', {
      headers: getHeaders(tenantId),
    });
    return response.data;
  },

  // 2. Categories
  listCategories: async (tenantId?: string): Promise<Category[]> => {
    const response = await api.get<Category[]>('/catalog/categories', {
      headers: getHeaders(tenantId),
    });
    return response.data;
  },

  createCategory: async (data: CategoryCreate, tenantId?: string): Promise<Category> => {
    const response = await api.post<Category>('/catalog/categories', data, {
      headers: getHeaders(tenantId),
    });
    return response.data;
  },

  // 3. Products CRUD
  listProducts: async (params?: ListProductsParams, tenantId?: string): Promise<Product[]> => {
    const response = await api.get<Product[]>('/catalog/products', {
      params,
      headers: getHeaders(tenantId),
    });
    return response.data;
  },

  getProduct: async (productId: string, tenantId?: string): Promise<ProductDetail> => {
    const response = await api.get<ProductDetail>(`/catalog/products/${encodeURIComponent(productId)}`, {
      headers: getHeaders(tenantId),
    });
    return response.data;
  },

  createProduct: async (data: ProductCreateInput, tenantId?: string): Promise<ProductDetail> => {
    const response = await api.post<ProductDetail>('/catalog/products', data, {
      headers: getHeaders(tenantId),
    });
    return response.data;
  },

  updateProduct: async (
    productId: string,
    data: ProductUpdateInput,
    tenantId?: string
  ): Promise<ProductDetail> => {
    const response = await api.put<ProductDetail>(
      `/catalog/products/${encodeURIComponent(productId)}`,
      data,
      {
        headers: getHeaders(tenantId),
      }
    );
    return response.data;
  },

  deleteProduct: async (productId: string, permanent: boolean = false, tenantId?: string): Promise<any> => {
    const response = await api.delete<any>(`/catalog/products/${encodeURIComponent(productId)}`, {
      params: permanent ? { permanent: true } : undefined,
      headers: getHeaders(tenantId),
    });
    return response.data;
  },

  // 4. Product Options
  setProductOptions: async (
    productId: string,
    options: ProductOptionCreate[],
    tenantId?: string
  ): Promise<ProductOption[]> => {
    const response = await api.put<ProductOption[]>(
      `/catalog/products/${encodeURIComponent(productId)}/options`,
      { options },
      {
        headers: getHeaders(tenantId),
      }
    );
    return response.data;
  },

  // 5. Candidate Variant Grid Generator
  getVariantGrid: async (productId: string, tenantId?: string): Promise<CandidateGridResponse> => {
    const response = await api.get<CandidateGridResponse>(
      `/catalog/products/${encodeURIComponent(productId)}/variant-grid`,
      {
        headers: getHeaders(tenantId),
      }
    );
    return response.data;
  },

  // 6. Variants
  upsertVariants: async (
    productId: string,
    variants: VariantCreate[],
    tenantId?: string
  ): Promise<Variant[]> => {
    const response = await api.post<Variant[]>(
      `/catalog/products/${encodeURIComponent(productId)}/variants`,
      { variants },
      {
        headers: getHeaders(tenantId),
      }
    );
    return response.data;
  },

  getVariant: async (sku: string, tenantId?: string): Promise<Variant> => {
    const response = await api.get<Variant>(`/catalog/variants/${encodeURIComponent(sku)}`, {
      headers: getHeaders(tenantId),
    });
    return response.data;
  },

  // 7. Locations
  listLocations: async (tenantId?: string): Promise<Location[]> => {
    const response = await api.get<Location[]>('/catalog/locations', {
      headers: getHeaders(tenantId),
    });
    return response.data;
  },

  createLocation: async (data: LocationCreate, tenantId?: string): Promise<Location> => {
    const response = await api.post<Location>('/catalog/locations', data, {
      headers: getHeaders(tenantId),
    });
    return response.data;
  },

  updateLocation: async (
    locationId: string,
    data: LocationCreate,
    tenantId?: string
  ): Promise<Location> => {
    const response = await api.put<Location>(
      `/catalog/locations/${encodeURIComponent(locationId)}`,
      data,
      {
        headers: getHeaders(tenantId),
      }
    );
    return response.data;
  },

  deleteLocation: async (locationId: string, tenantId?: string): Promise<void> => {
    await api.delete(`/catalog/locations/${encodeURIComponent(locationId)}`, {
      headers: getHeaders(tenantId),
    });
  },

  // 8. Inventory & Stock Movements
  setStock: async (data: SetStockRequest, tenantId?: string): Promise<InventoryLevel> => {
    const response = await api.post<InventoryLevel>('/catalog/inventory/set-stock', data, {
      headers: getHeaders(tenantId),
    });
    return response.data;
  },

  batchSetStock: async (items: SetStockRequest[], tenantId?: string): Promise<InventoryLevel[]> => {
    const response = await api.post<InventoryLevel[]>(
      '/catalog/inventory/batch-set-stock',
      { items },
      {
        headers: getHeaders(tenantId),
      }
    );
    return response.data;
  },

  adjustStock: async (data: AdjustStockRequest, tenantId?: string): Promise<InventoryLevel> => {
    const response = await api.post<InventoryLevel>('/catalog/inventory/adjust-stock', data, {
      headers: getHeaders(tenantId),
    });
    return response.data;
  },

  reserveStock: async (data: ReserveStockRequest, tenantId?: string): Promise<ReservationResponse> => {
    const response = await api.post<ReservationResponse>('/catalog/inventory/reserve', data, {
      headers: getHeaders(tenantId),
    });
    return response.data;
  },

  releaseStock: async (reservationId: string, tenantId?: string): Promise<ReleaseStockResponse> => {
    const response = await api.post<ReleaseStockResponse>(
      `/catalog/inventory/release/${encodeURIComponent(reservationId)}`,
      {},
      {
        headers: getHeaders(tenantId),
      }
    );
    return response.data;
  },

  transferStock: async (data: TransferStockRequest, tenantId?: string): Promise<TransferStockResponse> => {
    const response = await api.post<TransferStockResponse>('/catalog/inventory/transfer', data, {
      headers: getHeaders(tenantId),
    });
    return response.data;
  },

  // 9. Availability
  getBatchAvailability: async (
    skus?: string[],
    tenantId?: string
  ): Promise<Record<string, VariantAvailabilityResponse>> => {
    const response = await api.get<Record<string, VariantAvailabilityResponse>>(
      '/catalog/inventory/availability',
      {
        params: skus && skus.length > 0 ? { skus } : undefined,
        headers: getHeaders(tenantId),
      }
    );
    return response.data;
  },

  getAvailability: async (sku: string, tenantId?: string): Promise<VariantAvailabilityResponse> => {
    const response = await api.get<VariantAvailabilityResponse>(
      `/catalog/variants/${encodeURIComponent(sku)}/availability`,
      {
        headers: getHeaders(tenantId),
      }
    );
    return response.data;
  },

  checkAvailability: async (
    sku: string,
    qty: number = 1,
    locationId?: string,
    tenantId?: string
  ): Promise<CheckAvailabilityResponse> => {
    const response = await api.get<CheckAvailabilityResponse>(
      `/catalog/variants/${encodeURIComponent(sku)}/check-availability`,
      {
        params: {
          qty,
          location_id: locationId,
        },
        headers: getHeaders(tenantId),
      }
    );
    return response.data;
  },

  // 10. CSV Validation & Import
  validateRows: async (rows: Record<string, any>[], tenantId?: string): Promise<ValidationReport> => {
    const response = await api.post<ValidationReport>('/catalog/validate-rows', rows, {
      headers: getHeaders(tenantId),
    });
    return response.data;
  },

  downloadTemplateCsv: async (): Promise<string> => {
    const response = await api.get<string>('/catalog/import/template.csv', {
      responseType: 'text',
    });
    return response.data;
  },

  validateCsvImport: async (
    fileOrContent: File | string,
    autoCreateCategories: boolean = true,
    tenantId?: string
  ): Promise<ValidationReport> => {
    if (typeof fileOrContent === 'string') {
      const response = await api.post<ValidationReport>(
        '/catalog/import/validate',
        {
          csv_content: fileOrContent,
          auto_create_categories: autoCreateCategories,
        },
        {
          headers: getHeaders(tenantId),
        }
      );
      return response.data;
    } else {
      const formData = new FormData();
      formData.append('file', fileOrContent);
      formData.append('auto_create_categories', String(autoCreateCategories));

      const response = await api.post<ValidationReport>('/catalog/import/validate', formData, {
        headers: {
          ...getHeaders(tenantId),
          'Content-Type': 'multipart/form-data',
        },
      });
      return response.data;
    }
  },

  commitCsvImport: async (
    params: {
      fileOrContent: File | string;
      skipInvalid?: boolean;
      autoCreateCategories?: boolean;
    },
    tenantId?: string
  ): Promise<ImportCommitResponse> => {
    const { fileOrContent, skipInvalid = false, autoCreateCategories = true } = params;

    if (typeof fileOrContent === 'string') {
      const response = await api.post<ImportCommitResponse>(
        '/catalog/import/commit',
        {
          csv_content: fileOrContent,
          skip_invalid: skipInvalid,
          auto_create_categories: autoCreateCategories,
        },
        {
          headers: getHeaders(tenantId),
        }
      );
      return response.data;
    } else {
      const formData = new FormData();
      formData.append('file', fileOrContent);
      formData.append('skip_invalid', String(skipInvalid));
      formData.append('auto_create_categories', String(autoCreateCategories));

      const response = await api.post<ImportCommitResponse>('/catalog/import/commit', formData, {
        headers: {
          ...getHeaders(tenantId),
          'Content-Type': 'multipart/form-data',
        },
      });
      return response.data;
    }
  },

  getImportJobStatus: async (jobId: string, tenantId?: string): Promise<ImportJobResponse> => {
    const response = await api.get<ImportJobResponse>(
      `/catalog/import/jobs/${encodeURIComponent(jobId)}`,
      {
        headers: getHeaders(tenantId),
      }
    );
    return response.data;
  },

  // 10. AI Auto-Generation for Findability & Sales Knowledge
  generateFindability: async (
    data: GenerateFindabilityInput,
    tenantId?: string
  ): Promise<GenerateFindabilityOutput> => {
    const response = await api.post<GenerateFindabilityOutput>(
      '/catalog/ai/generate-findability',
      data,
      {
        headers: getHeaders(tenantId),
      }
    );
    return response.data;
  },

  // 11. AI Semantic Search & Query Expansion
  semanticSearch: async (
    data: SemanticSearchInput,
    tenantId?: string
  ): Promise<SemanticSearchOutput> => {
    const response = await api.post<SemanticSearchOutput>(
      '/catalog/ai/semantic-search',
      data,
      {
        headers: getHeaders(tenantId),
      }
    );
    return response.data;
  },
};
