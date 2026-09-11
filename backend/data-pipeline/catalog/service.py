import itertools
import json
import logging
import os
import re
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import or_, func, text
from sqlalchemy.orm import Session, joinedload, selectinload

from catalog.search_ranking import SearchableProduct, rank_products

from catalog.models import (
    Category,
    Product,
    ProductOption,
    OptionValue,
    Variant,
    VariantOptionValue,
    Location,
    InventoryLevel,
    StockMovement,
)
from catalog.schemas import (
    CategoryCreate,
    CategoryResponse,
    ProductCreate,
    ProductUpdate,
    ProductOptionCreate,
    CandidateVariant,
    CandidateGridResponse,
    VariantCreate,
    LocationCreate,
    ReservationAllocation,
    ReservationResponse,
    ReleaseStockResponse,
    TransferStockResponse,
    LocationAvailability,
    VariantAvailabilityResponse,
    CheckAvailabilityResponse,
    DescribeCatalogResponse,
    RowValidationItem,
    ValidationReport,
    GenerateFindabilityResponse,
    SemanticSearchResponse,
    SemanticMatchItem,
)

logger = logging.getLogger("catalog.service")


class ProductService:
    """Single write authority for products, options, variants, locations, and inventory."""

    def __init__(self, db: Session):
        self.db = db

    # -----------------------------------------------------------------------
    # Categories
    # -----------------------------------------------------------------------

    def upsert_category(self, tenant_id: UUID, data: CategoryCreate) -> Category:
        category = (
            self.db.query(Category)
            .filter(Category.tenant_id == tenant_id, Category.key == data.key)
            .first()
        )
        if category:
            category.label = data.label
            category.parent_key = data.parent_key
        else:
            category = Category(
                tenant_id=tenant_id,
                key=data.key,
                label=data.label,
                parent_key=data.parent_key,
            )
            self.db.add(category)
        self.db.commit()
        self.db.refresh(category)
        return category

    def list_categories(self, tenant_id: UUID) -> List[Category]:
        return (
            self.db.query(Category)
            .filter(Category.tenant_id == tenant_id)
            .order_by(Category.key.asc())
            .all()
        )

    # -----------------------------------------------------------------------
    # Products
    # -----------------------------------------------------------------------

    def upsert_product(
        self,
        tenant_id: UUID,
        data: ProductCreate | ProductUpdate,
        user_id: str,
        product_id: Optional[UUID] = None,
    ) -> Product:
        # Validate category if provided
        if getattr(data, "category", None) is not None:
            cat_exists = (
                self.db.query(Category)
                .filter(
                    Category.tenant_id == tenant_id,
                    Category.key == data.category,
                )
                .first()
            )
            if not cat_exists:
                raise ValueError(
                    f"Category '{data.category}' does not exist in tenant vocabulary"
                )

        if product_id:
            product = (
                self.db.query(Product)
                .filter(Product.tenant_id == tenant_id, Product.id == product_id)
                .first()
            )
            if not product:
                raise ValueError(f"Product with id '{product_id}' not found")

            update_data = data.model_dump(exclude_unset=True, exclude={"options"})
            for field, val in update_data.items():
                if hasattr(product, field):
                    setattr(product, field, val)

            options_data = getattr(data, "options", None)
            if options_data is not None:
                self.set_options(tenant_id, product.id, options_data)

            product.version += 1
        else:
            product_dict = data.model_dump(exclude={"options"})
            options_data = getattr(data, "options", None)
            product = Product(
                tenant_id=tenant_id,
                acl=[f"tenant:{tenant_id}", f"user:{user_id}"],
                **product_dict,
            )
            self.db.add(product)
            self.db.flush()

            if options_data:
                self.set_options(tenant_id, product.id, options_data)

        self.db.commit()
        return self.get_product(tenant_id, product.id)

    def get_product(self, tenant_id: UUID, product_id: UUID) -> Product:
        product = (
            self.db.query(Product)
            .options(
                selectinload(Product.options).selectinload(ProductOption.values),
                selectinload(Product.variants).selectinload(Variant.option_values),
            )
            .filter(Product.tenant_id == tenant_id, Product.id == product_id)
            .first()
        )
        if not product:
            raise ValueError(f"Product '{product_id}' not found")
        return product

    def list_products(
        self,
        tenant_id: UUID,
        status: Optional[str] = None,
        category: Optional[str] = None,
        subcategory: Optional[str] = None,
        type: Optional[str] = None,
        min_price: Optional[Decimal] = None,
        max_price: Optional[Decimal] = None,
        keywords: Optional[str] = None,
        target_industry: Optional[str] = None,
        in_stock: Optional[bool] = None,
        location_id: Optional[UUID] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Product]:
        query = (
            self.db.query(Product)
            .options(
                selectinload(Product.options).selectinload(ProductOption.values),
                selectinload(Product.variants).selectinload(Variant.option_values),
            )
            .filter(Product.tenant_id == tenant_id)
        )

        if status:
            query = query.filter(Product.status == status)

        if category:
            query = query.filter(Product.category == category)

        if subcategory:
            query = query.filter(Product.subcategory == subcategory)

        if type:
            query = query.filter(Product.type == type)

        if target_industry:
            query = query.filter(
                func.array_to_string(Product.target_industries, " ").ilike(
                    f"%{target_industry.strip()}%"
                )
            )

        if keywords:
            raw_kw = keywords.strip()
            kw_pattern = f"%{raw_kw}%"
            full_phrase_conds = [
                Product.name.ilike(kw_pattern),
                Product.description.ilike(kw_pattern),
                Product.ideal_customer_profile.ilike(kw_pattern),
                Product.value_proposition.ilike(kw_pattern),
                func.array_to_string(Product.keywords, " ").ilike(kw_pattern),
                func.array_to_string(Product.use_cases, " ").ilike(kw_pattern),
                func.array_to_string(Product.target_industries, " ").ilike(kw_pattern),
            ]
            stop_words = {
                "a", "an", "the", "for", "in", "on", "at", "to", "of", "and",
                "or", "is", "it", "my", "your", "with", "something", "some",
                "any", "want", "need", "looking", "about", "from", "by",
            }
            tokens = [
                w for w in re.findall(r"\w+", raw_kw.lower())
                if w not in stop_words and len(w) > 1
            ]
            token_conds = []
            for token in tokens:
                tp = f"%{token}%"
                token_conds.append(
                    or_(
                        Product.name.ilike(tp),
                        Product.description.ilike(tp),
                        Product.ideal_customer_profile.ilike(tp),
                        Product.value_proposition.ilike(tp),
                        func.array_to_string(Product.keywords, " ").ilike(tp),
                        func.array_to_string(Product.use_cases, " ").ilike(tp),
                        func.array_to_string(Product.target_industries, " ").ilike(tp),
                    )
                )

            if token_conds:
                query = query.filter(or_(*full_phrase_conds, *token_conds))
            else:
                query = query.filter(or_(*full_phrase_conds))

        if min_price is not None or max_price is not None:
            query = query.join(Variant, Variant.product_id == Product.id)
            if min_price is not None:
                query = query.filter(Variant.price >= min_price)
            if max_price is not None:
                query = query.filter(Variant.price <= max_price)
            query = query.distinct()

        if in_stock is True:
            if location_id:
                query = (
                    query.join(Variant, Variant.product_id == Product.id)
                    .join(InventoryLevel, InventoryLevel.variant_id == Variant.id)
                    .join(Location, Location.id == InventoryLevel.location_id)
                    .filter(
                        Location.id == location_id,
                        Location.sellable == True,
                        (InventoryLevel.qty_on_hand - InventoryLevel.qty_reserved) > 0,
                    )
                )
            else:
                subq = (
                    self.db.query(InventoryLevel.variant_id)
                    .join(Location, Location.id == InventoryLevel.location_id)
                    .filter(
                        InventoryLevel.tenant_id == tenant_id,
                        Location.sellable == True,
                        (InventoryLevel.qty_on_hand - InventoryLevel.qty_reserved) > 0,
                    )
                    .subquery()
                )
                query = query.join(Variant, Variant.product_id == Product.id).filter(
                    Variant.id.in_(self.db.query(subq.c.variant_id))
                )
            query = query.distinct()

        return query.order_by(Product.created_at.desc()).offset(offset).limit(limit).all()

    def delete_product(self, tenant_id: UUID, product_id: UUID) -> Product:
        """Soft delete product by setting status to RETIRED and retire variants strictly within tenant."""
        product = (
            self.db.query(Product)
            .filter(Product.tenant_id == tenant_id, Product.id == product_id)
            .first()
        )
        if not product:
            raise ValueError(f"Product '{product_id}' not found")
        product.status = "RETIRED"
        # Cascade RETIRED status to all variants of this product
        self.db.query(Variant).filter(
            Variant.tenant_id == tenant_id,
            Variant.product_id == product.id,
        ).update({"status": "RETIRED"}, synchronize_session=False)
        self.db.commit()
        self.db.refresh(product)
        return product

    def hard_delete_product(self, tenant_id: UUID, product_id: UUID) -> bool:
        """Permanently hard-delete product and all cascaded child records strictly within tenant."""
        product = (
            self.db.query(Product)
            .filter(Product.tenant_id == tenant_id, Product.id == product_id)
            .first()
        )
        if not product:
            raise ValueError(f"Product '{product_id}' not found")
        self.db.delete(product)
        self.db.commit()
        return True

    # -----------------------------------------------------------------------
    # Options & Candidate Grid Generation
    # -----------------------------------------------------------------------

    def set_options(
        self,
        tenant_id: UUID,
        product_id: UUID,
        options: List[ProductOptionCreate],
    ) -> List[ProductOption]:
        product = (
            self.db.query(Product)
            .filter(Product.tenant_id == tenant_id, Product.id == product_id)
            .first()
        )
        if not product:
            raise ValueError(f"Product '{product_id}' not found")

        # Remove existing options (cascades to OptionValues and VariantOptionValues)
        self.db.query(ProductOption).filter(
            ProductOption.tenant_id == tenant_id,
            ProductOption.product_id == product_id,
        ).delete(synchronize_session=False)

        created_options = []
        for pos, opt_in in enumerate(options):
            opt = ProductOption(
                product_id=product_id,
                tenant_id=tenant_id,
                name=opt_in.name,
                position=opt_in.position if opt_in.position else pos,
            )
            self.db.add(opt)
            self.db.flush()

            for val_pos, val_in in enumerate(opt_in.values):
                val = OptionValue(
                    option_id=opt.id,
                    tenant_id=tenant_id,
                    value=val_in.value,
                    position=val_in.position if val_in.position else val_pos,
                )
                self.db.add(val)
            created_options.append(opt)

        self.db.commit()
        return (
            self.db.query(ProductOption)
            .options(joinedload(ProductOption.values))
            .filter(
                ProductOption.tenant_id == tenant_id,
                ProductOption.product_id == product_id,
            )
            .order_by(ProductOption.position.asc())
            .all()
        )

    def generate_variant_grid(
        self, tenant_id: UUID, product_id: UUID
    ) -> CandidateGridResponse:
        """Compute Cartesian product of options as unpersisted candidates."""
        product = self.get_product(tenant_id, product_id)
        if not product.options:
            return CandidateGridResponse(product_id=product_id, candidates=[])

        # Extract values for each option axis in order
        options_values = [
            [(opt.name, val) for val in sorted(opt.values, key=lambda v: v.position)]
            for opt in sorted(product.options, key=lambda o: o.position)
            if opt.values
        ]

        if not options_values:
            return CandidateGridResponse(product_id=product_id, candidates=[])

        candidates = []
        base_sku_prefix = product.name.upper().replace(" ", "-")[:10]

        for combination in itertools.product(*options_values):
            option_value_ids = [val.id for _, val in combination]
            option_summary = {opt_name: val.value for opt_name, val in combination}
            sku_suffix = "-".join(val.value.upper().replace(" ", "") for _, val in combination)
            suggested_sku = f"{base_sku_prefix}-{sku_suffix}"

            candidates.append(
                CandidateVariant(
                    option_value_ids=option_value_ids,
                    option_summary=option_summary,
                    suggested_sku=suggested_sku,
                )
            )

        return CandidateGridResponse(product_id=product_id, candidates=candidates)

    def upsert_variants(
        self,
        tenant_id: UUID,
        product_id: UUID,
        variants: List[VariantCreate],
    ) -> List[Variant]:
        """Persists only enabled combinations; validates SKU uniqueness per tenant, price >= 0."""
        product = (
            self.db.query(Product)
            .filter(Product.tenant_id == tenant_id, Product.id == product_id)
            .first()
        )
        if not product:
            raise ValueError(f"Product '{product_id}' not found")

        batch_skus = set()
        persisted_variants = []
        for v_in in variants:
            if v_in.price < 0:
                raise ValueError(f"Variant price must be non-negative (got {v_in.price})")

            if v_in.sku in batch_skus:
                raise ValueError(f"Duplicate SKU '{v_in.sku}' in batch")
            batch_skus.add(v_in.sku)

            # Check SKU uniqueness per tenant
            existing = (
                self.db.query(Variant)
                .filter(Variant.tenant_id == tenant_id, Variant.sku == v_in.sku)
                .first()
            )
            if existing and existing.product_id != product_id:
                raise ValueError(
                    f"SKU '{v_in.sku}' already exists for a different product in this tenant"
                )

            # Validate that option_value_ids belong to this product and tenant
            if v_in.option_value_ids:
                valid_count = (
                    self.db.query(OptionValue)
                    .join(ProductOption, ProductOption.id == OptionValue.option_id)
                    .filter(
                        ProductOption.tenant_id == tenant_id,
                        ProductOption.product_id == product_id,
                        OptionValue.id.in_(v_in.option_value_ids),
                    )
                    .count()
                )
                if valid_count != len(v_in.option_value_ids):
                    raise ValueError(
                        "One or more option_value_ids do not belong to this product or tenant"
                    )

            if existing:
                variant = existing
                variant.price = v_in.price
                variant.barcode = v_in.barcode
                variant.weight = v_in.weight
                variant.currency = v_in.currency
                variant.status = v_in.status
            else:
                variant = Variant(
                    product_id=product_id,
                    tenant_id=tenant_id,
                    sku=v_in.sku,
                    barcode=v_in.barcode,
                    price=v_in.price,
                    currency=v_in.currency,
                    weight=v_in.weight,
                    status=v_in.status,
                )
                self.db.add(variant)
                self.db.flush()

            # Associate option values
            self.db.query(VariantOptionValue).filter(
                VariantOptionValue.tenant_id == tenant_id,
                VariantOptionValue.variant_id == variant.id,
            ).delete(synchronize_session=False)

            for opt_val_id in v_in.option_value_ids:
                vov = VariantOptionValue(
                    variant_id=variant.id,
                    option_value_id=opt_val_id,
                    tenant_id=tenant_id,
                )
                self.db.add(vov)

            persisted_variants.append(variant)

        self.db.commit()
        return (
            self.db.query(Variant)
            .options(joinedload(Variant.option_values))
            .filter(
                Variant.tenant_id == tenant_id,
                Variant.product_id == product_id,
            )
            .all()
        )

    def get_variant(self, tenant_id: UUID, sku: str) -> Variant:
        variant = (
            self.db.query(Variant)
            .options(
                joinedload(Variant.product),
                joinedload(Variant.option_values),
            )
            .filter(Variant.tenant_id == tenant_id, Variant.sku == sku)
            .first()
        )
        if not variant:
            raise ValueError(f"Variant with SKU '{sku}' not found")
        return variant

    # -----------------------------------------------------------------------
    # Locations
    # -----------------------------------------------------------------------

    def upsert_location(
        self,
        tenant_id: UUID,
        data: LocationCreate,
        location_id: Optional[UUID] = None,
    ) -> Location:
        if location_id:
            loc = (
                self.db.query(Location)
                .filter(Location.tenant_id == tenant_id, Location.id == location_id)
                .first()
            )
            if not loc:
                raise ValueError(f"Location '{location_id}' not found")
            for k, v in data.model_dump().items():
                setattr(loc, k, v)
        else:
            loc = Location(tenant_id=tenant_id, **data.model_dump())
            self.db.add(loc)

        self.db.commit()
        self.db.refresh(loc)
        return loc

    def list_locations(self, tenant_id: UUID) -> List[Location]:
        return (
            self.db.query(Location)
            .filter(Location.tenant_id == tenant_id)
            .order_by(Location.priority.asc(), Location.name.asc())
            .all()
        )

    def delete_location(self, tenant_id: UUID, location_id: UUID) -> bool:
        loc = (
            self.db.query(Location)
            .filter(Location.tenant_id == tenant_id, Location.id == location_id)
            .first()
        )
        if not loc:
            raise ValueError(f"Location '{location_id}' not found")

        active_inv = (
            self.db.query(InventoryLevel)
            .filter(
                InventoryLevel.tenant_id == tenant_id,
                InventoryLevel.location_id == location_id,
                (InventoryLevel.qty_on_hand > 0) | (InventoryLevel.qty_reserved > 0),
            )
            .first()
        )
        if active_inv:
            raise ValueError(
                f"Cannot delete location '{loc.name}' because it contains active inventory (on-hand or reserved). "
                "Please adjust or transfer the stock to 0 before deleting."
            )

        self.db.query(InventoryLevel).filter(
            InventoryLevel.tenant_id == tenant_id,
            InventoryLevel.location_id == location_id,
        ).delete(synchronize_session=False)

        self.db.delete(loc)
        self.db.commit()
        return True

    # -----------------------------------------------------------------------
    # Inventory Ledger & Operations
    # -----------------------------------------------------------------------

    def _get_or_create_inventory_level(
        self,
        tenant_id: UUID,
        variant_id: UUID,
        location_id: UUID,
        for_update: bool = False,
    ) -> InventoryLevel:
        query = self.db.query(InventoryLevel).filter(
            InventoryLevel.tenant_id == tenant_id,
            InventoryLevel.variant_id == variant_id,
            InventoryLevel.location_id == location_id,
        )
        if for_update:
            query = query.with_for_update()

        inv = query.first()
        if not inv:
            try:
                with self.db.begin_nested():
                    inv = InventoryLevel(
                        variant_id=variant_id,
                        location_id=location_id,
                        tenant_id=tenant_id,
                        qty_on_hand=0,
                        qty_reserved=0,
                    )
                    self.db.add(inv)
                    self.db.flush()
            except Exception:
                # Concurrent insert collision handled gracefully
                pass

            query = self.db.query(InventoryLevel).filter(
                InventoryLevel.tenant_id == tenant_id,
                InventoryLevel.variant_id == variant_id,
                InventoryLevel.location_id == location_id,
            )
            if for_update:
                query = query.with_for_update()
            inv = query.one()
        return inv

    def set_stock(
        self,
        tenant_id: UUID,
        variant_id: UUID,
        location_id: UUID,
        qty: int,
        reason: str = "RESTOCK",
        ref_id: Optional[UUID] = None,
        note: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> InventoryLevel:
        if qty < 0:
            raise ValueError(f"qty cannot be negative (got {qty})")

        # Validate variant belongs to tenant
        variant = (
            self.db.query(Variant)
            .filter(Variant.tenant_id == tenant_id, Variant.id == variant_id)
            .first()
        )
        if not variant:
            raise ValueError(f"Variant '{variant_id}' not found")

        # Validate location belongs to tenant
        location = (
            self.db.query(Location)
            .filter(Location.tenant_id == tenant_id, Location.id == location_id)
            .first()
        )
        if not location:
            raise ValueError(f"Location '{location_id}' not found")

        inv = self._get_or_create_inventory_level(
            tenant_id, variant_id, location_id, for_update=True
        )

        if qty < inv.qty_reserved:
            raise ValueError(
                f"Cannot set qty_on_hand ({qty}) less than reserved ({inv.qty_reserved})"
            )

        delta = qty - inv.qty_on_hand

        if delta != 0:
            movement = StockMovement(
                inv_level_id=inv.id,
                tenant_id=tenant_id,
                delta=delta,
                reason=reason,
                ref_id=ref_id,
                note=note or f"Stock set to {qty} (delta {delta:+d})",
                created_by=created_by,
            )
            self.db.add(movement)
            inv.qty_on_hand = qty

        self.db.commit()
        self.db.refresh(inv)
        return inv

    def batch_set_stock(
        self,
        tenant_id: UUID,
        items: List[Any],
        created_by: Optional[str] = None,
    ) -> List[InventoryLevel]:
        """Atomically set stock levels for multiple (variant, location) pairs in a single database transaction."""
        if not items:
            return []

        # Extract IDs
        variant_ids = {getattr(it, "variant_id", None) or it["variant_id"] for it in items}
        location_ids = {getattr(it, "location_id", None) or it["location_id"] for it in items}

        # Validate variant_ids belong to tenant
        db_variants = set(
            v[0]
            for v in self.db.query(Variant.id)
            .filter(Variant.tenant_id == tenant_id, Variant.id.in_(variant_ids))
            .all()
        )
        missing_variants = variant_ids - db_variants
        if missing_variants:
            raise ValueError(f"One or more variants not found in tenant: {missing_variants}")

        # Validate location_ids belong to tenant
        db_locations = set(
            l[0]
            for l in self.db.query(Location.id)
            .filter(Location.tenant_id == tenant_id, Location.id.in_(location_ids))
            .all()
        )
        missing_locations = location_ids - db_locations
        if missing_locations:
            raise ValueError(f"One or more locations not found in tenant: {missing_locations}")

        updated_levels = []
        for item in items:
            v_id = getattr(item, "variant_id", None) or item["variant_id"]
            l_id = getattr(item, "location_id", None) or item["location_id"]
            qty = getattr(item, "qty", None) if hasattr(item, "qty") else item["qty"]
            reason = getattr(item, "reason", "RESTOCK") if hasattr(item, "reason") else item.get("reason", "RESTOCK")
            ref_id = getattr(item, "ref_id", None) if hasattr(item, "ref_id") else item.get("ref_id")
            note = getattr(item, "note", None) if hasattr(item, "note") else item.get("note")

            if qty < 0:
                raise ValueError(f"qty cannot be negative (got {qty})")

            inv = self._get_or_create_inventory_level(
                tenant_id, v_id, l_id, for_update=True
            )
            if qty < inv.qty_reserved:
                raise ValueError(
                    f"Cannot set qty_on_hand ({qty}) less than reserved ({inv.qty_reserved})"
                )

            delta = qty - inv.qty_on_hand
            if delta != 0:
                movement = StockMovement(
                    inv_level_id=inv.id,
                    tenant_id=tenant_id,
                    delta=delta,
                    reason=reason,
                    ref_id=ref_id,
                    note=note or f"Stock set to {qty} (delta {delta:+d})",
                    created_by=created_by,
                )
                self.db.add(movement)
                inv.qty_on_hand = qty

            updated_levels.append(inv)

        self.db.commit()
        for inv in updated_levels:
            self.db.refresh(inv)
        return updated_levels

    def adjust_stock(
        self,
        tenant_id: UUID,
        variant_id: UUID,
        location_id: UUID,
        delta: int,
        reason: str = "ADJUST",
        ref_id: Optional[UUID] = None,
        note: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> InventoryLevel:
        # Validate variant belongs to tenant
        variant = (
            self.db.query(Variant)
            .filter(Variant.tenant_id == tenant_id, Variant.id == variant_id)
            .first()
        )
        if not variant:
            raise ValueError(f"Variant '{variant_id}' not found")

        # Validate location belongs to tenant
        location = (
            self.db.query(Location)
            .filter(Location.tenant_id == tenant_id, Location.id == location_id)
            .first()
        )
        if not location:
            raise ValueError(f"Location '{location_id}' not found")

        inv = self._get_or_create_inventory_level(
            tenant_id, variant_id, location_id, for_update=True
        )
        new_qty = inv.qty_on_hand + delta
        if new_qty < 0:
            raise ValueError(
                f"Adjustment delta {delta:+d} would result in negative qty_on_hand ({new_qty})"
            )
        if new_qty < inv.qty_reserved:
            raise ValueError(
                f"Adjustment delta {delta:+d} would result in qty_on_hand ({new_qty}) less than reserved ({inv.qty_reserved})"
            )

        inv.qty_on_hand = new_qty
        movement = StockMovement(
            inv_level_id=inv.id,
            tenant_id=tenant_id,
            delta=delta,
            reason=reason,
            ref_id=ref_id,
            note=note or f"Stock adjusted by {delta:+d} to {new_qty}",
            created_by=created_by,
        )
        self.db.add(movement)
        self.db.commit()
        self.db.refresh(inv)
        return inv

    def allocate(
        self,
        tenant_id: UUID,
        variant_id: UUID,
        qty: int,
    ) -> List[ReservationAllocation]:
        """Strategy function for multi-location inventory allocation (Section 5).

        Picks the sellable location(s) with qty_available >= qty, ordered by priority ASC.
        If none can fully cover, splits across sellable locations in priority order.
        Raises ValueError if insufficient sellable stock.
        """
        if qty <= 0:
            raise ValueError("Allocation quantity must be strictly greater than 0")

        loc_levels = (
            self.db.query(Location, InventoryLevel)
            .outerjoin(
                InventoryLevel,
                (InventoryLevel.location_id == Location.id)
                & (InventoryLevel.variant_id == variant_id)
                & (InventoryLevel.tenant_id == tenant_id),
            )
            .filter(Location.tenant_id == tenant_id, Location.sellable == True)
            .order_by(Location.priority.asc(), Location.id.asc())
            .all()
        )

        if not loc_levels:
            raise ValueError("No sellable locations configured for this tenant")

        # Check if any single location can fully cover
        for loc, inv in loc_levels:
            avail = max(0, (inv.qty_on_hand - inv.qty_reserved)) if inv else 0
            if avail >= qty:
                return [
                    ReservationAllocation(
                        location_id=loc.id,
                        location_name=loc.name,
                        qty=qty,
                    )
                ]

        # Split across locations in priority order
        total_available = sum(
            max(0, (inv.qty_on_hand - inv.qty_reserved)) if inv else 0
            for _, inv in loc_levels
        )
        if total_available < qty:
            raise ValueError(
                f"Insufficient sellable stock: total available {total_available}, requested {qty}"
            )

        allocations: List[ReservationAllocation] = []
        remaining = qty
        for loc, inv in loc_levels:
            if remaining <= 0:
                break
            avail = max(0, (inv.qty_on_hand - inv.qty_reserved)) if inv else 0
            if avail <= 0:
                continue
            take_qty = min(avail, remaining)
            allocations.append(
                ReservationAllocation(
                    location_id=loc.id,
                    location_name=loc.name,
                    qty=take_qty,
                )
            )
            remaining -= take_qty

        return allocations

    def reserve(
        self,
        tenant_id: UUID,
        sku: str,
        qty: int,
        location_id: Optional[UUID] = None,
        created_by: Optional[str] = None,
    ) -> ReservationResponse:
        """Reserve stock using priority allocation & row-level locking to prevent overselling."""
        if qty <= 0:
            raise ValueError("Reservation quantity must be strictly greater than 0")

        variant = self.get_variant(tenant_id, sku)
        reservation_id = uuid4()

        if location_id is not None:
            # Single explicit location reservation
            loc = (
                self.db.query(Location)
                .filter(Location.tenant_id == tenant_id, Location.id == location_id)
                .first()
            )
            if not loc:
                raise ValueError(f"Location '{location_id}' not found")
            if not loc.sellable:
                raise ValueError(f"Location '{loc.name}' is marked as not sellable")

            inv = self._get_or_create_inventory_level(
                tenant_id, variant.id, location_id, for_update=True
            )
            available = inv.qty_on_hand - inv.qty_reserved
            if available < qty:
                raise ValueError(
                    f"Insufficient stock at location '{loc.name}': available {available}, requested {qty}"
                )

            inv.qty_reserved += qty
            movement = StockMovement(
                inv_level_id=inv.id,
                tenant_id=tenant_id,
                delta=qty,
                reason="RESERVE",
                ref_id=reservation_id,
                note=f"Reserved {qty} units for SKU {sku}",
                created_by=created_by,
            )
            self.db.add(movement)
            self.db.commit()
            return ReservationResponse(
                reservation_id=reservation_id,
                sku=sku,
                requested_qty=qty,
                allocated_qty=qty,
                allocations=[
                    ReservationAllocation(
                        location_id=loc.id,
                        location_name=loc.name,
                        qty=qty,
                    )
                ],
            )
        else:
            # Row-lock existing inventory levels for sellable locations in priority order
            sellable_invs = (
                self.db.query(InventoryLevel)
                .join(Location, Location.id == InventoryLevel.location_id)
                .filter(
                    InventoryLevel.tenant_id == tenant_id,
                    InventoryLevel.variant_id == variant.id,
                    Location.sellable == True,
                )
                .order_by(Location.priority.asc(), Location.id.asc())
                .with_for_update()
                .all()
            )

            allocations = self.allocate(tenant_id, variant.id, qty)

            inv_by_loc = {inv.location_id: inv for inv in sellable_invs}
            for alloc in allocations:
                inv = inv_by_loc.get(alloc.location_id)
                if not inv:
                    inv = self._get_or_create_inventory_level(
                        tenant_id, variant.id, alloc.location_id, for_update=True
                    )
                avail = inv.qty_on_hand - inv.qty_reserved
                if avail < alloc.qty:
                    self.db.rollback()
                    raise ValueError(
                        f"Stock changed concurrently at location '{alloc.location_name}': available {avail}, needed {alloc.qty}"
                    )
                inv.qty_reserved += alloc.qty
                movement = StockMovement(
                    inv_level_id=inv.id,
                    tenant_id=tenant_id,
                    delta=alloc.qty,
                    reason="RESERVE",
                    ref_id=reservation_id,
                    note=f"Reserved {alloc.qty} units for SKU {sku}",
                    created_by=created_by,
                )
                self.db.add(movement)

            self.db.commit()
            return ReservationResponse(
                reservation_id=reservation_id,
                sku=sku,
                requested_qty=qty,
                allocated_qty=qty,
                allocations=allocations,
            )

    def release(
        self,
        tenant_id: UUID,
        reservation_id: UUID,
        created_by: Optional[str] = None,
    ) -> ReleaseStockResponse:
        """Release a previously made reservation and decrement qty_reserved."""
        # Prevent double-release
        already_released = (
            self.db.query(StockMovement)
            .filter(
                StockMovement.tenant_id == tenant_id,
                StockMovement.ref_id == reservation_id,
                StockMovement.reason == "RELEASE",
            )
            .first()
        )
        if already_released:
            raise ValueError(
                f"Reservation '{reservation_id}' has already been released"
            )

        movements = (
            self.db.query(StockMovement)
            .filter(
                StockMovement.tenant_id == tenant_id,
                StockMovement.ref_id == reservation_id,
                StockMovement.reason == "RESERVE",
            )
            .all()
        )
        if not movements:
            raise ValueError(
                f"No active reservation found with ID '{reservation_id}'"
            )

        total_released = 0
        for m in movements:
            inv = (
                self.db.query(InventoryLevel)
                .filter(
                    InventoryLevel.id == m.inv_level_id,
                    InventoryLevel.tenant_id == tenant_id,
                )
                .with_for_update()
                .one()
            )
            release_qty = min(m.delta, inv.qty_reserved)
            inv.qty_reserved -= release_qty
            total_released += release_qty

            rel_movement = StockMovement(
                inv_level_id=inv.id,
                tenant_id=tenant_id,
                delta=release_qty,
                reason="RELEASE",
                ref_id=reservation_id,
                note=f"Released {release_qty} units from reservation {reservation_id}",
                created_by=created_by,
            )
            self.db.add(rel_movement)

        self.db.commit()
        return ReleaseStockResponse(
            reservation_id=reservation_id,
            released_qty=total_released,
            movements_count=len(movements),
        )

    def transfer(
        self,
        tenant_id: UUID,
        sku: str,
        from_location_id: UUID,
        to_location_id: UUID,
        qty: int,
        note: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> TransferStockResponse:
        """Inter-location inventory transfer with row locking and paired ledger movements."""
        if qty <= 0:
            raise ValueError("Transfer quantity must be greater than 0")
        if from_location_id == to_location_id:
            raise ValueError("Source and destination locations must be distinct")

        # Validate variant belongs to tenant
        variant = self.get_variant(tenant_id, sku)

        # Validate both locations belong to tenant
        from_loc = (
            self.db.query(Location)
            .filter(Location.tenant_id == tenant_id, Location.id == from_location_id)
            .first()
        )
        if not from_loc:
            raise ValueError(f"Source location '{from_location_id}' not found")

        to_loc = (
            self.db.query(Location)
            .filter(Location.tenant_id == tenant_id, Location.id == to_location_id)
            .first()
        )
        if not to_loc:
            raise ValueError(f"Destination location '{to_location_id}' not found")

        # Lock both inventory rows in deterministic UUID order to avoid deadlocks
        ordered_ids = sorted([from_location_id, to_location_id])
        for loc_id in ordered_ids:
            self._get_or_create_inventory_level(
                tenant_id, variant.id, loc_id, for_update=True
            )

        from_inv = self._get_or_create_inventory_level(
            tenant_id, variant.id, from_location_id, for_update=True
        )
        to_inv = self._get_or_create_inventory_level(
            tenant_id, variant.id, to_location_id, for_update=True
        )

        from_avail = from_inv.qty_on_hand - from_inv.qty_reserved
        if from_avail < qty:
            raise ValueError(
                f"Insufficient available stock at source location: available {from_avail}, requested {qty}"
            )

        transfer_ref = uuid4()
        from_inv.qty_on_hand -= qty
        out_movement = StockMovement(
            inv_level_id=from_inv.id,
            tenant_id=tenant_id,
            delta=-qty,
            reason="TRANSFER_OUT",
            ref_id=transfer_ref,
            note=note or f"Transfer out {qty} units of SKU {sku} to location {to_location_id}",
            created_by=created_by,
        )
        self.db.add(out_movement)

        to_inv.qty_on_hand += qty
        in_movement = StockMovement(
            inv_level_id=to_inv.id,
            tenant_id=tenant_id,
            delta=qty,
            reason="TRANSFER_IN",
            ref_id=transfer_ref,
            note=note or f"Transfer in {qty} units of SKU {sku} from location {from_location_id}",
            created_by=created_by,
        )
        self.db.add(in_movement)

        self.db.commit()
        return TransferStockResponse(
            ref_id=transfer_ref,
            sku=sku,
            from_location_id=from_location_id,
            to_location_id=to_location_id,
            qty=qty,
        )

    # -----------------------------------------------------------------------
    # Availability & AI Access Tools
    # -----------------------------------------------------------------------

    def availability(
        self, tenant_id: UUID, sku: str
    ) -> VariantAvailabilityResponse:
        """Query v_variant_availability view and provide per-location availability breakdown."""
        variant = self.get_variant(tenant_id, sku)

        # Total available from view
        row = self.db.execute(
            text(
                "SELECT qty_available FROM catalog.v_variant_availability "
                "WHERE tenant_id = :tenant_id AND variant_id = :variant_id"
            ),
            {"tenant_id": tenant_id, "variant_id": variant.id},
        ).fetchone()

        total_available = int(row[0]) if row and row[0] is not None else 0

        # Per-location breakdown
        levels = (
            self.db.query(InventoryLevel, Location)
            .join(Location, Location.id == InventoryLevel.location_id)
            .filter(
                InventoryLevel.tenant_id == tenant_id,
                InventoryLevel.variant_id == variant.id,
            )
            .order_by(Location.priority.asc(), Location.name.asc())
            .all()
        )

        by_location: List[LocationAvailability] = []
        for inv, loc in levels:
            by_location.append(
                LocationAvailability(
                    location_id=loc.id,
                    location_name=loc.name,
                    sellable=loc.sellable,
                    priority=loc.priority,
                    qty_on_hand=inv.qty_on_hand,
                    qty_reserved=inv.qty_reserved,
                    qty_available=max(0, inv.qty_on_hand - inv.qty_reserved)
                    if loc.sellable
                    else 0,
                )
            )

        return VariantAvailabilityResponse(
            variant_id=variant.id,
            sku=sku,
            total_available=total_available,
            by_location=by_location,
        )

    def batch_availability(
        self,
        tenant_id: UUID,
        skus: Optional[List[str]] = None,
    ) -> Dict[str, VariantAvailabilityResponse]:
        """Fetch total sellable availability and per-location breakdown for multiple or all SKUs in 1-2 queries."""
        var_query = self.db.query(Variant.id, Variant.sku).filter(Variant.tenant_id == tenant_id)
        if skus:
            clean_skus = [s.strip() for s in skus if s and s.strip()]
            if not clean_skus:
                return {}
            var_query = var_query.filter(Variant.sku.in_(clean_skus))

        variants = var_query.all()
        if not variants:
            return {}

        variant_map = {v[0]: v[1] for v in variants}
        variant_ids = list(variant_map.keys())

        # Query all inventory levels joined with location for these variants
        levels = (
            self.db.query(InventoryLevel, Location)
            .join(Location, Location.id == InventoryLevel.location_id)
            .filter(
                InventoryLevel.tenant_id == tenant_id,
                InventoryLevel.variant_id.in_(variant_ids),
            )
            .order_by(Location.priority.asc(), Location.name.asc())
            .all()
        )

        # Group levels by variant_id
        inv_by_variant: Dict[UUID, List[Tuple[InventoryLevel, Location]]] = {
            v_id: [] for v_id in variant_ids
        }
        for inv, loc in levels:
            if inv.variant_id in inv_by_variant:
                inv_by_variant[inv.variant_id].append((inv, loc))

        result: Dict[str, VariantAvailabilityResponse] = {}
        for v_id, sku in variant_map.items():
            loc_list = inv_by_variant.get(v_id, [])
            by_loc: List[LocationAvailability] = []
            total_avail = 0

            for inv, loc in loc_list:
                loc_avail = (
                    max(0, inv.qty_on_hand - inv.qty_reserved) if loc.sellable else 0
                )
                if loc.sellable:
                    total_avail += loc_avail

                by_loc.append(
                    LocationAvailability(
                        location_id=loc.id,
                        location_name=loc.name,
                        sellable=loc.sellable,
                        priority=loc.priority,
                        qty_on_hand=inv.qty_on_hand,
                        qty_reserved=inv.qty_reserved,
                        qty_available=loc_avail,
                    )
                )

            result[sku] = VariantAvailabilityResponse(
                variant_id=v_id,
                sku=sku,
                total_available=total_avail,
                by_location=by_loc,
            )

        return result

    def check_availability(
        self,
        tenant_id: UUID,
        sku: str,
        qty: int = 1,
        location_id: Optional[UUID] = None,
    ) -> CheckAvailabilityResponse:
        """Check if requested quantity can be fulfilled (total or specific location)."""
        avail_resp = self.availability(tenant_id, sku)
        if location_id is not None:
            loc_match = next(
                (l for l in avail_resp.by_location if l.location_id == location_id),
                None,
            )
            can_fulfill = (
                loc_match is not None
                and loc_match.sellable
                and loc_match.qty_available >= qty
            )
        else:
            can_fulfill = avail_resp.total_available >= qty

        return CheckAvailabilityResponse(
            can_fulfill=can_fulfill,
            sku=sku,
            requested_qty=qty,
            total_available=avail_resp.total_available,
            location_id=location_id,
            by_location=avail_resp.by_location,
        )

    def describe_catalog(self, tenant_id: UUID) -> DescribeCatalogResponse:
        """Describe tenant catalog vocabulary, filterable fields, and option types for AI tools."""
        categories = self.list_categories(tenant_id)
        cat_responses = [CategoryResponse.model_validate(c) for c in categories]
        filterable_fields = [
            "category",
            "subcategory",
            "type",
            "status",
            "min_price",
            "max_price",
            "keywords",
            "target_industry",
            "in_stock",
            "location",
        ]
        option_names = [
            row[0]
            for row in self.db.query(ProductOption.name)
            .filter(ProductOption.tenant_id == tenant_id)
            .distinct()
            .all()
        ]
        return DescribeCatalogResponse(
            categories=cat_responses,
            filterable_fields=filterable_fields,
            option_types=sorted(option_names),
        )

    # -----------------------------------------------------------------------
    # CSV Dry-Run Validation
    # -----------------------------------------------------------------------

    def validate_rows(
        self,
        tenant_id: UUID,
        rows: List[Dict[str, Any]],
        auto_create_categories: bool = False,
    ) -> ValidationReport:
        """Validate flat CSV rows dry-run: checks types, categories, prices, SKUs, writes nothing."""
        categories = {c.key for c in self.list_categories(tenant_id)}
        results: List[RowValidationItem] = []

        # Pre-fetch existing database state for batch
        all_skus = {str(r.get("sku")).strip() for r in rows if r.get("sku")}
        all_locations = {
            str(r.get("location")).strip()
            for r in rows
            if r.get("location") and str(r.get("location")).strip()
        }

        # Query existing variants and their product names
        db_sku_to_prod_name: Dict[str, str] = {}
        if all_skus:
            db_vars = (
                self.db.query(Variant.sku, Product.name)
                .join(Product, Product.id == Variant.product_id)
                .filter(
                    Variant.tenant_id == tenant_id,
                    Variant.sku.in_(all_skus),
                )
                .all()
            )
            db_sku_to_prod_name = {row[0]: row[1] for row in db_vars}

        # Query existing inventory reserved quantities
        db_sku_loc_reserved: Dict[Tuple[str, str], int] = {}
        if all_skus and all_locations:
            db_invs = (
                self.db.query(Variant.sku, Location.name, InventoryLevel.qty_reserved)
                .join(Variant, Variant.id == InventoryLevel.variant_id)
                .join(Location, Location.id == InventoryLevel.location_id)
                .filter(
                    InventoryLevel.tenant_id == tenant_id,
                    Variant.sku.in_(all_skus),
                    Location.name.in_(all_locations),
                )
                .all()
            )
            db_sku_loc_reserved = {(row[0], row[1]): row[2] for row in db_invs}

        seen_skus: Dict[str, str] = {}
        seen_sku_prices: Dict[str, Decimal] = {}
        seen_sku_currencies: Dict[str, str] = {}
        seen_sku_options: Dict[str, Dict[str, str]] = {}
        seen_sku_locations: Set[Tuple[str, str]] = set()
        seen_prod_types: Dict[str, str] = {}
        seen_prod_categories: Dict[str, str] = {}

        valid_count = 0
        error_count = 0

        for idx, row in enumerate(rows):
            errors = []
            warnings = []

            p_name = row.get("product_name") or row.get("name")
            p_type = (row.get("type") or "PRODUCT").upper()
            cat = row.get("category")
            sku = row.get("sku")
            price = row.get("price")
            qty = row.get("qty")
            location = row.get("location")
            reorder_at = row.get("reorder_at")

            p_name_str = str(p_name).strip() if p_name else ""
            sku_str = str(sku).strip() if sku else ""
            loc_str = str(location).strip() if location else ""

            # Required field checks
            if not p_name_str:
                errors.append("product_name is required")
            if not sku_str:
                errors.append("sku is required")
            if p_type not in ("PRODUCT", "SERVICE"):
                errors.append(f"Invalid type '{p_type}'. Must be PRODUCT or SERVICE")
            if not cat:
                errors.append("category is required")
            elif not auto_create_categories and cat not in categories:
                errors.append(f"Category '{cat}' does not exist in tenant vocabulary")

            # Price validation
            parsed_price: Optional[Decimal] = None
            if price is None or str(price).strip() == "":
                errors.append("price is required")
            else:
                try:
                    parsed_price = Decimal(str(price).strip())
                    if parsed_price < 0:
                        errors.append("price must be >= 0")
                except Exception:
                    errors.append(f"Invalid price value '{price}'")

            # Qty validation
            parsed_qty: Optional[int] = None
            if qty is not None and str(qty).strip() != "":
                try:
                    parsed_qty = int(str(qty).strip())
                    if parsed_qty < 0:
                        errors.append("qty must be >= 0")
                except Exception:
                    errors.append(f"Invalid qty value '{qty}'")

            # Reorder point validation
            if reorder_at is not None and str(reorder_at).strip() != "":
                try:
                    r_val = int(str(reorder_at).strip())
                    if r_val < 0:
                        errors.append("reorder_at must be >= 0")
                except Exception:
                    errors.append(f"Invalid reorder_at value '{reorder_at}'")

            # Location and Qty cross-check
            if parsed_qty is not None and parsed_qty > 0 and not loc_str:
                warnings.append(
                    "Quantity specified without location; stock level will not be created until a location is specified."
                )

            # Product-level consistency across rows
            if p_name_str:
                if p_name_str in seen_prod_types and seen_prod_types[p_name_str] != p_type:
                    errors.append(
                        f"Conflicting type for product '{p_name_str}': '{seen_prod_types[p_name_str]}' vs '{p_type}'"
                    )
                else:
                    seen_prod_types[p_name_str] = p_type

                if cat and p_name_str in seen_prod_categories and seen_prod_categories[p_name_str] != cat:
                    errors.append(
                        f"Conflicting category for product '{p_name_str}': '{seen_prod_categories[p_name_str]}' vs '{cat}'"
                    )
                elif cat:
                    seen_prod_categories[p_name_str] = cat

            # Variant-level consistency across rows and against database
            if sku_str:
                # 1. Intra-CSV product name consistency
                if sku_str in seen_skus and seen_skus[sku_str] != p_name_str:
                    errors.append(
                        f"Duplicate SKU '{sku_str}' references multiple product names ('{seen_skus[sku_str]}' vs '{p_name_str}')"
                    )
                else:
                    seen_skus[sku_str] = p_name_str

                # 2. Database cross-check: SKU already belongs to different product in DB
                if sku_str in db_sku_to_prod_name and db_sku_to_prod_name[sku_str] != p_name_str:
                    errors.append(
                        f"SKU '{sku_str}' already belongs to existing product '{db_sku_to_prod_name[sku_str]}' in catalog"
                    )

                # 3. Price consistency for same SKU
                if parsed_price is not None:
                    if sku_str in seen_sku_prices and seen_sku_prices[sku_str] != parsed_price:
                        errors.append(
                            f"Conflicting price for SKU '{sku_str}': '{seen_sku_prices[sku_str]}' vs '{parsed_price}'"
                        )
                    else:
                        seen_sku_prices[sku_str] = parsed_price

                # 4. Currency consistency for same SKU
                currency_val = (row.get("currency") or "USD").strip().upper()
                if sku_str in seen_sku_currencies and seen_sku_currencies[sku_str] != currency_val:
                    errors.append(
                        f"Conflicting currency for SKU '{sku_str}': '{seen_sku_currencies[sku_str]}' vs '{currency_val}'"
                    )
                else:
                    seen_sku_currencies[sku_str] = currency_val

                # 5. Options consistency for same SKU
                row_opts: Dict[str, str] = {}
                for k, v in row.items():
                    if k and k.lower().startswith("option_") and v:
                        opt_key = k[len("option_"):].strip().lower()
                        if opt_key:
                            row_opts[opt_key] = str(v).strip()

                if sku_str in seen_sku_options:
                    for opt_k, opt_v in row_opts.items():
                        if opt_k in seen_sku_options[sku_str] and seen_sku_options[sku_str][opt_k] != opt_v:
                            errors.append(
                                f"Conflicting option '{opt_k}' for SKU '{sku_str}': '{seen_sku_options[sku_str][opt_k]}' vs '{opt_v}'"
                            )
                        else:
                            seen_sku_options[sku_str][opt_k] = opt_v
                else:
                    seen_sku_options[sku_str] = dict(row_opts)

                # 6. Duplicate (SKU, location) in CSV
                if loc_str:
                    pair = (sku_str, loc_str)
                    if pair in seen_sku_locations:
                        errors.append(
                            f"Duplicate (sku, location) combination ('{sku_str}', '{loc_str}')"
                        )
                    else:
                        seen_sku_locations.add(pair)

                # 7. Reserved stock check against DB
                if loc_str and parsed_qty is not None:
                    pair = (sku_str, loc_str)
                    if pair in db_sku_loc_reserved:
                        res_qty = db_sku_loc_reserved[pair]
                        if parsed_qty < res_qty:
                            errors.append(
                                f"Cannot set qty_on_hand ({parsed_qty}) less than reserved ({res_qty}) for SKU '{sku_str}' at '{loc_str}'"
                            )

            is_valid = len(errors) == 0
            if is_valid:
                valid_count += 1
            else:
                error_count += 1

            results.append(
                RowValidationItem(
                    row_index=idx,
                    valid=is_valid,
                    errors=errors,
                    warnings=warnings,
                )
            )

        # Compute preview counts of products/variants to create vs update (ONLY FOR VALID ROWS)
        valid_product_names = {
            str(rows[idx].get("product_name") or rows[idx].get("name")).strip()
            for idx, res in enumerate(results)
            if res.valid and (rows[idx].get("product_name") or rows[idx].get("name"))
        }
        valid_skus = {
            str(rows[idx].get("sku")).strip()
            for idx, res in enumerate(results)
            if res.valid and rows[idx].get("sku")
        }

        existing_product_names = (
            set(
                p[0]
                for p in self.db.query(Product.name)
                .filter(
                    Product.tenant_id == tenant_id,
                    Product.name.in_(valid_product_names),
                )
                .all()
            )
            if valid_product_names
            else set()
        )

        existing_skus = (
            set(
                v[0]
                for v in self.db.query(Variant.sku)
                .filter(
                    Variant.tenant_id == tenant_id,
                    Variant.sku.in_(valid_skus),
                )
                .all()
            )
            if valid_skus
            else set()
        )

        products_to_update = len(existing_product_names)
        products_to_create = len(valid_product_names - existing_product_names)
        variants_to_update = len(existing_skus)
        variants_to_create = len(valid_skus - existing_skus)

        return ValidationReport(
            total_rows=len(rows),
            valid_count=valid_count,
            error_count=error_count,
            products_to_create=products_to_create,
            products_to_update=products_to_update,
            variants_to_create=variants_to_create,
            variants_to_update=variants_to_update,
            row_results=results,
        )

    def generate_findability(
        self,
        name: str,
        prod_type: str = "PRODUCT",
        category: Optional[str] = None,
        subcategory: Optional[str] = None,
        description: Optional[str] = None,
    ) -> GenerateFindabilityResponse:
        """
        Auto-generate AI Agent Findability & Sales Knowledge (keywords, use cases,
        target industries, value proposition, ICP, and discount guardrails)
        using OpenRouter AI LLM with robust local heuristic fallback.
        """
        cat_str = (category or "").strip()
        subcat_str = (subcategory or "").strip()
        desc_str = (description or "").strip()

        # 1. Try OpenRouter AI Generation if API key is present
        api_key = (
            os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("OPEN_ROUTER_API")
            or os.environ.get("OPENROUTER_API")
            or ""
        ).strip()

        if api_key:
            try:
                import requests

                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "https://rolesync.ai",
                    "X-Title": "RoleSync Enterprise AI",
                    "Content-Type": "application/json",
                }

                system_prompt = (
                    "You are an expert enterprise sales engineer and autonomous AI agent catalog specialist. "
                    "Analyze the product title, type, category, and description. Generate high-impact sales intelligence "
                    "for autonomous sales agents.\n\n"
                    "Provide:\n"
                    "1. keywords: 5-8 high-intent search keywords/phrases buyer prospects or AI agents use to find this.\n"
                    "2. use_cases: 3-5 real-world practical business/personal use cases.\n"
                    "3. target_industries: 3-5 relevant vertical industries.\n"
                    "4. value_proposition: 1-2 sentence compelling ROI and outcome-focused value proposition.\n"
                    "5. ideal_customer_profile: 1-2 sentence ideal buyer profile (organization size, pain points, buyer persona).\n"
                    "6. min_discount_pct: standard minimum discount allowance (number, default 5.0).\n"
                    "7. max_discount_pct: deal ceiling discount guardrail (number, default 20.0).\n\n"
                    "Respond ONLY with a valid JSON object matching this exact schema without markdown formatting:\n"
                    "{\n"
                    '  "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],\n'
                    '  "use_cases": ["use case 1", "use case 2", "use case 3"],\n'
                    '  "target_industries": ["Tech", "Finance", "Healthcare"],\n'
                    '  "value_proposition": "...",\n'
                    '  "ideal_customer_profile": "...",\n'
                    '  "min_discount_pct": 5.0,\n'
                    '  "max_discount_pct": 20.0\n'
                    "}"
                )

                user_content = (
                    f"Product Name: {name}\n"
                    f"Product Type: {prod_type}\n"
                    f"Category: {cat_str}\n"
                    f"Subcategory: {subcat_str}\n"
                    f"Description: {desc_str[:3000]}"
                )

                candidate_models = [
                    "meta-llama/llama-3.3-70b-instruct:free",
                    "google/gemma-2-9b-it:free",
                    "liquid/lfm-2.5-2.6b:free",
                    "meta-llama/llama-3.1-8b-instruct:free",
                ]

                for model in candidate_models:
                    try:
                        res = requests.post(
                            "https://openrouter.ai/api/v1/chat/completions",
                            headers=headers,
                            json={
                                "model": model,
                                "messages": [
                                    {"role": "system", "content": system_prompt},
                                    {"role": "user", "content": user_content},
                                ],
                                "temperature": 0.3,
                                "max_tokens": 800,
                            },
                            timeout=8,
                        )
                        if res.status_code == 200:
                            data = res.json()
                            content = data["choices"][0]["message"]["content"].strip()
                            clean_json = re.sub(
                                r"^```json\s*|^```\s*|```$", "", content, flags=re.MULTILINE
                            ).strip()
                            parsed = json.loads(clean_json)

                            kw = [str(k).strip() for k in parsed.get("keywords", []) if str(k).strip()]
                            uc = [str(u).strip() for u in parsed.get("use_cases", []) if str(u).strip()]
                            ti = [str(t).strip() for t in parsed.get("target_industries", []) if str(t).strip()]
                            vp = str(parsed.get("value_proposition", "")).strip()
                            icp = str(parsed.get("ideal_customer_profile", "")).strip()

                            min_d = Decimal(str(parsed.get("min_discount_pct", 5.0)))
                            max_d = Decimal(str(parsed.get("max_discount_pct", 20.0)))

                            if kw and vp:
                                return GenerateFindabilityResponse(
                                    keywords=kw[:10],
                                    use_cases=uc[:6],
                                    target_industries=ti[:6],
                                    value_proposition=vp,
                                    ideal_customer_profile=icp,
                                    min_discount_pct=min_d,
                                    max_discount_pct=max_d,
                                )
                    except Exception as model_err:
                        logger.warning(f"OpenRouter model {model} attempt failed: {model_err}")
                        continue
            except Exception as e:
                logger.warning(f"AI findability generation network call failed: {e}")

        # 2. Local Intelligent Heuristic Fallback (deterministic, immediate, robust)
        return self._heuristic_findability(name, prod_type, cat_str, subcat_str, desc_str)

    def _heuristic_findability(
        self,
        name: str,
        prod_type: str,
        category: str,
        subcategory: str,
        description: str,
    ) -> GenerateFindabilityResponse:
        """Heuristic rule-based fallback generating realistic sales intelligence."""
        clean_name = name.strip()
        cat_display = (subcategory or category or "General").replace("_", " ").title()

        # Stop words filter
        stop_words = {
            "a", "an", "the", "for", "in", "on", "at", "to", "of", "and", "or",
            "is", "it", "with", "from", "by", "this", "that", "these", "those",
            "product", "service", "item", "new", "our", "all", "your", "we", "you",
        }

        # Extract tokens from name and description
        tokens = [
            w.lower()
            for w in re.findall(r"[a-zA-Z0-9\-\+]+", f"{clean_name} {category} {subcategory} {description}")
            if len(w) > 2 and w.lower() not in stop_words
        ]

        # Deduplicated keyword set
        seen = set()
        keywords: List[str] = []
        for t in tokens:
            if t not in seen:
                seen.add(t)
                keywords.append(t)
            if len(keywords) >= 6:
                break

        # Always include canonical phrases if name has multiple words
        name_words = clean_name.split()
        if len(name_words) >= 2:
            keywords.insert(0, clean_name.lower())

        # Tailored Use Cases
        if prod_type == "SERVICE":
            use_cases = [
                f"Enterprise {cat_display.lower()} onboarding and custom deployment",
                f"Strategic advisory and technical consulting for {clean_name}",
                "Workflow modernization, governance, and operational scaling",
                "Continuous maintenance, support, and SLA execution",
            ]
        else:
            use_cases = [
                f"Daily operational deployment for {cat_display.lower()} workflows",
                f"High-performance productivity and reliability with {clean_name}",
                "Workforce enablement, ergonomic comfort, and team collaboration",
                "Infrastructure optimization and scalable hardware rollout",
            ]

        # Target Industries based on category keywords
        industry_pool = ["Technology", "Enterprise SaaS", "Financial Services", "Healthcare & Life Sciences", "Professional Services"]
        target_industries = industry_pool[:4]

        # Crafted Value Proposition
        if description and len(description.strip()) > 30:
            first_sentence = description.split(".")[0].strip()
            value_prop = f"Empowers teams with {first_sentence.lower() if not first_sentence.startswith(clean_name) else first_sentence}."
        else:
            value_prop = f"Delivers premium enterprise-grade performance and dependable efficiency with {clean_name} for demanding business operations."

        # Crafted ICP
        if prod_type == "SERVICE":
            icp = f"Mid-to-large enterprise organizations requiring specialized {cat_display.lower()} expertise and SLA-backed execution."
        else:
            icp = f"Commercial teams and growth-focused businesses seeking reliable, high-grade {cat_display.lower()} solutions with rapid ROI."

        return GenerateFindabilityResponse(
            keywords=keywords[:8],
            use_cases=use_cases[:5],
            target_industries=target_industries,
            value_proposition=value_prop,
            ideal_customer_profile=icp,
            min_discount_pct=Decimal("5.0"),
            max_discount_pct=Decimal("20.0"),
        )

    def semantic_search(
        self,
        tenant_id: UUID,
        query: str,
        limit: int = 20,
        expand: bool = True,
    ) -> SemanticSearchResponse:
        """
        Relevance-ranked catalog search (BM25 over weighted product fields, see
        ``catalog.search_ranking``), optionally widened with synonyms from an LLM.
        """
        clean_query = query.strip()
        if not clean_query:
            return SemanticSearchResponse(query="", expanded_terms=[], results=[])

        expanded_terms = self._expand_query(clean_query) if expand else []
        products = (
            self.db.query(Product)
            .options(selectinload(Product.variants))
            .filter(Product.tenant_id == tenant_id, Product.status != "RETIRED")
            .all()
        )
        ranked = rank_products(
            clean_query,
            (
                SearchableProduct(
                    product_id=prod.id,
                    name=prod.name or "",
                    category=prod.category or "",
                    subcategory=prod.subcategory or "",
                    keywords=prod.keywords or [],
                    use_cases=prod.use_cases or [],
                    value_proposition=prod.value_proposition or "",
                    target_industries=prod.target_industries or [],
                    description=prod.description or "",
                    skus=[variant.sku for variant in prod.variants or [] if variant.sku],
                )
                for prod in products
            ),
            expanded_terms=expanded_terms,
            limit=limit,
        )
        return SemanticSearchResponse(
            query=clean_query,
            expanded_terms=expanded_terms,
            results=[
                SemanticMatchItem(
                    product_id=item.product_id,
                    score=item.score,
                    matched_terms=item.matched_terms,
                    rationale=item.rationale,
                )
                for item in ranked
            ],
        )

    @staticmethod
    def _expand_query(query: str) -> List[str]:
        """Up to 6 synonyms or related terms from an OpenRouter model; [] if unavailable."""
        api_key = (
            os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("OPEN_ROUTER_API")
            or os.environ.get("OPENROUTER_API")
            or ""
        ).strip()
        if not api_key:
            return []
        models = [
            model.strip()
            for model in os.environ.get("CATALOG_QUERY_EXPANSION_MODELS", "nvidia/nemotron-3.5-lightning:free").split(",")
            if model.strip()
        ]
        system_prompt = (
            "You are an expert sales catalog search analyzer. Given a user/customer query, "
            "extract 3-6 high-intent synonyms, related product categories, or search keywords. "
            "Respond ONLY with a JSON object: {\"expanded_terms\": [\"term1\", \"term2\", ...]}"
        )
        try:
            import requests

            res = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "https://rolesync.ai",
                    "X-Title": "RoleSync Enterprise AI",
                    "Content-Type": "application/json",
                },
                json={
                    "models": models,  # OpenRouter falls through to the next model on errors
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Customer Query: {query}"},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 150,
                    # Synonyms need no thinking; free reasoning models otherwise spend the whole budget on it.
                    "reasoning": {"enabled": False},
                },
                timeout=float(os.environ.get("CATALOG_QUERY_EXPANSION_TIMEOUT_SECONDS", "6")),
            )
            if res.status_code != 200:
                logger.warning("catalog query expansion: OpenRouter answered %s", res.status_code)
                return []
            content = res.json()["choices"][0]["message"].get("content") or ""
            match = re.search(r"\{.*\}", content, flags=re.DOTALL)
            parsed = json.loads(match.group(0)) if match else {}
        except Exception as exc:
            logger.warning("catalog query expansion failed: %s", exc)
            return []
        raw_terms = parsed.get("expanded_terms", []) if isinstance(parsed, dict) else []
        return [str(term).lower().strip() for term in raw_terms if str(term).strip()][:6]


