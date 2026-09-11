import asyncio
import csv
import io
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import joinedload

from catalog.database import SessionLocal
from catalog.models import (
    Category,
    InventoryLevel,
    Location,
    Product,
    ProductOption,
    OptionValue,
    Variant,
    VariantOptionValue,
)
from catalog.schemas import (
    CategoryCreate,
    LocationCreate,
    OptionValueCreate,
    ProductCreate,
    ProductOptionCreate,
    ProductUpdate,
    VariantCreate,
)
from catalog.service import ProductService

logger = logging.getLogger("catalog.csv_importer")

# ---------------------------------------------------------------------------
# Canonical Template Specification
# ---------------------------------------------------------------------------

CANONICAL_COLUMNS = [
    "product_name",
    "type",
    "category",
    "option_size",
    "option_color",
    "sku",
    "price",
    "currency",
    "keywords",
    "use_cases",
    "target_industries",
    "location",
    "qty",
    "reorder_at",
]

SAMPLE_CSV_ROWS = [
    {
        "product_name": "Ergonomic Executive Chair",
        "type": "PRODUCT",
        "category": "office_chair",
        "option_size": "L",
        "option_color": "Black",
        "sku": "CHAIR-EXEC-L-BLK",
        "price": "299.99",
        "currency": "USD",
        "keywords": "ergonomic, lumbar, mesh",
        "use_cases": "office, work from home",
        "target_industries": "technology, finance",
        "location": "Main Warehouse",
        "qty": "50",
        "reorder_at": "10",
    },
    {
        "product_name": "Ergonomic Executive Chair",
        "type": "PRODUCT",
        "category": "office_chair",
        "option_size": "M",
        "option_color": "Black",
        "sku": "CHAIR-EXEC-M-BLK",
        "price": "279.99",
        "currency": "USD",
        "keywords": "ergonomic, lumbar, mesh",
        "use_cases": "office, work from home",
        "target_industries": "technology, finance",
        "location": "Main Warehouse",
        "qty": "40",
        "reorder_at": "10",
    },
    {
        "product_name": "Ergonomic Executive Chair",
        "type": "PRODUCT",
        "category": "office_chair",
        "option_size": "L",
        "option_color": "Gray",
        "sku": "CHAIR-EXEC-L-GRY",
        "price": "299.99",
        "currency": "USD",
        "keywords": "ergonomic, lumbar, mesh",
        "use_cases": "office, work from home",
        "target_industries": "technology, finance",
        "location": "Secondary Warehouse",
        "qty": "25",
        "reorder_at": "5",
    },
    {
        "product_name": "Standing Desk Pro",
        "type": "PRODUCT",
        "category": "office_desk",
        "option_size": "140x70cm",
        "option_color": "Oak",
        "sku": "DESK-PRO-140-OAK",
        "price": "599.00",
        "currency": "USD",
        "keywords": "standing desk, motorized, electric",
        "use_cases": "office, ergonomics",
        "target_industries": "technology, creative",
        "location": "Main Warehouse",
        "qty": "15",
        "reorder_at": "3",
    },
]


def generate_csv_template() -> str:
    """Generate downloadable canonical CSV template content with headers and sample data."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CANONICAL_COLUMNS)
    writer.writeheader()
    for row in SAMPLE_CSV_ROWS:
        writer.writerow(row)
    return output.getvalue()


# ---------------------------------------------------------------------------
# CSV Parsing & Dynamic Option Helpers
# ---------------------------------------------------------------------------

def parse_list_field(val: Any) -> List[str]:
    """Parse comma/semicolon/JSON array separated strings into a list of strings."""
    if not val:
        return []
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    val_str = str(val).strip()
    if not val_str:
        return []
    if val_str.startswith("[") and val_str.endswith("]"):
        try:
            parsed = json.loads(val_str)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            pass
    delimiter = ";" if ";" in val_str and "," not in val_str else ","
    return [item.strip() for item in val_str.split(delimiter) if item.strip()]


def normalize_option_name(col_name: str) -> str:
    """Extract and format option axis name from 'option_<name>' column.
    
    e.g. 'option_size' -> 'Size', 'option_color' -> 'Color', 'option_desk_height' -> 'Desk Height'.
    """
    if not col_name.lower().startswith("option_"):
        return ""
    raw_name = col_name[len("option_"):].strip()
    if not raw_name:
        return ""
    return raw_name.replace("_", " ").title()


def parse_csv(csv_content: str | bytes) -> List[Dict[str, Any]]:
    """Parse CSV text or bytes into a list of cleaned row dictionaries."""
    if isinstance(csv_content, bytes):
        text_content = csv_content.decode("utf-8-sig", errors="replace")
    else:
        text_content = csv_content
        if text_content.startswith("\ufeff"):
            text_content = text_content[1:]

    reader = csv.DictReader(io.StringIO(text_content.strip()))
    rows: List[Dict[str, Any]] = []
    for r in reader:
        cleaned: Dict[str, Any] = {}
        for k, v in r.items():
            if k is not None and str(k).strip():
                cleaned_k = str(k).strip()
                cleaned_v = v.strip() if isinstance(v, str) else v
                cleaned[cleaned_k] = cleaned_v
        if any(cleaned.values()):
            rows.append(cleaned)
    return rows


@dataclass
class ParsedProductGroup:
    product_name: str
    product_type: str
    category: str
    description: Optional[str]
    keywords: List[str]
    use_cases: List[str]
    target_industries: List[str]
    options: Dict[str, List[str]] = field(default_factory=dict)
    variants: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    inventory: List[Dict[str, Any]] = field(default_factory=list)
    row_indices: List[int] = field(default_factory=list)


def group_rows_by_product(rows: List[Dict[str, Any]]) -> List[ParsedProductGroup]:
    """Group flat rows by product_name, detect dynamic options, variants, and inventory."""
    groups_by_name: Dict[str, ParsedProductGroup] = {}

    for idx, row in enumerate(rows):
        p_name = (row.get("product_name") or row.get("name") or "").strip()
        if not p_name:
            continue

        p_type = (row.get("type") or "PRODUCT").strip().upper()
        if p_type not in ("PRODUCT", "SERVICE"):
            p_type = "PRODUCT"

        cat = (row.get("category") or "").strip()
        desc = row.get("description")
        kws = parse_list_field(row.get("keywords"))
        use_cases = parse_list_field(row.get("use_cases"))
        target_ind = parse_list_field(row.get("target_industries"))

        if p_name not in groups_by_name:
            groups_by_name[p_name] = ParsedProductGroup(
                product_name=p_name,
                product_type=p_type,
                category=cat,
                description=desc,
                keywords=kws,
                use_cases=use_cases,
                target_industries=target_ind,
            )

        group = groups_by_name[p_name]
        group.row_indices.append(idx)

        # Merge metadata if current group has empty values
        if not group.category and cat:
            group.category = cat
        if not group.description and desc:
            group.description = desc
        for kw in kws:
            if kw not in group.keywords:
                group.keywords.append(kw)
        for uc in use_cases:
            if uc not in group.use_cases:
                group.use_cases.append(uc)
        for ti in target_ind:
            if ti not in group.target_industries:
                group.target_industries.append(ti)

        # Detect dynamic option columns (option_*)
        row_variant_options: Dict[str, str] = {}
        for col_k, col_v in row.items():
            if col_k.lower().startswith("option_") and col_v:
                opt_name = normalize_option_name(col_k)
                opt_val = str(col_v).strip()
                if opt_val:
                    if opt_name not in group.options:
                        group.options[opt_name] = []
                    if opt_val not in group.options[opt_name]:
                        group.options[opt_name].append(opt_val)
                    row_variant_options[opt_name] = opt_val

        # Variant information
        sku = (row.get("sku") or "").strip()
        raw_price = row.get("price")
        currency = (row.get("currency") or "USD").strip().upper()

        if sku:
            price = Decimal(str(raw_price).strip()) if raw_price is not None and str(raw_price).strip() != "" else Decimal("0")
            if sku not in group.variants:
                group.variants[sku] = {
                    "sku": sku,
                    "price": price,
                    "currency": currency,
                    "barcode": row.get("barcode"),
                    "weight": Decimal(str(row["weight"])) if row.get("weight") else None,
                    "options": row_variant_options,
                }
            else:
                # Update price/options if previously not populated
                if price > Decimal("0") and group.variants[sku]["price"] == Decimal("0"):
                    group.variants[sku]["price"] = price
                for k, v in row_variant_options.items():
                    group.variants[sku]["options"][k] = v

            # Inventory mapping (sku, location)
            loc = (row.get("location") or "").strip()
            raw_qty = row.get("qty")
            raw_reorder = row.get("reorder_at")
            if loc and raw_qty is not None and str(raw_qty).strip() != "":
                try:
                    qty = int(str(raw_qty).strip())
                    reorder_at = int(str(raw_reorder).strip()) if raw_reorder is not None and str(raw_reorder).strip() != "" else None
                    group.inventory.append({
                        "sku": sku,
                        "location": loc,
                        "qty": qty,
                        "reorder_at": reorder_at,
                    })
                except ValueError:
                    pass

    return list(groups_by_name.values())


# ---------------------------------------------------------------------------
# Job Store & Status Tracking
# ---------------------------------------------------------------------------

class ImportJob(BaseModel):
    job_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    user_id: str
    status: str = "PENDING"  # PENDING, PROCESSING, COMPLETED, FAILED
    progress_pct: float = 0.0
    total_rows: int = 0
    created_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    errors: List[str] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    csv_content: str = ""
    skip_invalid: bool = False
    auto_create_categories: bool = True

    model_config = ConfigDict(from_attributes=True)


class ImportJobStore:
    """Thread-safe in-memory store for import jobs with tenant isolation."""

    def __init__(self):
        self._jobs: Dict[UUID, ImportJob] = {}

    def create_job(
        self,
        tenant_id: UUID,
        user_id: str,
        csv_content: str,
        skip_invalid: bool = False,
        auto_create_categories: bool = True,
    ) -> ImportJob:
        job = ImportJob(
            tenant_id=tenant_id,
            user_id=user_id,
            csv_content=csv_content,
            skip_invalid=skip_invalid,
            auto_create_categories=auto_create_categories,
        )
        self._jobs[job.job_id] = job
        return job

    def get_job(
        self, job_id: UUID, tenant_id: Optional[UUID] = None
    ) -> Optional[ImportJob]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        if tenant_id is not None and job.tenant_id != tenant_id:
            return None
        return job

    def clear(self) -> None:
        self._jobs.clear()


# ---------------------------------------------------------------------------
# Catalog Import Worker / Job Runner
# ---------------------------------------------------------------------------

class CatalogImportWorker:
    """Async background worker for processing CSV import jobs idempotently via ProductService."""

    def __init__(self, job_store: Optional[ImportJobStore] = None):
        self.job_store = job_store or ImportJobStore()
        self._queue: Optional[asyncio.Queue[UUID]] = None
        self._worker_task: Optional[asyncio.Task] = None
        self._background_tasks: Set[asyncio.Task] = set()
        self._is_running = False

    def _get_queue(self) -> asyncio.Queue[UUID]:
        if self._queue is None:
            self._queue = asyncio.Queue()
        return self._queue

    async def start(self) -> None:
        if self._is_running:
            return
        self._is_running = True
        self._queue = asyncio.Queue()
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("CatalogImportWorker started.")

    async def stop(self) -> None:
        if not self._is_running:
            return
        self._is_running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        for task in list(self._background_tasks):
            task.cancel()
        logger.info("CatalogImportWorker stopped.")

    async def enqueue(self, job_id: UUID) -> None:
        """Enqueue job ID for background processing."""
        if self._is_running:
            await self._get_queue().put(job_id)
        else:
            # Fallback when worker loop is not running (e.g. standalone test execution)
            task = asyncio.create_task(self.process_job(job_id))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    def create_job(
        self,
        tenant_id: UUID,
        user_id: str,
        csv_content: str,
        skip_invalid: bool = False,
        auto_create_categories: bool = True,
    ) -> ImportJob:
        return self.job_store.create_job(
            tenant_id=tenant_id,
            user_id=user_id,
            csv_content=csv_content,
            skip_invalid=skip_invalid,
            auto_create_categories=auto_create_categories,
        )

    def get_job(
        self, job_id: UUID, tenant_id: Optional[UUID] = None
    ) -> Optional[ImportJob]:
        return self.job_store.get_job(job_id, tenant_id=tenant_id)

    async def _worker_loop(self) -> None:
        q = self._get_queue()
        while self._is_running:
            try:
                job_id = await q.get()
                await self.process_job(job_id)
                q.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Unhandled error in CatalogImportWorker: {e}")

    async def process_job(self, job_id: UUID) -> None:
        """Process import job asynchronously using a background thread for database I/O."""
        job = self.job_store.get_job(job_id)
        if not job:
            return

        job.status = "PROCESSING"
        job.started_at = datetime.now(timezone.utc)
        job.progress_pct = 0.0

        try:
            await asyncio.to_thread(self._execute_import, job)
        except Exception as e:
            logger.exception(f"Fatal error executing import job {job_id}: {e}")
            job.status = "FAILED"
            job.errors.append(f"Fatal execution error: {str(e)}")
            job.completed_at = datetime.now(timezone.utc)

    def _execute_import(self, job: ImportJob) -> None:
        """Synchronous import processor executed in worker thread."""
        raw_rows = parse_csv(job.csv_content)
        job.total_rows = len(raw_rows)

        if job.total_rows == 0:
            job.status = "COMPLETED"
            job.progress_pct = 100.0
            job.completed_at = datetime.now(timezone.utc)
            return

        db = SessionLocal()
        service = ProductService(db)

        try:
            # 1. Dry run validation
            report = service.validate_rows(
                tenant_id=job.tenant_id,
                rows=raw_rows,
                auto_create_categories=job.auto_create_categories,
            )

            # Check for validation failures
            if report.error_count > 0:
                if not job.skip_invalid:
                    job.status = "FAILED"
                    for r in report.row_results:
                        if not r.valid:
                            job.errors.append(
                                f"Row {r.row_index + 1}: {', '.join(r.errors)}"
                            )
                    job.completed_at = datetime.now(timezone.utc)
                    return
                else:
                    # Record skipped rows
                    for r in report.row_results:
                        if not r.valid:
                            job.skipped_count += 1
                            job.errors.append(
                                f"Row {r.row_index + 1} skipped: {', '.join(r.errors)}"
                            )

            # Filter rows to import
            if job.skip_invalid:
                valid_indices = {r.row_index for r in report.row_results if r.valid}
                rows_to_process = [
                    row for idx, row in enumerate(raw_rows) if idx in valid_indices
                ]
            else:
                rows_to_process = raw_rows

            if not rows_to_process:
                job.status = "COMPLETED"
                job.progress_pct = 100.0
                job.completed_at = datetime.now(timezone.utc)
                return

            # 2. Group rows by product_name
            groups = group_rows_by_product(rows_to_process)
            total_groups = len(groups)

            # 3. Process each product group through ProductService
            for g_idx, group in enumerate(groups):
                try:
                    # A. Upsert Category if provided
                    if group.category and job.auto_create_categories:
                        cat_exists = (
                            db.query(Category)
                            .filter(
                                Category.tenant_id == job.tenant_id,
                                Category.key == group.category,
                            )
                            .first()
                        )
                        if not cat_exists:
                            service.upsert_category(
                                job.tenant_id,
                                CategoryCreate(
                                    key=group.category,
                                    label=group.category.replace("_", " ").title(),
                                ),
                            )

                    # B. Upsert Product strictly by name within tenant
                    existing_product = (
                        db.query(Product)
                        .filter(
                            Product.tenant_id == job.tenant_id,
                            Product.name == group.product_name,
                        )
                        .first()
                    )

                    if existing_product:
                        p_data = ProductUpdate(
                            name=group.product_name,
                            type=group.product_type,
                            category=group.category,
                            description=group.description,
                            keywords=group.keywords,
                            use_cases=group.use_cases,
                            target_industries=group.target_industries,
                            status="ACTIVE",
                        )
                        product = service.upsert_product(
                            tenant_id=job.tenant_id,
                            data=p_data,
                            user_id=job.user_id,
                            product_id=existing_product.id,
                        )
                    else:
                        p_data = ProductCreate(
                            name=group.product_name,
                            type=group.product_type,
                            category=group.category,
                            description=group.description,
                            keywords=group.keywords,
                            use_cases=group.use_cases,
                            target_industries=group.target_industries,
                            status="ACTIVE",
                        )
                        product = service.upsert_product(
                            tenant_id=job.tenant_id,
                            data=p_data,
                            user_id=job.user_id,
                        )

                    # C. Set Options if present (merged with existing options if present)
                    opt_val_map: Dict[Tuple[str, str], UUID] = {}
                    if group.options:
                        # If existing product already had options, check if we need to update
                        existing_opts = (
                            db.query(ProductOption)
                            .options(joinedload(ProductOption.values))
                            .filter(
                                ProductOption.tenant_id == job.tenant_id,
                                ProductOption.product_id == product.id,
                            )
                            .order_by(ProductOption.position.asc())
                            .all()
                        )
                        existing_opt_dict: Dict[str, List[str]] = {
                            o.name: [val.value for val in o.values]
                            for o in existing_opts
                        }

                        # Check if group.options adds any new option axes or values
                        needs_option_update = False
                        merged_options: Dict[str, List[str]] = {}

                        # Map case-insensitive existing names
                        existing_name_map = {name.lower(): name for name in existing_opt_dict}

                        for name, vals in existing_opt_dict.items():
                            merged_options[name] = list(vals)

                        for opt_name, opt_values in group.options.items():
                            norm_key = opt_name.lower()
                            if norm_key in existing_name_map:
                                actual_name = existing_name_map[norm_key]
                                for v in opt_values:
                                    if v not in merged_options[actual_name]:
                                        merged_options[actual_name].append(v)
                                        needs_option_update = True
                            else:
                                merged_options[opt_name] = list(opt_values)
                                needs_option_update = True

                        if not existing_opts or needs_option_update:
                            # If updating existing product with previous variants not in this batch,
                            # remember previous variant-option value mappings to restore them
                            existing_variant_opt_names: Dict[str, List[Tuple[str, str]]] = {}
                            if existing_opts:
                                prev_vars = (
                                    db.query(Variant)
                                    .options(
                                        joinedload(Variant.option_values).joinedload(OptionValue.option)
                                    )
                                    .filter(
                                        Variant.tenant_id == job.tenant_id,
                                        Variant.product_id == product.id,
                                    )
                                    .all()
                                )
                                for pv in prev_vars:
                                    if pv.sku not in group.variants:
                                        existing_variant_opt_names[pv.sku] = [
                                            (ov.option.name.lower(), ov.value.lower())
                                            for ov in pv.option_values
                                            if ov.option
                                        ]

                            options_create = []
                            for pos, (opt_name, opt_values) in enumerate(merged_options.items()):
                                val_creates = [
                                    OptionValueCreate(value=v, position=v_pos)
                                    for v_pos, v in enumerate(opt_values)
                                ]
                                options_create.append(
                                    ProductOptionCreate(
                                        name=opt_name, position=pos, values=val_creates
                                    )
                                )
                            saved_options = service.set_options(
                                job.tenant_id, product.id, options_create
                            )
                            for s_opt in saved_options:
                                for s_val in s_opt.values:
                                    opt_val_map[
                                        (s_opt.name.strip().lower(), s_val.value.strip().lower())
                                    ] = s_val.id

                            # Restore variant option associations for variants not in current batch
                            for pv_sku, opt_pairs in existing_variant_opt_names.items():
                                pv = (
                                    db.query(Variant)
                                    .filter(
                                        Variant.tenant_id == job.tenant_id,
                                        Variant.sku == pv_sku,
                                    )
                                    .first()
                                )
                                if pv:
                                    for opt_pair in opt_pairs:
                                        if opt_pair in opt_val_map:
                                            vov = VariantOptionValue(
                                                variant_id=pv.id,
                                                option_value_id=opt_val_map[opt_pair],
                                                tenant_id=job.tenant_id,
                                            )
                                            db.add(vov)
                                    db.commit()
                        else:
                            # Existing options are identical and sufficient; reuse their IDs
                            for s_opt in existing_opts:
                                for s_val in s_opt.values:
                                    opt_val_map[
                                        (s_opt.name.strip().lower(), s_val.value.strip().lower())
                                    ] = s_val.id

                    # D. Upsert Variants
                    sku_list = list(group.variants.keys())
                    existing_skus = set(
                        row[0]
                        for row in db.query(Variant.sku)
                        .filter(
                            Variant.tenant_id == job.tenant_id,
                            Variant.sku.in_(sku_list),
                        )
                        .all()
                    )

                    variant_creates = []
                    for sku, v_info in group.variants.items():
                        opt_ids = []
                        for opt_k, opt_v in v_info.get("options", {}).items():
                            key = (opt_k.strip().lower(), opt_v.strip().lower())
                            if key in opt_val_map:
                                opt_ids.append(opt_val_map[key])

                        variant_creates.append(
                            VariantCreate(
                                sku=sku,
                                price=v_info["price"],
                                currency=v_info.get("currency", "USD"),
                                barcode=v_info.get("barcode"),
                                weight=v_info.get("weight"),
                                status="ACTIVE",
                                option_value_ids=opt_ids,
                            )
                        )

                    service.upsert_variants(job.tenant_id, product.id, variant_creates)

                    for sku in sku_list:
                        if sku in existing_skus:
                            job.updated_count += 1
                        else:
                            job.created_count += 1

                    # E. Set Stock per Location via ledger
                    loc_cache: Dict[str, Location] = {}
                    for inv_item in group.inventory:
                        loc_name = inv_item["location"]
                        sku = inv_item["sku"]
                        qty = inv_item["qty"]
                        reorder_at = inv_item.get("reorder_at")

                        if not loc_name or qty is None:
                            continue

                        if loc_name not in loc_cache:
                            loc = (
                                db.query(Location)
                                .filter(
                                    Location.tenant_id == job.tenant_id,
                                    Location.name == loc_name,
                                )
                                .first()
                            )
                            if not loc:
                                loc = service.upsert_location(
                                    job.tenant_id,
                                    LocationCreate(
                                        name=loc_name,
                                        type="WAREHOUSE",
                                        sellable=True,
                                        priority=100,
                                    ),
                                )
                            loc_cache[loc_name] = loc
                        else:
                            loc = loc_cache[loc_name]

                        var = service.get_variant(job.tenant_id, sku)
                        inv_level = service.set_stock(
                            tenant_id=job.tenant_id,
                            variant_id=var.id,
                            location_id=loc.id,
                            qty=qty,
                            reason="RESTOCK",
                            note="CSV initial import",
                            created_by=job.user_id,
                        )
                        if reorder_at is not None:
                            inv_level.reorder_at = reorder_at
                            db.commit()

                except Exception as exc:
                    logger.exception(
                        f"Error importing product '{group.product_name}': {exc}"
                    )
                    if job.skip_invalid:
                        job.skipped_count += len(group.row_indices)
                        job.errors.append(f"Product '{group.product_name}': {str(exc)}")
                        db.rollback()
                    else:
                        db.rollback()
                        raise exc

                job.progress_pct = round(((g_idx + 1) / total_groups) * 100.0, 1)

            job.status = "COMPLETED"
            job.progress_pct = 100.0
            job.completed_at = datetime.now(timezone.utc)

        finally:
            db.close()


# Default singleton instances
import_job_store = ImportJobStore()
catalog_import_worker = CatalogImportWorker(job_store=import_job_store)
