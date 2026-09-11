import uuid
from decimal import Decimal
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from catalog.database import init_catalog_db
from catalog.routes import router as catalog_router

# Test app with mounted catalog router
app = FastAPI()
app.include_router(catalog_router, prefix="/api/v1/catalog")


@pytest.fixture(scope="module", autouse=True)
def setup_catalog():
    init_catalog_db()


@pytest.fixture
def client():
    return TestClient(app)


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


def test_auth_validation(client):
    # 1. Missing auth headers
    res = client.get("/api/v1/catalog/categories")
    assert res.status_code == 401
    assert "tenant_id missing" in res.json()["detail"]

    # 2. Invalid UUID
    res = client.get("/api/v1/catalog/categories", headers={"X-Tenant-Id": "not-a-uuid"})
    assert res.status_code == 400
    assert "must be a valid UUID" in res.json()["detail"]

    # 3. Bearer JWT auth
    valid_uuid = str(uuid.uuid4())
    token = jwt.encode({"tenant_id": valid_uuid, "user_id": "jwt_user"}, "secret", algorithm="HS256")
    res = client.get("/api/v1/catalog/categories", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_full_catalog_and_inventory_lifecycle(client, headers_a, headers_b):
    # 1. Create Category
    cat_payload = {"key": "monitors", "label": "Computer Monitors"}
    res = client.post("/api/v1/catalog/categories", json=cat_payload, headers=headers_a)
    assert res.status_code == 201
    cat_data = res.json()
    assert cat_data["key"] == "monitors"

    # List Categories
    res = client.get("/api/v1/catalog/categories", headers=headers_a)
    assert res.status_code == 200
    assert any(c["key"] == "monitors" for c in res.json())

    # 2. Create Product
    prod_payload = {
        "name": "UltraWide Gaming Monitor",
        "category": "monitors",
        "type": "PRODUCT",
        "status": "ACTIVE",
        "description": "34-inch curved OLED monitor",
        "keywords": ["gaming", "ultrawide", "oled", "144hz"],
        "use_cases": ["gaming", "video editing"],
        "target_industries": ["entertainment", "creative"],
    }
    res = client.post("/api/v1/catalog/products", json=prod_payload, headers=headers_a)
    assert res.status_code == 201
    prod = res.json()
    product_id = prod["id"]
    assert prod["name"] == "UltraWide Gaming Monitor"

    # 3. Define Options
    options_payload = {
        "options": [
            {
                "name": "Resolution",
                "position": 0,
                "values": [
                    {"value": "1440p", "position": 0},
                    {"value": "4k", "position": 1},
                ],
            }
        ]
    }
    res = client.put(f"/api/v1/catalog/products/{product_id}/options", json=options_payload, headers=headers_a)
    assert res.status_code == 200
    options_resp = res.json()
    assert len(options_resp) == 1
    assert len(options_resp[0]["values"]) == 2
    val_1440p_id = options_resp[0]["values"][0]["id"]
    val_4k_id = options_resp[0]["values"][1]["id"]

    # 4. Generate Candidate Variant Grid (unpersisted)
    res = client.get(f"/api/v1/catalog/products/{product_id}/variant-grid", headers=headers_a)
    assert res.status_code == 200
    grid = res.json()
    assert len(grid["candidates"]) == 2

    # 5. Persist enabled variants
    variants_payload = {
        "variants": [
            {
                "sku": "MON-UW-1440P",
                "price": "699.99",
                "option_value_ids": [val_1440p_id],
            },
            {
                "sku": "MON-UW-4K",
                "price": "999.99",
                "option_value_ids": [val_4k_id],
            },
        ]
    }
    res = client.post(f"/api/v1/catalog/products/{product_id}/variants", json=variants_payload, headers=headers_a)
    assert res.status_code == 200
    variants = res.json()
    assert len(variants) == 2
    var_1440p = next(v for v in variants if v["sku"] == "MON-UW-1440P")

    # 6. Lookup Variant by SKU
    res = client.get("/api/v1/catalog/variants/MON-UW-1440P", headers=headers_a)
    assert res.status_code == 200
    assert res.json()["sku"] == "MON-UW-1440P"

    # 7. Create Locations
    loc1_res = client.post(
        "/api/v1/catalog/locations",
        json={"name": "Seattle Warehouse", "priority": 10, "sellable": True},
        headers=headers_a,
    )
    assert loc1_res.status_code == 201
    loc1_id = loc1_res.json()["id"]

    loc2_res = client.post(
        "/api/v1/catalog/locations",
        json={"name": "Austin Store", "priority": 20, "sellable": True},
        headers=headers_a,
    )
    assert loc2_res.status_code == 201
    loc2_id = loc2_res.json()["id"]

    # 8. Set Stock (via ledger)
    stock_payload = {
        "variant_id": var_1440p["id"],
        "location_id": loc1_id,
        "qty": 25,
        "reason": "RESTOCK",
    }
    res = client.post("/api/v1/catalog/inventory/set-stock", json=stock_payload, headers=headers_a)
    assert res.status_code == 200
    assert res.json()["qty_on_hand"] == 25
    assert res.json()["qty_available"] == 25

    # 9. Query Availability View
    res = client.get("/api/v1/catalog/variants/MON-UW-1440P/availability", headers=headers_a)
    assert res.status_code == 200
    avail = res.json()
    assert avail["total_available"] == 25
    assert len(avail["by_location"]) >= 1

    # 10. Reserve Stock
    reserve_payload = {
        "sku": "MON-UW-1440P",
        "qty": 5,
    }
    res = client.post("/api/v1/catalog/inventory/reserve", json=reserve_payload, headers=headers_a)
    assert res.status_code == 200
    reservation = res.json()
    assert reservation["allocated_qty"] == 5
    reservation_id = reservation["reservation_id"]

    # Verify availability dropped to 20
    res = client.get("/api/v1/catalog/variants/MON-UW-1440P/availability", headers=headers_a)
    assert res.json()["total_available"] == 20

    # 11. Release Reservation
    res = client.post(f"/api/v1/catalog/inventory/release/{reservation_id}", headers=headers_a)
    assert res.status_code == 200
    assert res.json()["released_qty"] == 5

    # Verify availability restored to 25
    res = client.get("/api/v1/catalog/variants/MON-UW-1440P/availability", headers=headers_a)
    assert res.json()["total_available"] == 25

    # 12. Transfer Stock from Seattle to Austin
    transfer_payload = {
        "sku": "MON-UW-1440P",
        "from_location_id": loc1_id,
        "to_location_id": loc2_id,
        "qty": 10,
    }
    res = client.post("/api/v1/catalog/inventory/transfer", json=transfer_payload, headers=headers_a)
    assert res.status_code == 200
    assert res.json()["qty"] == 10

    # Total availability still 25, split across locations
    res = client.get("/api/v1/catalog/variants/MON-UW-1440P/availability", headers=headers_a)
    assert res.json()["total_available"] == 25
    loc_breakdown = {loc["location_name"]: loc["qty_available"] for loc in res.json()["by_location"]}
    assert loc_breakdown["Seattle Warehouse"] == 15
    assert loc_breakdown["Austin Store"] == 10

    # 13. Soft Delete Product
    res = client.delete(f"/api/v1/catalog/products/{product_id}", headers=headers_a)
    assert res.status_code == 200
    assert res.json()["status"] == "RETIRED"

    # 13b. Permanent Hard Delete Product
    res_perm = client.delete(f"/api/v1/catalog/products/{product_id}?permanent=true", headers=headers_a)
    assert res_perm.status_code == 200
    assert res_perm.json()["status"] == "DELETED"
    # Ensure product is completely gone
    res_gone = client.get(f"/api/v1/catalog/products/{product_id}", headers=headers_a)
    assert res_gone.status_code == 404

    # 14. Cross-Tenant Isolation
    # Tenant B tries to access Tenant A's product -> 404
    res = client.get(f"/api/v1/catalog/products/{product_id}", headers=headers_b)
    assert res.status_code == 404

    # Tenant B tries to access Tenant A's variant -> 404
    res = client.get("/api/v1/catalog/variants/MON-UW-1440P", headers=headers_b)
    assert res.status_code == 404


def test_dry_run_validation_api(client, headers_a):
    # Setup category
    client.post(
        "/api/v1/catalog/categories",
        json={"key": "gadgets", "label": "Gadgets"},
        headers=headers_a,
    )

    rows = [
        {
            "product_name": "Smart Watch",
            "type": "PRODUCT",
            "category": "gadgets",
            "sku": "WATCH-01",
            "price": "199.99",
            "qty": 100,
        },
        {
            "product_name": "Broken Watch",
            "type": "INVALID_TYPE",
            "category": "missing_cat",
            "sku": "WATCH-ERR",
            "price": "-50.00",
        },
    ]

    res = client.post("/api/v1/catalog/validate-rows", json=rows, headers=headers_a)
    assert res.status_code == 200
    report = res.json()
    assert report["total_rows"] == 2
    assert report["valid_count"] == 1
    assert report["error_count"] == 1


def test_describe_and_check_availability_api(client, headers_a):
    # Test describe endpoint
    res = client.get("/api/v1/catalog/describe", headers=headers_a)
    assert res.status_code == 200
    data = res.json()
    assert "categories" in data
    assert "filterable_fields" in data
    assert "option_types" in data

    # Create category, product, variant, location, stock
    client.post("/api/v1/catalog/categories", json={"key": "audio", "label": "Audio"}, headers=headers_a)
    prod_res = client.post(
        "/api/v1/catalog/products",
        json={"name": "Studio Headphones", "category": "audio"},
        headers=headers_a,
    )
    p_id = prod_res.json()["id"]
    client.post(
        f"/api/v1/catalog/products/{p_id}/variants",
        json={"variants": [{"sku": "AUDIO-HP-01", "price": "149.99"}]},
        headers=headers_a,
    )
    loc_res = client.post(
        "/api/v1/catalog/locations",
        json={"name": "Audio Hub", "priority": 10, "sellable": True},
        headers=headers_a,
    )
    loc_id = loc_res.json()["id"]

    # Initial check availability: 0 stock
    res_chk0 = client.get("/api/v1/catalog/variants/AUDIO-HP-01/check-availability?qty=1", headers=headers_a)
    assert res_chk0.status_code == 200
    assert res_chk0.json()["can_fulfill"] is False

    # Fetch variant id
    var_res = client.get("/api/v1/catalog/variants/AUDIO-HP-01", headers=headers_a)
    var_id = var_res.json()["id"]

    # Set stock to 10
    client.post(
        "/api/v1/catalog/inventory/set-stock",
        json={"variant_id": var_id, "location_id": loc_id, "qty": 10},
        headers=headers_a,
    )

    # Check availability: can fulfill 5
    res_chk1 = client.get("/api/v1/catalog/variants/AUDIO-HP-01/check-availability?qty=5", headers=headers_a)
    assert res_chk1.status_code == 200
    assert res_chk1.json()["can_fulfill"] is True
    assert res_chk1.json()["total_available"] == 10

    # Check availability: cannot fulfill 15
    res_chk2 = client.get("/api/v1/catalog/variants/AUDIO-HP-01/check-availability?qty=15", headers=headers_a)
    assert res_chk2.status_code == 200
    assert res_chk2.json()["can_fulfill"] is False


def test_update_product_api(client, headers_a):
    client.post("/api/v1/catalog/categories", json={"key": "tablets", "label": "Tablets"}, headers=headers_a)
    p_res = client.post(
        "/api/v1/catalog/products",
        json={"name": "Pro Tablet 10", "category": "tablets", "description": "Original description"},
        headers=headers_a,
    )
    p_id = p_res.json()["id"]
    assert p_res.json()["version"] == 1

    # PUT update
    put_res = client.put(
        f"/api/v1/catalog/products/{p_id}",
        json={"name": "Pro Tablet 10 Max", "description": "Updated description"},
        headers=headers_a,
    )
    assert put_res.status_code == 200
    assert put_res.json()["name"] == "Pro Tablet 10 Max"
    assert put_res.json()["description"] == "Updated description"
    assert put_res.json()["version"] == 2


def test_double_release_api_rejection(client, headers_a):
    client.post("/api/v1/catalog/categories", json={"key": "keyboards", "label": "Keyboards"}, headers=headers_a)
    p = client.post(
        "/api/v1/catalog/products",
        json={"name": "Mech Keyboard", "category": "keyboards"},
        headers=headers_a,
    ).json()
    client.post(
        f"/api/v1/catalog/products/{p['id']}/variants",
        json={"variants": [{"sku": "KB-MECH-01", "price": "99.99"}]},
        headers=headers_a,
    )
    var = client.get("/api/v1/catalog/variants/KB-MECH-01", headers=headers_a).json()
    loc = client.post(
        "/api/v1/catalog/locations",
        json={"name": "KB Warehouse", "priority": 10, "sellable": True},
        headers=headers_a,
    ).json()
    client.post(
        "/api/v1/catalog/inventory/set-stock",
        json={"variant_id": var["id"], "location_id": loc["id"], "qty": 10},
        headers=headers_a,
    )

    # Reserve 3
    res_res = client.post(
        "/api/v1/catalog/inventory/reserve",
        json={"sku": "KB-MECH-01", "qty": 3},
        headers=headers_a,
    ).json()
    r_id = res_res["reservation_id"]

    # First release -> 200
    rel1 = client.post(f"/api/v1/catalog/inventory/release/{r_id}", headers=headers_a)
    assert rel1.status_code == 200
    assert rel1.json()["released_qty"] == 3

    # Second release -> 400 Bad Request
    rel2 = client.post(f"/api/v1/catalog/inventory/release/{r_id}", headers=headers_a)
    assert rel2.status_code == 400
    assert "already been released" in rel2.json()["detail"]


def test_product_input_thresholds_and_security(client, headers_a):
    client.post("/api/v1/catalog/categories", json={"key": "audio", "label": "Audio"}, headers=headers_a)

    # 1. Product Name < 3 chars rejected
    res_short = client.post(
        "/api/v1/catalog/products",
        json={"name": "AB", "category": "audio", "type": "PRODUCT"},
        headers=headers_a,
    )
    assert res_short.status_code == 422

    # 2. SQL injection pattern in name rejected
    res_sqli_name = client.post(
        "/api/v1/catalog/products",
        json={"name": "Headphones'; DROP TABLE products;--", "category": "audio", "type": "PRODUCT"},
        headers=headers_a,
    )
    assert res_sqli_name.status_code == 422
    assert "SQL injection" in str(res_sqli_name.json())

    # 3. SQL injection pattern in description rejected
    res_sqli_desc = client.post(
        "/api/v1/catalog/products",
        json={
            "name": "Studio Headphones",
            "category": "audio",
            "type": "PRODUCT",
            "description": "Safe prefix UNION SELECT * FROM users--",
        },
        headers=headers_a,
    )
    assert res_sqli_desc.status_code == 422
    assert "SQL injection" in str(res_sqli_desc.json())

    # 4. AI Findability - Description < 200 chars rejected
    res_ai_short_desc = client.post(
        "/api/v1/catalog/ai/generate-findability",
        json={
            "name": "Studio Headphones Pro",
            "type": "PRODUCT",
            "category": "audio",
            "description": "This is too short.",
        },
        headers=headers_a,
    )
    assert res_ai_short_desc.status_code == 422
    assert "200 characters" in str(res_ai_short_desc.json())

    # 5. AI Findability - Missing Category rejected
    res_ai_no_cat = client.post(
        "/api/v1/catalog/ai/generate-findability",
        json={
            "name": "Studio Headphones Pro",
            "type": "PRODUCT",
            "category": "",
            "description": "A" * 250,
        },
        headers=headers_a,
    )
    assert res_ai_no_cat.status_code == 422

    # 6. AI Findability - Valid input (>= 200 chars, valid name, valid category) accepted
    res_ai_valid = client.post(
        "/api/v1/catalog/ai/generate-findability",
        json={
            "name": "Studio Headphones Pro",
            "type": "PRODUCT",
            "category": "audio",
            "description": "High-fidelity professional closed-back headphones engineered for studio monitoring, mixing, and critical listening. Features 50mm neodymium drivers delivering wide frequency response from 10Hz to 35kHz with premium memory foam earcups.",
        },
        headers=headers_a,
    )
    assert res_ai_valid.status_code == 200
    body = res_ai_valid.json()
    assert len(body["keywords"]) > 0
    assert len(body["use_cases"]) > 0
    assert body["ideal_customer_profile"] is not None


def test_batch_endpoints_api(client, headers_a):
    # 1. Setup category & product & variants
    client.post(
        "/api/v1/catalog/categories",
        json={"key": "networking", "label": "Networking"},
        headers=headers_a,
    )
    prod_res = client.post(
        "/api/v1/catalog/products",
        json={
            "name": "Gigabit Switch Pro",
            "category": "networking",
            "type": "PRODUCT",
        },
        headers=headers_a,
    )
    p_id = prod_res.json()["id"]

    var_res = client.post(
        f"/api/v1/catalog/products/{p_id}/variants",
        json={
            "variants": [
                {"sku": "SW-8P", "price": 49.99},
                {"sku": "SW-16P", "price": 99.99},
            ]
        },
        headers=headers_a,
    )
    v1_id = var_res.json()[0]["id"]
    v2_id = var_res.json()[1]["id"]

    loc_res = client.post(
        "/api/v1/catalog/locations",
        json={"name": "Data Center A", "priority": 10},
        headers=headers_a,
    )
    loc_id = loc_res.json()["id"]

    # 2. Test batch set stock
    batch_stock_res = client.post(
        "/api/v1/catalog/inventory/batch-set-stock",
        json={
            "items": [
                {"variant_id": v1_id, "location_id": loc_id, "qty": 30, "reason": "RESTOCK"},
                {"variant_id": v2_id, "location_id": loc_id, "qty": 50, "reason": "RESTOCK"},
            ]
        },
        headers=headers_a,
    )
    assert batch_stock_res.status_code == 200
    assert len(batch_stock_res.json()) == 2
    assert batch_stock_res.json()[0]["qty_on_hand"] == 30
    assert batch_stock_res.json()[1]["qty_on_hand"] == 50

    # 3. Test batch availability
    avail_res = client.get(
        "/api/v1/catalog/inventory/availability",
        params={"skus": ["SW-8P", "SW-16P"]},
        headers=headers_a,
    )
    assert avail_res.status_code == 200
    data = avail_res.json()
    assert "SW-8P" in data
    assert "SW-16P" in data
    assert data["SW-8P"]["total_available"] == 30
    assert data["SW-16P"]["total_available"] == 50


def test_semantic_search_api(client, headers_a):
    # Setup a product with keywords and use cases
    client.post(
        "/api/v1/catalog/categories",
        json={"key": "furniture", "label": "Furniture"},
        headers=headers_a,
    )
    prod_res = client.post(
        "/api/v1/catalog/products",
        json={
            "name": "Ergonomic Lumbar Office Chair",
            "category": "furniture",
            "type": "PRODUCT",
            "description": "Premium mesh high back chair with adjustable lumbar support to eliminate back pain.",
            "keywords": ["ergonomic", "lumbar support", "desk chair", "back pain"],
            "use_cases": ["Desk work for 8+ hour shifts", "Relief for back fatigue"],
            "value_proposition": "Reduces lumbar strain and boosts focus during long workdays.",
        },
        headers=headers_a,
    )
    assert prod_res.status_code == 201
    prod_id = prod_res.json()["id"]

    # Test semantic search with conversational query
    search_res = client.post(
        "/api/v1/catalog/ai/semantic-search",
        json={"query": "chair for back pain", "limit": 10},
        headers=headers_a,
    )
    assert search_res.status_code == 200
    res_data = search_res.json()
    assert res_data["query"] == "chair for back pain"
    assert len(res_data["results"]) > 0
    # First result should match our chair
    assert res_data["results"][0]["product_id"] == prod_id
    assert res_data["results"][0]["score"] > 0
    assert len(res_data["results"][0]["matched_terms"]) > 0



