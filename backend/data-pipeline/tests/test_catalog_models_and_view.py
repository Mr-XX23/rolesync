import uuid
import pytest
from decimal import Decimal
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from catalog.database import SessionLocal, init_catalog_db
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


def test_schema_and_view_exists(db_session):
    # Verify catalog schema exists
    res = db_session.execute(
        text("SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'catalog';")
    ).fetchone()
    assert res is not None
    assert res[0] == "catalog"

    # Verify v_variant_availability view exists
    res = db_session.execute(
        text("SELECT table_name FROM information_schema.views WHERE table_schema = 'catalog' AND table_name = 'v_variant_availability';")
    ).fetchone()
    assert res is not None


def test_category_unique_constraint(db_session):
    tenant_id = uuid.uuid4()
    cat1 = Category(tenant_id=tenant_id, key="chairs", label="Chairs")
    db_session.add(cat1)
    db_session.commit()

    # Same key in same tenant must fail
    cat2 = Category(tenant_id=tenant_id, key="chairs", label="Duplicate Chairs")
    db_session.add(cat2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Same key in different tenant must succeed
    other_tenant = uuid.uuid4()
    cat3 = Category(tenant_id=other_tenant, key="chairs", label="Other Tenant Chairs")
    db_session.add(cat3)
    db_session.commit()


def test_product_check_constraints(db_session):
    tenant_id = uuid.uuid4()

    # Invalid type should fail
    bad_product = Product(
        tenant_id=tenant_id,
        type="INVALID_TYPE",
        name="Test",
        category="chairs",
        status="DRAFT",
    )
    db_session.add(bad_product)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Valid product
    good_product = Product(
        tenant_id=tenant_id,
        type="PRODUCT",
        name="Ergo Chair Pro",
        category="chairs",
        status="ACTIVE",
        keywords=["ergonomic", "lumbar"],
        use_cases=["office", "gaming"],
        target_industries=["tech"],
        acl=[f"tenant:{tenant_id}"],
    )
    db_session.add(good_product)
    db_session.commit()
    assert good_product.id is not None
    assert good_product.version == 1


def test_variant_constraints(db_session):
    tenant_id = uuid.uuid4()
    prod = Product(
        tenant_id=tenant_id,
        type="PRODUCT",
        name="Desk Lamp",
        category="lighting",
        status="ACTIVE",
        acl=[f"tenant:{tenant_id}"],
    )
    db_session.add(prod)
    db_session.commit()

    # Negative price should fail
    neg_variant = Variant(
        product_id=prod.id,
        tenant_id=tenant_id,
        sku="LAMP-NEG",
        price=Decimal("-10.00"),
    )
    db_session.add(neg_variant)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Valid variant
    v1 = Variant(
        product_id=prod.id,
        tenant_id=tenant_id,
        sku="LAMP-WHITE",
        price=Decimal("49.99"),
    )
    db_session.add(v1)
    db_session.commit()

    # Duplicate SKU in same tenant should fail
    v2 = Variant(
        product_id=prod.id,
        tenant_id=tenant_id,
        sku="LAMP-WHITE",
        price=Decimal("59.99"),
    )
    db_session.add(v2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_v_variant_availability_excludes_non_sellable(db_session):
    tenant_id = uuid.uuid4()

    # Product & Variant
    prod = Product(
        tenant_id=tenant_id,
        type="PRODUCT",
        name="Monitor Arm",
        category="accessories",
        status="ACTIVE",
        acl=[f"tenant:{tenant_id}"],
    )
    db_session.add(prod)
    db_session.commit()

    variant = Variant(
        product_id=prod.id,
        tenant_id=tenant_id,
        sku="ARM-MON-01",
        price=Decimal("99.00"),
    )
    db_session.add(variant)
    db_session.commit()

    # Sellable location: on_hand = 15, reserved = 3 -> available = 12
    loc_sellable = Location(
        tenant_id=tenant_id,
        name="Main Warehouse",
        type="WAREHOUSE",
        sellable=True,
        priority=10,
    )
    # Non-sellable location: on_hand = 50, reserved = 0 -> should NOT count
    loc_supplier = Location(
        tenant_id=tenant_id,
        name="Supplier Transit",
        type="IN_TRANSIT",
        sellable=False,
        priority=999,
    )
    db_session.add_all([loc_sellable, loc_supplier])
    db_session.commit()

    inv_sellable = InventoryLevel(
        variant_id=variant.id,
        location_id=loc_sellable.id,
        tenant_id=tenant_id,
        qty_on_hand=15,
        qty_reserved=3,
    )
    inv_supplier = InventoryLevel(
        variant_id=variant.id,
        location_id=loc_supplier.id,
        tenant_id=tenant_id,
        qty_on_hand=50,
        qty_reserved=0,
    )
    db_session.add_all([inv_sellable, inv_supplier])
    db_session.commit()

    # Query view
    row = db_session.execute(
        text("SELECT qty_available FROM catalog.v_variant_availability WHERE tenant_id = :tenant_id AND variant_id = :variant_id;"),
        {"tenant_id": tenant_id, "variant_id": variant.id},
    ).fetchone()

    assert row is not None
    assert int(row[0]) == 12  # Only sellable location 15 - 3 = 12
