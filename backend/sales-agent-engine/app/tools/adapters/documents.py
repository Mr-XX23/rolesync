"""Document generation: ``generate_document`` renders a document the agent describes (docx,
pptx, xlsx, pdf or md) and saves it to the rep's Google Drive, or the workspace knowledge
base when Drive isn't connected or is full. Undo moves the file to the Drive trash, or
deletes it from the knowledge base."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, StringConstraints, model_validator

from app.core.context import AgentContext
from app.tools.adapters.common import safe_filename
from app.tools.documents.render import FORMAT_LABELS, MIME_TYPES, Document, DocumentFormat, Section, Table, render
from app.tools.documents.storage import DESTINATION_LABELS, DocumentStore, StoredFile
from app.tools.registry import ToolDefinition
from app.tools.types import (
    SourceLink,
    ToolCategory,
    ToolInput,
    ToolInvocation,
    ToolKind,
    ToolOutput,
    ToolScope,
    UndoInvocation,
    UndoPlan,
)

Paragraph = Annotated[str, StringConstraints(min_length=1, max_length=4000)]
Bullet = Annotated[str, StringConstraints(min_length=1, max_length=600)]
ColumnName = Annotated[str, StringConstraints(min_length=1, max_length=100)]
CellValue = Annotated[str, StringConstraints(max_length=500)] | int | float | None


class TableArgs(ToolInput):
    columns: list[ColumnName] = Field(min_length=1, max_length=12)
    rows: list[list[CellValue]] = Field(default_factory=list, max_length=300)

    @model_validator(mode="after")
    def _rows_fit(self) -> TableArgs:
        for index, row in enumerate(self.rows):
            if len(row) > len(self.columns):
                raise ValueError(f"row {index + 1} has {len(row)} cells but the table has {len(self.columns)} columns")
        return self


class SectionArgs(ToolInput):
    heading: str | None = Field(default=None, max_length=200)
    paragraphs: list[Paragraph] = Field(default_factory=list, max_length=30)
    bullets: list[Bullet] = Field(default_factory=list, max_length=40)
    table: TableArgs | None = None


class GenerateDocumentArgs(ToolInput):
    title: str = Field(min_length=1, max_length=200)
    format: DocumentFormat = Field(
        description="docx (Word), pptx (slides: a title slide, then one or more per section), "
        "xlsx (a sheet per table, text on an Overview sheet), pdf, or md"
    )
    sections: list[SectionArgs] = Field(min_length=1, max_length=40)
    subtitle: str | None = Field(default=None, max_length=300)
    file_name: str | None = Field(default=None, max_length=120, description="Without extension; default: the title")


def to_document(args: GenerateDocumentArgs) -> Document:
    return Document(
        title=args.title,
        subtitle=args.subtitle,
        sections=tuple(
            Section(
                heading=section.heading,
                paragraphs=tuple(section.paragraphs),
                bullets=tuple(section.bullets),
                table=Table(columns=tuple(section.table.columns), rows=tuple(tuple(row) for row in section.table.rows))
                if section.table
                else None,
            )
            for section in args.sections
        ),
    )


def stored_file_result(stored: StoredFile, *, what: str) -> tuple[str, tuple[SourceLink, ...], UndoPlan]:
    """(summary suffix, links, undo plan) shared by every tool that saves a file."""
    where = DESTINATION_LABELS[stored.destination]
    summary = f"saved to {where}" + (f" ({stored.note.split(',')[0]})" if stored.note else "")
    links = (SourceLink(title=stored.name, url=stored.link),) if stored.link else ()
    if stored.destination == "google_drive":
        label = f"Move {what} '{stored.name}' to the Google Drive trash"
    else:
        label = f"Delete {what} '{stored.name}' from the knowledge base"
    undo = UndoPlan(args={"destination": stored.destination, "file_id": stored.file_id, "name": stored.name}, label=label)
    return summary, links, undo


def document_tools(store: DocumentStore, *, font_path: Path | None = None) -> list[ToolDefinition]:
    async def generate_document(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, GenerateDocumentArgs)
        content = await asyncio.to_thread(render, to_document(args), args.format, font_path=font_path)
        filename = safe_filename(args.file_name or args.title, args.format)
        stored = await store.save(invocation.ctx, filename=filename, content=content, mimetype=MIME_TYPES[args.format])
        where, links, undo = stored_file_result(stored, what="the document")
        return ToolOutput(
            data={**stored.to_dict(), "format": args.format, "size_bytes": len(content)},
            summary=f"{FORMAT_LABELS[args.format]} '{stored.name}' {where}",
            ref_id=stored.file_id,
            sources=links,
            undo=undo,
        )

    async def remove_document(invocation: UndoInvocation) -> str:
        args = invocation.args
        return await store.remove(
            invocation.ctx, destination=str(args["destination"]), file_id=str(args["file_id"]), name=str(args.get("name") or "document")
        )

    async def preview(ctx: AgentContext, args: ToolInput) -> dict[str, Any]:
        assert isinstance(args, GenerateDocumentArgs)
        destination = await store.planned_destination(ctx)
        return {
            "kind": "document",
            "title": args.title,
            "subtitle": args.subtitle,
            "format": args.format,
            "format_label": FORMAT_LABELS[args.format],
            "file_name": safe_filename(args.file_name or args.title, args.format),
            "destination": DESTINATION_LABELS[destination],
            "sections": [section.model_dump(mode="json") for section in args.sections],
        }

    return [
        ToolDefinition(
            name="generate_document",
            description=(
                "Create a document (Word, PowerPoint, Excel, PDF or Markdown) from a title and sections of paragraphs, "
                "bullets and tables, and save it to the rep's Google Drive (or the workspace knowledge base if Drive "
                "isn't available). The rep approves the content first. For price quotes use create_quote instead."
            ),
            kind=ToolKind.WRITE,
            scope=ToolScope.DOCUMENT,
            category=ToolCategory.ACTION,
            input_model=GenerateDocumentArgs,
            handler=generate_document,
            timeout_seconds=120,
            preview=preview,
            undo_handler=remove_document,
        )
    ]
