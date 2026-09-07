import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
# pyrefly: ignore [missing-import]
import py_eureka_client.eureka_client as eureka_client
from module_1_document_processing.composio_connector.webhook_handler import router as webhook_router, queue_worker
from module_1_document_processing.composio_connector.connector_routes import router as connector_router, gmail_sync_manager, gdrive_sync_manager, calendar_sync_manager

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
    # Start Staging Queue Worker
    await queue_worker.start()

    # Start Background Gmail, GDrive & Calendar Auto-Sync Schedulers
    await gmail_sync_manager.start_scheduler()
    await gdrive_sync_manager.start_scheduler()
    await calendar_sync_manager.start_scheduler()


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
    await calendar_sync_manager.stop_scheduler()
    await gdrive_sync_manager.stop_scheduler()
    await gmail_sync_manager.stop_scheduler()
    await queue_worker.stop()


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

@app.get("/health")
def health_check():
    return {"status": "UP"}
