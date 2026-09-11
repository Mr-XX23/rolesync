import uuid
from decimal import Decimal
import pytest
from catalog.database import SessionLocal, init_catalog_db
from catalog.models import Product, Variant, StockMovement, InventoryLevel
from catalog.schemas import (
    CategoryCreate,
    ProductCreate,
    ProductOptionCreate,
    OptionValueCreate,
    VariantCreate,
    LocationCreate,
)
from catalog.service import ProductService


@pytest.fixture(scope="module", autouse=True)
def setup_catalog():
    init_catalog_db()


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def service(db_session):
    return ProductService(db_session)


@pytest.fixture
def tenant_id():
    return uuid.uuid4()


def test_category_and_product_workflow(service, tenant_id):
    # 1. Upsert Category
    cat = service.upsert_category(
        tenant_id,
        CategoryCreate(key="office_seating", label="Office Seating"),
    )
    assert cat.key == "office_seating"

    # 2. Reject product with unknown category
    with pytest.raises(ValueError, match="does not exist in tenant vocabulary"):
        service.upsert_product(
            tenant_id=tenant_id,
            data=ProductCreate(
                name="Mystery Chair",
                category="non_existent_category",
                type="PRODUCT",
            ),
            user_id="user_123",
        )

    # 3. Create valid product with AI-findability attributes and ACL
    prod = service.upsert_product(
        tenant_id=tenant_id,
        data=ProductCreate(
            name="ErgoMaster Chair",
            category="office_seating",
            type="PRODUCT",
            status="ACTIVE",
            description="Premium ergonomic mesh chair for long working hours",
            keywords=["ergonomic", "back pain", "lumbar support", "posture"],
            use_cases=["office", "gaming", "desk work"],
            target_industries=["tech", "finance"],
            ideal_customer_profile="Software engineers sitting 8+ hours",
            value_proposition="Reduces back fatigue with adaptive lumbar cushioning",
            min_discount_pct=Decimal("5.0"),
            max_discount_pct=Decimal("20.0"),
        ),
        user_id="user_123",
    )
    assert prod.id is not None
    assert f"tenant:{tenant_id}" in prod.acl
    assert "user:user_123" in prod.acl
    assert prod.version == 1

    # 4. Fetch product detail
    fetched = service.get_product(tenant_id, prod.id)
    assert fetched.name == "ErgoMaster Chair"
    assert "lumbar support" in fetched.keywords


def test_options_and_candidate_grid_generation(service, tenant_id):
    # Setup Category and Product
    service.upsert_category(
        tenant_id, CategoryCreate(key="apparel", label="Apparel")
    )
    prod = service.upsert_product(
        tenant_id=tenant_id,
        data=ProductCreate(
            name="Team Hoodie",
            category="apparel",
            type="PRODUCT",
            status="ACTIVE",
        ),
        user_id="user_123",
    )

    # Define 2 axes: Size (S, M, L) and Color (Black, Navy)
    options = [
        ProductOptionCreate(
            name="Size",
            position=0,
            values=[
                OptionValueCreate(value="S", position=0),
                OptionValueCreate(value="M", position=1),
                OptionValueCreate(value="L", position=2),
            ],
        ),
        ProductOptionCreate(
            name="Color",
            position=1,
            values=[
                OptionValueCreate(value="Black", position=0),
                OptionValueCreate(value="Navy", position=1),
            ],
        ),
    ]
    created_options = service.set_options(tenant_id, prod.id, options)
    assert len(created_options) == 2
    assert len(created_options[0].values) == 3
    assert len(created_options[1].values) == 2

    # Generate Candidate Grid (Cartesian product: 3 * 2 = 6 candidates)
    grid = service.generate_variant_grid(tenant_id, prod.id)
    assert grid.product_id == prod.id
    assert len(grid.candidates) == 6

    # CRITICAL: Verify candidates are UNPERSISTED (DB has 0 variants for this product)
    variant_count = (
        service.db.query(Variant)
        .filter(Variant.product_id == prod.id)
        .count()
    )
    assert variant_count == 0

    # Pick only 2 enabled candidates to persist as variants
    cand1 = grid.candidates[0]  # S / Black
    cand2 = grid.candidates[3]  # M / Navy

    variants_to_persist = [
        VariantCreate(
            sku="HOODIE-BLK-S",
            price=Decimal("45.00"),
            currency="USD",
            option_value_ids=cand1.option_value_ids,
        ),
        VariantCreate(
            sku="HOODIE-NVY-M",
            price=Decimal("48.00"),
            currency="USD",
            option_value_ids=cand2.option_value_ids,
        ),
    ]

    persisted = service.upsert_variants(tenant_id, prod.id, variants_to_persist)
    assert len(persisted) == 2

    # Verify persisted in DB
    persisted_count = (
        service.db.query(Variant)
        .filter(Variant.product_id == prod.id)
        .count()
    )
    assert persisted_count == 2

    # Negative price rejected
    with pytest.raises((ValueError, Exception), match="greater than or equal to 0|non-negative"):
        VariantCreate(
            sku="HOODIE-INVALID",
            price=Decimal("-10.00"),
        )


def test_sku_uniqueness_across_products(service, tenant_id):
    service.upsert_category(
        tenant_id, CategoryCreate(key="misc", label="Miscellaneous")
    )
    p1 = service.upsert_product(
        tenant_id, ProductCreate(name="Item 1", category="misc"), "u1"
    )
    p2 = service.upsert_product(
        tenant_id, ProductCreate(name="Item 2", category="misc"), "u1"
    )

    # Assign SKU to Item 1
    service.upsert_variants(
        tenant_id,
        p1.id,
        [VariantCreate(sku="UNIQUE-SKU-1", price=Decimal("10.00"))],
    )

    # Attempt to assign same SKU to Item 2 in same tenant must fail
    with pytest.raises(ValueError, match="already exists for a different product"):
        service.upsert_variants(
            tenant_id,
            p2.id,
            [VariantCreate(sku="UNIQUE-SKU-1", price=Decimal("20.00"))],
        )


def test_product_soft_delete(service, tenant_id):
    service.upsert_category(
        tenant_id, CategoryCreate(key="legacy", label="Legacy")
    )
    p = service.upsert_product(
        tenant_id,
        ProductCreate(name="Old Model", category="legacy", status="ACTIVE"),
        "u1",
    )
    assert p.status == "ACTIVE"

    retired = service.delete_product(tenant_id, p.id)
    assert retired.status == "RETIRED"

    # Row still exists in DB with status RETIRED
    db_p = service.get_product(tenant_id, p.id)
    assert db_p.status == "RETIRED"


def test_product_search_and_natural_language_matching(service, tenant_id):
    service.upsert_category(
        tenant_id, CategoryCreate(key="hardware", label="Hardware")
    )
    service.upsert_product(
        tenant_id,
        ProductCreate(
            name="Acoustic Privacy Booth",
            category="hardware",
            status="ACTIVE",
            keywords=["soundproof", "phone booth", "quiet zone", "noise canceling"],
            use_cases=["private calls", "interviews", "deep focus"],
        ),
        "u1",
    )

    # Search by keyword in keywords array
    results = service.list_products(tenant_id, keywords="soundproof")
    assert len(results) == 1
    assert results[0].name == "Acoustic Privacy Booth"

    # Search by keyword in use_cases array
    results2 = service.list_products(tenant_id, keywords="private calls")
    assert len(results2) == 1

    # Search unmatched keyword
    results3 = service.list_products(tenant_id, keywords="unrelated query")
    assert len(results3) == 0


def test_stock_ledger_append_only(service, tenant_id):
    service.upsert_category(
        tenant_id, CategoryCreate(key="storage", label="Storage")
    )
    p = service.upsert_product(
        tenant_id, ProductCreate(name="Hard Drive", category="storage"), "u1"
    )
    variants = service.upsert_variants(
        tenant_id,
        p.id,
        [VariantCreate(sku="HDD-1TB", price=Decimal("50.00"))],
    )
    var = variants[0]

    loc = service.upsert_location(
        tenant_id,
        LocationCreate(name="Central Depot", type="WAREHOUSE"),
    )

    # 1. Set Stock to 100
    inv = service.set_stock(
        tenant_id=tenant_id,
        variant_id=var.id,
        location_id=loc.id,
        qty=100,
        reason="RESTOCK",
    )
    assert inv.qty_on_hand == 100

    # Verify movement record created
    movements = (
        service.db.query(StockMovement)
        .filter(StockMovement.inv_level_id == inv.id)
        .all()
    )
    assert len(movements) == 1
    assert movements[0].delta == 100
    assert movements[0].reason == "RESTOCK"

    # 2. Adjust Stock by -10 (e.g. damaged)
    inv2 = service.adjust_stock(
        tenant_id=tenant_id,
        variant_id=var.id,
        location_id=loc.id,
        delta=-10,
        reason="DAMAGE",
    )
    assert inv2.qty_on_hand == 90

    # Verify second movement record in ledger
    movements = (
        service.db.query(StockMovement)
        .filter(StockMovement.inv_level_id == inv.id)
        .order_by(StockMovement.at.asc())
        .all()
    )
    assert len(movements) == 2
    assert movements[1].delta == -10
    assert movements[1].reason == "DAMAGE"

    # 3. Illegal adjustment causing negative stock
    with pytest.raises(ValueError, match="negative qty_on_hand"):
        service.adjust_stock(
            tenant_id=tenant_id,
            variant_id=var.id,
            location_id=loc.id,
            delta=-150,
        )


def test_dry_run_validation(service, tenant_id):
    service.upsert_category(
        tenant_id, CategoryCreate(key="books", label="Books")
    )

    rows = [
        {
            "product_name": "Python Guide",
            "type": "PRODUCT",
            "category": "books",
            "sku": "BOOK-PY-01",
            "price": "39.99",
            "qty": 50,
        },
        {
            "product_name": "Invalid Book",
            "type": "UNKNOWN_TYPE",
            "category": "non_existent_category",
            "sku": "BOOK-ERR-01",
            "price": "-5.00",
            "qty": -10,
        },
    ]

    report = service.validate_rows(tenant_id, rows)
    assert report.total_rows == 2
    assert report.valid_count == 1
    assert report.error_count == 1
    assert report.row_results[0].valid is True
    assert report.row_results[1].valid is False
    assert len(report.row_results[1].errors) >= 3

    # Ensure NO writes took place in DB
    prod = (
        service.db.query(Product)
        .filter(Product.tenant_id == tenant_id, Product.name == "Python Guide")
        .first()
    )
    assert prod is None


def test_tenant_isolation(service):
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()

    # Tenant A creates product
    service.upsert_category(tenant_a, CategoryCreate(key="cat_a", label="Cat A"))
    prod_a = service.upsert_product(
        tenant_a, ProductCreate(name="Tenant A Secret", category="cat_a"), "user_a"
    )

    # Tenant B tries to fetch Tenant A product
    with pytest.raises(ValueError, match="not found"):
        service.get_product(tenant_b, prod_a.id)

    # Tenant B list_products does not see Tenant A products
    b_prods = service.list_products(tenant_b)
    assert len(b_prods) == 0


def test_vague_natural_language_search(service, tenant_id):
    service.upsert_category(
        tenant_id, CategoryCreate(key="wellness", label="Wellness")
    )
    p = service.upsert_product(
        tenant_id,
        ProductCreate(
            name="ErgoFlow Mesh Task Chair",
            category="wellness",
            status="ACTIVE",
            description="High performance office seating designed for spinal alignment",
            keywords=["back pain", "lumbar support", "spine relief", "posture"],
            use_cases=["desk work", "long shifts", "gaming"],
            target_industries=["technology", "finance"],
        ),
        "user_test",
    )
    service.upsert_variants(
        tenant_id,
        p.id,
        [VariantCreate(sku="ERGO-FLOW-01", price=Decimal("350.00"))],
    )

    # Acceptance criterion 6: Vague query returns product via keywords/use_cases matching
    vague_query = "something for back pain at my desk"
    results = service.list_products(tenant_id, keywords=vague_query)
    assert len(results) == 1
    assert results[0].id == p.id
    assert results[0].name == "ErgoFlow Mesh Task Chair"

    # Multi-term situational query
    results_sit = service.list_products(tenant_id, keywords="gaming long shifts spine relief")
    assert len(results_sit) == 1


def test_search_filters_subcategory_type_target_industry_in_stock(service, tenant_id):
    service.upsert_category(
        tenant_id, CategoryCreate(key="furniture", label="Furniture")
    )
    loc = service.upsert_location(
        tenant_id, LocationCreate(name="Main Hub", priority=10, sellable=True)
    )

    p1 = service.upsert_product(
        tenant_id,
        ProductCreate(
            name="Standing Desk Frame",
            category="furniture",
            subcategory="standing_desks",
            type="PRODUCT",
            status="ACTIVE",
            target_industries=["corporate", "home_office"],
        ),
        "user_test",
    )
    v1 = service.upsert_variants(
        tenant_id,
        p1.id,
        [VariantCreate(sku="DESK-FRAME-01", price=Decimal("299.00"))],
    )[0]

    p2 = service.upsert_product(
        tenant_id,
        ProductCreate(
            name="Ergonomic Consultation Service",
            category="furniture",
            subcategory="ergonomic_evaluations",
            type="SERVICE",
            status="ACTIVE",
            target_industries=["healthcare"],
        ),
        "user_test",
    )
    v2 = service.upsert_variants(
        tenant_id,
        p2.id,
        [VariantCreate(sku="SRV-ERGO-01", price=Decimal("150.00"))],
    )[0]

    # Filter by subcategory
    desks = service.list_products(tenant_id, subcategory="standing_desks")
    assert len(desks) == 1
    assert desks[0].name == "Standing Desk Frame"

    # Filter by type
    services = service.list_products(tenant_id, type="SERVICE")
    assert len(services) == 1
    assert services[0].name == "Ergonomic Consultation Service"

    # Filter by target_industry
    health = service.list_products(tenant_id, target_industry="healthcare")
    assert len(health) == 1
    assert health[0].name == "Ergonomic Consultation Service"

    # Stock filter: Initially 0 stock, in_stock=True returns 0
    in_stock_prods = service.list_products(tenant_id, in_stock=True)
    assert len(in_stock_prods) == 0

    # Add stock to p1
    service.set_stock(tenant_id, v1.id, loc.id, 10)
    in_stock_prods = service.list_products(tenant_id, in_stock=True)
    assert len(in_stock_prods) == 1
    assert in_stock_prods[0].id == p1.id


def test_set_stock_below_reserved_rejected(service, tenant_id):
    service.upsert_category(
        tenant_id, CategoryCreate(key="supplies", label="Supplies")
    )
    p = service.upsert_product(
        tenant_id, ProductCreate(name="Notebooks", category="supplies"), "u1"
    )
    v = service.upsert_variants(
        tenant_id, p.id, [VariantCreate(sku="NOTE-01", price=Decimal("5.00"))]
    )[0]
    loc = service.upsert_location(
        tenant_id, LocationCreate(name="Warehouse", priority=10, sellable=True)
    )

    # Initial stock: 10
    service.set_stock(tenant_id, v.id, loc.id, 10)
    # Reserve 6
    service.reserve(tenant_id, "NOTE-01", 6)

    # Setting stock below 6 must be rejected
    with pytest.raises(ValueError, match="less than reserved"):
        service.set_stock(tenant_id, v.id, loc.id, 4)

    # Setting stock >= 6 is valid
    inv = service.set_stock(tenant_id, v.id, loc.id, 8)
    assert inv.qty_on_hand == 8
    assert inv.qty_reserved == 6


def test_inventory_cross_tenant_location_rejected(service):
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()

    service.upsert_category(tenant_a, CategoryCreate(key="cat_a", label="Cat A"))
    p_a = service.upsert_product(tenant_a, ProductCreate(name="Item A", category="cat_a"), "u_a")
    v_a = service.upsert_variants(tenant_a, p_a.id, [VariantCreate(sku="SKU-A", price=Decimal("10.00"))])[0]

    # Tenant B creates location
    loc_b = service.upsert_location(tenant_b, LocationCreate(name="Tenant B Secret Hub", priority=10))

    # Tenant A attempts to set stock at Tenant B's location -> rejected
    with pytest.raises(ValueError, match="not found"):
        service.set_stock(tenant_a, v_a.id, loc_b.id, 50)

    # Tenant A attempts adjust_stock at Tenant B's location -> rejected
    with pytest.raises(ValueError, match="not found"):
        service.adjust_stock(tenant_a, v_a.id, loc_b.id, 10)


def test_delete_product_retires_variants(service, tenant_id):
    service.upsert_category(
        tenant_id, CategoryCreate(key="gadgets", label="Gadgets")
    )
    p = service.upsert_product(
        tenant_id, ProductCreate(name="Drone V1", category="gadgets", status="ACTIVE"), "u1"
    )
    service.upsert_variants(
        tenant_id,
        p.id,
        [
            VariantCreate(sku="DRONE-V1-STD", price=Decimal("499.00")),
            VariantCreate(sku="DRONE-V1-PRO", price=Decimal("799.00")),
        ],
    )

    # Soft delete product
    service.delete_product(tenant_id, p.id)

    # Verify all variants are also RETIRED
    variants = service.db.query(Variant).filter(Variant.product_id == p.id).all()
    assert len(variants) == 2
    assert all(v.status == "RETIRED" for v in variants)


def test_upsert_variants_validation(service, tenant_id):
    service.upsert_category(
        tenant_id, CategoryCreate(key="merch", label="Merch")
    )
    p1 = service.upsert_product(
        tenant_id, ProductCreate(name="T-Shirt", category="merch"), "u1"
    )
    p2 = service.upsert_product(
        tenant_id, ProductCreate(name="Cap", category="merch"), "u1"
    )

    opts = service.set_options(
        tenant_id,
        p1.id,
        [ProductOptionCreate(name="Size", values=[OptionValueCreate(value="M")])],
    )
    p1_val_id = opts[0].values[0].id

    # 1. Attempt to associate p1's option value to p2 -> rejected
    with pytest.raises(ValueError, match="do not belong to this product"):
        service.upsert_variants(
            tenant_id,
            p2.id,
            [VariantCreate(sku="CAP-M", price=Decimal("20.00"), option_value_ids=[p1_val_id])],
        )

    # 2. Batch with duplicate SKUs -> rejected
    with pytest.raises(ValueError, match="Duplicate SKU"):
        service.upsert_variants(
            tenant_id,
            p1.id,
            [
                VariantCreate(sku="SHIRT-DUP", price=Decimal("25.00")),
                VariantCreate(sku="SHIRT-DUP", price=Decimal("30.00")),
            ],
        )


def test_describe_catalog(service, tenant_id):
    service.upsert_category(tenant_id, CategoryCreate(key="tools", label="Tools"))
    p = service.upsert_product(tenant_id, ProductCreate(name="Drill", category="tools"), "u1")
    service.set_options(
        tenant_id,
        p.id,
        [ProductOptionCreate(name="Power", values=[OptionValueCreate(value="18V")])],
    )

    desc = service.describe_catalog(tenant_id)
    assert any(c.key == "tools" for c in desc.categories)
    assert "keywords" in desc.filterable_fields
    assert "Power" in desc.option_types


def test_cross_tenant_product_delete_isolation(service, tenant_id):
    # Tenant 1 creates a product
    service.upsert_category(tenant_id, CategoryCreate(key="secure_cat", label="Secure Category"))
    p1 = service.upsert_product(
        tenant_id,
        ProductCreate(name="Tenant1 Secret Product", category="secure_cat"),
        user_id="user_1",
    )

    # Tenant 2 tries to soft-delete or hard-delete Tenant 1's product
    other_tenant = uuid.uuid4()
    with pytest.raises(ValueError, match="not found"):
        service.delete_product(other_tenant, p1.id)

    with pytest.raises(ValueError, match="not found"):
        service.hard_delete_product(other_tenant, p1.id)

    # Verify product is intact under Tenant 1
    fetched = service.get_product(tenant_id, p1.id)
    assert fetched.status == "DRAFT"


def test_product_description_natural_sql_words(service, tenant_id):
    # Ensure natural English with words like 'select', 'from', 'table', 'create' is accepted
    service.upsert_category(tenant_id, CategoryCreate(key="furniture", label="Furniture"))
    desc_text = "Select from our wide range of office furniture. Create the ideal conference table setting."
    p = service.upsert_product(
        tenant_id,
        ProductCreate(
            name="Executive Conference Table",
            category="furniture",
            description=desc_text,
            value_proposition="Select from premium hardwood finishes to update your boardroom table.",
        ),
        user_id="user_1",
    )
    assert p.id is not None
    assert "Select from our wide range" in p.description


def test_batch_set_stock_and_batch_availability(service, tenant_id):
    service.upsert_category(tenant_id, CategoryCreate(key="hardware", label="Hardware"))
    p = service.upsert_product(tenant_id, ProductCreate(name="Power Router", category="hardware"), "u1")
    variants = service.upsert_variants(
        tenant_id,
        p.id,
        [
            VariantCreate(sku="RTR-100", price=Decimal("89.99")),
            VariantCreate(sku="RTR-200", price=Decimal("129.99")),
        ],
    )
    loc1 = service.upsert_location(tenant_id, LocationCreate(name="Hub North", priority=10))
    loc2 = service.upsert_location(tenant_id, LocationCreate(name="Hub South", priority=20))

    # 1. Batch set stock across variants and locations
    stock_items = [
        {"variant_id": variants[0].id, "location_id": loc1.id, "qty": 40, "reason": "RESTOCK", "note": "Initial"},
        {"variant_id": variants[0].id, "location_id": loc2.id, "qty": 20, "reason": "RESTOCK", "note": "Initial"},
        {"variant_id": variants[1].id, "location_id": loc1.id, "qty": 15, "reason": "RESTOCK", "note": "Initial"},
    ]
    updated = service.batch_set_stock(tenant_id, stock_items, created_by="tester")
    assert len(updated) == 3

    # 2. Batch availability check
    avail_map = service.batch_availability(tenant_id, skus=["RTR-100", "RTR-200"])
    assert "RTR-100" in avail_map
    assert "RTR-200" in avail_map
    assert avail_map["RTR-100"].total_available == 60
    assert avail_map["RTR-200"].total_available == 15
    assert len(avail_map["RTR-100"].by_location) == 2


