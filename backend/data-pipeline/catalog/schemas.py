from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Category Schemas
# ---------------------------------------------------------------------------

class CategoryBase(BaseModel):
    key: str = Field(..., min_length=1, max_length=100, description="Machine-readable key, e.g. 'office_chair'")
    label: str = Field(..., min_length=1, max_length=255, description="Human-readable label, e.g. 'Office Chair'")
    parent_key: Optional[str] = Field(None, max_length=100)


class CategoryCreate(CategoryBase):
    pass


class CategoryResponse(CategoryBase):
    id: UUID
    tenant_id: UUID

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Options & Option Values Schemas
# ---------------------------------------------------------------------------

class OptionValueBase(BaseModel):
    value: str = Field(..., min_length=1, max_length=255)
    position: int = Field(0, ge=0)


class OptionValueCreate(OptionValueBase):
    pass


class OptionValueResponse(OptionValueBase):
    id: UUID
    option_id: UUID
    tenant_id: UUID

    model_config = ConfigDict(from_attributes=True)


class ProductOptionBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Name of option axis, e.g. 'Color' or 'Size'")
    position: int = Field(0, ge=0)


class ProductOptionCreate(ProductOptionBase):
    values: List[OptionValueCreate] = Field(default_factory=list)


class ProductOptionResponse(ProductOptionBase):
    id: UUID
    product_id: UUID
    tenant_id: UUID
    values: List[OptionValueResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class SetOptionsRequest(BaseModel):
    options: List[ProductOptionCreate] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Candidate Variant Grid Schemas (Cartesian Generator)
# ---------------------------------------------------------------------------

class CandidateVariant(BaseModel):
    option_value_ids: List[UUID]
    option_summary: Dict[str, str] = Field(..., description="Map of Option Name -> Value, e.g. {'Size': 'M', 'Color': 'Black'}")
    suggested_sku: Optional[str] = None


class CandidateGridResponse(BaseModel):
    product_id: UUID
    candidates: List[CandidateVariant] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Variant Schemas
# ---------------------------------------------------------------------------

class VariantCreate(BaseModel):
    sku: str = Field(..., min_length=1, max_length=100)
    barcode: Optional[str] = Field(None, max_length=100)
    price: Decimal = Field(..., ge=0)
    currency: str = Field("USD", min_length=3, max_length=10)
    weight: Optional[Decimal] = None
    status: str = Field("ACTIVE", pattern="^(ACTIVE|RETIRED)$")
    option_value_ids: List[UUID] = Field(default_factory=list)


class VariantUpdate(BaseModel):
    sku: Optional[str] = Field(None, min_length=1, max_length=100)
    barcode: Optional[str] = Field(None, max_length=100)
    price: Optional[Decimal] = Field(None, ge=0)
    currency: Optional[str] = Field(None, min_length=3, max_length=10)
    weight: Optional[Decimal] = None
    status: Optional[str] = Field(None, pattern="^(ACTIVE|RETIRED)$")
    option_value_ids: Optional[List[UUID]] = None


class VariantResponse(BaseModel):
    id: UUID
    product_id: UUID
    tenant_id: UUID
    sku: str
    barcode: Optional[str] = None
    price: Decimal
    currency: str
    weight: Optional[Decimal] = None
    status: str
    created_at: datetime
    updated_at: datetime
    option_values: List[OptionValueResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class BatchUpsertVariantsRequest(BaseModel):
    variants: List[VariantCreate] = Field(..., min_length=1)


import re
from pydantic import field_validator

# Regex detecting genuine SQL injection patterns like stacked queries, SQL commands with comment dashes, union select, etc.
# Avoid matching natural English phrases like 'Select ... from our catalog' or 'Create a table setting'.
SQL_INJECTION_PATTERN = re.compile(
    r"(;\s*(DROP|SELECT|INSERT|UPDATE|DELETE|ALTER|TRUNCATE|EXEC(UTE)?)\b)"
    r"|(\bUNION\s+(ALL\s+)?SELECT\b)"
    r"|(?:--\s*|\/\*[\s\S]*?\*\/)"
    r"|(\b(?:OR|AND)\b\s+['\"0-9]+=['\"0-9]+)"
    r"|(\b(INSERT\s+INTO|DROP\s+TABLE|ALTER\s+TABLE|TRUNCATE\s+TABLE)\b)",
    re.IGNORECASE,
)

def validate_safe_text(val: Optional[str], field_name: str, max_chars: int = 10000) -> Optional[str]:
    if val is None:
        return None
    val_stripped = val.strip()
    if len(val_stripped) > max_chars:
        raise ValueError(f"{field_name} exceeds maximum length of {max_chars} characters.")
    if SQL_INJECTION_PATTERN.search(val_stripped):
        raise ValueError(f"Unsafe characters or SQL injection pattern detected in {field_name}.")
    return val_stripped


class ProductBase(BaseModel):
    type: str = Field("PRODUCT", pattern="^(PRODUCT|SERVICE)$")
    name: str = Field(..., min_length=3, max_length=255)
    category: str = Field(..., min_length=1, max_length=100)
    subcategory: Optional[str] = Field(None, max_length=100)
    status: str = Field("DRAFT", pattern="^(DRAFT|ACTIVE|RETIRED)$")
    description: Optional[str] = Field(None, max_length=10000)

    # AI Findability & Sales Intel
    keywords: List[str] = Field(default_factory=list)
    use_cases: List[str] = Field(default_factory=list)
    target_industries: List[str] = Field(default_factory=list)
    ideal_customer_profile: Optional[str] = Field(None, max_length=5000)
    value_proposition: Optional[str] = Field(None, max_length=5000)
    competitors_beats: List[str] = Field(default_factory=list)
    sales_tags: List[str] = Field(default_factory=list)

    # Pricing Guardrails
    min_discount_pct: Decimal = Field(Decimal("0"), ge=0, le=100)
    max_discount_pct: Decimal = Field(Decimal("0"), ge=0, le=100)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if len(v.strip()) < 3:
            raise ValueError("Product name must be at least 3 characters.")
        return validate_safe_text(v, "Product name", 255) or ""

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        return validate_safe_text(v, "Category", 100) or ""

    @field_validator("subcategory")
    @classmethod
    def validate_subcategory(cls, v: Optional[str]) -> Optional[str]:
        return validate_safe_text(v, "Subcategory", 100)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        return validate_safe_text(v, "Description", 10000)

    @field_validator("value_proposition")
    @classmethod
    def validate_value_prop(cls, v: Optional[str]) -> Optional[str]:
        return validate_safe_text(v, "Value proposition", 5000)

    @field_validator("ideal_customer_profile")
    @classmethod
    def validate_icp(cls, v: Optional[str]) -> Optional[str]:
        return validate_safe_text(v, "Ideal customer profile", 5000)

    @field_validator("keywords", "use_cases", "target_industries")
    @classmethod
    def validate_list_items(cls, items: List[str]) -> List[str]:
        cleaned = []
        for item in items:
            safe = validate_safe_text(item, "List tag item", 255)
            if safe:
                cleaned.append(safe)
        return cleaned


class ProductCreate(ProductBase):
    options: Optional[List[ProductOptionCreate]] = None


class ProductUpdate(BaseModel):
    type: Optional[str] = Field(None, pattern="^(PRODUCT|SERVICE)$")
    name: Optional[str] = Field(None, min_length=3, max_length=255)
    category: Optional[str] = Field(None, min_length=1, max_length=100)
    subcategory: Optional[str] = Field(None, max_length=100)
    status: Optional[str] = Field(None, pattern="^(DRAFT|ACTIVE|RETIRED)$")
    description: Optional[str] = Field(None, max_length=10000)
    keywords: Optional[List[str]] = None
    use_cases: Optional[List[str]] = None
    target_industries: Optional[List[str]] = None
    ideal_customer_profile: Optional[str] = Field(None, max_length=5000)
    value_proposition: Optional[str] = Field(None, max_length=5000)
    competitors_beats: Optional[List[str]] = None
    sales_tags: Optional[List[str]] = None
    min_discount_pct: Optional[Decimal] = Field(None, ge=0, le=100)
    max_discount_pct: Optional[Decimal] = Field(None, ge=0, le=100)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v.strip()) < 3:
            raise ValueError("Product name must be at least 3 characters.")
        return validate_safe_text(v, "Product name", 255)

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: Optional[str]) -> Optional[str]:
        return validate_safe_text(v, "Category", 100)

    @field_validator("subcategory")
    @classmethod
    def validate_subcategory(cls, v: Optional[str]) -> Optional[str]:
        return validate_safe_text(v, "Subcategory", 100)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        return validate_safe_text(v, "Description", 10000)

    @field_validator("value_proposition")
    @classmethod
    def validate_value_prop(cls, v: Optional[str]) -> Optional[str]:
        return validate_safe_text(v, "Value proposition", 5000)

    @field_validator("ideal_customer_profile")
    @classmethod
    def validate_icp(cls, v: Optional[str]) -> Optional[str]:
        return validate_safe_text(v, "Ideal customer profile", 5000)

    @field_validator("keywords", "use_cases", "target_industries")
    @classmethod
    def validate_list_items(cls, items: Optional[List[str]]) -> Optional[List[str]]:
        if items is None:
            return None
        cleaned = []
        for item in items:
            safe = validate_safe_text(item, "List tag item", 255)
            if safe:
                cleaned.append(safe)
        return cleaned


class ProductResponse(ProductBase):
    id: UUID
    tenant_id: UUID
    acl: List[str] = Field(default_factory=list)
    version: int
    created_at: datetime
    updated_at: datetime
    variants: List[VariantResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ProductDetailResponse(ProductResponse):
    options: List[ProductOptionResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Location Schemas
# ---------------------------------------------------------------------------

class LocationBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field("WAREHOUSE", pattern="^(WAREHOUSE|STORE|SUPPLIER|IN_TRANSIT)$")
    sellable: bool = True
    priority: int = Field(100, ge=1)
    address: Optional[Dict[str, Any]] = None


class LocationCreate(LocationBase):
    pass


class LocationResponse(LocationBase):
    id: UUID
    tenant_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Inventory & Stock Schemas
# ---------------------------------------------------------------------------

class SetStockRequest(BaseModel):
    variant_id: UUID
    location_id: UUID
    qty: int = Field(..., ge=0)
    reason: str = Field("RESTOCK", pattern="^(RESTOCK|ADJUST)$")
    ref_id: Optional[UUID] = None
    note: Optional[str] = None


class BatchSetStockRequest(BaseModel):
    items: List[SetStockRequest] = Field(..., min_length=1)


class AdjustStockRequest(BaseModel):
    variant_id: UUID
    location_id: UUID
    delta: int
    reason: str = Field("ADJUST", pattern="^(RESTOCK|SALE|ADJUST|DAMAGE)$")
    ref_id: Optional[UUID] = None
    note: Optional[str] = None


class ReserveStockRequest(BaseModel):
    sku: str = Field(..., min_length=1)
    qty: int = Field(..., gt=0)
    location_id: Optional[UUID] = None


class ReservationAllocation(BaseModel):
    location_id: UUID
    location_name: str
    qty: int


class ReservationResponse(BaseModel):
    reservation_id: UUID
    sku: str
    requested_qty: int
    allocated_qty: int
    allocations: List[ReservationAllocation]


class ReleaseStockResponse(BaseModel):
    reservation_id: UUID
    released_qty: int
    movements_count: int


class TransferStockRequest(BaseModel):
    sku: str = Field(..., min_length=1)
    from_location_id: UUID
    to_location_id: UUID
    qty: int = Field(..., gt=0)
    note: Optional[str] = None


class TransferStockResponse(BaseModel):
    ref_id: UUID
    sku: str
    from_location_id: UUID
    to_location_id: UUID
    qty: int


class InventoryLevelResponse(BaseModel):
    id: UUID
    variant_id: UUID
    location_id: UUID
    tenant_id: UUID
    qty_on_hand: int
    qty_reserved: int
    qty_available: int
    reorder_at: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class StockMovementResponse(BaseModel):
    id: UUID
    inv_level_id: UUID
    tenant_id: UUID
    delta: int
    reason: str
    ref_id: Optional[UUID] = None
    note: Optional[str] = None
    at: datetime
    created_by: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Availability Schemas
# ---------------------------------------------------------------------------

class LocationAvailability(BaseModel):
    location_id: UUID
    location_name: str
    sellable: bool
    priority: int
    qty_on_hand: int
    qty_reserved: int
    qty_available: int


class VariantAvailabilityResponse(BaseModel):
    variant_id: UUID
    sku: str
    total_available: int
    by_location: List[LocationAvailability] = Field(default_factory=list)


class CheckAvailabilityResponse(BaseModel):
    can_fulfill: bool
    sku: str
    requested_qty: int
    total_available: int
    location_id: Optional[UUID] = None
    by_location: List[LocationAvailability] = Field(default_factory=list)


class DescribeCatalogResponse(BaseModel):
    categories: List[CategoryResponse] = Field(default_factory=list)
    filterable_fields: List[str] = Field(default_factory=list)
    option_types: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Dry-run Validation Schemas (CSV Import Support)
# ---------------------------------------------------------------------------

class RowValidationItem(BaseModel):
    row_index: int
    valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ValidationReport(BaseModel):
    total_rows: int
    valid_count: int
    error_count: int
    products_to_create: int = 0
    products_to_update: int = 0
    variants_to_create: int = 0
    variants_to_update: int = 0
    row_results: List[RowValidationItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# CSV Import Job Schemas
# ---------------------------------------------------------------------------

class ImportCommitRequest(BaseModel):
    csv_content: Optional[str] = None
    skip_invalid: bool = False
    auto_create_categories: bool = True


class ImportCommitResponse(BaseModel):
    job_id: UUID
    status: str = "PENDING"
    message: str = "Import job queued successfully"


class ImportJobResponse(BaseModel):
    job_id: UUID
    tenant_id: UUID
    status: str
    progress_pct: float = 0.0
    total_rows: int = 0
    created_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    errors: List[str] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# AI Sales Intelligence & Findability Schemas
# ---------------------------------------------------------------------------

class GenerateFindabilityRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=255)
    type: str = Field(..., pattern="^(PRODUCT|SERVICE)$")
    category: str = Field(..., min_length=1, max_length=100)
    subcategory: Optional[str] = Field(None, max_length=100)
    description: str = Field(..., min_length=200, max_length=10000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if len(v.strip()) < 3:
            raise ValueError("Product/Service Name must be at least 3 characters.")
        return validate_safe_text(v, "Product name", 255) or ""

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Primary Category is required.")
        return validate_safe_text(v, "Category", 100) or ""

    @field_validator("subcategory")
    @classmethod
    def validate_subcategory(cls, v: Optional[str]) -> Optional[str]:
        return validate_safe_text(v, "Subcategory", 100)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        if len(v.strip()) < 200:
            raise ValueError("Product Description must be at least 200 characters for AI to generate high-fidelity sales knowledge.")
        return validate_safe_text(v, "Description", 10000) or ""


class GenerateFindabilityResponse(BaseModel):
    keywords: List[str] = Field(default_factory=list)
    use_cases: List[str] = Field(default_factory=list)
    target_industries: List[str] = Field(default_factory=list)
    value_proposition: str = Field("")
    ideal_customer_profile: str = Field("")
    min_discount_pct: Decimal = Field(Decimal("5.0"), ge=0, le=100)
    max_discount_pct: Decimal = Field(Decimal("20.0"), ge=0, le=100)


class SemanticSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(20, ge=1, le=100)


class SemanticMatchItem(BaseModel):
    product_id: UUID
    score: float
    matched_terms: List[str] = Field(default_factory=list)
    rationale: str = Field("")


class SemanticSearchResponse(BaseModel):
    query: str
    expanded_terms: List[str] = Field(default_factory=list)
    results: List[SemanticMatchItem] = Field(default_factory=list)

