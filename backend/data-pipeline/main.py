import os
from dotenv import load_dotenv

# Automatically load backend/.env
_env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
if os.path.exists(_env_path):
    load_dotenv(_env_path)

from contextlib import asynccontextmanager
from fastapi import FastAPI
# pyrefly: ignore [missing-import]
import py_eureka_client.eureka_client as eureka_client
from module_1_document_processing.composio_connector.webhook_handler import router as webhook_router, queue_worker
from module_1_document_processing.composio_connector.connector_routes import (
    router as connector_router,
    gmail_sync_manager,
    gdrive_sync_manager,
    calendar_sync_manager,
    slack_sync_manager,
    notion_sync_manager,
)
from module_1_document_processing.knowledge_vault_routes import router as knowledge_vault_router
from module_1_document_processing.knowledge_vault_routes import process_document_job
from module_1_document_processing.pipeline.job_payloads import JOB_DOCUMENT_INGEST
from module_1_document_processing.pipeline.queue_routes import router as queue_router
from module_1_document_processing.del_acl_and_reconc.reconciliation_routes import router as reconciliation_router
from module_1_document_processing.del_acl_and_reconc.reconciliation_scheduler import reconciliation_scheduler
from module_2_memory_gatekeeper.gatekeeper_routes import router as gatekeeper_router
from catalog.routes import router as catalog_router
from catalog.database import init_catalog_db
from catalog.csv_importer import catalog_import_worker
from rag.database import init_rag_db
from rag.state import set_persistence_available

raw_eureka = os.environ.get("EUREKA_SERVER", "http://eureka-service:8761/eureka/")
if "localhost" in raw_eureka or "127.0.0.1" in raw_eureka:
    EUREKA_SERVER = "http://eureka-service:8761/eureka/"
else:
    EUREKA_SERVER = raw_eureka

APP_NAME = os.environ.get("DATA_PIPELINE_SERVICE_NAME", "data-pipeline")
INSTANCE_PORT = int(os.environ.get("DATA_PIPELINE_PORT", "8000"))
INSTANCE_HOST = os.environ.get("DATA_PIPELINE_HOSTNAME", "data-pipeline")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize RAG pipeline persistence (canonical lineage, chunk hashes, checkpoints).
    # Runs before any worker starts so the stores resolve to Postgres, not memory.
    try:
        rag_ready = init_rag_db()
        set_persistence_available(rag_ready)
        print(
            "RAG persistence enabled (Postgres)."
            if rag_ready
            else "RAG persistence unavailable - falling back to in-memory stores."
        )
    except Exception as e:
        set_persistence_available(False)
        print(f"RAG persistence initialization error (using in-memory stores): {e}")

    # Uploads, URL ingests and reindexes share the connector queue, so every
    # ingestion path gets the same durability, retries and dead-lettering.
    queue_worker.register_handler(JOB_DOCUMENT_INGEST, process_document_job)

    # Start Staging Queue Worker
    await queue_worker.start()

    # Start Catalog CSV Import Worker
    await catalog_import_worker.start()

    # Start Background Gmail, GDrive, Calendar, Slack & Notion Auto-Sync Schedulers
    await gmail_sync_manager.start_scheduler()
    await gdrive_sync_manager.start_scheduler()
    await calendar_sync_manager.start_scheduler()
    await slack_sync_manager.start_scheduler()
    await notion_sync_manager.start_scheduler()

    # Reconciliation catches deletions and ACL drift that providers never emit
    # as events. Only sources that can be listed exhaustively are swept.
    reconciliation_scheduler.providers = {
        "gdrive": gdrive_sync_manager,
        "notion": notion_sync_manager,
        # Keyed by the stored `source` value, not the connector's colloquial name.
        "google_calendar": calendar_sync_manager,
    }
    await reconciliation_scheduler.start_scheduler()


    # Initialize catalog database and schema migrations
    try:
        init_catalog_db()
        print("Catalog database and schema initialized successfully.")
    except Exception as e:
        print(f"Catalog database initialization error: {e}")

    # Register with Eureka
    print(f"Registering {APP_NAME} with Eureka server at {EUREKA_SERVER}...")
    try:
        if hasattr(eureka_client, "init_async"):
            await eureka_client.init_async(
                eureka_server=EUREKA_SERVER,
                app_name=APP_NAME,
                instance_port=INSTANCE_PORT,
                instance_host=INSTANCE_HOST,
            )
        else:
            eureka_client.init(
                eureka_server=EUREKA_SERVER,
                app_name=APP_NAME,
                instance_port=INSTANCE_PORT,
                instance_host=INSTANCE_HOST,
            )
        print(f"Successfully registered {APP_NAME} with Eureka!")
    except Exception as e:
        print(f"Eureka registration error: {e}")

    yield

    # Stop Schedulers & Queue Worker & Deregister from Eureka
    await reconciliation_scheduler.stop_scheduler()
    await notion_sync_manager.stop_scheduler()
    await slack_sync_manager.stop_scheduler()
    await calendar_sync_manager.stop_scheduler()
    await gdrive_sync_manager.stop_scheduler()
    await gmail_sync_manager.stop_scheduler()
    await queue_worker.stop()
    await catalog_import_worker.stop()


    try:
        if hasattr(eureka_client, "stop_async"):
            await eureka_client.stop_async()
        elif hasattr(eureka_client, "stop"):
            eureka_client.stop()
        print(f"Deregistered {APP_NAME} from Eureka.")
    except Exception as e:
        print(f"Eureka deregistration error: {e}")

app = FastAPI(title="Role-Sync Data Pipeline Service", lifespan=lifespan)

app.include_router(webhook_router, prefix="/api/v1")
app.include_router(connector_router, prefix="/api/v1")
app.include_router(knowledge_vault_router, prefix="/api/v1")
app.include_router(knowledge_vault_router, prefix="/api/v1/data-pipeline")
app.include_router(reconciliation_router, prefix="/api/v1")
app.include_router(reconciliation_router, prefix="/api/v1/data-pipeline")
app.include_router(queue_router, prefix="/api/v1")
app.include_router(queue_router, prefix="/api/v1/data-pipeline")
app.include_router(gatekeeper_router, prefix="/api/v1")
app.include_router(gatekeeper_router, prefix="/api/v1/data-pipeline")
app.include_router(catalog_router, prefix="/api/v1/catalog")
app.include_router(catalog_router, prefix="/api/v1/data-pipeline/catalog")

@app.get("/health")
def health_check():
    return {"status": "UP"}
