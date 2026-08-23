import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
# pyrefly: ignore [missing-import]
import py_eureka_client.eureka_client as eureka_client
from connectors.handlers.webhook_handler import router as webhook_router

EUREKA_SERVER = os.environ.get("EUREKA_SERVER")
APP_NAME = os.environ.get("DATA_PIPELINE_SERVICE_NAME")
INSTANCE_PORT = int(os.environ.get("DATA_PIPELINE_PORT"))
INSTANCE_HOST = os.environ.get("DATA_PIPELINE_HOSTNAME")

@asynccontextmanager
async def lifespan(app: FastAPI):
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

@app.get("/health")
def health_check():
    return {"status": "UP"}
