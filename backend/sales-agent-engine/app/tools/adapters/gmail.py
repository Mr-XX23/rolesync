"""Gmail tools over Composio (connections owned by data-pipeline's connector flow)."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, StringConstraints

from app.platform.composio_client import ConnectorClient, ConnectorOutcomeUnknown
from app.tools.adapters.common import as_dict, as_list, clip, connection_required, plural, run_connector
from app.tools.registry import ToolDefinition
from app.tools.types import (
    SourceLink,
    ToolCategory,
    ToolInput,
    ToolInvocation,
    ToolKind,
    ToolOutcomeUnknown,
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


class SearchEmailsArgs(ToolInput):
    query: str = Field(
        min_length=1,
        max_length=500,
        description="Gmail search, e.g. 'from:jane@acme.com newer_than:90d' or 'subject:proposal acme'",
    )
    max_results: int = Field(default=10, ge=1, le=25)


class ReadEmailThreadArgs(ToolInput):
    thread_id: str = Field(min_length=1, max_length=100, description="thread_id from search_emails")


def gmail_tools(connector: ConnectorClient) -> list[ToolDefinition]:
    require_gmail = connection_required(connector, "gmail", "Gmail")

    async def send_email(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, SendEmailArgs)
        try:
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
        except ConnectorOutcomeUnknown as exc:
            raise ToolOutcomeUnknown(str(exc)) from exc
        message_id, thread_id = _message_ids(data)
        return ToolOutput(
            data={"message_id": message_id, "thread_id": thread_id, "to": args.to},
            summary=f"Email '{args.subject}' sent to {', '.join(args.to)}",
            ref_id=message_id,
        )

    async def search_emails(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, SearchEmailsArgs)
        data = await run_connector(
            connector,
            user_id=invocation.ctx.user_id,
            slug="GMAIL_FETCH_EMAILS",
            arguments={"query": args.query, "max_results": args.max_results, "user_id": "me"},
        )
        messages = sorted(
            (as_dict(item) for item in as_list(data.get("messages"))), key=lambda m: _timestamp(m), reverse=True
        )
        emails = [_email(message, text_limit=500) for message in messages]
        return ToolOutput(
            data={"emails": emails},
            summary=f"{plural(len(emails), 'email')} matching '{args.query}'",
            sources=_links(messages),
        )

    async def read_email_thread(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, ReadEmailThreadArgs)
        data = await run_connector(
            connector,
            user_id=invocation.ctx.user_id,
            slug="GMAIL_FETCH_MESSAGE_BY_THREAD_ID",
            arguments={"thread_id": args.thread_id, "user_id": "me"},
        )
        messages = sorted((as_dict(item) for item in as_list(data.get("messages"))), key=_timestamp)[-20:]
        emails = [_email(message, text_limit=3_000) for message in messages]
        subject = next((email["subject"] for email in emails if email["subject"]), "")
        return ToolOutput(
            data={"thread_id": args.thread_id, "emails": emails},
            summary=f"Thread '{subject or args.thread_id}': {plural(len(emails), 'message')}",
            sources=_links(messages[-1:]),
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
        ),
        ToolDefinition(
            name="search_emails",
            description=(
                "Search the user's Gmail (Gmail search syntax) for past conversations with a person or company. "
                "Returns sender, date, subject and a short extract, newest first."
            ),
            kind=ToolKind.READ,
            scope=ToolScope.READ,
            category=ToolCategory.COMMUNICATION,
            input_model=SearchEmailsArgs,
            handler=search_emails,
            timeout_seconds=45,
            acl=require_gmail,
        ),
        ToolDefinition(
            name="read_email_thread",
            description="Read the messages of one Gmail thread (from search_emails), oldest first.",
            kind=ToolKind.READ,
            scope=ToolScope.READ,
            category=ToolCategory.COMMUNICATION,
            input_model=ReadEmailThreadArgs,
            handler=read_email_thread,
            timeout_seconds=45,
            acl=require_gmail,
        ),
    ]


def _email(message: dict[str, Any], *, text_limit: int) -> dict[str, Any]:
    preview = as_dict(message.get("preview"))
    return {
        "message_id": message.get("messageId"),
        "thread_id": message.get("threadId"),
        "date": message.get("messageTimestamp"),
        "from": message.get("sender"),
        "to": message.get("to"),
        "subject": message.get("subject") or preview.get("subject") or "",
        "text": clip(message.get("messageText") or preview.get("body"), text_limit),
    }


def _timestamp(message: dict[str, Any]) -> tuple[int, float | str]:
    """Composio returns messages unsorted; timestamps may be epoch millis or ISO strings."""
    value = message.get("messageTimestamp") or message.get("internalDate") or ""
    try:
        return (1, float(value))
    except (TypeError, ValueError):
        return (0, str(value))


def _links(messages: list[dict[str, Any]]) -> tuple[SourceLink, ...]:
    return tuple(
        SourceLink(title=str(message.get("subject") or "email"), url=str(message["display_url"]))
        for message in messages[:5]
        if isinstance(message.get("display_url"), str) and message["display_url"].startswith("https://")
    )


def _message_ids(data: dict[str, Any]) -> tuple[str | None, str | None]:
    """Gmail's send response is ``{id, threadId, labelIds}``; Composio may nest it."""
    for candidate in (data, data.get("response_data"), data.get("data")):
        if isinstance(candidate, dict) and candidate.get("id"):
            return str(candidate["id"]), candidate.get("threadId") or candidate.get("thread_id")
    return None, None
