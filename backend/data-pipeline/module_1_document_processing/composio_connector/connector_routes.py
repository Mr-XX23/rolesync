from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from module_1_document_processing.composio_connector.connector_service import ConnectorService

router = APIRouter(tags=["Connectors"])
connector_service = ConnectorService()

class ConnectRequest(BaseModel):
    user_id: str = "usr_active"

@router.post("/connectors/{source}/connect")
def connect_connector(source: str, req: ConnectRequest):
    res = connector_service.connect_source(user_id=req.user_id, source=source)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res
