import asyncio
import io
import time
import uuid
from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from catalog.database import SessionLocal, init_catalog_db
from catalog.models import (
    Category,
    InventoryLevel,
    Location,
    Product,
    ProductOption,
    OptionValue,
    StockMovement,
    Variant,
    VariantOptionValue,
)
from catalog.routes import router as catalog_router
from catalog.csv_importer import (
    CANONICAL_COLUMNS,
    catalog_import_worker,
    generate_csv_template,
    group_rows_by_product,
    normalize_option_name,
    parse_csv,
    parse_list_field,
)

# Test application
app = FastAPI()
app.include_router(catalog_router, prefix="/api/v1/catalog")


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    init_catalog_db()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def tenant_a():
    return str(uuid.uuid4())


@pytest.fixture
def tenant_b():
    return str(uuid.uuid4())


@pytest.fixture
def headers_a(tenant_a):
    return {"X-Tenant-Id": tenant_a, "X-User-Id": "user_a"}


@pytest.fixture
def headers_b(tenant_b):
    return {"X-Tenant-Id": tenant_b, "X-User-Id": "user_b"}


def poll_job_until_terminal(client, job_id, headers, timeout=8.0, interval=0.05):
    """Helper to poll import job until COMPLETED or FAILED."""
    start = time.time()
    while time.time() - start < timeout:
        res = client.get(f"/api/v1/catalog/import/jobs/{job_id}", headers=headers)
        assert res.status_code == 200
        data = res.json()
        if data["status"] in ("COMPLETED", "FAILED"):
            return data
        time.sleep(interval)
    raise TimeoutError(f"Job {job_id} did not terminate within {timeout} seconds")


# ===========================================================================
# 1. Downloadable CSV Template Tests
# ===========================================================================

def test_template_generation():
    csv_text = generate_csv_template()
    assert csv_text is not None
    rows = parse_csv(csv_text)
    assert len(rows) >= 3

    # Check canonical header columns
    first_line = csv_text.strip().splitlines()[0]
    for col in CANONICAL_COLUMNS:
        assert col in first_line


def test_template_api_endpoint(client):
    res = client.get("/api/v1/catalog/import/template.csv")
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    assert 'filename="catalog_import_template.csv"' in res.headers["content-disposition"]
    csv_content = res.text
    rows = parse_csv(csv_content)
    assert len(rows) >= 3
    assert rows[0]["product_name"] == "Ergonomic Executive Chair"


# ===========================================================================
# 2. Parsing & Dynamic Option Extraction Tests
# ===========================================================================

def test_parse_helpers():
    # normalize_option_name
    assert normalize_option_name("option_size") == "Size"
    assert normalize_option_name("option_color") == "Color"
    assert normalize_option_name("option_seat_depth") == "Seat Depth"

    # parse_list_field
    assert parse_list_field("ergonomic, lumbar, mesh") == ["ergonomic", "lumbar", "mesh"]
    assert parse_list_field("office; work from home") == ["office", "work from home"]
    assert parse_list_field('["tech", "finance"]') == ["tech", "finance"]
    assert parse_list_field("") == []
    assert parse_list_field(None) == []


def test_parse_csv_and_grouping():
    sample_csv = """product_name,type,category,option_size,option_color,option_material,sku,price,currency,keywords,use_cases,target_industries,location,qty,reorder_at
Smart Desk,PRODUCT,office_desk,140cm,Walnut,Steel,DESK-140-WAL,649.00,USD,"desk,motorized",office,tech,Main Warehouse,20,5
Smart Desk,PRODUCT,office_desk,160cm,Walnut,Steel,DESK-160-WAL,699.00,USD,"desk,motorized",office,tech,Main Warehouse,15,5
Smart Desk,PRODUCT,office_desk,140cm,Walnut,Steel,DESK-140-WAL,649.00,USD,"desk,motorized",office,tech,Showroom,5,2
Mesh Task Chair,PRODUCT,office_chair,Standard,Black,,CHAIR-MESH-STD,199.99,USD,ergonomic,office,tech,Main Warehouse,30,10
"""
    rows = parse_csv(sample_csv)
    assert len(rows) == 4

    groups = group_rows_by_product(rows)
    assert len(groups) == 2

    # Group 1: Smart Desk
    desk_group = next(g for g in groups if g.product_name == "Smart Desk")
    assert desk_group.product_type == "PRODUCT"
    assert desk_group.category == "office_desk"
    assert "Size" in desk_group.options
    assert "Color" in desk_group.options
    assert "Material" in desk_group.options
    assert set(desk_group.options["Size"]) == {"140cm", "160cm"}
    assert set(desk_group.options["Color"]) == {"Walnut"}
    assert set(desk_group.options["Material"]) == {"Steel"}

    # Unique variants
    assert len(desk_group.variants) == 2
    assert "DESK-140-WAL" in desk_group.variants
    assert "DESK-160-WAL" in desk_group.variants
    assert desk_group.variants["DESK-140-WAL"]["price"] == Decimal("649.00")
    assert desk_group.variants["DESK-140-WAL"]["options"]["Size"] == "140cm"

    # Multi-location inventory
    assert len(desk_group.inventory) == 3
    desk_140_inv = [i for i in desk_group.inventory if i["sku"] == "DESK-140-WAL"]
    assert len(desk_140_inv) == 2
    assert any(i["location"] == "Main Warehouse" and i["qty"] == 20 for i in desk_140_inv)
    assert any(i["location"] == "Showroom" and i["qty"] == 5 for i in desk_140_inv)

    # Group 2: Mesh Task Chair
    chair_group = next(g for g in groups if g.product_name == "Mesh Task Chair")
    assert len(chair_group.variants) == 1
    assert "Material" not in chair_group.variants["CHAIR-MESH-STD"]["options"]


# ===========================================================================
# 3. Dry-Run Validation API Tests
# ===========================================================================

def test_dry_run_validation_clean(client, headers_a, tenant_a, db):
    # Seed category
    client.post(
        "/api/v1/catalog/categories",
        json={"key": "seating", "label": "Seating"},
        headers=headers_a,
    )

    clean_csv = """product_name,type,category,option_size,option_color,sku,price,currency,keywords,use_cases,target_industries,location,qty,reorder_at
Aeron Chair,PRODUCT,seating,B,Graphite,AERON-B-GRP,1195.00,USD,ergonomic,office,corporate,DC-1,10,2
Aeron Chair,PRODUCT,seating,C,Graphite,AERON-C-GRP,1245.00,USD,ergonomic,office,corporate,DC-1,8,2
"""
    # Test JSON payload
    res = client.post(
        "/api/v1/catalog/import/validate",
        json={"csv_content": clean_csv},
        headers=headers_a,
    )
    assert res.status_code == 200
    report = res.json()
    assert report["total_rows"] == 2
    assert report["valid_count"] == 2
    assert report["error_count"] == 0
    assert report["products_to_create"] == 1
    assert report["products_to_update"] == 0
    assert report["variants_to_create"] == 2
    assert report["variants_to_update"] == 0
    assert all(r["valid"] is True for r in report["row_results"])

    # Verify NO database writes occurred
    prod = (
        db.query(Product)
        .filter(Product.tenant_id == tenant_a, Product.name == "Aeron Chair")
        .first()
    )
    assert prod is None


def test_dry_run_validation_invalid_rows(client, headers_a):
    invalid_csv = """product_name,type,category,sku,price,qty
,PRODUCT,seating,SKU-NO-NAME,50.00,10
Bad Type Prod,INVALID_TYPE,seating,SKU-BAD-TYPE,50.00,10
Bad Price Prod,PRODUCT,seating,SKU-BAD-PRICE,-25.00,10
Bad Qty Prod,PRODUCT,seating,SKU-BAD-QTY,50.00,-5
No Sku Prod,PRODUCT,seating,,50.00,10
"""
    res = client.post(
        "/api/v1/catalog/import/validate",
        content=invalid_csv,
        headers={**headers_a, "Content-Type": "text/csv"},
    )
    assert res.status_code == 200
    report = res.json()
    assert report["total_rows"] == 5
    assert report["valid_count"] == 0
    assert report["error_count"] == 5
    for r in report["row_results"]:
        assert r["valid"] is False
        assert len(r["errors"]) >= 1


def test_dry_run_validation_file_upload(client, headers_a):
    csv_bytes = b"""product_name,type,category,sku,price,location,qty
File Chair,PRODUCT,seating,FILE-CHR-01,99.00,Warehouse,15
"""
    files = {"file": ("upload.csv", csv_bytes, "text/csv")}
    res = client.post(
        "/api/v1/catalog/import/validate",
        files=files,
        headers=headers_a,
    )
    assert res.status_code == 200
    report = res.json()
    assert report["valid_count"] == 1
    assert report["products_to_create"] == 1


# ===========================================================================
# 4. Async Import Worker Execution Tests
# ===========================================================================

def test_async_import_worker_full_pipeline(client, headers_a, tenant_a, db):
    csv_data = """product_name,type,category,option_size,option_color,sku,price,currency,keywords,use_cases,target_industries,location,qty,reorder_at
Nordic Lounge Chair,PRODUCT,furniture,Standard,Oatmeal,NORD-CHR-OAT,450.00,USD,"nordic,scandinavian",lounge,hospitality,Central Hub,25,5
Nordic Lounge Chair,PRODUCT,furniture,Standard,Charcoal,NORD-CHR-CHR,450.00,USD,"nordic,scandinavian",lounge,hospitality,Central Hub,15,3
Nordic Lounge Chair,PRODUCT,furniture,Standard,Charcoal,NORD-CHR-CHR,450.00,USD,"nordic,scandinavian",lounge,hospitality,Showroom North,8,2
"""
    # 1. Commit import job
    res = client.post(
        "/api/v1/catalog/import/commit",
        json={"csv_content": csv_data, "skip_invalid": False, "auto_create_categories": True},
        headers=headers_a,
    )
    assert res.status_code == 202
    job_info = res.json()
    job_id = job_info["job_id"]
    assert job_info["status"] == "PENDING"

    # 2. Wait for background worker
    finished_job = poll_job_until_terminal(client, job_id, headers_a)
    assert finished_job["status"] == "COMPLETED"
    assert finished_job["progress_pct"] == 100.0
    assert finished_job["created_count"] == 2  # 2 unique SKUs
    assert finished_job["updated_count"] == 0
    assert finished_job["skipped_count"] == 0
    assert finished_job["errors"] == []

    # 3. Verify Product in DB
    product = (
        db.query(Product)
        .filter(Product.tenant_id == tenant_a, Product.name == "Nordic Lounge Chair")
        .first()
    )
    assert product is not None
    assert product.type == "PRODUCT"
    assert product.category == "furniture"
    assert "nordic" in product.keywords

    # 4. Verify Options & Values
    options = (
        db.query(ProductOption)
        .filter(ProductOption.tenant_id == tenant_a, ProductOption.product_id == product.id)
        .all()
    )
    opt_names = {o.name for o in options}
    assert "Size" in opt_names
    assert "Color" in opt_names

    # 5. Verify Variants
    variants = (
        db.query(Variant)
        .filter(Variant.tenant_id == tenant_a, Variant.product_id == product.id)
        .all()
    )
    assert len(variants) == 2
    skus = {v.sku for v in variants}
    assert "NORD-CHR-OAT" in skus
    assert "NORD-CHR-CHR" in skus

    # 6. Verify Locations
    locations = (
        db.query(Location)
        .filter(Location.tenant_id == tenant_a)
        .all()
    )
    loc_names = {l.name for l in locations}
    assert "Central Hub" in loc_names
    assert "Showroom North" in loc_names

    # 7. Verify Inventory Levels & StockMovement Ledger
    oat_var = next(v for v in variants if v.sku == "NORD-CHR-OAT")
    chr_var = next(v for v in variants if v.sku == "NORD-CHR-CHR")
    hub_loc = next(l for l in locations if l.name == "Central Hub")
    show_loc = next(l for l in locations if l.name == "Showroom North")

    oat_hub_inv = (
        db.query(InventoryLevel)
        .filter(
            InventoryLevel.tenant_id == tenant_a,
            InventoryLevel.variant_id == oat_var.id,
            InventoryLevel.location_id == hub_loc.id,
        )
        .one()
    )
    assert oat_hub_inv.qty_on_hand == 25
    assert oat_hub_inv.reorder_at == 5

    chr_show_inv = (
        db.query(InventoryLevel)
        .filter(
            InventoryLevel.tenant_id == tenant_a,
            InventoryLevel.variant_id == chr_var.id,
            InventoryLevel.location_id == show_loc.id,
        )
        .one()
    )
    assert chr_show_inv.qty_on_hand == 8
    assert chr_show_inv.reorder_at == 2

    # StockMovement ledger entries
    movements = (
        db.query(StockMovement)
        .filter(StockMovement.tenant_id == tenant_a)
        .all()
    )
    assert len(movements) >= 3
    for m in movements:
        assert m.reason == "RESTOCK"
        assert m.delta > 0


# ===========================================================================
# 5. Idempotency Tests
# ===========================================================================

def test_import_idempotency_exact_same_csv(client, headers_a, tenant_a, db):
    csv_data = """product_name,type,category,option_size,sku,price,currency,location,qty
Idempotent Monitor,PRODUCT,electronics,27inch,MON-IDEM-27,299.99,USD,Main Warehouse,20
Idempotent Monitor,PRODUCT,electronics,32inch,MON-IDEM-32,399.99,USD,Main Warehouse,15
"""
    # 1. Initial import
    res1 = client.post(
        "/api/v1/catalog/import/commit",
        json={"csv_content": csv_data},
        headers=headers_a,
    )
    job1 = poll_job_until_terminal(client, res1.json()["job_id"], headers_a)
    assert job1["status"] == "COMPLETED"
    assert job1["created_count"] == 2
    assert job1["updated_count"] == 0

    count_prods_1 = db.query(Product).filter(Product.tenant_id == tenant_a).count()
    count_vars_1 = db.query(Variant).filter(Variant.tenant_id == tenant_a).count()
    count_invs_1 = db.query(InventoryLevel).filter(InventoryLevel.tenant_id == tenant_a).count()
    count_movs_1 = db.query(StockMovement).filter(StockMovement.tenant_id == tenant_a).count()

    # 2. Re-import the exact same CSV
    res2 = client.post(
        "/api/v1/catalog/import/commit",
        json={"csv_content": csv_data},
        headers=headers_a,
    )
    job2 = poll_job_until_terminal(client, res2.json()["job_id"], headers_a)
    assert job2["status"] == "COMPLETED"
    assert job2["created_count"] == 0
    assert job2["updated_count"] == 2  # Updated existing variants

    # Counts must NOT have duplicated
    count_prods_2 = db.query(Product).filter(Product.tenant_id == tenant_a).count()
    count_vars_2 = db.query(Variant).filter(Variant.tenant_id == tenant_a).count()
    count_invs_2 = db.query(InventoryLevel).filter(InventoryLevel.tenant_id == tenant_a).count()
    count_movs_2 = db.query(StockMovement).filter(StockMovement.tenant_id == tenant_a).count()

    assert count_prods_2 == count_prods_1
    assert count_vars_2 == count_vars_1
    assert count_invs_2 == count_invs_1
    # Because quantities did not change (delta=0), no new ledger rows are written
    assert count_movs_2 == count_movs_1


def test_import_idempotency_price_and_stock_update(client, headers_a, tenant_a, db):
    initial_csv = """product_name,type,category,option_size,sku,price,currency,location,qty
Idempotent Monitor,PRODUCT,electronics,27inch,MON-IDEM-27,299.99,USD,Main Warehouse,20
Idempotent Monitor,PRODUCT,electronics,32inch,MON-IDEM-32,399.99,USD,Main Warehouse,15
"""
    res_init = client.post(
        "/api/v1/catalog/import/commit",
        json={"csv_content": initial_csv},
        headers=headers_a,
    )
    job_init = poll_job_until_terminal(client, res_init.json()["job_id"], headers_a)
    assert job_init["status"] == "COMPLETED"
    assert job_init["created_count"] == 2

    # Update price and stock for MON-IDEM-27
    updated_csv = """product_name,type,category,option_size,sku,price,currency,location,qty
Idempotent Monitor,PRODUCT,electronics,27inch,MON-IDEM-27,279.99,USD,Main Warehouse,35
Idempotent Monitor,PRODUCT,electronics,32inch,MON-IDEM-32,399.99,USD,Main Warehouse,15
"""
    res = client.post(
        "/api/v1/catalog/import/commit",
        json={"csv_content": updated_csv},
        headers=headers_a,
    )
    job = poll_job_until_terminal(client, res.json()["job_id"], headers_a)
    assert job["status"] == "COMPLETED"
    assert job["created_count"] == 0
    assert job["updated_count"] == 2

    # Verify updated price
    var_27 = (
        db.query(Variant)
        .filter(Variant.tenant_id == tenant_a, Variant.sku == "MON-IDEM-27")
        .one()
    )
    assert var_27.price == Decimal("279.99")

    # Verify stock updated from 20 to 35 with delta = +15 in ledger
    inv = (
        db.query(InventoryLevel)
        .filter(InventoryLevel.tenant_id == tenant_a, InventoryLevel.variant_id == var_27.id)
        .one()
    )
    assert inv.qty_on_hand == 35

    delta_movement = (
        db.query(StockMovement)
        .filter(
            StockMovement.tenant_id == tenant_a,
            StockMovement.inv_level_id == inv.id,
            StockMovement.delta == 15,
        )
        .first()
    )
    assert delta_movement is not None


# ===========================================================================
# 6. Skip Invalid Flag Tests
# ===========================================================================

def test_skip_invalid_false_aborts_batch(client, headers_a, tenant_a, db):
    mixed_csv = """product_name,type,category,sku,price,qty
Valid Lamp,PRODUCT,lighting,LAMP-001,49.99,10
Invalid Lamp,PRODUCT,lighting,LAMP-002,-10.00,5
"""
    # With skip_invalid=False: should fail and write nothing
    res = client.post(
        "/api/v1/catalog/import/commit",
        json={"csv_content": mixed_csv, "skip_invalid": False},
        headers=headers_a,
    )
    job = poll_job_until_terminal(client, res.json()["job_id"], headers_a)
    assert job["status"] == "FAILED"
    assert len(job["errors"]) > 0
    assert any("Row 2" in err for err in job["errors"])

    # Ensure Valid Lamp was NOT imported
    lamp_prod = (
        db.query(Product)
        .filter(Product.tenant_id == tenant_a, Product.name == "Valid Lamp")
        .first()
    )
    assert lamp_prod is None


def test_skip_invalid_true_imports_valid_rows(client, headers_a, tenant_a, db):
    mixed_csv = """product_name,type,category,sku,price,qty
Valid Lamp Success,PRODUCT,lighting,LAMP-SUCCESS-01,49.99,10
Invalid Lamp Row,PRODUCT,lighting,LAMP-BAD-02,-10.00,5
"""
    # With skip_invalid=True: should import valid row and record skipped row
    res = client.post(
        "/api/v1/catalog/import/commit",
        json={"csv_content": mixed_csv, "skip_invalid": True},
        headers=headers_a,
    )
    job = poll_job_until_terminal(client, res.json()["job_id"], headers_a)
    assert job["status"] == "COMPLETED"
    assert job["created_count"] == 1
    assert job["skipped_count"] == 1
    assert len(job["errors"]) == 1

    # Ensure Valid Lamp Success was imported
    lamp_prod = (
        db.query(Product)
        .filter(Product.tenant_id == tenant_a, Product.name == "Valid Lamp Success")
        .first()
    )
    assert lamp_prod is not None

    lamp_var = (
        db.query(Variant)
        .filter(Variant.tenant_id == tenant_a, Variant.sku == "LAMP-SUCCESS-01")
        .first()
    )
    assert lamp_var is not None


# ===========================================================================
# 7. Multi-Tenant Isolation Tests
# ===========================================================================

def test_tenant_isolation_during_import(client, headers_a, headers_b, tenant_a, tenant_b, db):
    csv_a = """product_name,type,category,sku,price,location,qty
Tenant A Exclusive,PRODUCT,security,SHARED-SKU-100,500.00,Loc A,10
"""
    res_a = client.post(
        "/api/v1/catalog/import/commit",
        json={"csv_content": csv_a},
        headers=headers_a,
    )
    job_a_id = res_a.json()["job_id"]
    job_a = poll_job_until_terminal(client, job_a_id, headers_a)
    assert job_a["status"] == "COMPLETED"

    # 1. Tenant B cannot access Tenant A's import job
    res_job_b = client.get(f"/api/v1/catalog/import/jobs/{job_a_id}", headers=headers_b)
    assert res_job_b.status_code == 404

    # 2. Tenant B does not see Tenant A's imported product
    res_prods_b = client.get("/api/v1/catalog/products", headers=headers_b)
    assert res_prods_b.status_code == 200
    assert not any(p["name"] == "Tenant A Exclusive" for p in res_prods_b.json())

    # 3. Tenant B can import the EXACT SAME SKU without conflict
    csv_b = """product_name,type,category,sku,price,location,qty
Tenant B Exclusive,PRODUCT,logistics,SHARED-SKU-100,800.00,Loc B,20
"""
    res_b = client.post(
        "/api/v1/catalog/import/commit",
        json={"csv_content": csv_b},
        headers=headers_b,
    )
    job_b_id = res_b.json()["job_id"]
    job_b = poll_job_until_terminal(client, job_b_id, headers_b)
    assert job_b["status"] == "COMPLETED"
    assert job_b["created_count"] == 1

    # Verify both variants exist under their respective tenant_id
    var_a = (
        db.query(Variant)
        .filter(Variant.tenant_id == tenant_a, Variant.sku == "SHARED-SKU-100")
        .one()
    )
    assert var_a.price == Decimal("500.00")

    var_b = (
        db.query(Variant)
        .filter(Variant.tenant_id == tenant_b, Variant.sku == "SHARED-SKU-100")
        .one()
    )
    assert var_b.price == Decimal("800.00")
    assert var_a.id != var_b.id


# ===========================================================================
# 8. Edge Cases Tests
# ===========================================================================

def test_empty_and_whitespace_csv(client, headers_a):
    # Empty string
    res = client.post(
        "/api/v1/catalog/import/validate",
        json={"csv_content": ""},
        headers=headers_a,
    )
    assert res.status_code == 400
    assert "No CSV content provided" in res.json()["detail"]

    # Whitespace only
    res = client.post(
        "/api/v1/catalog/import/commit",
        json={"csv_content": "   \n\t  "},
        headers=headers_a,
    )
    assert res.status_code == 400
    assert "No CSV content provided" in res.json()["detail"]


def test_non_existent_job_id(client, headers_a):
    random_job_id = str(uuid.uuid4())
    res = client.get(f"/api/v1/catalog/import/jobs/{random_job_id}", headers=headers_a)
    assert res.status_code == 404
    assert f"Import job '{random_job_id}' not found" in res.json()["detail"]


def test_simple_product_without_options(client, headers_a, tenant_a, db):
    # CSV with no option_* columns
    csv_data = """product_name,type,category,sku,price,currency,location,qty
Simple Standalone Book,PRODUCT,media,BOOK-SOLO-01,24.95,USD,Warehouse 1,50
"""
    res = client.post(
        "/api/v1/catalog/import/commit",
        json={"csv_content": csv_data},
        headers=headers_a,
    )
    job = poll_job_until_terminal(client, res.json()["job_id"], headers_a)
    assert job["status"] == "COMPLETED"
    assert job["created_count"] == 1

    prod = (
        db.query(Product)
        .filter(Product.tenant_id == tenant_a, Product.name == "Simple Standalone Book")
        .one()
    )
    assert len(prod.options) == 0
    assert len(prod.variants) == 1
    assert prod.variants[0].sku == "BOOK-SOLO-01"
    assert len(prod.variants[0].option_values) == 0


def test_cross_product_sku_conflict_with_db_rejected(client, headers_a, tenant_a, db):
    # 1. Seed initial product with SKU-CHAIR-EXISTING
    init_csv = """product_name,type,category,sku,price
Ergonomic Chair,PRODUCT,seating,SKU-CHAIR-EXISTING,250.00
"""
    res1 = client.post(
        "/api/v1/catalog/import/commit",
        json={"csv_content": init_csv},
        headers=headers_a,
    )
    job1 = poll_job_until_terminal(client, res1.json()["job_id"], headers_a)
    assert job1["status"] == "COMPLETED"

    # 2. Dry run validation with different product name attempting to claim the same SKU
    conflict_csv = """product_name,type,category,sku,price
Executive Desk,PRODUCT,seating,SKU-CHAIR-EXISTING,500.00
"""
    val_res = client.post(
        "/api/v1/catalog/import/validate",
        json={"csv_content": conflict_csv},
        headers=headers_a,
    )
    assert val_res.status_code == 200
    report = val_res.json()
    assert report["valid_count"] == 0
    assert report["error_count"] == 1
    assert any("already belongs to existing product 'Ergonomic Chair'" in err for err in report["row_results"][0]["errors"])

    # 3. Commit with skip_invalid=False must fail
    res2 = client.post(
        "/api/v1/catalog/import/commit",
        json={"csv_content": conflict_csv, "skip_invalid": False},
        headers=headers_a,
    )
    job2 = poll_job_until_terminal(client, res2.json()["job_id"], headers_a)
    assert job2["status"] == "FAILED"

    # 4. Verify original product was NOT renamed and no "Executive Desk" exists
    chair_prod = (
        db.query(Product)
        .filter(Product.tenant_id == tenant_a, Product.name == "Ergonomic Chair")
        .first()
    )
    assert chair_prod is not None
    desk_prod = (
        db.query(Product)
        .filter(Product.tenant_id == tenant_a, Product.name == "Executive Desk")
        .first()
    )
    assert desk_prod is None


def test_incremental_variant_import_preserves_existing_options(client, headers_a, tenant_a, db):
    # 1. Import product with first variant (Size: S)
    csv_1 = """product_name,type,category,option_size,sku,price,location,qty
Classic Polo,PRODUCT,apparel,S,POLO-S,35.00,Main Warehouse,20
"""
    res1 = client.post(
        "/api/v1/catalog/import/commit",
        json={"csv_content": csv_1},
        headers=headers_a,
    )
    job1 = poll_job_until_terminal(client, res1.json()["job_id"], headers_a)
    assert job1["status"] == "COMPLETED"

    # 2. Import second variant (Size: M) for same product in separate batch
    csv_2 = """product_name,type,category,option_size,sku,price,location,qty
Classic Polo,PRODUCT,apparel,M,POLO-M,35.00,Main Warehouse,25
"""
    res2 = client.post(
        "/api/v1/catalog/import/commit",
        json={"csv_content": csv_2},
        headers=headers_a,
    )
    job2 = poll_job_until_terminal(client, res2.json()["job_id"], headers_a)
    assert job2["status"] == "COMPLETED"

    # 3. Verify product has both option values S and M
    prod = (
        db.query(Product)
        .filter(Product.tenant_id == tenant_a, Product.name == "Classic Polo")
        .one()
    )
    size_opt = next(o for o in prod.options if o.name == "Size")
    vals = {v.value for v in size_opt.values}
    assert vals == {"S", "M"}

    # 4. Crucial: verify variant POLO-S still has its option value 'S' and POLO-M has 'M'
    v_s = db.query(Variant).filter(Variant.tenant_id == tenant_a, Variant.sku == "POLO-S").one()
    v_m = db.query(Variant).filter(Variant.tenant_id == tenant_a, Variant.sku == "POLO-M").one()

    assert len(v_s.option_values) == 1
    assert v_s.option_values[0].value == "S"
    assert len(v_m.option_values) == 1
    assert v_m.option_values[0].value == "M"


def test_conflicting_sku_attributes_in_csv_rejected(client, headers_a):
    csv_conflicts = """product_name,type,category,option_size,sku,price,currency,location,qty
Tee,PRODUCT,apparel,S,TEE-CONFLICT-01,20.00,USD,Warehouse 1,10
Tee,PRODUCT,apparel,L,TEE-CONFLICT-01,25.00,EUR,Warehouse 2,15
"""
    res = client.post(
        "/api/v1/catalog/import/validate",
        json={"csv_content": csv_conflicts},
        headers=headers_a,
    )
    assert res.status_code == 200
    report = res.json()
    assert report["valid_count"] == 1
    assert report["error_count"] == 1
    row2_errors = report["row_results"][1]["errors"]
    assert any("Conflicting price" in e for e in row2_errors)
    assert any("Conflicting currency" in e for e in row2_errors)
    assert any("Conflicting option 'size'" in e for e in row2_errors)


def test_duplicate_sku_location_in_csv_rejected(client, headers_a):
    dup_loc_csv = """product_name,type,category,sku,price,location,qty
Storage Box,PRODUCT,storage,BOX-100,15.00,Main Hub,10
Storage Box,PRODUCT,storage,BOX-100,15.00,Main Hub,20
"""
    res = client.post(
        "/api/v1/catalog/import/validate",
        json={"csv_content": dup_loc_csv},
        headers=headers_a,
    )
    assert res.status_code == 200
    report = res.json()
    assert report["valid_count"] == 1
    assert report["error_count"] == 1
    assert any("Duplicate (sku, location) combination" in e for e in report["row_results"][1]["errors"])


def test_conflicting_product_type_and_category_rejected(client, headers_a):
    bad_prod_csv = """product_name,type,category,sku,price
Multi Identity,PRODUCT,electronics,ID-01,99.00
Multi Identity,SERVICE,consulting,ID-02,99.00
"""
    res = client.post(
        "/api/v1/catalog/import/validate",
        json={"csv_content": bad_prod_csv},
        headers=headers_a,
    )
    assert res.status_code == 200
    report = res.json()
    assert report["valid_count"] == 1
    assert report["error_count"] == 1
    row2_errors = report["row_results"][1]["errors"]
    assert any("Conflicting type" in e for e in row2_errors)
    assert any("Conflicting category" in e for e in row2_errors)


def test_reorder_at_validation(client, headers_a):
    csv_reorder = """product_name,type,category,sku,price,reorder_at
Item Neg,PRODUCT,hardware,ITEM-NEG,10.00,-3
Item Bad,PRODUCT,hardware,ITEM-BAD,10.00,abc
"""
    res = client.post(
        "/api/v1/catalog/import/validate",
        json={"csv_content": csv_reorder},
        headers=headers_a,
    )
    assert res.status_code == 200
    report = res.json()
    assert report["valid_count"] == 0
    assert report["error_count"] == 2
    assert any("reorder_at must be >= 0" in e for e in report["row_results"][0]["errors"])
    assert any("Invalid reorder_at value" in e for e in report["row_results"][1]["errors"])


def test_reserved_stock_lower_bound_validation(client, headers_a, tenant_a, db):
    # 1. Seed product, location, stock=10
    csv_stock = """product_name,type,category,sku,price,location,qty
Reserved Widget,PRODUCT,hardware,WIDGET-RES-01,40.00,Depot Alpha,10
"""
    res = client.post(
        "/api/v1/catalog/import/commit",
        json={"csv_content": csv_stock},
        headers=headers_a,
    )
    job = poll_job_until_terminal(client, res.json()["job_id"], headers_a)
    assert job["status"] == "COMPLETED"

    # 2. Reserve 6 units
    res_reserve = client.post(
        "/api/v1/catalog/inventory/reserve",
        json={"sku": "WIDGET-RES-01", "qty": 6},
        headers=headers_a,
    )
    assert res_reserve.status_code == 200

    # 3. Try to import setting qty=4 (less than reserved 6)
    csv_bad_qty = """product_name,type,category,sku,price,location,qty
Reserved Widget,PRODUCT,hardware,WIDGET-RES-01,40.00,Depot Alpha,4
"""
    val_res = client.post(
        "/api/v1/catalog/import/validate",
        json={"csv_content": csv_bad_qty},
        headers=headers_a,
    )
    assert val_res.status_code == 200
    report = val_res.json()
    assert report["valid_count"] == 0
    assert report["error_count"] == 1
    assert any("Cannot set qty_on_hand (4) less than reserved (6)" in e for e in report["row_results"][0]["errors"])

