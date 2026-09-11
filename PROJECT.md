# Project: Role-Sync FuLL Arch

## Architecture

* Role-Sync is a microservices architecture with a Spring Boot backend (Gateway, Auth-Service, Config-Service, etc.) and a React Vite frontend.

[Eraser IO ] Overvall Core HLD - Chnage to mermaid

title Full System HLD

// 1. Client Layer
Client Layer [icon: monitor] {
  React Dashboard [icon: react]
}

// 2. Spring Cloud Ecosystem
Spring Cloud Ecosystem [direction: right, color: blue] {
  Config Server [icon: settings]
  Eureka Server [icon: list]
  API Gateway [icon: server]
}

// 3. Core Business Services
Business Services [direction: down] {
  Auth Service [icon: shield]
  Workspace Service [icon: user]
  Billing Service [icon: credit-card]
  Task Orchestration Service [icon: settings]
  Notification Service [icon: mail]
}

// 4. Databases
Databases [direction: down] {
  Auth DB [icon: postgres]
  Workspace DB [icon: database]
  Billing DB [icon: database]
  Tasks DB [icon: database]
  Vector DB (pgvector) [icon: database]
  Notification Store (Redis Logs) [icon: database]
}

// 5. Event Infrastructure
Event Bus [icon: share-2] {
  Message Broker (Kafka) [icon: activity]
}

// 6. AI Engine
AI Engine [direction: down] {
  Knowledge & RAG Service [icon: file-text]
  AI Agent Service (LangGraph) [icon: cpu]
}

// 7. External Integrations
External Integrations [direction: down] {
  Payment Gateway (Stripe eSewa) [icon: globe]
  Email Provider (SMTP) [icon: send]
  External LLMs (OpenAI Anthropic) [icon: cloud]
}

// --- CONNECTIONS ---

// Client Ingress
React Dashboard > API Gateway : HTTPS

// Spring Cloud Governance
API Gateway > Eureka Server : Fetch Routes
Business Services > Eureka Server : Register Service
Business Services > Config Server : Fetch application.yml
API Gateway > Config Server : Load Gateway Config

// Gateway Routing
API Gateway > Auth Service : /api/v1/auth
API Gateway > Workspace Service : /api/v1/workspace
API Gateway > Billing Service : /api/v1/billing
API Gateway > Task Orchestration Service : /api/v1/tasks
API Gateway > Knowledge & RAG Service : /api/v1/documents

// DB Connections
Auth Service > Auth DB
Workspace Service > Workspace DB
Billing Service > Billing DB
Task Orchestration Service > Tasks DB
Notification Service > Notification Store (Redis Logs)
Knowledge & RAG Service > Vector DB (pgvector)

// Internal Sync Calls
Task Orchestration Service > Billing Service : Check Credits
AI Agent Service (LangGraph) > Knowledge & RAG Service : Get Context

// Async Event Flow
Task Orchestration Service > Message Broker (Kafka) : Publish Task
Message Broker (Kafka) > AI Agent Service (LangGraph) : Consume Task
AI Agent Service (LangGraph) > Message Broker (Kafka) : Publish Result
Message Broker (Kafka) > Task Orchestration Service : Save Artifact
Message Broker (Kafka) > Notification Service : Consume TaskCompleted

// Notification Flow
Notification Service > Email Provider (SMTP) : Send Alert
Notification Service > React Dashboard : WebSocket Push (Optional)

// External Outbound
Billing Service > Payment Gateway (Stripe eSewa) : Verify
AI Agent Service (LangGraph) > External LLMs (OpenAI Anthropic) : Generate

## Data Pipline

### DATA INGESTION PIPELINE

** link : \backend\data-pipeline\doc\arch.md

### Product / Service Management

direction down

// ============================================================
// RoleSync — Product & Service Management (FINAL)
// [BUILD] = new code · [REUSE] = existing infra
// Structured-only. No embeddings for catalog. AI queries via tools.
// ============================================================

title Product & Service Management — Final Architecture

// ---------- ENTRY PATHS ----------
Entry Paths [color: gray] {
  Manual UI [icon: edit, color: blue, label: "Manual UI [BUILD]\n5-step: product → options →\nvariant grid → stock → save"]
  CSV Import [icon: upload, color: blue, label: "CSV Import [BUILD]\nrow-per-variant-per-location"]
  API Sync [icon: code, color: gray, label: "API sync [STUB]\nShopify / ERP (future)"]
}

// ---------- IMPORT PIPELINE (async, reuses workers) ----------
Import Pipeline [color: amber] {
  Parse Group [icon: git-merge, color: amber, label: "Parse & group\nflat rows → hierarchy"]
  Validate [icon: check-square, color: amber, label: "Validate (dry run)\nall errors, no writes"]
  Error Report [icon: alert-circle, color: red, label: "Preview / error report\nreject-all or skip-invalid"]
  Import Queue [icon: list, color: orange, shape: cylinder, label: "Import queue [REUSE]\nRedis + workers"]
  Import Worker [icon: cpu, color: amber, label: "Import worker\nupsert by SKU, idempotent"]
}

// ---------- SHARED CORE (single write authority) ----------
Core [color: teal] {
  ProductService [icon: box, color: teal, label: "ProductService [BUILD]\nSINGLE owner of all writes\nvalidation · variant-gen · ledger"]
}

// ---------- CATALOG (product concept — purple) ----------
Catalog [color: purple] {
  Product [icon: package, color: purple, shape: cylinder, label: "PRODUCT\nname, category(enum), status\nkeywords[], use_cases[], sales_intel\ndiscount guardrails, acl[]"]
  ProductOption [icon: sliders, color: purple, shape: cylinder, label: "PRODUCT_OPTION\nSize, Color, Material"]
  OptionValue [icon: tag, color: purple, shape: cylinder, label: "OPTION_VALUE\nS/M/L, Black/Graphite"]
  Variant [icon: grid, color: purple, shape: cylinder, label: "VARIANT (buyable unit)\nsku(unique), PRICE, barcode, weight"]
  VariantOptionValue [icon: link, color: purple, shape: cylinder, label: "VARIANT_OPTION_VALUE\njoin: variant ↔ option values"]
  Category [icon: book, color: purple, shape: cylinder, label: "CATEGORY (per tenant)\ncontrolled vocabulary / enum"]
}

// ---------- INVENTORY (where & how much — green) ----------
Inventory [color: green] {
  Location [icon: map-pin, color: green, shape: cylinder, label: "LOCATION\ntype, sellable, priority"]
  InventoryLevel [icon: database, color: green, shape: cylinder, label: "INVENTORY_LEVEL\n(variant × location)\nqty_on_hand, qty_reserved"]
  StockMovement [icon: activity, color: green, shape: cylinder, label: "STOCK_MOVEMENT\nappend-only ledger, delta+ref"]
}

// ---------- SELL LOGIC (derived — coral) ----------
Sell Logic [color: coral] {
  Availability [icon: bar-chart, color: coral, label: "v_variant_availability\nSUM over sellable locations"]
  Allocation [icon: git-branch, color: coral, label: "Allocation / reserve\npriority location, no oversell"]
  Transfers [icon: repeat, color: coral, label: "Transfers\npaired movements, same ref_id"]
}

// ---------- STORE (single source of truth) ----------
Store [color: teal] {
  Postgres [icon: database, color: teal, label: "PostgreSQL (structured)\nSINGLE source of truth\nno embeddings for catalog"]
}

// ---------- AI ACCESS LAYER (tools, not embeddings) ----------
AI Access [color: pink] {
  DescribeCatalog [icon: info, color: pink, label: "describe_catalog()\nteaches AI the vocabulary"]
  SearchProducts [icon: search, color: pink, label: "search_products(filters+keywords)\nvague → structured filters"]
  ReadTools [icon: eye, color: pink, label: "get_product / get_variant\ncheck_availability"]
  CrudTools [icon: tool, color: pink, label: "create / edit / delete\n(human-in-the-loop)"]
}

// ---------- CONSUMERS ----------
Consumers [color: blue] {
  SalesAgent [icon: bot, color: blue, label: "Sales agent\ndecomposes request → tool calls"]
  QuoteBuilder [icon: file, color: blue, label: "Quote builder\nvariant + price + reserve"]
  CatalogUI [icon: layout, color: blue, label: "Catalog / inventory UI"]
}

// ================= FLOWS =================

// entry → import → service
Manual UI > ProductService: direct calls (validated)
CSV Import > Parse Group: file
API Sync > Parse Group: payload
Parse Group > Validate: grouped hierarchy
Validate > Error Report: issues found
Validate > Import Queue: if clean
Import Queue > Import Worker: batched jobs
Import Worker > ProductService: upsert by SKU

// service owns ALL writes to catalog + inventory
ProductService > Product: upsert
ProductService > Variant: upsert (price here)
ProductService > InventoryLevel: set stock
ProductService > StockMovement: log delta (append-only)

// catalog internal relations
Product > ProductOption: has
ProductOption > OptionValue: has
Product > Variant: sold as
Variant > VariantOptionValue: defined by
OptionValue > VariantOptionValue: used in
Product > Category: classified by

// inventory relations
Variant > InventoryLevel: stocked in
Location > InventoryLevel: holds
InventoryLevel > StockMovement: logs

// derived sell logic
InventoryLevel > Availability: sum sellable
Availability > Allocation: what can reserve
Allocation > StockMovement: reserve = movement
Location > Transfers: between locations

// everything persists to Postgres (one source of truth)
Product > Postgres: structured
Variant > Postgres: structured
InventoryLevel > Postgres: structured
StockMovement > Postgres: structured

// AI access layer reads/writes ONLY through tools over Postgres
DescribeCatalog > Postgres: schema + vocabulary
SearchProducts > Postgres: filtered query
SearchProducts > Availability: in-stock filter
ReadTools > Postgres: exact lookup
CrudTools > ProductService: validated writes

// consumers use the AI tools
SalesAgent > DescribeCatalog: learn vocabulary
SalesAgent > SearchProducts: find by need
SalesAgent > ReadTools: exact price/stock
QuoteBuilder > ReadTools: variant + price
QuoteBuilder > Allocation: reserve stock
CatalogUI > ProductService: manual edits