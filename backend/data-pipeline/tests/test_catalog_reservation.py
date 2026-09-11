import uuid
from decimal import Decimal
import pytest
from catalog.database import SessionLocal, init_catalog_db
from catalog.models import InventoryLevel, StockMovement
from catalog.schemas import (
    CategoryCreate,
    ProductCreate,
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
def setup_env(service):
    tenant_id = uuid.uuid4()
    service.upsert_category(
        tenant_id, CategoryCreate(key="desks", label="Standing Desks")
    )
    prod = service.upsert_product(
        tenant_id,
        ProductCreate(name="Smart Desk", category="desks", status="ACTIVE"),
        "u1",
    )
    variants = service.upsert_variants(
        tenant_id,
        prod.id,
        [VariantCreate(sku="DESK-SMART-01", price=Decimal("499.00"))],
    )
    variant = variants[0]

    # Location 1: Primary Warehouse (Priority 10, Sellable)
    loc_1 = service.upsert_location(
        tenant_id,
        LocationCreate(name="Primary Warehouse", priority=10, sellable=True),
    )
    # Location 2: Secondary Store (Priority 20, Sellable)
    loc_2 = service.upsert_location(
        tenant_id,
        LocationCreate(name="Secondary Store", priority=20, sellable=True),
    )
    # Location 3: Supplier Hub (Priority 5, NOT Sellable)
    loc_3 = service.upsert_location(
        tenant_id,
        LocationCreate(name="Supplier Hub", priority=5, sellable=False),
    )

    return {
        "tenant_id": tenant_id,
        "variant": variant,
        "loc_1": loc_1,
        "loc_2": loc_2,
        "loc_3": loc_3,
    }


def test_priority_allocation_single_location(service, setup_env):
    tenant_id = setup_env["tenant_id"]
    sku = setup_env["variant"].sku
    var_id = setup_env["variant"].id
    loc_1 = setup_env["loc_1"]
    loc_2 = setup_env["loc_2"]

    # Loc 1 has 10, Loc 2 has 20
    service.set_stock(tenant_id, var_id, loc_1.id, 10)
    service.set_stock(tenant_id, var_id, loc_2.id, 20)

    # Reserve 5 -> Loc 1 has priority 10 < 20 and can fully cover -> allocates from Loc 1
    res = service.reserve(tenant_id, sku, 5)
    assert res.allocated_qty == 5
    assert len(res.allocations) == 1
    assert res.allocations[0].location_id == loc_1.id
    assert res.allocations[0].qty == 5

    # Check inventory level
    inv_1 = (
        service.db.query(InventoryLevel)
        .filter(InventoryLevel.variant_id == var_id, InventoryLevel.location_id == loc_1.id)
        .one()
    )
    assert inv_1.qty_on_hand == 10
    assert inv_1.qty_reserved == 5


def test_single_cover_preference_over_split(service, setup_env):
    tenant_id = setup_env["tenant_id"]
    sku = setup_env["variant"].sku
    var_id = setup_env["variant"].id
    loc_1 = setup_env["loc_1"]
    loc_2 = setup_env["loc_2"]

    # Loc 1 has 3, Loc 2 has 10
    service.set_stock(tenant_id, var_id, loc_1.id, 3)
    service.set_stock(tenant_id, var_id, loc_2.id, 10)

    # Reserve 6 -> Loc 1 cannot fully cover (only has 3), Loc 2 can fully cover (has 10)
    res = service.reserve(tenant_id, sku, 6)
    assert res.allocated_qty == 6
    assert len(res.allocations) == 1
    assert res.allocations[0].location_id == loc_2.id
    assert res.allocations[0].qty == 6


def test_split_allocation_across_locations(service, setup_env):
    tenant_id = setup_env["tenant_id"]
    sku = setup_env["variant"].sku
    var_id = setup_env["variant"].id
    loc_1 = setup_env["loc_1"]
    loc_2 = setup_env["loc_2"]

    # Loc 1 has 4, Loc 2 has 5 -> Neither alone can cover 7, total = 9
    service.set_stock(tenant_id, var_id, loc_1.id, 4)
    service.set_stock(tenant_id, var_id, loc_2.id, 5)

    res = service.reserve(tenant_id, sku, 7)
    assert res.allocated_qty == 7
    assert len(res.allocations) == 2
    # Loc 1 (priority 10) gives 4, Loc 2 (priority 20) gives 3
    assert res.allocations[0].location_id == loc_1.id
    assert res.allocations[0].qty == 4
    assert res.allocations[1].location_id == loc_2.id
    assert res.allocations[1].qty == 3


def test_oversell_prevention(service, setup_env):
    tenant_id = setup_env["tenant_id"]
    sku = setup_env["variant"].sku
    var_id = setup_env["variant"].id
    loc_1 = setup_env["loc_1"]
    loc_2 = setup_env["loc_2"]
    loc_3 = setup_env["loc_3"]

    # Loc 1 has 2, Loc 2 has 3, Non-sellable Loc 3 has 100
    service.set_stock(tenant_id, var_id, loc_1.id, 2)
    service.set_stock(tenant_id, var_id, loc_2.id, 3)
    service.set_stock(tenant_id, var_id, loc_3.id, 100)

    # Total sellable = 5. Reserving 6 must fail without overselling
    with pytest.raises(ValueError, match="Insufficient sellable stock"):
        service.reserve(tenant_id, sku, 6)

    # Verify inventory state unchanged
    inv_1 = (
        service.db.query(InventoryLevel)
        .filter(InventoryLevel.variant_id == var_id, InventoryLevel.location_id == loc_1.id)
        .one()
    )
    inv_2 = (
        service.db.query(InventoryLevel)
        .filter(InventoryLevel.variant_id == var_id, InventoryLevel.location_id == loc_2.id)
        .one()
    )
    assert inv_1.qty_reserved == 0
    assert inv_2.qty_reserved == 0

    # Non-sellable location cannot be explicitly reserved either
    with pytest.raises(ValueError, match="not sellable"):
        service.reserve(tenant_id, sku, 1, location_id=loc_3.id)


def test_reservation_and_release(service, setup_env):
    tenant_id = setup_env["tenant_id"]
    sku = setup_env["variant"].sku
    var_id = setup_env["variant"].id
    loc_1 = setup_env["loc_1"]

    service.set_stock(tenant_id, var_id, loc_1.id, 20)

    # Check initial availability
    avail_before = service.availability(tenant_id, sku)
    assert avail_before.total_available == 20

    # Reserve 8
    res = service.reserve(tenant_id, sku, 8)
    assert res.allocated_qty == 8

    # Availability reduced
    avail_after = service.availability(tenant_id, sku)
    assert avail_after.total_available == 12

    # Release reservation
    rel = service.release(tenant_id, res.reservation_id)
    assert rel.released_qty == 8
    assert rel.movements_count == 1

    # Availability fully restored
    avail_restored = service.availability(tenant_id, sku)
    assert avail_restored.total_available == 20

    # Verify matching RELEASE movement logged in ledger
    rel_mov = (
        service.db.query(StockMovement)
        .filter(
            StockMovement.ref_id == res.reservation_id,
            StockMovement.reason == "RELEASE",
        )
        .first()
    )
    assert rel_mov is not None
    assert rel_mov.delta == 8


def test_inter_location_transfer(service, setup_env):
    tenant_id = setup_env["tenant_id"]
    sku = setup_env["variant"].sku
    var_id = setup_env["variant"].id
    loc_1 = setup_env["loc_1"]
    loc_2 = setup_env["loc_2"]

    service.set_stock(tenant_id, var_id, loc_1.id, 15)
    service.set_stock(tenant_id, var_id, loc_2.id, 5)

    # Transfer 7 units from Loc 1 to Loc 2
    transfer = service.transfer(
        tenant_id=tenant_id,
        sku=sku,
        from_location_id=loc_1.id,
        to_location_id=loc_2.id,
        qty=7,
        note="Rebalance store inventory",
    )
    assert transfer.qty == 7

    # Check stock on hand
    inv_1 = (
        service.db.query(InventoryLevel)
        .filter(InventoryLevel.variant_id == var_id, InventoryLevel.location_id == loc_1.id)
        .one()
    )
    inv_2 = (
        service.db.query(InventoryLevel)
        .filter(InventoryLevel.variant_id == var_id, InventoryLevel.location_id == loc_2.id)
        .one()
    )
    assert inv_1.qty_on_hand == 8   # 15 - 7
    assert inv_2.qty_on_hand == 12  # 5 + 7

    # Verify paired movements with shared ref_id
    movements = (
        service.db.query(StockMovement)
        .filter(StockMovement.ref_id == transfer.ref_id)
        .all()
    )
    assert len(movements) == 2
    reasons = {m.reason for m in movements}
    assert reasons == {"TRANSFER_OUT", "TRANSFER_IN"}
    deltas = {m.delta for m in movements}
    assert deltas == {-7, 7}

    # Cannot transfer more than available
    with pytest.raises(ValueError, match="Insufficient available stock"):
        service.transfer(
            tenant_id=tenant_id,
            sku=sku,
            from_location_id=loc_1.id,
            to_location_id=loc_2.id,
            qty=50,
        )

    # Cannot transfer to same location
    with pytest.raises(ValueError, match="must be distinct"):
        service.transfer(
            tenant_id=tenant_id,
            sku=sku,
            from_location_id=loc_1.id,
            to_location_id=loc_1.id,
            qty=2,
        )


def test_double_release_prevention(service, setup_env):
    tenant_id = setup_env["tenant_id"]
    sku = setup_env["variant"].sku
    var_id = setup_env["variant"].id
    loc_1 = setup_env["loc_1"]

    service.set_stock(tenant_id, var_id, loc_1.id, 20)

    # Customer 1 reserves 5
    res1 = service.reserve(tenant_id, sku, 5)
    # Release reservation 1
    rel1 = service.release(tenant_id, res1.reservation_id)
    assert rel1.released_qty == 5

    # Customer 2 reserves 5
    res2 = service.reserve(tenant_id, sku, 5)

    inv = (
        service.db.query(InventoryLevel)
        .filter(InventoryLevel.variant_id == var_id, InventoryLevel.location_id == loc_1.id)
        .one()
    )
    assert inv.qty_reserved == 5

    # Customer 1 attempts to release reservation 1 again -> MUST be rejected!
    with pytest.raises(ValueError, match="has already been released"):
        service.release(tenant_id, res1.reservation_id)

    # Verify Customer 2's reservation is completely intact
    service.db.refresh(inv)
    assert inv.qty_reserved == 5


def test_allocate_strategy_inspectable(service, setup_env):
    tenant_id = setup_env["tenant_id"]
    sku = setup_env["variant"].sku
    var_id = setup_env["variant"].id
    loc_1 = setup_env["loc_1"]
    loc_2 = setup_env["loc_2"]

    # Loc 1 (priority 10): 4 units; Loc 2 (priority 20): 6 units
    service.set_stock(tenant_id, var_id, loc_1.id, 4)
    service.set_stock(tenant_id, var_id, loc_2.id, 6)

    # 1. Single cover preference via allocate strategy
    alloc_single = service.allocate(tenant_id, var_id, 5)
    assert len(alloc_single) == 1
    assert alloc_single[0].location_id == loc_2.id
    assert alloc_single[0].qty == 5

    # 2. Split allocation via allocate strategy
    alloc_split = service.allocate(tenant_id, var_id, 8)
    assert len(alloc_split) == 2
    assert alloc_split[0].location_id == loc_1.id
    assert alloc_split[0].qty == 4
    assert alloc_split[1].location_id == loc_2.id
    assert alloc_split[1].qty == 4

    # 3. Insufficient stock via allocate strategy
    with pytest.raises(ValueError, match="Insufficient sellable stock"):
        service.allocate(tenant_id, var_id, 20)

    # 4. Verify allocate is inspectable and READ-ONLY: qty_reserved remains 0
    inv_1 = (
        service.db.query(InventoryLevel)
        .filter(InventoryLevel.variant_id == var_id, InventoryLevel.location_id == loc_1.id)
        .one()
    )
    inv_2 = (
        service.db.query(InventoryLevel)
        .filter(InventoryLevel.variant_id == var_id, InventoryLevel.location_id == loc_2.id)
        .one()
    )
    assert inv_1.qty_reserved == 0
    assert inv_2.qty_reserved == 0


def test_check_availability(service, setup_env):
    tenant_id = setup_env["tenant_id"]
    sku = setup_env["variant"].sku
    var_id = setup_env["variant"].id
    loc_1 = setup_env["loc_1"]

    service.set_stock(tenant_id, var_id, loc_1.id, 10)

    # Check fulfillable
    chk1 = service.check_availability(tenant_id, sku, qty=8)
    assert chk1.can_fulfill is True
    assert chk1.total_available == 10

    # Check unfulfillable
    chk2 = service.check_availability(tenant_id, sku, qty=15)
    assert chk2.can_fulfill is False

    # Check location-specific
    chk_loc = service.check_availability(tenant_id, sku, qty=5, location_id=loc_1.id)
    assert chk_loc.can_fulfill is True


def test_transfer_cross_tenant_location_rejected(service, setup_env):
    tenant_a = setup_env["tenant_id"]
    sku = setup_env["variant"].sku
    loc_1 = setup_env["loc_1"]

    tenant_b = uuid.uuid4()
    loc_b = service.upsert_location(tenant_b, LocationCreate(name="Other Tenant Hub", priority=10))

    # Transfer into Tenant B's location must be rejected
    with pytest.raises(ValueError, match="not found"):
        service.transfer(
            tenant_id=tenant_a,
            sku=sku,
            from_location_id=loc_1.id,
            to_location_id=loc_b.id,
            qty=1,
        )


def test_concurrent_reservations(setup_env):
    """Stress test: 25 concurrent threads racing for 20 units of stock."""
    from concurrent.futures import ThreadPoolExecutor
    tenant_id = setup_env["tenant_id"]
    sku = setup_env["variant"].sku
    var_id = setup_env["variant"].id
    loc_1 = setup_env["loc_1"]
    loc_2 = setup_env["loc_2"]

    # Use a fresh session to set stock: 10 in loc_1, 10 in loc_2 = 20 total
    main_db = SessionLocal()
    try:
        main_svc = ProductService(main_db)
        main_svc.set_stock(tenant_id, var_id, loc_1.id, 10)
        main_svc.set_stock(tenant_id, var_id, loc_2.id, 10)
    finally:
        main_db.close()

    success_count = 0
    failure_count = 0

    def reserve_one_unit():
        thread_db = SessionLocal()
        try:
            thread_svc = ProductService(thread_db)
            thread_svc.reserve(tenant_id, sku, 1)
            return True
        except ValueError:
            return False
        finally:
            thread_db.close()

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(reserve_one_unit) for _ in range(25)]
        for f in futures:
            if f.result():
                success_count += 1
            else:
                failure_count += 1

    assert success_count == 20
    assert failure_count == 5

    # Check total available is now exactly 0
    verify_db = SessionLocal()
    try:
        verify_svc = ProductService(verify_db)
        avail = verify_svc.availability(tenant_id, sku)
        assert avail.total_available == 0
    finally:
        verify_db.close()

