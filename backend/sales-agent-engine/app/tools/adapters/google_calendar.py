"""Google Calendar reads over Composio."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pydantic import Field

from app.core.clock import utcnow
from app.platform.composio_client import ConnectorClient
from app.tools.adapters.common import (
    as_dict,
    as_list,
    as_utc,
    clip,
    connection_required,
    plural,
    run_connector,
    utc_rfc3339,
)
from app.tools.registry import ToolDefinition
from app.tools.types import ToolCategory, ToolInput, ToolInputError, ToolInvocation, ToolKind, ToolOutput, ToolScope

_DEFAULT_WINDOW = timedelta(days=14)


class ListCalendarEventsArgs(ToolInput):
    start: datetime | None = Field(default=None, description="Only events ending after this time (ISO 8601). Default: now")
    end: datetime | None = Field(default=None, description="Only events starting before this time. Default: start + 14 days")
    query: str | None = Field(default=None, max_length=200, description="Free-text filter: title, description, attendees")
    max_results: int = Field(default=20, ge=1, le=50)


def calendar_tools(connector: ConnectorClient) -> list[ToolDefinition]:
    async def list_calendar_events(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, ListCalendarEventsArgs)
        start = as_utc(args.start) if args.start else utcnow()
        end = as_utc(args.end) if args.end else start + _DEFAULT_WINDOW
        if end <= start:
            raise ToolInputError("end must be after start")
        arguments: dict[str, Any] = {
            "calendarId": "primary",
            "timeMin": utc_rfc3339(start),
            "timeMax": utc_rfc3339(end),
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": args.max_results,
        }
        if args.query:
            arguments["q"] = args.query
        data = await run_connector(
            connector, user_id=invocation.ctx.user_id, slug="GOOGLECALENDAR_EVENTS_LIST", arguments=arguments
        )
        events = [_event(as_dict(item)) for item in as_list(data.get("items"))]
        return ToolOutput(
            data={"time_zone": data.get("timeZone"), "events": events},
            summary=f"{plural(len(events), 'calendar event')} between {arguments['timeMin'][:10]} and {arguments['timeMax'][:10]}",
        )

    return [
        ToolDefinition(
            name="list_calendar_events",
            description=(
                "List events on the user's primary Google Calendar in a time window (default: the next 14 days), "
                "optionally filtered by text such as a company or attendee name."
            ),
            kind=ToolKind.READ,
            scope=ToolScope.READ,
            category=ToolCategory.COMMUNICATION,
            input_model=ListCalendarEventsArgs,
            handler=list_calendar_events,
            timeout_seconds=45,
            acl=connection_required(connector, "googlecalendar", "Google Calendar"),
        )
    ]


def _event(event: dict[str, Any]) -> dict[str, Any]:
    start, end = as_dict(event.get("start")), as_dict(event.get("end"))
    attendees = [as_dict(item) for item in as_list(event.get("attendees"))]
    return {
        "title": event.get("summary") or "(no title)",
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "location": event.get("location"),
        "organizer": as_dict(event.get("organizer")).get("email"),
        "attendees": [
            {"email": a.get("email"), "name": a.get("displayName"), "response": a.get("responseStatus")}
            for a in attendees[:20]
        ],
        "description": clip(event.get("description"), 500),
        "link": event.get("htmlLink"),
    }
