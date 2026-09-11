"""Google Calendar over Composio: read events, create an event (undo: delete it, which emails
attendees a cancellation)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, StringConstraints

from app.core.clock import utcnow
from app.core.context import AgentContext
from app.platform.composio_client import ConnectorClient
from app.tools.adapters.common import (
    as_dict,
    as_list,
    as_utc,
    clip,
    connection_required,
    first_dict,
    plural,
    run_connector,
    run_connector_undo,
    run_connector_write,
    utc_rfc3339,
)
from app.tools.registry import ToolDefinition
from app.tools.types import (
    SourceLink,
    ToolCategory,
    ToolFailed,
    ToolInput,
    ToolInputError,
    ToolInvocation,
    ToolKind,
    ToolOutput,
    ToolScope,
    UndoInvocation,
    UndoPlan,
)

_DEFAULT_WINDOW = timedelta(days=14)

EmailAddress = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=320)]


class ListCalendarEventsArgs(ToolInput):
    start: datetime | None = Field(default=None, description="Only events ending after this time (ISO 8601). Default: now")
    end: datetime | None = Field(default=None, description="Only events starting before this time. Default: start + 14 days")
    query: str | None = Field(default=None, max_length=200, description="Free-text filter: title, description, attendees")
    max_results: int = Field(default=20, ge=1, le=50)


class CreateCalendarEventArgs(ToolInput):
    title: str = Field(min_length=1, max_length=300)
    start: datetime = Field(description="Start, ISO 8601 (e.g. 2026-09-15T14:00:00). Without a UTC offset it is read in time_zone")
    end: datetime | None = Field(default=None, description="End; default: start + duration_minutes")
    duration_minutes: int = Field(default=30, ge=5, le=24 * 60)
    time_zone: str | None = Field(
        default=None, max_length=64, description="IANA time zone, e.g. 'America/New_York'. Required if start has no UTC offset"
    )
    attendees: list[EmailAddress] = Field(default_factory=list, max_length=50)
    description: str | None = Field(default=None, max_length=8000)
    location: str | None = Field(default=None, max_length=500)
    add_video_link: bool = Field(default=False, description="Add a Google Meet link")
    notify_attendees: bool = Field(default=True, description="Email the invitation to the attendees")


def _schedule(args: CreateCalendarEventArgs) -> tuple[datetime, datetime, str]:
    """(local start, local end, zone): wall-clock times in the event's time zone."""
    zone_name = args.time_zone or ("UTC" if args.start.tzinfo else None)
    if zone_name is None:
        raise ToolInputError("the start time has no UTC offset: give time_zone (for example 'Europe/London')")
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ToolInputError(f"'{zone_name}' is not a known IANA time zone") from exc

    def local(moment: datetime) -> datetime:
        return (moment.astimezone(zone) if moment.tzinfo else moment.replace(tzinfo=zone)).replace(tzinfo=None)

    start = local(args.start)
    end = local(args.end) if args.end else start + timedelta(minutes=args.duration_minutes)
    if end <= start:
        raise ToolInputError("the event must end after it starts")
    if end - start > timedelta(days=14):
        raise ToolInputError("the event can't be longer than 14 days")
    if start.replace(tzinfo=zone) < utcnow() - timedelta(days=1):
        raise ToolInputError("the start time is in the past")
    return start, end, zone_name


def calendar_tools(connector: ConnectorClient) -> list[ToolDefinition]:
    require_calendar = connection_required(connector, "googlecalendar", "Google Calendar")

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

    async def create_calendar_event(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, CreateCalendarEventArgs)
        start, end, zone = _schedule(args)
        notify = args.notify_attendees and bool(args.attendees)
        arguments: dict[str, Any] = {
            "calendar_id": "primary",
            "summary": args.title,
            "start_datetime": start.isoformat(timespec="seconds"),
            "end_datetime": end.isoformat(timespec="seconds"),
            "timezone": zone,
            "attendees": args.attendees,
            "create_meeting_room": args.add_video_link,
            "send_updates": "all" if notify else "none",
        }
        if args.description:
            arguments["description"] = args.description
        if args.location:
            arguments["location"] = args.location
        data = await run_connector_write(
            connector, user_id=invocation.ctx.user_id, slug="GOOGLECALENDAR_CREATE_EVENT", arguments=arguments
        )
        event = first_dict(data, "response_data", "event", "data")
        event_id = str(event.get("id") or "") or None
        link = event.get("htmlLink") if isinstance(event.get("htmlLink"), str) else None
        when = f"{start:%a %d %b %Y %H:%M}–{end:%H:%M} ({zone})"
        guests = f" with {', '.join(args.attendees)}" if args.attendees else ""
        return ToolOutput(
            data={
                "event_id": event_id,
                "title": args.title,
                "start": arguments["start_datetime"],
                "end": arguments["end_datetime"],
                "time_zone": zone,
                "attendees": args.attendees,
                "invitations_sent": notify,
                "link": link,
                "video_link": event.get("hangoutLink"),
            },
            summary=f"Calendar event '{args.title}' created for {when}{guests}",
            ref_id=event_id,
            sources=(SourceLink(title=args.title, url=link),) if link and link.startswith("https://") else (),
            undo=UndoPlan(
                args={"event_id": event_id, "notify": notify},
                label=f"Delete the calendar event '{args.title}'" + (" and email attendees a cancellation" if notify else ""),
            )
            if event_id
            else None,
        )

    async def delete_event(invocation: UndoInvocation) -> str:
        event_id = str(invocation.args["event_id"])
        try:
            await run_connector_undo(
                connector,
                user_id=invocation.ctx.user_id,
                slug="GOOGLECALENDAR_DELETE_EVENT",
                arguments={
                    "calendar_id": "primary",
                    "event_id": event_id,
                    "send_updates": "all" if invocation.args.get("notify") else "none",
                },
            )
        except ToolFailed as exc:
            text = str(exc).lower()
            if not exc.retryable and ("404" in text or "410" in text or "not found" in text or "deleted" in text):
                return f"calendar event {event_id} was already deleted"
            raise
        return f"calendar event {event_id} deleted"

    async def create_preview(ctx: AgentContext, args: ToolInput) -> dict[str, Any]:
        assert isinstance(args, CreateCalendarEventArgs)
        start, end, zone = _schedule(args)
        return {
            "kind": "calendar_event",
            "title": args.title,
            "start": start.isoformat(timespec="minutes"),
            "end": end.isoformat(timespec="minutes"),
            "time_zone": zone,
            "attendees": args.attendees,
            "location": args.location,
            "description": args.description,
            "video_link": args.add_video_link,
            "notify_attendees": args.notify_attendees and bool(args.attendees),
        }

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
            acl=require_calendar,
        ),
        ToolDefinition(
            name="create_calendar_event",
            description=(
                "Create an event on the rep's primary Google Calendar and (by default) email invitations to the "
                "attendees. Give the start with a UTC offset or a time_zone. The rep approves it first."
            ),
            kind=ToolKind.WRITE,
            scope=ToolScope.COMMUNICATION,
            category=ToolCategory.COMMUNICATION,
            input_model=CreateCalendarEventArgs,
            handler=create_calendar_event,
            timeout_seconds=60,
            acl=require_calendar,
            preview=create_preview,
            undo_handler=delete_event,
        ),
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
