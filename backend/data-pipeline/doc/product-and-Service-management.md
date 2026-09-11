# Product & Service Management — Architecture & Implementation Specification

> **Audience:** AI coding agents, backend engineers, and frontend developers maintaining the RoleSync platform.
> **Context:** RoleSync is a live multi-tenant AI Sales OS. The data-ingestion pipeline (Composio connectors → security → chunking → embedding → MongoDB/pgvector) already exists and works. This module adds structured **product & service catalog management with multi-location inventory**. It is a self-contained module that reuses existing infra (Postgres, Redis, workers, auth/JWT, tenant model) but does **not** touch the document-ingestion vector pipeline and does **not** disrupt connector integrations.

---

## 1. Guiding Principles (Read First — Decisions Core)

1. **Structured, not embedded.** Catalog data is stored relationally in Postgres and queried exactly. Do **NOT** build an embedding/vector-sync layer for catalog data. The AI accesses it through structured **tools**, not similarity search. (Catalog queries are exact — price, SKU, stock, filters — where SQL is correct and embeddings add cost, staleness, and dual truth sources.)
2. **One service owns all writes.** Every entry path (manual UI, CSV import, future API sync) routes through a single `ProductService`. Nothing writes to catalog tables directly. Validation and business rules live in exactly one place.
3. **Price lives on the variant, stock lives on (variant × location).** A `PRODUCT` is the sellable concept with NO price and NO stock. A `VARIANT` is the buyable unit holding `price`, `sku`, `barcode`, `weight`. Stock is per `(variant, location)`.
4. **Inventory is an append-only ledger.** Never overwrite a quantity directly. Every change is a `STOCK_MOVEMENT` row (delta + reason + ref). `qty_on_hand` is derived/cached from movements.
5. **AI-findability comes from good structure + a keywords bridge, not embeddings.** Filterable attributes are first-class columns; categorical fields are enums; `keywords[]`/`use_cases[]` bridge vague natural-language requests to structured data.
6. **Multi-tenant isolation is mandatory.** Every row carries `tenant_id` and `acl[]`. Every query filters by `tenant_id` derived from authenticated JWT/gateway context — **never** from client input.
7. **Strict Subsystem Isolation.** The catalog subsystem operates in complete isolation from Composio connectors (Gmail, GDrive, Calendar, Slack, Notion) and document vector pipelines. It must never interfere with existing connectors or health checks.

---

## 2. Tech Stack (Existing Infra Reuse)

- **Language/API:** Python + FastAPI (matches existing backend services).
- **Frontend:** React + TypeScript + Tailwind CSS + Lucide Icons + Axios.
- **DB:** PostgreSQL (structured source of truth, schema `catalog` in dedicated database `rolesync-micro-catalog`).
- **Queue/Workers:** In-memory `asyncio.Queue` worker with Redis worker compatibility for async CSV batch import.
- **Auth:** Gateway-verified `X-User-Id`, workspace membership of `X-Tenant-Id` checked with workspace-service, and a role that can write (not VIEWER) for changes — see §8.1.
- **No new vector store, no embedding calls in the catalog core.**

---

## 3. Data Model (PostgreSQL — Schema `catalog`)

All tables carry `tenant_id UUID NOT NULL` and compound indexes on `(tenant_id, ...)`. Use `UUID` PKs (`uuid.uuid4`), `created_at`/`updated_at timestamptz`.

### 3.1 `catalog.product` — The Sellable Concept

```sql
id                      uuid PK DEFAULT gen_random_uuid()
tenant_id               uuid NOT NULL
type                    varchar(50) NOT NULL CHECK (type IN ('PRODUCT','SERVICE'))
name                    varchar(255) NOT NULL
category                varchar(100) NOT NULL          -- enum-controlled (§3.9)
subcategory             varchar(100)
status                  varchar(50) NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','ACTIVE','RETIRED'))
description             text
-- AI-Findability / Sales Intelligence layer (all queryable, NOT embedded):
keywords                text[] DEFAULT '{}'            -- synonyms + need-words ("back support","ergonomic")
use_cases               text[] DEFAULT '{}'            -- ("long work days","gaming","travel")
target_industries       text[] DEFAULT '{}'
ideal_customer_profile  text
value_proposition       text
competitors_beats       text[] DEFAULT '{}'
sales_tags              text[] DEFAULT '{}'
-- Guardrails for agent-led pricing:
min_discount_pct        numeric(5,2) DEFAULT 0
max_discount_pct        numeric(5,2) DEFAULT 0
-- Housekeeping & Security:
acl                     text[] NOT NULL                -- {'tenant:<id>','user:<id>'}
version                 int NOT NULL DEFAULT 1
created_at              timestamptz DEFAULT now()
updated_at              timestamptz DEFAULT now()
```

**Indexes:**
- B-Tree: `(tenant_id, status)`, `(tenant_id, category)`
- GIN Indexes: `keywords`, `use_cases`, `target_industries`, `competitors_beats`, `sales_tags`

### 3.2 `catalog.product_option` — Axes of Variation

```sql
id          uuid PK DEFAULT gen_random_uuid()
product_id  uuid FK -> product(id) ON DELETE CASCADE
tenant_id   uuid NOT NULL
name        varchar(100) NOT NULL          -- "Size","Color","Material"
position    int NOT NULL DEFAULT 0
```

### 3.3 `catalog.option_value` — Allowed Values per Option

```sql
id          uuid PK DEFAULT gen_random_uuid()
option_id   uuid FK -> product_option(id) ON DELETE CASCADE
tenant_id   uuid NOT NULL
value       varchar(255) NOT NULL          -- "S","M","L","Black","Graphite"
position    int NOT NULL DEFAULT 0
```

### 3.4 `catalog.variant` — The Buyable Unit (Holds Price)

```sql
id          uuid PK DEFAULT gen_random_uuid()
product_id  uuid FK -> product(id) ON DELETE CASCADE
tenant_id   uuid NOT NULL
sku         varchar(100) NOT NULL
barcode     varchar(100)
price       numeric(12,2) NOT NULL CHECK (price >= 0)
currency    varchar(10) NOT NULL DEFAULT 'USD'
weight      numeric(10,2)
status      varchar(50) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','RETIRED'))
created_at  timestamptz DEFAULT now()
updated_at  timestamptz DEFAULT now()
```
**Constraints:** `UNIQUE (tenant_id, sku)`. Indexes: `(tenant_id, product_id)`, `(tenant_id, price)`.

### 3.5 `catalog.variant_option_value` — Join Table

```sql
variant_id      uuid FK -> variant(id) ON DELETE CASCADE
option_value_id uuid FK -> option_value(id) ON DELETE CASCADE
tenant_id       uuid NOT NULL
PRIMARY KEY (variant_id, option_value_id)
```
**Index:** `(tenant_id, option_value_id)` for cross-product queries ("all Black variants").

### 3.6 `catalog.location` — Place Stock Lives

```sql
id          uuid PK DEFAULT gen_random_uuid()
tenant_id   uuid NOT NULL
name        varchar(255) NOT NULL
type        varchar(50) NOT NULL CHECK (type IN ('WAREHOUSE','STORE','SUPPLIER','IN_TRANSIT'))
sellable    boolean NOT NULL DEFAULT true
priority    int NOT NULL DEFAULT 100        -- lower number = fulfill first
address     jsonb
created_at  timestamptz DEFAULT now()
```

### 3.7 `catalog.inventory_level` — Stock per (Variant × Location)

```sql
id            uuid PK DEFAULT gen_random_uuid()
variant_id    uuid FK -> variant(id) ON DELETE CASCADE
location_id   uuid FK -> location(id) ON DELETE CASCADE
tenant_id     uuid NOT NULL
qty_on_hand   int NOT NULL DEFAULT 0
qty_reserved  int NOT NULL DEFAULT 0
reorder_at    int
created_at    timestamptz DEFAULT now()
updated_at    timestamptz DEFAULT now()
```
**Constraints:** `UNIQUE (variant_id, location_id)`. Index: `(tenant_id, variant_id)`.  
`qty_available = GREATEST(0, qty_on_hand - qty_reserved)` enforced at service level.

### 3.8 `catalog.stock_movement` — Append-Only Ledger

```sql
id             uuid PK DEFAULT gen_random_uuid()
inv_level_id   uuid FK -> inventory_level(id) ON DELETE CASCADE
tenant_id      uuid NOT NULL
delta          int NOT NULL           -- +restock, -sale, -damage, etc.
reason         varchar(50) NOT NULL CHECK (reason IN
                 ('RESTOCK','SALE','RESERVE','RELEASE','TRANSFER_IN','TRANSFER_OUT','ADJUST','DAMAGE'))
ref_id         uuid                   -- links paired moves (transfers) / order id / reservation id
note           text
at             timestamptz DEFAULT now()
created_by     varchar(255)
```
**Index:** `(tenant_id, inv_level_id, at)`. **Never UPDATE or DELETE these rows.**

### 3.9 `catalog.category` — Controlled Vocabulary (per Tenant)

```sql
id          uuid PK DEFAULT gen_random_uuid()
tenant_id   uuid NOT NULL
key         varchar(100) NOT NULL     -- 'office_chair' (machine key)
label       varchar(255) NOT NULL     -- 'Office Chair' (human label)
parent_key  varchar(100)              -- subcategory hierarchy
UNIQUE (tenant_id, key)
```

### 3.10 Derived Read Model: `catalog.v_variant_availability`

```sql
CREATE OR REPLACE VIEW catalog.v_variant_availability AS
SELECT il.tenant_id, il.variant_id,
       GREATEST(0, COALESCE(SUM(GREATEST(0, il.qty_on_hand - il.qty_reserved)), 0)) AS qty_available
FROM catalog.inventory_level il
JOIN catalog.location loc ON loc.id = il.location_id
WHERE loc.sellable = true
GROUP BY il.tenant_id, il.variant_id;
```

---

## 4. `ProductService` — The Single Write Authority

All modifications route through `catalog/service.py`. Direct DB writes from outside the service are strictly forbidden.

### 4.1 Core Product & Variant Authority Methods

```python
class ProductService:
    # ---- Categories ----
    def upsert_category(tenant_id, data: CategoryCreate) -> Category
    def list_categories(tenant_id) -> List[Category]

    # ---- Products ----
    def upsert_product(tenant_id, data: ProductCreate|ProductUpdate, user_id: str, product_id=None) -> Product
    def get_product(tenant_id, product_id: UUID) -> Product
    def list_products(tenant_id, status=None, category=None, subcategory=None, type=None,
                      min_price=None, max_price=None, keywords=None, target_industry=None,
                      in_stock=None, location_id=None, limit=20, offset=0) -> List[Product]
    def delete_product(tenant_id, product_id: UUID) -> Product          # Soft-delete -> RETIRED
    def hard_delete_product(tenant_id, product_id: UUID) -> bool        # Permanent cascaded deletion

    # ---- Options & Candidate Grid ----
    def set_options(tenant_id, product_id: UUID, options: List[ProductOptionCreate]) -> List[ProductOption]
    def generate_variant_grid(tenant_id, product_id: UUID) -> CandidateGridResponse # Cartesian candidate grid
    def upsert_variants(tenant_id, product_id: UUID, variants: List[VariantCreate]) -> List[Variant]
    def get_variant(tenant_id, sku: str) -> Variant

    # ---- Locations ----
    def upsert_location(tenant_id, data: LocationCreate, location_id=None) -> Location
    def list_locations(tenant_id) -> List[Location]
    def delete_location(tenant_id, location_id: UUID) -> bool           # Rejects if active inventory exists

    # ---- Inventory Ledger (Transactional with SELECT ... FOR UPDATE) ----
    def set_stock(tenant_id, variant_id, location_id, qty, reason='RESTOCK', ref_id=None, note=None, created_by=None) -> InventoryLevel
    def batch_set_stock(tenant_id, items: List[SetStockRequest], created_by=None) -> List[InventoryLevel]
    def adjust_stock(tenant_id, variant_id, location_id, delta, reason='ADJUST', ref_id=None, note=None, created_by=None) -> InventoryLevel
    def allocate(tenant_id, variant_id, qty) -> List[ReservationAllocation] # Priority allocation strategy
    def reserve(tenant_id, sku, qty, location_id=None, created_by=None) -> ReservationResponse
    def release(tenant_id, reservation_id: UUID, created_by=None) -> ReleaseStockResponse
    def transfer(tenant_id, sku, from_location_id, to_location_id, qty, note=None, created_by=None) -> TransferStockResponse

    # ---- Availability Reads ----
    def availability(tenant_id, sku: str) -> VariantAvailabilityResponse
    def batch_availability(tenant_id, skus=None) -> Dict[str, VariantAvailabilityResponse]
    def check_availability(tenant_id, sku: str, qty=1, location_id=None) -> CheckAvailabilityResponse
    def describe_catalog(tenant_id) -> DescribeCatalogResponse

    # ---- Validation & AI Intelligence ----
    def validate_rows(tenant_id, rows: List[Dict], auto_create_categories=False) -> ValidationReport
    def generate_findability(name, prod_type='PRODUCT', category=None, subcategory=None, description=None) -> GenerateFindabilityResponse
    def semantic_search(tenant_id, query: str, limit=20) -> SemanticSearchResponse
```

---

## 5. Allocation Rule & Oversell Prevention

When `reserve()` is invoked without a specific location:
1. **Selection:** Filter locations where `tenant_id = :tenant_id AND sellable = true`, ordered by `priority ASC, id ASC`.
2. **Single Location Fast-Path:** If any sellable location has `qty_available >= qty`, allocate entirely to that location.
3. **Multi-Location Split:** If no single location covers the requested quantity, greedily take available stock from each location in priority order until `qty` is fulfilled.
4. **Row-Locking Guarantee:** Acquired via `SELECT ... FOR UPDATE` on inventory levels to guarantee serializability under concurrent checkout. If total sellable availability is less than requested, the transaction aborts with a descriptive `ValueError`.

---

## 6. AI Access Layer (Structured Tools, Not Embeddings)

### 6.1 Tool Interfaces for Autonomous Sales Agents

- `describe_catalog(tenant_id)`: Exposes tenant vocabulary, active categories, filterable attributes, and option types.
- `search_products(tenant_id, filters)`: Multi-attribute structured search matching categories, price bands, in-stock status, and natural language keywords.
- `get_product(tenant_id, product_id)`: Fetches product, option axes, values, and variants.
- `get_variant(tenant_id, sku)`: Exact specification, pricing, and availability lookup.
- `check_availability(tenant_id, sku, qty, location_id?)`: Deterministic check whether order can be fulfilled immediately.
- `create_product`, `edit_product`, `delete_product`: Controlled CRUD operations requiring user confirmation before execution.

### 6.2 AI Intelligence Enhancements (Hybrid AI + Heuristic Engine)

#### Auto-Generate Findability (`generate_findability`)
Analyzes product name, category, and description (minimum 200 characters) to generate:
- 5–8 high-intent search keywords.
- 3–5 real-world use-cases.
- Target industry verticals.
- 1–2 sentence compelling Value Proposition and Ideal Customer Profile (ICP).
- Pricing guardrails (`min_discount_pct`, `max_discount_pct`).

**Execution Strategy:**
- **Tier 1 (OpenRouter AI):** Calls Llama 3.3 70B, Gemma 2 9B, or Liquid LFM with strict JSON output schemas.
- **Tier 2 (Heuristic Fallback):** Token extraction, stop-word elimination, and deterministic industry heuristics when offline or rate-limited.

#### Semantic Search (`semantic_search`)
Structured keyword matching enhanced by AI query expansion:
1. Query expanded into high-intent synonyms and domain terms via OpenRouter LLM.
2. Weighted scoring across fields:
   - Exact query in Name (+25 pts) or SKU (+30 pts).
   - Token in Name/SKU (+15 pts).
   - Token in Category/Keywords (+10 pts).
   - Token in Use Cases (+12 pts).
   - Token in Value Prop (+8 pts) or Description (+4 pts).
3. Results ranked deterministically without embeddings.

---

## 7. Entry Paths & CSV Import Pipeline

### 7.1 Manual UI 5-Step Flow
1. **Create Product Concept:** Name, category, status, description, and AI findability metadata.
2. **Define Option Axes:** Dynamic options (e.g., Size, Color, Finish) and permitted values.
3. **Candidate Grid Generation:** Cartesian generation (`generate_variant_grid`); users activate only valid combinations with unique SKUs and prices.
4. **Set Multi-Location Stock:** Variant × Location matrix persisted via atomic batch updates (`batch_set_stock`).
5. **Finalize & Activate:** Status transitioned to `ACTIVE`.

### 7.2 Advanced CSV Import Pipeline

**Canonical Format (Row per Variant per Location):**
```csv
product_name,type,category,option_size,option_color,sku,price,currency,keywords,use_cases,target_industries,location,qty,reorder_at
```

**7-Step Asynchronous Import Architecture:**
1. **Upload & Ingestion:** Accepts multipart file upload, raw CSV text, or JSON payload; auto-strips UTF-8 BOM.
2. **Dynamic Option Detection:** Any column matching `option_<name>` is parsed into an option axis (e.g., `option_desk_height` → `Desk Height`).
3. **Validation Dry-Run (`validate_rows`):** Checks types, price `>= 0`, SKU collisions, category validity, and reserved stock safety without writing to the database.
4. **Preview & Resolution:** Returns `ValidationReport` with row-by-row error feedback, create vs. update counts, and user option for `skip_invalid=true`.
5. **Background Queue (`CatalogImportWorker`):** Asynchronous execution via `asyncio.Queue` running in a dedicated background thread to prevent blocking web workers.
6. **Idempotent Commit:** Product upsert by name, variant upsert by SKU, location auto-creation, and stock ledger entries.
7. **Job Status API:** Tracks `PENDING`, `VALIDATING`, `COMMITTING`, `COMPLETED`, `FAILED` with percentage progress via `GET /import/jobs/{id}`.

---

## 8. Multi-Tenancy, Security & Authentication Architecture

### 8.1 Identity, Workspace Membership & Roles (`catalog/auth.py`)

Every request passes through `get_catalog_context`:
1. **Identity:** The user id comes only from the `X-User-Id` header, which the API gateway sets after verifying the access-token cookie (client-supplied copies are stripped). Missing → `401 Unauthorized`.
2. **Workspace:** `X-Tenant-Id` (or `X-Workspace-Id`) names the workspace the caller acts in and must be a UUID (missing or malformed → `400 Bad Request`). The caller must be an active member of it, checked with workspace-service (`module_1_document_processing/workspace_access.py`): not a member → `403 Forbidden`; membership can't be verified → `503 Service Unavailable`. Catalog queries are scoped by this tenant id.
3. **Role:** Routes that change catalog data use `get_catalog_writer_context`, which also requires a role that can write (OWNER, ADMIN or MEMBER). Viewers get `403 Forbidden` ("Viewers can't make changes in this workspace", the same rule as the knowledge vault) on category upserts; product create/update/delete; options and variants; location create/update/delete; set, batch-set and adjust stock, reserve, release and transfer; and CSV import commit. Reads stay open to every member, including the POST routes that don't change data (`/ai/semantic-search`, `/ai/generate-findability`, `/validate-rows`, `/import/validate`).

### 8.2 Input Sanitization & SQL Injection Defense (`catalog/schemas.py`)

All string inputs pass through regex pattern matching detecting:
- Stacked queries (`; DROP`, `; SELECT`, `; UPDATE`).
- Union injection (`UNION ALL SELECT`).
- SQL comment characters (`--`, `/* ... */`).
- Tautology patterns (`OR '1'='1'`).
- DDL statements (`ALTER TABLE`, `TRUNCATE TABLE`).

Length constraints enforced across all text fields (Name `<= 255`, Category `<= 100`, Description `<= 10000`, Value Prop `<= 5000`).

---

## 9. API Routing & Service Integration

### 9.1 Dual-Prefix Route Mounting (`main.py`)

Mounted at two prefixes to support direct microservice access and API Gateway service-namespaced routing:
```python
app.include_router(catalog_router, prefix="/api/v1/catalog")
app.include_router(catalog_router, prefix="/api/v1/data-pipeline/catalog")
```

### 9.2 Route Inventory

| Domain | Method | Endpoint | Description |
|---|---|---|---|
| **Introspection** | `GET` | `/describe` | Tenant catalog vocabulary schema |
| **AI Tools** | `POST` | `/ai/generate-findability` | AI sales metadata auto-generation |
| | `POST` | `/ai/semantic-search` | Query expansion + weighted search |
| **Categories** | `GET`, `POST` | `/categories` | List and upsert tenant categories |
| **Products** | `GET`, `POST` | `/products` | Filtered list and create product |
| | `GET`, `PUT`, `DELETE`| `/products/{id}` | Detail, update, and soft/hard delete |
| **Options & Grid**| `PUT` | `/products/{id}/options` | Replace option axes and values |
| | `GET` | `/products/{id}/variant-grid` | Compute Cartesian candidate grid |
| | `POST` | `/products/{id}/variants` | Persist enabled variants |
| | `GET` | `/variants/{sku}` | Lookup variant by SKU |
| **Locations** | `GET`, `POST` | `/locations` | List and create stock locations |
| | `PUT`, `DELETE` | `/locations/{id}` | Update and safe-delete location |
| **Inventory** | `POST` | `/inventory/set-stock` | Set absolute stock level |
| | `POST` | `/inventory/batch-set-stock` | Atomic multi-item stock update |
| | `POST` | `/inventory/adjust-stock` | Delta adjustment (+/-) |
| | `POST` | `/inventory/reserve` | Multi-location stock reservation |
| | `POST` | `/inventory/release/{id}` | Release active reservation |
| | `POST` | `/inventory/transfer` | Inter-location stock transfer |
| **Availability** | `GET` | `/inventory/availability` | Batch multi-SKU availability |
| | `GET` | `/variants/{sku}/availability` | Single variant breakdown |
| | `GET` | `/variants/{sku}/check-availability` | Can-fulfill validation check |
| **CSV Import** | `GET` | `/import/template.csv` | Download canonical template |
| | `POST` | `/import/validate` | Dry-run validation |
| | `POST` | `/import/commit` | Enqueue background import job |
| | `GET` | `/import/jobs/{id}` | Poll import job progress |
| | `POST` | `/validate-rows` | Direct row list validation |

---

## 10. UI Architecture, Edge Cases & Generic Error Handling

### 10.1 Generic Frontend Interceptor Architecture (`axiosInstance.ts`)

- **401 Token Refresh Queue:** Automatically intercepts `401 Unauthorized` responses. If a token refresh (`/auth/refresh`) is already in progress, subsequent requests are placed into a pending promise queue (`failedQueue`) and replayed once the new token is acquired.
- **Refresh Failure Guard:** If `/auth/refresh` itself returns 401, the queue is cleared, user state is cleared, and `logoutCallback()` executes cleanly.
- **Tenant Context Injection (`catalogApi.ts`):** `getActiveTenantId()` checks Redux store workspace state, falling back to localStorage and finally a fallback UUID, preventing blank-tenant crash loops.

### 10.2 Edge Case Matrix & Resilient Handling

| Edge Case Scenario | Impact | System Defense & UI Resilience |
|---|---|---|
| **Empty Catalog & No Locations** | First-time onboarding experience | UI displays an onboarding state with "Create First Location" and "Add Product" actions; CSV importer auto-creates missing locations and categories if enabled. |
| **Variant Matrix Explosion** | Product with 4 options × 5 values = 625 variants | `generate_variant_grid` computes candidates in memory without saving; UI displays candidate table where users explicitly check which SKUs to activate. Only checked items are saved. |
| **Concurrent Stock Checkout Contention** | Multiple agents/users reserving the same stock | Backend row-locks `InventoryLevel` using `SELECT ... FOR UPDATE`. If stock depletes mid-transaction, rolls back and returns descriptive `400 Insufficient Stock`. UI catches error and triggers automated fresh stock reload. |
| **Location Deletion with Remaining Stock** | Attempting to delete warehouse holding active inventory | Backend refuses with `400 Bad Request` citing remaining units. UI modal shows inventory warning directing user to transfer or adjust stock to 0 first. |
| **Negative Stock Drift Attempt** | Stock adjustment delta exceeds on-hand stock | Backend checks `qty_on_hand + delta >= 0` and `qty_on_hand + delta >= qty_reserved`. UI prevents submitting adjustments that breach reserved limits. |
| **Network Disconnect Mid-Import** | Large CSV upload interrupted | Import executes asynchronously on backend worker (`ImportJobStore`). UI polls `GET /import/jobs/{id}` with exponential backoff; refreshing the browser does not cancel backend progress. |
| **Malformed CSV Header or Encoding** | User uploads Excel export with UTF-8 BOM or mixed delimiters | Parser automatically strips `﻿` BOM; list parser supports comma, semicolon, and JSON arrays; option columns normalize dynamically (`option_desk_height` → `Desk Height`). |
| **Duplicate SKU in CSV or Database** | Accidental SKU collision | Validation dry-run flags collision before writing anything. If valid, worker updates existing variant by SKU idempotently without duplication. |

---

## 11. Subsystem Isolation & Connector Non-Interference Guarantees

The catalog and inventory module is architected to ensure **zero interference** with other subsystems:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            FASTAPI LIFESPAN ROOT                            │
├──────────────────────────────────────┬──────────────────────────────────────┤
│ COMPOSIO CONNECTORS & VECTOR PIPELINE│ CATALOG & INVENTORY MODULE           │
│                                      │                                      │
│ • Gmail / GDrive / Calendar Sync     │ • Dedicated Schema: "catalog"        │
│ • Slack / Notion Sync Schedulers     │ • Dedicated DB: rolesync-micro-catalog│
│ • Composio Webhook Ingestion Queue   │ • Isolated asyncio.Queue Worker      │
│ • Embedding & pgvector Document Vault│ • Zero vector/embedding dependencies  │
│ • Health Check: /health -> UP        │ • Independent routes: /api/v1/catalog│
└──────────────────────────────────────┴──────────────────────────────────────┘
```

1. **Connector Non-Interference:** Composio sync managers (`gmail_sync_manager`, `calendar_sync_manager`, etc.) operate on their own async loops. The catalog worker has its own dedicated queue and thread runner; catalog workloads cannot block or starve connector syncs.
2. **Health Check Decoupling:** Global `/health` endpoint remains independent. If PostgreSQL catalog experiences a transient slowdown, connector ingestion and Eureka status reporting continue unhindered.
3. **Database Segregation:** All catalog tables and views live under the dedicated `catalog` PostgreSQL schema in `rolesync-micro-catalog`, avoiding table collisions or locking with document processing pipelines.
4. **No Side-Effects on Other Connection Checkers:** The module does not touch Composio credentials, OAuth tokens, or third-party webhooks.

---

## 12. Business Logic Invariants ("Business Senses") & Stability Policy

To preserve business integrity across future platform updates:

1. **Single Write Authority:** All catalog writes MUST route through `ProductService`. No direct SQL or raw ORM mutations.
2. **Append-Only Ledger Principle:** Every stock modification MUST generate a `StockMovement` row. Direct modification of `qty_on_hand` without an associated movement is forbidden.
3. **Oversell Prevention Guarantee:** Available stock is strictly `qty_on_hand - qty_reserved`. Reservations lock rows to prevent overselling.
4. **Separation of Concept & Unit:** `Product` represents sellable concept (no price, no stock). `Variant` represents buyable unit (holds price, SKU). `InventoryLevel` represents stock per location.
5. **Non-Breaking API Evolution:** Existing endpoints, field names, and response structures must remain backward compatible. Any new functionality must be additive.

---

## 13. System Architecture Diagram

```
direction down

// ============================================================
// RoleSync — Product & Service Management Architecture
// ============================================================

title Product & Service Management — Complete System Topology

// ---------- ENTRY PATHS & UI ----------
Entry Paths [color: gray] {
  Manual UI [icon: edit, color: blue, label: "Manual UI (React)
5-step product & variant wizard"]
  CSV Import UI [icon: upload, color: blue, label: "CSV Import UI
Dry-run preview & background commit"]
  AI Tools [icon: bot, color: purple, label: "AI Agent Tools
Describe, Search, Check, Reserve"]
}

// ---------- GATEWAY & AUTH CASCADE ----------
Security Boundary [color: orange] {
  Auth Resolver [icon: shield, color: orange, label: "CatalogContext Resolver
Gateway-verified X-User-Id
X-Tenant-Id workspace membership
Writer role for changes"]
  Input Sanitizer [icon: alert-triangle, color: red, label: "Input Sanitizer
SQL injection regex check
Field length boundaries"]
}

// ---------- CATALOG CORE (Single Write Authority) ----------
Core Domain [color: teal] {
  ProductService [icon: box, color: teal, label: "ProductService
Single write authority
Validation · Grid · Ledger"]
  ImportWorker [icon: cpu, color: amber, label: "CatalogImportWorker
Async queue worker · Idempotent SKU commit"]
}

// ---------- DATA STORAGE (Postgres Schema: catalog) ----------
PostgreSQL [color: purple] {
  ProductModel [icon: package, color: purple, label: "product & category
AI findability · ICP · Guardrails"]
  VariantModel [icon: grid, color: purple, label: "variant & options
SKU(unique) · Price · Option join"]
  InventoryModel [icon: database, color: green, label: "location & inventory_level
(variant x location) stock"]
  LedgerModel [icon: activity, color: green, label: "stock_movement
Append-only ledger · Audit trail"]
  AvailabilityView [icon: bar-chart, color: coral, label: "v_variant_availability
Sellable stock aggregation view"]
}

// ---------- ISOLATION BOUNDARY (Other Subsystems) ----------
Protected Systems [color: gray] {
  Composio Connectors [icon: link, color: gray, label: "Composio Connectors (ISOLATED)
Gmail, GDrive, Slack, Notion, Calendar"]
  Vector Engine [icon: layers, color: gray, label: "Vector & RAG Engine (ISOLATED)
MongoDB, chunking, embeddings"]
}

// ---------- FLOWS ----------
Manual UI > Security Boundary: HTTP with JWT / Headers
CSV Import UI > Security Boundary: CSV payload / multipart
AI Tools > Security Boundary: Internal tool execution

Security Boundary > ProductService: Authenticated CatalogContext
Security Boundary > Input Sanitizer: Payload validation

ProductService > ProductModel: Validated upsert
ProductService > VariantModel: Variant grid & pricing
ProductService > InventoryModel: Location stock management
ProductService > LedgerModel: Append-only stock movements
ProductService > AvailabilityView: Read sellable availability

ImportWorker > ProductService: Batched idempotent writes
```
