"""Where generated files go, as decided for this build: the rep's Google Drive; if Drive isn't
connected or is full, the workspace knowledge base. Both can be undone (Drive: move to the
trash; knowledge base: delete the document the agent added).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from app.core.context import AgentContext
from app.platform.composio_client import ConnectorClient, ConnectorError, ConnectorOutcomeUnknown
from app.platform.data_pipeline import DataPipelineClient, DataPipelineError
from app.tools.adapters.common import as_dict, first_dict, pipeline_failure, pipeline_write_failure, run_connector_undo
from app.tools.types import ToolFailed, ToolInputError, ToolOutcomeUnknown

logger = logging.getLogger(__name__)

Destination = Literal["google_drive", "knowledge_base"]
DESTINATION_LABELS: dict[str, str] = {"google_drive": "Google Drive", "knowledge_base": "the workspace knowledge base"}

_QUOTA_MARKERS = ("storagequotaexceeded", "quota exceeded", "storage quota", "insufficient storage", "drive is full")
_GONE_MARKERS = ("not found", "notfound", "404", "does not exist", "already", "trashed")


@dataclass(frozen=True, slots=True)
class StoredFile:
    destination: Destination
    file_id: str
    name: str
    link: str | None
    note: str | None = None  # why it went to the knowledge base instead of Drive

    def to_dict(self) -> dict[str, Any]:
        return {
            "saved_to": self.destination,
            "file_id": self.file_id,
            "file_name": self.name,
            "link": self.link,
            "note": self.note,
        }


class DriveFull(Exception):
    pass


class DocumentStore:
    def __init__(
        self,
        *,
        connector: ConnectorClient | None,
        data_pipeline: DataPipelineClient,
        vault_link: str,
        max_bytes: int,
    ) -> None:
        self._connector = connector
        self._pipeline = data_pipeline
        self._vault_link = vault_link.rstrip("/")
        self._max_bytes = max_bytes

    async def planned_destination(self, ctx: AgentContext) -> Destination:
        """Where a file would go now (for approval previews; Drive's free space is checked on save)."""
        return "google_drive" if await self._drive_connected(ctx.user_id) else "knowledge_base"

    async def save(self, ctx: AgentContext, *, filename: str, content: bytes, mimetype: str) -> StoredFile:
        if len(content) > self._max_bytes:
            raise ToolInputError(
                f"the document is {len(content) // 1024} KB, over the {self._max_bytes // 1024} KB limit; make it shorter"
            )
        if not await self._drive_connected(ctx.user_id):
            note = "Google Drive isn't connected, so it was saved to the workspace knowledge base"
            return await self._to_knowledge_base(ctx, filename=filename, content=content, mimetype=mimetype, note=note)
        try:
            return await self._to_drive(ctx, filename=filename, content=content, mimetype=mimetype)
        except DriveFull:
            note = "Google Drive is full, so it was saved to the workspace knowledge base"
            return await self._to_knowledge_base(ctx, filename=filename, content=content, mimetype=mimetype, note=note)

    async def remove(self, ctx: AgentContext, *, destination: str, file_id: str, name: str) -> str:
        """Undo a save. Safe to repeat: a file that is already gone counts as removed."""
        if destination == "google_drive":
            if self._connector is None:
                raise ToolFailed("Google Drive is not available to this service")
            try:
                await run_connector_undo(
                    self._connector, user_id=ctx.user_id, slug="GOOGLEDRIVE_TRASH_FILE", arguments={"file_id": file_id}
                )
            except ToolFailed as exc:
                if not exc.retryable and any(marker in str(exc).lower() for marker in _GONE_MARKERS):
                    return f"'{name}' was already gone from Google Drive"
                raise
            return f"'{name}' moved to the Google Drive trash"
        try:
            removed = await self._pipeline.delete_document(ctx.user_id, ctx.tenant_id, file_id)
        except DataPipelineError as exc:
            raise pipeline_failure(exc) from exc
        return f"'{name}' deleted from the knowledge base" if removed else f"'{name}' was already gone from the knowledge base"

    # ------------------------------------------------------------------ destinations
    async def _drive_connected(self, user_id: UUID) -> bool:
        if self._connector is None:
            return False
        try:
            return await self._connector.has_active_connection(user_id, "googledrive")
        except ConnectorError as exc:
            raise ToolFailed(str(exc), retryable=True) from exc

    async def _to_drive(self, ctx: AgentContext, *, filename: str, content: bytes, mimetype: str) -> StoredFile:
        assert self._connector is not None
        if await self._drive_is_full(ctx.user_id, len(content)):
            raise DriveFull()
        staged = await self._stage(filename, content, mimetype)
        try:
            data = await self._connector.execute(
                user_id=ctx.user_id, slug="GOOGLEDRIVE_UPLOAD_FILE", arguments={"file_to_upload": staged}
            )
        except ConnectorOutcomeUnknown as exc:
            raise ToolOutcomeUnknown(f"Google Drive gave no answer, so '{filename}' may have been saved: {exc}") from exc
        except ConnectorError as exc:
            if any(marker in str(exc).lower() for marker in _QUOTA_MARKERS):
                raise DriveFull() from exc
            raise ToolFailed(f"could not save '{filename}' to Google Drive: {exc}") from exc
        file = first_dict(data, "response_data", "file", "data")
        file_id = str(file.get("id") or "")
        if not file_id:
            # Saved, but without an id it can't be linked or undone: report it rather than guess.
            raise ToolOutcomeUnknown(f"Google Drive accepted '{filename}' but returned no file id; check the Drive root folder")
        link = file.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"
        return StoredFile("google_drive", file_id, str(file.get("name") or filename), str(link))

    async def _stage(self, filename: str, content: bytes, mimetype: str) -> dict[str, str]:
        assert self._connector is not None
        try:
            return await self._connector.stage_file(
                slug="GOOGLEDRIVE_UPLOAD_FILE", filename=filename, content=content, mimetype=mimetype
            )
        except ConnectorError as exc:
            raise ToolFailed(str(exc), retryable=True) from exc

    async def _drive_is_full(self, user_id: UUID, size: int) -> bool:
        assert self._connector is not None
        try:
            data = await self._connector.execute(
                user_id=user_id, slug="GOOGLEDRIVE_GET_ABOUT", arguments={"fields": "storageQuota"}
            )
        except ConnectorError:
            logger.info("could not read Google Drive's storage quota; trying the upload anyway", exc_info=True)
            return False
        quota = as_dict(first_dict(data, "response_data", "data").get("storageQuota"))
        try:
            limit = int(quota["limit"])
            usage = int(quota.get("usage") or 0)
        except (KeyError, TypeError, ValueError):
            return False  # no limit reported: unlimited storage
        return usage + size > limit

    async def _to_knowledge_base(
        self, ctx: AgentContext, *, filename: str, content: bytes, mimetype: str, note: str
    ) -> StoredFile:
        try:
            document = await self._pipeline.upload_document(
                ctx.user_id, ctx.tenant_id, filename=filename, content=content, mimetype=mimetype
            )
        except DataPipelineError as exc:
            if exc.status == 403:
                raise ToolFailed(
                    f"{note.split(',')[0]}, and you can't add documents to this workspace's knowledge base: {exc}"
                ) from exc
            raise pipeline_write_failure(exc) from exc
        doc_id = str(document["doc_id"])
        return StoredFile("knowledge_base", doc_id, str(document.get("name") or filename), f"{self._vault_link}?doc={doc_id}", note)
