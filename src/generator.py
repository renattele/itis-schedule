"""Generate iCal (.ics) calendars from parsed lessons."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event

from .parser import Lesson

TZ = ZoneInfo("Europe/Moscow")

# Public holidays that fall on a weekday during the fall 2026 semester.
_HOLIDAYS = {
    date(2026, 11, 4),  # День народного единства
}


def _uid(group: str, lesson: Lesson) -> str:
    """Generate a deterministic UID for an event."""
    raw = (
        f"{group}|{lesson.day}|{lesson.time_start}|{lesson.time_end}|"
        f"{lesson.subject}|{lesson.instructor}|{lesson.room}|{lesson.weeks}|{lesson.start_from}"
    )
    return hashlib.sha1(raw.encode()).hexdigest() + "@itis-schedule"


def _first_weekday(start: date, target_weekday: int) -> date:
    """Find the first date >= *start* that falls on *target_weekday*."""
    days_ahead = (target_weekday - start.weekday()) % 7
    return start + timedelta(days=days_ahead)


def _week_number(semester_start: date, day: date) -> int:
    """1-based academic week number. Week 1 is the week containing semester_start."""
    sem_monday = semester_start - timedelta(days=semester_start.weekday())
    day_monday = day - timedelta(days=day.weekday())
    return ((day_monday - sem_monday).days // 7) + 1


def _parse_weeks_spec(spec: str) -> str | set[int]:
    if spec in ("all", "even", "odd", "", None):
        return spec or "all"
    m = re.fullmatch(r"(\d{1,2})-(\d{1,2})", spec)
    if m:
        start, end = int(m.group(1)), int(m.group(2))
        return set(range(start, end + 1))
    return "all"


def _resolve_start_from(semester_start: date, start_from: str) -> date | None:
    if not start_from:
        return None
    try:
        month, day = map(int, start_from.split("-"))
    except ValueError:
        return None
    year = semester_start.year
    try:
        resolved = date(year, month, day)
    except ValueError:
        return None
    # Spring dates in a fall-start semester belong to the next calendar year.
    if resolved < semester_start and month < 8:
        resolved = date(year + 1, month, day)
    return resolved


def _occurrence_dates(
    lesson: Lesson,
    semester_start: date,
    semester_end: date,
) -> list[date]:
    """List of dates on which *lesson* actually happens."""
    first = _first_weekday(semester_start, lesson.day)
    start_from = _resolve_start_from(semester_start, lesson.start_from)
    if start_from:
        first = max(first, _first_weekday(start_from, lesson.day))

    weeks_spec = _parse_weeks_spec(lesson.weeks)
    dates: list[date] = []
    current = first
    while current <= semester_end:
        if current >= semester_start and current not in _HOLIDAYS:
            week_num = _week_number(semester_start, current)
            include = False
            if weeks_spec == "all":
                include = True
            elif weeks_spec == "odd":
                include = week_num % 2 == 1
            elif weeks_spec == "even":
                include = week_num % 2 == 0
            elif isinstance(weeks_spec, set):
                include = week_num in weeks_spec
            if include:
                dates.append(current)
        current += timedelta(days=7)
    return dates


def generate_ical(
    group_id: str,
    lessons: list[Lesson],
    semester_start: date,
    semester_end: date,
    include_type: bool = True,
) -> bytes:
    """Create an iCal calendar for one group.

    Each lesson becomes a weekly-recurring VEVENT spanning the semester.

    Args:
        group_id: e.g. "11-501".
        lessons: Parsed lesson list.
        semester_start: First day of the semester.
        semester_end: Last day of the semester.
        include_type: Whether to prepend [Type] to the summary.

    Returns:
        Serialised iCal bytes (UTF-8).
    """
    cal = Calendar()
    cal.add("prodid", "-//ITIS Schedule Generator//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", group_id)
    cal.add("x-wr-timezone", "Europe/Moscow")
    now = datetime.now(timezone.utc)

    for lesson in lessons:
        h_start, m_start = map(int, lesson.time_start.split(":"))
        h_end, m_end = map(int, lesson.time_end.split(":"))

        occ_dates = _occurrence_dates(lesson, semester_start, semester_end)
        if not occ_dates:
            continue

        first_date = occ_dates[0]
        last_date = occ_dates[-1]

        dt_start = datetime.combine(
            first_date, time(h_start, m_start, 0), tzinfo=TZ
        )
        dt_end = datetime.combine(
            first_date, time(h_end, m_end, 0), tzinfo=TZ
        )

        event = Event()
        event.add("uid", _uid(group_id, lesson))
        event.add("dtstamp", now)
        event.add("dtstart", dt_start)
        event.add("dtend", dt_end)
        summary = lesson.subject
        if include_type and lesson.type:
            summary = f"[{lesson.type}] {summary}"

        event.add("summary", summary)

        desc_parts: list[str] = []
        if lesson.notes:
            desc_parts.append(lesson.notes)
        elif lesson.instructor:
            desc_parts.append(f"Преподаватель: {lesson.instructor}")
        if lesson.link:
            event.add("url", lesson.link)
            desc_parts.append(lesson.link)

        if desc_parts:
            event.add("description", "\n".join(desc_parts))

        # Room stays in LOCATION so in-person classes keep an auditorium even
        # when a webinar URL is also present. URL-only webinars use LOCATION
        # as a fallback so calendar apps still show a clickable place.
        if lesson.room:
            event.add("location", lesson.room)
        elif lesson.link:
            event.add("location", lesson.link)

        if len(occ_dates) > 1:
            skipped = []
            expected = first_date
            while expected <= last_date:
                if expected not in occ_dates:
                    skipped.append(expected)
                expected += timedelta(days=7)

            rrule = {
                "freq": "weekly",
                # UNTIL must be UTC when DTSTART is timezone-aware (RFC 5545).
                "until": datetime.combine(
                    last_date, time(23, 59, 59), tzinfo=TZ
                ).astimezone(timezone.utc),
            }
            event.add("rrule", rrule)
            for skip in skipped:
                event.add(
                    "exdate",
                    datetime.combine(skip, time(h_start, m_start, 0), tzinfo=TZ),
                )

        cal.add_component(event)

    return cal.to_ical()
