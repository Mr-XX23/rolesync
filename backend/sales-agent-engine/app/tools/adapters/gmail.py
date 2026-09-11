"""Gmail tools over Composio (connections owned by data-pipeline's connector flow)."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, StringConstraints

from app.core.context import AgentContext
from app.platform.composio_client import ConnectorClient
from app.tools.registry import ToolDefinition
from app.tools.types import (
    ToolAccessDenied,
    ToolCategory,
    ToolInput,
    ToolInvocation,
    ToolKind,
    ToolOutput,
    ToolScope,
)

EmailAddress = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=320)]


class SendEmailArgs(ToolInput):
    to: list[EmailAddress] = Field(min_length=1, max_length=20, description="Recipient email addresses")
    cc: list[EmailAddress] = Field(default_factory=list, max_length=20)
    bcc: list[EmailAddress] = Field(default_factory=list, max_length=20)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20_000, description="Complete, ready-to-send email body")
    is_html: bool = Field(default=False, description="True only if body is HTML")


def gmail_tools(connector: ConnectorClient) -> list[ToolDefinition]:
    async def require_gmail(ctx: AgentContext, args: ToolInput) -> None:
        if not await connector.has_active_connection(ctx.user_id, "gmail"):
            raise ToolAccessDenied("Gmail is not connected for this user; connect it under Connectors first")

    async def send_email(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, SendEmailArgs)
        data = await connector.execute(
            user_id=invocation.ctx.user_id,
            slug="GMAIL_SEND_EMAIL",
            arguments={
                "recipient_email": args.to[0],
                "extra_recipients": args.to[1:],
                "cc": args.cc,
                "bcc": args.bcc,
                "subject": args.subject,
                "body": args.body,
                "is_html": args.is_html,
                "user_id": "me",
            },
        )
        message_id, thread_id = _message_ids(data)
        return ToolOutput(
            data={"message_id": message_id, "thread_id": thread_id, "to": args.to},
            summary=f"Email '{args.subject}' sent to {', '.join(args.to)}",
            ref_id=message_id,
        )

    return [
        ToolDefinition(
            name="send_email",
            description=(
                "Send an email from the user's connected Gmail account. The user reviews and approves the "
                "exact message before it is sent, so provide complete, final content."
            ),
            kind=ToolKind.WRITE,
            scope=ToolScope.COMMUNICATION,
            category=ToolCategory.COMMUNICATION,
            input_model=SendEmailArgs,
            handler=send_email,
            irreversible=True,  # a sent email cannot be recalled, so there is no undo action
            timeout_seconds=60,
            acl=require_gmail,
            preview=lambda args: {
                "kind": "email",
                "to": args.to,
                "cc": args.cc,
                "bcc": args.bcc,
                "subject": args.subject,
                "body": args.body,
                "is_html": args.is_html,
            },
        )
    ]


def _message_ids(data: dict[str, Any]) -> tuple[str | None, str | None]:
    """Gmail's send response is ``{id, threadId, labelIds}``; Composio may nest it."""
    for candidate in (data, data.get("response_data"), data.get("data")):
        if isinstance(candidate, dict) and candidate.get("id"):
            return str(candidate["id"]), candidate.get("threadId") or candidate.get("thread_id")
    return None, None
