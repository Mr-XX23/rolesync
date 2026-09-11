"""Changing the catalog needs a workspace role that can write: viewers read the catalog but
can't change it (403, as in the knowledge vault); owners, admins and members can.

Runs the real routes with workspace-service faked. The catalog service and the CSV import
worker are replaced by a stub whose every method raises ``Reached(<method name>)``, which the
test app answers with ``{"reached": <method name>}``: a request that gets past the access
checks shows where it got to, and no database is needed.
"""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from catalog import routes
from module_1_document_processing import workspace_access
from module_1_document_processing.workspace_access import MembershipDirectory

WORKSPACE = str(uuid.uuid4())
OTHER_WORKSPACE = str(uuid.uuid4())
OWNER, ADMIN, MEMBER, VIEWER, OUTSIDER = (str(uuid.uuid4()) for _ in range(5))
ROLES = {
    OWNER: {WORKSPACE: "OWNER"},
    ADMIN: {WORKSPACE: "ADMIN"},
    MEMBER: {WORKSPACE: "MEMBER"},
    VIEWER: {WORKSPACE: "VIEWER", OTHER_WORKSPACE: "OWNER"},
    OUTSIDER: {OTHER_WORKSPACE: "OWNER"},
}

PRODUCT, VARIANT, LOCATION, OTHER_LOCATION, RESERVATION, JOB = (str(uuid.uuid4()) for _ in range(6))
STOCK = {"variant_id": VARIANT, "location_id": LOCATION, "qty": 5}
CSV = {"csv_content": "product_name,type,category,sku,price\nStudio Headphones,PRODUCT,audio,HP-01,149.99"}

# (method, route path, JSON body, the service or import-worker method the request should reach)
CHANGES = [
    ("POST", "/categories", {"key": "audio", "label": "Audio"}, "upsert_category"),
    ("POST", "/products", {"name": "Studio Headphones", "category": "audio"}, "upsert_product"),
    ("PUT", "/products/{product_id}", {"name": "Studio Headphones Pro"}, "upsert_product"),
    ("DELETE", "/products/{product_id}", None, "delete_product"),
    ("DELETE", "/products/{product_id}?permanent=true", None, "hard_delete_product"),
    ("PUT", "/products/{product_id}/options", {"options": []}, "set_options"),
    ("POST", "/products/{product_id}/variants", {"variants": [{"sku": "HP-01", "price": "149.99"}]}, "upsert_variants"),
    ("POST", "/locations", {"name": "Main Warehouse"}, "upsert_location"),
    ("PUT", "/locations/{location_id}", {"name": "Main Warehouse"}, "upsert_location"),
    ("DELETE", "/locations/{location_id}", None, "delete_location"),
    ("POST", "/inventory/set-stock", STOCK, "set_stock"),
    ("POST", "/inventory/batch-set-stock", {"items": [STOCK]}, "batch_set_stock"),
    ("POST", "/inventory/adjust-stock", {"variant_id": VARIANT, "location_id": LOCATION, "delta": -1}, "adjust_stock"),
    ("POST", "/inventory/reserve", {"sku": "HP-01", "qty": 1}, "reserve"),
    ("POST", "/inventory/release/{reservation_id}", None, "release"),
    ("POST", "/inventory/transfer", {"sku": "HP-01", "from_location_id": LOCATION, "to_location_id": OTHER_LOCATION, "qty": 1}, "transfer"),
    ("POST", "/import/commit", CSV, "create_job"),
]
READS = [
    ("GET", "/describe", None, "describe_catalog"),
    ("GET", "/categories", None, "list_categories"),
    ("GET", "/products", None, "list_products"),
    ("GET", "/products/{product_id}", None, "get_product"),
    ("GET", "/products/{product_id}/variant-grid", None, "generate_variant_grid"),
    ("GET", "/variants/{sku}", None, "get_variant"),
    ("GET", "/variants/{sku}/availability", None, "availability"),
    ("GET", "/variants/{sku}/check-availability", None, "check_availability"),
    ("GET", "/locations", None, "list_locations"),
    ("GET", "/inventory/availability", None, "batch_availability"),
    ("GET", "/import/jobs/{job_id}", None, "get_job"),
    # POSTs that don't change data
    ("POST", "/ai/semantic-search", {"query": "headphones for mixing"}, "semantic_search"),
    (
        "POST",
        "/ai/generate-findability",
        {
            "name": "Studio Headphones",
            "type": "PRODUCT",
            "category": "audio",
            "description": "Closed-back studio headphones with 50mm drivers for mixing and monitoring. " * 3,
        },
        "generate_findability",
    ),
    ("POST", "/validate-rows", [{"product_name": "Studio Headphones", "sku": "HP-01"}], "validate_rows"),
    ("POST", "/import/validate", CSV, "validate_rows"),
]


class Reached(Exception):
    pass


class _Stub:
    def __getattr__(self, name):
        def call(*args, **kwargs):
            raise Reached(name)

        return call


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        workspace_access, "directory", MembershipDirectory("http://workspace.test", fetch=lambda base, user, t: ROLES.get(user, {}))
    )
    monkeypatch.setattr(routes, "catalog_import_worker", _Stub())
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1/catalog")
    app.dependency_overrides[routes.get_service] = _Stub
    app.add_exception_handler(Reached, lambda request, exc: JSONResponse({"reached": str(exc)}))
    return TestClient(app)


def _send(client, user, method, path, body, workspace=WORKSPACE):
    url = "/api/v1/catalog" + path.format(product_id=PRODUCT, location_id=LOCATION, reservation_id=RESERVATION, job_id=JOB, sku="HP-01")
    return client.request(method, url, headers={"X-User-Id": user, "X-Tenant-Id": workspace}, json=body)


def test_viewers_cannot_change_the_catalog(client):
    for method, path, body, _ in CHANGES:
        refused = _send(client, VIEWER, method, path, body)
        assert refused.status_code == 403, (method, path, refused.text)
        assert refused.json()["detail"] == "Viewers can't make changes in this workspace"


def test_owners_admins_and_members_can_change_the_catalog(client):
    for user in (OWNER, ADMIN, MEMBER):
        for method, path, body, reaches in CHANGES:
            response = _send(client, user, method, path, body)
            assert response.json() == {"reached": reaches}, (ROLES[user][WORKSPACE], method, path, response.text)


def test_viewers_can_still_read_the_catalog(client):
    for method, path, body, reaches in READS:
        response = _send(client, VIEWER, method, path, body)
        assert response.json() == {"reached": reaches}, (method, path, response.text)


def test_the_role_that_counts_is_the_one_in_the_workspace_acted_in(client):
    method, path, body, reaches = CHANGES[0]
    # The viewer owns another workspace and can change that workspace's catalog.
    assert _send(client, VIEWER, method, path, body, workspace=OTHER_WORKSPACE).json() == {"reached": reaches}
    # Owning some other workspace doesn't make you a member of this one.
    refused = _send(client, OUTSIDER, method, path, body)
    assert (refused.status_code, refused.json()["detail"]) == (403, "You are not a member of this workspace")


def test_every_catalog_route_is_listed_as_a_change_or_a_read():
    """A new route fails here until it's added to CHANGES (writers only) or READS."""
    served = {(method, route.path) for route in routes.router.routes for method in route.methods}
    served.discard(("GET", "/import/template.csv"))  # static template, no workspace data
    assert served == {(method, path.split("?")[0]) for method, path, _, _ in CHANGES + READS}
